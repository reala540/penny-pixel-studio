"""Evidence handling before and during writing.

Every usable fact keeps a stable link to the passage that states it, the source's id and its publication date, so
the same evidence can be shown to the checker for any later version of the script (it is saved with the script).
Sources that have nothing to do with the topic are set aside before facts are extracted. Old figures are marked
historical, so a script must say when they applied instead of presenting them as current.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .. import config
from .models import Fact, FactSheet

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "from", "is", "are", "be",
        "how", "what", "why", "your", "you", "this", "that", "it", "its", "as", "vs", "versus", "into", "about", "do",
        "does", "can", "will", "new", "real", "really", "actually", "explained", "guide", "revealed", "inside", "more"}
PASSAGE_CHARS = 420     # the quoted passage kept per fact
WINDOW_CHARS = 700      # each extra piece of source text shown to the checker
WINDOWS = 3             # at most this many extra pieces per fact
MIN_RELEVANCE = 0.15    # share of the topic's words a source must mention to be used


def words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9][a-z0-9.\-]*[a-z0-9]|[a-z0-9]", (text or "").lower())
            if w not in STOP and len(w) > 2}


def source_text(s: dict) -> str:
    return " ".join(filter(None, [s.get("title"), s.get("summary"), s.get("body_text")]))


def _date(s: dict) -> str | None:
    d = s.get("published_at")
    if isinstance(d, datetime):
        return d.date().isoformat()
    return str(d)[:10] if d else None


def relevant_sources(idea: dict, sources: list[dict]) -> tuple[list[dict], list[str]]:
    """Sources that mention the topic. A source sharing too few of the idea's words (e.g. a currency-API product page
    for a savings video) is set aside and listed, never silently used. If that would leave nothing, all are kept."""
    topic = words(f"{idea.get('title', '')} {idea.get('angle', '')}")
    if not topic:
        return sources, []
    kept, dropped = [], []
    for s in sources:
        overlap = len(topic & words(source_text(s)[:6000])) / len(topic)
        (kept if overlap >= MIN_RELEVANCE else dropped).append(s)
    if not kept:
        return sources, []
    return kept, [f"Not used (off-topic for this video): {s.get('title', '')[:90]}" for s in dropped]


def _stale_after_days(topic: str) -> int:
    """After this many days a source's figures are history, not news (config/research.yaml: stale_after_days)."""
    return int((config.research().get("stale_after_days") or {}).get(topic, 365))


def find_passage(fact: Fact, text: str) -> str:
    """The part of the source that states the fact: the model's quote when it is really there, else the window
    holding the fact's numbers and most of its words."""
    from .verify import _norm, quote_in_evidence

    if fact.passage and quote_in_evidence(fact.passage, text):
        return fact.passage.strip()[:PASSAGE_CHARS]
    want = words(fact.text)
    from .quality import numbers_in

    nums = numbers_in(fact.text)
    sentences = [x for x in re.split(r"(?<=[.!?”])\s+", text) if x.strip()]
    best, best_key = "", (0.0, 0)
    for size in (1, 2):  # one sentence first; two only when the fact spans a sentence break
        for i in range(len(sentences) - size + 1):
            chunk = " ".join(sentences[i:i + size]).strip()
            if len(chunk) > PASSAGE_CHARS or (nums and not nums <= numbers_in(chunk)):
                continue
            score = len(want & words(chunk)) / max(len(want), 1)
            key = (round(score, 3), -len(chunk))   # most of the fact's words, then the shortest passage
            if key > best_key:
                best, best_key = chunk, key
    return best if best_key[0] >= 0.5 else ""


def attach(facts: FactSheet, sources: list[dict], now: datetime | None = None) -> tuple[FactSheet, list[str]]:
    """Give each fact its passage, source id and date; drop facts nobody can point to in the source. A 'current'
    fact from an old source becomes 'historical', so it is always said with its date."""
    now = now or datetime.now(timezone.utc)
    by_label = {f"S{i}": s for i, s in enumerate(sources, 1)}
    kept, dropped = [], []
    for f in facts.facts:
        s = by_label.get(f.source_ref)
        if not s:
            dropped.append(f"{f.key}: cites unknown source {f.source_ref}")
            continue
        passage = find_passage(f, source_text(s))
        if not passage:
            dropped.append(f"{f.key}: its words weren't found in {f.source_ref}")
            continue
        kind = f.time_kind
        pub = s.get("published_at")
        if kind == "current" and isinstance(pub, datetime):
            age = (now - (pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc))).days
            if age > _stale_after_days(s.get("topic") or ""):
                kind = "historical"
        kept.append(f.model_copy(update={"passage": passage, "time_kind": kind, "source_id": str(s.get("id") or ""),
                                         "published": _date(s)}))
    return FactSheet(facts=kept, context=facts.context, open_questions=facts.open_questions), dropped


def windows(text: str, claim: str, n: int = WINDOWS) -> list[str]:
    """The pieces of a long source that best match a claim (anywhere in the article, not just its opening)."""
    want = words(claim)
    if not want or not text:
        return []
    step = WINDOW_CHARS // 2
    scored = []
    for start in range(0, max(len(text) - step, 1), step):
        chunk = text[start:start + WINDOW_CHARS]
        scored.append((len(want & words(chunk)), start, chunk))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out, used = [], []
    for score, start, chunk in scored:
        if score == 0 or len(out) >= n:
            break
        if any(abs(start - u) < WINDOW_CHARS for u in used):
            continue
        used.append(start)
        out.append(chunk.strip())
    return out


def evidence_for(fact: Fact, sources_by_id: dict[str, dict], claim: str) -> str:
    """Everything the checker needs for one cited fact: the fact, its passage, where and when it was published, and
    the parts of the full article that match the claim being checked."""
    s = sources_by_id.get(fact.source_id or "") or {}
    head = (f"Fact: {fact.text}\nPassage: {fact.passage}\nSource: {s.get('title') or ''} ({s.get('publisher') or ''}), "
            f"published {fact.published or 'date unknown'}"
            + (f", data period {fact.data_period}" if fact.data_period else "")
            + f". Time: {fact.time_kind}.")
    extra = windows(source_text(s), claim)
    return head + ("\nMore from the article:\n" + "\n...\n".join(extra) if extra else "")


def date_numbers(facts: list[Fact]) -> set[str]:
    """Years and full dates the evidence gives through publication dates and data periods (as numbers_in sees them)."""
    from .quality import numbers_in

    out: set[str] = set()
    for f in facts:
        for v in (f.published, f.data_period):
            if v:
                out |= numbers_in(str(v).replace("-", " "))
                out |= set(re.findall(r"\d{4}-\d{2}-\d{2}", str(v)))
    return out
