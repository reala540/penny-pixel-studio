"""Choosing the YouTube playlist for an upload, and the safe fallbacks."""

from studio.publish import playlists as pl

AI = [{"id": "P1", "title": "AI Tools for Work", "description": "ChatGPT, Gemini and other assistants at work"},
      {"id": "P2", "title": "Robotics and Simulation", "description": "NVIDIA Cosmos, robots and world models"},
      {"id": "P3", "title": "Shorts", "description": ""}]


def test_long_video_goes_to_the_topic_playlist_and_never_to_shorts():
    p, why = pl.choose(AI, {"title": "NVIDIA Cosmos 3: Building a Mini Metaverse", "tags": ["robots"], "body": ""}, "long_video")
    assert p["id"] == "P2" and "topic" in why


def test_a_short_goes_to_the_single_shorts_playlist():
    p, _ = pl.choose(AI, {"title": "Cosmos robots in 60 seconds", "tags": [], "body": ""}, "short_video")
    assert p["id"] == "P3"


def test_nothing_matches_means_no_playlist():
    p, why = pl.choose(AI, {"title": "Budget basics", "tags": [], "body": ""}, "long_video")
    assert p is None and "no playlist" in why


def test_owner_rules_win_and_default_catches_the_rest():
    rules = [{"playlist_id": "P1", "keywords": ["metaverse"]}, {"playlist_id": "P2", "default": True}]
    assert pl.choose(AI, {"title": "Mini Metaverse with Cosmos", "tags": [], "body": ""}, "long_video", rules)[0]["id"] == "P1"
    assert pl.choose(AI, {"title": "Budget basics", "tags": [], "body": ""}, "long_video", rules)[0]["id"] == "P2"
    # a rule for a playlist that no longer exists is ignored
    assert pl.choose(AI, {"title": "Budget basics", "tags": [], "body": ""}, "long_video",
                     [{"playlist_id": "GONE", "default": True}])[0] is None


class _Resp:
    def __init__(self, code, data=None):
        self.status_code, self._d, self.text = code, data or {}, ""
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 300: raise RuntimeError("http")


class _Client:
    def __init__(self): self.posts = []
    def get(self, url, **k):
        return _Resp(200, {"items": [{"id": i["id"], "snippet": {"title": i["title"], "description": i["description"]}} for i in AI]})
    def post(self, url, **k):
        self.posts.append(k["json"]); return _Resp(200, {})


def test_place_adds_with_permission_and_makes_a_todo_without(monkeypatch):
    calls, audits = [], []
    settings = {}
    monkeypatch.setattr(pl.db, "get_setting", lambda c, k, d=None: settings.get(k, d))
    monkeypatch.setattr(pl.db, "run", lambda c, q, a=None: calls.append(q))
    monkeypatch.setattr(pl.db, "audit", lambda c, act, *a, **k: audits.append(act))
    scopes = {"scopes": []}
    monkeypatch.setattr(pl.db, "one", lambda c, q, a=None: scopes)
    ctx = {"kind": "long_video", "title": "NVIDIA Cosmos 3 robots", "tags": [], "body": ""}
    cl = _Client()
    assert pl.place(None, cl, "t", {"id": "a"}, ctx, "VID", "post") == "manual"
    assert not cl.posts and any("manual_tasks" in q for q in calls)
    scopes["scopes"] = ["https://www.googleapis.com/auth/youtube.force-ssl"]
    assert pl.place(None, cl, "t", {"id": "a"}, ctx, "VID", "post") == "added"
    assert cl.posts[0]["snippet"]["playlistId"] == "P2"
    assert "youtube_playlist_added" in audits


def test_place_never_raises(monkeypatch):
    monkeypatch.setattr(pl.db, "get_setting", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(pl.db, "audit", lambda *a, **k: None)
    assert pl.place(None, _Client(), "t", {"id": "a"}, {}, "VID", "post") == "failed"
