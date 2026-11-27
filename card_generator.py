"""Generate dynamic 1080x1350 (4:5) editorial Instagram news cards & carousels."""

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

PAPER_CREAM = (245, 242, 234)
PAPER_BUFF = (238, 231, 217)
NOIR_INK = (16, 18, 24)
INK_PRIMARY = (20, 22, 26)
INK_SECONDARY = (48, 52, 58)
INK_MUTED = (112, 110, 104)
LIGHT_PRIMARY = (246, 244, 238)
LIGHT_SECONDARY = (212, 210, 204)
LIGHT_MUTED = (154, 154, 150)

CARD_THEMES = (
    "full_bleed_hero",
    "split_editorial",
    "framed_dispatch",
    "duotone_cinema",
    "riso_kinetic",
)
_THEME_ALIASES = {
    "framed_gallery": "framed_dispatch",
    "dark_duotone": "duotone_cinema",
    "riso_poster": "riso_kinetic",
    "editorial_horizon": "split_editorial",
}

# Per-publisher curated print/editorial palettes: (accent, wash, deep_ink, warm_highlight).
SOURCE_PALETTES = {
    "OpenAI": (
        ((16, 163, 127), (64, 142, 128), (16, 46, 44), (222, 168, 92)),
        ((20, 184, 146), (78, 128, 156), (18, 36, 58), (228, 154, 96)),
    ),
    "Anthropic": (
        ((212, 108, 72), (176, 118, 92), (48, 26, 22), (234, 182, 124)),
        ((198, 96, 62), (128, 98, 86), (34, 24, 22), (228, 164, 104)),
    ),
    "NVIDIA": (
        ((118, 185, 0), (76, 128, 52), (18, 40, 16), (216, 198, 88)),
        ((132, 206, 24), (58, 122, 108), (14, 34, 38), (196, 180, 84)),
    ),
    "Google AI": (
        ((58, 122, 232), (88, 136, 204), (18, 36, 74), (230, 160, 80)),
        ((66, 133, 244), (72, 154, 148), (20, 48, 62), (224, 170, 96)),
    ),
    "Google DeepMind": (
        ((38, 124, 226), (76, 154, 192), (14, 38, 68), (112, 214, 184)),
        ((64, 142, 240), (96, 118, 198), (22, 32, 72), (226, 168, 92)),
    ),
    "Google Devices": (
        ((66, 133, 244), (110, 154, 214), (24, 42, 72), (236, 174, 88)),
        ((52, 168, 83), (88, 142, 168), (20, 46, 54), (232, 178, 94)),
    ),
    "AMD": (
        ((224, 48, 52), (174, 82, 58), (54, 18, 22), (234, 168, 84)),
        ((232, 62, 66), (126, 68, 82), (38, 18, 28), (218, 146, 86)),
    ),
    "Microsoft Research": (
        ((0, 146, 218), (68, 126, 182), (18, 38, 70), (226, 174, 98)),
        ((18, 164, 232), (86, 142, 140), (18, 46, 58), (216, 154, 90)),
    ),
    "Microsoft": (
        ((0, 120, 212), (76, 142, 196), (18, 38, 68), (234, 178, 86)),
        ((16, 137, 224), (88, 156, 134), (20, 46, 52), (224, 162, 92)),
    ),
    "Apple": (
        ((62, 116, 208), (118, 134, 162), (22, 26, 36), (218, 174, 114)),
        ((94, 112, 142), (138, 144, 158), (26, 28, 34), (204, 176, 132)),
    ),
    "Meta": (
        ((24, 119, 242), (84, 146, 222), (18, 38, 78), (118, 204, 212)),
        ((42, 132, 246), (112, 128, 212), (24, 34, 72), (226, 158, 108)),
    ),
    "Xbox": (
        ((16, 168, 48), (64, 138, 78), (14, 38, 20), (178, 222, 96)),
        ((32, 186, 66), (52, 128, 104), (14, 34, 30), (208, 212, 96)),
    ),
    "PlayStation": (
        ((0, 112, 209), (66, 122, 204), (14, 28, 66), (92, 208, 236)),
        ((28, 126, 228), (104, 102, 198), (20, 24, 62), (222, 152, 102)),
    ),
    "Samsung": (
        ((28, 92, 208), (82, 126, 196), (16, 28, 64), (164, 206, 234)),
        ((48, 112, 224), (96, 138, 176), (20, 36, 56), (224, 176, 108)),
    ),
    "NASA": (
        ((232, 94, 48), (74, 108, 168), (14, 24, 54), (240, 184, 92)),
        ((46, 124, 216), (96, 128, 182), (12, 22, 48), (236, 116, 68)),
    ),
    "Amazon": (
        ((236, 142, 28), (94, 124, 154), (20, 32, 46), (246, 192, 98)),
        ((224, 132, 24), (112, 132, 146), (24, 34, 44), (238, 174, 88)),
    ),
    "AWS": (
        ((234, 138, 32), (76, 118, 158), (18, 30, 48), (118, 194, 218)),
        ((242, 148, 42), (96, 132, 166), (22, 34, 52), (242, 194, 104)),
    ),
    "AWS Machine Learning": (
        ((228, 134, 36), (68, 146, 148), (18, 38, 48), (128, 214, 192)),
        ((42, 158, 146), (92, 134, 168), (20, 36, 54), (238, 164, 72)),
    ),
    "GitHub": (
        ((130, 88, 228), (88, 118, 186), (20, 22, 42), (98, 206, 158)),
        ((46, 168, 102), (96, 112, 178), (18, 24, 38), (168, 136, 236)),
    ),
    "Cloudflare": (
        ((236, 116, 36), (178, 124, 78), (38, 26, 22), (244, 178, 86)),
        ((244, 128, 44), (92, 124, 152), (24, 32, 44), (244, 186, 98)),
    ),
    "Cisco": (
        ((28, 154, 204), (74, 136, 172), (16, 40, 58), (226, 172, 92)),
        ((24, 168, 184), (82, 144, 152), (18, 44, 50), (224, 164, 96)),
    ),
    "Salesforce": (
        ((24, 152, 224), (88, 158, 206), (18, 44, 72), (236, 178, 92)),
        ((32, 164, 214), (78, 148, 166), (18, 46, 58), (224, 166, 96)),
    ),
    "Stripe": (
        ((99, 91, 255), (104, 132, 224), (20, 24, 62), (94, 214, 198)),
        ((82, 104, 242), (82, 162, 186), (18, 32, 58), (234, 164, 108)),
    ),
    "Mozilla": (
        ((234, 78, 52), (176, 98, 84), (44, 20, 22), (240, 178, 88)),
        ((224, 68, 48), (92, 128, 162), (26, 30, 44), (236, 162, 86)),
    ),
    "IBM": (
        ((32, 108, 224), (76, 124, 192), (16, 32, 66), (132, 198, 232)),
        ((46, 122, 234), (92, 142, 178), (20, 38, 60), (218, 174, 104)),
    ),
    "Figma": (
        ((242, 78, 30), (146, 98, 222), (32, 22, 52), (76, 204, 148)),
        ((152, 92, 236), (226, 98, 72), (34, 24, 48), (112, 212, 168)),
    ),
    "Notion": (
        ((224, 76, 58), (136, 128, 118), (32, 30, 28), (228, 174, 104)),
        ((58, 118, 192), (126, 122, 114), (28, 28, 30), (224, 152, 98)),
    ),
    "JPMorganChase": (
        ((38, 108, 172), (92, 128, 164), (18, 32, 52), (214, 174, 102)),
        ((186, 138, 68), (82, 112, 148), (18, 28, 44), (226, 186, 112)),
    ),
    "Comcast": (
        ((42, 124, 216), (96, 134, 186), (18, 34, 62), (232, 166, 84)),
        ((216, 96, 62), (82, 128, 174), (22, 32, 54), (232, 178, 96)),
    ),
}
DEFAULT_PALETTES = (
    ((72, 104, 224), (102, 134, 192), (20, 30, 62), (228, 168, 92)),
    ((26, 156, 138), (84, 134, 156), (18, 38, 48), (226, 164, 92)),
)

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
    """Remove invisible format/control chars and link-hint artifacts."""
    cleaned = re.sub(r"\s*\(\s*opens in a new (?:window|tab)\s*\)", "", text, flags=re.I)
    return " ".join(
        "".join(ch for ch in cleaned if unicodedata.category(ch) not in {"Cs", "Cf"}).split()
    )


def _topic_seed(topic: dict) -> int:
    key = f"{topic.get('published', '')}|{topic.get('source_url', '')}|{topic.get('text', '')}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16)


