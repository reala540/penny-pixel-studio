"""Shorts that fail their checks: the package retries once, the owner can ask for new Shorts later from the same
checked facts, and nothing that already exists (script, main video, platform posts) is changed or posted twice."""

import uuid

import pytest

from studio import db, produce
from studio.script import quality

from .test_database import as_user, reset_role
from .test_end_to_end import silent_tts  # noqa: F401  (fixture)
from .test_produce_idea import setup_ideas


def _failing_shorts(monkeypatch, fail_first: int | None = None):
    """check_short rejects the first `fail_first` Shorts (all of them when None)."""
    real = quality.check_short
    seen = {"n": 0}

    def check(short, channel):
        seen["n"] += 1
        if fail_first is None or seen["n"] <= fail_first:
            return ["Short too thin: ~11s"]
        return real(short, channel)
    monkeypatch.setattr(quality, "check_short", check)
    return real


def _package(c, monkeypatch, **kw):
    router, storage, ideas = setup_ideas(c, monkeypatch, n=1)
    out = produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"], **kw)
    return router, storage, db.one(c, "select * from content_projects where id=%s", (out["project_id"],))


def _children(c, pid):
    return db.all_(c, "select * from content_projects where parent_project_id=%s order by created_at", (pid,))


def test_both_shorts_dropped_retries_once_and_keeps_the_reasons(synced, monkeypatch, silent_tts):
    c = synced
    _failing_shorts(monkeypatch, fail_first=2)        # the package's two Shorts fail, the retry's pass
    _, _, head = _package(c, monkeypatch)
    assert len(_children(c, head["id"])) == 2
    problems = head["quality_report"]["package_problems"]
    assert sum("dropped" in p for p in problems) == 2


def test_new_shorts_for_a_decided_package_add_only_short_posts(synced, monkeypatch, silent_tts):
    c = synced
    real = _failing_shorts(monkeypatch)                # every Short fails while the package is made
    router, storage, head = _package(c, monkeypatch)
    assert _children(c, head["id"]) == []
    # the owner approved it and its text posts went out
    db.run(c, "update content_projects set status='approved', approved_script_version_id=current_script_version_id where id=%s", (head["id"],))
    db.run(c, "update content_variants set status='approved' where project_id=%s", (head["id"],))
    db.run(c, """update scheduled_posts set status='published' where variant_id in
                 (select id from content_variants where project_id=%s and kind='text_post')""", (head["id"],))
    before = db.all_(c, """select v.id, v.kind, v.status, v.social_account_id, sp.status post, sp.scheduled_at from content_variants v
                           join scheduled_posts sp on sp.variant_id=v.id where v.project_id=%s order by v.id""", (head["id"],))
    script_before = head["current_script_version_id"]
    monkeypatch.setattr(quality, "check_short", real)  # now the new Shorts pass
    out = produce.remake_shorts(c, router, storage, head["id"], job_id="j1")
    assert out["made"] == 2
    kids = _children(c, head["id"])
    assert len(kids) == 2 and {k["status"] for k in kids} <= {"ready_for_review", "needs_attention"}
    # the main video's script, posts and their times are untouched
    after_head = db.one(c, "select * from content_projects where id=%s", (head["id"],))
    assert after_head["current_script_version_id"] == script_before and after_head["status"] == "approved"
    assert db.all_(c, """select v.id, v.kind, v.status, v.social_account_id, sp.status post, sp.scheduled_at from content_variants v
                         join scheduled_posts sp on sp.variant_id=v.id where v.project_id=%s order by v.id""", (head["id"],)) == before
    new = db.all_(c, """select v.kind, v.status, sp.status post from content_variants v join scheduled_posts sp on sp.variant_id=v.id
                        where v.project_id = any(%s)""", ([k["id"] for k in kids],))
    assert new and {r["kind"] for r in new} <= {"short_video", "reel", "story"}
    assert {r["post"] for r in new} == {"pending_approval"}           # nothing goes out until the owner approves
    # asking again makes a second set, still without touching anything else
    out2 = produce.remake_shorts(c, router, storage, head["id"], job_id="j2")
    assert out2["made"] == 2 and len(_children(c, head["id"])) == 4


def test_when_new_shorts_fail_too_the_owner_is_told(synced, monkeypatch, silent_tts):
    c = synced
    _failing_shorts(monkeypatch)
    router, storage, head = _package(c, monkeypatch)
    out = produce.remake_shorts(c, router, storage, head["id"], job_id="j3")
    assert out["made"] == 0 and _children(c, head["id"]) == []
    note = db.one(c, "select title from notifications where dedupe_key=%s", (f"remake_failed:{head['id']}:j3",))
    assert note and "Couldn't make new Shorts" in note["title"]
    qr = db.one(c, "select quality_report from content_projects where id=%s", (head["id"],))["quality_report"]
    assert qr["shorts_remakes"][-1]["made"] == 0


def test_remake_refuses_shorts_and_rejected_packages(synced, monkeypatch, silent_tts):
    c = synced
    router, storage, head = _package(c, monkeypatch)
    kid = _children(c, head["id"])[0]
    with pytest.raises(ValueError, match="main video"):
        produce.remake_shorts(c, router, storage, kid["id"])
    db.run(c, "update content_projects set status='rejected' where id=%s", (head["id"],))
    with pytest.raises(ValueError, match="rejected"):
        produce.remake_shorts(c, router, storage, head["id"])


def test_the_real_video_length_replaces_the_estimate(synced, monkeypatch, silent_tts):
    c = synced
    _, _, head = _package(c, monkeypatch)
    db.run(c, "update content_projects set quality_report = quality_report || %s where id=%s",
           (db.j({"issues": ["Too short: about 7.8 min (aim for 8-14 min)", "Critic score below 7"]}), head["id"]))
    produce.use_real_length(c, head["id"], 582.6)
    assert db.one(c, "select quality_report from content_projects where id=%s", (head["id"],))["quality_report"]["issues"] == ["Critic score below 7"]
    monkeypatch.setattr(quality, "MIN_LONG_SECONDS", 480)   # tests run with a lower minimum; use the real one here
    produce.use_real_length(c, head["id"], 300)
    assert db.one(c, "select quality_report from content_projects where id=%s", (head["id"],))["quality_report"]["issues"][-1].startswith("Too short: 5.0 min")


def test_owner_can_request_new_shorts_and_a_hand_posted_text_shows_as_published(synced, monkeypatch, silent_tts):
    c = synced
    _, _, head = _package(c, monkeypatch)
    post = db.one(c, """select sp.id, sp.variant_id from scheduled_posts sp join content_variants v on v.id=sp.variant_id
                        where v.project_id=%s limit 1""", (head["id"],))
    db.run(c, "update content_variants set status='approved' where id=%s", (post["variant_id"],))
    task = db.one(c, """insert into manual_tasks (scheduled_post_id, platform, title, instructions)
                        values (%s, 'x', 'Post manually', 'copy and paste') returning id""", (post["id"],))
    owner = str(uuid.uuid4())
    as_user(c, owner)
    db.one(c, "select public.claim_ownership() ok")
    job = db.one(c, "select public.enqueue_owner_job('remake_shorts', %s, '{}'::jsonb) id", (head["id"],))["id"]
    db.one(c, "select public.complete_manual_task(%s, null) ok", (task["id"],))
    reset_role(c)
    assert db.one(c, "select job_type, status from generation_jobs where id=%s", (job,)) == {"job_type": "remake_shorts", "status": "queued"}
    assert db.one(c, "select status from content_variants where id=%s", (post["variant_id"],))["status"] == "published"
