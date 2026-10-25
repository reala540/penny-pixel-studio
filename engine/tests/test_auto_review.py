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


@pytest.fixture(autouse=True)
def low_risk(monkeypatch):
    """These tests cover the review flow itself; Smart Mode's risk rules have their own tests (test_smart_mode.py)."""
    monkeypatch.setattr(auto, "risk_reasons", lambda conn, family: [])


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


def test_unsure_review_with_fixes_switched_off_goes_to_telegram(synced, monkeypatch, silent_tts):
    c = synced
    set_mode(c, True)
    db.run(c, "insert into settings (key, value) values ('auto_review_fix', '{\"max_attempts\": 0}')")
    monkeypatch.setattr(auto, "ai_review", lambda router, fam, var, conn: (
        PolicyReview(publishable=True, confidence=0.6, summary="Probably fine"), "beta/b1"))
    _, _, _, out = _produce_week(c, monkeypatch)
    assert {r["verdict"] for r in out["auto_review"]} == {"needs_review"}
    assert statuses(c) == ["pending_approval"]
    assert db.one(c, "select count(*) n from approvals")["n"] == 0
    note = db.one(c, "select title, body from notifications where kind='auto_review_needs_you' limit 1")
    assert note["title"].startswith("👀 Needs your review") and "confidence" in note["body"]


def test_unsure_review_queues_a_rewrite_with_the_reviewers_notes(synced, monkeypatch, silent_tts):
    c = synced
    set_mode(c, True)
    monkeypatch.setattr(auto, "ai_review", lambda router, fam, var, conn: (
        PolicyReview(publishable=True, confidence=0.6, issues=["The hook overstates the result"], summary="Unsure"), "beta/b1"))
    _, _, _, out = _produce_week(c, monkeypatch)
    assert {r["verdict"] for r in out["auto_review"]} == {"fixing"}
    assert statuses(c) == ["pending_approval"]                       # nothing posts while it's being fixed
    jobs_ = db.all_(c, "select job_type, status, requested_by, input from generation_jobs where input->>'auto_fix'='true'")
    assert len(jobs_) == 2 and {j["job_type"] for j in jobs_} == {"regenerate_script"}
    assert all(j["status"] == "queued" and j["requested_by"] == "owner" for j in jobs_)
    assert "overstates" in jobs_[0]["input"]["instructions"] and "confidence" in jobs_[0]["input"]["instructions"]
    assert db.one(c, "select count(*) n from notifications where kind='auto_fixing'")["n"] == 2
    rows = db.all_(c, "select verdict, attempt, fix from auto_reviews")
    assert {(r["verdict"], r["attempt"]) for r in rows} == {("fixing", 1)} and "rewriting" in rows[0]["fix"]
    # while the fix is queued, another pass leaves it alone
    assert {r["verdict"] for r in auto.run(c, router=None)} == {"skipped"}


def test_rewrite_fix_runs_and_the_package_is_approved_afterwards(synced, monkeypatch, silent_tts):
    from studio import maintenance

    c = synced
    set_mode(c, True)
    verdicts = iter([0.6, 0.6, 0.95, 0.95])                           # unsure first, confident after the rewrite
    monkeypatch.setattr(auto, "ai_review", lambda router, fam, var, conn: (
        PolicyReview(publishable=True, confidence=next(verdicts, 0.95), summary="ok"), "beta/b1"))
    router, storage, _, out = _produce_week(c, monkeypatch)
    assert {r["verdict"] for r in out["auto_review"]} == {"fixing"}
    done = maintenance.process_owner_jobs(c, router, storage)
    assert [d["status"] for d in done] == ["completed", "completed"], done
    assert statuses(c) == ["scheduled"]
    assert db.one(c, "select count(*) n from script_versions where origin='rewrite'")["n"] == 2
    final = db.all_(c, "select verdict, attempt from auto_reviews where verdict='approved'")
    assert len(final) == 2 and all(r["attempt"] == 2 for r in final)
    assert "Fixed automatically" in db.one(c, "select body from notifications where kind='auto_approved' limit 1")["body"]


def test_post_text_problems_are_fixed_in_place_then_approved(synced, monkeypatch, silent_tts):
    c = synced
    passing(monkeypatch)
    _produce_week(c, monkeypatch)                                      # produced while OFF
    money = db.one(c, "select id from content_projects where channel_slug='money' and format='long'")["id"]
    v = db.one(c, "select id, body from content_variants where project_id=%s and kind='long_video'", (money,))
    stripped = "\n".join(l for l in v["body"].splitlines() if "not personal" not in l.lower() and "general" not in l.lower())
    db.run(c, "update content_variants set body=%s where id=%s", (stripped + "\nThis is a game-changer.", v["id"]))
    set_mode(c, True)
    results = {r["project"]: r for r in auto.run(c, router=None)}
    assert results[str(money)]["verdict"] == "approved" and results[str(money)]["fix_attempts"] == 1
    body = db.one(c, "select body from content_variants where id=%s", (v["id"],))["body"]
    assert "not personal" in body.lower() and "game-changer" not in body.lower() and "big shift" in body
    assert db.one(c, "select count(*) n from auto_reviews where project_id=%s and verdict='fixing'", (money,))["n"] == 1


