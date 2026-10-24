"""Regression coverage for concurrent research and owner-directed missions."""

from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
import threading

from studio import maintenance, produce
from studio.research import engine as research


def test_collect_fetches_concurrently_and_isolates_source_failures(monkeypatch):
    barrier = threading.Barrier(2)
    active = 0
    peak = 0
    lock = threading.Lock()
    stored_threads = []

    def good(name):
        def fetch(_fetcher, _cfg):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait(timeout=2)
                return []
            finally:
                with lock:
                    active -= 1
        fetch.__name__ = name
        return fetch

    def broken(_fetcher, _cfg):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(research.config, "research", lambda: {
        "parallel_sources": 3,
        "freshness_days": {},
        "adapters": {
            "first": {"enabled": True},
            "second": {"enabled": True},
            "broken": {"enabled": True},
        },
    })
    monkeypatch.setattr(research, "ADAPTERS", {
        "first": good("first"), "second": good("second"), "broken": broken,
    })
    monkeypatch.setattr(research, "store_source", lambda conn, item, fresh: stored_threads.append(threading.get_ident()) or 1)

    report = research.collect(object(), fetcher=object())

    assert peak == 2
    assert report["first"] == {"ok": True, "items": 0, "new": 0}
    assert report["second"]["ok"] is True
    assert report["broken"]["ok"] is False
    assert "source unavailable" in report["broken"]["error"]
    assert stored_threads == []  # no items means no database work; DB writes remain in the main loop below


def test_collect_stores_results_on_calling_thread(monkeypatch):
    main_thread = threading.get_ident()
    stored_threads = []
    monkeypatch.setattr(research.config, "research", lambda: {
        "parallel_sources": 2,
        "freshness_days": {},
        "adapters": {"first": {"enabled": True}},
    })
    monkeypatch.setattr(research, "ADAPTERS", {"first": lambda *_: [object()]})
    monkeypatch.setattr(research, "store_source", lambda conn, item, fresh: stored_threads.append(threading.get_ident()) or 1)

    report = research.collect(object(), fetcher=object())

    assert report["first"]["new"] == 1
    assert stored_threads == [main_thread]


def test_brainstorm_includes_owner_direction_and_requested_depth():
    captured = {}

    class Router:
        def complete_diverse(self, role, prompt, n_models, **kwargs):
            captured.update(role=role, prompt=prompt, n_models=n_models)
            return [SimpleNamespace(data=SimpleNamespace(ideas=[]))]

    research.brainstorm(Router(), "ai", [], [], n_models=5, brief="Compare open-weight browser agents")

    assert captured["role"] == "brainstormer"
    assert captured["n_models"] == 5
    assert "Compare open-weight browser agents" in captured["prompt"]
    assert "never invent evidence" in captured["prompt"]


def test_research_batch_scopes_channel_and_forwards_mission_controls(monkeypatch):
    calls = []
    audits = []
    monkeypatch.setattr(produce, "apply_brand_overrides", lambda conn: None)
    monkeypatch.setattr(produce.db, "run_lock", lambda conn, name: nullcontext(True))
    monkeypatch.setattr(research, "collect", lambda conn, fetcher: {"first": {"ok": True}})
    monkeypatch.setattr(produce.capacity, "plan_batch", lambda conn: {"long_per_channel": {"ai": 1, "money": 1}})
    monkeypatch.setattr(research, "run_ideas", lambda conn, router, channel, n, week, **kwargs: calls.append((channel, n, kwargs)) or [])
    monkeypatch.setattr(produce.db, "audit", lambda *args: audits.append(args))

    out = produce.research_batch(object(), object(), date(2026, 10, 19), brief="Find practical workflows", channel="ai", n_models=5)

    assert calls == [("ai", 2, {"brief": "Find practical workflows", "n_models": 5})]
    assert out["ideas"] == {"ai": 0}
    assert audits[0][4]["channel"] == "ai"
    assert audits[0][4]["models"] == 5


def test_run_mission_stops_at_review_and_preserves_channel(monkeypatch):
    calls = []
    monkeypatch.setattr(maintenance.produce, "research_batch", lambda *args, **kwargs: calls.append(("research", kwargs)) or {"ideas": {}})
    monkeypatch.setattr(maintenance.produce, "produce_batch", lambda *args, **kwargs: calls.append(("production", kwargs)) or {"projects": []})

    out = maintenance._run_owner_job(object(), object(), object(), {
        "id": "job-1", "job_type": "run_mission", "project_id": None,
        "input": {"brief": "Research AI agents", "channel": "ai", "models": 5},
    })

    assert [name for name, _ in calls] == ["research", "production"]
    assert calls[0][1]["channel"] == "ai"
    assert calls[0][1]["n_models"] == 5
    assert calls[1][1]["channel"] == "ai"
    assert set(out) == {"research", "production"}  # no approval or publishing stage
