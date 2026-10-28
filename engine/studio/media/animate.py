"""A few original animated scenes, drawn frame by frame with Pillow in the channel's own colours and joined by FFmpeg.

Movement is there to explain the narration: coins going into budget jars, a basket whose prices rise, AI agents
handing a task along, a number counting up to its real value. Every number shown comes from the scene itself (the
writer takes it from the checked facts), and the bottom of the frame stays clear for captions.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .visuals import Frame, Theme, background, draw_lines, fit_text, font

TEMPLATES = ("budget_jars", "price_basket", "agent_handoff", "counter")

# a template's static stand-in, used when there are too many animated scenes or an animation can't be drawn
STATIC_TYPE = {"budget_jars": "list", "price_basket": "comparison", "agent_handoff": "steps", "counter": "stat"}


def ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


NUM_RE = re.compile(r"^\s*([^\d\-.]*)(-?[\d,]*\.?\d+)\s*(.*)$")


def parse_number(text: str) -> tuple[str, float, str, int] | None:
    """'$1,200' -> ('$', 1200.0, '', 0); '53%' -> ('', 53.0, '%', 0); '2.5x' -> ('', 2.5, 'x', 1)."""
    m = NUM_RE.match(str(text or ""))
    if not m:
        return None
    raw = m.group(2).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    return m.group(1).strip(), value, m.group(3).strip(), decimals


def fmt_value(prefix: str, value: float, suffix: str, decimals: int) -> str:
    body = f"{value:,.{decimals}f}"
    sep = "" if suffix in ("%", "x", "k", "m", "") or len(suffix) <= 1 else " "
    return f"{prefix}{body}{sep}{suffix}"


def _rows(items: list[str], parts: int) -> list[list[str]]:
    out = []
    for it in items:
        cells = [c.strip() for c in str(it).split("|")]
        if len(cells) >= parts and all(cells[:parts]):
            out.append(cells[:parts])
    return out


def usable(visual: dict) -> bool:
    """Whether this animated scene has what its template needs; otherwise it's shown as a still scene."""
    a = visual.get("animation")
    items = visual.get("items") or []
    if a == "budget_jars":
        return 2 <= len([r for r in _rows(items, 2) if parse_number(r[1])]) <= 4
    if a == "price_basket":
        return 1 <= len([r for r in _rows(items, 3) if parse_number(r[1]) and parse_number(r[2])]) <= 4
    if a == "agent_handoff":
        return 2 <= len([i for i in items if str(i).strip()]) <= 5
    if a == "counter":
        return parse_number(visual.get("stat_value") or "") is not None
    return False


def as_static(visual: dict) -> dict:
    """The still version of an animated scene (same words and numbers)."""
    a = visual.get("animation")
    v = {k: val for k, val in visual.items() if k != "animation"}
    v["type"] = STATIC_TYPE.get(a, "title_card")
    items = visual.get("items") or []
    if a == "budget_jars":
        v["items"] = [f"{r[0]}: {r[1]}" for r in _rows(items, 2)]
    elif a == "price_basket":
        v["items"] = [f"{r[0]}|{r[1]} → {r[2]}" for r in _rows(items, 3)]
    return v


# ------------------------------------------------------------------------------------------ drawing

def _headline(d: ImageDraw.ImageDraw, text: str, theme: Theme, box: tuple[int, int, int, int], s: float) -> int:
    x0, y0, x1, y1 = box
    if not text:
        return y0
    f, lines, lh = fit_text(d, text, "black", x1 - x0, int((y1 - y0) * 0.22), int(78 * s), max_lines=2)
    return draw_lines(d, lines, f, x0, y0, lh, theme.text) + int(28 * s)


def _coin(d, cx, cy, r, theme):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=theme.highlight, outline=(*theme.primary, 255), width=max(int(r * 0.12), 1))
    f = font("black", max(int(r * 1.2), 8))
    tw = d.textlength("$", font=f)
    d.text((cx - tw / 2, cy - r * 0.72), "$", font=f, fill=theme.primary)


