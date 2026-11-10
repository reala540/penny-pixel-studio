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
    pending: bool = False           # accepted by TikTok, not yet confirmed published


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
        if config.services()["publishing"]["youtube"].get("privacy_status", "private") != "public":
            return Capability(True, "api_draft", "Configured to upload privately; public posting is not enabled")
        return Capability(True, "api")

    def publish(self, conn, account, variant, video: Path, thumb: Path | None, token: str) -> PublishResult:
        pub = config.services()["publishing"]["youtube"]
        requested_visibility = pub.get("privacy_status", "public" if pub.get("api_audited") else "private")
        if requested_visibility not in ("public", "private", "unlisted"):
            raise PermanentError("YouTube privacy_status must be public, private or unlisted")
        tags = [t for t in (variant.get("tags") or []) if t][:30]
        meta = {"snippet": {"title": (variant.get("title") or "")[:100], "description": (variant.get("body") or "")[:4900],
                            "tags": tags,
                            "categoryId": str((pub.get("category_ids") or {}).get(variant.get("channel_slug"))
                                              or pub.get("category_id", "27")),
                            "defaultLanguage": pub.get("default_language", "en"),
                            "defaultAudioLanguage": pub.get("default_language", "en")},  # better automatic captions
                "status": {"privacyStatus": requested_visibility, "selfDeclaredMadeForKids": False,
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
        try:
            uploaded = up.json()
        except ValueError as exc:
            raise AmbiguousPublish("YouTube accepted the upload but returned no readable receipt; do not upload again") from exc
        if not isinstance(uploaded, dict):
            raise AmbiguousPublish("YouTube upload receipt is malformed; check the channel before retrying")
        vid = uploaded.get("id")
        if not vid:
            raise AmbiguousPublish("YouTube upload receipt has no video ID; check the channel before retrying")
        status = uploaded.get("status")
        visibility = status.get("privacyStatus", "unknown") if isinstance(status, dict) else "unknown"
        if vid:
            try:
                check = self.client.get("https://www.googleapis.com/youtube/v3/videos",
                                        params={"part": "status", "id": vid}, headers=headers)
                if check.is_success:
                    items = check.json().get("items") or []
                    if items:
                        visibility = items[0].get("status", {}).get("privacyStatus", visibility)
            except (httpx.HTTPError, ValueError, AttributeError, TypeError):
                pass  # never retry a successful upload because its visibility check failed
        db.run(conn, """insert into provider_usage (provider, service, units, success) values
                        ('youtube','youtube_api',100,true)""")
        if thumb and thumb.exists() and vid:
            t = self.client.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set", params={"videoId": vid},
                                 content=thumb.read_bytes(), headers={**headers, "Content-Type": "image/jpeg"})
            if t.status_code < 300:
                db.run(conn, """insert into provider_usage (provider, service, units, success) values
                                ('youtube','youtube_api',50,true)""")
        followup = None if visibility == "public" else (
            f"Uploaded successfully; visibility is {visibility}. Check YouTube Studio before recording it as public.")
        return PublishResult(vid, f"https://www.youtube.com/watch?v={vid}" if vid else None,
                             visibility, "api" if visibility == "public" else "api_draft", followup)


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
        if variant["kind"] == "text_post" and thumb and Path(thumb).exists():
            # a picture post (the video's thumbnail with the text as its caption) reaches more people than plain text
            r = self.client.post(f"{g}/{page_id}/photos",
                                 data={"caption": variant.get("body") or "", "published": "true", "access_token": token},
                                 files={"source": ("thumb.jpg", Path(thumb).read_bytes(), "image/jpeg")})
            _raise_for(r, "facebook", after_upload=True)
            pid = r.json().get("post_id") or r.json().get("id")
            if not pid:
                raise AmbiguousPublish("facebook: the picture post wasn't confirmed (no post id came back): check the Page")
            return PublishResult(str(pid), f"https://www.facebook.com/{pid}", "public", "api")
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

PRIVACY_NAME = {"PUBLIC_TO_EVERYONE": "public", "MUTUAL_FOLLOW_FRIENDS": "friends", "FOLLOWER_OF_CREATOR": "followers",
                "SELF_ONLY": "private"}


def tiktok_post_info(settings: dict, creator: dict, caption: str, aigc: bool, seconds: float | None) -> dict:
    """TikTok's Direct Post request, from the owner's confirmed choices, checked against the creator's settings right now.
    Raises PermanentError (the owner must look again) when a choice is no longer allowed."""
    privacy = settings.get("privacy_level")
    if privacy not in (creator.get("privacy_level_options") or []):
        raise PermanentError(f"tiktok: '{privacy}' is no longer an allowed audience for this account; choose again on the dashboard")
    if settings.get("branded_content") and privacy == "SELF_ONLY":
        raise PermanentError("tiktok: branded content can't be private; choose another audience on the dashboard")
    if settings.get("disclose") and not (settings.get("your_brand") or settings.get("branded_content")):
        raise PermanentError("tiktok: commercial content is switched on but neither 'Your brand' nor 'Branded content' is chosen")
    limit = creator.get("max_video_post_duration_sec")
    if seconds and limit and seconds > float(limit):
        raise PermanentError(f"tiktok: the video is {seconds:.0f} s; this account can post at most {limit} s")
    return {"title": caption[:2200], "privacy_level": privacy,
            "disable_comment": bool(creator.get("comment_disabled")) or not settings.get("allow_comment"),
            "disable_duet": bool(creator.get("duet_disabled")) or not settings.get("allow_duet"),
            "disable_stitch": bool(creator.get("stitch_disabled")) or not settings.get("allow_stitch"),
            "brand_organic_toggle": bool(settings.get("disclose") and settings.get("your_brand")),
            "brand_content_toggle": bool(settings.get("disclose") and settings.get("branded_content")),
            "is_aigc": aigc}


def _seconds(video: Path) -> float | None:
    import subprocess
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                             capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class TikTok:
    """Direct Post when the owner confirmed this post's TikTok settings on the dashboard (TikTok's required posting screen)
    and the connection has video.publish; otherwise the video goes to the owner's TikTok inbox as a draft."""
    platform = "tiktok"
    base = "https://open.tiktokapis.com/v2"
    poll_seconds = 5
    polls = 24

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0))

    def capability(self, conn, account, kind) -> Capability:
        if not _connected(conn, account["id"]):
            return Capability(False, "manual", "TikTok not connected")
        return Capability(True, "api")

    @staticmethod
    def _can_direct(conn, account, variant) -> bool:
        row = db.one(conn, "select scopes from oauth_connections where social_account_id=%s", (account["id"],))
        settings = variant.get("tiktok_post") or {}
        if settings and "video.publish" not in (row or {}).get("scopes", []):
            raise PermanentError("tiktok: Direct Post permission is missing; reconnect after TikTok grants video.publish, or choose inbox upload")
        return bool(settings.get("confirmed_at") and settings.get("privacy_level")) and "video.publish" in (row or {}).get("scopes", [])

    def _json(self, r: httpx.Response) -> dict:
        _raise_for(r, "tiktok")
        try:
            body = r.json()
        except ValueError:
            raise TransientError("tiktok: unreadable reply")
        err = (body.get("error") or {}).get("code")
        if err and err != "ok":
            if err in ("rate_limit_exceeded", "spam_risk_too_many_posts", "spam_risk_user_banned_from_posting",
                       "reached_active_user_cap"):
                raise QuotaError(f"tiktok: {body['error']}")
            raise PermanentError(f"tiktok: {body['error']}")
        return body.get("data") or {}

    def publish(self, conn, account, variant, video: Path, thumb, token: str) -> PublishResult:
        import time
        h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
        size = video.stat().st_size
        if size > 64 * 1024 * 1024:
            raise PermanentError("tiktok: video larger than one 64 MB chunk; lower the bitrate")
        source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}
        caption = ((variant.get("body") or "") + " " + " ".join(f"#{x.lstrip('#')}" for x in variant.get("hashtags") or [])).strip()
        direct = self._can_direct(conn, account, variant)
        creator: dict = {}
        if direct:
            creator = self._json(self.client.post(f"{self.base}/post/publish/creator_info/query/", headers=h))
            if creator.get("can_post") is False:
                raise QuotaError("tiktok: the account can't post right now (TikTok's posting limit); trying again later")
            info = tiktok_post_info(variant["tiktok_post"], creator, caption,
                                    bool(variant.get("synthetic_media", False)), _seconds(video))
            data = self._json(self.client.post(f"{self.base}/post/publish/video/init/", headers=h,
                                               json={"post_info": info, "source_info": source}))
        else:
            data = self._json(self.client.post(f"{self.base}/post/publish/inbox/video/init/", headers=h,
                                               json={"source_info": source}))
        pid = data.get("publish_id")
        if not pid or not data.get("upload_url"):
            raise AmbiguousPublish("tiktok: upload initialization did not return an ID and URL; check TikTok before retrying")
        tracking = {"publish_id": pid, "direct": direct, "creator_username": creator.get("creator_username"),
                    "privacy_level": (variant.get("tiktok_post") or {}).get("privacy_level")}
        # Persist the platform ID BEFORE sending bytes, so a crash cannot cause an accidental second upload.
        if started := variant.get("_tiktok_started"):
            started(tracking)
        try:
            up = self.client.put(data["upload_url"], content=video.read_bytes(),
                                 headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                                          "Content-Range": f"bytes 0-{size - 1}/{size}"})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AmbiguousPublish("tiktok: upload dropped; check TikTok before retrying") from exc
        _raise_for(up, "tiktok", after_upload=True)
        if not direct:
            return PublishResult(pid, None, "draft", "api_draft",
                                 "Open the TikTok app: a notification says your video is ready. Add a sound if you like, "
                                 "paste the caption from the dashboard and post it. (For direct posting, confirm the "
                                 "post's TikTok settings on the dashboard before its time.)")
        # TikTok processes the upload; ask until it says posted or failed (never upload again: the file is already there)
        for _ in range(self.polls):
            result = self.check_upload(tracking, token)
            if not result.pending:
                return result
            time.sleep(self.poll_seconds)
        return result

    def check_upload(self, tracking: dict, token: str) -> PublishResult:
        """Check a saved upload ID. Never initialize another upload or resend bytes."""
        pid = tracking["publish_id"]
        try:
            st = self._json(self.client.post(f"{self.base}/post/publish/status/fetch/",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
                json={"publish_id": pid}))
        except (TransientError, QuotaError, AuthError, PermanentError, httpx.HTTPError):
            return PublishResult(pid, None, "unknown", "api_draft", pending=True)
        status = st.get("status")
        if not tracking.get("direct", True) and status == "SEND_TO_USER_INBOX":
            return PublishResult(pid, None, "draft", "api_draft", "Open TikTok's inbox to finish this upload and add the caption from the dashboard.")
        if status == "FAILED":
            raise PermanentError(f"tiktok: TikTok could not publish the video ({st.get('fail_reason', 'no reason given')})")
        if status != "PUBLISH_COMPLETE":
            return PublishResult(pid, None, "unknown", "api_draft", pending=True)
        privacy = tracking.get("privacy_level")
        visibility = PRIVACY_NAME.get(privacy, "unknown")
        post_ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
        username = tracking.get("creator_username")
        url = f"https://www.tiktok.com/@{username}/video/{post_ids[0]}" if post_ids and username else None
        if privacy == "SELF_ONLY":
            return PublishResult(pid, url, "private", "api_draft",
                                 "Posted as 'Only me' (TikTok allows only this until the app is approved). Open it in TikTok "
                                 "and change who can watch if you want it public.")
        return PublishResult(str(post_ids[0]) if post_ids else pid, url, visibility, "api" if privacy == "PUBLIC_TO_EVERYONE" else "api_draft",
                             None if privacy == "PUBLIC_TO_EVERYONE" else f"Posted for {visibility} only, as chosen.")


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
        media_id = self._upload_picture(thumb, token)
        payload: dict = {"text": text, **({"media": {"media_ids": [media_id]}} if media_id else {})}
        try:
            r = self.client.post("https://api.x.com/2/tweets", json=payload,
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


    def _upload_picture(self, thumb, token: str) -> str | None:
        """The video's thumbnail uploaded for the post. Nothing is posted yet, so any problem (an older login without
        the media permission, a busy server) just sends the post as text."""
        if not (thumb and Path(thumb).exists()):
            return None
        try:
            r = self.client.post("https://api.x.com/2/media/upload", headers={"Authorization": f"Bearer {token}"},
                                 data={"media_category": "tweet_image", "media_type": "image/jpeg"},
                                 files={"media": ("thumb.jpg", Path(thumb).read_bytes(), "image/jpeg")})
        except (httpx.TimeoutException, httpx.TransportError):
            return None
        if r.status_code >= 400:
            return None
        body = r.json() if r.content else {}
        mid = (body.get("data") or {}).get("id") or body.get("media_id_string")
        return str(mid) if mid else None


ADAPTERS = {"youtube": YouTube, "facebook": Facebook, "tiktok": TikTok, "x": X}
