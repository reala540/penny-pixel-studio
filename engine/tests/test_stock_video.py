"""Real stock video clips (Pexels / Pixabay) under a scene's words, platform limits before approval, and a caption
per platform for Shorts. All network calls are faked."""

import subprocess

import httpx

from studio import db, produce
from studio.media import render as rendering
from studio.media import stock
from studio.publish import limits

from .test_end_to_end import silent_tts  # noqa: F401  (fixture)


def _testsrc(path, seconds=2, size="320x180"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=6",
                    "-t", str(seconds), "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    return tuple(int(x) for x in out.split(","))


def test_pexels_clip_is_found_with_a_licence_and_a_sensible_size(tmp_path, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    src = _testsrc(tmp_path / "src.mp4").read_bytes()
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if "api.pexels.com/videos/search" in str(req.url):
            return httpx.Response(200, json={"videos": [
                {"url": "https://pexels.test/v/short", "duration": 2, "user": {"name": "A"}, "video_files": []},
                {"url": "https://pexels.test/v/1", "duration": 12, "user": {"name": "Ana"}, "video_files": [
                    {"link": "https://cdn.test/4k.mp4", "width": 3840, "height": 2160, "file_type": "video/mp4"},
                    {"link": "https://cdn.test/hd.mp4", "width": 1920, "height": 1080, "file_type": "video/mp4"},
                    {"link": "https://cdn.test/sd.mp4", "width": 640, "height": 360, "file_type": "video/mp4"}]}]})
        if "cdn.test/hd.mp4" in str(req.url):
            return httpx.Response(200, content=src)
        return httpx.Response(404)
    hit = stock.find_video("people shopping", tmp_path / "raw", "landscape",
                           client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert hit and hit.provider == "pexels-video" and hit.source_url == "https://pexels.test/v/1"
    assert "Pexels License" in hit.license and hit.path.exists()
    assert any("hd.mp4" in u for u in seen) and not any("4k.mp4" in u for u in seen)   # the smallest full-HD file


def test_no_keys_or_no_results_means_no_clip(tmp_path, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    assert stock.find_video("anything", tmp_path) is None
    monkeypatch.setenv("PIXABAY_API_KEY", "k")
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"hits": []})))
    assert stock.find_video("anything", tmp_path, client=client) is None


def test_clip_is_trimmed_and_cropped_then_rendered_under_the_words(tmp_path, silent_tts):
    raw = _testsrc(tmp_path / "raw.mp4", seconds=3, size="640x360")
    small = rendering.prepare_clip(raw, tmp_path / "small.mp4", "short")
    w, h, _, _ = rendering._size_for("short", "final")
    assert _probe(small) == (w, h)                                     # cut to the vertical frame, no sound kept
    recipe = rendering.recipe_from_script({"title": "T", "hook": "A quick look at prices.", "scenes": [
        {"narration": "Prices rose again this month.", "visual": {"type": "stock", "headline": "Prices rose", "stock_query": "groceries"}},
        {"narration": "Here is what that means.", "visual": {"type": "title_card", "headline": "What it means"}}]},
        "money", "short", "T")
    out = rendering.render(recipe, tmp_path / "out.mp4", "preview", work_dir=tmp_path / "work", videos={1: small})
    assert out.video.exists() and out.duration > 1
    again = rendering.render(recipe, tmp_path / "out2.mp4", "preview", work_dir=tmp_path / "work", videos={1: small})
    assert again.cached_scenes == len(recipe["scenes"])                # unchanged scenes are never redrawn


