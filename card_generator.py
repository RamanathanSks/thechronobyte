"""Generate editorial 1080x1350 (4:5) JPEG news cards across rotating print themes."""

import hashlib
import logging
import math
from pathlib import Path
import random
import re
import time
import unicodedata

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

LOGGER = logging.getLogger(__name__)

CARD_WIDTH = 1080
CARD_HEIGHT = 1350

PAPER_CREAM = (245, 242, 234)
PAPER_BUFF = (238, 232, 218)
NOIR_INK = (19, 21, 25)
INK_PRIMARY = (20, 22, 24)
INK_SECONDARY = (48, 51, 55)
INK_MUTED = (118, 114, 106)
LIGHT_PRIMARY = (244, 241, 232)
LIGHT_SECONDARY = (206, 202, 194)
LIGHT_MUTED = (142, 140, 134)

CARD_THEMES = ("framed_gallery", "dark_duotone", "riso_poster", "editorial_horizon")

# Per-source curated print palettes: (accent, secondary_wash, deep_ink, warm_highlight).
SOURCE_PALETTES = {
    "OpenAI": (
        ((16, 163, 127), (78, 146, 134), (19, 54, 52), (219, 164, 88)),
        ((16, 163, 127), (96, 138, 162), (24, 42, 68), (224, 152, 92)),
    ),
    "NVIDIA": (
        ((118, 185, 0), (88, 138, 62), (24, 48, 22), (218, 198, 92)),
        ((118, 185, 0), (66, 128, 118), (18, 42, 46), (198, 178, 84)),
    ),
    "Google AI": (
        ((58, 122, 232), (96, 142, 206), (22, 42, 82), (226, 154, 78)),
        ((58, 122, 232), (82, 156, 152), (24, 54, 68), (224, 168, 96)),
    ),
    "AMD": (
        ((220, 44, 48), (188, 92, 62), (62, 22, 26), (232, 168, 86)),
        ((220, 44, 48), (132, 74, 86), (42, 24, 34), (218, 144, 82)),
    ),
    "Microsoft Research": (
        ((0, 146, 218), (74, 132, 188), (20, 44, 78), (224, 174, 98)),
        ((0, 146, 218), (92, 148, 146), (22, 52, 64), (216, 154, 88)),
    ),
}
DEFAULT_PALETTES = (
    ((82, 98, 216), (110, 134, 192), (26, 36, 72), (224, 168, 92)),
)