def _budget_jars(d, img, visual, theme, frame, p):
    s = frame.s
    x0, y0, x1, y1 = frame.content_box
    top = _headline(d, visual.get("headline") or "", theme, frame.content_box, s)
    rows = [r for r in _rows(visual.get("items") or [], 2) if parse_number(r[1])][:4]
    nums = [parse_number(r[1]) for r in rows]
    biggest = max(n[1] for n in nums) or 1
    n = len(rows)
    gap = int(40 * s)
    jw = (x1 - x0 - gap * (n - 1)) / n
    label_h = int(110 * s)
    jar_top, jar_bot = top + int(90 * s), y1 - label_h
    src = ((x0 + x1) / 2, top + int(30 * s))
    for i, (row, num) in enumerate(zip(rows, nums)):
        jx = x0 + i * (jw + gap)
        local = ease((p - i * 0.12) / 0.6)                     # jars fill one after another
        level = (num[1] / biggest) * local
        d.rounded_rectangle((jx, jar_top, jx + jw, jar_bot), radius=int(30 * s), outline=(*theme.text, 200), width=max(int(4 * s), 2))
        fill_top = jar_bot - (jar_bot - jar_top - int(12 * s)) * level
        if level > 0.01:
            d.rounded_rectangle((jx + int(8 * s), fill_top, jx + jw - int(8 * s), jar_bot - int(8 * s)), radius=int(22 * s),
                                fill=(*theme.secondary, 230))
        # a few coins on their way into this jar
        for k in range(3):
            t = (p - i * 0.12 - k * 0.07) / 0.5
            if 0 < t < 1:
                e = ease(t)
                cx = src[0] + (jx + jw / 2 - src[0]) * e
                cy = src[1] + (fill_top - src[1]) * e - math.sin(e * math.pi) * 60 * s
                _coin(d, cx, cy, int(22 * s), theme)
        lf, ll, llh = fit_text(d, row[0], "bold", int(jw), int(label_h * 0.5), int(40 * s), min_size=18, max_lines=2)
        draw_lines(d, ll, lf, jx, jar_bot + int(14 * s), llh, theme.text, align="center", box_w=int(jw))
        if local > 0.85:
            vf = font("black", int(46 * s))
            txt = fmt_value(*num)
            tw = d.textlength(txt, font=vf)
            above = fill_top - int(64 * s)
            if above > jar_top + int(6 * s):   # room above the coins: write it there
                d.text((jx + (jw - tw) / 2, above), txt, font=vf, fill=theme.highlight)
            else:                               # a full jar: write it inside, in the background colour
                d.text((jx + (jw - tw) / 2, fill_top + int(16 * s)), txt, font=vf, fill=theme.primary)


