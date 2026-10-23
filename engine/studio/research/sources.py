"""Free research adapters. Every item records publisher, URL, publication and retrieval time.

All fetched text is untrusted: it is stored as data and only ever placed inside <source>
tags in prompts.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import quote_plus

import httpx

USER_AGENT = "PennyAndPixelStudio/2.1 (+research bot; contact via repository owner)"


@dataclass
class SourceItem:
    adapter: str
    title: str
    url: str
    publisher: str | None = None
    published_at: datetime | None = None
    event_date: str | None = None
    summary: str = ""
    topic: str = "both"
    credibility: str = "unrated"
    metrics: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.url}|{self.title}".encode()).hexdigest()


def clean_text(text: str | None, limit: int = 1200) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 and Atom → [{title, link, published, summary, source}]."""
    root = ET.fromstring(xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = []
    for it in root.iter("item"):
        src = it.find("source")
        items.append({"title": clean_text(it.findtext("title"), 300), "link": (it.findtext("link") or "").strip(),
                      "published": it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"),
                      "summary": clean_text(it.findtext("description")),
                      "source": src.text.strip() if src is not None and src.text else None})
    for en in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = en.find("a:link[@rel='alternate']", ns)
        if link is None:
            link = en.find("a:link", ns)
        items.append({"title": clean_text(en.findtext("a:title", namespaces=ns), 300),
                      "link": link.get("href") if link is not None else "",
                      "published": en.findtext("a:published", namespaces=ns) or en.findtext("a:updated", namespaces=ns),
                      "summary": clean_text(en.findtext("a:summary", namespaces=ns) or en.findtext("a:content", namespaces=ns)),
                      "source": None})
    return [i for i in items if i["title"] and i["link"]]


class Fetcher:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=30.0, follow_redirects=True,
                                              headers={"User-Agent": USER_AGENT})

    def get(self, url: str, **kw) -> httpx.Response:
        resp = self.client.get(url, **kw)
        resp.raise_for_status()
        return resp


# ---------------------------------------------------------------------------- adapters

def google_news(f: Fetcher, cfg: dict) -> list[SourceItem]:
    out = []
    for topic, queries in (cfg.get("queries") or {}).items():
        for q in queries:
            url = (f"https://news.google.com/rss/search?q={quote_plus(q)}+when:7d"
                   f"&hl={cfg.get('hl', 'en-US')}&gl={cfg.get('gl', 'US')}&ceid={cfg.get('gl', 'US')}:en")
            for i in parse_feed(f.get(url).text)[:8]:
                out.append(SourceItem("google_news_rss", i["title"], i["link"], publisher=i["source"],
                                      published_at=parse_date(i["published"]), summary=i["summary"],
                                      topic=topic, credibility="reputable_media" if i["source"] else "unrated",
                                      metrics={"query": q}))
    return out


def google_trends(f: Fetcher, cfg: dict) -> list[SourceItem]:
    out = []
    for geo in cfg.get("geo", ["US"]):
        root = ET.fromstring(f.get(f"https://trends.google.com/trending/rss?geo={geo}").text)
        for it in root.iter("item"):
            traffic = it.findtext("{https://trends.google.com/trending/rss}approx_traffic") or ""
            title = clean_text(it.findtext("title"), 200)
            out.append(SourceItem("google_trends_rss", f"Trending search: {title}",
                                  f"https://trends.google.com/trends/explore?geo={geo}&q={quote_plus(title)}",
                                  publisher="Google Trends", published_at=parse_date(it.findtext("pubDate")),
                                  summary=f"Approx. traffic {traffic} in {geo}", topic="both",
                                  credibility="primary_data",
                                  metrics={"traffic": traffic, "geo": geo, "term": title}))
    return out


def hacker_news(f: Fetcher, cfg: dict) -> list[SourceItem]:
    since = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
    out = []
    for kw in cfg.get("keywords", []):
        data = f.get("https://hn.algolia.com/api/v1/search",
                     params={"query": kw, "tags": "story",
                             "numericFilters": f"points>{cfg.get('min_points', 150)},created_at_i>{since}"}).json()
        for h in data.get("hits", [])[:5]:
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
            out.append(SourceItem("hacker_news", clean_text(h.get("title"), 300), url, publisher="Hacker News",
                                  published_at=parse_date(h.get("created_at")), topic="ai", credibility="community",
                                  summary=f"{h.get('points', 0)} points, {h.get('num_comments', 0)} comments",
                                  metrics={"points": h.get("points", 0), "comments": h.get("num_comments", 0),
                                           "discussion": f"https://news.ycombinator.com/item?id={h['objectID']}"}))
    return out


def official_feeds(f: Fetcher, cfg: dict) -> list[SourceItem]:
    out = []
    for feed in cfg.get("feeds", []):
        try:
            items = parse_feed(f.get(feed["url"]).text)
        except Exception:
            continue  # one broken feed must not stop the batch
        for i in items[:10]:
            out.append(SourceItem("official_feeds", i["title"], i["link"], publisher=feed["name"],
                                  published_at=parse_date(i["published"]), summary=i["summary"],
                                  topic=feed.get("topic", "both"), credibility=feed.get("credibility", "official")))
    return out


