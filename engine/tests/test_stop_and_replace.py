"""Stop & clear (one button under Running now) and the automatic replacement of packages left waiting for the owner."""

from datetime import datetime, timedelta, timezone

import pytest

from studio import db, jobs, produce
from studio.review import auto, replace

from .fakes import ScriptedRouter
from .test_end_to_end import _approve_all, _connect_all, produced, silent_tts  # noqa: F401


def _counts(conn):
    return db.one(conn, """select (select count(*) from content_projects where parent_project_id is null) packages,
                                  (select count(*) from content_ideas) ideas,
                                  (select count(*) from generation_jobs where status in ('queued','running')) running""")


# ----------------------------------------------------------------------------- Stop & clear

def test_stop_and_clear_erases_what_the_running_work_made_and_keeps_everything_else(produced):
    conn, _ = produced
    ai = db.one(conn, "select * from content_projects where channel_slug='ai' and parent_project_id is null")
    money = db.one(conn, "select * from content_projects where channel_slug='money' and parent_project_id is null")
    db.run(conn, "update content_projects set status='approved' where id=%s", (money["id"],))  # the owner decided on this one
    # a package job is busy re-making the Pixel video, and an idea run started a minute ago
    db.run(conn, """insert into generation_jobs (job_type, idempotency_key, status, requested_by, project_id, started_at)
                    values ('produce_idea','busy','running','owner',%s, now())""", (ai["id"],))
    late = db.one(conn, """insert into content_ideas (channel_slug, title, status, batch_week, source_ids)
                           values ('ai','Made by the stopped run','shortlisted', current_date, '{}') returning id""")["id"]
    files = db.one(conn, "select count(*) n from media_assets where storage_path is not null and project_id in "
                         "(select id from content_projects where id=%s or parent_project_id=%s)", (ai["id"], ai["id"]))["n"]
    out = db.one(conn, "select public.stop_and_clear() r")["r"]
    assert out["stopped"] is True and out["jobs_stopped"] == 1 and out["packages"] == 1
    assert len(out["storage_paths"]) == files > 0  # the Worker removes these files
    assert not db.one(conn, "select 1 x from content_projects where id=%s", (ai["id"],))      # the busy package is gone
    assert db.one(conn, "select status from content_projects where id=%s", (money["id"],))["status"] == "approved"
    assert not db.one(conn, "select 1 x from content_ideas where id=%s", (late,))            # so is what it started from
    assert _counts(conn)["running"] == 0
    assert db.get_setting(conn, "stop_requested_at")
    log = db.one(conn, "select actor, details from audit_logs where action='stop_and_clear'")
    assert log["details"]["packages"] == 1
    assert db.all_(conn, "select * from audit_chain_problems()") == []
    # pressing it again with nothing running changes nothing
    assert db.one(conn, "select public.stop_and_clear() r")["r"] == {"stopped": False, "reason": "nothing is running"}


def test_published_work_is_never_erased(produced):
    conn, storage = produced
    from studio.publish import runner

    from .test_end_to_end import Platform, _adapters
    _connect_all(conn)
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")
    db.run(conn, "update scheduled_posts set status='scheduled'")
    post = db.one(conn, "select * from scheduled_posts where status='scheduled' order by scheduled_at limit 1")
    assert runner.publish_post(conn, storage, post, _adapters(Platform()),
                               now=datetime.now(timezone.utc) + timedelta(days=30)) in ("published", "published_needs_followup")
    pid = db.one(conn, """select coalesce(p.parent_project_id, p.id) id from scheduled_posts sp join content_variants v on v.id=sp.variant_id
                          join content_projects p on p.id=v.project_id where sp.id=%s""", (post["id"],))["id"]
    with pytest.raises(Exception, match="published posts can't be erased"):
        db.one(conn, "select public.erase_projects(array[%s]::uuid[])", (pid,))
    conn.rollback() if not conn.autocommit else None
    db.run(conn, """insert into generation_jobs (job_type, idempotency_key, status, requested_by, project_id)
                    values ('produce_idea','busy2','queued','owner',%s)""", (pid,))
    db.one(conn, "select public.stop_and_clear()")
    assert db.one(conn, "select 1 x from content_projects where id=%s", (pid,))
    assert db.one(conn, "select count(*) n from published_posts")["n"] == 1


