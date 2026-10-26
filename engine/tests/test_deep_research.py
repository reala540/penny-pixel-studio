"""Deep research: a long video is written from the full articles behind an idea plus related sources, and an idea
without enough material stops before any writing instead of padding or inventing."""

import httpx
import pytest

from studio import db
from studio.errors import NeedsReview
from studio.research import deepen
from studio.research.sources import Fetcher
from studio.script import pipeline

from .fakes import ScriptedRouter

ARTICLE = "<html><head><script>var x=1;</script></head><body><nav><p>" + "Menu link text that is long enough. " * 3 + \
    "</p></nav>" + "".join(f"<p>Paragraph {i}: the report found that 42% of firms saw no gain from AI tools in 2026, "
                           "and costs rose for most of them.</p>" for i in range(20)) + \
    "<p>Subscribe to our newsletter for more stories like this one, every single week.</p></body></html>"


def web(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    if "list=search" in url:
        return httpx.Response(200, json={"query": {"search": [{"title": "Productivity paradox"}]}})
    if "prop=extracts" in url:
        return httpx.Response(200, json={"query": {"pages": {"1": {"title": "Productivity paradox",
                              "fullurl": "https://en.wikipedia.org/wiki/Productivity_paradox",
                              "extract": "The productivity paradox is the observed slowdown. " * 40}}}})
    if "hn.algolia.com" in url:
        return httpx.Response(200, json={"hits": [
            {"title": "AI and firms", "url": "https://example.org/ai-firms", "created_at_i": 1792800000, "points": 300},
            {"title": "Same site again", "url": "https://example.org/other", "created_at_i": 1792800000},
            {"title": "A tweet", "url": "https://x.com/someone/status/1"}]})
    if "example.org" in url or "apollo.com" in url:
        return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html; charset=utf-8"})
    return httpx.Response(404)


def test_article_text_keeps_the_story_and_drops_menus_scripts_and_boilerplate():
    f = Fetcher(httpx.Client(transport=httpx.MockTransport(web)))
    text = deepen.article_text(f, "https://example.org/ai-firms")
    assert text.startswith("Paragraph 0") and "42%" in text
    assert "var x" not in text and "Menu link" not in text and "newsletter" not in text
    assert deepen.article_text(f, "https://news.google.com/rss/articles/abc") == ""  # can't be read: skipped
    assert deepen.article_text(f, "https://example.com/missing") == ""


def test_an_idea_gets_its_articles_read_and_related_sources_added(synced, monkeypatch):
    c = synced
    src = db.one(c, """insert into research_sources (adapter, title, publisher, url, summary, credibility, topic, content_hash)
                       values ('hacker_news','No signs of AI payoff','Hacker News',
                               'https://www.apollo.com/insights/no-signs-of-ai-payoff','Discussion','community','ai','h1')
                       returning id""")["id"]
    idea = db.one(c, """insert into content_ideas (channel_slug, title, angle, status, source_ids, batch_week)
                        values ('ai','AI ROI reality check','What the data says','selected', array[%s]::uuid[], current_date)
                        returning *""", (src,))
    monkeypatch.setattr(deepen, "fetcher", lambda: Fetcher(httpx.Client(transport=httpx.MockTransport(web))))
    out = deepen.deepen(c, ScriptedRouter(monkeypatch), idea, "ai")
    assert out == {"filled": 1, "added": 2}  # Wikipedia background + one article per publisher; no tweets
    rows = db.all_(c, """select s.adapter, s.publisher, length(s.body_text) n from content_ideas i,
                         unnest(i.source_ids) sid join research_sources s on s.id = sid where i.id=%s""", (idea["id"],))
    assert [r["adapter"] for r in rows] == ["hacker_news", "wikipedia", "web_article"]
    assert all(r["n"] >= deepen.MIN_ARTICLE for r in rows)
    # running again never adds a source twice
    again = db.one(c, "select * from content_ideas where id=%s", (idea["id"],))
    assert deepen.deepen(c, ScriptedRouter(monkeypatch), again, "ai")["added"] == 0
    assert len(db.one(c, "select source_ids from content_ideas where id=%s", (idea["id"],))["source_ids"]) == 3
    monkeypatch.setattr(deepen, "ENOUGH_TEXT", 1000)  # and an idea with plenty of material isn't researched again
    assert deepen.deepen(c, ScriptedRouter(monkeypatch), again, "ai") == {"skipped": True}


def test_too_little_material_stops_before_any_script_is_written(monkeypatch):
    monkeypatch.setattr(pipeline, "MIN_LONG_FACTS", 10)
    router = ScriptedRouter(monkeypatch)
    sources = [{"adapter": "hacker_news", "title": "No signs of AI payoff outside the tech sector", "publisher": "HN",
                "summary": "Discussion", "credibility": "community", "published_at": None, "body_text": None}]
    with pytest.raises(NeedsReview, match="Not enough source material"):
        pipeline.write_long(router, "ai", {"title": "AI ROI", "angle": ""}, sources)
    assert [r for r, _ in router.calls] == ["research_summarizer"]


def test_fact_sheets_read_the_article_text_not_just_the_headline(monkeypatch):
    seen = []
    router = ScriptedRouter(monkeypatch)
    real = router._chat_once

    def spy(cand, role, messages, **kw):
        seen.append(messages[1]["content"])
        return real(cand, role, messages, **kw)
    router._chat_once = spy

    sources = [{"adapter": "web_article", "title": "AI and firms", "publisher": "example.org", "summary": "Short.",
                "credibility": "unrated", "published_at": None, "body_text": "The report found that 42% of firms saw no gain."}]
    facts, _, _ = pipeline.build_fact_sheet(router, {"title": "AI ROI"}, sources)
    assert "42% of firms saw no gain" in seen[0]
    assert facts.facts  # numbers found in the article text count as grounded


def test_a_section_written_too_short_gets_one_follow_up(monkeypatch):
    from studio.script.models import Fact, FactSheet

    monkeypatch.setattr(pipeline, "SHORT_SECTION", 0.6)
    router = ScriptedRouter(monkeypatch)
    facts = FactSheet(facts=[Fact(key=f"F{i}", text=f"Fact {i} from the report.", source_ref="S1") for i in range(1, 7)],
                      context="")
    script, _ = pipeline.draft(router, "ai", {"title": "AI ROI", "angle": ""}, facts)
    follow_ups = sum(1 for sc in script.scenes if sc.visual.headline == "More")
    assert follow_ups >= 1
    assert [r for r, _ in router.calls].count("scriptwriter") == 1 + 7 + follow_ups  # outline, 7 sections, follow-ups
    monkeypatch.setattr(pipeline, "SHORT_SECTION", 0)
    again, _ = pipeline.draft(ScriptedRouter(monkeypatch), "ai", {"title": "AI ROI", "angle": ""}, facts)
    assert not any(sc.visual.headline == "More" for sc in again.scenes)


def test_with_no_voice_editor_free_the_checked_script_goes_on(monkeypatch):
    from studio.errors import QuotaError
    from studio.script.models import Fact, FactSheet

    def no_editor(*a, **k):
        raise QuotaError("All free providers for 'voice_editor' are exhausted or failing")
    monkeypatch.setattr(pipeline, "voice_edit", no_editor)
    router = ScriptedRouter(monkeypatch)
    sources = [{"adapter": "web_article", "title": f"AI and firms {i}", "publisher": f"site{i}.org", "summary": f"Fact {i} is stated.",
                "credibility": "unrated", "published_at": None, "body_text": f"Fact {i} is stated here."} for i in range(4)]
    result = pipeline.write_long(router, "ai", {"title": "AI ROI", "angle": ""}, sources)
    assert result.script.scenes and any(t.get("step") == "voice_edit" and "skipped" in t for t in result.trail)