def reddit_rss(f: Fetcher, cfg: dict) -> list[SourceItem]:
    out = []
    for topic, subs in (cfg.get("subreddits") or {}).items():
        for sub in subs:
            try:
                items = parse_feed(f.get(f"https://www.reddit.com/r/{sub}/top/.rss?t=week").text)
            except Exception:
                continue
            for i in items[:8]:
                out.append(SourceItem("reddit_rss", i["title"], i["link"], publisher=f"r/{sub}",
                                      published_at=parse_date(i["published"]), summary=i["summary"][:400],
                                      topic=topic, credibility="community"))
    return out


def youtube_search(f: Fetcher, cfg: dict, queries: list[tuple[str, str]] | None = None) -> list[SourceItem]:
    key = os.environ.get(cfg.get("key_env", "YOUTUBE_API_KEY"), "")
    if not key:
        return []
    out = []
    published_after = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for topic, q in (queries or [])[: cfg.get("max_searches_per_batch", 8)]:
        data = f.get("https://www.googleapis.com/youtube/v3/search",
                     params={"part": "snippet", "q": q, "type": "video", "order": "viewCount", "maxResults": 10,
                             "publishedAfter": published_after, "key": key}).json()
        ids = [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]
        stats = {}
        if ids:
            vd = f.get("https://www.googleapis.com/youtube/v3/videos",
                       params={"part": "statistics", "id": ",".join(ids), "key": key}).json()
            stats = {v["id"]: v.get("statistics", {}) for v in vd.get("items", [])}
        for it in data.get("items", []):
            vid = it.get("id", {}).get("videoId")
            if not vid:
                continue
            sn = it["snippet"]
            out.append(SourceItem("youtube_search", clean_text(sn.get("title"), 300),
                                  f"https://www.youtube.com/watch?v={vid}", publisher=sn.get("channelTitle"),
                                  published_at=parse_date(sn.get("publishedAt")), summary=clean_text(sn.get("description"), 400),
                                  topic=topic, credibility="community",
                                  metrics={"views": int(stats.get(vid, {}).get("viewCount", 0) or 0), "query": q,
                                           "competitor": True}))
    return out


def fred(f: Fetcher, cfg: dict) -> list[SourceItem]:
    key = os.environ.get(cfg.get("key_env", "FRED_API_KEY"), "")
    if not key:
        return []
    out = []
    for s in cfg.get("series", []):
        data = f.get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id": s["id"], "api_key": key, "file_type": "json", "sort_order": "desc",
                             "limit": 13}).json()
        obs = [o for o in data.get("observations", []) if o.get("value") not in (".", None)]
        if not obs:
            continue
        latest, year_ago = obs[0], obs[-1]
        summary = (f"{s['name']} ({s['id']}): {latest['value']} for the period starting {latest['date']}; "
                   f"{year_ago['value']} for the period starting {year_ago['date']}.")
        out.append(SourceItem("fred", f"{s['name']} — latest official data", f"https://fred.stlouisfed.org/series/{s['id']}",
                              publisher="Federal Reserve Bank of St. Louis (FRED)", published_at=datetime.now(timezone.utc),
                              event_date=latest["date"], summary=summary, topic="money", credibility="primary_data",
                              metrics={"series": s["id"], "observations": obs[:13]}))
    return out


def sec_edgar(f: Fetcher, cfg: dict) -> list[SourceItem]:
    ua = os.environ.get(cfg.get("user_agent_env", "SEC_USER_AGENT"), "")
    if not ua:
        return []
    headers = {"User-Agent": ua}
    tickers = f.get("https://www.sec.gov/files/company_tickers.json", headers=headers).json()
    by_ticker = {v["ticker"]: v for v in tickers.values()}
    out = []
    for t in cfg.get("companies", []):
        info = by_ticker.get(t)
        if not info:
            continue
        cik = str(info["cik_str"]).zfill(10)
        sub = f.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers).json()
        recent = sub.get("filings", {}).get("recent", {})
        for form, date, acc, doc in list(zip(recent.get("form", []), recent.get("filingDate", []),
                                             recent.get("accessionNumber", []), recent.get("primaryDocument", [])))[:15]:
            if form not in ("10-K", "10-Q", "8-K"):
                continue
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
            out.append(SourceItem("sec_edgar", f"{info['title']} filed a {form}", url, publisher="SEC EDGAR",
                                  published_at=parse_date(date + "T00:00:00+00:00"), event_date=date,
                                  summary=f"{info['title']} ({t}) {form} filed {date}.", topic="money",
                                  credibility="official", metrics={"ticker": t, "form": form}))
    return out


def wikipedia_summary(f: Fetcher, title: str) -> SourceItem | None:
    try:
        data = f.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(title.replace(' ', '_'))}").json()
    except Exception:
        return None
    if data.get("type") == "disambiguation" or not data.get("extract"):
        return None
    return SourceItem("wikipedia", data.get("title", title), data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                      publisher="Wikipedia", published_at=parse_date(data.get("timestamp")), summary=data["extract"][:1200],
                      topic="both", credibility="reputable_media")


ADAPTERS: dict[str, Callable[[Fetcher, dict], list[SourceItem]]] = {
    "google_news_rss": google_news,
    "google_trends_rss": google_trends,
    "hacker_news": hacker_news,
    "official_feeds": official_feeds,
    "reddit_rss": reddit_rss,
    "fred": fred,
    "sec_edgar": sec_edgar,
}
