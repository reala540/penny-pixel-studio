"""Original, on-brand scene cards rendered with Pillow + Matplotlib (no paid image APIs).

Every card leaves the lower part of the frame free for captions.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import config

FONT_CANDIDATES = {
    "black": ["/usr/share/fonts/opentype/inter/InterDisplay-Black.otf", "/usr/share/fonts/opentype/inter/Inter-Black.otf",
              "/usr/share/fonts/truetype/inter/Inter-Black.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "bold": ["/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf", "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
             "/usr/share/fonts/truetype/inter/Inter-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "medium": ["/usr/share/fonts/opentype/inter/Inter-Medium.otf", "/usr/share/fonts/truetype/inter/Inter-Medium.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "regular": ["/usr/share/fonts/opentype/inter/Inter-Regular.otf", "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


@lru_cache(maxsize=None)
def font_path(weight: str) -> str:
    for p in FONT_CANDIDATES[weight]:
        if Path(p).exists():
            return p
    raise FileNotFoundError(f"No font found for weight {weight}; install fonts-inter or fonts-dejavu")


@lru_cache(maxsize=256)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path(weight), size)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


@dataclass
class Theme:
    channel: str
    name: str
    primary: tuple
    secondary: tuple
    text: tuple
    highlight: tuple

    @classmethod
    def for_channel(cls, channel: str) -> "Theme":
        ch = config.brand()["channels"][channel]
        d = ch["design"]
        return cls(channel, ch["display_name"], hex_rgb(d["primary"]), hex_rgb(d["secondary"]), hex_rgb(d["text"]),
                   hex_rgb(d.get("highlight", d["secondary"])))


@dataclass
class Frame:
    width: int
    height: int

    @property
    def vertical(self) -> bool:
        return self.height > self.width

    @property
    def s(self) -> float:  # scale relative to 1080p short side
        return min(self.width, self.height) / 1080

    @property
    def content_box(self) -> tuple[int, int, int, int]:
        """Area for card content; the rest is reserved for brand chip and captions."""
        if self.vertical:
            return (int(80 * self.s), int(300 * self.s), self.width - int(80 * self.s), int(self.height * 0.62))
        return (int(120 * self.s), int(170 * self.s), self.width - int(120 * self.s), int(self.height * 0.70))


# ------------------------------------------------------------------------------- drawing helpers

@lru_cache(maxsize=16)
def background(theme_key: str, w: int, h: int, primary: tuple, secondary: tuple, channel: str) -> Image.Image:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w * 0.78, h * 0.18
    d = np.sqrt(((xx - cx) / w) ** 2 + ((yy - cy) / h) ** 2)
    glow = np.clip(1 - d * 1.6, 0, 1) ** 2
    base = np.array(primary, np.float32)
    glow_col = np.array(mix(primary, secondary, 0.35), np.float32)
    img = base * (1 - glow[..., None] * 0.55) + glow_col * (glow[..., None] * 0.55)
    dark = np.clip((yy / h) ** 1.5 * 0.35, 0, 0.35)
    img = img * (1 - dark[..., None])
    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(out, "RGBA")
    step = max(int(min(w, h) / 22), 24)
    if channel == "ai":  # dot grid: precise, techy
        for y in range(step // 2, h, step):
            for x in range(step // 2, w, step):
                draw.ellipse((x - 1.4, y - 1.4, x + 1.4, y + 1.4), fill=(255, 255, 255, 22))
    else:  # soft ledger lines: calm, paper-like
        for y in range(step, h, step):
            draw.line((0, y, w, y), fill=(255, 255, 255, 14), width=1)
    return out


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_text(draw, text: str, weight: str, max_w: int, max_h: int, start: int, min_size: int = 28,
             line_gap: float = 1.12, max_lines: int = 4) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    size = start
    while size >= min_size:
        f = font(weight, size)
        lines = wrap(draw, text, f, max_w)
        lh = int(size * line_gap)
        if len(lines) <= max_lines and lh * len(lines) <= max_h:
            return f, lines, lh
        size -= 4
    f = font(weight, min_size)
    lines = wrap(draw, text, f, max_w)[:max_lines]
    return f, lines, int(min_size * line_gap)


def draw_lines(draw, lines, f, x, y, lh, fill, align="left", box_w=0):
    for i, line in enumerate(lines):
        lx = x
        if align == "center":
            lx = x + (box_w - draw.textlength(line, font=f)) / 2
        draw.text((lx, y + i * lh), line, font=f, fill=fill)
    return y + lh * len(lines)


def brand_chip(img: Image.Image, theme: Theme, frame: Frame) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    s = frame.s
    x, y = int(56 * s), int(48 * s) if not frame.vertical else int(120 * s)
    label = theme.name.upper()
    f = font("bold", int(26 * s))
    tw = d.textlength(label, font=f)
    pad = int(16 * s)
    d.rounded_rectangle((x, y, x + tw + pad * 2 + int(22 * s), y + int(52 * s)), radius=int(26 * s),
                        fill=(255, 255, 255, 26), outline=(255, 255, 255, 50), width=1)
    d.ellipse((x + pad, y + int(19 * s), x + pad + int(14 * s), y + int(33 * s)), fill=theme.secondary)
    d.text((x + pad + int(24 * s), y + int(12 * s)), label, font=f, fill=theme.text)


# ------------------------------------------------------------------------------- cards

def render_card(visual: dict, theme: Theme, frame: Frame, kicker: str | None = None,
                photo: Path | None = None, source_note: str | None = None, over_video: bool = False) -> Image.Image:
    """One scene's picture. With `over_video` it's a see-through layer (words plus a soft shade) to lay over a clip."""
    w, h = frame.width, frame.height
    vtype = visual.get("type", "title_card")
    if over_video:
        img = _video_scrim(w, h, theme)
    else:
        img = background(theme.channel, w, h, theme.primary, theme.secondary, theme.channel).copy()
    if vtype == "stock" and photo and Path(photo).exists() and not over_video:
        img = _photo_background(img, Path(photo), theme)
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, y1 = frame.content_box
    bw, bh = x1 - x0, y1 - y0
    s = frame.s
    if kicker:
        kf = font("bold", int(30 * s))
        d.text((x0, y0), kicker.upper()[:60], font=kf, fill=theme.secondary)
        y0 += int(62 * s)
        bh = y1 - y0
    head = visual.get("headline") or ""

    if vtype in ("title_card", "stock", "quote"):
        weight = "black" if vtype != "quote" else "bold"
        text = head or kicker or ""
        if vtype == "quote":
            qf = font("black", int(220 * s))
            d.text((x0 - int(10 * s), y0 - int(80 * s)), "“", font=qf, fill=(*theme.secondary, 200))
            y0 += int(70 * s)
            bh -= int(70 * s)
        f, lines, lh = fit_text(d, text, weight, bw, bh, int((150 if not frame.vertical else 120) * s))
        total = lh * len(lines)
        ty = y0 + (bh - total) // 2 if vtype != "quote" else y0
        end = draw_lines(d, lines, f, x0, ty, lh, theme.text)
        d.rounded_rectangle((x0, end + int(24 * s), x0 + int(160 * s), end + int(36 * s)), radius=int(6 * s),
                            fill=theme.secondary)
    elif vtype == "stat":
        val = visual.get("stat_value") or head
        vf, vlines, vlh = fit_text(d, val, "black", bw, int(bh * 0.55), int(300 * s), max_lines=2)
        y = draw_lines(d, vlines, vf, x0, y0 + int(bh * 0.05), vlh, theme.highlight)
        label = visual.get("stat_label") or (head if val != head else "")
        if label:
            lf, llines, llh = fit_text(d, label, "bold", bw, int(bh * 0.35), int(64 * s), max_lines=3)
            draw_lines(d, llines, lf, x0, y + int(20 * s), llh, theme.text)
    elif vtype in ("list", "steps"):
        items = [i for i in (visual.get("items") or []) if i][:5]
        y = y0
        if head:
            hf, hl, hlh = fit_text(d, head, "black", bw, int(bh * 0.28), int(84 * s), max_lines=2)
            y = draw_lines(d, hl, hf, x0, y, hlh, theme.text) + int(28 * s)
        room = (y1 - y) / max(len(items), 1)
        isize = int(min(56 * s, room * 0.42))
        for n, item in enumerate(items, 1):
            cy = int(y + (n - 1) * room)
            r = int(isize * 0.62)
            d.ellipse((x0, cy, x0 + 2 * r, cy + 2 * r), fill=theme.secondary)
            num = str(n) if vtype == "steps" else "•"
            nf = font("black", int(r * 1.1))
            tw = d.textlength(num, font=nf)
            d.text((x0 + r - tw / 2, cy + r * 0.28), num, font=nf, fill=theme.primary)
            itf, il, ilh = fit_text(d, item, "bold", bw - 3 * r, int(room * 0.9), isize, min_size=24, max_lines=2)
            draw_lines(d, il, itf, x0 + int(2.8 * r), cy + int(r * 0.2), ilh, theme.text)
    elif vtype == "comparison":
        items = (visual.get("items") or [])[:6]
        rows = [tuple(p.strip() for p in (i.split("|") + [""])[:2]) for i in items]
        y = y0
        if head:
            hf, hl, hlh = fit_text(d, head, "black", bw, int(bh * 0.22), int(76 * s), max_lines=2)
            y = draw_lines(d, hl, hf, x0, y, hlh, theme.text) + int(24 * s)
        colw = (bw - int(40 * s)) // 2
        for ci in range(2):
            cx = x0 + ci * (colw + int(40 * s))
            d.rounded_rectangle((cx, y, cx + colw, y1), radius=int(28 * s),
                                fill=(255, 255, 255, 20 if ci == 0 else 34), outline=(*theme.secondary, 120), width=2)
        rh = (y1 - y - int(40 * s)) / max(len(rows), 1)
        for ri, row in enumerate(rows):
            for ci in range(2):
                cx = x0 + ci * (colw + int(40 * s)) + int(32 * s)
                f, ls, lh = fit_text(d, row[ci], "bold" if ri == 0 else "medium", colw - int(64 * s), int(rh * 0.9),
                                     int((54 if ri == 0 else 44) * s), min_size=22, max_lines=2)
                draw_lines(d, ls, f, cx, int(y + int(24 * s) + ri * rh), lh,
                           theme.secondary if ri == 0 else theme.text)
    elif vtype == "chart" and visual.get("chart"):
        chart = render_chart(visual["chart"], theme, (bw, bh))
        img.paste(chart, (x0, y0), chart)
    else:
        f, lines, lh = fit_text(d, head or " ", "black", bw, bh, int(120 * s))
        draw_lines(d, lines, f, x0, y0, lh, theme.text)

    if source_note:
        sf_ = font("medium", int(22 * s))
        note = f"Source: {source_note}"[:110]
        nx = w - int(56 * s) - d.textlength(note, font=sf_)
        ny = int(h * (0.705 if not frame.vertical else 0.635))
        d.text((nx, ny), note, font=sf_, fill=(*theme.text, 170))
    brand_chip(img, theme, frame)
    return img


def _photo_background(base: Image.Image, photo: Path, theme: Theme) -> Image.Image:
    w, h = base.size
    p = Image.open(photo).convert("RGB")
    scale = max(w / p.width, h / p.height)
    p = p.resize((int(p.width * scale) + 1, int(p.height * scale) + 1), Image.LANCZOS)
    left, top = (p.width - w) // 2, (p.height - h) // 2
    p = p.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(1.2))
    shade = Image.new("RGB", (w, h), theme.primary)
    grad = Image.linear_gradient("L").resize((w, h)).rotate(90, expand=False)
    mask = Image.eval(grad, lambda v: int(150 + v * 0.35))
    return Image.composite(shade, p, mask)


def _video_scrim(w: int, h: int, theme: Theme) -> Image.Image:
    """A see-through shade, lighter at the top so the clip's movement shows, darker where the words sit."""
    grad = Image.linear_gradient("L").resize((w, h))          # 0 at the top, 255 at the bottom
    alpha = Image.eval(grad, lambda v: int(70 + v * 0.62))
    layer = Image.new("RGBA", (w, h), (*theme.primary, 0))
    layer.putalpha(alpha)
    return layer


