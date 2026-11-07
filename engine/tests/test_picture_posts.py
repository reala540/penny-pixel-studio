"""Owner's request (7 Nov): posts go out with a picture (the video's thumbnail) and their text, on every platform
that takes written posts (Facebook and X; YouTube and TikTok only take videos)."""

import json

import httpx

from studio.publish import adapters


def _no_budget(monkeypatch):
    for name in ("reserve", "commit", "release"):
        monkeypatch.setattr(adapters.budget, name, lambda *a, **k: None)


def test_an_x_post_carries_the_picture(tmp_path, monkeypatch):
    _no_budget(monkeypatch)
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"\xff\xd8jpeg")
    sent = {}

    def handler(req):
        if req.url.path.endswith("/media/upload"):
            assert b"\xff\xd8jpeg" in req.content and b"tweet_image" in req.content
            return httpx.Response(200, json={"data": {"id": "m1"}})
        sent.update(json.loads(req.content))
        return httpx.Response(201, json={"data": {"id": "t1"}})

    x = adapters.X(httpx.Client(transport=httpx.MockTransport(handler)))
    res = x.publish(None, {}, {"kind": "text_post", "body": "Your raise vs inflation."}, None, thumb, "tok", "ref")
    assert res.platform_post_id == "t1"
    assert sent == {"text": "Your raise vs inflation.", "media": {"media_ids": ["m1"]}}


def test_if_the_picture_cant_be_uploaded_the_x_post_still_goes_out_as_text(tmp_path, monkeypatch):
    """An older X login without the media permission: nothing was posted yet, so the text goes out alone."""
    _no_budget(monkeypatch)
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"\xff\xd8jpeg")
    sent = {}

    def handler(req):
        if req.url.path.endswith("/media/upload"):
            return httpx.Response(403, json={"title": "Forbidden"})
        sent.update(json.loads(req.content))
        return httpx.Response(201, json={"data": {"id": "t2"}})

    x = adapters.X(httpx.Client(transport=httpx.MockTransport(handler)))
    res = x.publish(None, {}, {"kind": "text_post", "body": "Plain."}, None, thumb, "tok", "ref")
    assert res.platform_post_id == "t2" and sent == {"text": "Plain."}
