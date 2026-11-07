"""Smart Mode: Auto Review & Post only ever approves low-risk packages; everything else waits for the owner."""

from studio import db
from studio.review import auto
from studio.review.auto import PolicyReview

from .test_end_to_end import _produce_week, silent_tts  # noqa: F401

OWNER = "00000000-0000-0000-0000-000000000001"


def _heads(conn):
    return {p["channel_slug"]: p for p in db.all_(conn, "select * from content_projects where parent_project_id is null")}


def test_risky_packages_always_wait_for_a_person(synced, monkeypatch, silent_tts):
    _produce_week(synced, monkeypatch)
    monkeypatch.setattr(auto, "TRUST_PERIOD", {"ai": 5, "money": 10})  # live config: Pixel has none (owner's choice)
    heads = _heads(synced)
    ai, money = auto._family(synced, heads["ai"]["id"]), auto._family(synced, heads["money"]["id"])
    db.run(synced, "update content_ideas set score_breakdown = score_breakdown || '{\"evergreen\": true}'")
    # trust period: nobody has approved anything yet
    assert any(r.startswith("Trust period") for r in auto.risk_reasons(synced, ai))
    monkeypatch.setattr(auto, "TRUST_PERIOD", {"ai": 1, "money": 1})
    for h in heads.values():
        db.run(synced, "insert into approvals (target_type, target_id, decision, decided_by, source) values ('project',%s,'approved',%s,'owner')",
               (h["id"], OWNER))
    assert auto.risk_reasons(synced, ai) == []  # an evergreen AI explainer after the trust period is low-risk
    # money topics that always need a person
    db.run(synced, "update content_projects set title='Roth IRA vs 401(k): which first?' where id=%s", (heads["money"]["id"],))
    reasons = auto.risk_reasons(synced, auto._family(synced, heads["money"]["id"]))
    assert any("Money topic" in r and "roth" in r and "401(k)" in r for r in reasons)
    # news waits for a person only while that's switched on (live: off, the freshness check guards it)
    db.run(synced, "update content_ideas set score_breakdown = score_breakdown || '{\"evergreen\": false}' where id=%s", (heads["ai"]["idea_id"],))
    assert not any(r.startswith("Time-sensitive") for r in auto.risk_reasons(synced, ai))
    monkeypatch.setattr(auto, "NEWS_NEEDS_PERSON", True)
    assert any(r.startswith("Time-sensitive") for r in auto.risk_reasons(synced, ai))
    db.run(synced, "update content_ideas set score_breakdown = score_breakdown || '{\"evergreen\": true}'")
    # only partly supported claims
    db.run(synced, """update research_claims set status='partially_supported'
                      where script_version_id=%s and ctid in (select ctid from research_claims where script_version_id=%s limit 1)""",
           (heads["ai"]["current_script_version_id"], heads["ai"]["current_script_version_id"]))
    assert any("partly supported" in r for r in auto.risk_reasons(synced, ai))
    assert money  # sanity


def test_auto_review_sends_a_risky_package_to_the_owner(synced, monkeypatch, silent_tts):
    router, *_ = _produce_week(synced, monkeypatch)
    db.one(synced, "select public.set_auto_review_post(true, 'owner') r")
    review = PolicyReview(publishable=True, confidence=0.97, summary="Fine.")
    monkeypatch.setattr(auto, "ai_review", lambda r, f, v, c: (review, "beta/b1"))
    money = _heads(synced)["money"]
    db.run(synced, "update content_projects set title='Roth IRA vs 401(k): which first?' where id=%s", (money["id"],))
    out = auto.review_project(synced, router, money["id"])
    assert out["verdict"] == "needs_review" and out["posts_scheduled"] == 0
    assert any("Smart Mode" in r for r in out["reasons"])
    assert db.one(synced, "select status from content_projects where id=%s", (money["id"],))["status"] != "approved"


def _warn_only(conn, project_id):
    """The package's only problem left is an editorial one (low editor scores)."""
    w = {"kind": "warning", "code": "critic_low", "text": "Editor scores below 7: {'pacing': 4}"}
    db.run(conn, """update content_projects set quality_report = quality_report || %s where id=%s""",
           (db.j({"issues": [w["text"]], "findings": [w]}), project_id))


def test_low_editor_scores_are_fixed_first_then_posted(synced, monkeypatch, silent_tts):
    """Owner's choice (7 Nov): low editor scores trigger the usual rewrite; if they're still low after every fix
    attempt, the package posts anyway, as long as every fact is backed and nothing blocks it."""
    router, *_ = _produce_week(synced, monkeypatch)
    db.one(synced, "select public.set_auto_review_post(true, 'owner') r")
    db.run(synced, "update content_ideas set score_breakdown = score_breakdown || '{\"evergreen\": true}'")
    review = PolicyReview(publishable=True, confidence=0.97, summary="Fine.")
    monkeypatch.setattr(auto, "ai_review", lambda r, f, v, c: (review, "beta/b1"))
    ai = _heads(synced)["ai"]
    _warn_only(synced, ai["id"])
    # attempts left: it's rewritten, not posted
    db.run(synced, "insert into settings (key, value) values ('auto_review_fix', %s) on conflict (key) do update set value=excluded.value",
           (db.j({"max_attempts": 1}),))
    out = auto.review_project(synced, router, ai["id"])
    assert out["verdict"] == "fixing" and out["fix"] == "regenerate_script"
    # the rewrite still scores low and every attempt is used: it goes out, and the note says what was accepted
    db.run(synced, "update generation_jobs set status='completed' where job_type='regenerate_script'")
    out = auto.review_project(synced, router, ai["id"])
    assert out["verdict"] == "approved" and out["posts_scheduled"] > 0, out
    note = db.one(synced, "select body from notifications where kind='auto_approved' order by created_at desc limit 1")["body"]
    assert "Posted with editor notes left" in note and "pacing" in note


def test_accepting_warnings_never_lets_a_blocker_through(synced, monkeypatch, silent_tts):
    router, *_ = _produce_week(synced, monkeypatch)
    db.one(synced, "select public.set_auto_review_post(true, 'owner') r")
    db.run(synced, "update content_ideas set score_breakdown = score_breakdown || '{\"evergreen\": true}'")
    monkeypatch.setattr(auto, "ai_review", lambda r, f, v, c: (PolicyReview(publishable=True, confidence=0.97), "beta/b1"))
    ai = _heads(synced)["ai"]
    b = {"kind": "blocker", "code": "check", "text": "Scene 3 states numbers ['15'] without a claim/source"}
    w = {"kind": "warning", "code": "critic_low", "text": "Editor scores below 7: {'pacing': 4}"}
    db.run(synced, "update content_projects set quality_report = quality_report || %s where id=%s",
           (db.j({"issues": [b["text"], w["text"]], "findings": [b, w]}), ai["id"]))
    db.run(synced, "insert into settings (key, value) values ('auto_review_fix', %s) on conflict (key) do update set value=excluded.value",
           (db.j({"max_attempts": 0}),))
    out = auto.review_project(synced, router, ai["id"])
    assert out["verdict"] == "needs_review" and out["posts_scheduled"] == 0
    assert any("states numbers" in r for r in out["reasons"])