def _price_basket(d, img, visual, theme, frame, p):
    s = frame.s
    x0, y0, x1, y1 = frame.content_box
    top = _headline(d, visual.get("headline") or "", theme, frame.content_box, s)
    rows = [r for r in _rows(visual.get("items") or [], 3) if parse_number(r[1]) and parse_number(r[2])][:4]
    vertical = frame.vertical
    bx0 = x0
    bw = (x1 - x0) * (0.38 if not vertical else 0.6)
    by0 = top + bw * 0.3 + int(20 * s)   # leave room for the handle under the headline
    by1 = by0 + bw * 0.62
    if vertical:
        bx0 = x0 + ((x1 - x0) - bw) / 2
    # the basket: a handle, a body that tips slightly as it fills
    tilt = math.sin(min(p, 1) * math.pi) * 6 * s
    d.arc((bx0 + bw * 0.2, by0 - bw * 0.25, bx0 + bw * 0.8, by0 + bw * 0.3), 180, 360, fill=theme.text, width=max(int(8 * s), 2))
    d.polygon([(bx0, by0 + tilt), (bx0 + bw, by0 - tilt), (bx0 + bw * 0.86, by1), (bx0 + bw * 0.14, by1)], fill=(*theme.secondary, 235))
    for k in range(1, 4):
        yy = by0 + (by1 - by0) * k / 4
        d.line((bx0 + bw * 0.06, yy, bx0 + bw * 0.94, yy), fill=(*theme.primary, 120), width=max(int(3 * s), 1))
    # the prices
    lx0 = bx0 + bw + int(60 * s) if not vertical else x0
    ly = top + int(20 * s) if not vertical else by1 + int(40 * s)
    total_b = total_a = 0.0
    prefix, decimals = "", 2
    rh = min(int(90 * s), int((y1 - ly) / (len(rows) + 1.6)))
    for i, r in enumerate(rows):
        b, a = parse_number(r[1]), parse_number(r[2])
        prefix, decimals = b[0] or a[0], max(b[3], a[3])
        e = ease((p - 0.15 - i * 0.1) / 0.5)
        now = b[1] + (a[1] - b[1]) * e
        total_b += b[1]
        total_a += a[1]
        f = font("bold", int(42 * s))
        d.text((lx0, ly + i * rh), r[0][:22], font=f, fill=theme.text)
        val = fmt_value(prefix, now, b[2], decimals)
        vf = font("black", int(46 * s))
        col = theme.highlight if a[1] > b[1] and e > 0.05 else theme.text
        d.text((x1 - d.textlength(val, font=vf), ly + i * rh), val, font=vf, fill=col)
    e = ease((p - 0.2) / 0.65)
    total = total_b + (total_a - total_b) * e
    ty = ly + len(rows) * rh + int(16 * s)
    d.line((lx0, ty, x1, ty), fill=(*theme.text, 150), width=max(int(3 * s), 1))
    tf = font("black", int(60 * s))
    label = "Total"
    d.text((lx0, ty + int(14 * s)), label, font=tf, fill=theme.text)
    tv = fmt_value(prefix, total, "", decimals)
    d.text((x1 - d.textlength(tv, font=tf), ty + int(14 * s)), tv, font=tf, fill=theme.highlight)


def _robot(d, cx, cy, r, theme, active: bool):
    body = (*theme.secondary, 255) if active else (*theme.text, 70)
    d.rounded_rectangle((cx - r, cy - r * 0.8, cx + r, cy + r * 0.8), radius=int(r * 0.35), fill=body)
    eye = theme.primary
    for ex in (-0.38, 0.38):
        d.ellipse((cx + ex * r - r * 0.13, cy - r * 0.2, cx + ex * r + r * 0.13, cy + r * 0.06), fill=eye)
    d.line((cx, cy - r * 0.8, cx, cy - r * 1.1), fill=body, width=max(int(r * 0.08), 1))
    d.ellipse((cx - r * 0.1, cy - r * 1.22, cx + r * 0.1, cy - r * 1.02), fill=body)


def _agent_handoff(d, img, visual, theme, frame, p):
    s = frame.s
    x0, y0, x1, y1 = frame.content_box
    top = _headline(d, visual.get("headline") or "", theme, frame.content_box, s)
    steps = [str(i).strip() for i in (visual.get("items") or []) if str(i).strip()][:5]
    n = len(steps)
    vertical = frame.vertical
    r = int((70 if not vertical else 60) * s)
    if vertical:
        pts = [((x0 + x1) / 2 - r * 2.2, top + r * 1.4 + i * (y1 - top - r * 2.4) / max(n - 1, 1)) for i in range(n)]
    else:
        pts = [(x0 + r + i * (x1 - x0 - 2 * r) / max(n - 1, 1), (top + y1) / 2 - r * 0.4) for i in range(n)]
    for i in range(n - 1):
        d.line((*pts[i], *pts[i + 1]), fill=(*theme.text, 90), width=max(int(5 * s), 2))
    travel = min(p / 0.8, 1) * (n - 1)
    at = int(min(travel, n - 1))
    for i, (cx, cy) in enumerate(pts):
        _robot(d, cx, cy, r, theme, active=i <= at)
        f = font("bold", int(34 * s))
        label = steps[i][:28]
        if vertical:
            d.text((cx + r * 1.6, cy - r * 0.35), label, font=f, fill=theme.text)
        else:
            tw = d.textlength(label, font=f)
            d.text((cx - tw / 2, cy + r * 1.15), label, font=f, fill=theme.text)
    # the task card moving between agents
    seg = min(int(travel), n - 2) if n > 1 else 0
    t = ease(travel - seg) if n > 1 else 1
    ax, ay = pts[seg]
    bx, by = pts[min(seg + 1, n - 1)]
    cx, cy = ax + (bx - ax) * t, ay + (by - ay) * t - r * 1.55 - math.sin(t * math.pi) * r * 0.5
    cw, ch = r * 1.2, r * 0.8
    d.rounded_rectangle((cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2), radius=int(r * 0.15), fill=theme.highlight)
    for k in range(3):
        ly = cy - ch * 0.25 + k * ch * 0.22
        d.line((cx - cw * 0.32, ly, cx + cw * (0.32 if k < 2 else 0.1), ly), fill=theme.primary, width=max(int(r * 0.06), 1))
    if p > 0.85:  # done: a tick beside the last agent
        lx, ly = pts[-1]
        tx, ty = (lx + r * 1.25, ly - r * 0.2) if not vertical else (lx - r * 1.9, ly - r * 0.2)
        d.line((tx, ty, tx + r * 0.3, ty + r * 0.3, tx + r * 0.85, ty - r * 0.35),
               fill=theme.highlight, width=max(int(r * 0.16), 2), joint="curve")


