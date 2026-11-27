"""Generate dynamic 1080x1350 (4:5) Instagram news carousels themed live from each source."""

import colorsys
import hashlib
import logging
import math
from pathlib import Path
import random
import re
import time
import unicodedata

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

LOGGER = logging.getLogger(__name__)

CARD_WIDTH = 1080
CARD_HEIGHT = 1350

INK_PRIMARY = (18, 20, 24)
INK_SECONDARY = (48, 52, 58)
INK_MUTED = (108, 108, 104)
LIGHT_PRIMARY = (246, 245, 240)
LIGHT_SECONDARY = (212, 212, 206)
LIGHT_MUTED = (154, 156, 152)

CARD_THEMES = (
    "full_bleed_hero",
    "split_top_photo",
    "split_bottom_photo",
    "editorial_sidebar",
    "duotone_frame",
    "riso_zine",
)
_THEME_ALIASES = {
    "framed_gallery": "split_bottom_photo",
    "framed_dispatch": "split_bottom_photo",
    "dark_duotone": "duotone_frame",
    "duotone_cinema": "duotone_frame",
    "riso_poster": "riso_zine",
    "riso_kinetic": "riso_zine",
    "editorial_horizon": "split_top_photo",
    "split_editorial": "split_top_photo",
}

FONT_CANDIDATES = {
    "serif": (
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/cambria.ttc",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
    ),
    "serif_bold": (
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/cambriab.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
    ),
    "display": (
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    "semibold": (
        "C:/Windows/Fonts/seguisb.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    "regular": (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    "mono": (
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
}

_CONTINUATION_SECTIONS = (
    "KEY TAKEAWAYS",
    "INSIDE THE RELEASE",
    "CLOSER LOOK",
    "THE DETAILS",
)
_METRIC_PATTERN = re.compile(
    r"(?:US\$|AU\$|CA\$|USD|INR|EUR|GBP|[₹$€£])\s*\d[\d,.]*(?:\s*(?:million|billion|M|B|K))?\b"
    r"|\b\d+(?:\.\d+)?x\b"
    r"|\b\d+(?:\.\d+)?%"
    r"|\b\d{1,3}(?:,\d{3})+\+?",
    re.I,
)


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
    cleaned = re.sub(r"\s*\(\s*opens in a new (?:window|tab)\s*\)", "", text, flags=re.I)
    return " ".join(
        "".join(ch for ch in cleaned if unicodedata.category(ch) not in {"Cs", "Cf"}).split()
    )


def _topic_seed(topic: dict) -> int:
    key = f"{topic.get('published', '')}|{topic.get('source_url', '')}|{topic.get('text', '')}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16)


def _split_long_block(text: str, target_chars: int = 230) -> list[str]:
    if len(text) <= target_chars + 65:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) <= 1:
        return [text]
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        trial = f"{current} {sent}".strip()
        if current and len(trial) > target_chars:
            chunks.append(current)
            current = sent
        else:
            current = trial
    if current:
        if chunks and len(current) < 65:
            chunks[-1] = f"{chunks[-1]} {current}".strip()
        else:
            chunks.append(current)
    return chunks


def _build_body_blocks(
    topic: dict,
    max_blocks: int = 12,
    split_long: bool = False,
    target_chars: int = 230,
) -> list[str]:
    """Collect distinct source paragraphs + RSS lead without repeating the headline."""
    title_low = _strip_invisible(topic["text"]).lower()
    summary = re.sub(r"\s*(?:\[\u2026\]|\[\.\.\.\]|…)$", "", (topic.get("summary") or "").strip())
    raw_items = list(topic.get("paragraphs") or []) + list(topic.get("content_blocks") or [])
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
        pieces = _split_long_block(cleaned, target_chars=target_chars) if split_long else [cleaned]
        for piece in pieces:
            selected.append(piece)
            if len(selected) == max_blocks:
                return selected
    return selected


# ---------------------------------------------------------------------------
# Live Source Theme & Photo Palette Extraction (Zero Hardcoded Brand Table)
# ---------------------------------------------------------------------------


def _hsv_to_rgb_int(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def _rgb_to_hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)


def _tune_accent(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Preserve scraped hue while ensuring crisp readable contrast on dark & light cards."""
    h, s, v = _rgb_to_hsv(rgb)
    return _hsv_to_rgb_int(h, max(0.46, min(0.88, s)), max(0.56, min(0.88, v)))


def _tune_wash(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    h, s, v = _rgb_to_hsv(rgb)
    return _hsv_to_rgb_int(h, max(0.28, min(0.66, s)), max(0.46, min(0.76, v)))


def _tune_deep(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    h, s, _ = _rgb_to_hsv(rgb)
    return _hsv_to_rgb_int(h, max(0.22, min(0.56, s if s > 0.08 else 0.25)), 0.17)


def _tune_highlight(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    h, s, _ = _rgb_to_hsv(rgb)
    return _hsv_to_rgb_int(h, max(0.32, min(0.72, s if s > 0.1 else 0.45)), 0.88)


def _surface_tones_from_hue(h: float, scraped_bgs: list[tuple[int, int, int]]) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """Derive custom-tinted dark ink, light paper, and warm buff paper harmonized to the source."""
    dark_bg = _hsv_to_rgb_int(h, 0.24, 0.10)
    light_bg = _hsv_to_rgb_int(h, 0.045, 0.965)
    buff_bg = _hsv_to_rgb_int((h + 0.04) % 1.0, 0.095, 0.935)
    for bg in scraped_bgs:
        luma = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        bh, bs, bv = _rgb_to_hsv(bg)
        if 8 <= luma <= 52:
            dark_bg = _hsv_to_rgb_int(bh, min(0.35, bs), max(0.08, min(0.16, bv)))
            break
    for bg in scraped_bgs:
        luma = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        bh, bs, bv = _rgb_to_hsv(bg)
        if 225 <= luma <= 252 and bs >= 0.02:
            light_bg = _hsv_to_rgb_int(bh, min(0.07, bs), max(0.94, min(0.98, bv)))
            break
    return dark_bg, light_bg, buff_bg


def _extract_photo_clusters(img: Image.Image, n_colors: int = 10) -> list[tuple[int, tuple[int, int, int]]]:
    """Extract dominant RGB clusters from a source photograph using Pillow median-cut."""
    rgb = _flatten_to_rgb(img, (240, 238, 232)).resize((64, 64), Image.Resampling.BILINEAR)
    quant = rgb.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT)
    raw_pal = quant.getpalette() or []
    counts = quant.getcolors(maxcolors=n_colors + 4) or []
    clusters: list[tuple[int, tuple[int, int, int]]] = []
    for count, idx in sorted(counts, reverse=True):
        base = idx * 3
        if base + 2 < len(raw_pal):
            clusters.append((count, (raw_pal[base], raw_pal[base + 1], raw_pal[base + 2])))
    return clusters


def _pick_distinct_color(
    candidates: list[tuple[int, int, int]],
    avoid: tuple[int, int, int],
    min_hue_gap: float = 0.09,
) -> tuple[int, int, int] | None:
    ah, _, _ = _rgb_to_hsv(avoid)
    for rgb in candidates:
        h, s, v = _rgb_to_hsv(rgb)
        gap = min(abs(h - ah), 1.0 - abs(h - ah))
        if s >= 0.18 and v >= 0.20 and gap >= min_hue_gap:
            return rgb
    return None


def _resolve_live_palette(
    source_images: list[dict],
    source_theme: dict | None,
    seed: int,
) -> dict:
    """Build a complete color palette dynamically from scraped source CSS + hero photo."""
    theme = source_theme if isinstance(source_theme, dict) else {}
    scraped_accents = [tuple(int(v) for v in c) for c in (theme.get("accents") or []) if len(c) == 3]
    scraped_bgs = [tuple(int(v) for v in c) for c in (theme.get("backgrounds") or []) if len(c) == 3]

    photo_chromatic: list[tuple[int, int, int]] = []
    photo_darks: list[tuple[int, int, int]] = []
    if source_images:
        clusters = _extract_photo_clusters(source_images[0]["image"])
        scored = []
        for count, rgb in clusters:
            _, s, v = _rgb_to_hsv(rgb)
            if v <= 0.34:
                photo_darks.append(rgb)
            if s >= 0.18 and 0.16 <= v <= 0.96:
                score = (s ** 1.2) * (0.35 + 0.65 * v) * math.log(count + 2.0)
                scored.append((score, rgb))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        photo_chromatic = [rgb for _, rgb in scored]

    origin_parts: list[str] = []
    if scraped_accents:
        origin_parts.append("scraped_css")
    if photo_chromatic:
        origin_parts.append("source_photo")

    # Prioritize live scraped CSS accents & source photo clusters; only fall back algorithmically if bare offline dict.
    if photo_chromatic and scraped_accents:
        # Rotate seamlessly between hero photo's vibrant anchor and webpage brand accent.
        primary_raw = photo_chromatic[0] if seed % 2 == 0 else scraped_accents[0]
        pool = scraped_accents + photo_chromatic
    elif photo_chromatic:
        primary_raw = photo_chromatic[0]
        pool = photo_chromatic
    elif scraped_accents:
        primary_raw = scraped_accents[0]
        pool = scraped_accents
    else:
        origin_parts.append("algorithmic_hsv")
        hue = ((seed * 137) % 360) / 360.0
        primary_raw = _hsv_to_rgb_int(hue, 0.72, 0.80)
        pool = [
            _hsv_to_rgb_int((hue + 0.08) % 1.0, 0.54, 0.70),
            _hsv_to_rgb_int((hue + 0.56) % 1.0, 0.58, 0.86),
        ]

    accent = _tune_accent(primary_raw)
    ah, _, _ = _rgb_to_hsv(accent)
    secondary_raw = _pick_distinct_color(pool, accent, min_hue_gap=0.07) or _hsv_to_rgb_int((ah + 0.09) % 1.0, 0.52, 0.72)
    wash = _tune_wash(secondary_raw)

    highlight_raw = _pick_distinct_color(pool, secondary_raw, min_hue_gap=0.14) or _hsv_to_rgb_int((ah + 0.42) % 1.0, 0.56, 0.88)
    highlight = _tune_highlight(highlight_raw)

    deep_raw = photo_darks[0] if photo_darks else primary_raw
    deep = _tune_deep(deep_raw)
    dark_surface, light_surface, buff_surface = _surface_tones_from_hue(ah, scraped_bgs)

    return {
        "accent": accent,
        "wash": wash,
        "deep": deep,
        "highlight": highlight,
        "dark_surface": dark_surface,
        "light_surface": light_surface,
        "buff_surface": buff_surface,
        "origin": "+".join(origin_parts),
    }


def _coerce_source_images(source_images, topic: dict) -> list[dict]:
    """Normalize optional verified source photos into {'image': Image, 'credit': str} dicts."""
    raw_list = source_images if source_images is not None else topic.get("images") or []
    source_name = _strip_invisible(topic.get("source") or "Source").upper()
    domain = _strip_invisible(topic.get("allowed_host") or "").upper()
    default_credit = f"{source_name} ({domain})" if domain and domain not in source_name else source_name

    normalized: list[dict] = []
    for entry in raw_list:
        if isinstance(entry, Image.Image):
            normalized.append({"image": entry.copy(), "credit": default_credit})
        elif isinstance(entry, dict) and isinstance(entry.get("image"), Image.Image):
            host = _strip_invisible(str(entry.get("source_host") or "")).upper()
            credit = _strip_invisible(str(entry.get("credit") or "")).upper() or host or default_credit
            normalized.append({"image": entry["image"].copy(), "credit": credit})
    return normalized


def _flatten_to_rgb(img: Image.Image, bg_rgb: tuple[int, int, int]) -> Image.Image:
    if img.mode == "RGB":
        return img
    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (*bg_rgb, 255))
    return Image.alpha_composite(bg, rgba).convert("RGB")


def _analyze_image(img: Image.Image) -> dict:
    w, h = img.size
    aspect = w / max(1, h)
    sample = _flatten_to_rgb(img, (242, 240, 234)).resize((32, 32), Image.Resampling.BILINEAR).convert("L")
    luma = ImageStat.Stat(sample).mean[0]
    return {"width": w, "height": h, "aspect": aspect, "luma": luma}


def _compose_post_template(
    topic: dict,
    source_images: list[dict],
    source_theme: dict | None,
    seed: int,
    explicit_theme: str | None = None,
) -> dict:
    """Dynamically compose a unique per-post visual template recipe from source + photo + seed."""
    theme = source_theme if isinstance(source_theme, dict) else {}
    img_stats = _analyze_image(source_images[0]["image"]) if source_images else None

    scraped_polarity = str(theme.get("polarity") or "").lower()
    if explicit_theme in _THEME_ALIASES:
        layout, mode = _THEME_ALIASES[explicit_theme], "alias"
    elif explicit_theme in CARD_THEMES:
        layout, mode = explicit_theme, "explicit"
    else:
        mode = "dynamic"
        if scraped_polarity == "light" and (seed // 7) % 4 != 0:
            pool = ("split_top_photo", "split_bottom_photo", "editorial_sidebar", "riso_zine")
        elif img_stats and (img_stats["aspect"] >= 1.55 or img_stats["luma"] >= 205):
            pool = ("split_top_photo", "split_bottom_photo", "editorial_sidebar", "duotone_frame", "riso_zine")
        else:
            pool = CARD_THEMES
        layout = pool[seed % len(pool)]

    if layout in {"full_bleed_hero", "duotone_frame"}:
        dark_mode = True
    elif layout == "riso_zine":
        dark_mode = False
    elif scraped_polarity == "dark":
        dark_mode = True
    elif scraped_polarity == "light":
        dark_mode = False
    elif img_stats and img_stats["luma"] < 85:
        dark_mode = (seed // 5) % 2 == 0
    else:
        dark_mode = (seed // 5) % 3 == 0

    font_hint = str(theme.get("font_hint") or "").lower()
    if layout == "riso_zine":
        headline_font = "display"
    elif font_hint == "serif":
        headline_font = "serif_bold" if seed % 3 != 0 else "serif"
    elif font_hint == "sans":
        headline_font = "display" if seed % 3 != 0 else "serif_bold"
    else:
        headline_font = ("serif_bold", "display", "serif")[(seed // 11) % 3]

    if layout == "riso_zine":
        frame_style = "offset_block"
    elif layout == "duotone_frame":
        frame_style = "hairline_glow"
    else:
        frame_style = ("elevated_shadow", "polaroid_mat", "hairline_glow", "offset_block")[(seed // 13) % 4]

    kicker_style = ("solid_pill", "outline_pill", "bracket_mono", "accent_bar")[(seed // 17) % 4]
    motif = (
        "riso_shapes"
        if layout == "riso_zine"
        else ("dot_grid", "arch_lines", "ambient_blur", "concentric_rings", "clean_grain")[(seed // 19) % 5]
    )
    progress_style = "bar" if (seed // 23) % 2 == 0 else "dots"
    card_badge_style = ("solid_square", "outline_ring", "accent_rail")[(seed // 29) % 3]

    return {
        "layout": layout,
        "mode": mode,
        "dark_mode": dark_mode,
        "headline_font": headline_font,
        "frame_style": frame_style,
        "kicker_style": kicker_style,
        "motif": motif,
        "progress_style": progress_style,
        "card_badge_style": card_badge_style,
        "flip_extra_photo": bool((seed // 31) % 2),
    }


# ---------------------------------------------------------------------------
# Rendering Primitives
# ---------------------------------------------------------------------------


def _fit_photo_panel(
    img: Image.Image,
    target_w: int,
    target_h: int,
    matte_rgb: tuple[int, int, int],
    crop_focus: tuple[float, float] = (0.5, 0.36),
    allow_contain_for_wide: bool = True,
) -> Image.Image:
    rgb = _flatten_to_rgb(img, matte_rgb)
    src_w, src_h = rgb.size
    src_aspect = src_w / max(1, src_h)
    dst_aspect = target_w / max(1, target_h)

    if allow_contain_for_wide and (src_aspect > dst_aspect * 1.75 or src_aspect < dst_aspect * 0.50):
        backdrop = ImageOps.fit(rgb, (target_w, target_h), method=Image.Resampling.BILINEAR, centering=(0.5, 0.5))
        backdrop = ImageEnhance.Brightness(backdrop.filter(ImageFilter.GaussianBlur(radius=34))).enhance(0.55)
        pad = 20
        contained = ImageOps.contain(rgb, (max(40, target_w - pad * 2), max(40, target_h - pad * 2)), method=Image.Resampling.LANCZOS)
        cw, ch = contained.size
        canvas = backdrop.convert("RGBA")
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw, ch), radius=12, fill=255)
        canvas.paste(contained.convert("RGBA"), ((target_w - cw) // 2, (target_h - ch) // 2), mask)
        return canvas

    return ImageOps.fit(rgb, (target_w, target_h), method=Image.Resampling.LANCZOS, centering=crop_focus).convert("RGBA")


def _apply_analog_grain(image: Image.Image, strength: float = 0.18) -> Image.Image:
    if strength <= 0:
        return image.convert("RGBA")
    w, h = image.size
    base_rgb = image.convert("RGB")
    fine = Image.effect_noise((w, h), 20).convert("RGB")
    med = Image.effect_noise((max(1, w // 2), max(1, h // 2)), 22).resize((w, h), resample=Image.Resampling.BILINEAR).convert("RGB")
    grain = Image.blend(fine, med, alpha=0.35)
    soft = ImageChops.soft_light(base_rgb, grain)
    return Image.blend(base_rgb, soft, alpha=strength).convert("RGBA")


def _apply_linear_scrim(
    canvas: Image.Image,
    start_y: int,
    end_y: int,
    color_rgb: tuple[int, int, int],
    start_alpha: int = 0,
    end_alpha: int = 244,
) -> Image.Image:
    if end_y <= start_y:
        return canvas
    grad = Image.linear_gradient("L").resize((1, end_y - start_y), resample=Image.Resampling.BILINEAR)
    span = end_alpha - start_alpha
    grad = grad.point(lambda p: max(0, min(255, int(start_alpha + (p / 255.0) * span))))
    full_alpha = Image.new("L", canvas.size, 0)
    full_alpha.paste(grad.resize((CARD_WIDTH, end_y - start_y), resample=Image.Resampling.NEAREST), (0, start_y))
    if end_y < CARD_HEIGHT and end_alpha > 0:
        ImageDraw.Draw(full_alpha).rectangle((0, end_y, CARD_WIDTH, CARD_HEIGHT), fill=end_alpha)
    overlay = Image.new("RGBA", canvas.size, (*color_rgb, 255))
    overlay.putalpha(full_alpha)
    return Image.alpha_composite(canvas, overlay)


def _apply_motif(
    canvas: Image.Image,
    motif: str,
    palette: dict,
    dark_mode: bool,
    seed: int,
    hero_photo: Image.Image | None = None,
) -> Image.Image:
    """Apply a subtle per-post background motif harmonized to the live palette."""
    accent, wash, highlight = palette["accent"], palette["wash"], palette["highlight"]
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    stroke = (255, 255, 255, 16) if dark_mode else (*INK_PRIMARY, 16)

    if motif == "dot_grid":
        for y in range(118, CARD_HEIGHT - 125, 30):
            for x in range(36, CARD_WIDTH - 36, 30):
                draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=stroke)
        return Image.alpha_composite(canvas, layer)

    if motif == "arch_lines":
        for x in (68, CARD_WIDTH // 2, CARD_WIDTH - 68):
            draw.line((x, 108, x, CARD_HEIGHT - 128), fill=stroke, width=1)
        for y in (360, 740, 1080):
            draw.line((68, y, CARD_WIDTH - 68, y), fill=stroke, width=1)
        # Subtle editorial corner crop marks
        mark = (*accent, 110)
        for cx, cy in ((42, 42), (CARD_WIDTH - 42, 42), (42, CARD_HEIGHT - 42), (CARD_WIDTH - 42, CARD_HEIGHT - 42)):
            draw.line((cx - 10, cy, cx + 10, cy), fill=mark, width=2)
            draw.line((cx, cy - 10, cx, cy + 10), fill=mark, width=2)
        return Image.alpha_composite(canvas, layer)

    if motif == "concentric_rings":
        rng = random.Random(seed + 5)
        cx = int(CARD_WIDTH * rng.uniform(0.68, 0.92))
        cy = int(CARD_HEIGHT * rng.uniform(0.18, 0.42))
        ring_stroke = (*accent, 34) if dark_mode else (*accent, 38)
        for r in (130, 220, 310, 400, 490):
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ring_stroke, width=2)
        return Image.alpha_composite(canvas, layer)

    if motif == "ambient_blur" and hero_photo is not None:
        base_bg = palette["dark_surface"] if dark_mode else palette["light_surface"]
        ambient = ImageOps.fit(_flatten_to_rgb(hero_photo, base_bg), canvas.size, method=Image.Resampling.BILINEAR)
        ambient = ambient.filter(ImageFilter.GaussianBlur(radius=92))
        if dark_mode:
            ambient = ImageEnhance.Brightness(ambient).enhance(0.24).convert("RGBA")
            return Image.blend(canvas, ambient, alpha=0.62)
        soft = Image.blend(ambient, Image.new("RGB", canvas.size, base_bg), alpha=0.86).convert("RGBA")
        return Image.blend(canvas, soft, alpha=0.72)

    if motif == "riso_shapes":
        paper_rgb = canvas.convert("RGB")
        paper_rgb = _multiply_ink_shape(paper_rgb, lambda d: d.ellipse((620, 620, 1260, 1180), fill=highlight), 2.0)
        paper_rgb = _multiply_ink_shape(paper_rgb, lambda d: d.pieslice((-120, 720, 620, 1210), 270, 90, fill=wash), 2.0)
        return paper_rgb.convert("RGBA")

    return canvas


def _multiply_ink_shape(canvas_rgb: Image.Image, draw_fn, blur_radius: float = 1.5) -> Image.Image:
    ink = Image.new("RGB", canvas_rgb.size, (255, 255, 255))
    draw_fn(ImageDraw.Draw(ink))
    if blur_radius > 0:
        ink = ink.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    return ImageChops.multiply(canvas_rgb, ink)


def _composite_rounded_box(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    width: int = 0,
) -> Image.Image:
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    return Image.alpha_composite(canvas, overlay)


def _draw_pill(
    canvas: Image.Image,
    text: str,
    x: int,
    y: int,
    bg_fill: tuple[int, int, int, int],
    text_fill: tuple[int, int, int, int],
    outline_fill: tuple[int, int, int, int] | None = None,
    align_right: bool = False,
    font_weight: str = "mono",
    font_size: int = 14,
    pad_x: int = 15,
    height: int = 30,
) -> tuple[Image.Image, int]:
    font = _load_font(font_weight, font_size)
    probe = ImageDraw.Draw(canvas)
    tw = _text_width(probe, text, font)
    box_w = int(tw + pad_x * 2)
    left = (x - box_w) if align_right else x
    canvas = _composite_rounded_box(
        canvas,
        (left, y, left + box_w, y + height),
        radius=height // 2,
        fill=bg_fill,
        outline=outline_fill,
        width=1 if outline_fill else 0,
    )
    text_y = y + max(4, (height - font_size) // 2 - 2)
    ImageDraw.Draw(canvas).text((left + pad_x, text_y), text, font=font, fill=text_fill)
    return canvas, box_w


def _draw_kicker(
    canvas: Image.Image,
    text: str,
    x: int,
    y: int,
    spec: dict,
    palette: dict,
) -> Image.Image:
    """Draw a per-post styled category kicker (solid pill, outline, mono bracket, or accent bar)."""
    accent, deep = palette["accent"], palette["deep"]
    dark = spec["dark_mode"]
    ks = spec["kicker_style"]
    if ks == "solid_pill":
        canvas, _ = _draw_pill(canvas, text, x, y, (*accent, 245), (255, 255, 255, 255), height=30)
        return canvas
    if ks == "outline_pill":
        bg = (*palette["dark_surface"], 220) if dark else (*palette["light_surface"], 235)
        fg = (*accent, 255) if dark else (*deep, 255)
        canvas, _ = _draw_pill(canvas, text, x, y, bg, fg, outline_fill=(*accent, 210), height=30)
        return canvas
    if ks == "bracket_mono":
        font = _load_font("mono", 16)
        fill = (*accent, 255) if dark else (*deep, 255)
        ImageDraw.Draw(canvas).text((x, y + 6), f"[ {text} ]", font=font, fill=fill)
        return canvas
    # accent_bar
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((x, y + 6, x + 5, y + 26), fill=(*accent, 255))
    font = _load_font("mono", 15)
    fill = (*LIGHT_PRIMARY, 245) if dark else (*INK_PRIMARY, 245)
    draw.text((x + 14, y + 7), text, font=font, fill=fill)
    return canvas


def _paste_photo_frame(
    canvas: Image.Image,
    photo: Image.Image,
    box: tuple[int, int, int, int],
    palette: dict,
    frame_style: str = "elevated_shadow",
    dark_mode: bool = False,
    credit_text: str = "",
    crop_focus: tuple[float, float] = (0.5, 0.36),
) -> Image.Image:
    """Mount a source photograph using the post's dynamic frame treatment."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    accent, deep = palette["accent"], palette["deep"]
    matte_rgb = deep if dark_mode else palette["buff_surface"]
    short_credit = credit_text if len(credit_text) <= 28 else credit_text[:25].rstrip() + "…"

    if frame_style == "polaroid_mat":
        mat_fill = (30, 34, 42, 248) if dark_mode else (255, 255, 255, 252)
        mat_border = (255, 255, 255, 42) if dark_mode else (20, 22, 24, 34)
        shadow = Image.new("RGBA", (CARD_WIDTH // 2, CARD_HEIGHT // 2), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((x0 // 2, (y0 + 10) // 2, x1 // 2, (y1 + 12) // 2), radius=8, fill=(0, 0, 0, 80))
        canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(radius=14)).resize(canvas.size, Image.Resampling.BILINEAR))
        canvas = _composite_rounded_box(canvas, box, radius=16, fill=mat_fill, outline=mat_border, width=1)
        pad = 16
        bot_pad = 44 if short_credit else 16
        ix0, iy0, ix1, iy1 = x0 + pad, y0 + pad, x1 - pad, y1 - bot_pad
        iw, ih = max(40, ix1 - ix0), max(40, iy1 - iy0)
        fitted = _fit_photo_panel(photo, iw, ih, matte_rgb=matte_rgb, crop_focus=crop_focus)
        mask = Image.new("L", (iw, ih), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, iw, ih), radius=10, fill=255)
        canvas.paste(fitted, (ix0, iy0), mask)
        if short_credit:
            cfont = _load_font("mono", 13)
            cfill = (*LIGHT_MUTED, 235) if dark_mode else (*INK_MUTED, 240)
            ImageDraw.Draw(canvas).text((ix0 + 4, iy1 + 13), f"SOURCE PHOTO  ·  {short_credit}", font=cfont, fill=cfill)
        return canvas

    radius = 12 if frame_style == "offset_block" else 18
    if frame_style == "offset_block":
        canvas = _composite_rounded_box(canvas, (x0 + 10, y0 + 10, x1 + 10, y1 + 10), radius=radius, fill=(*accent, 238))
    else:
        shadow = Image.new("RGBA", (CARD_WIDTH // 2, CARD_HEIGHT // 2), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (x0 // 2, (y0 + 10) // 2, x1 // 2, (y1 + 12) // 2),
            radius=max(2, radius // 2),
            fill=(0, 0, 0, 115 if dark_mode else 82),
        )
        canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(radius=14)).resize(canvas.size, Image.Resampling.BILINEAR))

    fitted = _fit_photo_panel(photo, w, h, matte_rgb=matte_rgb, crop_focus=crop_focus)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
    canvas.paste(fitted, (x0, y0), mask)

    if frame_style == "offset_block":
        border, bwidth = (*INK_PRIMARY, 240) if not dark_mode else (*LIGHT_PRIMARY, 210), 3
    elif frame_style == "hairline_glow":
        border, bwidth = (*accent, 200), 2
    else:
        border, bwidth = (255, 255, 255, 44) if dark_mode else (20, 22, 24, 34), 2

    canvas = _composite_rounded_box(canvas, box, radius=radius, fill=(0, 0, 0, 0), outline=border, width=bwidth)
    if short_credit:
        canvas, _ = _draw_pill(
            canvas,
            f"SOURCE · {short_credit}",
            x1 - 14,
            y1 - 40,
            bg_fill=(14, 16, 22, 198),
            text_fill=(*LIGHT_PRIMARY, 242),
            outline_fill=(255, 255, 255, 55),
            align_right=True,
            font_size=12,
            pad_x=11,
            height=26,
        )
    return canvas


def _draw_masthead(
    canvas: Image.Image,
    topic: dict,
    handle: str,
    accent: tuple[int, int, int],
    primary_fill: tuple[int, int, int, int],
    muted_fill: tuple[int, int, int, int],
    rule_fill: tuple[int, int, int, int] | None = None,
    frosted: bool = False,
    margin_x: int = 68,
) -> Image.Image:
    top_y = 48
    source = _strip_invisible(topic.get("source", "Tech News")).upper()
    date_label = topic["published"].strftime("%b %d, %Y").upper().replace(" 0", " ")
    meta = f"{source}  ·  {date_label}"

    if frosted:
        font_b = _load_font("semibold", 16)
        probe = ImageDraw.Draw(canvas)
        left_text = f"CHRONO BYTE  ·  {handle}"
        lw = int(_text_width(probe, left_text, font_b) + 46)
        canvas = _composite_rounded_box(
            canvas,
            (margin_x, top_y - 6, margin_x + lw, top_y + 30),
            radius=18,
            fill=(14, 16, 22, 198),
            outline=(255, 255, 255, 55),
            width=1,
        )
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((margin_x + 14, top_y + 7, margin_x + 24, top_y + 17), radius=2, fill=(*accent, 255))
        draw.text((margin_x + 32, top_y + 2), left_text, font=font_b, fill=(*LIGHT_PRIMARY, 248))
        canvas, _ = _draw_pill(
            canvas,
            meta,
            CARD_WIDTH - margin_x,
            top_y - 6,
            bg_fill=(14, 16, 22, 198),
            text_fill=(*LIGHT_PRIMARY, 238),
            outline_fill=(255, 255, 255, 55),
            align_right=True,
            font_size=14,
            pad_x=15,
            height=36,
        )
        return canvas

    draw = ImageDraw.Draw(canvas)
    font_bold = _load_font("semibold", 18)
    font_reg = _load_font("regular", 18)
    draw.rounded_rectangle((margin_x, top_y + 4, margin_x + 12, top_y + 16), radius=3, fill=(*accent, 255))
    brand = "CHRONO BYTE"
    draw.text((margin_x + 22, top_y), brand, font=font_bold, fill=primary_fill)
    brand_w = _text_width(draw, brand, font_bold)
    draw.text((margin_x + 28 + brand_w, top_y), f" ·  {handle}", font=font_reg, fill=muted_fill)
    meta_w = _text_width(draw, meta, font_reg)
    draw.text((CARD_WIDTH - margin_x - meta_w, top_y), meta, font=font_reg, fill=muted_fill)
    if rule_fill is not None:
        draw.line((margin_x, 96, CARD_WIDTH - margin_x, 96), fill=rule_fill, width=1)
    return canvas


def _draw_progress_footer(
    canvas: Image.Image,
    current_idx: int,
    total_slides: int,
    handle: str,
    label: str,
    accent: tuple[int, int, int],
    muted_fill: tuple[int, int, int, int],
    divider_fill: tuple[int, int, int, int] | None,
    badge_bg: tuple[int, int, int, int],
    badge_text: tuple[int, int, int, int],
    badge_outline: tuple[int, int, int, int] | None = None,
    margin_x: int = 68,
    progress_style: str = "dots",
) -> Image.Image:
    draw = ImageDraw.Draw(canvas)
    if divider_fill is not None:
        draw.line((margin_x, 1222, CARD_WIDTH - margin_x, 1222), fill=divider_fill, width=1)

    footer_y = 1244
    col_font = _load_font("regular", 17)
    short_label = label if len(label) <= 14 else label[:13].rstrip()
    draw.text((margin_x, footer_y + 6), f"{handle}  ·  {short_label}", font=col_font, fill=muted_fill)

    if total_slides > 1:
        mid_y = footer_y + 16
        if progress_style == "bar":
            bar_w = 136
            bx0 = (CARD_WIDTH - bar_w) // 2
            draw.rounded_rectangle((bx0, mid_y - 3, bx0 + bar_w, mid_y + 3), radius=3, fill=(*muted_fill[:3], 95))
            fill_w = max(18, int(bar_w * (current_idx / total_slides)))
            draw.rounded_rectangle((bx0, mid_y - 3, bx0 + fill_w, mid_y + 3), radius=3, fill=(*accent, 255))
        else:
            dot_gap = 18
            total_w = (total_slides - 1) * dot_gap + 22
            cx = (CARD_WIDTH - total_w) // 2
            for idx in range(1, total_slides + 1):
                if idx == current_idx:
                    draw.rounded_rectangle((cx, mid_y - 4, cx + 22, mid_y + 4), radius=4, fill=(*accent, 255))
                    cx += 28
                else:
                    draw.ellipse((cx, mid_y - 4, cx + 8, mid_y + 4), fill=(*muted_fill[:3], 130))
                    cx += dot_gap

        badge_str = (
            f"{current_idx:02d} / {total_slides:02d}  ·  SWIPE →"
            if current_idx < total_slides
            else f"{current_idx:02d} / {total_slides:02d}"
        )
        canvas, _ = _draw_pill(
            canvas,
            badge_str,
            CARD_WIDTH - margin_x,
            footer_y,
            bg_fill=badge_bg,
            text_fill=badge_text,
            outline_fill=badge_outline,
            align_right=True,
            font_size=14,
            pad_x=15,
            height=34,
        )
    return canvas


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
    y = start_y
    for line in lines:
        draw_x = (CARD_WIDTH - _text_width(draw, line, font)) / 2 if centered else float(x)
        draw.text((draw_x, y), line, font=font, fill=fill)
        y += line_step
    return y


def _fit_headline_lines(
    draw: ImageDraw.ImageDraw,
    headline: str,
    width: int,
    base_size: int,
    small_size: int,
    font_weight: str = "serif_bold",
    max_lines: int = 4,
) -> tuple[list[str], ImageFont.ImageFont]:
    font = _load_font(font_weight, base_size)
    lines = _wrap_text(draw, headline, font, width, max_lines=max_lines)
    if len(lines) >= max_lines:
        font = _load_font(font_weight, small_size)
        lines = _wrap_text(draw, headline, font, width, max_lines=max_lines)
    return lines, font


def _short_cover_deck(blocks: list[str], max_chars: int = 165) -> tuple[str, int]:
    if not blocks:
        return "", 0
    lead = blocks[0].strip()
    if len(lead) <= max_chars:
        return lead, 1
    first_sentence = re.split(r"(?<=[.!?])\s+", lead)[0].strip()
    if 35 <= len(first_sentence) <= max_chars + 15:
        consumed = 1 if len(first_sentence) >= len(lead) - 20 else 0
        return first_sentence, consumed
    clipped = lead[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return clipped, 1


def _build_abstract_plate(width: int, height: int, palette: dict, seed: int, dark: bool = True) -> Image.Image:
    accent, wash, deep, highlight = palette["accent"], palette["wash"], palette["deep"], palette["highlight"]
    rng = random.Random(seed)
    base_color = deep if dark else palette["buff_surface"]
    plate = Image.new("RGBA", (width, height), (*base_color, 255))
    art = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ad = ImageDraw.Draw(art)

    shift = rng.uniform(0.0, math.tau)
    wave_pts = [
        (
            x,
            int(
                height * 0.48
                + height * 0.14 * math.sin((x / max(1, width)) * math.pi * 1.5 + shift)
                + height * 0.06 * math.cos((x / max(1, width)) * math.pi * 2.8 - shift)
            ),
        )
        for x in range(0, width + 24, 24)
    ]
    ad.polygon(wave_pts + [(width, height), (0, height)], fill=(*wash, 215 if dark else 175))
    ad.ellipse((int(width * rng.uniform(0.15, 0.45)), int(height * 0.10), int(width * 1.05), int(height * 1.15)), fill=(*highlight, 150))
    ad.ellipse((-int(width * 0.15), -int(height * 0.15), int(width * 0.55), int(height * 0.65)), fill=(*accent, 130))
    plate = Image.alpha_composite(plate, art.filter(ImageFilter.GaussianBlur(radius=62)))

    ring_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring_layer)
    cx, cy = int(width * rng.uniform(0.58, 0.80)), int(height * rng.uniform(0.32, 0.60))
    stroke = (255, 255, 255, 38) if dark else (*deep, 38)
    for r in (100, 175, 250, 325):
        rd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=stroke, width=2)
    plate = Image.alpha_composite(plate, ring_layer)
    return _apply_analog_grain(plate, strength=0.30)