def _split_long_block(text: str, target_chars: int = 230) -> list[str]:
    """Break long paragraphs at sentence boundaries for scannable card panels."""
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
    """Flatten transparent PNGs/WebPs cleanly over a surface color instead of black."""
    if img.mode == "RGB":
        return img
    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (*bg_rgb, 255))
    return Image.alpha_composite(bg, rgba).convert("RGB")


def _analyze_image(img: Image.Image) -> dict:
    """Inspect source photo aspect ratio and brightness for adaptive layout choice."""
    w, h = img.size
    aspect = w / max(1, h)
    sample = _flatten_to_rgb(img, PAPER_CREAM).resize((32, 32), Image.Resampling.BILINEAR).convert("L")
    luma = ImageStat.Stat(sample).mean[0]
    return {"width": w, "height": h, "aspect": aspect, "luma": luma}


def _fit_photo_panel(
    img: Image.Image,
    target_w: int,
    target_h: int,
    matte_rgb: tuple[int, int, int],
    crop_focus: tuple[float, float] = (0.5, 0.36),
    allow_contain_for_wide: bool = True,
) -> Image.Image:
    """Fit a source photo sharply into target bounds, preserving wide charts via ambient matte."""
    rgb = _flatten_to_rgb(img, matte_rgb)
    src_w, src_h = rgb.size
    src_aspect = src_w / max(1, src_h)
    dst_aspect = target_w / max(1, target_h)

    extreme_ratio = src_aspect > dst_aspect * 1.75 or src_aspect < dst_aspect * 0.50
    if allow_contain_for_wide and extreme_ratio:
        backdrop = ImageOps.fit(rgb, (target_w, target_h), method=Image.Resampling.BILINEAR, centering=(0.5, 0.5))
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius=34))
        backdrop = ImageEnhance.Brightness(backdrop).enhance(0.55)
        pad = 22
        inner_w = max(40, target_w - pad * 2)
        inner_h = max(40, target_h - pad * 2)
        contained = ImageOps.contain(rgb, (inner_w, inner_h), method=Image.Resampling.LANCZOS)
        cw, ch = contained.size
        canvas = backdrop.convert("RGBA")
        inner_rgba = contained.convert("RGBA")
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw, ch), radius=12, fill=255)
        canvas.paste(inner_rgba, ((target_w - cw) // 2, (target_h - ch) // 2), mask)
        return canvas

    fitted = ImageOps.fit(rgb, (target_w, target_h), method=Image.Resampling.LANCZOS, centering=crop_focus)
    return fitted.convert("RGBA")


def _apply_analog_grain(image: Image.Image, strength: float = 0.24) -> Image.Image:
    """Overlay crisp multi-scale analog print/film grain over an RGB/RGBA image."""
    if strength <= 0:
        return image.convert("RGBA")
    w, h = image.size
    base_rgb = image.convert("RGB")
    fine = Image.effect_noise((w, h), 20).convert("RGB")
    med = Image.effect_noise((max(1, w // 2), max(1, h // 2)), 22).resize(
        (w, h), resample=Image.Resampling.BILINEAR
    ).convert("RGB")
    grain = Image.blend(fine, med, alpha=0.35)
    soft = ImageChops.soft_light(base_rgb, grain)
    return Image.blend(base_rgb, soft, alpha=strength).convert("RGBA")


def _apply_linear_scrim(
    canvas: Image.Image,
    start_y: int,
    end_y: int,
    color_rgb: tuple[int, int, int],
    start_alpha: int = 0,
    end_alpha: int = 242,
) -> Image.Image:
    """Composite a smooth vertical gradient scrim using native Pillow gradient ops."""
    if end_y <= start_y:
        return canvas
    grad = Image.linear_gradient("L").resize((1, end_y - start_y), resample=Image.Resampling.BILINEAR)
    if start_alpha != 0 or end_alpha != 255:
        span = end_alpha - start_alpha
        grad = grad.point(lambda p: max(0, min(255, int(start_alpha + (p / 255.0) * span))))
    alpha_band = grad.resize((CARD_WIDTH, end_y - start_y), resample=Image.Resampling.NEAREST)
    full_alpha = Image.new("L", canvas.size, 0)
    full_alpha.paste(alpha_band, (0, start_y))
    if end_y < CARD_HEIGHT and end_alpha > 0:
        ImageDraw.Draw(full_alpha).rectangle((0, end_y, CARD_WIDTH, CARD_HEIGHT), fill=end_alpha)
    overlay = Image.new("RGBA", canvas.size, (*color_rgb, 255))
    overlay.putalpha(full_alpha)
    return Image.alpha_composite(canvas, overlay)


def _apply_dot_grid(
    canvas: Image.Image,
    dot_fill: tuple[int, int, int, int],
    step: int = 28,
    radius: int = 1,
    box: tuple[int, int, int, int] = (0, 0, CARD_WIDTH, CARD_HEIGHT),
) -> Image.Image:
    """Overlay a fine editorial halftone/architectural dot grid."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    for y in range(y0 + step // 2, y1, step):
        for x in range(x0 + step // 2, x1, step):
            ld.ellipse((x - radius, y - radius, x + radius, y + radius), fill=dot_fill)
    return Image.alpha_composite(canvas, layer)


def _composite_rounded_box(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    width: int = 0,
) -> Image.Image:
    """Alpha-composite a rounded rectangle cleanly onto an RGBA canvas."""
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
    font_size: int = 15,
    pad_x: int = 15,
    height: int = 32,
) -> tuple[Image.Image, int]:
    """Draw a compact rounded badge pill and return (canvas, box_width)."""
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


def _paste_photo_frame(
    canvas: Image.Image,
    photo: Image.Image,
    box: tuple[int, int, int, int],
    matte_rgb: tuple[int, int, int],
    radius: int = 18,
    border_fill: tuple[int, int, int, int] | None = (255, 255, 255, 48),
    border_width: int = 2,
    shadow_alpha: int = 85,
    offset_block_fill: tuple[int, int, int, int] | None = None,
    credit_text: str = "",
    crop_focus: tuple[float, float] = (0.5, 0.36),
    allow_contain_for_wide: bool = True,
) -> Image.Image:
    """Place a source photograph cleanly inside a rounded frame with optional shadow & credit."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0

    if offset_block_fill is not None:
        canvas = _composite_rounded_box(
            canvas, (x0 + 10, y0 + 10, x1 + 10, y1 + 10), radius=radius, fill=offset_block_fill
        )
    elif shadow_alpha > 0:
        shadow = Image.new("RGBA", (CARD_WIDTH // 2, CARD_HEIGHT // 2), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (x0 // 2, (y0 + 10) // 2, x1 // 2, (y1 + 12) // 2),
            radius=max(2, radius // 2),
            fill=(0, 0, 0, shadow_alpha),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=14)).resize(
            canvas.size, resample=Image.Resampling.BILINEAR
        )
        canvas = Image.alpha_composite(canvas, shadow)

    fitted = _fit_photo_panel(
        photo, w, h, matte_rgb=matte_rgb, crop_focus=crop_focus, allow_contain_for_wide=allow_contain_for_wide
    )
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
    canvas.paste(fitted, (x0, y0), mask)

    if border_fill is not None and border_width > 0:
        canvas = _composite_rounded_box(
            canvas, box, radius=radius, fill=(0, 0, 0, 0), outline=border_fill, width=border_width
        )
    if credit_text:
        short_credit = credit_text if len(credit_text) <= 28 else credit_text[:25].rstrip() + "…"
        canvas, _ = _draw_pill(
            canvas,
            f"SOURCE · {short_credit}",
            x1 - 14,
            y1 - 42,
            bg_fill=(14, 16, 22, 198),
            text_fill=(*LIGHT_PRIMARY, 240),
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
) -> Image.Image:
    """Draw the Chrono Byte editorial masthead bar across the top."""
    margin_x = 68
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
            font_weight="mono",
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
) -> Image.Image:
    """Draw a clean footer with carousel progress dots, handle, and swipe pill."""
    draw = ImageDraw.Draw(canvas)
    if divider_fill is not None:
        draw.line((margin_x, 1222, CARD_WIDTH - margin_x, 1222), fill=divider_fill, width=1)

    footer_y = 1244
    col_font = _load_font("regular", 17)
    short_label = label if len(label) <= 14 else label[:13].rstrip()
    footer_text = f"{handle}  ·  {short_label}" if short_label else handle
    draw.text((margin_x, footer_y + 6), footer_text, font=col_font, fill=muted_fill)

    if total_slides > 1:
        dot_y = footer_y + 16
        dot_gap = 18
        total_dots_w = (total_slides - 1) * dot_gap + 22
        dots_x = (CARD_WIDTH - total_dots_w) // 2
        cx = dots_x
        for idx in range(1, total_slides + 1):
            if idx == current_idx:
                draw.rounded_rectangle((cx, dot_y - 4, cx + 22, dot_y + 4), radius=4, fill=(*accent, 255))
                cx += 28
            else:
                draw.ellipse((cx, dot_y - 4, cx + 8, dot_y + 4), fill=(*muted_fill[:3], 130))
                cx += dot_gap

        badge_text_str = (
            f"{current_idx:02d} / {total_slides:02d}  ·  SWIPE →"
            if current_idx < total_slides
            else f"{current_idx:02d} / {total_slides:02d}"
        )
        canvas, _ = _draw_pill(
            canvas,
            badge_text_str,
            CARD_WIDTH - margin_x,
            footer_y,
            bg_fill=badge_bg,
            text_fill=badge_text,
            outline_fill=badge_outline,
            align_right=True,
            font_weight="mono",
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
    """Pick a single crisp, non-wall-of-text lead deck for the Slide 1 cover."""
    if not blocks:
        return "", 0
    lead = blocks[0].strip()
    if len(lead) <= max_chars:
        return lead, 1
    first_sentence = re.split(r"(?<=[.!?])\s+", lead)[0].strip()
    if 35 <= len(first_sentence) <= max_chars + 15:
        # Leave remaining sentences for Slide 2 when cover shows only the opening sentence.
        consumed = 1 if len(first_sentence) >= len(lead) - 20 else 0
        return first_sentence, consumed
    clipped = lead[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return clipped, 1


def _build_abstract_plate(
    width: int,
    height: int,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    dark: bool = True,
) -> Image.Image:
    """Create a rich, atmospheric textured editorial art plate when an article has no photo."""
    accent, wash, deep, highlight = palette
    rng = random.Random(seed)
    base_color = deep if dark else PAPER_BUFF
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
    ad.ellipse(
        (int(width * rng.uniform(0.15, 0.45)), int(height * 0.10), int(width * 1.05), int(height * 1.15)),
        fill=(*highlight, 150 if dark else 135),
    )
    ad.ellipse(
        (-int(width * 0.15), -int(height * 0.15), int(width * 0.55), int(height * 0.65)),
        fill=(*accent, 130 if dark else 110),
    )
    plate = Image.alpha_composite(plate, art.filter(ImageFilter.GaussianBlur(radius=62)))

    ring_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring_layer)
    cx = int(width * rng.uniform(0.58, 0.80))
    cy = int(height * rng.uniform(0.32, 0.60))
    stroke = (255, 255, 255, 38) if dark else (*deep, 38)
    for r in (100, 175, 250, 325):
        rd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=stroke, width=2)
    plate = Image.alpha_composite(plate, ring_layer)
    return _apply_analog_grain(plate, strength=0.34)


# ---------------------------------------------------------------------------
# 5 Dynamic Slide 1 Cover Archetypes
# ---------------------------------------------------------------------------


def _render_full_bleed_hero(
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    source_images: list[dict],
    deck_override: str | None = None,
    total_slides: int = 1,
) -> Image.Image:
    """Cinema full-bleed source photo cover with frosted pills and luminous gradient scrim."""
    accent, _, deep, _ = palette
    if source_images:
        canvas = _fit_photo_panel(
            source_images[0]["image"],
            CARD_WIDTH,
            CARD_HEIGHT,
            matte_rgb=deep,
            crop_focus=(0.5, 0.35),
            allow_contain_for_wide=True,
        )
    else:
        canvas = _build_abstract_plate(CARD_WIDTH, CARD_HEIGHT, palette, seed, dark=True)
        canvas = _apply_dot_grid(canvas, (255, 255, 255, 16), step=32)

    # Top scrim for masthead legibility + deep bottom scrim for bold typography.
    top_scrim = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    grad_top = Image.linear_gradient("L").resize((1, 180), resample=Image.Resampling.BILINEAR)
    grad_top = grad_top.point(lambda p: int(185 * (1.0 - p / 255.0)))
    top_alpha = Image.new("L", canvas.size, 0)
    top_alpha.paste(grad_top.resize((CARD_WIDTH, 180), resample=Image.Resampling.NEAREST), (0, 0))
    top_overlay = Image.new("RGBA", canvas.size, (*NOIR_INK, 255))
    top_overlay.putalpha(top_alpha)
    canvas = Image.alpha_composite(canvas, top_overlay)

    canvas = _apply_linear_scrim(canvas, start_y=450, end_y=1225, color_rgb=deep, start_alpha=0, end_alpha=244)
    canvas = _draw_masthead(canvas, topic, handle, accent, (*LIGHT_PRIMARY, 250), (*LIGHT_MUTED, 235), frosted=True)

    margin_x = 68
    content_w = CARD_WIDTH - margin_x * 2
    draw = ImageDraw.Draw(canvas)

    h_weight = "display" if seed % 2 == 0 else "serif_bold"
    headline = _strip_invisible(topic["text"])
    h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 60, 50, font_weight=h_weight, max_lines=4)
    h_step = int(h_font.size * 1.13)

    deck_font = _load_font("regular", 27)
    deck_lines = _wrap_text(draw, deck_override, deck_font, content_w - 20, max_lines=2) if deck_override else []
    deck_h = len(deck_lines) * 36 + (16 if deck_lines else 0)
    stack_h = 44 + len(h_lines) * h_step + 22 + deck_h
    stack_top = max(510, 1188 - stack_h)

    topic_tag = (_strip_invisible(topic.get("topic_tag") or "") or "TECH BRIEF").upper()
    canvas, _ = _draw_pill(
        canvas,
        topic_tag,
        margin_x,
        stack_top,
        bg_fill=(*accent, 240),
        text_fill=(255, 255, 255, 255),
        font_weight="mono",
        font_size=14,
        pad_x=15,
        height=30,
    )
    draw = ImageDraw.Draw(canvas)
    h_end = _draw_text_lines(draw, h_lines, margin_x, stack_top + 44, h_step, h_font, (*LIGHT_PRIMARY, 255))
    draw.rectangle((margin_x, h_end + 12, margin_x + 74, h_end + 16), fill=(*accent, 255))
    if deck_lines:
        _draw_text_lines(draw, deck_lines, margin_x, h_end + 28, 36, deck_font, (*LIGHT_SECONDARY, 246))

    canvas = _draw_progress_footer(
        canvas,
        current_idx=1,
        total_slides=total_slides,
        handle=handle,
        label="VISUAL BRIEF",
        accent=accent,
        muted_fill=(*LIGHT_MUTED, 235),
        divider_fill=(255, 255, 255, 42),
        badge_bg=(16, 20, 26, 225),
        badge_text=(*LIGHT_PRIMARY, 252),
        badge_outline=(*accent, 190),
    )
    return _apply_analog_grain(canvas, strength=0.14)


def _render_split_editorial(
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    source_images: list[dict],
    deck_override: str | None = None,
    total_slides: int = 1,
) -> Image.Image:
    """Two-zone broadsheet split: large upper photo plate + overlapping pill + lower serif deck."""
    accent, _, deep, _ = palette
    dark_variant = seed % 3 == 0
    bg_rgb = NOIR_INK if dark_variant else PAPER_CREAM
    primary_fill = (*LIGHT_PRIMARY, 255) if dark_variant else (*INK_PRIMARY, 255)
    secondary_fill = (*LIGHT_SECONDARY, 244) if dark_variant else (*INK_SECONDARY, 245)
    muted_fill = (*LIGHT_MUTED, 235) if dark_variant else (*INK_MUTED, 235)
    rule_fill = (255, 255, 255, 32) if dark_variant else (20, 22, 24, 30)

    canvas = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*bg_rgb, 255))
    canvas = _draw_masthead(canvas, topic, handle, accent, primary_fill, muted_fill, rule_fill=rule_fill)

    margin_x = 68
    content_w = CARD_WIDTH - margin_x * 2
    photo_box = (margin_x, 118, CARD_WIDTH - margin_x, 658)
    if source_images:
        canvas = _paste_photo_frame(
            canvas,
            source_images[0]["image"],
            photo_box,
            matte_rgb=deep if dark_variant else (228, 222, 208),
            radius=20,
            border_fill=(255, 255, 255, 42) if dark_variant else (20, 22, 24, 32),
            shadow_alpha=90 if not dark_variant else 110,
            credit_text=source_images[0]["credit"],
        )
    else:
        plate = _build_abstract_plate(content_w, photo_box[3] - photo_box[1], palette, seed, dark=dark_variant)
        mask = Image.new("L", plate.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, *plate.size), radius=20, fill=255)
        canvas.paste(plate, (photo_box[0], photo_box[1]), mask)

    topic_tag = (_strip_invisible(topic.get("topic_tag") or "") or "TECH BRIEF").upper()
    canvas, _ = _draw_pill(
        canvas,
        topic_tag,
        margin_x + 22,
        640,
        bg_fill=(*accent, 255),
        text_fill=(255, 255, 255, 255),
        outline_fill=(*bg_rgb, 255),
        font_weight="mono",
        font_size=15,
        pad_x=16,
        height=34,
    )

    draw = ImageDraw.Draw(canvas)
    headline = _strip_invisible(topic["text"])
    h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 56, 48, font_weight="serif_bold", max_lines=4)
    h_step = int(h_font.size * 1.14)
    h_end = _draw_text_lines(draw, h_lines, margin_x, 704, h_step, h_font, primary_fill)
    draw.rectangle((margin_x, h_end + 16, margin_x + 84, h_end + 20), fill=(*accent, 255))

    if deck_override:
        deck_font = _load_font("regular", 27)
        deck_lines = _wrap_text(draw, deck_override, deck_font, content_w, max_lines=3)
        avail = max(1, (1195 - (h_end + 36)) // 37)
        _draw_text_lines(draw, deck_lines[:avail], margin_x, h_end + 36, 37, deck_font, secondary_fill)

    canvas = _draw_progress_footer(
        canvas,
        current_idx=1,
        total_slides=total_slides,
        handle=handle,
        label="DAILY BRIEF",
        accent=accent,
        muted_fill=muted_fill,
        divider_fill=rule_fill,
        badge_bg=(28, 32, 40, 230) if dark_variant else (*deep, 236),
        badge_text=(*LIGHT_PRIMARY, 252),
        badge_outline=(*accent, 150) if dark_variant else None,
    )
    return _apply_analog_grain(canvas, strength=0.15)


def _render_framed_dispatch(
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    source_images: list[dict],
    deck_override: str | None = None,
    total_slides: int = 1,
) -> Image.Image:
    """Warm magazine cover: punchy headline + concise deck above an elevated source photo."""
    accent, _, deep, _ = palette
    canvas = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*PAPER_CREAM, 255))
    canvas = _draw_masthead(
        canvas, topic, handle, accent, (*INK_SECONDARY, 240), (*INK_MUTED, 235), rule_fill=(20, 22, 24, 28)
    )

    margin_x = 68
    content_w = CARD_WIDTH - margin_x * 2
    topic_tag = (_strip_invisible(topic.get("topic_tag") or "") or "TECH BRIEF").upper()
    canvas, _ = _draw_pill(
        canvas,
        topic_tag,
        margin_x,
        122,
        bg_fill=(*deep, 236),
        text_fill=(*LIGHT_PRIMARY, 252),
        font_weight="mono",
        font_size=14,
        pad_x=14,
        height=28,
    )

    draw = ImageDraw.Draw(canvas)
    headline = _strip_invisible(topic["text"])
    h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 56, 48, font_weight="serif_bold", max_lines=4)
    h_step = int(h_font.size * 1.14)
    h_end = _draw_text_lines(draw, h_lines, margin_x, 168, h_step, h_font, (*INK_PRIMARY, 255))
    draw.rectangle((margin_x, h_end + 14, margin_x + 76, h_end + 18), fill=(*accent, 255))

    y_cursor = h_end + 32
    if deck_override:
        deck_font = _load_font("regular", 27)
        deck_lines = _wrap_text(draw, deck_override, deck_font, content_w, max_lines=3)
        y_cursor = _draw_text_lines(draw, deck_lines, margin_x, y_cursor, 36, deck_font, (*INK_SECONDARY, 242))
        y_cursor += 14

    plate_top = max(465, min(695, y_cursor + 12))
    avail_h = 1196 - plate_top
    if source_images:
        aspect = _analyze_image(source_images[0]["image"])["aspect"]
        ideal_h = int(content_w / max(1.25, min(1.85, aspect)))
        frame_h = max(360, min(avail_h, ideal_h))
        plate_top = plate_top + max(0, (avail_h - frame_h) // 2)
        plate_bottom = plate_top + frame_h
    else:
        plate_bottom = 1200
    photo_box = (margin_x, plate_top, CARD_WIDTH - margin_x, plate_bottom)
    if source_images:
        canvas = _paste_photo_frame(
            canvas,
            source_images[0]["image"],
            photo_box,
            matte_rgb=deep,
            radius=20,
            border_fill=(20, 22, 24, 38),
            shadow_alpha=85,
            credit_text=source_images[0]["credit"],
        )
    else:
        plate = _build_abstract_plate(content_w, plate_bottom - plate_top, palette, seed, dark=True)
        mask = Image.new("L", plate.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, *plate.size), radius=20, fill=255)
        canvas.paste(plate, (margin_x, plate_top), mask)

    canvas = _draw_progress_footer(
        canvas,
        current_idx=1,
        total_slides=total_slides,
        handle=handle,
        label="DISPATCH",
        accent=accent,
        muted_fill=(*INK_MUTED, 235),
        divider_fill=(20, 22, 24, 30),
        badge_bg=(*deep, 238),
        badge_text=(*LIGHT_PRIMARY, 252),
    )
    return _apply_analog_grain(canvas, strength=0.16)


