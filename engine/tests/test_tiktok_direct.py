"""TikTok Direct Post with the owner's confirmed choices; inbox draft otherwise."""

import pytest

from studio.errors import PermanentError
from studio.publish import adapters

CREATOR = {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"], "comment_disabled": False, "duet_disabled": True,
           "stitch_disabled": False, "max_video_post_duration_sec": 600, "can_post": True, "creator_username": "pennyandpixel"}
CHOICES = {"privacy_level": "PUBLIC_TO_EVERYONE", "allow_comment": True, "allow_duet": True, "allow_stitch": False,
           "disclose": False, "confirmed_at": "2026-11-10T00:00:00Z"}


def test_post_info_uses_choices_and_respects_creator_switches():
    info = adapters.tiktok_post_info(CHOICES, CREATOR, "Caption #ai", True, 30)
    assert info["privacy_level"] == "PUBLIC_TO_EVERYONE"
    assert info["disable_comment"] is False
    assert info["disable_duet"] is True          # the creator turned Duet off in TikTok
    assert info["disable_stitch"] is True        # the owner didn't opt in
    assert info["is_aigc"] is True and info["brand_content_toggle"] is False


@pytest.mark.parametrize("change,msg", [
    ({"privacy_level": "FOLLOWER_OF_CREATOR"}, "no longer an allowed audience"),
    ({"privacy_level": "SELF_ONLY", "disclose": True, "branded_content": True}, "can't be private"),
    ({"disclose": True}, "neither"),
])
def test_post_info_refuses_choices_tiktok_doesnt_allow(change, msg):
    with pytest.raises(PermanentError, match=msg):
        adapters.tiktok_post_info({**CHOICES, **change}, CREATOR, "c", False, 30)


def test_post_info_refuses_too_long_video():
    with pytest.raises(PermanentError, match="at most 600"):
        adapters.tiktok_post_info(CHOICES, CREATOR, "c", False, 700)


class _R:
    def __init__(self, data, code=200):
        self.status_code, self._d, self.text, self.headers = code, data, "", {}
        self.is_success = code < 300
    def json(self): return self._d


class _Client:
    def __init__(self, status="PUBLISH_COMPLETE"):
        self.calls, self.status = [], status
    def post(self, url, headers=None, json=None):
        self.calls.append((url.rsplit("/v2/", 1)[1], json))
        if "creator_info" in url:
            return _R({"data": CREATOR, "error": {"code": "ok"}})
        if "status/fetch" in url:
            return _R({"data": {"status": self.status, "publicaly_available_post_id": [7123]}, "error": {"code": "ok"}})
        return _R({"data": {"publish_id": "p1", "upload_url": "https://up"}, "error": {"code": "ok"}})
    def put(self, url, content=None, headers=None):
        return _R({}, 201)


@pytest.fixture
def video(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"0" * 1000)
    return f


def _tt(monkeypatch, client, scopes):
    monkeypatch.setattr(adapters.db, "one", lambda *a, **k: {"scopes": scopes})
    monkeypatch.setattr(adapters, "_seconds", lambda v: 30.0)
    t = adapters.TikTok(client)
    t.poll_seconds = 0
    return t


def test_confirmed_post_goes_out_directly_and_public(monkeypatch, video):
    c = _Client()
    t = _tt(monkeypatch, c, ["user.info.basic", "video.upload", "video.publish"])
    r = t.publish(None, {"id": "a"}, {"body": "Hello", "hashtags": ["ai"], "tiktok_post": CHOICES}, video, None, "tok")
    paths = [p for p, _ in c.calls]
    assert "post/publish/video/init/" in paths and "post/publish/inbox/video/init/" not in paths
    init = next(j for p, j in c.calls if p == "post/publish/video/init/")
    assert init["post_info"]["title"] == "Hello #ai"
    assert r.method == "api" and r.visibility == "public" and r.url == "https://www.tiktok.com/@pennyandpixel/video/7123"


def test_without_confirmed_settings_it_is_an_inbox_draft(monkeypatch, video):
    c = _Client()
    t = _tt(monkeypatch, c, ["user.info.basic", "video.upload", "video.publish"])
    r = t.publish(None, {"id": "a"}, {"body": "Hello", "tiktok_post": None}, video, None, "tok")
    assert [p for p, _ in c.calls] == ["post/publish/inbox/video/init/"] and r.method == "api_draft"


def test_without_video_publish_permission_it_is_an_inbox_draft(monkeypatch, video):
    c = _Client()
    t = _tt(monkeypatch, c, ["user.info.basic", "video.upload"])
    r = t.publish(None, {"id": "a"}, {"body": "Hello", "tiktok_post": CHOICES}, video, None, "tok")
    assert r.method == "api_draft" and "creator_info" not in str(c.calls)


def test_private_post_says_so(monkeypatch, video):
    c = _Client()
    t = _tt(monkeypatch, c, ["video.publish"])
    r = t.publish(None, {"id": "a"}, {"body": "x", "tiktok_post": {**CHOICES, "privacy_level": "SELF_ONLY"}}, video, None, "tok")
    assert r.visibility == "private" and r.manual_followup


def test_tiktok_failure_is_reported(monkeypatch, video):
    t = _tt(monkeypatch, _Client(status="FAILED"), ["video.publish"])
    with pytest.raises(PermanentError, match="could not publish"):
        t.publish(None, {"id": "a"}, {"body": "x", "tiktok_post": CHOICES}, video, None, "tok")