FONT_CANDIDATES = {
    "serif": (
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/pala.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
    ),
    "serif_bold": (
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/palab.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
    ),
    "semibold": (
        "C:/Windows/Fonts/seguisb.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    "regular": (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    ),
}


def _resolve_font_path(weight: str) -> Path | None:
    for candidate in FONT_CANDIDATES.get(weight, ()):
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def _load_font(weight: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = _resolve_font_path(weight)
    if font_path is not None:
        return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default(size=size)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    bbox = draw.textbbox((0, 0), text, font=font)
    return float(bbox[2] - bbox[0])


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Wrap text by pixel width and truncate cleanly at max_lines."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    truncated = False

    for word in words:
        trial = f"{current} {word}".strip()
        if _text_width(draw, trial, font) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
            if len(lines) == max_lines:
                truncated = True
                current = ""
                break
        if _text_width(draw, word, font) > max_width:
            clipped = word
            while len(clipped) > 1 and _text_width(draw, clipped + "…", font) > max_width:
                clipped = clipped[:-1]
            current = clipped + "…"
        else:
            current = word

    if current and len(lines) < max_lines:
        lines.append(current)
    elif current:
        truncated = True

    if truncated and lines:
        last = lines[-1].rstrip(" ,;:-…")
        while last and _text_width(draw, last + "…", font) > max_width:
            last = last[:-1].rstrip(" ,;:-")
        lines[-1] = (last or lines[-1][:1]) + "…"
    return lines


def _strip_invisible(text: str) -> str:
    """Remove format/control chars (e.g. U+2060 word joiner) that render as boxes."""
    return " ".join(
        "".join(ch for ch in text if unicodedata.category(ch) not in {"Cs", "Cf"}).split()
    )


def _topic_seed(topic: dict) -> int:
    key = f"{topic.get('published', '')}|{topic.get('source_url', '')}|{topic.get('text', '')}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16)


def _build_body_blocks(topic: dict, max_blocks: int = 3) -> list[str]:
    """Collect distinct, substantive paragraphs + RSS lead without repeating headline."""
    title_low = _strip_invisible(topic["text"]).lower()
    summary = re.sub(r"\s*(?:\[\u2026\]|\[\.\.\.\]|…)$", "", (topic.get("summary") or "").strip())
    raw_items = list(topic.get("paragraphs") or [])
    if summary:
        raw_items.append(summary)

    selected: list[str] = []
    for item in raw_items:
        cleaned = re.sub(r"\s*(?:\[\u2026\]|\[\.\.\.\]|…)$", "", _strip_invisible(item)).strip()
        if not cleaned or len(cleaned) < 25:
            continue
        low = cleaned.lower()
        if low == title_low:
            continue
        if low.startswith(title_low) and len(cleaned) > len(title_low) + 20:
            cleaned = cleaned[len(title_low):].lstrip(" ,:—-")
            if cleaned:
                cleaned = cleaned[0].upper() + cleaned[1:]
                low = cleaned.lower()
        joined = " ".join(selected).lower()
        if low in joined or low[:55] in joined:
            continue
        if any(existing.lower() in low or existing.lower()[:55] == low[:55] for existing in selected):
            for idx, existing in enumerate(selected):
                if existing.lower() in low or existing.lower()[:55] == low[:55]:
                    if len(cleaned) > len(existing):
                        selected[idx] = cleaned
                    break
            continue
        selected.append(cleaned)
        if len(selected) == max_blocks:
            break
    return selected


def _apply_analog_grain(image: Image.Image, strength: float = 0.40) -> Image.Image:
    """Overlay crisp multi-scale analog print/film grain over an RGB/RGBA image."""
    w, h = image.size
    base_rgb = image.convert("RGB")
    fine = Image.effect_noise((w, h), 24).convert("RGB")
    med = Image.effect_noise((max(1, w // 2), max(1, h // 2)), 26).resize(
        (w, h), resample=Image.Resampling.BILINEAR
    ).convert("RGB")
    grain = Image.blend(fine, med, alpha=0.35)
    soft = ImageChops.soft_light(base_rgb, grain)
    return Image.blend(base_rgb, soft, alpha=strength).convert("RGBA")


def _draw_masthead(
    draw: ImageDraw.ImageDraw,
    topic: dict,
    handle: str,
    accent: tuple[int, int, int],
    primary_fill: tuple[int, int, int, int],
    muted_fill: tuple[int, int, int, int],
    rule_fill: tuple[int, int, int, int] | None = None,
) -> None:
    """Draw the Chrono Byte editorial masthead bar across the top."""
    font_bold = _load_font("semibold", 18)
    font_reg = _load_font("regular", 18)
    margin_x = 76
    top_y = 52

    draw.rounded_rectangle((margin_x, top_y + 4, margin_x + 12, top_y + 16), radius=3, fill=(*accent, 255))
    brand = "CHRONO BYTE"
    draw.text((margin_x + 22, top_y), brand, font=font_bold, fill=primary_fill)
    brand_w = _text_width(draw, brand, font_bold)
    draw.text((margin_x + 28 + brand_w, top_y), f" ·  {handle}", font=font_reg, fill=muted_fill)

    source = _strip_invisible(topic.get("source", "Tech News")).upper()
    date_label = topic["published"].strftime("%b %d, %Y").upper().replace(" 0", " ")
    meta = f"{source}  ·  {date_label}"
    meta_w = _text_width(draw, meta, font_reg)
    draw.text((CARD_WIDTH - margin_x - meta_w, top_y), meta, font=font_reg, fill=muted_fill)
    if rule_fill is not None:
        draw.line((margin_x, 98, CARD_WIDTH - margin_x, 98), fill=rule_fill, width=1)


def _draw_text_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    x: int,
    start_y: int,
    line_step: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    centered: bool = False,
) -> int:
    """Draw left-aligned or centered lines and return the ending y-coordinate."""
    y = start_y
    for line in lines:
        draw_x = (CARD_WIDTH - _text_width(draw, line, font)) / 2 if centered else float(x)
        draw.text((draw_x, y), line, font=font, fill=fill)
        y += line_step
    return y


def _draw_paragraph_blocks(
    draw: ImageDraw.ImageDraw,
    blocks: list[str],
    x: int,
    start_y: int,
    max_y: int,
    width: int,
    font: ImageFont.ImageFont,
    line_step: int,
    fill: tuple[int, int, int, int],
    para_gap: int = 20,
    centered: bool = False,
) -> int:
    """Draw multiple rich paragraphs cleanly until vertical space fills without overflow."""
    y = start_y
    for block in blocks:
        remaining = max(0, (max_y - y) // line_step)
        if remaining < 2:
            break
        lines = _wrap_text(draw, block, font, width, max_lines=remaining)
        y = _draw_text_lines(draw, lines, x, y, line_step, font, fill, centered=centered)
        y += para_gap
    return y


def _fit_headline_lines(
    draw: ImageDraw.ImageDraw,
    headline: str,
    width: int,
    base_size: int,
    small_size: int,
    font_weight: str = "serif",
) -> tuple[list[str], ImageFont.ImageFont]:
    font = _load_font(font_weight, base_size)
    lines = _wrap_text(draw, headline, font, width, max_lines=4)
    if len(lines) >= 4:
        font = _load_font(font_weight, small_size)
        lines = _wrap_text(draw, headline, font, width, max_lines=4)
    return lines, font


def _render_framed_gallery(
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
) -> Image.Image:
    """Architectural magazine cover: dense readable brief above a framed lower art plate."""
    accent, wash, deep, highlight = palette
    rng = random.Random(seed)

    canvas = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*PAPER_CREAM, 255))
    draw = ImageDraw.Draw(canvas)
    _draw_masthead(
        draw, topic, handle, accent, (*INK_SECONDARY, 235), (*INK_MUTED, 235), rule_fill=(20, 22, 24, 28)
    )

    margin_x = 76
    content_w = CARD_WIDTH - margin_x * 2
    headline = _strip_invisible(topic["text"])
    h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 60, 52, font_weight="serif_bold")
    h_step = int(h_font.size * 1.14)
    h_end = _draw_text_lines(draw, h_lines, margin_x, 132, h_step, h_font, (*INK_PRIMARY, 255))

    rule_y = h_end + 18
    draw.rectangle((margin_x, rule_y, margin_x + 76, rule_y + 4), fill=(*accent, 255))

    blocks = _build_body_blocks(topic, max_blocks=3)
    body_font = _load_font("regular", 28)
    body_end = _draw_paragraph_blocks(
        draw,
        blocks,
        margin_x,
        rule_y + 24,
        max_y=845,
        width=content_w,
        font=body_font,
        line_step=39,
        fill=(*INK_SECONDARY, 242),
        para_gap=18,
    )

    # Flush lower artwork window cleanly under the copy with zero empty dead gap.
    plate_top = max(560, min(865, body_end + 18))
    plate_bottom = CARD_HEIGHT - 64
    plate_w = content_w
    plate_h = plate_bottom - plate_top

    plate = Image.new("RGBA", (plate_w, plate_h), (*deep, 255))
    art = Image.new("RGBA", (plate_w, plate_h), (0, 0, 0, 0))
    ad = ImageDraw.Draw(art)

    shift = rng.uniform(0.0, math.tau)
    wave_pts = [
        (
            x,
            int(
                plate_h * 0.42
                + 48 * math.sin((x / plate_w) * math.pi * 1.6 + shift)
                + 20 * math.cos((x / plate_w) * math.pi * 3.1 - shift)
            ),
        )
        for x in range(0, plate_w + 20, 20)
    ]
    ad.polygon(wave_pts + [(plate_w, plate_h), (0, plate_h)], fill=(*wash, 232))
    ad.ellipse(
        (rng.randint(80, 420), int(plate_h * 0.15), rng.randint(680, 960), plate_h + 160),
        fill=(*highlight, 175),
    )
    ad.ellipse((-120, -140, int(plate_w * 0.55), int(plate_h * 0.65)), fill=(*accent, 115))
    art = art.filter(ImageFilter.GaussianBlur(radius=54))
    plate = Image.alpha_composite(plate, art)

    line_layer = Image.new("RGBA", (plate_w, plate_h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line_layer)
    cx = int(plate_w * rng.uniform(0.62, 0.84))
    cy = int(plate_h * rng.uniform(0.32, 0.62))
    for radius in (120, 195, 270, 345):
        ld.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(255, 255, 255, 42), width=2)
    plate = Image.alpha_composite(plate, line_layer)
    plate = _apply_analog_grain(plate, strength=0.38)

    mask = Image.new("L", (plate_w, plate_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, plate_w, plate_h), radius=16, fill=255)
    canvas.paste(plate, (margin_x, plate_top), mask)
    return _apply_analog_grain(canvas, strength=0.16)


def _render_dark_duotone(
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
) -> Image.Image:
    """Midnight print poster: full-height editorial story + luminous duotone glow."""
    accent, wash, _, highlight = palette
    rng = random.Random(seed)

    canvas = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*NOIR_INK, 255))
    glow = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)

    anchor_x = rng.randint(360, 840)
    gd.ellipse((anchor_x - 520, 620, anchor_x + 540, 1480), fill=(*wash, 175))
    gd.ellipse((rng.randint(-180, 240), 840, rng.randint(520, 880), 1560), fill=(*accent, 135))
    gd.ellipse((rng.randint(240, 680), 940, 1180, 1520), fill=(*highlight, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=130))
    canvas = Image.alpha_composite(canvas, glow)

    chrome = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chrome)
    cd.rounded_rectangle((36, 32, CARD_WIDTH - 36, CARD_HEIGHT - 32), radius=12, outline=(255, 255, 255, 28), width=2)
    _draw_masthead(
        cd, topic, handle, accent, (*LIGHT_PRIMARY, 235), (*LIGHT_MUTED, 235), rule_fill=(255, 255, 255, 28)
    )
    canvas = Image.alpha_composite(canvas, chrome)
    draw = ImageDraw.Draw(canvas)

    margin_x = 84
    content_w = CARD_WIDTH - margin_x * 2
    topic_tag = (_strip_invisible(topic.get("topic_tag") or "") or "AI BRIEF").upper()
    tag_font = _load_font("semibold", 19)
    draw.text((margin_x, 146), topic_tag, font=tag_font, fill=(*accent, 255))

    headline = _strip_invisible(topic["text"])
    h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 64, 54, font_weight="serif")
    h_step = int(h_font.size * 1.14)
    h_end = _draw_text_lines(draw, h_lines, margin_x, 188, h_step, h_font, (*LIGHT_PRIMARY, 255))

    draw.rectangle((margin_x, h_end + 18, margin_x + 84, h_end + 22), fill=(*accent, 230))

    blocks = _build_body_blocks(topic, max_blocks=3)
    body_font = _load_font("regular", 31)
    _draw_paragraph_blocks(
        draw,
        blocks,
        margin_x,
        h_end + 48,
        max_y=1170,
        width=content_w - 16,
        font=body_font,
        line_step=44,
        fill=(*LIGHT_SECONDARY, 245),
        para_gap=24,
    )

    # Subtle colophon strip anchoring the bottom border cleanly.
    draw.line((margin_x, 1226, CARD_WIDTH - margin_x, 1226), fill=(255, 255, 255, 36), width=1)
    col_font = _load_font("regular", 17)
    draw.text((margin_x, 1246), f"DAILY BRIEF  ·  {handle}", font=col_font, fill=(*LIGHT_MUTED, 220))
    source_label = _strip_invisible(topic.get("source", "")).upper()
    sw = _text_width(draw, source_label, col_font)
    draw.text((CARD_WIDTH - margin_x - sw, 1246), source_label, font=col_font, fill=(*LIGHT_MUTED, 220))

    return _apply_analog_grain(canvas, strength=0.34)


