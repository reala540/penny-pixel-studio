"""Strict duplicate protection and audit trail: the same content never goes to one account twice, an upload that
didn't finish clearly is never retried by itself, and the audit trail can't be edited."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from studio import db
from studio.publish import runner

from .test_end_to_end import Platform, _adapters, _approve_all, _connect_all, produced, silent_tts  # noqa: F401

LATER = datetime.now(timezone.utc) + timedelta(days=30)


def _ready(conn):
    _connect_all(conn)
    _approve_all(conn)
    db.run(conn, "update content_projects set fresh_until = now() + interval '60 days'")
    db.run(conn, "update scheduled_posts set status='scheduled'")


def _one_post(conn, platform: str) -> dict:
    return db.one(conn, """select sp.* from scheduled_posts sp join social_accounts a on a.id = sp.social_account_id
                           where a.platform=%s and sp.status='scheduled' order by sp.scheduled_at limit 1""", (platform,))


def test_same_video_never_goes_to_the_same_account_twice(produced):
    conn, storage = produced
    _ready(conn)
    first = _one_post(conn, "facebook")
    platform = Platform()
    assert runner.publish_post(conn, storage, first, _adapters(platform), now=LATER) == "published"
    sent = len(platform.requests)
    # a second, different post on the same account carrying the exact same text and video
    v1 = db.one(conn, "select * from content_variants where id=%s", (first["variant_id"],))
    twin = db.one(conn, """select sp.* from scheduled_posts sp join content_variants v on v.id = sp.variant_id
                           where sp.social_account_id=%s and sp.status='scheduled' and v.kind=%s and sp.id<>%s limit 1""",
                  (first["social_account_id"], v1["kind"], first["id"]))
    if twin is None:
        pytest.skip("no second post of the same kind on this account in the sample week")
    db.run(conn, "update content_variants set title=%s, body=%s, project_id=%s where id=%s",
           (v1["title"], v1["body"], v1["project_id"], twin["variant_id"]))
    twin = db.one(conn, "update scheduled_posts set attempts=attempts+1 where id=%s returning *", (twin["id"],))
    assert runner.publish_post(conn, storage, twin, _adapters(platform), now=LATER) == "duplicate"
    assert len(platform.requests) == sent  # nothing sent
    row = db.one(conn, "select status, last_error from scheduled_posts where id=%s", (twin["id"],))
    assert row["status"] == "blocked" and row["last_error"].startswith("Duplicate:")
    assert db.one(conn, "select outcome from publish_attempts where scheduled_post_id=%s", (twin["id"],))["outcome"] == "blocked_duplicate"
    # and even a direct insert can't record the same content twice for one account
    digest = db.one(conn, "select content_sha256 from published_posts where scheduled_post_id=%s", (first["id"],))["content_sha256"]
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.run(conn, """insert into published_posts (scheduled_post_id, platform, method, social_account_id, content_sha256)
                        values (%s,'facebook','api',%s,%s)""", (twin["id"], first["social_account_id"], digest))


class Crash(Exception):
    """Something unexpected while talking to the platform: we can't know whether the post went out."""


def test_an_unclear_upload_waits_for_the_owner_then_retries_once(produced, monkeypatch):
    conn, storage = produced
    _ready(conn)
    post = _one_post(conn, "x")
    adapters = _adapters(Platform())

    def boom(*a, **k):
        raise Crash("connection dropped mid-upload")
    monkeypatch.setattr(adapters["x"], "publish", boom)
    with pytest.raises(Crash):
        runner.publish_post(conn, storage, post, adapters, now=LATER)
    open_attempt = db.one(conn, "select * from publish_attempts where scheduled_post_id=%s", (post["id"],))
    assert open_attempt["outcome"] is None  # written before the upload, never closed
    # the next run (even with a working platform) refuses to send it again
    platform = Platform()
    post = db.one(conn, "select * from scheduled_posts where id=%s", (post["id"],))
    assert runner.publish_post(conn, storage, post, _adapters(platform), now=LATER) == "needs_review"
    assert platform.requests == []
    assert db.one(conn, "select status from scheduled_posts where id=%s", (post["id"],))["status"] == "needs_review"
    # a second runner can't start the same post while an attempt is open
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.run(conn, """insert into publish_attempts (scheduled_post_id, social_account_id, content_sha256)
                        values (%s,%s,'x')""", (post["id"], post["social_account_id"]))
    # the owner checked the platform and presses Try again: the attempt is cleared on the record, and it posts once
    db.run(conn, "update scheduled_posts set status='scheduled' where id=%s", (post["id"],))
    cleared = db.one(conn, "select * from publish_attempts where id=%s", (open_attempt["id"],))
    assert cleared["cleared_at"] is not None and cleared["outcome"] == "not_sent"
    post = db.one(conn, "select * from scheduled_posts where id=%s", (post["id"],))
    assert runner.publish_post(conn, storage, post, _adapters(platform), now=LATER) == "published"
    assert db.one(conn, "select count(*) n from published_posts where scheduled_post_id=%s", (post["id"],))["n"] == 1
    with pytest.raises(psycopg.errors.RaiseException):  # an outcome is recorded once
        db.run(conn, "update publish_attempts set outcome='published' where id=%s", (open_attempt["id"],))


def test_every_change_is_on_a_tamper_evident_record(produced):
    conn, _ = produced
    _ready(conn)
    actions = [r["action"] for r in db.all_(conn, "select action from audit_logs order by id")]
    assert "content_projects_insert" in actions and "scheduled_posts_update" in actions
    assert db.all_(conn, "select * from audit_chain_problems()") == []
    # an edit made behind the triggers' back (as a superuser could) is detected
    db.run(conn, "set session_replication_role = replica")
    db.run(conn, "update audit_logs set details = '{\"edited\": true}' where id = 3")
    db.run(conn, "set session_replication_role = origin")
    problems = db.all_(conn, "select * from audit_chain_problems()")
    assert problems and problems[0]["id"] == 3 and problems[0]["problem"] == "row was changed"