def _render_duotone_cinema(
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    source_images: list[dict],
    deck_override: str | None = None,
    total_slides: int = 1,
) -> Image.Image:
    """Midnight noir feature card with luminous accent glow behind an editorial source photo."""
    accent, wash, deep, highlight = palette
    canvas = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*NOIR_INK, 255))

    glow = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((140, 120, 960, 740), fill=(*wash, 125))
    gd.ellipse((540, 720, 1220, 1460), fill=(*accent, 95))
    gd.ellipse((-180, 780, 480, 1420), fill=(*highlight, 80))
    canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(radius=130)))
    canvas = _apply_dot_grid(canvas, (255, 255, 255, 14), step=34)

    frame = ImageDraw.Draw(canvas)
    frame.rounded_rectangle((32, 30, CARD_WIDTH - 32, CARD_HEIGHT - 30), radius=14, outline=(255, 255, 255, 28), width=2)
    canvas = _draw_masthead(
        canvas, topic, handle, accent, (*LIGHT_PRIMARY, 240), (*LIGHT_MUTED, 235), rule_fill=(255, 255, 255, 30)
    )

    margin_x = 72
    content_w = CARD_WIDTH - margin_x * 2
    photo_box = (margin_x, 128, CARD_WIDTH - margin_x, 622)
    if source_images:
        vivid = ImageEnhance.Contrast(_flatten_to_rgb(source_images[0]["image"], deep)).enhance(1.06)
        canvas = _paste_photo_frame(
            canvas,
            vivid,
            photo_box,
            matte_rgb=deep,
            radius=18,
            border_fill=(*accent, 180),
            border_width=2,
            shadow_alpha=125,
            credit_text=source_images[0]["credit"],
        )
    else:
        plate = _build_abstract_plate(content_w, photo_box[3] - photo_box[1], palette, seed, dark=True)
        mask = Image.new("L", plate.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, *plate.size), radius=18, fill=255)
        canvas.paste(plate, (photo_box[0], photo_box[1]), mask)

    topic_tag = (_strip_invisible(topic.get("topic_tag") or "") or "TECH BRIEF").upper()
    canvas, _ = _draw_pill(
        canvas,
        f"SPOTLIGHT  ·  {topic_tag}",
        margin_x,
        650,
        bg_fill=(26, 30, 38, 240),
        text_fill=(*accent, 255),
        outline_fill=(*accent, 185),
        font_weight="mono",
        font_size=14,
        pad_x=15,
        height=30,
    )

    draw = ImageDraw.Draw(canvas)
    headline = _strip_invisible(topic["text"])
    h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 56, 48, font_weight="serif", max_lines=4)
    h_step = int(h_font.size * 1.14)
    h_end = _draw_text_lines(draw, h_lines, margin_x, 698, h_step, h_font, (*LIGHT_PRIMARY, 255))
    draw.rectangle((margin_x, h_end + 16, margin_x + 84, h_end + 20), fill=(*accent, 245))

    if deck_override:
        deck_font = _load_font("regular", 27)
        deck_lines = _wrap_text(draw, deck_override, deck_font, content_w, max_lines=3)
        avail = max(1, (1195 - (h_end + 38)) // 37)
        _draw_text_lines(draw, deck_lines[:avail], margin_x, h_end + 38, 37, deck_font, (*LIGHT_SECONDARY, 245))

    canvas = _draw_progress_footer(
        canvas,
        current_idx=1,
        total_slides=total_slides,
        handle=handle,
        label="NOIR EDITION",
        accent=accent,
        muted_fill=(*LIGHT_MUTED, 235),
        divider_fill=(255, 255, 255, 36),
        badge_bg=(26, 30, 38, 232),
        badge_text=(*LIGHT_PRIMARY, 252),
        badge_outline=(*accent, 180),
        margin_x=margin_x,
    )
    return _apply_analog_grain(canvas, strength=0.22)


def _multiply_ink_shape(canvas_rgb: Image.Image, draw_fn, blur_radius: float = 1.5) -> Image.Image:
    ink = Image.new("RGB", canvas_rgb.size, (255, 255, 255))
    draw_fn(ImageDraw.Draw(ink))
    if blur_radius > 0:
        ink = ink.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    return ImageChops.multiply(canvas_rgb, ink)


def _render_riso_kinetic(
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    source_images: list[dict],
    deck_override: str | None = None,
    total_slides: int = 1,
) -> Image.Image:
    """Swiss/Zine poster: bold sans typography, multiplied ink blocks, and offset photo frame."""
    accent, wash, deep, highlight = palette
    soft_accent = tuple(int(c * 0.72 + PAPER_BUFF[i] * 0.28) for i, c in enumerate(accent))
    paper_rgb = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), PAPER_BUFF)
    paper_rgb = _multiply_ink_shape(paper_rgb, lambda d: d.ellipse((620, 620, 1260, 1180), fill=highlight), 2.0)
    paper_rgb = _multiply_ink_shape(paper_rgb, lambda d: d.pieslice((-120, 720, 620, 1210), 270, 90, fill=soft_accent), 2.0)
    canvas = paper_rgb.convert("RGBA")
    canvas = _apply_dot_grid(canvas, (*INK_PRIMARY, 16), step=26, box=(0, 100, CARD_WIDTH, CARD_HEIGHT - 120))

    canvas = _draw_masthead(canvas, topic, handle, accent, (*INK_PRIMARY, 240), (*INK_MUTED, 235))
    draw = ImageDraw.Draw(canvas)
    margin_x = 68
    content_w = CARD_WIDTH - margin_x * 2
    draw.line((margin_x, 102, CARD_WIDTH - margin_x, 102), fill=(*INK_PRIMARY, 210), width=4)

    topic_tag = (_strip_invisible(topic.get("topic_tag") or "") or "TECH BRIEF").upper()
    canvas, _ = _draw_pill(
        canvas,
        f"ISSUE  //  {topic_tag}",
        margin_x,
        122,
        bg_fill=(*INK_PRIMARY, 240),
        text_fill=(*PAPER_BUFF, 255),
        font_weight="mono",
        font_size=14,
        pad_x=14,
        height=28,
    )

    draw = ImageDraw.Draw(canvas)
    headline = _strip_invisible(topic["text"])
    h_lines, h_font = _fit_headline_lines(draw, headline, content_w, 56, 48, font_weight="display", max_lines=4)
    h_step = int(h_font.size * 1.12)
    h_end = _draw_text_lines(draw, h_lines, margin_x, 168, h_step, h_font, (*INK_PRIMARY, 255))

    y_cursor = h_end + 18
    if deck_override:
        deck_font = _load_font("regular", 26)
        deck_lines = _wrap_text(draw, deck_override, deck_font, content_w, max_lines=2)
        y_cursor = _draw_text_lines(draw, deck_lines, margin_x, y_cursor, 35, deck_font, (*INK_SECONDARY, 245))
        y_cursor += 12

    plate_top = max(445, min(660, y_cursor + 12))
    avail_h = 1190 - plate_top
    frame_w = (CARD_WIDTH - margin_x * 2) - 10
    if source_images:
        aspect = _analyze_image(source_images[0]["image"])["aspect"]
        ideal_h = int(frame_w / max(1.25, min(1.85, aspect)))
        frame_h = max(360, min(avail_h, ideal_h))
        plate_top = plate_top + max(0, (avail_h - frame_h) // 2)
        plate_bottom = plate_top + frame_h
    else:
        plate_bottom = 1190
    photo_box = (margin_x, plate_top, CARD_WIDTH - margin_x - 10, plate_bottom)
    if source_images:
        canvas = _paste_photo_frame(
            canvas,
            source_images[0]["image"],
            photo_box,
            matte_rgb=deep,
            radius=12,
            border_fill=(*INK_PRIMARY, 240),
            border_width=3,
            offset_block_fill=(*accent, 235),
            credit_text=source_images[0]["credit"],
        )
    else:
        plate = _build_abstract_plate(photo_box[2] - photo_box[0], photo_box[3] - photo_box[1], palette, seed, dark=False)
        canvas = _composite_rounded_box(
            canvas,
            (photo_box[0] + 10, photo_box[1] + 10, photo_box[2] + 10, photo_box[3] + 10),
            radius=12,
            fill=(*accent, 230),
        )
        mask = Image.new("L", plate.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, *plate.size), radius=12, fill=255)
        canvas.paste(plate, (photo_box[0], photo_box[1]), mask)
        canvas = _composite_rounded_box(canvas, photo_box, radius=12, fill=(0, 0, 0, 0), outline=(*INK_PRIMARY, 235), width=3)

    canvas = _draw_progress_footer(
        canvas,
        current_idx=1,
        total_slides=total_slides,
        handle=handle,
        label="PRINT ZINE",
        accent=accent,
        muted_fill=(*INK_MUTED, 240),
        divider_fill=(*INK_PRIMARY, 55),
        badge_bg=(*INK_PRIMARY, 232),
        badge_text=(*PAPER_BUFF, 255),
    )
    return _apply_analog_grain(canvas, strength=0.30)


