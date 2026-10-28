"""Original animated scenes: a balanced few per video, numbers the narrator says, a still fallback, one-scene
previews, and optional CC0 sound effects. Network calls are faked."""

import subprocess
import uuid

import httpx
import pytest

from studio import db, produce
from studio.media import animate, sfx
from studio.media import render as rendering
from studio.media.visuals import Frame, Theme
from studio.script import quality
from studio.script.models import Script, Scene, Visual

from .test_database import as_user, reset_role
from .test_end_to_end import silent_tts  # noqa: F401  (fixture)
from .test_produce_idea import setup_ideas

JARS = {"type": "animated", "animation": "budget_jars", "headline": "Your paycheck", "items": ["Needs|$1,500", "Wants|$900", "Savings|$600"]}
BASKET = {"type": "animated", "animation": "price_basket", "headline": "One year later", "items": ["Eggs|$3.20|$4.10"]}
AGENTS = {"type": "animated", "animation": "agent_handoff", "headline": "Agents", "items": ["Research", "Write", "Check"]}
COUNTER = {"type": "animated", "animation": "counter", "headline": "Pilots", "stat_value": "53%", "stat_label": "reach production"}


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.split()
    return out


def test_numbers_and_still_versions():
    assert animate.parse_number("$1,200") == ("$", 1200.0, "", 0)
    assert animate.parse_number("53%") == ("", 53.0, "%", 0)
    assert animate.fmt_value("$", 3.2, "", 2) == "$3.20"
    assert all(animate.usable(v) for v in (JARS, BASKET, AGENTS, COUNTER))
    assert not animate.usable({**JARS, "items": ["Only one|$5"]})
    assert animate.as_static(JARS) == {"type": "list", "headline": "Your paycheck", "items": ["Needs: $1,500", "Wants: $900", "Savings: $600"]}
    assert animate.as_static(COUNTER)["type"] == "stat"


def test_every_template_draws_each_frame_in_both_shapes():
    for v, ch in ((JARS, "money"), (BASKET, "money"), (AGENTS, "ai"), (COUNTER, "ai")):
        for fr in (Frame(480, 270), Frame(270, 480)):
            for p in (0, 0.3, 0.7, 1):
                img = animate.frame_image(v, Theme.for_channel(ch), fr, p)
                assert img.size == (fr.width, fr.height)


def test_animation_becomes_a_video(tmp_path, silent_tts):
    out = animate.render_animation(COUNTER, Theme.for_channel("ai"), Frame(320, 180), 1.5, 6, tmp_path / "a.mp4")
    assert "video,320,180" in _probe(out)


def test_only_a_few_animated_scenes_per_video_and_bad_ones_go_still():
    scenes = [{"narration": f"Scene {i}.", "visual": dict(JARS)} for i in range(6)]
    scenes.append({"narration": "x", "visual": {**JARS, "items": ["broken"]}})
    script = {"title": "T", "hook": "H", "scenes": scenes, "cta": "Bye"}
    r = rendering.recipe_from_script(script, "money", "long", "T")
    kinds = [s["visual"]["type"] for s in r["scenes"]]
    assert kinds.count("animated") == 4                            # the cap for a long video
    assert kinds[-2] == "list"                                     # the unusable one is shown still
    short = rendering.recipe_from_script({"title": "T", "hook": "H", "scenes": scenes[:3]}, "money", "short", "T")
    assert [s["visual"]["type"] for s in short["scenes"]].count("animated") == 1


def test_an_animation_may_only_show_numbers_the_narrator_says():
    bad = Scene(narration="Needs and wants take most of it.", visual=Visual(**JARS))
    good = Scene(narration="Needs take $1,500, wants $900 and savings $600.", visual=Visual(**JARS))
    assert quality.animation_numbers([bad])[0].startswith("Scene 1 animation shows numbers")
    assert quality.animation_numbers([good]) == []