def _counter(d, img, visual, theme, frame, p):
    s = frame.s
    x0, y0, x1, y1 = frame.content_box
    prefix, value, suffix, decimals = parse_number(visual.get("stat_value") or "0")
    e = ease(p / 0.75)
    shown = fmt_value(prefix, value * e, suffix, decimals)
    top = _headline(d, visual.get("headline") or "", theme, frame.content_box, s)
    vf, vl, vlh = fit_text(d, fmt_value(prefix, value, suffix, decimals), "black", x1 - x0, int((y1 - top) * 0.45),
                           int(260 * s), max_lines=1)
    d.text((x0, top), shown, font=vf, fill=theme.highlight)
    y = top + vlh + int(20 * s)
    if suffix == "%" and 0 <= value <= 100:
        bh = int(36 * s)
        d.rounded_rectangle((x0, y, x1, y + bh), radius=bh // 2, fill=(*theme.text, 50))
        d.rounded_rectangle((x0, y, x0 + max((x1 - x0) * value / 100 * e, bh), y + bh), radius=bh // 2, fill=theme.secondary)
        y += bh + int(28 * s)
    label = visual.get("stat_label") or ""
    if label:
        lf, ll, llh = fit_text(d, label, "bold", x1 - x0, int((y1 - y) * 0.9), int(60 * s), max_lines=3)
        draw_lines(d, ll, lf, x0, y, llh, theme.text)


DRAW = {"budget_jars": _budget_jars, "price_basket": _price_basket, "agent_handoff": _agent_handoff, "counter": _counter}


def frame_image(visual: dict, theme: Theme, frame: Frame, progress: float) -> Image.Image:
    from .visuals import brand_chip

    img = background(theme.channel, frame.width, frame.height, theme.primary, theme.secondary, theme.channel).copy()
    d = ImageDraw.Draw(img, "RGBA")
    DRAW[visual["animation"]](d, img, visual, theme, frame, progress)
    brand_chip(img, theme, frame)
    return img


def animation_hash(visual: dict, theme: Theme, frame: Frame, seconds: float, fps: int) -> str:
    payload = json.dumps([visual, theme.channel, frame.width, frame.height, round(seconds, 2), fps, "anim-v1"],
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def render_animation(visual: dict, theme: Theme, frame: Frame, seconds: float, fps: int, out: Path) -> Path:
    """Silent video of the animation, `seconds` long. Frames are streamed straight into FFmpeg (no image files)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    total = max(int(math.ceil(seconds * fps)), 1)
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{frame.width}x{frame.height}", "-r", str(fps), "-i", "-",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)],
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(total):
            proc.stdin.write(frame_image(visual, theme, frame, i / max(total - 1, 1)).convert("RGB").tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode()[-400:]
        if proc.wait(timeout=600) != 0:
            raise RuntimeError(f"ffmpeg failed drawing an animation: {err}")
    except BaseException:
        proc.kill()
        out.unlink(missing_ok=True)
        raise
    return out