def test_policy_flags_and_wrong_destinations_are_never_retried(synced, monkeypatch, silent_tts):
    c = synced
    set_mode(c, True)
    monkeypatch.setattr(auto, "ai_review", lambda router, fam, var, conn: (
        PolicyReview(publishable=False, confidence=0.9, policy_flags=["Promises returns"], summary="no"), "beta/b1"))
    _, _, _, out = _produce_week(c, monkeypatch)
    assert {r["verdict"] for r in out["auto_review"]} == {"needs_review"}
    assert db.one(c, "select count(*) n from generation_jobs where input->>'auto_fix'='true'")["n"] == 0
    assert auto.plan_fix([{"code": "destination"}, {"code": "banned"}]) == ([], None)
    assert auto.plan_fix([{"code": "fresh"}]) == ([], "recheck")
    assert auto.plan_fix([{"code": "claims"}, {"code": "licences"}]) == ([], "rewrite")


def test_attempts_stop_at_the_limit(synced, monkeypatch, silent_tts):
    c = synced
    passing(monkeypatch)
    _produce_week(c, monkeypatch)
    ai = db.one(c, "select id from content_projects where channel_slug='ai' and format='long'")["id"]
    db.run(c, "update content_projects set fresh_until=now() + interval '2 hours' where id=%s", (ai,))
    set_mode(c, True)
    for attempt in (1, 2, 3):
        r = auto.review_project(c, None, ai)
        assert r["verdict"] == "fixing" and r["attempt"] == attempt and r["fix"] == "recheck_project"
        db.run(c, "update generation_jobs set status='completed' where input->>'auto_fix'='true'")  # the recheck didn't help
    r = auto.review_project(c, None, ai)
    assert r["verdict"] == "needs_review" and any("after 3 automatic" in x for x in r["reasons"])
    assert statuses(c) == ["pending_approval"]


def test_a_missed_slot_moves_to_the_next_free_slot(synced, monkeypatch, silent_tts):
    c = synced
    passing(monkeypatch)
    _produce_week(c, monkeypatch)
    past = datetime.now(timezone.utc) - timedelta(hours=3)
    db.run(c, "update scheduled_posts set scheduled_at=%s", (past,))
    set_mode(c, True)
    auto.run(c, router=None)
    rows = db.all_(c, """select sp.scheduled_at, sp.social_account_id, v.kind, a.platform, a.weekly_targets
                           from scheduled_posts sp join content_variants v on v.id=sp.variant_id
                           join social_accounts a on a.id=sp.social_account_id where sp.status='scheduled'""")
    assert rows and all(r["scheduled_at"] > datetime.now(timezone.utc) for r in rows)
    from zoneinfo import ZoneInfo

    for r in rows:   # each lands on one of its own account's posting times
        prefix = "shorts" if r["platform"] == "youtube" and r["kind"] == "short_video" else "posting"
        local = r["scheduled_at"].astimezone(ZoneInfo("Africa/Nairobi"))
        assert local.strftime("%H:%M") in r["weekly_targets"][f"{prefix}_times"]
        assert local.strftime("%a").lower() in r["weekly_targets"][f"{prefix}_days"]
    per_account: dict = {}
    for r in rows:
        per_account.setdefault(r["social_account_id"], []).append(r["scheduled_at"])
    assert all(len(set(v)) == len(v) for v in per_account.values())   # never two posts in the same slot


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
    results = {r["project"]: r for r in auto.run(c, router=None)}      # default: fix first
    assert results[str(money)]["verdict"] == "fixing" and results[str(money)]["fix"] == "regenerate_script"
    assert any("quality gates" in x for x in results[str(money)]["reasons"])
    assert results[str(ai)]["verdict"] == "fixing" and results[str(ai)]["fix"] == "recheck_project"
    assert any("fresh" in x for x in results[str(ai)]["reasons"])
    assert statuses(c) == ["pending_approval"]
    # with fixes switched off they come straight to you
    db.run(c, "delete from auto_reviews")
    db.run(c, "delete from generation_jobs where input->>'auto_fix'='true'")
    db.run(c, "insert into settings (key, value) values ('auto_review_fix', '{\"max_attempts\": 0}')")
    results = {r["project"]: r for r in auto.run(c, router=None)}
    assert {r["verdict"] for r in results.values()} == {"needs_review"}
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