def test_a_running_engine_stops_at_its_next_step(synced):
    conn = synced
    jobs._process_started = None
    jobs.check_stop(conn)  # the run starts
    jobs.progress(conn, "working")  # no stop asked: carries on
    db.run(conn, "insert into settings (key, value) values ('stop_requested_at', to_jsonb(now() + interval '1 second'))")
    with pytest.raises(jobs.Stopped):
        jobs.progress(conn, "still working")
    with pytest.raises(jobs.Stopped):
        jobs.run_stage(conn, "script", "k1", lambda _: {})
    jobs._process_started = None  # a run that starts after the stop works normally
    db.run(conn, "update settings set value = to_jsonb(now() - interval '1 minute') where key='stop_requested_at'")
    jobs.check_stop(conn)
    jobs.progress(conn, "fresh run")
    jobs._process_started = None


# ----------------------------------------------------------------------------- held packages

def _hold(conn, project_id, hours_ago: float, reasons: str):
    db.run(conn, "update content_projects set status='needs_attention' where id=%s", (project_id,))
    db.run(conn, """insert into auto_reviews (project_id, verdict, checks, reasons, created_at)
                    values (%s, 'needs_review', %s, %s, now() - make_interval(secs => %s))""",
           (project_id, db.j([{"code": "quality_gates", "ok": True}, {"code": "smart_mode", "ok": False, "detail": reasons}]),
            db.j([reasons]), hours_ago * 3600))


def _safe_idea(conn, channel="ai", title="How to compare AI note-takers", evergreen=True, sensitivity="none"):
    src = db.one(conn, "select id from research_sources limit 1")["id"]
    run = db.one(conn, "insert into idea_runs (trigger, config, requested_count) values ('manual','{}',1) returning id")
    return db.one(conn, """insert into generated_ideas (run_id, rank, title, summary, audience, channel_slug, trend_signals,
                                                        scores, total, score_explanation, confidence, sensitivity, fingerprint)
                           values (%s,1,%s,'A lasting how-to','workers',%s,%s,%s,70,'ok','high',%s,%s) returning *""",
                  (run["id"], title, channel, db.j([{"source_id": str(src)}]), db.j({"evergreen": evergreen}), sensitivity,
                   f"fp-{title}"))


@pytest.fixture
def held(produced, monkeypatch):
    conn, storage = produced
    db.set_setting(conn, "auto_review_post", True)
    p = db.one(conn, "select * from content_projects where channel_slug='ai' and parent_project_id is null")
    made = []

    def fake_produce(c, router, storage, *, generated_idea_id=None, channel=None, content_idea_id=None):
        new = db.one(c, """insert into content_projects (channel_slug, format, title, status, batch_week)
                           values (%s,'long','The safer video','approved', current_date) returning id""", (channel,))
        made.append(generated_idea_id)
        return {"project_id": str(new["id"]), "status": "approved"}
    monkeypatch.setattr(produce, "produce_idea", fake_produce)
    sent = []
    monkeypatch.setattr(replace.notify, "send", lambda c, kind, title, body="", **kw: sent.append((kind, title, body)) or True)
    return conn, storage, p, made, sent


def test_a_reminder_first_then_a_safer_replacement(held, monkeypatch):
    conn, storage, p, made, sent = held
    idea = _safe_idea(conn)
    _safe_idea(conn, title="Breaking: new model launched", evergreen=False)       # news: never picked
    _safe_idea(conn, title="Should you trust AI doctors?", sensitivity="sensitive")  # sensitive: never picked
    _hold(conn, p["id"], 13, "Time-sensitive (news): a person checks it before it goes out")
    out = replace.tick(conn, ScriptedRouter(monkeypatch), storage)
    assert out["reminded"] == 1 and out["replaced"] == [] and sent[0][0] == "held_reminder"
    assert "erases it and makes a safer video" in sent[0][2]
    assert db.get_setting(conn, "auto_replace_next_at")  # the Worker wakes the engine when the replacement is due
    assert db.one(conn, "select status from content_projects where id=%s", (p["id"],))["status"] == "needs_attention"

    db.run(conn, "update auto_reviews set created_at = now() - interval '25 hours' where project_id=%s", (p["id"],))
    out = replace.tick(conn, ScriptedRouter(monkeypatch), storage)
    assert [r["outcome"] for r in out["replaced"]] == ["replaced"]
    assert made == [idea["id"]]                                    # the evergreen, non-sensitive idea
    assert not db.one(conn, "select 1 x from content_projects where id=%s", (p["id"],))  # erased after the new one exists
    assert sent[-1][0] == "auto_replace" and "safer video" in sent[-1][2]
    rec = db.one(conn, "select * from auto_replacements")
    assert rec["outcome"] == "replaced" and rec["new_title"] == idea["title"]
    assert db.one(conn, "select 1 x from audit_logs where action='auto_replaced'")