def _ideal_photo_box(
    margin_x: int,
    width: int,
    avail_top: int,
    avail_bottom: int,
    source_images: list[dict],
) -> tuple[int, int, int, int]:
    """Compute an aspect-aware photo frame inside [avail_top, avail_bottom] to avoid side-clipping."""
    avail_h = max(320, avail_bottom - avail_top)
    if source_images:
        aspect = _analyze_image(source_images[0]["image"])["aspect"]
        ideal_h = int(width / max(1.20, min(1.85, aspect)))
        frame_h = max(350, min(avail_h, ideal_h))
        top = avail_top + max(0, (avail_h - frame_h) // 2)
        return (margin_x, top, margin_x + width, top + frame_h)
    return (margin_x, avail_top, margin_x + width, avail_bottom)


# ---------------------------------------------------------------------------
# 6 Dynamic Cover Layouts Driven by Live Scraped Palette + Per-Post Spec
# ---------------------------------------------------------------------------


def _render_cover(
    topic: dict,
    palette: dict,
    spec: dict,
    seed: int,
    handle: str,
    source_images: list[dict],
    deck: str,
    total_slides: int,
) -> Image.Image:
    layout = spec["layout"]
    accent, wash, deep, highlight = palette["accent"], palette["wash"], palette["deep"], palette["highlight"]
    dark = spec["dark_mode"]
    bg_rgb = palette["dark_surface"] if dark else (palette["buff_surface"] if layout == "riso_zine" else palette["light_surface"])
    primary_fill = (*LIGHT_PRIMARY, 255) if dark else (*INK_PRIMARY, 255)
    secondary_fill = (*LIGHT_SECONDARY, 245) if dark else (*INK_SECONDARY, 245)
    muted_fill = (*LIGHT_MUTED, 235) if dark else (*INK_MUTED, 235)
    rule_fill = (255, 255, 255, 32) if dark else (20, 22, 24, 30)
    badge_bg = (24, 28, 36, 232) if dark else (*deep, 238)
    badge_outline = (*accent, 180) if dark else None
    topic_tag = (_strip_invisible(topic.get("topic_tag") or "") or "TECH BRIEF").upper()
    headline = _strip_invisible(topic["text"])
    hero_img = source_images[0]["image"] if source_images else None

    if layout == "full_bleed_hero":
        if hero_img is not None:
            canvas = _fit_photo_panel(hero_img, CARD_WIDTH, CARD_HEIGHT, matte_rgb=deep, crop_focus=(0.5, 0.35), allow_contain_for_wide=True)
        else:
            canvas = _build_abstract_plate(CARD_WIDTH, CARD_HEIGHT, palette, seed, dark=True)
            canvas = _apply_motif(canvas, "dot_grid", palette, True, seed)

        grad_top = Image.linear_gradient("L").resize((1, 180), Image.Resampling.BILINEAR).point(lambda p: int(185 * (1.0 - p / 255.0)))
        top_alpha = Image.new("L", canvas.size, 0)
        top_alpha.paste(grad_top.resize((CARD_WIDTH, 180), Image.Resampling.NEAREST), (0, 0))
        top_ov = Image.new("RGBA", canvas.size, (*palette["dark_surface"], 255))
        top_ov.putalpha(top_alpha)
        canvas = Image.alpha_composite(canvas, top_ov)
        canvas = _apply_linear_scrim(canvas, 450, 1225, deep, start_alpha=0, end_alpha=244)
        canvas = _draw_masthead(canvas, topic, handle, accent, (*LIGHT_PRIMARY, 250), (*LIGHT_MUTED, 235), frosted=True)

        margin_x = 68
        content_w = CARD_WIDTH - margin_x * 2
        draw = ImageDraw.Draw(canvas)
        h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 60, 50, font_weight=spec["headline_font"], max_lines=4)
        h_step = int(h_font.size * 1.13)
        deck_font = _load_font("regular", 27)
        deck_lines = _wrap_text(draw, deck, deck_font, content_w - 20, max_lines=2) if deck else []
        stack_h = 44 + len(h_lines) * h_step + 22 + (len(deck_lines) * 36 + 14 if deck_lines else 0)
        stack_top = max(510, 1188 - stack_h)

        canvas = _draw_kicker(canvas, topic_tag, margin_x, stack_top, {**spec, "dark_mode": True}, palette)
        draw = ImageDraw.Draw(canvas)
        h_end = _draw_text_lines(draw, h_lines, margin_x, stack_top + 44, h_step, h_font, (*LIGHT_PRIMARY, 255))
        draw.rectangle((margin_x, h_end + 12, margin_x + 76, h_end + 16), fill=(*accent, 255))
        if deck_lines:
            _draw_text_lines(draw, deck_lines, margin_x, h_end + 28, 36, deck_font, (*LIGHT_SECONDARY, 246))

        canvas = _draw_progress_footer(
            canvas, 1, total_slides, handle, "VISUAL BRIEF", accent, (*LIGHT_MUTED, 235),
            (255, 255, 255, 42), (16, 20, 26, 226), (*LIGHT_PRIMARY, 252), (*accent, 190),
            progress_style=spec["progress_style"],
        )
        return _apply_analog_grain(canvas, strength=0.14)

    # Non-bleed layouts start from custom hue-tinted surface + per-post motif.
    canvas = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*bg_rgb, 255))
    if layout == "duotone_frame":
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((140, 110, 960, 740), fill=(*wash, 125))
        gd.ellipse((540, 720, 1220, 1460), fill=(*accent, 95))
        gd.ellipse((-180, 780, 480, 1420), fill=(*highlight, 80))
        canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(radius=130)))
    canvas = _apply_motif(canvas, spec["motif"], palette, dark, seed, hero_photo=hero_img)

    if layout == "duotone_frame":
        ImageDraw.Draw(canvas).rounded_rectangle((30, 28, CARD_WIDTH - 30, CARD_HEIGHT - 28), radius=14, outline=(255, 255, 255, 28), width=2)

    if layout == "editorial_sidebar":
        # Bold Swiss vertical accent spine along the left edge.
        ImageDraw.Draw(canvas).rectangle((0, 0, 20, CARD_HEIGHT), fill=(*accent, 255))
        margin_x = 76
    else:
        margin_x = 72 if layout == "duotone_frame" else 68

    content_w = CARD_WIDTH - margin_x - 68
    canvas = _draw_masthead(
        canvas, topic, handle, accent, primary_fill, muted_fill,
        rule_fill=None if layout == "riso_zine" else rule_fill,
        margin_x=margin_x,
    )
    if layout == "riso_zine":
        ImageDraw.Draw(canvas).line((margin_x, 102, CARD_WIDTH - 68, 102), fill=(*INK_PRIMARY, 215), width=4)

    if layout in {"split_top_photo", "duotone_frame"}:
        photo_box = (margin_x, 120, margin_x + content_w, 646)
        if hero_img is not None:
            photo_in = ImageEnhance.Contrast(_flatten_to_rgb(hero_img, deep)).enhance(1.06) if layout == "duotone_frame" else hero_img
            canvas = _paste_photo_frame(
                canvas, photo_in, photo_box, palette, frame_style=spec["frame_style"],
                dark_mode=dark, credit_text=source_images[0]["credit"],
            )
        else:
            plate = _build_abstract_plate(content_w, photo_box[3] - photo_box[1], palette, seed, dark=dark)
            mask = Image.new("L", plate.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, *plate.size), radius=18, fill=255)
            canvas.paste(plate, (photo_box[0], photo_box[1]), mask)

        kicker_y = 632 if layout == "split_top_photo" else 666
        canvas = _draw_kicker(canvas, topic_tag, margin_x + (18 if layout == "split_top_photo" else 0), kicker_y, spec, palette)
        draw = ImageDraw.Draw(canvas)
        h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 56, 48, font_weight=spec["headline_font"], max_lines=4)
        h_step = int(h_font.size * 1.14)
        h_end = _draw_text_lines(draw, h_lines, margin_x, kicker_y + 46, h_step, h_font, primary_fill)
        draw.rectangle((margin_x, h_end + 15, margin_x + 82, h_end + 19), fill=(*accent, 255))
        if deck:
            deck_font = _load_font("regular", 27)
            deck_lines = _wrap_text(draw, deck, deck_font, content_w, max_lines=3)
            avail = max(1, (1195 - (h_end + 35)) // 37)
            _draw_text_lines(draw, deck_lines[:avail], margin_x, h_end + 35, 37, deck_font, secondary_fill)
        footer_label = "NOIR EDITION" if layout == "duotone_frame" else "DAILY BRIEF"
    else:
        # split_bottom_photo, editorial_sidebar, riso_zine -> headline-first above framed photo
        canvas = _draw_kicker(canvas, topic_tag, margin_x, 122, spec, palette)
        draw = ImageDraw.Draw(canvas)
        h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 56, 48, font_weight=spec["headline_font"], max_lines=4)
        h_step = int(h_font.size * 1.13)
        h_end = _draw_text_lines(draw, h_lines, margin_x, 168, h_step, h_font, primary_fill)
        if layout != "riso_zine":
            draw.rectangle((margin_x, h_end + 14, margin_x + 76, h_end + 18), fill=(*accent, 255))
        y_cursor = h_end + (22 if layout == "riso_zine" else 32)
        if deck:
            deck_font = _load_font("regular", 26)
            deck_lines = _wrap_text(draw, deck, deck_font, content_w, max_lines=2)
            y_cursor = _draw_text_lines(draw, deck_lines, margin_x, y_cursor, 35, deck_font, secondary_fill) + 12

        avail_top = max(445, min(675, y_cursor + 12))
        frame_w = content_w - (10 if spec["frame_style"] == "offset_block" else 0)
        photo_box = _ideal_photo_box(margin_x, frame_w, avail_top, 1192, source_images)
        if hero_img is not None:
            canvas = _paste_photo_frame(
                canvas, hero_img, photo_box, palette, frame_style=spec["frame_style"],
                dark_mode=dark, credit_text=source_images[0]["credit"],
            )
        else:
            plate = _build_abstract_plate(photo_box[2] - photo_box[0], photo_box[3] - photo_box[1], palette, seed, dark=not (layout == "riso_zine"))
            if spec["frame_style"] == "offset_block":
                canvas = _composite_rounded_box(
                    canvas, (photo_box[0] + 10, photo_box[1] + 10, photo_box[2] + 10, photo_box[3] + 10), 12, (*accent, 235)
                )
            mask = Image.new("L", plate.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, *plate.size), radius=16, fill=255)
            canvas.paste(plate, (photo_box[0], photo_box[1]), mask)
        footer_label = "PRINT ZINE" if layout == "riso_zine" else ("EDITION" if layout == "editorial_sidebar" else "DISPATCH")

    canvas = _draw_progress_footer(
        canvas, 1, total_slides, handle, footer_label, accent, muted_fill,
        (*INK_PRIMARY, 55) if layout == "riso_zine" else rule_fill,
        (*INK_PRIMARY, 232) if layout == "riso_zine" else badge_bg,
        (*palette["buff_surface"], 255) if layout == "riso_zine" else (*LIGHT_PRIMARY, 252),
        None if layout == "riso_zine" else badge_outline,
        margin_x=margin_x,
        progress_style=spec["progress_style"],
    )
    return _apply_analog_grain(canvas, strength=0.26 if layout == "riso_zine" else 0.16)