_THEME_RENDERERS = {
    "full_bleed_hero": _render_full_bleed_hero,
    "split_editorial": _render_split_editorial,
    "framed_dispatch": _render_framed_dispatch,
    "duotone_cinema": _render_duotone_cinema,
    "riso_kinetic": _render_riso_kinetic,
}


def _select_theme_and_palette(
    topic: dict,
    theme: str | None = None,
    source_images: list[dict] | None = None,
) -> tuple[str, str, tuple[tuple[int, int, int], ...], int, int, int]:
    """Select an editorial archetype & publisher palette adapted to the hero image."""
    source = _strip_invisible(topic.get("source", "Tech News"))
    seed = _topic_seed(topic)
    palettes = SOURCE_PALETTES.get(source, DEFAULT_PALETTES)
    palette_idx = seed % len(palettes)
    palette = palettes[palette_idx]

    if theme in _THEME_ALIASES:
        return _THEME_ALIASES[theme], "alias", palette, palette_idx, len(palettes), seed
    if theme in _THEME_RENDERERS:
        return theme, "explicit", palette, palette_idx, len(palettes), seed

    if source_images:
        stats = _analyze_image(source_images[0]["image"])
        if stats["aspect"] >= 1.55 or stats["luma"] >= 205:
            # Widescreen (16:9 / panoramic) and bright studio shots look cleanest in framed/split cards.
            pool = ("split_editorial", "framed_dispatch", "duotone_cinema", "riso_kinetic")
        else:
            pool = CARD_THEMES
    else:
        pool = ("split_editorial", "framed_dispatch", "duotone_cinema", "riso_kinetic", "full_bleed_hero")
    return pool[seed % len(pool)], "dynamic", palette, palette_idx, len(palettes), seed


