"""AI Idea Generator: 70% measured trend weight, evidence, dedupe, diversity, honesty and approval boundaries."""

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from studio import db, maintenance
from studio.ideas import generator as g
from studio.ideas.generator import Assessment, AssessmentList, CandidateList

NOW = datetime.now(timezone.utc)


def src(conn, adapter, title, days, publisher, url=None, topic="ai", metrics="{}", cred="reputable_media"):
    url = url or f"https://example.org/{hashlib.md5(title.encode()).hexdigest()[:8]}"
    return db.one(conn, """insert into research_sources (adapter, title, publisher, url, published_at, summary, credibility,
                           topic, body_excerpt, content_hash) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                  (adapter, title, publisher, url, NOW - timedelta(days=days), f"About {title}", cred, topic, metrics,
                   hashlib.sha256(url.encode()).hexdigest()))["id"]


@pytest.fixture
def sources(synced):
    c = synced
    src(c, "google_trends_rss", "Trending search: ai agents", 0.5, "Google Trends", topic="both",
        metrics='{"traffic": "200K+", "geo": "US", "term": "ai agents"}', cred="primary_data")
    src(c, "google_news_rss", "Browser agents arrive in office suites", 1, "Reuters")
    src(c, "hacker_news", "Show HN: an open-source browser agent", 2, "Hacker News", metrics='{"points": 640, "comments": 210}',
        cred="community")
    src(c, "google_news_rss", "Central banks hold rates", 3, "AP", topic="money")
    src(c, "official_feeds", "BLS: wages rose last month", 4, "BLS latest numbers", topic="money", cred="primary_data")
    src(c, "reddit_rss", "Budget apps that actually work", 5, "r/personalfinance", topic="money", cred="community")
    src(c, "google_news_rss", "Old story about chatbots", 40, "Old Times")       # outside the 14-day window
    return c


TOPICS = [
    ("Browser agents: we test what they can really do", "AI tools", "ai", ["E1", "E2", "E3"]),
    ("Do browser agents make office work faster? A timed test", "AI tools", "ai", ["E1", "E2", "E3"]),  # near-duplicate
    ("What rate holds mean for your savings in five countries", "Personal finance", "money", ["E4"]),
    ("Wages are rising: the math on what it buys", "Careers", "money", ["E5"]),
    ("Budget apps compared on the features that matter", "Personal finance", "money", ["E6"]),
    ("Open-source agents versus paid ones: total cost", "AI tools", "ai", ["E3"]),
    ("A beginner's map of AI agent risks at work", "AI safety", "ai", ["E2"]),
    ("Timeless: how compound interest actually works", "Personal finance", "money", []),   # no evidence
    ("The hidden trade-off of letting AI book your travel", "AI tools", "ai", ["E99"]),     # invalid citation
    ("Salary negotiation scripts tested on real offers", "Careers", "money", ["E5"]),
    ("Prompting vs. agents: when to use which", "AI tools", "ai", ["E1"]),
    ("Saving for school fees: a three-country comparison", "Personal finance", "money", ["E4", "E6"]),
    ("Can an AI agent do your taxes? We check the limits", "AI tools", "ai", ["E2", "E4"]),
    ("Side income ideas ranked by real hourly pay", "Careers", "money", ["E6"]),
    ("Why your AI assistant forgets: memory explained", "AI explainers", "ai", ["E3"]),
]


class FakeRouter:
    """Answers brainstormer/critic like real providers would, and records what it was asked."""

    def __init__(self, fail_assessment=False, ideas=TOPICS):
        self.calls = []
        self.fail_assessment = fail_assessment
        self.ideas = ideas

    def complete(self, role, prompt, schema=None, exclude=None, **kw):
        self.calls.append((role, set(exclude or ())))
        if role == "brainstormer" and schema is CandidateList:
            if "Owner's note" in prompt:
                data = {"ideas": [{"title": "Browser agents, tested on five real office tasks", "summary": "Sharper.",
                                   "audience": "Office workers", "markets": ["Global"], "category": "AI tools",
                                   "channel": "ai", "evidence": [], "trend_angle": "", "suggested_format": "long video",
                                   "execution": "Five timed tasks"}]}
            else:
                data = {"ideas": [{"title": t, "summary": f"{t}. A clear, practical look for viewers.",
                                   "audience": "Curious adults", "markets": ["Global"], "category": cat, "channel": ch,
                                   "evidence": ev, "trend_angle": "Current coverage", "suggested_format": "long video",
                                   "execution": "Charts and a screen demo"} for t, cat, ch, ev in self.ideas]}
            return SimpleNamespace(data=CandidateList.model_validate(data), provider="alpha", model="a1",
                                   substituted_from=None)
        if role == "critic" and schema is AssessmentList:
            if self.fail_assessment:
                raise RuntimeError("all reviewers busy")
            keys = [line.split(":")[0] for line in prompt.splitlines() if line[:1] == "I" and line[1:2].isdigit()]
            return SimpleNamespace(data=AssessmentList(assessments=[
                Assessment(id=k, originality=7, international=6, feasibility=8, engagement=7,
                           rationale="Clear angle.") for k in keys]), provider="beta", model="b1",
                substituted_from="gamma/g1")
        raise AssertionError(role)


def test_weights_are_exactly_70_10_10_5_5():
    assert g.WEIGHTS == {"trend": 70, "originality": 10, "international": 10, "feasibility": 5, "engagement": 5}
    full = Assessment(id="I1", originality=10, international=10, feasibility=10, engagement=10, rationale="")
    none = Assessment(id="I1", originality=0, international=0, feasibility=0, engagement=0, rationale="")
    assert g.score_idea(1.0, full, 0)[0] == 100
    assert g.score_idea(1.0, none, 0)[0] == 70          # perfect trend alone is worth 70
    assert g.score_idea(0.0, full, 0)[0] == 30          # perfect assessment alone is worth 30
    assert g.score_idea(0.5, None, 0)[0] == 35          # no assessment: nothing invented for the other 30


def test_trend_score_is_measured_from_evidence():
    assert g.trend_score([]) == (0.0, {"independent_sources": 0, "newest_age_days": None, "signal_strength": 0,
                                       "source_types": 0}, "unverified")
    fresh = [{"adapter": a, "publisher": p, "published_at": NOW - timedelta(days=d), "retrieved_at": NOW, "metrics": {}}
             for a, p, d in (("google_trends_rss", "Google Trends", 0.2), ("google_news_rss", "Reuters", 1),
                             ("hacker_news", "Hacker News", 2), ("google_news_rss", "AP", 1))]
    high, parts, conf = g.trend_score(fresh)
    assert conf == "high" and parts["independent_sources"] == 4 and high > 0.9
    old = [{"adapter": "reddit_rss", "publisher": "r/x", "published_at": NOW - timedelta(days=12), "retrieved_at": NOW,
            "metrics": {}}]
    low, _, conf_low = g.trend_score(old)
    assert conf_low == "low" and low < 0.4


def test_generates_exactly_ten_ranked_evidence_backed_ideas(sources):
    c = sources
    router = FakeRouter()
    out = g.run(c, router, overrides={"refresh_sources": False, "notify": False})
    ideas = db.all_(c, "select * from generated_ideas order by rank")
    assert out["status"] == "completed" and len(ideas) == 10
    assert [i["rank"] for i in ideas] == list(range(1, 11))
    assert [float(i["total"]) for i in ideas] == sorted((float(i["total"]) for i in ideas), reverse=True)
    titles = [i["title"] for i in ideas]
    assert not ({"Browser agents: we test what they can really do",
                 "Do browser agents make office work faster? A timed test"} <= set(titles))   # near-twins never both
    for i in ideas:
        expected = sum(g.WEIGHTS[k] * float(i["scores"][k]) for k in g.WEIGHTS)
        assert float(i["total"]) == pytest.approx(expected, abs=0.1)              # 70% trend weighting applied
        assert "opinion, not a measurement" in i["score_explanation"]
        for s in i["trend_signals"]:                                              # every link is a stored source
            assert db.one(c, "select 1 from research_sources where id=%s and url=%s", (s["source_id"], s["url"]))
            assert s["published_at"] and "Old story" not in s["title"]          # dated, within the window
    top = ideas[0]
    assert top["trend_verified"] and top["confidence"] in ("high", "medium")
    assert any("200K+" in s["observed"] for i in ideas for s in i["trend_signals"])  # the source's own number, verbatim
    # the assessor is a different provider from the proposer, and substitutions are reported
    assert ("critic", {"alpha"}) in router.calls
    run = db.one(c, "select * from idea_runs")
    assert any("gamma/g1 was unavailable" in n for n in run["notes"])


def test_unsupported_ideas_are_labelled_trend_unverified(sources):
    c = sources
    g.run(c, FakeRouter(), overrides={"refresh_sources": False, "notify": False, "count": 15})
    rows = {r["title"]: r for r in db.all_(c, "select * from generated_ideas")}
    for t in ("Timeless: how compound interest actually works", "The hidden trade-off of letting AI book your travel"):
        r = rows[t]
        assert r["trend_verified"] is False and r["confidence"] == "unverified"
        assert float(r["scores"]["trend"]) == 0 and r["trend_signals"] == []   # the invalid E99 citation was dropped
        assert r["sensitivity"] == "poorly_supported" and "Trend unverified" in r["score_explanation"]


def test_past_ideas_are_not_repeated(sources):
    c = sources
    g.run(c, FakeRouter(), overrides={"refresh_sources": False, "notify": False})
    first = {r["title"] for r in db.all_(c, "select title from generated_ideas")}
    out = g.run(c, FakeRouter(), overrides={"refresh_sources": False, "notify": False})
    second = {r["title"] for r in db.all_(c, "select title from generated_ideas where run_id=%s", (out["run_id"],))}
    assert not (first & second)


def test_failed_assessment_scores_on_evidence_only_and_says_so(sources):
    c = sources
    g.run(c, FakeRouter(fail_assessment=True), overrides={"refresh_sources": False, "notify": False})
    run = db.one(c, "select * from idea_runs")
    assert any("AI assessment failed" in n for n in run["notes"])
    for r in db.all_(c, "select * from generated_ideas"):
        assert float(r["total"]) <= 70 and "assessment unavailable" in r["score_explanation"]


def test_generation_never_starts_production_or_publishing(sources):
    c = sources
    before = {t: db.one(c, f"select count(*) n from {t}")["n"]
              for t in ("content_ideas", "content_projects", "scheduled_posts", "published_posts")}
    g.run(c, FakeRouter(), overrides={"refresh_sources": False, "notify": False})
    after = {t: db.one(c, f"select count(*) n from {t}")["n"] for t in before}
    assert before == after


def test_queued_owner_job_runs_through_the_queue(sources):
    c = sources
    db.run(c, """insert into generation_jobs (job_type, idempotency_key, status, requested_by, input)
                 values ('generate_ideas', 'ideas:manual:1', 'queued', 'owner',
                         '{"trigger":"manual","overrides":{"refresh_sources":false,"notify":false}}')""")
    done = maintenance.process_owner_jobs(c, FakeRouter(), storage=None)
    assert done and done[0]["status"] == "completed"
    assert db.one(c, "select status, produced_count from idea_runs")["produced_count"] == 10


def test_refine_keeps_research_and_records_history(sources):
    c = sources
    g.run(c, FakeRouter(), overrides={"refresh_sources": False, "notify": False})
    idea = db.one(c, "select * from generated_ideas where trend_verified order by rank limit 1")
    g.refine(c, FakeRouter(), idea["id"], "Make it more practical for office workers")
    after = db.one(c, "select * from generated_ideas where id=%s", (idea["id"],))
    assert after["title"] == "Browser agents, tested on five real office tasks"
    assert after["trend_signals"] == idea["trend_signals"]
    assert after["status_history"][-1]["status"] == "refined"


def test_config_is_validated_and_shapes_research():
    cfg = g.validate_config({"count": 99, "region": ["us", "Kenya", "gb"], "channels": ["ai", "bogus"],
                             "sources": ["google_trends_rss", "made_up"], "hour": 40, "min_score": -5,
                             "categories": ["AI tools", "", "Personal finance"], "frequency": "hourly"})
    assert cfg["count"] == 30 and cfg["region"] == ["US", "GB"] and cfg["channels"] == ["ai"]
    assert cfg["sources"] == ["google_trends_rss"] and cfg["hour"] == 23 and cfg["min_score"] == 0
    assert cfg["frequency"] == "manual" and cfg["categories"] == ["AI tools", "Personal finance"]
    rc = g.research_config_for(cfg)
    assert rc["adapters"]["google_trends_rss"]["geo"] == ["US", "GB"]
    assert rc["adapters"]["google_news_rss"]["enabled"] is False          # not an allowed source
    glob = g.research_config_for(g.validate_config({"categories": ["AI tools"]}))
    assert "AI tools" in glob["adapters"]["google_news_rss"]["queries"]["ai"]
    assert glob["adapters"]["google_trends_rss"]["geo"] == g.GLOBAL_TRENDS_GEOS
