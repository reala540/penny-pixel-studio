"""Licensed stock photos from Pixabay / Pexels (free keys) and Openverse (no key), and short stock video clips from
Pexels / Pixabay (the same free keys). Every download gets a license record.

Openverse is limited to public-domain images (CC0 / PDM), so no credit line is needed and commercial use is allowed.
If nothing is found, the caller falls back to original typographic cards.
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
    for fn in (_pixabay, _pexels, _openverse):
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


def _openverse(client, query, orientation):
    r = client.get("https://api.openverse.org/v1/images/", headers={"User-Agent": "penny-pixel-studio/2.1"}, params={
        "q": query[:200], "license": "cc0,pdm", "mature": "false", "page_size": 10,
        "aspect_ratio": "wide" if orientation == "landscape" else "tall"})
    r.raise_for_status()
    min_side = 1080
    for h in r.json().get("results") or []:
        if (h.get("license") or "").lower() not in ("cc0", "pdm") or not h.get("url"):
            continue
        if min(h.get("width") or 0, h.get("height") or 0) < min_side:
            continue
        name = "CC0 1.0 (public domain dedication)" if h["license"].lower() == "cc0" else "Public Domain Mark 1.0"
        return h["url"], {
            "source_url": h.get("foreign_landing_url") or h["url"], "provider": f"openverse:{h.get('source') or 'unknown'}",
            "creator": h.get("creator"), "license": f"{name}, via Openverse (free commercial use)",
            "attribution_required": False,
            "attribution_text": f"{h.get('title') or 'Image'} by {h.get('creator') or 'unknown'} ({name})"}
    return None


# ------------------------------------------------------------------ video clips (b-roll)

def find_video(query: str, out_dir: Path, orientation: str = "landscape", min_seconds: float = 4.0,
               client: httpx.Client | None = None) -> StockPhoto | None:
    """A short licensed stock video clip for a scene, or None. Same licence record shape as photos."""
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for fn in (_pexels_video, _pixabay_video):
        try:
            hit = fn(client, query, orientation, min_seconds)
        except Exception:
            hit = None
        if not hit:
            continue
        url, meta = hit
        path = out_dir / f"clip_{hashlib.sha256(url.encode()).hexdigest()[:20]}.mp4"
        if not path.exists():
            with client.stream("GET", url) as r:
                r.raise_for_status()
                size = 0
                with open(path, "wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        size += len(chunk)
                        if size > MAX_CLIP_BYTES:
                            break
                        fh.write(chunk)
            if size > MAX_CLIP_BYTES:  # too big to be a short b-roll clip: skip it rather than fill the storage
                path.unlink(missing_ok=True)
                continue
        return StockPhoto(path=path, **meta)
    return None


MAX_CLIP_BYTES = 60 * 1024 * 1024


def _best_file(files: list[dict], orientation: str) -> dict | None:
    """The smallest file that is still full-HD on its short side, else the biggest available."""
    def short_side(f):
        return min(int(f.get("width") or 0), int(f.get("height") or 0))
    usable = [f for f in files if f.get("url") and short_side(f) > 0]
    if orientation == "portrait":
        usable = [f for f in usable if int(f.get("height") or 0) >= int(f.get("width") or 0)] or usable
    else:
        usable = [f for f in usable if int(f.get("width") or 0) >= int(f.get("height") or 0)] or usable
    hd = sorted((f for f in usable if short_side(f) >= 1080), key=short_side)
    return hd[0] if hd else (max(usable, key=short_side) if usable else None)


def _pexels_video(client, query, orientation, min_seconds):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None
    r = client.get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                   params={"query": query[:100], "orientation": orientation, "per_page": 8, "size": "medium"})
    r.raise_for_status()
    for v in r.json().get("videos") or []:
        if float(v.get("duration") or 0) < min_seconds:
            continue
        best = _best_file([{"url": f.get("link"), "width": f.get("width"), "height": f.get("height")}
                           for f in v.get("video_files") or [] if (f.get("file_type") or "") == "video/mp4"], orientation)
        if best:
            who = (v.get("user") or {}).get("name")
            return best["url"], {
                "source_url": v["url"], "provider": "pexels-video", "creator": who,
                "license": "Pexels License (free commercial use, no attribution required)",
                "attribution_required": False, "attribution_text": f"Video by {who} on Pexels"}
    return None


def _pixabay_video(client, query, orientation, min_seconds):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return None
    r = client.get("https://pixabay.com/api/videos/", params={"key": key, "q": query[:100], "safesearch": "true",
                                                               "per_page": 8})
    r.raise_for_status()
    for h in r.json().get("hits") or []:
        if float(h.get("duration") or 0) < min_seconds:
            continue
        best = _best_file(list((h.get("videos") or {}).values()), orientation)
        if best:
            return best["url"], {
                "source_url": h["pageURL"], "provider": "pixabay-video", "creator": h.get("user"),
                "license": "Pixabay Content License (free commercial use)", "attribution_required": False,
                "attribution_text": f"Video by {h.get('user')} on Pixabay"}
    return None
