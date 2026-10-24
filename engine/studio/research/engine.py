"""Research batch: collect sources, brainstorm ideas with several models, score and shortlist."""

from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field

from .. import config, db, similarity
from ..ai.router import Router
from .sources import ADAPTERS, Fetcher, SourceItem

AI_WORDS = set("ai llm gpt model models chatbot openai anthropic claude gemini nvidia agent agents robot automation "
               "machine learning neural chip chips software app tool tools deepmind copilot mistral open-source".split())
MONEY_WORDS = set("money finance financial budget budgeting invest investing investment stock stocks salary pay "
                  "inflation rate rates interest mortgage debt loan loans savings save tax taxes economy economic "
                  "jobs job career income bank banks credit retirement pension wealth price prices".split())
CRED_WEIGHT = {"official": 1.0, "primary_data": 1.0, "reputable_media": 0.7, "community": 0.4, "unrated": 0.3}


def classify_topic(text: str, default: str = "both") -> str:
    words = set(re.findall(r"[a-z\-]+", text.lower()))
    ai, money = len(words & AI_WORDS), len(words & MONEY_WORDS)
    if ai and money:
        return "both"
    if ai:
        return "ai"
    if money:
        return "money"
    return default


# ----------------------------------------------------------------------------- collect

def collect(conn, fetcher: Fetcher | None = None) -> dict:
    """Fetch independent adapters concurrently, then store results deterministically.

    httpx clients support concurrent requests. The database connection never crosses
    threads, which keeps psycopg and transaction behaviour unchanged.
    """
    cfg = config.research()
    fetcher = fetcher or Fetcher()
    fresh = cfg.get("freshness_days", {})
    enabled = [(name, adapter_cfg) for name, adapter_cfg in (cfg.get("adapters") or {}).items()
               if adapter_cfg.get("enabled") and name in ADAPTERS]

    def fetch_one(entry):
        name, adapter_cfg = entry
        try:
            return name, ADAPTERS[name](fetcher, adapter_cfg), None
        except Exception as exc:  # one source must not break the batch
            return name, [], str(exc)[:300]

    report: dict[str, dict] = {}
    workers = max(1, min(int(cfg.get("parallel_sources", 6)), len(enabled) or 1))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="studio-research") as pool:
        fetched = list(pool.map(fetch_one, enabled))
    for name, items, error in fetched:
        if error is not None:
            report[name] = {"ok": False, "error": error, "items": 0}
            continue
        stored = sum(store_source(conn, it, fresh) for it in items)
        report[name] = {"ok": True, "items": len(items), "new": stored}
    return report


def store_source(conn, it: SourceItem, fresh_days: dict) -> int:
    if not it.url.lower().startswith(("https://", "http://")):
        return 0  # untrusted feeds: only web links are stored (no javascript:, data:, file: ...)
    # the text decides first; the query/feed topic is only the tie-breaker
    topic = classify_topic(f"{it.title} {it.summary}", default=it.topic if it.topic in ("ai", "money") else "both")
    base = it.published_at or datetime.now(timezone.utc)
    fresh_until = base + timedelta(days=int(fresh_days.get(topic if topic != "both" else "ai", 14)))
    row = db.one(conn, """
        insert into research_sources (adapter, title, publisher, url, published_at, event_date, summary,
                                      body_excerpt, credibility, topic, fresh_until, content_hash)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (content_hash) do update
           set topic = case when research_sources.topic <> excluded.topic then 'both' else research_sources.topic end
        returning id, (xmax = 0) as inserted""",
        (it.adapter, it.title, it.publisher, it.url, it.published_at, it.event_date, it.summary,
         db.dumps(it.metrics) if it.metrics else None, it.credibility, topic, fresh_until, it.content_hash))
    return 1 if row and row["inserted"] else 0


# ----------------------------------------------------------------------------- ideas

class IdeaPitch(BaseModel):
    title: str = Field(description="Working video title, specific, under 70 characters")
    angle: str = Field(description="The original angle: what this video says that others don't")
    why_now: str = Field(description="Why this matters to the audience this week")
    source_refs: list[str] = Field(description="Source labels like S3 that support the idea")
    evergreen: bool = False


class IdeaPitches(BaseModel):
    ideas: list[IdeaPitch]