def test_animated_scene_renders_with_narration_and_is_cached(tmp_path, silent_tts, monkeypatch):
    recipe = rendering.recipe_from_script({"title": "T", "hook": "Look at this.", "scenes": [
        {"narration": "Needs take $1,500, wants $900 and savings $600.", "visual": JARS}]}, "money", "short", "T")
    out = rendering.render(recipe, tmp_path / "o.mp4", "preview", work_dir=tmp_path / "w")
    assert out.video.exists() and any(x.startswith("audio") for x in _probe(out.video))
    again = rendering.render(recipe, tmp_path / "o2.mp4", "preview", work_dir=tmp_path / "w")
    assert again.cached_scenes == len(recipe["scenes"])
    # an animation that can't be drawn: the scene is shown still, the video still renders
    monkeypatch.setitem(animate.DRAW, "budget_jars", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    recipe["scenes"][1]["narration"] += " Really."
    assert rendering.render(recipe, tmp_path / "o3.mp4", "preview", work_dir=tmp_path / "w").video.exists()


def test_sound_effects_are_cc0_only_and_optional(tmp_path, monkeypatch):
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    assert sfx.find_effect("budget_jars", tmp_path) is None
    monkeypatch.setenv("FREESOUND_API_KEY", "k")

    def handler(req):
        if "apiv2/search" in str(req.url):
            return httpx.Response(200, json={"results": [
                {"id": 1, "name": "attribution needed", "url": "https://fs.test/1", "username": "a",
                 "license": "http://creativecommons.org/licenses/by/4.0/", "previews": {"preview-hq-mp3": "https://cdn.fs/1.mp3"}},
                {"id": 2, "name": "coin", "url": "https://fs.test/2", "username": "b",
                 "license": "http://creativecommons.org/publicdomain/zero/1.0/", "previews": {"preview-hq-mp3": "https://cdn.fs/2.mp3"}}]})
        if str(req.url) == "https://cdn.fs/2.mp3":
            return httpx.Response(200, content=b"ID3fake")
        return httpx.Response(404)
    hit = sfx.find_effect("budget_jars", tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert hit and hit.source_url == "https://fs.test/2" and "CC0" in hit.license


def test_preview_one_scene_and_owner_can_ask_for_it(synced, monkeypatch, silent_tts):
    c = synced
    router, storage, ideas = setup_ideas(c, monkeypatch, n=1)
    out = produce.produce_idea(c, router, storage, content_idea_id=ideas[0]["id"])
    pid = out["project_id"]
    res = produce.preview_scene(c, storage, pid, 0)
    rec = db.one(c, "select recipe from content_projects where id=%s", (pid,))["recipe"]
    assert rec["scene_previews"]["0"]["key"] == res["key"] and res["seconds"] > 0
    with pytest.raises(ValueError, match="doesn't exist"):
        produce.preview_scene(c, storage, pid, 999)
    as_user(c, str(uuid.uuid4()))
    db.one(c, "select public.claim_ownership() ok")
    job = db.one(c, "select public.enqueue_owner_job('preview_scene', %s, '{\"scene\": 0}'::jsonb) id", (pid,))["id"]
    reset_role(c)
    assert db.one(c, "select job_type from generation_jobs where id=%s", (job,))["job_type"] == "preview_scene"
    db.run(c, "insert into app_secrets (name, ciphertext) values ('FREESOUND_API_KEY', 'x')")   # the key can be saved


def test_effects_attach_with_licences(synced, tmp_path, monkeypatch):
    c = synced
    f = tmp_path / "coin.mp3"
    f.write_bytes(b"ID3")
    monkeypatch.setattr(sfx, "find_effect", lambda a, out_dir, client=None: sfx.StockPhoto(
        f, f"https://fs.test/{a}", "freesound", "b", "CC0 1.0 (public domain dedication), via Freesound", False, "coin (CC0)"))
    from studio.storage import LocalStorage
    pid = db.one(c, "insert into content_projects (channel_slug, format, title, status) values ('money','long','T','rendering') returning id")["id"]
    recipe = {"format": "long", "scenes": [{"visual": dict(JARS)}, {"visual": {"type": "title_card"}}]}
    effects = produce.attach_effects(c, LocalStorage(tmp_path / "s"), pid, recipe, tmp_path / "w")
    assert list(effects) == [0] and recipe["scenes"][0]["sfx_key"] and recipe["scenes"][0]["sfx_license_record_id"]