def fmt_num(v: float) -> str:
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def render_chart(spec: dict, theme: Theme, size: tuple[int, int]) -> Image.Image:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    w, h = size
    dpi = 100
    fp = font_manager.FontProperties(fname=font_path("bold"))
    fr = font_manager.FontProperties(fname=font_path("medium"))
    fig, ax = plt.subplots(figsize=(w / dpi, h / dpi), dpi=dpi)
    fig.patch.set_alpha(0)
    ax.set_facecolor((0, 0, 0, 0))
    txt = tuple(c / 255 for c in theme.text)
    acc = tuple(c / 255 for c in theme.secondary)
    labels, values = spec["labels"], spec["values"]
    scale = h / 600
    if spec.get("kind") == "line":
        ax.plot(labels, values, color=acc, linewidth=6 * scale, marker="o", markersize=12 * scale)
        ax.fill_between(range(len(values)), values, min(values) * 0.98, color=acc, alpha=0.15)
    else:
        bars = ax.bar(labels, values, color=[acc if i == len(values) - 1 else (*txt, 0.35) for i in range(len(values))],
                      width=0.62)
        for b, v in zip(bars, values):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{fmt_num(v)}{spec.get('unit', '')}",
                    ha="center", va="bottom", color=txt, fontproperties=fp, fontsize=28 * scale)
    ax.set_title(spec.get("title", ""), color=txt, fontproperties=fp, fontsize=40 * scale, loc="left", pad=24 * scale)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color((*txt, 0.4))
    ax.tick_params(colors=txt, labelsize=22 * scale, length=0)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontproperties(fr)
        lbl.set_fontsize(22 * scale)
    ax.yaxis.set_visible(spec.get("kind") == "line")
    ax.grid(axis="y", color=(*txt, 0.12), linewidth=1)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGBA").resize((w, h), Image.LANCZOS)


def card_hash(visual: dict, theme: Theme, frame: Frame, kicker, photo, source_note, over_video: bool = False) -> str:
    parts = [visual, theme.channel, frame.width, frame.height, kicker, str(photo or ""), source_note, "card-v3"]
    if over_video:  # unchanged hashes for every existing card, so their cached clips are reused
        parts.append("over-video")
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def card_file(visual: dict, theme: Theme, frame: Frame, out_dir: Path, kicker=None, photo=None,
              source_note=None, over_video: bool = False) -> tuple[Path, str]:
    h = card_hash(visual, theme, frame, kicker, photo, source_note, over_video)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"card_{h}.png"
    if not path.exists():
        render_card(visual, theme, frame, kicker, photo, source_note, over_video).save(path, optimize=False,
                                                                                       compress_level=1)
    return path, h