# ---------------------------------------------------------------------------
# Dynamic Inner Slides (Photo Feature / Numbered Cards / Pull Quote / Closing)
# ---------------------------------------------------------------------------


def _create_inner_surface(
    topic: dict,
    palette: dict,
    spec: dict,
    seed: int,
    handle: str,
    hero_photo: Image.Image | None = None,
) -> tuple[Image.Image, dict]:
    accent, wash, deep = palette["accent"], palette["wash"], palette["deep"]
    dark = spec["dark_mode"]
    layout = spec["layout"]
    bg_rgb = palette["dark_surface"] if dark else (palette["buff_surface"] if layout == "riso_zine" else palette["light_surface"])
    canvas = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*bg_rgb, 255))

    if dark:
        if hero_photo is not None:
            ambient = ImageOps.fit(_flatten_to_rgb(hero_photo, bg_rgb), canvas.size, method=Image.Resampling.BILINEAR)
            ambient = ImageEnhance.Brightness(ambient.filter(ImageFilter.GaussianBlur(radius=85))).enhance(0.22).convert("RGBA")
            canvas = Image.blend(canvas, ambient, alpha=0.62)
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((540, 820, 1280, 1520), fill=(*wash, 95))
        gd.ellipse((-220, 900, 440, 1460), fill=(*accent, 75))
        canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(radius=140)))
    elif hero_photo is not None and layout != "riso_zine":
        ambient = ImageOps.fit(_flatten_to_rgb(hero_photo, bg_rgb), canvas.size, method=Image.Resampling.BILINEAR)
        ambient = ambient.filter(ImageFilter.GaussianBlur(radius=95))
        soft = Image.blend(ambient, Image.new("RGB", canvas.size, bg_rgb), alpha=0.87).convert("RGBA")
        canvas = Image.blend(canvas, soft, alpha=0.68)

    if spec["motif"] in {"dot_grid", "arch_lines"}:
        canvas = _apply_motif(canvas, spec["motif"], palette, dark, seed)
    if layout == "duotone_frame":
        ImageDraw.Draw(canvas).rounded_rectangle((30, 28, CARD_WIDTH - 30, CARD_HEIGHT - 28), radius=14, outline=(255, 255, 255, 28), width=2)
    margin_x = 76 if layout == "editorial_sidebar" else (72 if layout == "duotone_frame" else 68)
    if layout == "editorial_sidebar":
        ImageDraw.Draw(canvas).rectangle((0, 0, 20, CARD_HEIGHT), fill=(*accent, 255))

    primary = (*LIGHT_PRIMARY, 255) if dark else (*INK_PRIMARY, 255)
    secondary = (*LIGHT_SECONDARY, 245) if dark else (*INK_SECONDARY, 245)
    muted = (*LIGHT_MUTED, 235) if dark else (*INK_MUTED, 235)
    divider = (255, 255, 255, 34) if dark else ((*INK_PRIMARY, 55) if layout == "riso_zine" else (20, 22, 24, 30))

    canvas = _draw_masthead(
        canvas, topic, handle, accent, primary, muted,
        rule_fill=None if layout == "riso_zine" else divider,
        margin_x=margin_x,
    )
    if layout == "riso_zine":
        ImageDraw.Draw(canvas).line((margin_x, 102, CARD_WIDTH - 68, 102), fill=(*INK_PRIMARY, 215), width=4)

    return canvas, {
        "dark": dark,
        "margin_x": margin_x,
        "bg_rgb": bg_rgb,
        "primary": primary,
        "secondary": secondary,
        "muted": muted,
        "accent": (*accent, 255),
        "panel_bg": (28, 32, 42, 222) if dark else ((236, 230, 216, 236) if layout == "riso_zine" else (255, 255, 255, 218)),
        "panel_outline": (255, 255, 255, 34) if dark else ((*INK_PRIMARY, 185) if layout == "riso_zine" else (20, 22, 24, 28)),
        "panel_accent_outline": (*accent, 190),
        "badge_bg": (24, 28, 36, 232) if dark else ((*INK_PRIMARY, 232) if layout == "riso_zine" else (*deep, 238)),
        "badge_text": (*palette["buff_surface"], 255) if layout == "riso_zine" else (*LIGHT_PRIMARY, 252),
        "badge_outline": (*accent, 175) if dark else None,
        "divider": divider,
        "grain": 0.24 if layout == "riso_zine" else 0.16,
    }


