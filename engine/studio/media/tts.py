"""Narration with Kokoro (open source, Apache-2.0, runs on CPU). Cached by content hash."""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from .. import config

MODEL_URLS = {
    "kokoro-v1.0.int8.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
SAMPLE_RATE = 24000
SCENE_PAUSE_SECONDS = 0.35


def model_dir() -> Path:
    d = config.runtime().cache_dir / "kokoro"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_models() -> Path:
    d = model_dir()
    for name, url in MODEL_URLS.items():
        target = d / name
        if target.exists() and target.stat().st_size > 1_000_000:
            continue
        tmp = target.with_suffix(".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
            r.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
        tmp.rename(target)
    return d


@lru_cache(maxsize=1)
def _kokoro():
    from kokoro_onnx import Kokoro

    d = ensure_models()
    return Kokoro(str(d / "kokoro-v1.0.int8.onnx"), str(d / "voices-v1.0.bin"))


def speech_hash(text: str, voice: str, speed: float) -> str:
    return hashlib.sha256(f"kokoro-v1|{voice}|{speed:.2f}|{text}".encode()).hexdigest()[:24]


def synthesize(text: str, voice: str, speed: float, out_dir: Path) -> tuple[Path, float, str]:
    """Write narration WAV (with a short trailing pause). Returns (path, seconds, hash)."""
    h = speech_hash(text, voice, speed)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{h}.wav"
    if path.exists():
        info = sf.info(str(path))
        return path, info.frames / info.samplerate, h
    if os.environ.get("STUDIO_TTS") == "silent":
        # Test-only engine: silence sized to the words. Never used for real content.
        seconds = max(len(text.split()) / 2.5, 0.8)
        samples = np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)
        sr = SAMPLE_RATE
    else:
        samples, sr = _kokoro().create(text, voice=voice, speed=speed, lang="en-us")
    pause = np.zeros(int(SCENE_PAUSE_SECONDS * sr), dtype=np.float32)
    audio = np.concatenate([np.asarray(samples, dtype=np.float32), pause])
    sf.write(str(path), audio, sr)
    return path, len(audio) / sr, h
