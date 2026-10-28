"""Short sound effects for animated scenes, from Freesound (free key). Only CC0 (public-domain) sounds are used, so no
credit line is needed; each one still gets a licence record. Without a key, animated scenes are simply silent apart
from the narration."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx

from .stock import StockPhoto

QUERY = {"budget_jars": "coin drop", "price_basket": "cash register", "agent_handoff": "soft whoosh", "counter": "soft tick"}


def find_effect(animation: str, out_dir: Path, client: httpx.Client | None = None) -> StockPhoto | None:
    key = os.environ.get("FREESOUND_API_KEY")
    query = QUERY.get(animation)
    if not key or not query:
        return None
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    try:
        r = client.get("https://freesound.org/apiv2/search/text/", params={
            "query": query, "filter": 'license:"Creative Commons 0" duration:[0.2 TO 3]', "sort": "rating_desc",
            "fields": "id,name,url,username,license,previews,duration", "page_size": 5, "token": key})
        r.raise_for_status()
        for h in r.json().get("results") or []:
            if "publicdomain/zero" not in (h.get("license") or "") or not (h.get("previews") or {}).get("preview-hq-mp3"):
                continue
            url = h["previews"]["preview-hq-mp3"]
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"sfx_{hashlib.sha256(url.encode()).hexdigest()[:16]}.mp3"
            if not path.exists():
                a = client.get(url)
                a.raise_for_status()
                if len(a.content) > 2_000_000:
                    continue
                path.write_bytes(a.content)
            return StockPhoto(path=path, source_url=h["url"], provider="freesound", creator=h.get("username"),
                              license="CC0 1.0 (public domain dedication), via Freesound", attribution_required=False,
                              attribution_text=f"\"{h.get('name')}\" by {h.get('username')} (CC0)")
    except Exception:
        return None
    return None
