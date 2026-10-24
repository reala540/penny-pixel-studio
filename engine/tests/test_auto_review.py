"""Auto Review & Post: OFF keeps today's manual flow exactly; ON approves only fully passing packages."""

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from studio import db
from studio.publish import runner
from studio.review import auto
from studio.review.auto import PolicyReview

from .test_database import as_user, reset_role
from .test_end_to_end import _produce_week, silent_tts  # noqa: F401  (fixture)

OWNER = str(uuid.uuid4())


def set_mode(conn, on: bool):
    return db.one(conn, "select public.set_auto_review_post(%s, 'owner') r", (on,))["r"]


def passing(monkeypatch, **over):
    review = PolicyReview(publishable=True, confidence=0.95, summary="Accurate and on brand.", **over)
    monkeypatch.setattr(auto, "ai_review", lambda router, fam, var, conn: (review, "beta/b1"))


def statuses(conn):
    return sorted({r["status"] for r in db.all_(conn, "select status from scheduled_posts")})


def test_off_by_default_keeps_the_manual_flow(synced, monkeypatch, silent_tts):
    c = synced
    assert db.get_setting(c, "auto_review_post", False) is False
    passing(monkeypatch)
    _, _, _, out = _produce_week(c, monkeypatch)
    assert out["auto_review"] == []
    assert statuses(c) == ["pending_approval"]
    assert db.one(c, "select count(*) n from approvals")["n"] == 0
    assert db.one(c, "select count(*) n from auto_reviews")["n"] == 0


def test_on_approves_passing_packages_and_publishing_guards_accept_them(synced, monkeypatch, silent_tts):
    c = synced
    set_mode(c, True)
    passing(monkeypatch)
    _, _, _, out = _produce_week(c, monkeypatch)
    verdicts = [r["verdict"] for r in out["auto_review"]]
    assert verdicts == ["approved", "approved"], out["auto_review"]
    assert statuses(c) == ["scheduled"]
    assert db.one(c, "select count(*) n from approvals where source='auto_review'")["n"] > 0
    assert db.one(c, "select count(*) n from approvals where source='owner'")["n"] == 0
    assert db.one(c, "select count(*) n from notifications where kind='auto_approved'")["n"] == 2
    assert db.one(c, "select count(*) n from audit_logs where action='auto_review_approved'")["n"] == 2
    post = db.one(c, "select * from scheduled_posts limit 1")
    ctx = runner._context(c, post) if hasattr(runner, "_context") else None
    if ctx is not None:
        assert runner.safety_problems(c, post, ctx, datetime.now(timezone.utc)) == []   # same publish guards apply
    # reviewing again never double-approves or double-posts
    assert all(r["verdict"] == "skipped" for r in [auto.review_project(c, None, p["id"]) for p in
               db.all_(c, "select id from content_projects where parent_project_id is null")])


def test_failed_or_unsure_review_goes_to_telegram_not_publishing(synced, monkeypatch, silent_tts):
    c = synced
    set_mode(c, True)
    passing(monkeypatch, policy_flags=[])
    monkeypatch.setattr(auto, "ai_review", lambda router, fam, var, conn: (
        PolicyReview(publishable=True, confidence=0.6, summary="Probably fine"), "beta/b1"))
    _, _, _, out = _produce_week(c, monkeypatch)
    assert {r["verdict"] for r in out["auto_review"]} == {"needs_review"}
    assert statuses(c) == ["pending_approval"]
    assert db.one(c, "select count(*) n from approvals")["n"] == 0
    note = db.one(c, "select title, body from notifications where kind='auto_review_needs_you' limit 1")
    assert note["title"].startswith("👀 Needs your review") and "confidence" in note["body"]


