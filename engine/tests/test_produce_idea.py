"""B1: "Create package" makes exactly the selected idea, and only that package is planned and reviewed."""

import threading
import uuid
from pathlib import Path

import pytest

from studio import config, db, maintenance, produce
from studio.errors import TransientError
from studio.research import engine as research
from studio.review import auto
from studio.review.auto import PolicyReview
from studio.script import pipeline
from studio.storage import LocalStorage

from .fakes import ScriptedRouter, fake_sources
from .test_end_to_end import silent_tts  # noqa: F401  (fixture)


def setup_ideas(conn, monkeypatch, n=2, channel="money"):
    router = ScriptedRouter(monkeypatch)
    week = research.week_start()
    fake_sources(conn, channel)
    research.run_ideas(conn, router, channel, n, week)
    ideas = db.all_(conn, "select * from content_ideas where channel_slug=%s order by score desc", (channel,))
    storage = LocalStorage(Path(config.runtime().work_dir) / "storage")
    return router, storage, ideas


def counts(conn):
    return db.one(conn, """select (select count(*) from content_projects where parent_project_id is null) longs,
                                  (select count(*) from content_variants) variants,
                                  (select count(*) from scheduled_posts) posts,
                                  (select count(*) from script_versions) scripts""")


def test_makes_exactly_the_selected_idea_and_plans_only_its_posts(synced, monkeypatch, silent_tts):
    c = synced
    router, storage, ideas = setup_ideas(c, monkeypatch, n=2)
    assert len(ideas) >= 2
    chosen, other = ideas[1], ideas[0]                       # not the top one, to prove it's the selection
    out = produce.produce_idea(c, router, storage, content_idea_id=chosen["id"])
    assert out["status"] == "ready_for_review" and out["posts_planned"] > 0
    longs = db.all_(c, "select id, idea_id from content_projects where parent_project_id is null")
    assert [str(r["idea_id"]) for r in longs] == [str(chosen["id"])]
    assert db.one(c, "select status from content_ideas where id=%s", (other["id"],))["status"] != "produced"
    posts = db.all_(c, """select sp.status, v.project_id from scheduled_posts sp join content_variants v on v.id=sp.variant_id""")
    family = {r["id"] for r in db.all_(c, "select id from content_projects where id=%s or parent_project_id=%s",
                                         (out["project_id"], out["project_id"]))}
    assert posts and all(p["project_id"] in family for p in posts)
    assert {p["status"] for p in posts} == {"pending_approval"}            # still waits for approval


def test_other_projects_of_the_same_week_are_never_planned_or_approved(synced, monkeypatch, silent_tts):
    c = synced
    router, storage, ideas = setup_ideas(c, monkeypatch, n=2)
    first = produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])
    # make the first package look unplanned, as if it came from a batch that hasn't planned yet
    db.run(c, "delete from content_variants where project_id in (select id from content_projects where id=%s or parent_project_id=%s)",
           (first["project_id"], first["project_id"]))
    db.run(c, "insert into settings (key, value) values ('auto_review_post', 'true') on conflict (key) do update set value='true'")
    monkeypatch.setattr(auto, "ai_review", lambda r, f, v, conn: (PolicyReview(publishable=True, confidence=0.97, summary="ok"), "beta/b1"))
    # the sample ideas produce near-identical scripts and have no trust history: those rules have their own tests
    monkeypatch.setattr(produce, "repeats_earlier", lambda *a: None)
    monkeypatch.setattr(auto, "risk_reasons", lambda conn, family: [])
    second = produce.produce_idea(c, router, storage, content_idea_id=ideas[1]["id"])
    assert db.one(c, "select count(*) n from content_variants where project_id=%s", (first["project_id"],))["n"] == 0
    assert db.one(c, "select status from content_projects where id=%s", (first["project_id"],))["status"] == "ready_for_review"
    assert db.one(c, "select status from content_projects where id=%s", (second["project_id"],))["status"] == "approved"
    assert {r["project"] for r in second["auto_review"]} == {second["project_id"]}