# ---------------------------------------------------------------------------
# Dynamic Inner Slides (Photo Feature / Numbered Fact Cards / Pull Quote / Closing)
# ---------------------------------------------------------------------------


def _create_inner_surface(
    theme: str,
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    hero_photo: Image.Image | None = None,
) -> tuple[Image.Image, dict]:
    """Build a cohesive inner-slide surface harmonized with Slide 1 and source photography."""
    accent, wash, deep, highlight = palette
    dark_mode = theme in {"full_bleed_hero", "duotone_cinema"} or (theme == "split_editorial" and seed % 3 == 0)

    if dark_mode:
        canvas = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*NOIR_INK, 255))
        if hero_photo is not None:
            ambient = ImageOps.fit(
                _flatten_to_rgb(hero_photo, NOIR_INK), (CARD_WIDTH, CARD_HEIGHT), method=Image.Resampling.BILINEAR
            ).filter(ImageFilter.GaussianBlur(radius=85))
            ambient = ImageEnhance.Brightness(ambient).enhance(0.24).convert("RGBA")
            canvas = Image.blend(canvas, ambient, alpha=0.65)
        glow = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((540, 820, 1280, 1520), fill=(*wash, 110))
        gd.ellipse((-220, 900, 440, 1460), fill=(*accent, 80))
        canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(radius=140)))
        if theme == "duotone_cinema":
            ImageDraw.Draw(canvas).rounded_rectangle(
                (32, 30, CARD_WIDTH - 32, CARD_HEIGHT - 30), radius=14, outline=(255, 255, 255, 28), width=2
            )
        canvas = _draw_masthead(
            canvas, topic, handle, accent, (*LIGHT_PRIMARY, 238), (*LIGHT_MUTED, 235), rule_fill=(255, 255, 255, 30)
        )
        return canvas, {
            "dark": True,
            "bg_rgb": NOIR_INK,
            "primary": (*LIGHT_PRIMARY, 255),
            "secondary": (*LIGHT_SECONDARY, 245),
            "muted": (*LIGHT_MUTED, 235),
            "accent": (*accent, 255),
            "deep": (*deep, 255),
            "panel_bg": (28, 32, 42, 224),
            "panel_outline": (255, 255, 255, 34),
            "panel_accent_outline": (*accent, 185),
            "badge_bg": (26, 30, 38, 232),
            "badge_text": (*LIGHT_PRIMARY, 252),
            "badge_outline": (*accent, 175),
            "divider": (255, 255, 255, 36),
            "grain": 0.20,
        }

    if theme == "riso_kinetic":
        paper_rgb = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), PAPER_BUFF)
        paper_rgb = _multiply_ink_shape(paper_rgb, lambda d: d.ellipse((680, 1080, 1240, 1560), fill=highlight), 2.0)
        paper_rgb = _multiply_ink_shape(paper_rgb, lambda d: d.ellipse((500, 1160, 820, 1480), fill=wash), 2.0)
        canvas = paper_rgb.convert("RGBA")
        canvas = _apply_dot_grid(canvas, (*INK_PRIMARY, 14), step=28, box=(0, 100, CARD_WIDTH, CARD_HEIGHT - 120))
        canvas = _draw_masthead(canvas, topic, handle, accent, (*INK_PRIMARY, 240), (*INK_MUTED, 235))
        ImageDraw.Draw(canvas).line((68, 102, CARD_WIDTH - 68, 102), fill=(*INK_PRIMARY, 210), width=4)
        return canvas, {
            "dark": False,
            "bg_rgb": PAPER_BUFF,
            "primary": (*INK_PRIMARY, 255),
            "secondary": (*INK_SECONDARY, 245),
            "muted": (*INK_MUTED, 240),
            "accent": (*accent, 255),
            "deep": (*deep, 255),
            "panel_bg": (231, 223, 206, 236),
            "panel_outline": (*INK_PRIMARY, 180),
            "panel_accent_outline": (*INK_PRIMARY, 210),
            "badge_bg": (*INK_PRIMARY, 232),
            "badge_text": (*PAPER_BUFF, 255),
            "badge_outline": None,
            "divider": (*INK_PRIMARY, 55),
            "grain": 0.28,
        }

    # Cream archival paper (split_editorial light / framed_dispatch).
    canvas = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (*PAPER_CREAM, 255))
    if hero_photo is not None:
        ambient = ImageOps.fit(
            _flatten_to_rgb(hero_photo, PAPER_CREAM), (CARD_WIDTH, CARD_HEIGHT), method=Image.Resampling.BILINEAR
        ).filter(ImageFilter.GaussianBlur(radius=95))
        light_wash = Image.blend(ambient, Image.new("RGB", canvas.size, PAPER_CREAM), alpha=0.86).convert("RGBA")
        canvas = Image.blend(canvas, light_wash, alpha=0.7)
    canvas = _draw_masthead(
        canvas, topic, handle, accent, (*INK_SECONDARY, 240), (*INK_MUTED, 235), rule_fill=(20, 22, 24, 28)
    )
    return canvas, {
        "dark": False,
        "bg_rgb": PAPER_CREAM,
        "primary": (*INK_PRIMARY, 255),
        "secondary": (*INK_SECONDARY, 245),
        "muted": (*INK_MUTED, 235),
        "accent": (*accent, 255),
        "deep": (*deep, 255),
        "panel_bg": (255, 255, 255, 214),
        "panel_outline": (20, 22, 24, 28),
        "panel_accent_outline": (*accent, 180),
        "badge_bg": (*deep, 238),
        "badge_text": (*LIGHT_PRIMARY, 252),
        "badge_outline": None,
        "divider": (20, 22, 24, 32),
        "grain": 0.14,
    }


