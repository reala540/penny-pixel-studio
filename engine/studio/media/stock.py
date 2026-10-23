"""Licensed stock photos from Pexels / Pixabay (free APIs). Every download gets a license record.

If no key is configured, the caller falls back to original typographic cards.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class StockPhoto:
    path: Path
    source_url: str
    provider: str
    creator: str | None
    license: str
    attribution_required: bool
    attribution_text: str | None


def find_photo(query: str, out_dir: Path, orientation: str = "landscape",
               client: httpx.Client | None = None) -> StockPhoto | None:
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for fn in (_pexels, _pixabay):
        try:
            hit = fn(client, query, orientation)
        except Exception:
            hit = None
        if not hit:
            continue
        url, meta = hit
        path = out_dir / f"stock_{hashlib.sha256(url.encode()).hexdigest()[:20]}.jpg"
        if not path.exists():
            r = client.get(url)
            r.raise_for_status()
            path.write_bytes(r.content)
        return StockPhoto(path=path, **meta)
    return None


def _pexels(client, query, orientation):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None
    r = client.get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                   params={"query": query, "orientation": orientation, "per_page": 5, "size": "large"})
    r.raise_for_status()
    photos = r.json().get("photos") or []
    if not photos:
        return None
    p = photos[0]
    return p["src"].get("large2x") or p["src"]["original"], {
        "source_url": p["url"], "provider": "pexels", "creator": p.get("photographer"),
        "license": "Pexels License (free commercial use, no attribution required)",
        "attribution_required": False, "attribution_text": f"Photo by {p.get('photographer')} on Pexels"}


def _pixabay(client, query, orientation):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return None
    r = client.get("https://pixabay.com/api/", params={
        "key": key, "q": query[:100], "image_type": "photo", "safesearch": "true", "per_page": 5,
        "orientation": "horizontal" if orientation == "landscape" else "vertical"})
    r.raise_for_status()
    hits = r.json().get("hits") or []
    if not hits:
        return None
    h = hits[0]
    return h.get("largeImageURL") or h["webformatURL"], {
        "source_url": h["pageURL"], "provider": "pixabay", "creator": h.get("user"),
        "license": "Pixabay Content License (free commercial use)", "attribution_required": False,
        "attribution_text": f"Image by {h.get('user')} on Pixabay"}