def test_nothing_is_erased_without_a_replacement(held, monkeypatch):
    conn, storage, p, made, sent = held
    _hold(conn, p["id"], 30, "Time-sensitive (news): a person checks it before it goes out")
    monkeypatch.setattr(replace, "_new_ideas", lambda *a: None)  # no safe idea can be found
    out = replace.tick(conn, ScriptedRouter(monkeypatch), storage)
    assert out["replaced"][0]["outcome"] == "failed"
    assert db.one(conn, "select 1 x from content_projects where id=%s", (p["id"],))
    _safe_idea(conn)

    def broken(*a, **k):
        raise RuntimeError("render failed")
    monkeypatch.setattr(produce, "produce_idea", broken)
    out = replace.tick(conn, ScriptedRouter(monkeypatch), storage)
    assert out["replaced"][0]["outcome"] == "failed"
    assert db.one(conn, "select 1 x from content_projects where id=%s", (p["id"],))  # the original keeps waiting


def test_trust_period_quality_problems_and_the_weekly_limit_always_wait(held, monkeypatch):
    conn, storage, p, made, sent = held
    _safe_idea(conn)
    _hold(conn, p["id"], 30, "Trust period: you approve this channel's first 5 packages yourself (0 so far)")
    replace.tick(conn, ScriptedRouter(monkeypatch), storage)
    assert made == [] and "trust period" in sent[0][2]  # reminded, never replaced: a new one would wait the same way
    # a quality problem is for a person, whatever the time
    db.run(conn, "delete from auto_reviews")
    db.run(conn, """insert into auto_reviews (project_id, verdict, checks, created_at) values (%s,'needs_review',%s, now() - interval '30 hours')""",
           (p["id"], db.j([{"code": "claims", "ok": False}, {"code": "smart_mode", "ok": False, "detail": "Time-sensitive (news)"}])))
    assert replace.held_for_risk(conn) == []
    # the weekly limit
    db.run(conn, "delete from auto_reviews")
    _hold(conn, p["id"], 30, "Time-sensitive (news): a person checks it before it goes out")
    db.set_setting(conn, "auto_replace", {"max_per_week": 0})
    replace.tick(conn, ScriptedRouter(monkeypatch), storage)
    assert made == [] and any("limit" in t for _, t, _ in sent)
    # switched off, or Auto Review & Post off: nothing at all
    db.set_setting(conn, "auto_replace", {"enabled": False, "max_per_week": 2})
    assert replace.tick(conn, ScriptedRouter(monkeypatch), storage)["skipped"]
    db.set_setting(conn, "auto_replace", {"enabled": True})
    db.set_setting(conn, "auto_review_post", False)
    assert replace.tick(conn, ScriptedRouter(monkeypatch), storage)["skipped"]
    assert made == []


def test_a_money_idea_with_sensitive_words_is_never_the_replacement(held, monkeypatch):
    conn, storage, p, made, sent = held
    _safe_idea(conn, channel="money", title="Should you refinance your mortgage?")
    ok = _safe_idea(conn, channel="money", title="A weekly budget that survives real life")
    assert replace.safe_idea(conn, "money", set())["id"] == ok["id"]


def test_ideas_say_whether_they_are_evergreen(synced, monkeypatch):
    from studio.ideas import generator

    assert generator.Assessment(id="I1", originality=5, international=5, feasibility=5, engagement=5,
                                rationale="ok").evergreen is False  # unknown means news: a person checks it
    assert "evergreen" in generator.Assessment.model_fields