def _draw_inner_header(canvas: Image.Image, topic: dict, section_title: str, style: dict, spec: dict) -> tuple[Image.Image, int]:
    margin_x = style["margin_x"]
    content_w = CARD_WIDTH - margin_x - 68
    draw = ImageDraw.Draw(canvas)
    kicker_font = _load_font("regular", 17)
    kicker = _wrap_text(
        draw, f"{_strip_invisible(topic.get('source', 'NEWS')).upper()}  ·  {_strip_invisible(topic['text'])}",
        kicker_font, content_w, max_lines=1,
    )
    if kicker:
        draw.text((margin_x, 118), kicker[0], font=kicker_font, fill=style["muted"])
    title_weight = "display" if spec["headline_font"] == "display" else "serif_bold"
    title_font = _load_font(title_weight, 38)
    draw.text((margin_x, 148), section_title, font=title_font, fill=style["primary"])
    draw.rectangle((margin_x, 200, margin_x + 76, 204), fill=style["accent"])
    return canvas, 226


def _extract_stat_token(blocks: list[str]) -> str | None:
    for block in blocks:
        match = _METRIC_PATTERN.search(block)
        if match:
            token = " ".join(match.group(0).split())
            if len(token) <= 18:
                return token
    return None


def _render_fact_grid_slide(
    topic: dict,
    palette: dict,
    spec: dict,
    seed: int,
    handle: str,
    section_title: str,
    blocks: list[str],
    slide_idx: int,
    total_slides: int,
    hero_photo: Image.Image | None,
) -> Image.Image:
    accent = palette["accent"]
    canvas, style = _create_inner_surface(topic, palette, spec, seed, handle, hero_photo=hero_photo)
    margin_x = style["margin_x"]
    content_w = CARD_WIDTH - margin_x - 68
    canvas, cursor_y = _draw_inner_header(canvas, topic, section_title, style, spec)

    stat_token = _extract_stat_token(blocks)
    if stat_token:
        canvas, _ = _draw_pill(
            canvas, f"KEY FIGURE  ·  {stat_token.upper()}", CARD_WIDTH - 68, 152,
            bg_fill=(*accent, 34), text_fill=style["accent"], outline_fill=style["accent"],
            align_right=True, font_size=14, pad_x=14, height=30,
        )

    probe = ImageDraw.Draw(canvas)
    body_font = _load_font("regular", 28)
    line_step = 40
    num_font = _load_font("mono", 18)
    max_y = 1185
    badge_style = spec["card_badge_style"]

    measured: list[tuple[list[str], int]] = []
    temp_y = cursor_y
    text_offset = 44 if badge_style == "accent_rail" else 118
    text_w = content_w - text_offset
    for item_idx, block in enumerate(blocks[:3], start=1):
        lines = _wrap_text(probe, block, body_font, text_w, max_lines=6)
        box_h = max(136, len(lines) * line_step + 58)
        if temp_y + box_h > max_y:
            if item_idx == 1:
                avail_lines = max(2, (max_y - temp_y - 58) // line_step)
                lines = _wrap_text(probe, block, body_font, text_w, max_lines=avail_lines)
                box_h = len(lines) * line_step + 58
            else:
                break
        measured.append((lines, box_h))
        temp_y += box_h + 22

    total_h = sum(bh for _, bh in measured)
    slack = max(0, max_y - cursor_y - total_h)
    gap = min(44, max(22, slack // max(1, len(measured) + 1))) if len(measured) > 1 else 22
    if measured:
        used = total_h + gap * (len(measured) - 1)
        cursor_y += min(95, max(0, (max_y - cursor_y - used) // 3))

    for item_idx, (lines, box_h) in enumerate(measured, start=1):
        canvas = _composite_rounded_box(
            canvas, (margin_x, cursor_y, CARD_WIDTH - 68, cursor_y + box_h),
            radius=18, fill=style["panel_bg"], outline=style["panel_outline"],
            width=2 if spec["layout"] == "riso_zine" else 1,
        )
        num_str = f"{item_idx:02d}"
        if badge_style == "accent_rail":
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((margin_x + 2, cursor_y + 18, margin_x + 8, cursor_y + box_h - 18), fill=style["accent"])
            _draw_text_lines(draw, lines, margin_x + 28, cursor_y + 28, line_step, body_font, style["primary"])
        else:
            bx, by = margin_x + 24, cursor_y + 28
            if badge_style == "outline_ring":
                canvas = _composite_rounded_box(
                    canvas, (bx, by, bx + 48, by + 42), radius=21, fill=(*accent, 28), outline=style["accent"], width=2
                )
                num_fill = style["accent"]
            else:
                canvas = _composite_rounded_box(canvas, (bx, by, bx + 48, by + 42), radius=11, fill=(*accent, 240))
                num_fill = (255, 255, 255, 255)
            draw = ImageDraw.Draw(canvas)
            nw = _text_width(draw, num_str, num_font)
            draw.text((bx + (48 - nw) / 2, by + 10), num_str, font=num_font, fill=num_fill)
            _draw_text_lines(draw, lines, bx + 68, cursor_y + 28, line_step, body_font, style["primary"])
        cursor_y += box_h + gap

    canvas = _draw_progress_footer(
        canvas, slide_idx, total_slides, handle, "KEY FACTS", accent, style["muted"], style["divider"],
        style["badge_bg"], style["badge_text"], style["badge_outline"], margin_x=margin_x,
        progress_style=spec["progress_style"],
    )
    return _apply_analog_grain(canvas, strength=style["grain"])


def _render_photo_feature_slide(
    topic: dict,
    palette: dict,
    spec: dict,
    seed: int,
    handle: str,
    section_title: str,
    blocks: list[str],
    slide_idx: int,
    total_slides: int,
    feature_photo: dict,
    hero_photo: Image.Image | None,
    photo_on_bottom: bool = False,
) -> Image.Image:
    accent = palette["accent"]
    canvas, style = _create_inner_surface(topic, palette, spec, seed, handle, hero_photo=hero_photo)
    margin_x = style["margin_x"]
    content_w = CARD_WIDTH - margin_x - 68
    canvas, cursor_y = _draw_inner_header(canvas, topic, section_title, style, spec)

    body_font = _load_font("regular", 27)
    line_step = 37
    photo_h = 435

    def draw_cards(start_y: int, limit_y: int) -> tuple[Image.Image, int]:
        nonlocal canvas
        y = start_y
        probe = ImageDraw.Draw(canvas)
        for item_idx, block in enumerate(blocks[:2], start=1):
            lines = _wrap_text(probe, block, body_font, content_w - 56, max_lines=4)
            box_h = len(lines) * line_step + 44
            if y + box_h > limit_y:
                if item_idx == 1:
                    avail = max(2, (limit_y - y - 44) // line_step)
                    lines = _wrap_text(probe, block, body_font, content_w - 56, max_lines=avail)
                    box_h = len(lines) * line_step + 44
                else:
                    break
            canvas = _composite_rounded_box(
                canvas, (margin_x, y, CARD_WIDTH - 68, y + box_h),
                radius=16, fill=style["panel_bg"], outline=style["panel_outline"], width=1,
            )
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((margin_x + 2, y + 18, margin_x + 6, y + box_h - 18), fill=style["accent"])
            _draw_text_lines(draw, lines, margin_x + 28, y + 22, line_step, body_font, style["primary"])
            probe = draw
            y += box_h + 16
        return canvas, y

    if photo_on_bottom:
        canvas, cards_end = draw_cards(cursor_y, 725)
        p_top = max(cards_end + 10, 1188 - photo_h)
        photo_box = (margin_x, p_top, CARD_WIDTH - 68, min(1192, p_top + photo_h))
        canvas = _paste_photo_frame(
            canvas, feature_photo["image"], photo_box, palette, frame_style=spec["frame_style"],
            dark_mode=style["dark"], credit_text=feature_photo["credit"],
        )
    else:
        photo_box = (margin_x, cursor_y, CARD_WIDTH - 68, cursor_y + photo_h)
        canvas = _paste_photo_frame(
            canvas, feature_photo["image"], photo_box, palette, frame_style=spec["frame_style"],
            dark_mode=style["dark"], credit_text=feature_photo["credit"],
        )
        canvas, _ = draw_cards(photo_box[3] + 24, 1190)

    canvas = _draw_progress_footer(
        canvas, slide_idx, total_slides, handle, "VISUAL CONTEXT", accent, style["muted"], style["divider"],
        style["badge_bg"], style["badge_text"], style["badge_outline"], margin_x=margin_x,
        progress_style=spec["progress_style"],
    )
    return _apply_analog_grain(canvas, strength=style["grain"])


def _render_pull_quote_slide(
    topic: dict,
    palette: dict,
    spec: dict,
    seed: int,
    handle: str,
    section_title: str,
    blocks: list[str],
    slide_idx: int,
    total_slides: int,
    hero_photo: Image.Image | None,
) -> Image.Image:
    accent = palette["accent"]
    canvas, style = _create_inner_surface(topic, palette, spec, seed, handle, hero_photo=hero_photo)
    margin_x = style["margin_x"]
    content_w = CARD_WIDTH - margin_x - 68
    canvas, cursor_y = _draw_inner_header(canvas, topic, section_title, style, spec)

    quote_text = blocks[0] if blocks else _strip_invisible(topic["text"])
    extra_text = blocks[1] if len(blocks) > 1 else ""

    draw = ImageDraw.Draw(canvas)
    draw.text((margin_x - 6, cursor_y - 12), "“", font=_load_font("serif_bold", 120), fill=style["accent"])
    q_font = _load_font("serif", 38)
    q_lines = _wrap_text(draw, quote_text, q_font, content_w - 20, max_lines=7)
    if len(q_lines) >= 7:
        q_font = _load_font("serif", 33)
        q_lines = _wrap_text(draw, quote_text, q_font, content_w - 20, max_lines=7)
    q_end = _draw_text_lines(draw, q_lines, margin_x + 12, cursor_y + 78, int(q_font.size * 1.28), q_font, style["primary"])

    if extra_text and q_end + 145 < 1185:
        box_top = q_end + 34
        sub_font = _load_font("regular", 27)
        sub_lines = _wrap_text(draw, extra_text, sub_font, content_w - 60, max_lines=5)
        box_h = len(sub_lines) * 37 + 44
        if box_top + box_h <= 1190:
            canvas = _composite_rounded_box(
                canvas, (margin_x, box_top, CARD_WIDTH - 68, box_top + box_h),
                radius=16, fill=style["panel_bg"], outline=style["panel_outline"], width=1,
            )
            draw = ImageDraw.Draw(canvas)
            _draw_text_lines(draw, sub_lines, margin_x + 28, box_top + 22, 37, sub_font, style["secondary"])

    canvas = _draw_progress_footer(
        canvas, slide_idx, total_slides, handle, "IN DEPTH", accent, style["muted"], style["divider"],
        style["badge_bg"], style["badge_text"], style["badge_outline"], margin_x=margin_x,
        progress_style=spec["progress_style"],
    )
    return _apply_analog_grain(canvas, strength=style["grain"])


def _render_closing_slide(
    topic: dict,
    palette: dict,
    spec: dict,
    seed: int,
    handle: str,
    trailing_blocks: list[str],
    discussion_prompt: str,
    total_slides: int,
    hero_photo: Image.Image | None,
) -> Image.Image:
    accent = palette["accent"]
    canvas, style = _create_inner_surface(topic, palette, spec, seed + 1, handle, hero_photo=hero_photo)
    margin_x = style["margin_x"]
    content_w = CARD_WIDTH - margin_x - 68
    section_title = "KEY TAKEAWAY" if trailing_blocks else "JOIN THE CONVERSATION"
    canvas, cursor_y = _draw_inner_header(canvas, topic, section_title, style, spec)

    draw = ImageDraw.Draw(canvas)
    body_end = cursor_y + 10
    if trailing_blocks:
        takeaway_font = _load_font("regular", 28)
        t_lines = _wrap_text(draw, trailing_blocks[0], takeaway_font, content_w - 56, max_lines=6)
        box_h = len(t_lines) * 39 + 48
        canvas = _composite_rounded_box(
            canvas, (margin_x, cursor_y, CARD_WIDTH - 68, cursor_y + box_h),
            radius=16, fill=style["panel_bg"], outline=style["panel_outline"], width=1,
        )
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((margin_x + 2, cursor_y + 18, margin_x + 6, cursor_y + box_h - 18), fill=style["accent"])
        _draw_text_lines(draw, t_lines, margin_x + 28, cursor_y + 24, 39, takeaway_font, style["primary"])
        body_end = cursor_y + box_h + 26

    inner_x = margin_x + 36
    inner_w = content_w - 72
    q_font = _load_font("display" if spec["headline_font"] == "display" else "serif_bold", 34)
    prompt_text = discussion_prompt.strip() or "What is your take on this development?"
    q_lines = _wrap_text(draw, prompt_text, q_font, inner_w, max_lines=4)
    panel_top = max(380 if not trailing_blocks else 560, min(800, body_end + 18))
    q_end = panel_top + 74 + len(q_lines) * 44
    divider_y = q_end + 28
    panel_bottom = min(1185, divider_y + 124)

    canvas = _composite_rounded_box(
        canvas, (margin_x, panel_top, CARD_WIDTH - 68, panel_bottom),
        radius=20, fill=style["panel_bg"], outline=style["panel_accent_outline"], width=2,
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((inner_x, panel_top + 30), "YOUR TAKE?", font=_load_font("mono", 16), fill=style["accent"])
    _draw_text_lines(draw, q_lines, inner_x, panel_top + 74, 44, q_font, style["primary"])
    draw.line((inner_x, divider_y, CARD_WIDTH - 68 - 36, divider_y), fill=style["divider"], width=1)

    domain = _strip_invisible(topic.get("allowed_host") or "official release").lower()
    draw.text((inner_x, divider_y + 22), f"FULL ARTICLE & DISCUSSION ON THREADS  ·  {handle.upper()}", font=_load_font("semibold", 20), fill=style["primary"])
    draw.text((inner_x, divider_y + 56), f"Tap link in bio for the verified {domain} release.", font=_load_font("regular", 19), fill=style["muted"])

    canvas = _draw_progress_footer(
        canvas, total_slides, total_slides, handle, "END OF BRIEF", accent, style["muted"], style["divider"],
        style["badge_bg"], style["badge_text"], style["badge_outline"], margin_x=margin_x,
        progress_style=spec["progress_style"],
    )
    return _apply_analog_grain(canvas, strength=style["grain"])


def _paginate_inner_blocks(blocks: list[str], max_mid_slides: int, has_extra_photos: int = 0) -> tuple[list[list[str]], list[str]]:
    if not blocks or max_mid_slides <= 0:
        return [], blocks[:1]
    mid_pages: list[list[str]] = []
    idx = 0
    while idx < len(blocks) and len(mid_pages) < max_mid_slides:
        slide_num = len(mid_pages) + 1
        cap = 2 if slide_num <= has_extra_photos else (3 if len(blocks) - idx >= 4 else 2)
        if len(blocks) - idx <= 1 and len(mid_pages) >= 1:
            break
        take = min(cap, max(1, len(blocks) - idx))
        mid_pages.append(blocks[idx : idx + take])
        idx += take
    return mid_pages, blocks[idx : idx + 1]


def render_news_card(
    topic: dict,
    output_path: str | Path,
    handle: str = "@thechronobyte",
    theme: str | None = None,
    source_images: list[dict] | list[Image.Image] | None = None,
    source_theme: dict | None = None,
) -> Path:
    """Render a 1080x1350 editorial JPEG card themed dynamically from the source itself."""
    started = time.monotonic()
    coerced_imgs = _coerce_source_images(source_images, topic)
    live_theme = source_theme if source_theme is not None else topic.get("source_theme")
    seed = _topic_seed(topic)
    palette = _resolve_live_palette(coerced_imgs, live_theme, seed)
    spec = _compose_post_template(topic, coerced_imgs, live_theme, seed, explicit_theme=theme)
    blocks = _build_body_blocks(topic, max_blocks=4, split_long=True, target_chars=210)
    deck, _ = _short_cover_deck(blocks, max_chars=165)

    LOGGER.info(
        "[4/6 Card] Rendering %dx%d JPEG | layout=%s (%s) | palette=%s | dark=%s | font=%s | frame=%s | motif=%s | photos=%d",
        CARD_WIDTH, CARD_HEIGHT, spec["layout"], spec["mode"], palette["origin"],
        spec["dark_mode"], spec["headline_font"], spec["frame_style"], spec["motif"], len(coerced_imgs),
    )

    canvas = _render_cover(topic, palette, spec, seed, handle, coerced_imgs, deck, total_slides=1)
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(dest, format="JPEG", quality=95, optimize=True)
    LOGGER.info("[4/6 Card] Saved JPEG %s (%.1f KB, %.2fs)", dest, dest.stat().st_size / 1024.0, time.monotonic() - started)
    return dest


def render_news_carousel(
    topic: dict,
    output_dir: str | Path,
    handle: str = "@thechronobyte",
    theme: str | None = None,
    max_slides: int = 5,
    stem: str = "card",
    discussion_prompt: str | None = None,
    source_images: list[dict] | list[Image.Image] | None = None,
    source_theme: dict | None = None,
) -> list[Path]:
    """Render a dynamic multi-slide (2-5 cards) 1080x1350 Instagram carousel themed from the source."""
    if max_slides < 2:
        return [
            render_news_card(
                topic, Path(output_dir) / f"{stem}-01.jpg",
                handle=handle, theme=theme, source_images=source_images, source_theme=source_theme,
            )
        ]

    started = time.monotonic()
    coerced_imgs = _coerce_source_images(source_images, topic)
    live_theme = source_theme if source_theme is not None else topic.get("source_theme")
    seed = _topic_seed(topic)
    palette = _resolve_live_palette(coerced_imgs, live_theme, seed)
    spec = _compose_post_template(topic, coerced_imgs, live_theme, seed, explicit_theme=theme)

    all_blocks = _build_body_blocks(topic, max_blocks=14, split_long=True, target_chars=230)
    deck, consumed_cover = _short_cover_deck(all_blocks, max_chars=165)
    remaining = all_blocks[consumed_cover:]
    extra_photos = coerced_imgs[1:]
    mid_pages, trailing = _paginate_inner_blocks(remaining, max_mid_slides=max(0, max_slides - 2), has_extra_photos=len(extra_photos))
    total_slides = 2 + len(mid_pages)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info(
        "[4/6 Card] Rendering %d-slide %dx%d carousel | layout=%s (%s) | palette=%s | dark=%s | "
        "font=%s | frame=%s | kicker=%s | motif=%s | photos=%d | blocks=%d",
        total_slides, CARD_WIDTH, CARD_HEIGHT, spec["layout"], spec["mode"], palette["origin"],
        spec["dark_mode"], spec["headline_font"], spec["frame_style"], spec["kicker_style"],
        spec["motif"], len(coerced_imgs), len(all_blocks),
    )

    saved_paths: list[Path] = []
    prompt_text = discussion_prompt or str(topic.get("discussion_prompt") or "")
    hero_photo = coerced_imgs[0]["image"] if coerced_imgs else None

    cover_img = _render_cover(topic, palette, spec, seed, handle, coerced_imgs, deck, total_slides=total_slides)
    slide1_path = out_dir / f"{stem}-01.jpg"
    cover_img.convert("RGB").save(slide1_path, format="JPEG", quality=95, optimize=True)
    saved_paths.append(slide1_path)

    for idx, page_blocks in enumerate(mid_pages, start=2):
        sec_title = _CONTINUATION_SECTIONS[(idx - 2) % len(_CONTINUATION_SECTIONS)]
        extra_idx = idx - 2
        if extra_idx < len(extra_photos):
            slide_img = _render_photo_feature_slide(
                topic, palette, spec, seed + idx, handle, sec_title, page_blocks,
                slide_idx=idx, total_slides=total_slides, feature_photo=extra_photos[extra_idx],
                hero_photo=hero_photo, photo_on_bottom=(extra_idx % 2 == 1) ^ spec["flip_extra_photo"],
            )
        elif idx % 2 == 1 and len(page_blocks) <= 2:
            slide_img = _render_pull_quote_slide(
                topic, palette, spec, seed + idx, handle, "HIGHLIGHT", page_blocks,
                slide_idx=idx, total_slides=total_slides, hero_photo=hero_photo,
            )
        else:
            slide_img = _render_fact_grid_slide(
                topic, palette, spec, seed + idx, handle, sec_title, page_blocks,
                slide_idx=idx, total_slides=total_slides, hero_photo=hero_photo,
            )
        slide_path = out_dir / f"{stem}-{idx:02d}.jpg"
        slide_img.convert("RGB").save(slide_path, format="JPEG", quality=95, optimize=True)
        saved_paths.append(slide_path)

    closing_img = _render_closing_slide(
        topic, palette, spec, seed + total_slides, handle, trailing, prompt_text,
        total_slides=total_slides, hero_photo=hero_photo,
    )
    closing_path = out_dir / f"{stem}-{total_slides:02d}.jpg"
    closing_img.convert("RGB").save(closing_path, format="JPEG", quality=95, optimize=True)
    saved_paths.append(closing_path)

    sizes_kb = [round(p.stat().st_size / 1024.0, 1) for p in saved_paths]
    LOGGER.info(
        "[4/6 Card] Saved %d carousel JPEG slides to %s (sizes_kb=%s, total=%.1f KB, %.2fs)",
        len(saved_paths), out_dir, sizes_kb, sum(sizes_kb), time.monotonic() - started,
    )
    return saved_paths
