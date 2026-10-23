"""Three deterministic, on-brand thumbnail templates (1280x720) + a phone-feed-size preview."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .visuals import Frame, Theme, background, fit_text, font, mix

W, H = 1280, 720
TEMPLATES = ("bold_left", "big_number", "split_contrast")


def _outline_text(d: ImageDraw.ImageDraw, xy, text, fnt, fill, stroke=(10, 10, 18), width=6):
    d.text(xy, text, font=fnt, fill=fill, stroke_width=width, stroke_fill=stroke)


def render_thumbnail(template: str, headline: str, theme: Theme, photo: Path | None = None,
                     number: str | None = None) -> Image.Image:
    img = background(theme.channel, W, H, theme.primary, theme.secondary, theme.channel).copy()
    d = ImageDraw.Draw(img, "RGBA")
    words = headline.strip().upper()
    if photo and Path(photo).exists():
        p = Image.open(photo).convert("RGB")
        scale = max((W * 0.5) / p.width, H / p.height)
        p = p.resize((int(p.width * scale) + 1, int(p.height * scale) + 1), Image.LANCZOS)
        p = p.crop((0, 0, int(W * 0.5), H))
        mask = Image.linear_gradient("L").rotate(-90, expand=True).resize((int(W * 0.5), H))
        img.paste(p, (int(W * 0.5), 0), mask)
    else:  # original graphic motif so the right side never looks empty
        cx, cy = int(W * 0.8), int(H * 0.52)
        for r, a in ((300, 30), (220, 45), (140, 70)):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*theme.secondary, a), width=10)
        glyph = "%" if theme.channel == "money" else "</>"
        gf = font("black", 170 if len(glyph) > 1 else 230)
        gw = d.textlength(glyph, font=gf)
        d.text((cx - gw / 2, cy - (120 if len(glyph) > 1 else 150)), glyph, font=gf, fill=(*theme.secondary, 150))

    if template == "bold_left":
        f, lines, lh = fit_text(d, words, "black", int(W * 0.62), int(H * 0.72), 150, min_size=60, line_gap=1.02,
                                max_lines=3)
        y = (H - lh * len(lines)) // 2
        for i, line in enumerate(lines):
            col = theme.highlight if i == len(lines) - 1 else theme.text
            _outline_text(d, (64, y + i * lh), line, f, col)
        d.rounded_rectangle((64, y - 34, 220, y - 18), radius=8, fill=theme.secondary)
    elif template == "big_number":
        num = number or next((w for w in words.split() if any(c.isdigit() for c in w)), None)
        rest = words.replace(num, "").strip() if num else words
        if num:
            nf, nl, nlh = fit_text(d, num, "black", int(W * 0.6), int(H * 0.55), 300, min_size=120, max_lines=1)
            _outline_text(d, (60, 70), nl[0], nf, theme.highlight, width=8)
            y = 70 + nlh + 10
        else:
            y = 90
        f, lines, lh = fit_text(d, rest or words, "black", int(W * 0.6), H - y - 60, 96, min_size=48, max_lines=3)
        for i, line in enumerate(lines):
            _outline_text(d, (64, y + i * lh), line, f, theme.text)
    else:  # split_contrast
        d.rectangle((0, 0, int(W * 0.56), H), fill=(*mix(theme.primary, (0, 0, 0), 0.35), 235))
        d.polygon([(int(W * 0.56), 0), (int(W * 0.62), 0), (int(W * 0.56), H)], fill=(*theme.secondary, 255))
        f, lines, lh = fit_text(d, words, "black", int(W * 0.5), int(H * 0.8), 130, min_size=56, line_gap=1.0,
                                max_lines=4)
        y = (H - lh * len(lines)) // 2
        for i, line in enumerate(lines):
            _outline_text(d, (56, y + i * lh), line, f, theme.text if i % 2 == 0 else theme.highlight)
    chip_f = font("bold", 26)
    label = theme.name.split()[-1].upper()
    tw = d.textlength(label, font=chip_f)
    d.rounded_rectangle((W - tw - 90, 30, W - 30, 78), radius=24, fill=(*theme.secondary, 255))
    d.text((W - tw - 60, 38), label, font=chip_f, fill=theme.primary)
    return img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))


def make_set(headlines: list[str], theme: Theme, out_dir: Path, photo: Path | None = None) -> list[dict]:
    """Up to three candidates, each with a phone-feed-size preview for the review screen."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i, template in enumerate(TEMPLATES):
        headline = (headlines[i] if i < len(headlines) else headlines[0]).strip()
        img = render_thumbnail(template, headline, theme, photo)
        path = out_dir / f"thumb_{i + 1}_{template}.jpg"
        img.convert("RGB").save(path, quality=90)
        mobile = out_dir / f"thumb_{i + 1}_{template}_mobile.jpg"
        img.resize((336, 189), Image.LANCZOS).convert("RGB").save(mobile, quality=85)
        out.append({"label": f"Option {i + 1}", "template": template, "headline": headline, "path": path,
                    "mobile": mobile})
    return out
