"""Scene-based video rendering with FFmpeg, driven entirely by a small JSON *recipe*.

The recipe (script scenes + voice + visual specs + asset references) is stored forever;
any video can be re-rendered from it at preview or final quality. Each scene clip is
cached by content hash, so changing scene 4 only re-renders scene 4 and the final join.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..errors import PermanentError, TransientError
from . import captions, tts
from . import animate
from .visuals import Frame, Theme, card_file

FPS = int(os.environ.get("STUDIO_FPS", "30"))


@dataclass
class RenderResult:
    video: Path
    duration: float
    scenes: list[dict]
    seconds_taken: float
    bytes: int
    cached_scenes: int = 0
    stats: dict = field(default_factory=dict)


def ffmpeg(args: list[str], timeout: int = 1800) -> None:
    if not shutil.which("ffmpeg"):
        raise PermanentError("FFmpeg is not installed")
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise TransientError(f"ffmpeg failed: {proc.stderr[-800:]}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True)
    return float(json.loads(out.stdout or "{}").get("format", {}).get("duration", 0.0))


def _scaled(w: int, h: int) -> tuple[int, int]:
    """STUDIO_RENDER_SCALE shrinks frames (tests only); dimensions stay even for H.264."""
    s = float(os.environ.get("STUDIO_RENDER_SCALE", "1"))
    return (max(int(w * s) // 2 * 2, 64), max(int(h * s) // 2 * 2, 64)) if s != 1 else (w, h)


def size_for(fmt: str, quality: str) -> tuple[int, int, int, str]:
    w, h, crf, preset = _size_for(fmt, quality)
    return (*_scaled(w, h), crf, preset)


def _size_for(fmt: str, quality: str) -> tuple[int, int, int, str]:
    r = config.services()["render"]
    if quality == "preview":
        p = r["preview"]["long" if fmt == "long" else "short"]
        return p["width"], p["height"], p["crf"], "ultrafast"
    q = r["long" if fmt == "long" else "short"]
    return q["width"], q["height"], q["crf"], q["preset"]


def _limit_animations(scenes: list[dict], fmt: str) -> None:
    """Keep the mix balanced: at most a few animated scenes, each with what its template needs; others go still."""
    cap = int(config.services()["render"].get("animated_max_" + ("long" if fmt == "long" else "short"), 4 if fmt == "long" else 1))
    used = 0
    for sc in scenes:
        v = sc["visual"]
        if v.get("type") != "animated":
            continue
        if used < cap and animate.usable(v):
            used += 1
        else:
            sc["visual"] = animate.as_static(v)


def recipe_from_script(script: dict, channel: str, fmt: str, title: str) -> dict:
    """Turn a validated Script/ShortScript dict into a render recipe (hook + scenes + outro)."""
    ch = config.brand()["channels"][channel]
    brand = config.brand()["brand"]
    vp = ch["voice_profile"]
    scenes = [{"narration": script["hook"], "visual": {"type": "title_card", "headline": script.get("title", title)},
               "kicker": None}]
    for sc in script["scenes"]:
        visual = dict(sc["visual"])
        if not visual.get("headline") and sc.get("on_screen_text"):
            visual["headline"] = sc["on_screen_text"]
        if visual["type"] in ("title_card", "stock") and not visual.get("headline"):
            visual["headline"] = sc["narration"].split(".")[0][:90]
        scenes.append({"narration": sc["narration"], "visual": visual,
                       "kicker": sc.get("on_screen_text") if visual.get("headline") != sc.get("on_screen_text") else None,
                       "source_note": (visual.get("chart") or {}).get("source_note") or None})
    _limit_animations(scenes, fmt)
    if fmt == "long" and script.get("cta"):
        scenes.append({"narration": script["cta"],
                       "visual": {"type": "title_card", "headline": f"Subscribe to {ch['display_name']}"},
                       "kicker": "Thanks for watching"})
    elif fmt == "short":
        scenes.append({"narration": "", "visual": {"type": "title_card", "headline": f"Follow {brand['handles']['tiktok']}"},
                       "kicker": brand["name"], "silent_seconds": 1.5})
    return {"version": 1, "format": fmt, "channel": channel, "title": title, "voice": vp["tts_voice"],
            "speed": float(vp.get("tts_speed", 1.0)), "scenes": scenes}


CLIP_SECONDS = 20  # a stock clip is cut to this length (it loops if a scene runs longer)


def prepare_clip(src: Path, out: Path, fmt: str) -> Path:
    """A stock clip made storage-friendly: cut to CLIP_SECONDS, cropped to the video's frame, no sound, compact."""
    w, h, _, _ = _size_for(fmt, "final")
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg(["-i", str(src), "-t", str(CLIP_SECONDS), "-an", "-vf",
                f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(out)], timeout=600)
    return out