def test_a_generated_idea_keeps_its_sources_and_is_converted_once(synced, monkeypatch, silent_tts):
    c = synced
    router = ScriptedRouter(monkeypatch)
    srcs = fake_sources(c, "money")
    run = db.one(c, "insert into idea_runs (trigger, config, requested_count) values ('manual','{}',1) returning id")
    signals = [{"source_id": str(srcs[2]), "title": "a"}, {"source_id": str(srcs[0]), "title": "b"},
               {"source_id": str(uuid.uuid4()), "title": "gone"}, {"source_id": str(srcs[1]), "title": "c"}]
    g = db.one(c, """insert into generated_ideas (run_id, rank, title, summary, audience, channel_slug, trend_signals, total,
                                                  score_explanation, confidence, fingerprint)
                     values (%s, 1, 'Budget data point', 'What the savings rate means for you', 'savers', 'money', %s, 72,
                             'measured', 'high', 'fp-1') returning id""", (run["id"], db.j(signals)))
    storage = LocalStorage(Path(config.runtime().work_dir) / "storage")
    out = produce.produce_idea(c, router, storage, generated_idea_id=g["id"], channel="money")
    gi = db.one(c, "select content_idea_id, status from generated_ideas where id=%s", (g["id"],))
    ci = db.one(c, "select * from content_ideas where id=%s", (gi["content_idea_id"],))
    assert gi["status"] == "sent_to_studio"
    assert [str(x) for x in ci["source_ids"]] == [str(srcs[2]), str(srcs[0]), str(srcs[1])]  # stored ones, in order
    assert ci["score_breakdown"]["from_generated_idea"] == str(g["id"])
    assert db.one(c, "select idea_id from content_projects where id=%s", (out["project_id"],))["idea_id"] == ci["id"]
    claims = db.all_(c, "select source_id from research_claims where source_id is not null")
    assert claims and {r["source_id"] for r in claims} <= {srcs[2], srcs[0], srcs[1]}  # checked against its evidence
    before = counts(c)
    again = produce.produce_idea(c, router, storage, generated_idea_id=g["id"], channel="money")
    assert again["project_id"] == out["project_id"] and counts(c) == before        # pressing twice changes nothing
    assert db.one(c, "select count(*) n from content_ideas")["n"] == 1


def test_simultaneous_requests_get_one_research_idea(synced, db_url, monkeypatch):
    c = synced
    srcs = fake_sources(c, "ai")
    run = db.one(c, "insert into idea_runs (trigger, config, requested_count) values ('manual','{}',1) returning id")
    g = db.one(c, """insert into generated_ideas (run_id, rank, title, summary, audience, channel_slug, trend_signals, total,
                                                  score_explanation, confidence, fingerprint)
                     values (%s,1,'AI agents','x','y','both',%s,60,'m','medium','fp-2') returning id""",
               (run["id"], db.j([{"source_id": str(srcs[0])}])))
    got, errors = [], []

    def worker():
        conn = db.connect(db_url)
        try:
            got.append(str(produce.idea_for_production(conn, generated_idea_id=g["id"], channel="ai")["id"]))
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(got)) == 1
    assert db.one(c, "select count(*) n from content_ideas")["n"] == 1


def test_a_second_run_while_production_is_busy_is_refused(synced, db_url, monkeypatch, silent_tts):
    c = synced
    router, storage, ideas = setup_ideas(c, monkeypatch, n=1)
    other = db.connect(db_url)
    try:
        with db.run_lock(other, "production") as free:
            assert free
            with pytest.raises(RuntimeError, match="Another production run"):
                produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])
    finally:
        other.close()
    assert counts(c)["longs"] == 0


def test_bad_requests_are_explained(synced, monkeypatch):
    c = synced
    run = db.one(c, "insert into idea_runs (trigger, config, requested_count) values ('manual','{}',1) returning id")
    g = db.one(c, """insert into generated_ideas (run_id, rank, title, summary, audience, channel_slug, trend_signals, total,
                                                  score_explanation, confidence, fingerprint)
                     values (%s,1,'No evidence','x','y','both','[]',10,'m','unverified','fp-3') returning id""", (run["id"],))
    with pytest.raises(ValueError, match="Choose Pixel or Penny"):
        produce.idea_for_production(c, generated_idea_id=g["id"])
    with pytest.raises(ValueError, match="no stored sources"):
        produce.idea_for_production(c, generated_idea_id=g["id"], channel="ai")
    with pytest.raises(ValueError, match="Choose an idea"):
        produce.idea_for_production(c)


def test_resumes_from_the_failed_step_without_duplicating_anything(synced, monkeypatch, silent_tts):
    c = synced
    router, storage, ideas = setup_ideas(c, monkeypatch, n=1)
    real = pipeline.make_package
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientError("every writer is busy")
        return real(*a, **k)

    monkeypatch.setattr(pipeline, "make_package", flaky)
    with pytest.raises(RuntimeError, match="busy"):
        produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])
    head = db.one(c, "select id, status from content_projects where parent_project_id is null")
    assert head["status"] == "failed"
    assert db.one(c, "select count(*) n from script_versions")["n"] == 1                    # the script stage finished
    out = produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])          # Try again from this step
    assert out["project_id"] == str(head["id"]) and out["status"] == "ready_for_review"
    after = counts(c)
    assert after["longs"] == 1 and after["scripts"] == 1 + db.one(c, "select count(*) n from content_projects where parent_project_id is not null")["n"]
    assert after["posts"] == after["variants"] > 0
    produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])                # and once more
    assert counts(c) == after