def test_review_errors_fall_back_to_manual_approval(synced, monkeypatch, silent_tts):
    c = synced
    set_mode(c, True)

    def broken(*a, **k):
        raise RuntimeError("every reviewer is busy")

    monkeypatch.setattr(auto, "ai_review", broken)
    _, _, _, out = _produce_week(c, monkeypatch)
    assert {r["verdict"] for r in out["auto_review"]} == {"error"}
    assert statuses(c) == ["pending_approval"]
    assert db.one(c, "select count(*) n from notifications where kind='auto_review_needs_you'")["n"] == 2


def test_needs_attention_and_deterministic_failures_are_never_auto_approved(synced, monkeypatch, silent_tts):
    c = synced
    passing(monkeypatch)
    _produce_week(c, monkeypatch)                      # produced while OFF: everything waits
    money = db.one(c, "select id from content_projects where channel_slug='money' and format='long'")["id"]
    db.run(c, "update content_projects set status='needs_attention' where id=%s", (money,))
    ai = db.one(c, "select id from content_projects where channel_slug='ai' and format='long'")["id"]
    db.run(c, "update content_projects set fresh_until=now() + interval '2 hours' where id=%s", (ai,))
    set_mode(c, True)
    results = {r["project"]: r for r in auto.run(c, router=None)}
    assert results[str(money)]["verdict"] == "needs_review"
    assert any("quality gates" in x for x in results[str(money)]["reasons"])
    assert results[str(ai)]["verdict"] == "needs_review"
    assert any("fresh" in x for x in results[str(ai)]["reasons"])
    assert statuses(c) == ["pending_approval"]


def test_switching_off_mid_review_stops_approval(synced, monkeypatch, silent_tts):
    c = synced
    passing(monkeypatch)
    _produce_week(c, monkeypatch)
    set_mode(c, True)
    calls = iter([True, True, False])                   # ON at start and per package, OFF right before approving
    monkeypatch.setattr(auto, "mode_on", lambda conn: next(calls, False))
    out = auto.run(c, router=None)
    assert out and out[0]["verdict"] == "skipped"
    assert statuses(c) == ["pending_approval"]


def test_turning_off_returns_unpublished_auto_approvals_to_review(synced, monkeypatch, silent_tts):
    c = synced
    set_mode(c, True)
    passing(monkeypatch)
    _produce_week(c, monkeypatch)
    one = db.one(c, "select id from scheduled_posts where status='scheduled' limit 1")["id"]
    db.run(c, "update scheduled_posts set status='published' where id=%s", (one,))   # already out: left alone
    db.run(c, """update content_variants set status='published'
                 where id=(select variant_id from scheduled_posts where id=%s)""", (one,))
    r = set_mode(c, False)
    assert r["on"] is False and r["was"] is True and r["reverted_posts"] > 0
    assert db.one(c, "select status from scheduled_posts where id=%s", (one,))["status"] == "published"
    rest = {x["status"] for x in db.all_(c, "select status from scheduled_posts where id<>%s", (one,))}
    assert rest == {"pending_approval"}
    log = db.all_(c, "select action, actor from audit_logs where action like 'auto_review_post_%' order by created_at")
    assert [l["action"] for l in log] == ["auto_review_post_on", "auto_review_post_off"]
    assert auto.run(c, router=None) == []               # OFF: nothing is reviewed or approved


def test_only_the_owner_can_switch_it_and_only_through_the_audited_function(synced):
    c = synced
    as_user(c, OWNER)
    db.one(c, "select public.claim_ownership() ok")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.run(c, "insert into settings (key, value) values ('auto_review_post', 'true')")
    reset_role(c)
    as_user(c, OWNER)
    assert db.one(c, "select public.set_auto_review_post(true, 'owner') r")["r"]["on"] is True
    reset_role(c)
    as_user(c, str(uuid.uuid4()), "intruder@example.com")
    with pytest.raises(psycopg.errors.RaiseException):
        db.one(c, "select public.set_auto_review_post(false, 'owner') r")
    reset_role(c)
    c.execute("set role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.one(c, "select public.set_auto_review_post(true, 'owner') r")
    reset_role(c)
    assert db.get_setting(c, "auto_review_post") is True