def _animated_clip(sc, theme, frame, dur, wav, ahash, w, h, crf, preset, card_dir, clip_dir, effect=None) -> tuple[Path, int]:
    """An animated scene with its narration (and a quiet sound effect, if one was found). If the animation can't be
    drawn, the scene is shown still instead."""
    vhash = animate.animation_hash(sc["visual"], theme, frame, dur, FPS)
    effect = effect if effect is not None and Path(effect).exists() else None
    ehash = _file_hash(effect) if effect else ""
    key = hashlib.sha256(f"{vhash}|{ahash}|{w}x{h}|{crf}|{preset}|anim-clip-v1{('|' + ehash) if ehash else ''}".encode()).hexdigest()[:24]
    clip = clip_dir / f"clip_{key}.mp4"
    if clip.exists():
        return clip, 1
    silent = card_dir / f"anim_{vhash}.mp4"
    try:
        if not silent.exists():
            animate.render_animation(sc["visual"], theme, frame, dur, FPS, silent)
        fade = f"[0:v]fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.18,fade=t=out:st={max(dur - 0.18, 0):.2f}:d=0.18[v]"
        if effect:  # under the voice, starting as the movement starts
            inputs = ["-i", str(silent), "-i", str(wav), "-i", str(effect)]
            graph = fade + ";[2:a]volume=0.22,adelay=250|250,apad[e];[1:a][e]amix=inputs=2:duration=first:normalize=0[a]"
            amap = "[a]"
        else:
            inputs, graph, amap = ["-i", str(silent), "-i", str(wav)], fade, "1:a"
        ffmpeg([*inputs, "-filter_complex", graph,
                "-map", "[v]", "-map", amap, "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                "-t", f"{dur:.3f}", str(clip)])
        return clip, 0
    except Exception:
        still = {**sc, "visual": animate.as_static(sc["visual"])}
        card, chash = card_file(still["visual"], theme, frame, card_dir, kicker=sc.get("kicker"),
                                source_note=sc.get("source_note"))
        frames = max(int(math.ceil(dur * FPS)), 1)
        ffmpeg(["-loop", "1", "-i", str(card), "-i", str(wav), "-filter_complex",
                f"[0:v]scale={w}:{h},fps={FPS},format=yuv420p[v]", "-map", "[v]", "-map", "1:a",
                "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-b:a", "128k", "-ar", "48000", "-ac", "2", "-frames:v", str(frames), "-t", f"{dur:.3f}", str(clip)])
        return clip, 0


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _silence(path: Path, seconds: float) -> None:
    ffmpeg(["-f", "lavfi", "-i", f"anullsrc=r={tts.SAMPLE_RATE}:cl=mono", "-t", f"{seconds:.2f}", str(path)])


def render(recipe: dict, out_path: Path, quality: str = "preview", work_dir: Path | None = None,
           photos: dict[int, Path] | None = None, music: Path | None = None,
           videos: dict[int, Path] | None = None, effects: dict[int, Path] | None = None) -> RenderResult:
    started = time.monotonic()
    work = work_dir or (config.runtime().work_dir / "render")
    audio_dir, card_dir, clip_dir = work / "audio", work / "cards", work / "clips"
    for d in (audio_dir, card_dir, clip_dir):
        d.mkdir(parents=True, exist_ok=True)
    fmt, channel = recipe["format"], recipe["channel"]
    w, h, crf, preset = size_for(fmt, quality)
    frame, theme = Frame(w, h), Theme.for_channel(channel)
    clips, timeline, cached, t = [], [], 0, 0.0
    for i, sc in enumerate(recipe["scenes"]):
        if sc.get("narration"):
            wav, dur, ahash = tts.synthesize(sc["narration"], recipe["voice"], recipe["speed"], audio_dir)
        else:
            dur = float(sc.get("silent_seconds", 1.5))
            ahash = f"silence{dur:.2f}"
            wav = audio_dir / f"{ahash}.wav"
            if not wav.exists():
                _silence(wav, dur)
        photo = (photos or {}).get(i)
        video = (videos or {}).get(i)
        if sc["visual"].get("type") == "animated":
            clip, was_cached = _animated_clip(sc, theme, frame, dur, wav, ahash, w, h, crf, preset, card_dir, clip_dir,
                                              (effects or {}).get(i))
            cached += was_cached
            clips.append(clip)
            timeline.append({"index": i, "narration": sc.get("narration", ""), "start": round(t, 3), "duration": round(dur, 3),
                             "audio_hash": ahash, "card_hash": clip.stem, "clip": clip.name})
            t += dur
            continue
        if video is not None and not Path(video).exists():
            video = None
        card, chash = card_file(sc["visual"], theme, frame, card_dir, kicker=sc.get("kicker"),
                                photo=None if video else photo, source_note=sc.get("source_note"),
                                over_video=video is not None)
        vhash = _file_hash(video) if video else ""
        key = hashlib.sha256(f"{chash}|{ahash}|{w}x{h}|{crf}|{preset}|clip-v2{('|' + vhash) if vhash else ''}".encode()).hexdigest()[:24]
        clip = clip_dir / f"clip_{key}.mp4"
        if clip.exists():
            cached += 1
        elif video:
            # a real clip under the scene's words: cropped to the frame, looped if shorter than the narration, its own
            # sound dropped (the narration is the only voice)
            ffmpeg(["-stream_loop", "-1", "-i", str(video), "-i", str(card), "-i", str(wav), "-filter_complex",
                    f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1[b];"
                    f"[b][1:v]overlay=0:0,format=yuv420p,"
                    f"fade=t=in:st=0:d=0.18,fade=t=out:st={max(dur - 0.18, 0):.2f}:d=0.18[v]",
                    "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                    "-t", f"{dur:.3f}", str(clip)])
        else:
            frames = max(int(math.ceil(dur * FPS)), 1)
            zoom = "1+0.035*on/{}".format(frames) if i % 2 == 0 else "1.035-0.035*on/{}".format(frames)
            ffmpeg(["-i", str(card), "-i", str(wav), "-filter_complex",
                    f"[0:v]scale={int(w * 1.5)}:-2,zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    f":d={frames}:s={w}x{h}:fps={FPS},format=yuv420p,"
                    f"fade=t=in:st=0:d=0.18,fade=t=out:st={max(dur - 0.18, 0):.2f}:d=0.18[v]",
                    "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                    "-t", f"{dur:.3f}", str(clip)])
        clips.append(clip)
        timeline.append({"index": i, "narration": sc.get("narration", ""), "start": round(t, 3), "duration": round(dur, 3),
                         "audio_hash": ahash, "card_hash": chash, "clip": clip.name})
        t += dur

    concat = work / f"concat_{out_path.stem}.txt"
    concat.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    ass = captions.build_ass([s for s in timeline if s["narration"]], theme, w, h, work / f"{out_path.stem}.ass")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = ["-f", "concat", "-safe", "0", "-i", str(concat)]
    vf = f"ass='{ass.resolve()}'"
    if music and music.exists():
        args += ["-stream_loop", "-1", "-i", str(music), "-filter_complex",
                 f"[0:v]{vf}[v];[1:a]volume=0.14[m];[m][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
                 f"[0:a][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]",
                 "-map", "[v]", "-map", "[a]"]
    else:
        args += ["-vf", vf, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    args += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k" if quality == "final" else "96k", "-ar", "48000",
             "-movflags", "+faststart", "-t", f"{t:.3f}", str(out_path)]
    ffmpeg(args, timeout=3600)
    return RenderResult(out_path, probe_duration(out_path), timeline, round(time.monotonic() - started, 2),
                        out_path.stat().st_size, cached, {"width": w, "height": h, "quality": quality})


def narration_m4a(wav: Path, out: Path) -> Path:
    """Compact narration copy for the recipe archive (~1 MB per 3 minutes)."""
    ffmpeg(["-i", str(wav), "-c:a", "aac", "-b:a", "48k", str(out)])
    return out
