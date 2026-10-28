"""Official-API publishing adapters. Each one reports what it can genuinely do; anything it
cannot do becomes a manual task with clear instructions — never a fake "posted".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from .. import budget, config, db
from ..errors import AmbiguousPublish, AuthError, PermanentError, QuotaError, TransientError


@dataclass
class PublishResult:
    platform_post_id: str | None
    url: str | None
    visibility: str
    method: str                     # api | api_draft
    manual_followup: str | None = None


@dataclass
class Capability:
    can_publish: bool
    method: str                     # api | api_draft | manual
    reason: str = ""


# Meta's error codes (https://developers.facebook.com/docs/graph-api/guides/error-handling): a login that expired or a
# permission that is missing comes back as HTTP 400, so the code inside the reply decides what the owner should do
META_LOGIN = {102, 190, 463, 467}
META_RATE = {4, 17, 32, 613, 80001}


def _meta_error(r: httpx.Response) -> dict:
    try:
        err = r.json().get("error")
    except ValueError:
        return {}
    return err if isinstance(err, dict) else {}


def _raise_for(r: httpx.Response, platform: str, after_upload: bool = False) -> None:
    if platform == "facebook" and r.status_code >= 400:
        err = _meta_error(r)
        code, msg = err.get("code"), str(err.get("message") or "")[:200]
        if code in META_LOGIN:
            raise AuthError(f"facebook: the login expired or was removed (code {code}): {msg}. "
                            "Reconnect Facebook in Settings → Accounts")
        if code == 10 or (isinstance(code, int) and 200 <= code < 300):
            raise AuthError(f"facebook: a permission is missing (code {code}): {msg}. Reconnect Facebook in "
                            "Settings → Accounts and allow every permission it asks for")
        if code in META_RATE:
            raise QuotaError(f"facebook: Facebook's rate limit was reached (code {code}); trying again later")
    if r.status_code in (401, 403):
        raise AuthError(f"{platform}: permission denied ({r.status_code}): {r.text[:200]}")
    if r.status_code == 429:
        raise QuotaError(f"{platform}: rate limited / daily quota reached")
    if r.status_code >= 500:
        if after_upload:
            raise AmbiguousPublish(f"{platform}: server error after upload — check the platform before retrying")
        raise TransientError(f"{platform}: server error {r.status_code}")
    if r.status_code >= 400:
        raise PermanentError(f"{platform}: {r.status_code} {r.text[:300]}")


def _connected(conn, account_id) -> bool:
    row = db.one(conn, "select status from oauth_connections where social_account_id=%s", (account_id,))
    sec = db.one(conn, "select 1 from oauth_secrets where social_account_id=%s", (account_id,))
    return bool(row and row["status"] == "connected" and sec)


# ------------------------------------------------------------------------------------------ YouTube

class YouTube:
    platform = "youtube"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0))

    def capability(self, conn, account: dict, kind: str) -> Capability:
        if not _connected(conn, account["id"]):
            return Capability(False, "manual", "YouTube channel not connected")
        if not config.services()["publishing"]["youtube"]["api_audited"]:
            return Capability(True, "api_draft", "API not yet audited by Google: uploads are private until you "
                                                 "publish them in YouTube Studio")
        return Capability(True, "api")

    def publish(self, conn, account, variant, video: Path, thumb: Path | None, token: str) -> PublishResult:
        audited = config.services()["publishing"]["youtube"]["api_audited"]
        pub = config.services()["publishing"]["youtube"]
        tags = [t for t in (variant.get("tags") or []) if t][:30]
        meta = {"snippet": {"title": (variant.get("title") or "")[:100], "description": (variant.get("body") or "")[:4900],
                            "tags": tags,
                            "categoryId": str((pub.get("category_ids") or {}).get(variant.get("channel_slug"))
                                              or pub.get("category_id", "27")),
                            "defaultLanguage": pub.get("default_language", "en"),
                            "defaultAudioLanguage": pub.get("default_language", "en")},  # better automatic captions
                "status": {"privacyStatus": "public" if audited else "private", "selfDeclaredMadeForKids": False,
                           "containsSyntheticMedia": bool(variant.get("synthetic_media", False))}}
        size = video.stat().st_size
        headers = {"Authorization": f"Bearer {token}"}
        r = self.client.post("https://www.googleapis.com/upload/youtube/v3/videos",
                             params={"uploadType": "resumable", "part": "snippet,status"}, json=meta,
                             headers={**headers, "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"})
        _raise_for(r, "youtube")
        location = r.headers.get("location")
        if not location:
            raise TransientError("youtube: no upload session URL returned")
        try:
            with video.open("rb") as fh:
                up = self.client.put(location, content=fh.read(),
                                     headers={**headers, "Content-Type": "video/mp4", "Content-Length": str(size)})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AmbiguousPublish("youtube: upload connection dropped — the video may or may not exist") from exc
        _raise_for(up, "youtube", after_upload=True)
        vid = up.json().get("id")
        db.run(conn, """insert into provider_usage (provider, service, units, success) values
                        ('youtube','youtube_api',1600,true)""")
        if thumb and thumb.exists() and vid:
            t = self.client.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set", params={"videoId": vid},
                                 content=thumb.read_bytes(), headers={**headers, "Content-Type": "image/jpeg"})
            if t.status_code < 300:
                db.run(conn, """insert into provider_usage (provider, service, units, success) values
                                ('youtube','youtube_api',50,true)""")
        followup = None if audited else ("Open YouTube Studio > Content, find this private video and set it to "
                                         "Public (or schedule it).")
        return PublishResult(vid, f"https://www.youtube.com/watch?v={vid}" if vid else None,
                             "public" if audited else "private", "api" if audited else "api_draft", followup)


# ------------------------------------------------------------------------------------------ Facebook

class Facebook:
    platform = "facebook"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0))
        self.ver = config.services()["publishing"]["facebook"]["graph_version"]

    def capability(self, conn, account, kind) -> Capability:
        if not _connected(conn, account["id"]):
            return Capability(False, "manual", "Facebook Page not connected")
        return Capability(True, "api")

    def publish(self, conn, account, variant, video: Path | None, thumb, token: str, page_id: str) -> PublishResult:
        g = f"https://graph.facebook.com/{self.ver}"
        if variant["kind"] == "text_post":
            r = self.client.post(f"{g}/{page_id}/feed", data={"message": variant.get("body") or "", "access_token": token})
            _raise_for(r, "facebook", after_upload=True)
            pid = r.json().get("id")
            if not pid:  # Facebook normally returns the new post's id; without it nobody can say the post exists
                raise AmbiguousPublish("facebook: the text post wasn't confirmed (no post id came back): check the Page")
            return PublishResult(pid, f"https://www.facebook.com/{pid}", "public", "api")
        if video is None:
            raise PermanentError(f"facebook: a {variant['kind'].replace('_', ' ')} needs a video")
        if variant["kind"] == "long_video":
            return self._long_video(g, page_id, variant, video, token)
        # Reels and Stories: start, upload the file to Facebook's upload host, then finish
        edge = "video_stories" if variant["kind"] == "story" else "video_reels"
        start = self.client.post(f"{g}/{page_id}/{edge}", data={"upload_phase": "start", "access_token": token})
        _raise_for(start, "facebook")
        vid = start.json().get("video_id")
        upload_url = start.json().get("upload_url") or f"https://rupload.facebook.com/video-upload/{self.ver}/{vid}"
        size = video.stat().st_size
        try:
            up = self.client.post(upload_url, content=video.read_bytes(),
                                  headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError("facebook: upload dropped before finishing (nothing published yet)") from exc
        _raise_for(up, "facebook")
        if variant["kind"] == "story":  # a Story has no caption
            fin = self.client.post(f"{g}/{page_id}/video_stories",
                                   data={"upload_phase": "finish", "video_id": vid, "access_token": token})
            _raise_for(fin, "facebook", after_upload=True)
            body = fin.json()
            if not body.get("success", False):
                raise AmbiguousPublish("facebook: story finish phase did not confirm success")
            post_id = body.get("post_id") or vid
            return PublishResult(str(post_id), f"https://www.facebook.com/{post_id}", "public", "api")
        caption = (variant.get("body") or "") + ("\n" + " ".join(f"#{h.lstrip('#')}" for h in variant.get("hashtags") or []))
        fin = self.client.post(f"{g}/{page_id}/video_reels",
                               data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                     "description": caption.strip()[:2200], "access_token": token})
        _raise_for(fin, "facebook", after_upload=True)
        if fin.json().get("success") is not True:  # only an explicit yes counts as posted
            raise AmbiguousPublish("facebook: the Reel's finish step didn't confirm success: check the Page")
        return PublishResult(vid, f"https://www.facebook.com/reel/{vid}", "public", "api")

    CHUNK_LIMIT = 200  # a long video is sent in pieces; this many pieces means something is wrong

    def _long_video(self, g: str, page_id: str, variant: dict, video: Path, token: str) -> PublishResult:
        """A long video on the Page, sent in pieces (resumable upload) so a big file never needs one huge request."""
        gv = g.replace("https://graph.facebook.com", "https://graph-video.facebook.com")
        size = video.stat().st_size
        start = self.client.post(f"{gv}/{page_id}/videos",
                                 data={"upload_phase": "start", "file_size": str(size), "access_token": token})
        _raise_for(start, "facebook")
        s = start.json()
        session, vid = s.get("upload_session_id"), s.get("video_id")
        lo, hi = int(s.get("start_offset", 0)), int(s.get("end_offset", 0))
        try:
            with video.open("rb") as fh:
                for _ in range(self.CHUNK_LIMIT):
                    if lo >= hi:
                        break
                    fh.seek(lo)
                    piece = fh.read(hi - lo)
                    r = self.client.post(f"{gv}/{page_id}/videos",
                                         data={"upload_phase": "transfer", "upload_session_id": session,
                                               "start_offset": str(lo), "access_token": token},
                                         files={"video_file_chunk": ("chunk", piece, "application/octet-stream")})
                    _raise_for(r, "facebook")
                    lo, hi = int(r.json().get("start_offset", hi)), int(r.json().get("end_offset", hi))
                else:
                    raise PermanentError("facebook: the video upload didn't finish after many pieces")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError("facebook: upload dropped before finishing (nothing published yet)") from exc
        fin = self.client.post(f"{gv}/{page_id}/videos",
                               data={"upload_phase": "finish", "upload_session_id": session,
                                     "title": (variant.get("title") or "")[:255],
                                     "description": (variant.get("body") or "")[:5000], "access_token": token})
        _raise_for(fin, "facebook", after_upload=True)
        if not fin.json().get("success", False):
            raise AmbiguousPublish("facebook: video finish phase did not confirm success")
        return PublishResult(str(vid), f"https://www.facebook.com/{page_id}/videos/{vid}", "public", "api")


# ------------------------------------------------------------------------------------------ TikTok

class TikTok:
    platform = "tiktok"
    base = "https://open.tiktokapis.com/v2"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0))

    def capability(self, conn, account, kind) -> Capability:
        if not _connected(conn, account["id"]):
            return Capability(False, "manual", "TikTok not connected")
        if config.services()["publishing"]["tiktok"]["direct_post_approved"]:
            return Capability(True, "api")
        return Capability(True, "api_draft", "Direct posting needs TikTok's audit; sending to your TikTok inbox as a draft")

    def publish(self, conn, account, variant, video: Path, thumb, token: str) -> PublishResult:
        direct = config.services()["publishing"]["tiktok"]["direct_post_approved"]
        h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
        size = video.stat().st_size
        if size > 64 * 1024 * 1024:
            raise PermanentError("tiktok: video larger than one 64 MB chunk; lower the bitrate")
        source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}
        caption = ((variant.get("body") or "") + " " + " ".join(f"#{x.lstrip('#')}" for x in variant.get("hashtags") or [])).strip()
        if direct:
            info = self.client.post(f"{self.base}/post/publish/creator_info/query/", headers=h)
            _raise_for(info, "tiktok")
            options = info.json().get("data", {}).get("privacy_level_options") or []
            privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in options else (options[0] if options else "SELF_ONLY")
            body = {"post_info": {"title": caption[:2200], "privacy_level": privacy, "disable_comment": False,
                                  "disable_duet": False, "disable_stitch": False,
                                  "is_aigc": bool(variant.get("synthetic_media", False))},
                    "source_info": source}
            init = self.client.post(f"{self.base}/post/publish/video/init/", headers=h, json=body)
        else:
            init = self.client.post(f"{self.base}/post/publish/inbox/video/init/", headers=h, json={"source_info": source})
        _raise_for(init, "tiktok")
        data = init.json().get("data", {})
        err = (init.json().get("error") or {}).get("code")
        if err and err != "ok":
            raise PermanentError(f"tiktok: {init.json().get('error')}")
        try:
            up = self.client.put(data["upload_url"], content=video.read_bytes(),
                                 headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                                          "Content-Range": f"bytes 0-{size - 1}/{size}"})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AmbiguousPublish("tiktok: upload dropped; check TikTok before retrying") from exc
        _raise_for(up, "tiktok", after_upload=True)
        pid = data.get("publish_id")
        if direct:
            return PublishResult(pid, None, "public", "api")
        return PublishResult(pid, None, "draft", "api_draft",
                             "Open the TikTok app: a notification says your video is ready. Add a sound if you like, "
                             "paste the caption from the dashboard and post it.")


# ------------------------------------------------------------------------------------------ X

URL_RE = re.compile(r"https?://|www\.|\b[\w-]+\.(com|net|org|io|co|ai|ke)\b", re.IGNORECASE)


class X:
    platform = "x"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=30)

    def capability(self, conn, account, kind) -> Capability:
        if not config.services()["publishing"]["x"]["enabled"]:
            return Capability(False, "manual", "X auto-posting disabled in settings")
        if not _connected(conn, account["id"]):
            return Capability(False, "manual", "X account not connected")
        if budget.month_summary(conn, "x_api")["remaining"] <= 0:
            return Capability(False, "manual", "X monthly budget used up")
        return Capability(True, "api")

    def cost_for(self, text: str) -> float:
        b = config.services()["budgets"]["x_api"]
        if URL_RE.search(text):
            if not b.get("allow_links", False):
                raise PermanentError("x: post contains a link; links are blocked to protect the budget")
            return float(b["cost_per_post_with_url_usd"])
        return float(b["cost_per_post_usd"])

    def publish(self, conn, account, variant, video, thumb, token: str, reference: str) -> PublishResult:
        text = (variant.get("body") or "").strip()
        if not text or len(text) > 280:
            raise PermanentError("x: post must be 1-280 characters")
        cost = self.cost_for(text)
        budget.reserve(conn, "x_api", cost, reference)  # raises BudgetExceeded before any paid call
        try:
            r = self.client.post("https://api.x.com/2/tweets", json={"text": text},
                                 headers={"Authorization": f"Bearer {token}"})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AmbiguousPublish("x: request timed out — the post may exist; budget kept reserved") from exc
        if r.status_code >= 400:
            if r.status_code < 500:
                budget.release(conn, reference)
            _raise_for(r, "x", after_upload=True)
        budget.commit(conn, reference)
        tid = (r.json().get("data") or {}).get("id")
        return PublishResult(tid, f"https://x.com/i/web/status/{tid}" if tid else None, "public", "api")


ADAPTERS = {"youtube": YouTube, "facebook": Facebook, "tiktok": TikTok, "x": X}
