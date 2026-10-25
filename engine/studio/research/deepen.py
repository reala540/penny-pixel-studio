"""Deep research for one idea, just before its long video is written.

A feed gives a headline and a line of summary: far too little for an honest 8-14 minute video. Here the studio
reads the full articles behind the idea's sources and adds a few related, independent sources (Wikipedia
background and articles found through Hacker News search). All fetched text is untrusted data: it is stored as
`body_text` and only ever placed inside <source> tags in prompts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse

from pydantic import BaseModel, Field

from .. import config, db
from ..ai.router import Router
from .engine import store_source
from .sources import Fetcher, SourceItem, clean_text

ARTICLE_CHARS = 12000
ENOUGH_TEXT = 9000      # an idea whose sources already hold this much text isn't researched again
MIN_ARTICLE = 800       # shorter pages (paywalls, cookie walls, link lists) are not worth a source slot
MAX_SOURCES = 10
UNREADABLE_HOSTS = ("news.google.com", "news.ycombinator.com", "twitter.com", "x.com", "reddit.com",
                    "youtube.com", "youtu.be", "facebook.com", "tiktok.com", "instagram.com", "linkedin.com")
BOILERPLATE = re.compile(r"cookie|subscribe to|sign up for|newsletter|all rights reserved|javascript", re.I)


class SearchPlan(BaseModel):
    queries: list[str] = Field(default_factory=list, description="2-3 short web search queries (3-6 words each)")
    wikipedia: list[str] = Field(default_factory=list, description="1-3 Wikipedia article titles for background")


def fetcher() -> Fetcher | None:
    """The live fetcher; tests replace this so nothing goes to the network."""
    return Fetcher()


def readable(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return url.lower().startswith(("https://", "http://")) and not any(
        host == h or host.endswith("." + h) for h in UNREADABLE_HOSTS)


def article_text(f: Fetcher, url: str, limit: int = ARTICLE_CHARS) -> str:
    """The readable paragraphs of a web page, or '' when there are none (or the page can't be fetched)."""
    if not readable(url):
        return ""
    try:
        resp = f.get(url)
    except Exception:
        return ""
    if "html" not in resp.headers.get("content-type", "html"):
        return ""
    page = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer|form|aside)\b.*?</\1>", " ", resp.text[:3_000_000])
    paras = [clean_text(p, 3000) for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", page)]
    text = " ".join(p for p in paras if len(p) >= 60 and not BOILERPLATE.search(p))
    return text[:limit] if len(text) >= MIN_ARTICLE else ""


def wikipedia_articles(f: Fetcher, topics: list[str], limit: int = 2) -> list[tuple[SourceItem, str]]:
    out: list[tuple[SourceItem, str]] = []
    for topic in topics:
        if len(out) >= limit:
            break
        try:
            hits = f.get("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=1"
                         f"&srsearch={quote_plus(topic)}").json().get("query", {}).get("search", [])
            if not hits:
                continue
            title = hits[0]["title"]
            pages = f.get("https://en.wikipedia.org/w/api.php?action=query&prop=extracts|info&inprop=url"
                          f"&explaintext=1&redirects=1&format=json&titles={quote_plus(title)}").json()
            page = next(iter(pages.get("query", {}).get("pages", {}).values()), {})
        except Exception:
            continue
        text = clean_text(page.get("extract"), ARTICLE_CHARS)
        if len(text) < MIN_ARTICLE or any(it.title == page.get("title") for it, _ in out):
            continue
        out.append((SourceItem("wikipedia", page.get("title", title), page.get("fullurl") or
                               f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                               publisher="Wikipedia", published_at=datetime.now(timezone.utc), summary=text[:600],
                               credibility="reputable_media", metrics={"query": topic}), text))
    return out


def linked_articles(f: Fetcher, queries: list[str], limit: int = 4) -> list[tuple[SourceItem, str]]:
    """Articles people linked on Hacker News for these searches: a free search API with real publishers' URLs."""
    out: list[tuple[SourceItem, str]] = []
    seen: set[str] = set()
    for q in queries:
        try:
            hits = f.get(f"https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=8&query={quote_plus(q)}").json()["hits"]
        except Exception:
            continue
        for h in hits:
            url = h.get("url") or ""
            host = (urlparse(url).hostname or "").lower().removeprefix("www.")
            if len(out) >= limit or not readable(url) or host in seen:
                continue
            text = article_text(f, url)
            if not text:
                continue
            seen.add(host)  # one article per publisher: independent sources, not one site's view
            when = None
            try:
                when = datetime.fromtimestamp(int(h.get("created_at_i")), timezone.utc)
            except (TypeError, ValueError):
                pass
            out.append((SourceItem("web_article", clean_text(h.get("title"), 300) or host, url, publisher=host,
                                   published_at=when, summary=text[:600], metrics={"query": q, "points": h.get("points")}),
                        text))
    return out


def search_plan(router: Router, idea: dict, channel: str) -> SearchPlan:
    words = " ".join(re.findall(r"[A-Za-z0-9$%()'-]+", idea["title"]))[:80]
    try:
        markets = ", ".join(config.brand()["channels"][channel].get("audience_profile", {}).get("markets", []))
        res = router.complete("research_summarizer", (
            f"Video idea: {idea['title']}\nAngle: {idea.get('angle', '')}\nViewers in: {markets}\n\nSuggest web search "
            "queries that would find solid, specific reporting and data on this topic (not opinion pieces), and "
            "Wikipedia article titles that give background a viewer needs."), schema=SearchPlan, temperature=0.2)
        plan = res.data
    except Exception:  # no AI available for this: search by the title's words
        plan = SearchPlan()
    plan.queries = [q for q in plan.queries if q.strip()][:3] or [words]
    plan.wikipedia = [t for t in plan.wikipedia if t.strip()][:3] or [words]
    return plan


def deepen(conn, router: Router, idea: dict, channel: str) -> dict:
    """Fill in the full text of the idea's sources and add related ones. Safe to run again: it stops early once the
    idea has enough material, and a source is stored once."""
    f = fetcher()
    rows = db.all_(conn, "select id, url, body_text from research_sources where id = any(%s)", (list(idea["source_ids"]),))
    if f is None or sum(len(r["body_text"] or "") for r in rows) >= ENOUGH_TEXT:
        return {"skipped": True}
    filled = 0
    for r in rows:
        if not r["body_text"]:
            text = article_text(f, r["url"])
            if text:
                db.run(conn, "update research_sources set body_text=%s where id=%s", (text, r["id"]))
                filled += 1
    room = MAX_SOURCES - len(rows)
    added: list = []
    if room > 0:
        plan = search_plan(router, idea, channel)
        fresh = config.research().get("freshness_days", {})
        for item, text in (wikipedia_articles(f, plan.wikipedia) + linked_articles(f, plan.queries))[:room]:
            item.topic = channel
            store_source(conn, item, fresh)
            row = db.one(conn, "update research_sources set body_text=coalesce(body_text, %s) where content_hash=%s "
                               "returning id", (text, item.content_hash))
            if row and row["id"] not in idea["source_ids"] and row["id"] not in added:
                added.append(row["id"])
        if added:
            db.run(conn, "update content_ideas set source_ids = source_ids || %s::uuid[] where id=%s",
                   ([str(a) for a in added], idea["id"]))
            idea["source_ids"] = list(idea["source_ids"]) + added
    return {"filled": filled, "added": len(added)}
