"""Generate editorial 1080x1350 (4:5) JPEG news cards for Instagram & Threads."""

from pathlib import Path
import unicodedata
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CARD_WIDTH = 1080
CARD_HEIGHT = 1350

SOURCE_ACCENTS = {
    "OpenAI": (16, 163, 127),            # #10A37F
    "NVIDIA": (118, 185, 0),             # #76B900
    "Google AI": (66, 133, 244),         # #4285F4
    "AMD": (237, 28, 36),                # #ED1C24
    "Microsoft Research": (0, 164, 239), # #00A4EF
}
DEFAULT_ACCENT = (99, 102, 241)

FONT_CANDIDATES = {
    "bold": (
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ),
    "semibold": (
        "C:/Windows/Fonts/seguisb.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
    "regular": (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    ),
    "mono": (
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
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
        # Handle single ultra-long token cleanly.
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


def _draw_background(accent: tuple[int, int, int]) -> Image.Image:
    """Create dark obsidian canvas with soft source-colored glow and subtle dot grid."""
    base = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (10, 13, 20, 255))

    glow_layer = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    # Top-right primary glow + bottom-left secondary glow.
    glow_draw.ellipse((540, -180, 1260, 540), fill=(*accent, 52))
    glow_draw.ellipse((-240, 880, 440, 1520), fill=(*accent, 34))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=140))
    base = Image.alpha_composite(base, glow_layer)

    grid_layer = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid_layer)
    for x in range(48, CARD_WIDTH, 48):
        for y in range(48, CARD_HEIGHT, 48):
            grid_draw.rectangle((x, y, x + 1, y + 1), fill=(255, 255, 255, 16))
    base = Image.alpha_composite(base, grid_layer)
    return base


def _draw_pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    label: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None,
    text_fill: tuple[int, int, int, int],
    pad_x: int = 22,
    pad_y: int = 11,
) -> int:
    """Draw a rounded badge pill and return its right edge x-coordinate."""
    x, y = xy
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    w = tw + pad_x * 2
    h = th + pad_y * 2
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=fill, outline=outline, width=2)
    draw.text((x + pad_x - bbox[0], y + pad_y - bbox[1]), label, font=font, fill=text_fill)
    return x + w


def _strip_invisible(text: str) -> str:
    """Remove format/control chars (e.g. U+2060 word joiner) that render as boxes."""
    return " ".join(
        "".join(ch for ch in text if unicodedata.category(ch) not in {"Cs", "Cf"}).split()
    )


def _build_body_paragraphs(topic: dict) -> list[str]:
    """Select clean readable context paragraphs distinct from the headline."""
    title_low = _strip_invisible(topic["text"]).lower()
    raw_items = list(topic.get("paragraphs") or [])
    summary = (topic.get("summary") or "").strip()
    if summary:
        raw_items.append(summary)

    selected: list[str] = []
    for item in raw_items:
        cleaned = _strip_invisible(item).rstrip("…")
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
        selected.append(cleaned)
        if len(selected) == 2:
            break
    return selected


