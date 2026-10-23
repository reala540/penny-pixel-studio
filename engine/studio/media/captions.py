"""Word-timed, highlighted captions (ASS format, burned in by FFmpeg/libass).

Timing comes from each scene's real narration length: words are spread across the
scene audio in proportion to their spoken length, which stays in sync because every
scene is synthesised separately.
"""

from __future__ import annotations

import re
from pathlib import Path

from .visuals import Theme, font_path


def _ass_color(rgb: tuple, alpha: int = 0) -> str:
    r, g, b = rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _ts(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _weight(word: str) -> float:
    core = re.sub(r"[^\w%$]", "", word)
    w = max(len(core), 2) + (3 if re.search(r"[.!?,;:]$", word) else 0)
    if re.search(r"\d", core):
        w += len(core) * 1.5  # numbers take longer to say
    return w


def chunk(words: list[str], max_words: int) -> list[list[str]]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or re.search(r"[.!?]$", w):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def build_ass(scenes: list[dict], theme: Theme, width: int, height: int, path: Path,
              lead_in: float = 0.05, tail: float = 0.35) -> Path:
    """scenes: [{narration, start, duration}] with absolute start times in seconds."""
    vertical = height > width
    size = int((78 if vertical else 62) * min(width, height) / 1080)
    margin_v = int(height * (0.30 if vertical else 0.08))
    max_words = 3 if vertical else 6
    fontname = "Inter" if "nter" in Path(font_path("bold")).name else "DejaVu Sans"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{fontname},{size},{_ass_color(theme.highlight)},{_ass_color((255, 255, 255))},{_ass_color((10, 10, 18))},{_ass_color((0, 0, 0), 120)},1,0,0,0,100,100,0,0,1,{max(3, size // 14)},2,2,{int(width * 0.08)},{int(width * 0.08)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for sc in scenes:
        words = sc["narration"].split()
        if not words:
            continue
        speak = max(sc["duration"] - tail - lead_in, 0.3)
        total_w = sum(_weight(w) for w in words)
        t = sc["start"] + lead_in
        for group in chunk(words, max_words):
            gdur = speak * sum(_weight(w) for w in group) / total_w
            parts = []
            for w in group:
                k = max(int(round(100 * speak * _weight(w) / total_w)), 1)
                parts.append(f"{{\\kf{k}}}{w.replace('{', '(').replace('}', ')')}")
            text = " ".join(parts).upper() if vertical else " ".join(parts)
            lines.append(f"Dialogue: 0,{_ts(t)},{_ts(t + gdur)},Cap,,0,0,0,,{text}")
            t += gdur
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path