def test_publishing_pause_does_not_stop_creating(synced, monkeypatch, silent_tts):
    c = synced
    db.run(c, "insert into settings (key, value) values ('paused', 'true') on conflict (key) do update set value='true'")
    router, storage, ideas = setup_ideas(c, monkeypatch, n=1)
    out = produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])
    assert out["status"] == "ready_for_review"
    assert {r["status"] for r in db.all_(c, "select status from scheduled_posts")} == {"pending_approval"}
    assert db.get_setting(c, "paused") is True                                              # pause itself unchanged


def test_the_weekly_batch_never_remakes_an_idea_that_has_a_package(synced, monkeypatch, silent_tts):
    c = synced
    router, storage, ideas = setup_ideas(c, monkeypatch, n=1)
    db.run(c, "update content_ideas set status='shortlisted'")
    first = produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])
    db.run(c, "update content_ideas set status='shortlisted'")        # even if it's still shortlisted
    monkeypatch.setattr("studio.capacity.plan_batch", lambda conn, today=None: {"long_per_channel": {"ai": 0, "money": 1}})
    produce.produce_batch(c, router, storage, research.week_start())
    same = db.all_(c, "select id from content_projects where parent_project_id is null and idea_id=%s", (ideas[0]["id"],))
    assert [str(r["id"]) for r in same] == [first["project_id"]]         # other shortlisted ideas may be made; this one isn't remade


def test_owner_job_runs_it_and_links_the_project(synced, monkeypatch, silent_tts):
    c = synced
    router, storage, ideas = setup_ideas(c, monkeypatch, n=1)
    db.run(c, """insert into generation_jobs (job_type, idempotency_key, status, requested_by, input)
                 values ('produce_idea', 'owner:produce_idea:1', 'queued', 'owner', %s)""",
           (db.j({"content_idea_id": str(ideas[0]["id"]), "channel": "money"}),))
    done = maintenance.process_owner_jobs(c, router, storage)
    assert [d["status"] for d in done] == ["completed"]
    job = db.one(c, "select project_id, output, progress from generation_jobs where idempotency_key='owner:produce_idea:1'")
    assert job["project_id"] is not None and job["output"]["status"] == "ready_for_review" and job["progress"] is None


def test_test_again_reruns_the_key_check(synced, monkeypatch):
    c = synced
    seen = {}

    def fake_check(conn, only=None):
        seen["conn"], seen["only"] = conn, only
        return [{"provider": "groq", "status": "ok"}, {"provider": "gemini", "status": "failed"}]

    monkeypatch.setattr("studio.cli.run_provider_check", fake_check)
    db.run(c, """insert into generation_jobs (job_type, idempotency_key, status, requested_by)
                 values ('check_providers', 'owner:check:1', 'queued', 'owner')""")
    done = maintenance.process_owner_jobs(c, router=None, storage=None)
    assert done[0]["status"] == "completed" and seen["conn"] is c and seen["only"] is None
    # Test on one service checks only that service
    db.run(c, """insert into generation_jobs (job_type, idempotency_key, status, requested_by, input)
                 values ('check_providers', 'owner:check:2', 'queued', 'owner', '{"provider": "ollama"}')""")
    maintenance.process_owner_jobs(c, router=None, storage=None)
    assert seen["only"] == "ollama"
    assert db.one(c, "select output from generation_jobs where idempotency_key='owner:check:1'")["output"] == {"ok": 1, "checked": 2}


def test_cancelled_stage_resumes_without_remaking_completed_script(synced,monkeypatch,silent_tts):
    from studio import jobs
    c=synced
    router,storage,ideas=setup_ideas(c,monkeypatch,n=1)
    real=pipeline.make_package
    calls={'n':0}
    def cancelled_once(*args,**kwargs):
        calls['n']+=1
        if calls['n']==1:raise jobs.JobCancelled('Owner cancelled the package stage')
        return real(*args,**kwargs)
    monkeypatch.setattr(pipeline,'make_package',cancelled_once)
    with pytest.raises(jobs.JobCancelled):produce.produce_idea(c,router,storage,content_idea_id=ideas[0]['id'])
    assert db.one(c,'select count(*) n from script_versions')['n']==1
    out=produce.produce_idea(c,router,storage,content_idea_id=ideas[0]['id'])
    assert out['status']=='ready_for_review'
    assert db.one(c,"select count(*) n from content_projects where parent_project_id is null")['n']==1
    assert db.one(c,"select attempts from generation_jobs where job_type='script'")['attempts']==1
