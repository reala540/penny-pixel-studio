"""Affiliate offers the owner added in Settings. At most one matching offer is added to a long video's description,
disclosure first, so viewers see it's an affiliate link before they click. Never in X posts (links are blocked there),
Shorts or the narration, and never worded as advice for someone's own situation."""
from __future__ import annotations

import re

from . import db

MONEY_NOTE = "This isn't a recommendation for your personal situation; compare options before you sign up."


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def match(conn, channel: str, text: str) -> dict | None:
    """The enabled offer whose topics best match this video (all words of a topic must appear), or None."""
    if not db.one(conn, "select 1 from information_schema.tables where table_schema='public' and table_name='affiliate_offers'"):
        return None
    offers = db.all_(conn, """select * from affiliate_offers where enabled and channel_slug in (%s, 'both')
                              order by created_at""", (channel,))
    words = _words(text)
    best, score = None, 0
    for o in offers:
        hits = sum(1 for t in o["topics"] if t.strip() and _words(t) <= words)
        if hits > score:
            best, score = o, hits
    return best


def block(offer: dict, channel: str) -> str:
    lines = [offer["disclosure"].strip()]
    lines.append(f"{offer['name']}{(' - ' + offer['blurb'].strip()) if offer.get('blurb') else ''}: {offer['url']}")
    if channel == "money":
        lines.append(MONEY_NOTE)
    return "\n".join(lines)


def add_to_description(conn, channel: str, description: str, topic_text: str) -> tuple[str, dict | None]:
    offer = match(conn, channel, topic_text)
    if offer is None or offer["url"] in description:
        return description, None
    return f"{description.rstrip()}\n\n{block(offer, channel)}", {"id": str(offer["id"]), "name": offer["name"]}