def _draw_inner_header(
    canvas: Image.Image,
    topic: dict,
    section_title: str,
    style: dict,
    margin_x: int = 68,
) -> tuple[Image.Image, int]:
    draw = ImageDraw.Draw(canvas)
    content_w = CARD_WIDTH - margin_x * 2
    kicker_font = _load_font("regular", 17)
    headline = _strip_invisible(topic["text"])
    kicker = _wrap_text(
        draw, f"{_strip_invisible(topic.get('source', 'NEWS')).upper()}  ·  {headline}", kicker_font, content_w, max_lines=1
    )
    if kicker:
        draw.text((margin_x, 118), kicker[0], font=kicker_font, fill=style["muted"])
    title_font = _load_font("serif_bold", 38)
    draw.text((margin_x, 148), section_title, font=title_font, fill=style["primary"])
    draw.rectangle((margin_x, 200, margin_x + 76, 204), fill=style["accent"])
    return canvas, 226


def _extract_stat_token(blocks: list[str]) -> str | None:
    """Return a concise real numeric metric/price from verbatim source blocks if present."""
    for block in blocks:
        match = _METRIC_PATTERN.search(block)
        if match:
            token = " ".join(match.group(0).split())
            if len(token) <= 18:
                return token
    return None


def _render_fact_grid_slide(
    theme: str,
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    section_title: str,
    blocks: list[str],
    slide_idx: int,
    total_slides: int,
    hero_photo: Image.Image | None,
) -> Image.Image:
    """Visual numbered insight cards (01 / 02 / 03) with optional Key Figure callout badge."""
    accent, _, _, _ = palette
    canvas, style = _create_inner_surface(theme, topic, palette, seed, handle, hero_photo=hero_photo)
    margin_x = 68
    content_w = CARD_WIDTH - margin_x * 2
    canvas, cursor_y = _draw_inner_header(canvas, topic, section_title, style, margin_x=margin_x)

    stat_token = _extract_stat_token(blocks)
    if stat_token:
        canvas, _ = _draw_pill(
            canvas,
            f"KEY FIGURE  ·  {stat_token.upper()}",
            CARD_WIDTH - margin_x,
            152,
            bg_fill=(*accent, 34),
            text_fill=style["accent"],
            outline_fill=style["accent"],
            align_right=True,
            font_weight="mono",
            font_size=14,
            pad_x=14,
            height=30,
        )

    probe = ImageDraw.Draw(canvas)
    body_font = _load_font("regular", 28)
    line_step = 40
    num_font = _load_font("mono", 18)
    max_y = 1185

    # Pre-measure cards so we can distribute vertical spacing cleanly inside [cursor_y, max_y].
    measured_cards: list[tuple[list[str], int]] = []
    temp_y = cursor_y
    text_w = content_w - 118
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
        measured_cards.append((lines, box_h))
        temp_y += box_h + 22

    total_cards_h = sum(bh for _, bh in measured_cards)
    slack = max(0, max_y - cursor_y - total_cards_h)
    panel_gap = min(44, max(22, slack // max(1, len(measured_cards) + 1))) if len(measured_cards) > 1 else 22
    if len(measured_cards) > 0:
        used_with_gaps = total_cards_h + panel_gap * (len(measured_cards) - 1)
        cursor_y += min(95, max(0, (max_y - cursor_y - used_with_gaps) // 3))

    for item_idx, (lines, box_h) in enumerate(measured_cards, start=1):
        canvas = _composite_rounded_box(
            canvas,
            (margin_x, cursor_y, CARD_WIDTH - margin_x, cursor_y + box_h),
            radius=18,
            fill=style["panel_bg"],
            outline=style["panel_outline"],
            width=2 if theme == "riso_kinetic" else 1,
        )
        badge_x = margin_x + 24
        badge_y = cursor_y + 28
        canvas = _composite_rounded_box(
            canvas,
            (badge_x, badge_y, badge_x + 48, badge_y + 42),
            radius=11,
            fill=(*accent, 238),
        )
        draw = ImageDraw.Draw(canvas)
        num_str = f"{item_idx:02d}"
        nw = _text_width(draw, num_str, num_font)
        draw.text((badge_x + (48 - nw) / 2, badge_y + 10), num_str, font=num_font, fill=(255, 255, 255, 255))

        _draw_text_lines(draw, lines, badge_x + 68, cursor_y + 28, line_step, body_font, style["primary"])
        cursor_y += box_h + panel_gap

    canvas = _draw_progress_footer(
        canvas,
        current_idx=slide_idx,
        total_slides=total_slides,
        handle=handle,
        label="KEY FACTS",
        accent=accent,
        muted_fill=style["muted"],
        divider_fill=style["divider"],
        badge_bg=style["badge_bg"],
        badge_text=style["badge_text"],
        badge_outline=style["badge_outline"],
        margin_x=margin_x,
    )
    return _apply_analog_grain(canvas, strength=style["grain"])


def _render_photo_feature_slide(
    theme: str,
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    section_title: str,
    blocks: list[str],
    slide_idx: int,
    total_slides: int,
    feature_photo: dict,
    hero_photo: Image.Image | None,
) -> Image.Image:
    """Showcase an extra image from the official source above concise insight cards."""
    accent, _, _, _ = palette
    canvas, style = _create_inner_surface(theme, topic, palette, seed, handle, hero_photo=hero_photo)
    margin_x = 68
    content_w = CARD_WIDTH - margin_x * 2
    canvas, cursor_y = _draw_inner_header(canvas, topic, section_title, style, margin_x=margin_x)

    photo_box = (margin_x, cursor_y, CARD_WIDTH - margin_x, cursor_y + 430)
    canvas = _paste_photo_frame(
        canvas,
        feature_photo["image"],
        photo_box,
        matte_rgb=style["bg_rgb"],
        radius=18,
        border_fill=style["panel_outline"],
        border_width=2,
        credit_text=feature_photo["credit"],
    )

    cursor_y = photo_box[3] + 24
    body_font = _load_font("regular", 27)
    line_step = 37
    probe = ImageDraw.Draw(canvas)
    for item_idx, block in enumerate(blocks[:2], start=1):
        lines = _wrap_text(probe, block, body_font, content_w - 56, max_lines=4)
        box_h = len(lines) * line_step + 44
        if cursor_y + box_h > 1190:
            if item_idx == 1:
                avail = max(2, (1190 - cursor_y - 44) // line_step)
                lines = _wrap_text(probe, block, body_font, content_w - 56, max_lines=avail)
                box_h = len(lines) * line_step + 44
            else:
                break
        canvas = _composite_rounded_box(
            canvas,
            (margin_x, cursor_y, CARD_WIDTH - margin_x, cursor_y + box_h),
            radius=16,
            fill=style["panel_bg"],
            outline=style["panel_outline"],
            width=1,
        )
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((margin_x + 2, cursor_y + 18, margin_x + 6, cursor_y + box_h - 18), fill=style["accent"])
        _draw_text_lines(draw, lines, margin_x + 28, cursor_y + 22, line_step, body_font, style["primary"])
        probe = draw
        cursor_y += box_h + 16

    canvas = _draw_progress_footer(
        canvas,
        current_idx=slide_idx,
        total_slides=total_slides,
        handle=handle,
        label="VISUAL CONTEXT",
        accent=accent,
        muted_fill=style["muted"],
        divider_fill=style["divider"],
        badge_bg=style["badge_bg"],
        badge_text=style["badge_text"],
        badge_outline=style["badge_outline"],
        margin_x=margin_x,
    )
    return _apply_analog_grain(canvas, strength=style["grain"])


def _render_pull_quote_slide(
    theme: str,
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    section_title: str,
    blocks: list[str],
    slide_idx: int,
    total_slides: int,
    hero_photo: Image.Image | None,
) -> Image.Image:
    """Editorial spotlight pull-quote slide breaking up multi-card reading rhythm."""
    accent, _, _, _ = palette
    canvas, style = _create_inner_surface(theme, topic, palette, seed, handle, hero_photo=hero_photo)
    margin_x = 68
    content_w = CARD_WIDTH - margin_x * 2
    canvas, cursor_y = _draw_inner_header(canvas, topic, section_title, style, margin_x=margin_x)

    quote_text = blocks[0] if blocks else _strip_invisible(topic["text"])
    extra_text = blocks[1] if len(blocks) > 1 else ""

    draw = ImageDraw.Draw(canvas)
    mark_font = _load_font("serif_bold", 120)
    draw.text((margin_x - 6, cursor_y - 14), "“", font=mark_font, fill=style["accent"])

    q_font = _load_font("serif", 38)
    q_lines = _wrap_text(draw, quote_text, q_font, content_w - 20, max_lines=7)
    if len(q_lines) >= 7:
        q_font = _load_font("serif", 33)
        q_lines = _wrap_text(draw, quote_text, q_font, content_w - 20, max_lines=7)
    q_step = int(q_font.size * 1.28)
    q_end = _draw_text_lines(draw, q_lines, margin_x + 12, cursor_y + 78, q_step, q_font, style["primary"])

    if extra_text and q_end + 145 < 1185:
        box_top = q_end + 34
        sub_font = _load_font("regular", 27)
        sub_lines = _wrap_text(draw, extra_text, sub_font, content_w - 60, max_lines=5)
        box_h = len(sub_lines) * 37 + 44
        if box_top + box_h <= 1190:
            canvas = _composite_rounded_box(
                canvas,
                (margin_x, box_top, CARD_WIDTH - margin_x, box_top + box_h),
                radius=16,
                fill=style["panel_bg"],
                outline=style["panel_outline"],
                width=1,
            )
            draw = ImageDraw.Draw(canvas)
            _draw_text_lines(draw, sub_lines, margin_x + 28, box_top + 22, 37, sub_font, style["secondary"])

    canvas = _draw_progress_footer(
        canvas,
        current_idx=slide_idx,
        total_slides=total_slides,
        handle=handle,
        label="IN DEPTH",
        accent=accent,
        muted_fill=style["muted"],
        divider_fill=style["divider"],
        badge_bg=style["badge_bg"],
        badge_text=style["badge_text"],
        badge_outline=style["badge_outline"],
        margin_x=margin_x,
    )
    return _apply_analog_grain(canvas, strength=style["grain"])


def _render_closing_slide(
    theme: str,
    topic: dict,
    palette: tuple[tuple[int, int, int], ...],
    seed: int,
    handle: str,
    trailing_blocks: list[str],
    discussion_prompt: str,
    total_slides: int,
    hero_photo: Image.Image | None,
) -> Image.Image:
    """Final recap + interactive question panel + verified publisher attribution + CTA."""
    accent, _, _, _ = palette
    canvas, style = _create_inner_surface(theme, topic, palette, seed + 1, handle, hero_photo=hero_photo)
    margin_x = 68
    content_w = CARD_WIDTH - margin_x * 2
    section_title = "KEY TAKEAWAY" if trailing_blocks else "JOIN THE CONVERSATION"
    canvas, cursor_y = _draw_inner_header(canvas, topic, section_title, style, margin_x=margin_x)

    draw = ImageDraw.Draw(canvas)
    body_end = cursor_y + 10
    if trailing_blocks:
        takeaway_font = _load_font("regular", 28)
        t_lines = _wrap_text(draw, trailing_blocks[0], takeaway_font, content_w - 56, max_lines=6)
        box_h = len(t_lines) * 39 + 44
        canvas = _composite_rounded_box(
            canvas,
            (margin_x, cursor_y, CARD_WIDTH - margin_x, cursor_y + box_h),
            radius=16,
            fill=style["panel_bg"],
            outline=style["panel_outline"],
            width=1,
        )
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((margin_x + 2, cursor_y + 18, margin_x + 6, cursor_y + box_h - 18), fill=style["accent"])
        _draw_text_lines(draw, t_lines, margin_x + 28, cursor_y + 22, 39, takeaway_font, style["primary"])
        body_end = cursor_y + box_h + 26

    inner_x = margin_x + 36
    inner_w = content_w - 72
    q_font = _load_font("serif_bold", 34)
    prompt_text = discussion_prompt.strip() or "What is your take on this development?"
    q_lines = _wrap_text(draw, prompt_text, q_font, inner_w, max_lines=4)
    panel_top = max(360 if not trailing_blocks else 560, min(800, body_end + 14))
    q_end = panel_top + 74 + len(q_lines) * 44
    divider_y = q_end + 28
    panel_bottom = min(1185, divider_y + 124)

    canvas = _composite_rounded_box(
        canvas,
        (margin_x, panel_top, CARD_WIDTH - margin_x, panel_bottom),
        radius=20,
        fill=style["panel_bg"],
        outline=style["panel_accent_outline"],
        width=2,
    )
    draw = ImageDraw.Draw(canvas)
    eyebrow_font = _load_font("mono", 16)
    draw.text((inner_x, panel_top + 30), "YOUR TAKE?", font=eyebrow_font, fill=style["accent"])
    _draw_text_lines(draw, q_lines, inner_x, panel_top + 74, 44, q_font, style["primary"])

    draw.line((inner_x, divider_y, CARD_WIDTH - margin_x - 36, divider_y), fill=style["divider"], width=1)
    domain = _strip_invisible(topic.get("allowed_host") or "official release").lower()
    cta_title_font = _load_font("semibold", 20)
    cta_sub_font = _load_font("regular", 19)
    draw.text(
        (inner_x, divider_y + 22),
        f"FULL ARTICLE & DISCUSSION ON THREADS  ·  {handle.upper()}",
        font=cta_title_font,
        fill=style["primary"],
    )
    draw.text(
        (inner_x, divider_y + 56),
        f"Tap link in bio for the verified {domain} release.",
        font=cta_sub_font,
        fill=style["muted"],
    )

    canvas = _draw_progress_footer(
        canvas,
        current_idx=total_slides,
        total_slides=total_slides,
        handle=handle,
        label="END OF BRIEF",
        accent=accent,
        muted_fill=style["muted"],
        divider_fill=style["divider"],
        badge_bg=style["badge_bg"],
        badge_text=style["badge_text"],
        badge_outline=style["badge_outline"],
        margin_x=margin_x,
    )
    return _apply_analog_grain(canvas, strength=style["grain"])


def _paginate_inner_blocks(blocks: list[str], max_mid_slides: int, has_extra_photos: int = 0) -> tuple[list[list[str]], list[str]]:
    """Distribute remaining short blocks into scannable inner slides + closing slide."""
    if not blocks or max_mid_slides <= 0:
        return [], blocks[:1]
    mid_pages: list[list[str]] = []
    idx = 0
    while idx < len(blocks) and len(mid_pages) < max_mid_slides:
        slide_num = len(mid_pages) + 1
        # Keep slides scannable: fewer blocks when pairing with a secondary source photo.
        cap = 2 if slide_num <= has_extra_photos else (3 if len(blocks) - idx >= 4 else 2)
        if len(blocks) - idx <= 1 and len(mid_pages) >= 1:
            break
        take = min(cap, max(1, len(blocks) - idx))
        mid_pages.append(blocks[idx : idx + take])
        idx += take
    trailing = blocks[idx : idx + 1]
    return mid_pages, trailing


def render_news_card(
    topic: dict,
    output_path: str | Path,
    handle: str = "@thechronobyte",
    theme: str | None = None,
    source_images: list[dict] | list[Image.Image] | None = None,
) -> Path:
    """Render a 1080x1350 editorial JPEG news card using dynamic layout + source imagery."""
    started = time.monotonic()
    coerced_imgs = _coerce_source_images(source_images, topic)
    chosen_theme, mode, palette, palette_idx, palette_count, seed = _select_theme_and_palette(
        topic, theme, coerced_imgs
    )
    blocks = _build_body_blocks(topic, max_blocks=4, split_long=True, target_chars=210)
    deck, _ = _short_cover_deck(blocks, max_chars=165)

    serif_font = _resolve_font_path("serif_bold") or _resolve_font_path("serif")
    sans_font = _resolve_font_path("regular")
    LOGGER.info(
        "[4/6 Card] Rendering %dx%d JPEG | layout=%s (%s) | palette=%d/%d | source=%s | "
        "source_images=%d | fonts=(serif=%s, sans=%s)",
        CARD_WIDTH,
        CARD_HEIGHT,
        chosen_theme,
        mode,
        palette_idx + 1,
        palette_count,
        _strip_invisible(topic.get("source", "Tech News")),
        len(coerced_imgs),
        serif_font.name if serif_font else "pillow-default",
        sans_font.name if sans_font else "pillow-default",
    )

    canvas = _THEME_RENDERERS[chosen_theme](
        topic, palette, seed, handle, coerced_imgs, deck_override=deck, total_slides=1
    )
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
) -> list[Path]:
    """Render a dynamic multi-slide (2-5 cards) 1080x1350 Instagram carousel with source photos."""
    if max_slides < 2:
        return [
            render_news_card(
                topic,
                Path(output_dir) / f"{stem}-01.jpg",
                handle=handle,
                theme=theme,
                source_images=source_images,
            )
        ]

    started = time.monotonic()
    coerced_imgs = _coerce_source_images(source_images, topic)
    chosen_theme, mode, palette, palette_idx, palette_count, seed = _select_theme_and_palette(
        topic, theme, coerced_imgs
    )
    all_blocks = _build_body_blocks(topic, max_blocks=14, split_long=True, target_chars=230)
    deck, consumed_cover = _short_cover_deck(all_blocks, max_chars=165)

    remaining_blocks = all_blocks[consumed_cover:]
    extra_photos = coerced_imgs[1:]
    mid_pages, trailing_blocks = _paginate_inner_blocks(
        remaining_blocks,
        max_mid_slides=max(0, max_slides - 2),
        has_extra_photos=len(extra_photos),
    )
    total_slides = 2 + len(mid_pages)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    serif_font = _resolve_font_path("serif_bold") or _resolve_font_path("serif")
    sans_font = _resolve_font_path("regular")
    LOGGER.info(
        "[4/6 Card] Rendering %d-slide %dx%d carousel | layout=%s (%s) | palette=%d/%d | source=%s | "
        "source_images=%d | blocks=%d (mid_slides=%d, closing=%d) | fonts=(serif=%s, sans=%s)",
        total_slides,
        CARD_WIDTH,
        CARD_HEIGHT,
        chosen_theme,
        mode,
        palette_idx + 1,
        palette_count,
        _strip_invisible(topic.get("source", "Tech News")),
        len(coerced_imgs),
        len(all_blocks),
        len(mid_pages),
        len(trailing_blocks),
        serif_font.name if serif_font else "pillow-default",
        sans_font.name if sans_font else "pillow-default",
    )

    saved_paths: list[Path] = []
    prompt_text = discussion_prompt or str(topic.get("discussion_prompt") or "")
    hero_photo = coerced_imgs[0]["image"] if coerced_imgs else None

    cover_img = _THEME_RENDERERS[chosen_theme](
        topic, palette, seed, handle, coerced_imgs, deck_override=deck, total_slides=total_slides
    )
    slide1_path = out_dir / f"{stem}-01.jpg"
    cover_img.convert("RGB").save(slide1_path, format="JPEG", quality=95, optimize=True)
    saved_paths.append(slide1_path)

    for idx, page_blocks in enumerate(mid_pages, start=2):
        sec_title = _CONTINUATION_SECTIONS[(idx - 2) % len(_CONTINUATION_SECTIONS)]
        extra_idx = idx - 2
        if extra_idx < len(extra_photos):
            slide_img = _render_photo_feature_slide(
                chosen_theme,
                topic,
                palette,
                seed + idx,
                handle,
                sec_title,
                page_blocks,
                slide_idx=idx,
                total_slides=total_slides,
                feature_photo=extra_photos[extra_idx],
                hero_photo=hero_photo,
            )
        elif idx % 2 == 1 and len(page_blocks) <= 2:
            slide_img = _render_pull_quote_slide(
                chosen_theme,
                topic,
                palette,
                seed + idx,
                handle,
                "HIGHLIGHT",
                page_blocks,
                slide_idx=idx,
                total_slides=total_slides,
                hero_photo=hero_photo,
            )
        else:
            slide_img = _render_fact_grid_slide(
                chosen_theme,
                topic,
                palette,
                seed + idx,
                handle,
                sec_title,
                page_blocks,
                slide_idx=idx,
                total_slides=total_slides,
                hero_photo=hero_photo,
            )
        slide_path = out_dir / f"{stem}-{idx:02d}.jpg"
        slide_img.convert("RGB").save(slide_path, format="JPEG", quality=95, optimize=True)
        saved_paths.append(slide_path)

    closing_img = _render_closing_slide(
        chosen_theme,
        topic,
        palette,
        seed + total_slides,
        handle,
        trailing_blocks,
        prompt_text,
        total_slides=total_slides,
        hero_photo=hero_photo,
    )
    closing_path = out_dir / f"{stem}-{total_slides:02d}.jpg"
    closing_img.convert("RGB").save(closing_path, format="JPEG", quality=95, optimize=True)
    saved_paths.append(closing_path)

    sizes_kb = [round(p.stat().st_size / 1024.0, 1) for p in saved_paths]
    LOGGER.info(
        "[4/6 Card] Saved %d carousel JPEG slides to %s (sizes_kb=%s, total=%.1f KB, %.2fs)",
        len(saved_paths),
        out_dir,
        sizes_kb,
        sum(sizes_kb),
        time.monotonic() - started,
    )
    return saved_paths