def render_news_card(topic: dict, output_path: str | Path, handle: str = "@thechronobyte") -> Path:
    """Render a 1080x1350 editorial JPEG card for the given news topic."""
    source = _strip_invisible(topic.get("source", "Tech News"))
    headline_text = _strip_invisible(topic["text"])
    accent = SOURCE_ACCENTS.get(source, DEFAULT_ACCENT)
    canvas = _draw_background(accent)
    # Draw translucent chrome on a separate RGBA layer so alpha blends cleanly.
    chrome = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    chrome_draw = ImageDraw.Draw(chrome)

    margin = 76
    content_width = CARD_WIDTH - margin * 2

    font_brand = _load_font("semibold", 24)
    font_sub = _load_font("regular", 19)
    font_pill = _load_font("bold", 20)
    font_headline = _load_font("bold", 60)
    font_body = _load_font("regular", 32)
    font_footer_title = _load_font("semibold", 24)
    font_footer_sub = _load_font("regular", 21)

    # Top header bar.
    dot_y = 78
    chrome_draw.rounded_rectangle((margin, dot_y + 5, margin + 16, dot_y + 21), radius=4, fill=(*accent, 255))
    chrome_draw.text((margin + 28, dot_y), "CHRONO BYTE", font=font_brand, fill=(248, 250, 252, 255))
    chrome_draw.text((margin + 28, dot_y + 32), "DAILY AI & SILICON BRIEF", font=font_sub, fill=(148, 163, 184, 255))

    published = topic["published"]
    date_label = published.strftime("%b %d, %Y").upper().replace(" 0", " ")
    _draw_pill(
        chrome_draw,
        (CARD_WIDTH - margin - int(_text_width(chrome_draw, date_label, font_pill)) - 44, dot_y + 4),
        date_label,
        font_pill,
        fill=(255, 255, 255, 18),
        outline=(255, 255, 255, 42),
        text_fill=(203, 213, 225, 255),
    )

    chrome_draw.line((margin, 162, CARD_WIDTH - margin, 162), fill=(255, 255, 255, 28), width=2)

    # Source + Topic pills.
    pill_y = 202
    next_x = _draw_pill(
        chrome_draw,
        (margin, pill_y),
        source.upper(),
        font_pill,
        fill=(*accent, 46),
        outline=(*accent, 195),
        text_fill=(248, 250, 252, 255),
    )
    topic_tag = _strip_invisible(topic.get("topic_tag") or "")
    if topic_tag and topic_tag.lower() != source.lower():
        _draw_pill(
            chrome_draw,
            (next_x + 16, pill_y),
            topic_tag.upper(),
            font_pill,
            fill=(30, 41, 59, 200),
            outline=(100, 116, 139, 130),
            text_fill=(203, 213, 225, 255),
        )

    # Bottom footer card (translucent glass).
    footer_top = 1146
    chrome_draw.rounded_rectangle(
        (margin, footer_top, CARD_WIDTH - margin, 1272),
        radius=24,
        fill=(15, 23, 42, 185),
        outline=(255, 255, 255, 34),
        width=2,
    )
    chrome_draw.text((margin + 30, footer_top + 26), handle, font=font_footer_title, fill=(248, 250, 252, 255))
    host = urlsplit(topic.get("source_url", "")).hostname or "official source"
    chrome_draw.text(
        (margin + 30, footer_top + 64),
        f"Source: {host}  ·  Full thread on Threads",
        font=font_footer_sub,
        fill=(148, 163, 184, 255),
    )

    cta = "READ FULL STORY"
    cta_w = int(_text_width(chrome_draw, cta, font_pill)) + 44
    _draw_pill(
        chrome_draw,
        (CARD_WIDTH - margin - cta_w - 28, footer_top + 38),
        cta,
        font_pill,
        fill=(*accent, 235),
        outline=None,
        text_fill=(10, 13, 20, 255),
    )

    canvas = Image.alpha_composite(canvas, chrome)
    draw = ImageDraw.Draw(canvas)

    # Main headline.
    headline_lines = _wrap_text(draw, headline_text, font_headline, content_width, max_lines=4)
    if len(headline_lines) >= 4:
        font_headline = _load_font("bold", 52)
        headline_lines = _wrap_text(draw, headline_text, font_headline, content_width, max_lines=4)

    y = 286
    line_step = int(font_headline.size * 1.2)
    for line in headline_lines:
        draw.text((margin, y), line, font=font_headline, fill=(248, 250, 252, 255))
        y += line_step

    # Accent divider bar.
    y += 18
    draw.rounded_rectangle((margin, y, margin + 96, y + 6), radius=3, fill=(*accent, 255))
    y += 38

    # Body paragraphs (clipped cleanly above footer card).
    max_body_y = footer_top - 42
    body_step = 46
    paragraphs = _build_body_paragraphs(topic)
    for para in paragraphs:
        remaining_lines = max(0, (max_body_y - y) // body_step)
        if remaining_lines < 2:
            break
        wrapped = _wrap_text(draw, para, font_body, content_width, max_lines=remaining_lines)
        for line in wrapped:
            draw.text((margin, y), line, font=font_body, fill=(203, 213, 225, 255))
            y += body_step
        y += 20

    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(dest, format="JPEG", quality=95, optimize=True)
    return dest
