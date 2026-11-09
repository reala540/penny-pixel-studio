"""Put every YouTube upload into the right playlist on its channel.

The channel itself is already decided by the schedule (AI videos go to the AI channel, money videos to the Money channel).
Inside a channel, the playlist is chosen like this:

1. The owner's rules (setting `youtube_playlist_rules`): a list of
   {"playlist_id": "...", "keywords": ["budget", "inflation"], "kinds": ["long_video"], "default": false}.
   The first rule on this channel's playlists whose keywords appear in the video wins; a rule marked "default" catches
   whatever matches nothing else (one per kind and channel at most).
2. Otherwise the channel's own playlists, read from YouTube (cached for a day): a Shorts playlist (title contains
   "short") takes Shorts, and long videos never go there; the playlist whose title and description share the most
   meaningful words with the video's title, tags and opening wins, if it shares at least one.
3. Nothing fits: the video stays out of playlists, and the reason is written to the activity log.

Adding needs YouTube's "manage" permission (youtube.force-ssl). Until a channel is reconnected with it, the chosen
playlist becomes a one-tap to-do for the owner instead. A playlist step never undoes or retries an upload.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx

from .. import db

API = "https://www.googleapis.com/youtube/v3"
MANAGE = {"https://www.googleapis.com/auth/youtube.force-ssl", "https://www.googleapis.com/auth/youtube"}
CACHE_HOURS = 24
STOP = {"the", "and", "for", "with", "your", "you", "what", "how", "why", "this", "that", "from", "are", "can", "does",
        "will", "into", "about", "our", "new", "its", "it's", "more", "less", "than", "when", "who", "out", "not", "all",
        "video", "videos", "playlist", "channel", "penny", "pixel", "explained", "guide", "tips", "2025", "2026", "2027"}


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9'+-]{2,}", (text or "").lower()) if w not in STOP}


def is_shorts(p: dict) -> bool:
    return "short" in (p.get("title") or "").lower()


def choose(playlists: list[dict], video: dict, kind: str, rules: list[dict] | None = None) -> tuple[dict | None, str]:
    """(playlist, why). video: {"title", "tags", "body"}; kind: long_video | short_video."""
    text = " ".join([video.get("title") or "", " ".join(video.get("tags") or []), (video.get("body") or "")[:600]])
    have = {p["id"]: p for p in playlists}
    vw = words(text)
    fallback = None
    for r in rules or []:
        p = have.get(r.get("playlist_id"))
        if not p or (r.get("kinds") and kind not in r["kinds"]):
            continue
        kws = [k.lower() for k in r.get("keywords") or [] if k]
        low = text.lower()
        if kws and any(re.search(rf"\b{re.escape(k)}\b", low) for k in kws):
            return p, f"your rule (keyword match) for “{p['title']}”"
        if r.get("default") and fallback is None:
            fallback = p
    shorts = [p for p in playlists if is_shorts(p)]
    if kind == "short_video" and len(shorts) == 1:
        return shorts[0], f"the channel's Shorts playlist “{shorts[0]['title']}”"
    # several Shorts playlists: the best topic match among them; none: a Short can join a topic playlist
    candidates = (shorts or playlists) if kind == "short_video" else [p for p in playlists if not is_shorts(p)]
    best, score = None, 0
    for p in candidates:
        s = len(vw & words(f"{p.get('title', '')} {p.get('description', '')}"))
        if s > score:
            best, score = p, s
    if best:
        return best, f"“{best['title']}” shares {score} topic word(s) with the video"
    if fallback:
        return fallback, f"your default playlist “{fallback['title']}”"
    return None, "no playlist on this channel matches the video's topic"


def fetch(client: httpx.Client, token: str) -> list[dict]:
    out, page = [], None
    for _ in range(10):
        r = client.get(f"{API}/playlists", params={"part": "snippet", "mine": "true", "maxResults": 50,
                                                   **({"pageToken": page} if page else {})},
                       headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        data = r.json()
        out += [{"id": i["id"], "title": i["snippet"].get("title", ""), "description": i["snippet"].get("description", "")}
                for i in data.get("items") or []]
        page = data.get("nextPageToken")
        if not page:
            break
    return out


def channel_playlists(conn, client, token: str, account_id) -> list[dict]:
    key = f"youtube_playlists:{account_id}"
    cached = db.get_setting(conn, key, None)
    now = datetime.now(timezone.utc)
    if isinstance(cached, dict) and cached.get("at"):
        try:
            if datetime.fromisoformat(cached["at"]) > now - timedelta(hours=CACHE_HOURS):
                return cached.get("items") or []
        except ValueError:
            pass
    items = fetch(client, token)
    db.run(conn, "insert into settings (key, value) values (%s, %s) on conflict (key) do update set value=excluded.value",
           (key, db.j({"at": now.isoformat(), "items": items})))
    return items


def can_manage(conn, account_id) -> bool:
    row = db.one(conn, "select scopes from oauth_connections where social_account_id=%s", (account_id,))
    return bool(row and MANAGE & set(row.get("scopes") or []))


def place(conn, client: httpx.Client, token: str, account: dict, ctx: dict, video_id: str, post_id) -> str:
    """Add the uploaded video to its playlist. Returns what happened; never raises."""
    if not video_id:
        return "no video"
    try:
        playlists = channel_playlists(conn, client, token, account["id"])
        if not playlists:
            db.audit(conn, "youtube_playlist_skipped", "scheduled_post", post_id, {"reason": "the channel has no playlists"})
            return "none"
        rules = db.get_setting(conn, "youtube_playlist_rules", []) or []
        kind = ctx.get("kind") or "long_video"
        p, why = choose(playlists, {"title": ctx.get("title"), "tags": ctx.get("tags"), "body": ctx.get("body")}, kind, rules)
        if not p:
            db.audit(conn, "youtube_playlist_skipped", "scheduled_post", post_id, {"reason": why})
            return "none"
        if not can_manage(conn, account["id"]):
            db.run(conn, """insert into manual_tasks (scheduled_post_id, platform, title, instructions, deep_link)
                            values (%s,'youtube',%s,%s,%s)""",
                   (post_id, f"Add to playlist: {p['title']}",
                    f"Add this video to the playlist “{p['title']}” ({why}). In YouTube Studio: Content → the video → "
                    f"Playlists → tick “{p['title']}” → Save. To make this automatic, reconnect this YouTube channel "
                    f"on the Setup page (it asks for permission to manage playlists).",
                    f"https://studio.youtube.com/video/{video_id}/edit"))
            db.audit(conn, "youtube_playlist_manual", "scheduled_post", post_id, {"playlist": p["title"], "why": why})
            return "manual"
        r = client.post(f"{API}/playlistItems", params={"part": "snippet"},
                        json={"snippet": {"playlistId": p["id"], "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
                        headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 300:
            db.audit(conn, "youtube_playlist_failed", "scheduled_post", post_id,
                     {"playlist": p["title"], "status": r.status_code, "detail": r.text[:300]})
            return "failed"
        db.run(conn, "insert into provider_usage (provider, service, units, success) values ('youtube','youtube_api',50,true)")
        db.audit(conn, "youtube_playlist_added", "scheduled_post", post_id, {"playlist": p["title"], "why": why})
        return "added"
    except Exception as exc:   # a playlist problem must never touch the upload itself
        try:
            db.audit(conn, "youtube_playlist_failed", "scheduled_post", post_id, {"error": str(exc)[:300]})
        except Exception:
            pass
        return "failed"