def recent_sources(conn, channel: str, days: int = 21, limit: int = 60) -> list[dict]:
    return db.all_(conn, """
        select id, adapter, title, publisher, url, published_at, summary, credibility, topic, body_excerpt
          from research_sources
         where topic in (%s, 'both') and retrieved_at > now() - make_interval(days => %s)
         order by (credibility in ('official','primary_data')) desc, published_at desc nulls last
         limit %s""", (channel, days, limit))


def source_block(sources: list[dict]) -> str:
    lines = []
    for i, s in enumerate(sources, 1):
        when = s["published_at"].date().isoformat() if s.get("published_at") else "date unknown"
        lines.append(f'<source id="S{i}" publisher="{s.get("publisher") or s["adapter"]}" published="{when}" '
                     f'credibility="{s["credibility"]}">{s["title"]} — {(s.get("summary") or "")[:300]}</source>')
    return "\n".join(lines)


def brainstorm(router: Router, channel: str, sources: list[dict], past_titles: list[str], n_models: int = 3,
               brief: str = "") -> list[dict]:
    ch = config.brand()["channels"][channel]
    prompt = (
        f"Channel: {ch['display_name']}. Host: {ch['host_persona']}\nFocus: {ch['topic_focus']}\n"
        f"Audience: {ch['audience_profile']['who']}\n\n"
        f"Recent sources:\n{source_block(sources)}\n\n"
        f"Already covered (do not repeat): {'; '.join(past_titles[:40]) or 'nothing yet'}\n\n"
        + (f"Owner direction for this mission (prioritise this, but never invent evidence): {brief.strip()}\n\n" if brief.strip() else "")
        + "Pitch 4 video ideas. Each must be backed by at least one source above, have a genuinely original "
        "angle (a test, a comparison, the math, the hidden trade-off, the 'what it means for you'), and avoid hype. "
        "Prefer ideas where we can show original charts, numbers or step-by-step demos."
    )
    results = router.complete_diverse("brainstormer", prompt, n_models, schema=IdeaPitches, temperature=0.9)
    pitches = []
    for res in results:
        for idea in res.data.ideas:
            refs = [int(r[1:]) - 1 for r in idea.source_refs if re.fullmatch(r"S\d+", r) and 0 < int(r[1:]) <= len(sources)]
            if not refs:
                continue  # no evidence -> not eligible
            pitches.append({**idea.model_dump(), "source_ids": [sources[i]["id"] for i in refs],
                            "sources": [sources[i] for i in refs], "proposed_by": res.provider})
    return pitches


# ----------------------------------------------------------------------------- scoring