def test_stock_scenes_mix_clips_and_photos_with_licences(synced, tmp_path, monkeypatch, silent_tts):
    c = synced
    clip = rendering.prepare_clip(_testsrc(tmp_path / "c.mp4"), tmp_path / "prepared" / "c.mp4", "long")
    calls = {"video": 0}

    def fake_video(query, out_dir, orientation="landscape", **kw):
        calls["video"] += 1
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"clip_{calls['video']}.mp4"
        p.write_bytes(clip.read_bytes())
        return stock.StockPhoto(p, f"https://pexels.test/v/{calls['video']}", "pexels-video", "Ana",
                                "Pexels License (free commercial use, no attribution required)", False, "Video by Ana")
    monkeypatch.setattr(stock, "find_video", fake_video)
    monkeypatch.setattr(stock, "find_photo", lambda *a, **k: None)
    from studio.storage import LocalStorage
    storage = LocalStorage(tmp_path / "store")
    pid = db.one(c, "insert into content_projects (channel_slug, format, title, status) values ('money','long','T','rendering') returning id")["id"]
    recipe = {"format": "long", "title": "T", "scenes": [{"visual": {"type": "stock", "stock_query": f"q{i}"}} for i in range(4)]}
    photos, videos = produce.attach_media(c, storage, pid, recipe, tmp_path / "work")
    assert sorted(videos) == [0, 2] and calls["video"] == 2               # every other stock scene tries a clip
    for i in (0, 2):
        sc = recipe["scenes"][i]
        assert sc["video_key"] and sc["license_record_id"]
    assert db.one(c, "select count(*) n from media_assets where kind='video_clip' and license_record_id is not null")["n"] == 2
    assert recipe["scenes"][1]["visual"]["type"] == "title_card"           # no photo found: an original card instead


def test_platform_limits():
    assert limits.problems("x", "text_post", None, "a" * 281) == ["text is 281 characters (limit 280)"]
    assert "link" in limits.problems("x", "text_post", None, "read example.com")[0]
    assert limits.problems("youtube", "long_video", "t" * 101, "d")[0].startswith("title is 101")
    assert limits.problems("tiktok", "short_video", None, "x", hashtags=list("abcdef")) == ["6 hashtags (at most 5)"]
    assert limits.problems("facebook", "reel", None, "x" * 2195, hashtags=["ai", "tips"])[0].startswith("caption with hashtags is 2205")
    assert limits.problems("facebook", "story", None, None) == []


def test_each_platform_gets_its_own_short_caption():
    sb = {"title": "Rent vs buy", "caption": "The YouTube one", "tiktok_caption": "TikTok words", "reel_caption": "Reel words",
          "hashtags": ["#money", "rent", "housing", "budget", "home", "extra"]}
    t, body, tags = produce.short_caption(sb, "tiktok", "short_video", "x")
    assert body == "TikTok words" and len(tags) == 5
    assert produce.short_caption(sb, "facebook", "reel", "x")[1] == "Reel words"
    yt = produce.short_caption(sb, "youtube", "short_video", "x")
    assert yt[1].startswith("The YouTube one") and yt[1].endswith("#Shorts") and len(yt[2]) == 3
    plain = {"title": "T", "caption": "Only one", "hashtags": ["a"]}
    assert produce.short_caption(plain, "tiktok", "short_video", "x")[1] == "Only one"   # falls back to the main caption


def test_cleanup_keeps_a_clip_while_a_post_still_needs_it(synced, tmp_path, monkeypatch):
    import copy

    from studio import config, maintenance
    from studio.storage import LocalStorage

    real = config.services()
    soon = copy.deepcopy(real)
    soon["retention"]["preview_days_after_decision"] = -1   # every decided project counts as old enough
    monkeypatch.setattr(config, "services", lambda: soon)

    c = synced
    storage = LocalStorage(tmp_path / "store")
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"clip")
    key = storage.upload("projects/p/clips/clip.mp4", f, "video/mp4")
    pid = db.one(c, "insert into content_projects (channel_slug, format, title, status) values ('ai','short','S','published') returning id")["id"]
    db.run(c, "insert into media_assets (project_id, kind, storage_path) values (%s,'video_clip',%s)", (pid, key))
    acc = db.one(c, "select id from social_accounts where platform='facebook'")["id"]
    v = db.one(c, "insert into content_variants (project_id, social_account_id, kind, status) values (%s,%s,'story','approved') returning id", (pid, acc))["id"]
    db.run(c, "insert into scheduled_posts (variant_id, social_account_id, scheduled_at, status, idempotency_key) values (%s,%s,now()+interval '1 day','scheduled',%s)",
           (v, acc, f"post:{v}"))
    maintenance.cleanup(c, storage)
    assert db.one(c, "select deleted_at from media_assets where project_id=%s", (pid,))["deleted_at"] is None   # still needed
    db.run(c, "update scheduled_posts set status='published' where variant_id=%s", (v,))
    maintenance.cleanup(c, storage)
    assert db.one(c, "select deleted_at from media_assets where project_id=%s", (pid,))["deleted_at"] is not None
