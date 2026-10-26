"""Telegram links open the exact item, using the same rules as the dashboard (lib/activity.ts jobDestination)."""
from datetime import datetime, timezone

from studio import links


def test_links_point_at_the_exact_item(monkeypatch):
    monkeypatch.setattr(links, "_base", lambda: "https://studio.test")
    assert links.post("p1") == "https://studio.test/calendar?post=p1"
    assert links.project("x", "posts") == "https://studio.test/content/x?tab=posts"
    assert links.idea_run("r9") == "https://studio.test/content/ideas?source=generator&run=r9"
    assert links.needs_you() == "https://studio.test/content?tab=needs-you"
    assert links.research_since(datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)) == \
        "https://studio.test/content/ideas?source=research&since=2026-10-26T08%3A00%3A00%2B00%3A00"


def test_job_links_match_the_dashboard(monkeypatch):
    monkeypatch.setattr(links, "_base", lambda: "https://studio.test")
    assert links.job({"id": "j1", "job_type": "check_providers", "input": {}}) == "https://studio.test/settings/ai?job=j1#key-check"
    assert links.job({"id": "j2", "job_type": "produce_idea", "input": {"generated_idea_id": "g1", "channel": "ai"}}) == \
        "https://studio.test/create?step=progress&kind=generated&id=g1&channel=ai"
    assert links.job({"id": "j3", "job_type": "regenerate_script", "project_id": "p7", "input": {}}) == "https://studio.test/content/p7"
    assert links.job({"id": "j4", "job_type": "run_research", "input": {}}) == "https://studio.test/activity?job=j4#job-detail"