def score_idea(idea: dict, channel: str, all_recent: list[dict], history_titles: list[str],
               router: Router | None = None, weights: dict | None = None) -> dict:
    cfg = config.research()
    weights = weights or cfg["scoring_weights"]
    ch = config.brand()["channels"][channel]
    text = f"{idea['title']} {idea['angle']}"
    now = datetime.now(timezone.utc)
    srcs = idea["sources"]

    evidence = min(sum(CRED_WEIGHT.get(s["credibility"], 0.3) for s in srcs) / 2.5, 1.0)
    ages = [(now - s["published_at"]).days for s in srcs if s.get("published_at")]
    window = cfg["freshness_days"].get(channel, 14)
    freshness = 0.6 if idea.get("evergreen") else (max(0.0, 1 - min(ages) / window) if ages else 0.3)
    recent = [s for s in all_recent if s.get("published_at") and (now - s["published_at"]).days <= 3]
    momentum = min(sum(1 for s in recent if similarity.lexical_similarity(text, s["title"]) > 0.12) / 4, 1.0)

    trends = [s for s in all_recent if s["adapter"] == "google_trends_rss"]
    yt = [s for s in all_recent if s["adapter"] == "youtube_search"]
    demand = 0.4
    if trends:
        demand = max([0.4] + [0.9 for s in trends if similarity.lexical_similarity(text, s["title"]) > 0.15])
    competition = 0.5
    if yt:
        similar = [s for s in yt if similarity.lexical_similarity(text, s["title"]) > 0.2]
        competition = 1 - min(len(similar) / 5, 1.0)
        if similar:
            demand = max(demand, min(math.log10(1 + max(_views(s) for s in similar)) / 6, 1.0))

    sim, idx, method = similarity.max_similarity(text, history_titles, router)
    repeat = similarity.is_repeat(sim, method)
    originality = 0.0 if repeat else round(1 - sim, 3)
    profile = f"{ch['topic_focus']} {ch['audience_profile']['who']}"
    fit = min(similarity.lexical_similarity(text, profile) * 4, 1.0)
    topic_ok = classify_topic(text, channel) in (channel, "both")
    brand_fit = fit if topic_ok else fit * 0.3
    monetization = 0.9 if channel == "money" else 0.75
    feasibility = 0.85 if re.search(r"\d|chart|math|step|test|compare|vs\b|how to", text.lower()) else 0.6

    features = {"audience_relevance": round(max(fit, 0.3), 3), "search_demand": round(demand, 3),
                "trend_momentum": round(momentum, 3), "freshness": round(freshness, 3),
                "originality": originality, "evidence": round(evidence, 3), "brand_fit": round(brand_fit, 3),
                "competition": round(competition, 3), "monetization": monetization,
                "feasibility": feasibility, "history": 0.5}
    total = round(100 * sum(weights[k] * features[k] for k in weights), 2)
    if repeat:
        total = round(total * 0.3, 2)
    top = sorted(((weights[k] * v, k) for k, v in features.items() if k in weights), reverse=True)[:3]
    reasons = ", ".join(k.replace("_", " ") for _, k in top)
    explanation = f"Strongest signals: {reasons}. Backed by {len(srcs)} source(s)."
    if repeat:
        explanation += f" Penalised: too similar to '{history_titles[idx]}'."
    if not ages and not idea.get("evergreen"):
        explanation += " Publication dates unknown — freshness uncertain."
    return {"score": total, "features": features, "explanation": explanation, "repeat": repeat}


def _views(s: dict) -> int:
    import json
    try:
        return int(json.loads(s.get("body_excerpt") or "{}").get("views", 0))
    except (ValueError, TypeError):
        return 0


def pick(scored: list[dict], n: int, experiment_share: float) -> list[dict]:
    """Top ideas by score, reserving ~experiment_share of slots for the best 'different' ideas."""
    eligible = sorted([s for s in scored if not s["repeat"]], key=lambda s: s["score"], reverse=True)
    n_exp = int(round(n * experiment_share)) if n >= 3 else 0
    main = eligible[: n - n_exp]
    rest = [s for s in eligible if s not in main]
    # experiments: highest originality among the remainder
    exp = sorted(rest, key=lambda s: s["features"]["originality"], reverse=True)[:n_exp]
    for e in exp:
        e["is_experiment"] = True
    return main + exp


def week_start(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def run_ideas(conn, router: Router, channel: str, n: int, week: date, *, brief: str = "",
              n_models: int = 3) -> list[dict]:
    sources = recent_sources(conn, channel)
    if not sources:
        return []
    history = [r["title"] for r in db.all_(conn, """
        select title from content_projects where channel_slug=%s
        union all select title from content_ideas where channel_slug=%s and batch_week < %s
        order by 1 limit 400""", (channel, channel, week))]
    pitches = brainstorm(router, channel, sources[:40], history, n_models=max(1, min(n_models, 5)), brief=brief)
    # drop near-duplicate pitches from different models
    unique: list[dict] = []
    for p in pitches:
        if all(similarity.lexical_similarity(p["title"], u["title"]) < 0.5 for u in unique):
            unique.append(p)
    scored = []
    for p in unique:
        s = score_idea(p, channel, sources, history, router)
        scored.append({**p, **s})
    picks = pick(scored, n, config.research().get("experiment_share", 0.3))
    pick_titles = {p["title"] for p in picks}
    out = []
    for s in scored:
        status = "shortlisted" if s["title"] in pick_titles else "proposed"
        row = db.one(conn, """
            insert into content_ideas (channel_slug, title, angle, status, score, score_breakdown, explanation,
                                       is_experiment, source_ids, batch_week)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
            (channel, s["title"], s["angle"], status, s["score"],
             db.j({**s["features"], "why_now": s["why_now"], "proposed_by": s["proposed_by"],
                   "evergreen": bool(s.get("evergreen"))}),
             s["explanation"], bool(s.get("is_experiment")), s["source_ids"], week))
        out.append(row)
    return out