def _multiply_ink_shape(canvas_rgb: Image.Image, draw_fn, blur_radius: float = 1.5) -> Image.Image:
    """Stamp one translucent risograph ink pass using physical multiply blending."""
    ink = Image.new("RGB", canvas_rgb.size, (255, 255, 255))
    draw_fn(ImageDraw.Draw(ink))
    if blur_radius > 0:
        ink = ink.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    return ImageChops.multiply(canvas_rgb, ink)


def _render_riso_poster(
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
) -> Image.Image:
    """Mid-century Swiss / Riso print: full story column above multiplied ink shapes."""
    accent, wash, deep, highlight = palette
    rng = random.Random(seed)
    soft_accent = tuple(int(c * 0.72 + PAPER_BUFF[i] * 0.28) for i, c in enumerate(accent))

    paper_rgb = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), PAPER_BUFF)
    variant = seed % 2
    if variant == 0:
        paper_rgb = _multiply_ink_shape(
            paper_rgb, lambda d: d.pieslice((-60, 810, 780, 1650), start=180, end=360, fill=highlight)
        )
        paper_rgb = _multiply_ink_shape(
            paper_rgb, lambda d: d.ellipse((420, 820, 1220, 1620), fill=wash)
        )
        paper_rgb = _multiply_ink_shape(
            paper_rgb, lambda d: d.rounded_rectangle((76, 1080, 620, 1296), radius=12, fill=deep)
        )
    else:
        paper_rgb = _multiply_ink_shape(
            paper_rgb, lambda d: d.rounded_rectangle((76, 820, 1004, 1296), radius=220, fill=wash)
        )
        paper_rgb = _multiply_ink_shape(
            paper_rgb, lambda d: d.ellipse((500, 770, 1180, 1450), fill=highlight)
        )
        paper_rgb = _multiply_ink_shape(
            paper_rgb, lambda d: d.ellipse((-120, 910, 560, 1590), fill=soft_accent)
        )

    canvas = paper_rgb.convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    _draw_masthead(draw, topic, handle, accent, (*INK_SECONDARY, 235), (*INK_MUTED, 235))
    margin_x = 76
    content_w = CARD_WIDTH - margin_x * 2

    draw.line((margin_x, 104, CARD_WIDTH - margin_x, 104), fill=(*INK_PRIMARY, 185), width=3)
    stamp_font = _load_font("semibold", 18)
    topic_tag = (_strip_invisible(topic.get("topic_tag") or "") or "AI BRIEF").upper()
    draw.text((margin_x, 130), f"FOCUS  /  {topic_tag}", font=stamp_font, fill=(*INK_MUTED, 245))

    headline = _strip_invisible(topic["text"])
    h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 60, 52, font_weight="serif_bold")
    h_step = int(h_font.size * 1.13)
    h_end = _draw_text_lines(draw, h_lines, margin_x, 170, h_step, h_font, (*INK_PRIMARY, 255))

    blocks = _build_body_blocks(topic, max_blocks=3)
    body_font = _load_font("regular", 28)
    _draw_paragraph_blocks(
        draw,
        blocks,
        margin_x,
        h_end + 26,
        max_y=790,
        width=content_w - 20,
        font=body_font,
        line_step=39,
        fill=(*INK_SECONDARY, 242),
        para_gap=18,
    )

    return _apply_analog_grain(canvas, strength=0.45 + rng.uniform(0.0, 0.04))


