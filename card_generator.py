"""Generate editorial 1080x1350 (4:5) JPEG news cards for Instagram & Threads."""

import hashlib
import math
from pathlib import Path
import random
import re
import unicodedata

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

CARD_WIDTH = 1080
CARD_HEIGHT = 1350

PAPER_COLOR = (244, 241, 232)
INK_PRIMARY = (20, 22, 24)
INK_SECONDARY = (50, 53, 56)
INK_MUTED = (122, 118, 110)

# Curated atmospheric color palettes per source: (accent_dot, mist_tint, horizon_dark, primary_wash, warm_bloom).
SOURCE_PALETTES = {
    "OpenAI": (
        ((16, 163, 127), (146, 198, 182), (24, 62, 58), (212, 148, 72), (235, 198, 126)),
        ((16, 163, 127), (154, 188, 194), (30, 52, 74), (88, 152, 138), (228, 182, 108)),
    ),
    "NVIDIA": (
        ((102, 168, 0), (168, 196, 142), (28, 56, 26), (168, 178, 74), (226, 208, 120)),
        ((102, 168, 0), (148, 188, 168), (22, 48, 52), (96, 156, 98), (214, 192, 104)),
    ),
    "Google AI": (
        ((56, 118, 228), (156, 186, 218), (28, 46, 86), (214, 138, 68), (236, 198, 124)),
        ((56, 118, 228), (164, 198, 206), (34, 64, 88), (104, 154, 204), (226, 184, 118)),
    ),
    "AMD": (
        ((216, 42, 42), (206, 170, 154), (72, 26, 28), (208, 114, 58), (236, 188, 118)),
        ((216, 42, 42), (190, 178, 168), (54, 34, 42), (176, 88, 66), (228, 172, 112)),
    ),
    "Microsoft Research": (
        ((0, 142, 214), (152, 192, 216), (24, 48, 82), (126, 168, 206), (226, 192, 128)),
        ((0, 142, 214), (164, 196, 192), (26, 58, 72), (198, 144, 78), (232, 198, 136)),
    ),
}
DEFAULT_PALETTES = (
    ((78, 92, 208), (166, 186, 212), (32, 42, 74), (196, 136, 74), (232, 194, 126)),
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


def _load_font(weight: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES.get(weight, ()):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
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


def _build_subhead(topic: dict, max_chars: int = 210) -> str:
    """Select one crisp 2-4 line editorial subheadline distinct from the headline."""
    title_low = _strip_invisible(topic["text"]).lower()
    raw_items = list(topic.get("paragraphs") or [])
    summary = (topic.get("summary") or "").strip()
    if summary:
        raw_items.append(summary)

    chosen = ""
    for item in raw_items:
        cleaned = _strip_invisible(item).rstrip("…")
        cleaned = re.sub(r"\s*(?:\[\u2026\]|\[\.\.\.\]|…)$", "", cleaned).strip()
        if not cleaned or len(cleaned) < 25:
            continue
        low = cleaned.lower()
        if low == title_low:
            continue
        if low.startswith(title_low) and len(cleaned) > len(title_low) + 20:
            cleaned = cleaned[len(title_low):].lstrip(" ,:—-")
            if cleaned:
                cleaned = cleaned[0].upper() + cleaned[1:]
        chosen = cleaned
        break

    if not chosen:
        return ""
    if len(chosen) <= max_chars:
        return chosen
    clipped = chosen[:max_chars]
    for sep in (". ", "! ", "? "):
        idx = clipped.rfind(sep)
        if idx >= 70:
            return clipped[: idx + 1].strip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(" ,;:-") + "…"


def _apply_analog_grain(image: Image.Image, seed: int) -> Image.Image:
    """Blend crisp tactile analog film/riso grain across the canvas."""
    base_rgb = image.convert("RGB")
    fine = Image.effect_noise((CARD_WIDTH, CARD_HEIGHT), 26).convert("RGB")
    med = Image.effect_noise((CARD_WIDTH // 2, CARD_HEIGHT // 2), 28).resize(
        (CARD_WIDTH, CARD_HEIGHT), resample=Image.Resampling.BILINEAR
    ).convert("RGB")
    grain = Image.blend(fine, med, alpha=0.38)

    rng = random.Random(seed)
    grain_mix = 0.44 + rng.uniform(0.0, 0.06)
    soft = ImageChops.soft_light(base_rgb, grain)
    return Image.blend(base_rgb, soft, alpha=grain_mix).convert("RGBA")


def _build_wave(
    base_y: float,
    amp: float,
    freq: float,
    phase: float,
    slope: float,
    offset_jitter: list[float] | None = None,
) -> list[tuple[int, int]]:
    """Build smooth organic horizon contour points across the full card width."""
    pts: list[tuple[int, int]] = []
    step = 20
    for idx, x in enumerate(range(0, CARD_WIDTH + step, step)):
        cx = min(x, CARD_WIDTH)
        t = cx / CARD_WIDTH
        y = (
            base_y
            + slope * (cx - CARD_WIDTH / 2)
            + amp * math.sin(t * math.pi * freq + phase)
            + (amp * 0.38) * math.cos(t * math.pi * (freq * 2.1) - phase * 0.7)
        )
        if offset_jitter and idx < len(offset_jitter):
            y += offset_jitter[idx]
        pts.append((cx, int(y)))
    return pts


def _draw_editorial_background(
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
) -> Image.Image:
    """Create warm archival paper top fading into organic painterly horizon art."""
    _, mist, horizon_dark, wash, bloom = palette
    rng = random.Random(seed)

    base = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*PAPER_COLOR, 255))

    # 1. Soft atmospheric mist sweeping diagonally from lower right or lower left behind text.
    mist_layer = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    mist_draw = ImageDraw.Draw(mist_layer)
    mist_x = rng.randint(640, 960) if seed % 2 == 0 else rng.randint(80, 420)
    mist_draw.ellipse((mist_x - 520, 440, mist_x + 560, 1080), fill=(*mist, 138))
    mist_layer = mist_layer.filter(ImageFilter.GaussianBlur(radius=165))
    base = Image.alpha_composite(base, mist_layer)

    # 2. Painterly layered horizontal wave washes (organic sweep, no obvious circles).
    horizon_y = rng.randint(768, 808)
    phase = rng.uniform(0.0, math.tau)
    amp = rng.uniform(9.0, 18.0)
    slope = rng.uniform(-0.02, 0.02)
    wave_main = _build_wave(horizon_y, amp, 1.35, phase, slope)
    wave_mid = _build_wave(horizon_y + 165, amp * 1.6, 1.15, phase + 1.1, -slope * 0.8)
    wave_low = _build_wave(horizon_y + 340, amp * 1.4, 1.6, phase + 2.3, slope * 1.1)

    art_layer = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    art_draw = ImageDraw.Draw(art_layer)

    # Primary rich pigment base below the horizon.
    art_draw.polygon(wave_main + [(CARD_WIDTH, CARD_HEIGHT), (0, CARD_HEIGHT)], fill=(*wash, 240))
    # Sweeping mineral / sunlit secondary wash across lower region.
    art_draw.polygon(wave_mid + [(CARD_WIDTH, CARD_HEIGHT), (0, CARD_HEIGHT)], fill=(*bloom, 205))
    # Warm sunlit fade near bottom edge.
    light_paper = (
        min(255, int(bloom[0] * 0.45 + PAPER_COLOR[0] * 0.55)),
        min(255, int(bloom[1] * 0.45 + PAPER_COLOR[1] * 0.55)),
        min(255, int(bloom[2] * 0.45 + PAPER_COLOR[2] * 0.55)),
    )
    art_draw.polygon(wave_low + [(CARD_WIDTH, CARD_HEIGHT), (0, CARD_HEIGHT)], fill=(*light_paper, 175))

    # Deep organic pigment ridge right along the horizon transition.
    ridge_band = [(x, y - 6) for x, y in wave_main] + [(x, y + 72) for x, y in reversed(wave_main)]
    art_draw.polygon(ridge_band, fill=(*horizon_dark, 232))
    art_layer = art_layer.filter(ImageFilter.GaussianBlur(radius=48))
    base = Image.alpha_composite(base, art_layer)

    # 3. Tactile horizon stipple edge: subtly textured pigment band along the wave crest.
    jitter = [rng.uniform(-4.5, 4.5) for _ in range(len(wave_main))]
    crest_wave = _build_wave(horizon_y + 4, amp, 1.35, phase, slope, offset_jitter=jitter)
    crest_layer = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    crest_draw = ImageDraw.Draw(crest_layer)
    crest_draw.line([(x, y - 16) for x, y in crest_wave], fill=(*mist, 130), width=22)
    crest_draw.line(crest_wave, fill=(*horizon_dark, 175), width=20)
    crest_layer = crest_layer.filter(ImageFilter.GaussianBlur(radius=11))
    base = Image.alpha_composite(base, crest_layer)

    return _apply_analog_grain(base, seed)


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    start_y: int,
    line_step: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> int:
    """Draw horizontally centered lines and return the ending y-coordinate."""
    y = start_y
    for line in lines:
        w = _text_width(draw, line, font)
        draw.text(((CARD_WIDTH - w) / 2, y), line, font=font, fill=fill)
        y += line_step
    return y


def render_news_card(topic: dict, output_path: str | Path, handle: str = "@thechronobyte") -> Path:
    """Render a 1080x1350 editorial JPEG card with paper top + textured horizon art."""
    source = _strip_invisible(topic.get("source", "Tech News"))
    headline_text = _strip_invisible(topic["text"])
    seed = _topic_seed(topic)
    palettes = SOURCE_PALETTES.get(source, DEFAULT_PALETTES)
    palette = palettes[seed % len(palettes)]
    accent = palette[0]

    canvas = _draw_editorial_background(palette, seed)
    draw = ImageDraw.Draw(canvas)

    font_header_bold = _load_font("semibold", 19)
    font_header = _load_font("regular", 19)
    font_headline = _load_font("serif", 68)
    font_body = _load_font("regular", 30)

    # Subtle minimal top masthead so the headline & subhead remain the centerpiece.
    margin_x = 76
    top_y = 54
    draw.rounded_rectangle((margin_x, top_y + 5, margin_x + 12, top_y + 17), radius=3, fill=(*accent, 255))
    brand_label = "CHRONO BYTE"
    draw.text((margin_x + 22, top_y), brand_label, font=font_header_bold, fill=(*INK_SECONDARY, 235))
    brand_w = _text_width(draw, brand_label, font_header_bold)
    draw.text((margin_x + 28 + brand_w, top_y), f" ·  {handle}", font=font_header, fill=(*INK_MUTED, 235))

    published = topic["published"]
    date_label = published.strftime("%b %d, %Y").upper().replace(" 0", " ")
    meta_label = f"{source.upper()}  ·  {date_label}"
    meta_w = _text_width(draw, meta_label, font_header)
    draw.text((CARD_WIDTH - margin_x - meta_w, top_y), meta_label, font=font_header, fill=(*INK_MUTED, 235))

    # Measure centered editorial headline + subhead inside the upper paper region.
    headline_width = 820
    headline_lines = _wrap_text(draw, headline_text, font_headline, headline_width, max_lines=4)
    if len(headline_lines) >= 4:
        font_headline = _load_font("serif", 58)
        headline_lines = _wrap_text(draw, headline_text, font_headline, headline_width, max_lines=4)
    headline_step = int(font_headline.size * 1.13)

    subhead_text = _build_subhead(topic)
    body_width = 760
    body_step = 42
    body_lines = _wrap_text(draw, subhead_text, font_body, body_width, max_lines=4) if subhead_text else []

    gap = 32 if body_lines else 0
    block_height = len(headline_lines) * headline_step + gap + len(body_lines) * body_step
    zone_top = 148
    zone_bottom = 720
    start_y = max(zone_top, zone_top + (zone_bottom - zone_top - block_height) // 2)

    after_headline_y = _draw_centered_lines(
        draw,
        headline_lines,
        start_y,
        headline_step,
        font_headline,
        (*INK_PRIMARY, 255),
    )
    if body_lines:
        _draw_centered_lines(
            draw,
            body_lines,
            after_headline_y + gap,
            body_step,
            font_body,
            (*INK_SECONDARY, 245),
        )

    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(dest, format="JPEG", quality=95, optimize=True)
    return dest
