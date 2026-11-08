"""Recovery journeys with real database guards and model parsing; no real platform or email calls."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from studio import db, maintenance, preflight, produce
from studio.errors import NeedsReview, QuotaError
from studio.publish import runner
from studio.review import auto, recovery
from studio.script import pipeline, repair
from studio.media import stock
from studio.media.visual_plan import plan
from studio.script.models import Script, FactSheet
from .fakes import ScriptedRouter, fake_sources
from .test_database import as_user, reset_role


def seed(c, monkeypatch):
    router = ScriptedRouter(monkeypatch, extra=("delta", "epsilon"))
    ids = fake_sources(c, "ai")
    sources = produce._sources_for(c, ids)
    result = pipeline.write_long(
        router, "ai", {"title": "AI assistant data", "angle": ""}, sources
    )
    p = produce.ensure_project(
        c, "ai", "long", result.script.title, datetime.now().date()
    )
    sv = produce.save_script(
        c,
        p["id"],
        result.script.model_dump(),
        "ai",
        result.trail,
        result.claims,
        result.facts,
        sources,
    )
    db.run(
        c,
        "update content_projects set status='ready_for_review',quality_report=%s,recipe=%s where id=%s",
        (
            db.j(result.report),
            db.j(
                {
                    "preview_key": "test-preview",
                    "package": {"x_post": "A checked useful guide."},
                }
            ),
            p["id"],
        ),
    )
    p = db.one(c, "select * from content_projects where id=%s", (p["id"],))
    acc = db.one(c, "select * from social_accounts where platform='x' limit 1")
    produce._create_variant(
        c, acc, p, "text_post", datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    db.set_setting(c, "auto_review_post", True)
    monkeypatch.setattr(
        auto,
        "ai_review",
        lambda *a, **kw: (
            auto.PolicyReview(publishable=True, confidence=0.99),
            "independent/test",
        ),
    )
    return router, p, sv, result


def test_partial_claim_enters_repair_and_cannot_be_approved(synced, monkeypatch):
    r, p, sv, _ = seed(synced, monkeypatch)
    db.run(
        synced,
        "update research_claims set status='partially_supported' where script_version_id=%s",
        (sv["id"],),
    )
    out = auto.review_project(synced, r, p["id"])
    assert out["verdict"] == "fixing"
    assert (
        db.one(synced, "select count(*) n from approvals where source='auto_review'")[
            "n"
        ]
        == 0
    )
    assert "partially_supported" in repair.BAD
    assert auto.review_project(synced, r, p["id"])["reason"] == "a fix is in progress"


def test_final_fact_failure_withdraws_approval_and_queues_once(synced, monkeypatch):
    r, p, sv, _ = seed(synced, monkeypatch)
    assert auto.review_project(synced, r, p["id"])["verdict"] == "approved"
    monkeypatch.setattr(
        preflight,
        "check",
        lambda *a, **kw: (_ for _ in ()).throw(
            preflight.Failed(
                "C1 needs qualification",
                [{"key": "C1", "status": "partially_supported", "note": "Too broad"}],
                sv["id"],
            )
        ),
    )
    out = runner.run_due(
        synced, None, router=r, now=datetime.now(timezone.utc) + timedelta(days=60)
    )
    assert out == {"repair_queued": 1}
    head = db.one(
        synced,
        "select status,approved_script_version_id from content_projects where id=%s",
        (p["id"],),
    )
    assert head == {"status": "needs_attention", "approved_script_version_id": None}
    assert (
        db.one(
            synced,
            "select count(*) n from generation_jobs where input->>'auto_fix'='true'",
        )["n"]
        == 1
    )
    assert db.one(synced, "select count(*) n from publish_attempts")["n"] == 0
    assert recovery.queue_final(synced, p["id"], [], "same failure") is True
    assert (
        db.one(
            synced,
            "select count(*) n from generation_jobs where input->>'auto_fix'='true'",
        )["n"]
        == 1
    )


def test_unavailable_checker_retries_without_rewriting_or_uploading(
    synced, monkeypatch
):
    r, p, _, _ = seed(synced, monkeypatch)
    auto.review_project(synced, r, p["id"])
    monkeypatch.setattr(
        preflight,
        "check",
        lambda *a, **kw: (_ for _ in ()).throw(
            QuotaError("Free checker quota exhausted")
        ),
    )
    out = runner.run_due(
        synced, None, router=r, now=datetime.now(timezone.utc) + timedelta(days=60)
    )
    assert out == {"check_retry": 1}
    row = db.one(synced, "select status,locked_until from scheduled_posts")
    assert row["status"] == "scheduled" and row["locked_until"] > datetime.now(
        timezone.utc
    )
    assert (
        db.one(
            synced,
            "select count(*) n from generation_jobs where input->>'auto_fix'='true'",
        )["n"]
        == 0
    )
    assert db.one(synced, "select count(*) n from publish_attempts")["n"] == 0


def test_recovery_never_changes_ambiguous_upload(synced, monkeypatch):
    r, p, sv, _ = seed(synced, monkeypatch)
    auto.review_project(synced, r, p["id"])
    post = db.one(synced, "select * from scheduled_posts")
    db.run(
        synced,
        "insert into publish_attempts(scheduled_post_id,social_account_id,content_sha256,outcome) values(%s,%s,'abc','ambiguous')",
        (post["id"], post["social_account_id"]),
    )
    assert recovery.queue_final(synced, p["id"], [], "bad fact") is False
    assert (
        db.one(synced, "select status from content_projects where id=%s", (p["id"],))[
            "status"
        ]
        == "approved"
    )


def test_recovery_rejects_changed_version_and_mode_off(synced, monkeypatch):
    r, p, sv, result = seed(synced, monkeypatch)
    new = produce.save_script(
        synced, p["id"], result.script.model_dump(), "owner_edit", []
    )
    assert recovery.queue_final(synced, p["id"], [], "old check", sv["id"]) is False
    db.set_setting(synced, "auto_review_post", False)
    assert recovery.queue_final(synced, p["id"], [], "bad check", new["id"]) is False


def test_repair_limit_cannot_be_bypassed_by_repeated_failures(synced, monkeypatch):
    _, p, _, _ = seed(synced, monkeypatch)
    db.set_setting(synced, "auto_review_fix", {"max_attempts": 0})
    assert recovery.queue_final(synced, p["id"], [], "bad check") is False


@pytest.mark.parametrize(
    "text,risky",
    [
        (
            "Compare old and new pay with inflation. Taxes and insurance affect take-home pay.",
            False,
        ),
        ("A mortgage is a loan secured against property.", False),
        ("What is an ETF? It is a pooled investment fund.", False),
        ("You should buy this ETF for retirement.", True),
        ("Roth IRA vs 401(k): which first?", True),
        ("We recommend claiming this tax deduction.", True),
        ("Do not buy that stock.", True),
        ("Apply for this mortgage today.", True),
    ],
)
def test_general_education_vs_financial_recommendations(text, risky):
    assert bool(auto.money_advice_hits(text)) is risky


def test_visual_plan_preserves_data_and_only_promotes_relevant_scenes():
    scenes = [{"narration": "Opening", "visual": {"type": "title_card"}}]
    scenes += [
        {
            "narration": "Check the document before using its summary.",
            "visual": {"type": "title_card"},
        },
        {"narration": "Budget rose 5%", "visual": {"type": "stat", "stat_value": "5%"}},
        {
            "narration": "Follow these steps",
            "visual": {"type": "steps", "items": ["Read", "Check"]},
        },
        {"narration": "Closing", "visual": {"type": "title_card"}},
    ]
    got = plan(scenes)
    assert (
        got[1]["visual"]["type"] == "stock"
        and got[1]["kicker"] == "Illustrative footage"
    )
    assert got[2] == scenes[2] and got[3] == scenes[3]
    assert scenes[1]["visual"]["type"] == "title_card"  # original never mutated
    assert (
        stock.best(
            [{"tags": "football"}], "document summary", lambda x: x["tags"], lambda x: 1
        )
        is None
    )


def test_funnel_is_owner_only_and_does_not_turn_attempts_into_packages(
    synced, monkeypatch
):
    _, p, sv, _ = seed(synced, monkeypatch)
    for attempt in (1, 2):
        db.run(
            synced,
            "insert into auto_reviews(project_id,script_version_id,verdict,checks,reasons,attempt) values(%s,%s,'needs_review','[]','[]',%s)",
            (p["id"], sv["id"], attempt),
        )
    as_user(synced, "00000000-0000-0000-0000-000000000002")
    with pytest.raises(Exception, match="owner only"):
        db.one(synced, "select studio_automation_funnel() r")
    db.one(synced, "select claim_ownership()")
    out = db.one(synced, "select studio_automation_funnel() r")["r"]
    assert out["reviewed"] == 1 and out["review_attempts"] == 2 and out["public"] == 0
    reset_role(synced)


def test_partial_repair_rebuilds_derivatives_and_is_reapproved_before_publication(
    synced, monkeypatch, tmp_path
):
    from studio.storage import LocalStorage
    from .test_end_to_end import _connect_all, _adapters, Platform

    r, p, sv, result = seed(synced, monkeypatch)
    child = produce.ensure_project(
        synced,
        "ai",
        "short",
        "Old derivative",
        datetime.now().date(),
        parent_id=p["id"],
        key="old-child",
    )
    db.run(
        synced,
        "update content_projects set status='ready_for_review' where id=%s",
        (child["id"],),
    )
    db.run(
        synced,
        "update research_claims set status='partially_supported' where script_version_id=%s",
        (sv["id"],),
    )
    assert auto.review_project(synced, r, p["id"])["verdict"] == "fixing"

    def render(c, storage, pid, body, channel, fmt):
        db.run(
            c,
            "update content_projects set recipe=coalesce(recipe,'{}'::jsonb)||%s where id=%s",
            (db.j({"preview_key": "repaired-preview", "render": {"scenes": []}}), pid),
        )
        return {"key": "repaired-preview"}

    monkeypatch.setattr(produce, "render_preview", render)
    monkeypatch.setattr(produce, "make_thumbnails", lambda *a: [])
    storage = LocalStorage(tmp_path / "storage")
    done = maintenance.process_owner_jobs(synced, r, storage, rounds=2)
    assert done and all(x["status"] == "completed" for x in done), done
    current = db.one(synced, "select * from content_projects where id=%s", (p["id"],))
    assert current["current_script_version_id"] != sv["id"]
    assert (
        current["approved_script_version_id"] == current["current_script_version_id"]
        and current["status"] == "approved"
    )
    assert (
        db.one(
            synced, "select status from content_projects where id=%s", (child["id"],)
        )["status"]
        == "rejected"
    )
    assert (
        db.one(
            synced,
            "select count(*) n from content_projects where parent_project_id=%s and status='approved'",
            (p["id"],),
        )["n"]
        == 2
    )
    assert not db.one(
        synced,
        "select 1 from research_claims where script_version_id=%s and status='partially_supported'",
        (current["current_script_version_id"],),
    )
    # Publish one real runner journey through fake platform HTTP. The other platform connections stay uncalled.
    _connect_all(synced)
    db.run(synced, "update scheduled_posts set scheduled_at=now()+interval '100 days'")
    db.run(
        synced,
        "update scheduled_posts set scheduled_at=now()-interval '1 minute' where variant_id in(select id from content_variants where project_id=%s and kind='text_post' and social_account_id in(select id from social_accounts where platform='x'))",
        (p["id"],),
    )
    monkeypatch.setattr(runner, "final_media", lambda *a, **kw: (None, None))
    out = runner.run_due(synced, storage, adapters=_adapters(Platform()), router=r)
    assert out.get("published") == 1, out
    assert db.one(synced, "select visibility,method from published_posts") == {
        "visibility": "public",
        "method": "api",
    }
    as_user(synced, "00000000-0000-0000-0000-000000000002")
    db.one(synced, "select claim_ownership()")
    funnel = db.one(synced, "select studio_automation_funnel() r")["r"]
    assert (
        funnel["approved"] == 1 and funnel["public"] == 1
    )  # parent plus its Shorts count once
    reset_role(synced)


def test_failed_final_repair_can_queue_another_bounded_attempt(synced, monkeypatch):
    _, p, _, _ = seed(synced, monkeypatch)
    assert recovery.queue_final(synced, p["id"], [], "bad claim")
    db.run(
        synced,
        "update generation_jobs set status='failed' where input->>'auto_fix'='true'",
    )
    assert recovery.queue_final(synced, p["id"], [], "retry bad claim")
    assert (
        db.one(
            synced,
            "select count(*) n from generation_jobs where input->>'auto_fix'='true'",
        )["n"]
        == 2
    )


def test_model_outage_resumes_checked_script_after_backoff(
    synced, monkeypatch, tmp_path
):
    from studio.storage import LocalStorage

    r, p, sv, _ = seed(synced, monkeypatch)
    db.run(
        synced,
        "update research_claims set status='partially_supported' where script_version_id=%s",
        (sv["id"],),
    )
    assert auto.review_project(synced, r, p["id"])["verdict"] == "fixing"
    real_package = pipeline.make_package
    calls = []

    def package(*args, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise QuotaError("Temporary free model quota")
        return real_package(*args, **kw)

    monkeypatch.setattr(pipeline, "make_package", package)

    def render(c, storage, pid, *args):
        db.run(
            c,
            "update content_projects set recipe=coalesce(recipe,'{}'::jsonb)||%s where id=%s",
            (db.j({"preview_key": "new-preview"}), pid),
        )
        return {}

    monkeypatch.setattr(produce, "render_preview", render)
    monkeypatch.setattr(produce, "make_thumbnails", lambda *args: [])
    storage = LocalStorage(tmp_path / "storage")
    first = maintenance.process_owner_jobs(synced, r, storage, rounds=3)
    assert [x["status"] for x in first] == ["retrying"]
    job = db.one(
        synced, "select * from generation_jobs where input->>'auto_fix'='true'"
    )
    assert (
        job["status"] == "queued"
        and job["attempts"] == 1
        and job["next_attempt_at"] > datetime.now(timezone.utc)
    )
    assert job["input"]["resume_version"] != str(sv["id"])
    db.run(
        synced,
        "update generation_jobs set next_attempt_at=now()-interval '1 minute' where id=%s",
        (job["id"],),
    )
    second = maintenance.process_owner_jobs(synced, r, storage, rounds=2)
    assert all(x["status"] == "completed" for x in second), second
    assert (
        db.one(
            synced,
            "select count(*) n from script_versions where project_id=%s",
            (p["id"],),
        )["n"]
        == 2
    )
    assert (
        db.one(synced, "select status from content_projects where id=%s", (p["id"],))[
            "status"
        ]
        == "approved"
    )


@pytest.mark.parametrize("status", ["rejected", "archived"])
def test_rejected_or_archived_package_is_never_resurrected(synced, monkeypatch, status):
    _, p, _, _ = seed(synced, monkeypatch)
    db.run(
        synced, "update content_projects set status=%s where id=%s", (status, p["id"])
    )
    assert recovery.queue_final(synced, p["id"], [], "bad claim") is False
    assert (
        db.one(synced, "select status from content_projects where id=%s", (p["id"],))[
            "status"
        ]
        == status
    )


def test_final_check_never_uses_verdict_for_a_different_version(synced, monkeypatch):
    r, p, sv, result = seed(synced, monkeypatch)
    produce.save_script(synced, p["id"], result.script.model_dump(), "owner_edit", [])
    with pytest.raises(preflight.Changed):
        preflight.check(synced, r, p["id"], expected_version=sv["id"])


def test_repair_polish_reuses_writers_to_reserve_an_independent_checker(monkeypatch):
    from studio.script.models import Script, Scene, Visual
    from .fakes import scene_text

    router = ScriptedRouter(monkeypatch, extra=("delta",))
    script = Script(
        title="Guide",
        hook="Read carefully",
        promise="Learn",
        cta="Subscribe",
        scenes=[Scene(narration=scene_text(1), visual=Visual(type="title_card"))],
    )
    _, trail = pipeline.voice_edit(
        router, "ai", script, {"alpha", "beta", "gamma"}, reuse_writers=True
    )
    assert set(trail["companies"]) <= {"alpha", "beta", "gamma"}
    assert any(c.provider == "delta" for c in router.candidates("claim_checker"))


def test_review_and_final_check_share_the_same_repair_budget(synced, monkeypatch):
    r, p, sv, _ = seed(synced, monkeypatch)
    db.run(
        synced,
        "update research_claims set status='partially_supported' where script_version_id=%s",
        (sv["id"],),
    )
    assert auto.review_project(synced, r, p["id"])["verdict"] == "fixing"
    db.run(
        synced,
        "update generation_jobs set status='failed' where input->>'auto_fix'='true'",
    )
    assert recovery.queue_final(synced, p["id"], [], "final failure")
    db.run(
        synced,
        "update generation_jobs set status='failed' where input->>'auto_fix'='true'",
    )
    db.run(
        synced,
        "insert into auto_reviews(project_id,script_version_id,verdict,checks,reasons,attempt,fix) values(%s,%s,'fixing','[]','[]',2,'post text cleaned')",
        (p["id"], sv["id"]),
    )
    db.set_setting(synced, "auto_review_fix", {"max_attempts": 3})
    assert auto.fix_attempts(synced, p["id"]) == 3
    assert recovery.queue_final(synced, p["id"], [], "another final failure") is False


def test_pixabay_queries_are_cached_for_24_hours_without_saving_key(
    tmp_path, monkeypatch
):
    import httpx, os, time

    monkeypatch.setenv("STUDIO_WORK_DIR", str(tmp_path))
    calls = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                calls.append(request) or httpx.Response(200, json={"hits": []})
            )
        )
    )
    params = {"key": "unit-test-secret", "q": "document review"}
    assert stock._pixabay_data(client, "/api/", params) == {"hits": []}
    assert (
        stock._pixabay_data(client, "/api/", params) == {"hits": []} and len(calls) == 1
    )
    cache = next(tmp_path.rglob("*.json"))
    assert "unit-test-secret" not in cache.name + cache.read_text()
    os.utime(cache, (time.time() - 86401, time.time() - 86401))
    stock._pixabay_data(client, "/api/", params)
    assert len(calls) == 2