def _render_editorial_horizon(
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
) -> Image.Image:
    """Warm archival paper with rich centered brief over grainy horizon art."""
    accent, wash, deep, highlight = palette
    rng = random.Random(seed)
    mist = (
        int(wash[0] * 0.45 + PAPER_CREAM[0] * 0.55),
        int(wash[1] * 0.45 + PAPER_CREAM[1] * 0.55),
        int(wash[2] * 0.45 + PAPER_CREAM[2] * 0.55),
    )

    base = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*PAPER_CREAM, 255))
    mist_layer = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    mist_x = rng.randint(620, 960) if seed % 2 == 0 else rng.randint(80, 420)
    ImageDraw.Draw(mist_layer).ellipse((mist_x - 520, 460, mist_x + 560, 1120), fill=(*mist, 150))
    base = Image.alpha_composite(base, mist_layer.filter(ImageFilter.GaussianBlur(radius=160)))

    horizon_y = rng.randint(835, 875)
    phase = rng.uniform(0.0, math.tau)
    amp = rng.uniform(9.0, 18.0)
    slope = rng.uniform(-0.02, 0.02)

    def wave(by: float, a: float, f: float, p: float, s: float) -> list[tuple[int, int]]:
        return [
            (
                min(x, CARD_WIDTH),
                int(
                    by
                    + s * (min(x, CARD_WIDTH) - CARD_WIDTH / 2)
                    + a * math.sin((min(x, CARD_WIDTH) / CARD_WIDTH) * math.pi * f + p)
                ),
            )
            for x in range(0, CARD_WIDTH + 20, 20)
        ]

    wave_main = wave(horizon_y, amp, 1.35, phase, slope)
    wave_low = wave(horizon_y + 165, amp * 1.5, 1.15, phase + 1.1, -slope * 0.8)

    art = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    ad = ImageDraw.Draw(art)
    ad.polygon(wave_main + [(CARD_WIDTH, CARD_HEIGHT), (0, CARD_HEIGHT)], fill=(*wash, 240))
    ad.polygon(wave_low + [(CARD_WIDTH, CARD_HEIGHT), (0, CARD_HEIGHT)], fill=(*highlight, 205))
    ad.polygon(
        [(x, y - 6) for x, y in wave_main] + [(x, y + 66) for x, y in reversed(wave_main)],
        fill=(*deep, 232),
    )
    base = Image.alpha_composite(base, art.filter(ImageFilter.GaussianBlur(radius=46)))

    crest = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(crest).line(wave_main, fill=(*deep, 175), width=18)
    base = Image.alpha_composite(base, crest.filter(ImageFilter.GaussianBlur(radius=10)))
    canvas = _apply_analog_grain(base, strength=0.44)
    draw = ImageDraw.Draw(canvas)

    _draw_masthead(draw, topic, handle, accent, (*INK_SECONDARY, 235), (*INK_MUTED, 235))
    headline = _strip_invisible(topic["text"])
    h_lines, h_font = _fit_headline_lines(draw, headline, 860, 62, 52, font_weight="serif")
    h_step = int(h_font.size * 1.13)

    blocks = _build_body_blocks(topic, max_blocks=2)
    body_font = _load_font("regular", 28)
    body_step = 39
    para_gap = 18

    # Measure full multi-paragraph copy so it fills the sky zone cleanly with even breathing room.
    measured_lines: list[list[str]] = []
    avail_lines = max(2, (790 - (140 + len(h_lines) * h_step + 28)) // body_step)
    for block in blocks:
        if avail_lines < 2:
            break
        wrapped = _wrap_text(draw, block, body_font, 820, max_lines=avail_lines)
        measured_lines.append(wrapped)
        avail_lines -= len(wrapped) + 1

    body_h = sum(len(lines) * body_step for lines in measured_lines) + max(0, len(measured_lines) - 1) * para_gap
    gap = 28 if measured_lines else 0
    total_h = len(h_lines) * h_step + gap + body_h
    start_y = max(136, 136 + (795 - 136 - total_h) // 2)

    y = _draw_text_lines(draw, h_lines, 0, start_y, h_step, h_font, (*INK_PRIMARY, 255), centered=True)
    if measured_lines:
        y += gap
        for lines in measured_lines:
            y = _draw_text_lines(draw, lines, 0, y, body_step, body_font, (*INK_SECONDARY, 245), centered=True)
            y += para_gap
    return canvas


_THEME_RENDERERS = {
    "framed_gallery": _render_framed_gallery,
    "dark_duotone": _render_dark_duotone,
    "riso_poster": _render_riso_poster,
    "editorial_horizon": _render_editorial_horizon,
}


def render_news_card(
    topic: dict,
    output_path: str | Path,
    handle: str = "@thechronobyte",
    theme: str | None = None,
) -> Path:
    """Render a 1080x1350 editorial JPEG card using one of four rotating print themes."""
    started = time.monotonic()
    source = _strip_invisible(topic.get("source", "Tech News"))
    seed = _topic_seed(topic)
    palettes = SOURCE_PALETTES.get(source, DEFAULT_PALETTES)
    palette_idx = seed % len(palettes)
    palette = palettes[palette_idx]

    if theme in _THEME_RENDERERS:
        chosen_theme = theme
        theme_mode = "explicit"
    else:
        chosen_theme = CARD_THEMES[seed % len(CARD_THEMES)]
        theme_mode = "rotating"

    serif_font = _resolve_font_path("serif_bold") or _resolve_font_path("serif")
    sans_font = _resolve_font_path("regular")
    body_blocks = _build_body_blocks(topic, max_blocks=3)
    LOGGER.info(
        "[4/6 Card] Rendering %dx%d JPEG | theme=%s (%s) | palette=%d/%d | source=%s | "
        "body_blocks=%d | fonts=(serif=%s, sans=%s)",
        CARD_WIDTH,
        CARD_HEIGHT,
        chosen_theme,
        theme_mode,
        palette_idx + 1,
        len(palettes),
        source,
        len(body_blocks),
        serif_font.name if serif_font else "pillow-default",
        sans_font.name if sans_font else "pillow-default",
    )

    canvas = _THEME_RENDERERS[chosen_theme](topic, palette, seed, handle)

    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(dest, format="JPEG", quality=95, optimize=True)
    size_kb = dest.stat().st_size / 1024.0
    LOGGER.info(
        "[4/6 Card] Saved JPEG %s (%.1f KB, %.2fs)",
        dest,
        size_kb,
        time.monotonic() - started,
    )
    return dest
