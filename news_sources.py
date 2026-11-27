"""Primary-source registry, feed normalization, and fail-closed article checks.

These checks establish provenance and freshness, not independent proof that a
publisher's claims are true. No search snippets, rumors or model output qualify.
"""

import hashlib
import ipaddress
import json
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

LOGGER = logging.getLogger(__name__)

NEWS_FEEDS = (
    ("OpenAI", "https://openai.com/news/rss.xml", "openai.com"),
    ("NVIDIA", "https://blogs.nvidia.com/feed/", "blogs.nvidia.com"),
    ("Google AI", "https://blog.google/technology/ai/rss/", "blog.google"),
    ("AMD", "https://ir.amd.com/news-events/press-releases/rss", "ir.amd.com"),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/", "www.microsoft.com"),
    ("Apple", "https://www.apple.com/newsroom/rss-feed.rss", "www.apple.com"),
    ("Meta", "https://about.fb.com/news/feed/", "about.fb.com"),
    ("Microsoft", "https://blogs.microsoft.com/feed/", "blogs.microsoft.com"),
    ("Xbox", "https://news.xbox.com/en-us/feed/", "news.xbox.com"),
    ("PlayStation", "https://blog.playstation.com/feed/", "blog.playstation.com"),
    ("Samsung", "https://news.samsung.com/global/feed", "news.samsung.com"),
    ("Google Devices", "https://blog.google/products-and-platforms/devices/pixel/rss/", "blog.google"),
    ("NASA", "https://www.nasa.gov/news-release/feed/", "www.nasa.gov"),
    ("Amazon", "https://www.aboutamazon.com/rss/feed.rss", "www.aboutamazon.com"),
    ("AWS", "https://aws.amazon.com/blogs/aws/feed/", "aws.amazon.com"),
    ("AWS Machine Learning", "https://aws.amazon.com/blogs/machine-learning/feed/", "aws.amazon.com"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "deepmind.google"),
    ("GitHub", "https://github.blog/feed/", "github.blog"),
    ("Cloudflare", "https://blog.cloudflare.com/rss/", "blog.cloudflare.com"),
    ("Cisco", "https://blogs.cisco.com/feed", "blogs.cisco.com"),
    ("Salesforce", "https://www.salesforce.com/news/feed/?bc=DB", "www.salesforce.com"),
    ("Stripe", "https://stripe.com/blog/feed.rss", "stripe.com"),
    ("Mozilla", "https://blog.mozilla.org/en/feed/", "blog.mozilla.org"),
    ("IBM", "https://newsroom.ibm.com/announcements?pagetemplate=rss", "newsroom.ibm.com"),
    # These publishers use official newsrooms/sitemaps instead of public RSS.
    ("Figma", "https://www.figma.com/blog/", "www.figma.com"),
    ("Anthropic", "https://www.anthropic.com/news", "www.anthropic.com"),
    ("Notion", "https://www.notion.com/blog", "www.notion.com"),
    ("JPMorganChase", "https://www.jpmorganchase.com/sitemap.xml", "www.jpmorganchase.com"),
    ("Comcast", "https://corporate.comcast.com/press", "corporate.comcast.com"),
    # Gaming news, launches & leaks.
    ("IGN", "https://www.ign.com/rss/articles/feed", "www.ign.com"),
    ("Eurogamer", "https://www.eurogamer.net/feed/news", "www.eurogamer.net"),
    ("PC Gamer", "https://www.pcgamer.com/rss/", "www.pcgamer.com"),
    ("Polygon", "https://www.polygon.com/rss/index.xml", "www.polygon.com"),
    # Latest mobile news, flagships & leaks/rumors.
    ("9to5Mac", "https://9to5mac.com/feed/", "9to5mac.com"),
    ("9to5Google", "https://9to5google.com/feed/", "9to5google.com"),
    ("Android Authority", "https://www.androidauthority.com/feed/", "www.androidauthority.com"),
    ("Android Police", "https://www.androidpolice.com/feed/", "www.androidpolice.com"),
    ("MacRumors", "https://feeds.macrumors.com/MacRumors-All", "www.macrumors.com"),
    # Latest tech news, upcoming hardware, gadgets & rumors.
    ("The Verge", "https://www.theverge.com/rss/index.xml", "www.theverge.com"),
    ("TechCrunch", "https://techcrunch.com/feed/", "techcrunch.com"),
    ("Tom's Hardware", "https://www.tomshardware.com/feeds.xml", "www.tomshardware.com"),
    ("XDA Developers", "https://www.xda-developers.com/feed/", "www.xda-developers.com"),
    ("Engadget", "https://www.engadget.com/rss.xml", "www.engadget.com"),
    ("Gizmodo", "https://gizmodo.com/feed", "gizmodo.com"),
    ("TechSpot", "https://www.techspot.com/backend.xml", "www.techspot.com"),
    ("NotebookCheck", "https://www.notebookcheck.net/News.152.100.html", "www.notebookcheck.net"),
)
SOURCE_CATEGORIES = {
    "Apple": "Tech Industry", "Meta": "Tech Industry", "Microsoft": "Tech Industry",
    "Xbox": "Video Games", "PlayStation": "Video Games", "Samsung": "New Technology",
    "Google Devices": "Mobile Phones", "NASA": "Space Programs",
    "Amazon": "Tech Industry", "AWS": "Cloud Computing",
    "AWS Machine Learning": "Machine Learning", "Google DeepMind": "Artificial Intelligence",
    "GitHub": "Developer Tools", "Cloudflare": "Cybersecurity", "Cisco": "Connectivity",
    "Salesforce": "Productivity", "Stripe": "Financial Technology", "Mozilla": "Developer Tools",
    "IBM": "Tech Industry", "Figma": "Design Tools", "Anthropic": "Claude",
    "Notion": "Productivity", "JPMorganChase": "Financial Technology", "Comcast": "Connectivity",
    "IGN": "Video Games", "Eurogamer": "Video Games", "PC Gamer": "Video Games", "Polygon": "Video Games",
    "9to5Mac": "Mobile Phones", "9to5Google": "Mobile Phones",
    "Android Authority": "Mobile Phones", "Android Police": "Mobile Phones", "MacRumors": "Mobile Phones",
    "The Verge": "Tech Industry", "TechCrunch": "Tech Industry",
    "Tom's Hardware": "Computer Hardware", "XDA Developers": "Mobile Phones",
    "Engadget": "Tech Industry", "Gizmodo": "Tech Industry",
    "TechSpot": "Computer Hardware", "NotebookCheck": "Upcoming Tech",
}
REQUIRES_TECH_MATCH = frozenset({
    "Amazon", "Comcast", "IBM", "The Verge", "TechCrunch", "Engadget", "Gizmodo", "Polygon", "IGN",
})
NEWSROOM_PATHS = {
    "Figma": r"^/blog/[^/]+/?$",
    "Anthropic": r"^/news/[^/]+/?$",
    "Notion": r"^/blog/[^/]+/?$",
    "JPMorganChase": r"^/about/technology/blog/[^/]+/?$",
    "Comcast": r"^/(?:press/releases|stories|news-information/news-feed)/.+$",
}
MAX_NEWSROOM_ARTICLES = 6
# Explicit publisher host exceptions (official feed/blog host pairs).
PUBLISHER_HOSTS = {
    "deepmind.google": ("deepmind.google", "blog.google"),
    "www.macrumors.com": ("www.macrumors.com", "feeds.macrumors.com"),
}
VISIBLE_DATE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b"
)
PRICE_PATTERN = re.compile(r"\b(pric(?:e|es|ing)|msrp|costs?|discounts?|retail\s+offers?)\b", re.I)
RUMOR_PATTERN = re.compile(
    r"\b(rumou?rs?|rumou?red|unconfirmed|leaks?|leaked|leaker|tipster|insiders?|"
    r"speculation|reportedly|allegedly|purportedly|said to|tipped to|cad renders?|"
    r"geekbench leak|benchmark leak|early render|supply chain report)\b",
    re.I,
)
UPCOMING_PATTERN = re.compile(
    r"\b(upcoming|next[- ]gen|next generation|teased|teaser|prototype|roadmap|"
    r"coming soon|launching soon|expected in 202\d|first look|hands[- ]on|spotted on geekbench)\b",
    re.I,
)
DEALS_SPAM_PATTERN = re.compile(
    r"\b(black friday|cyber monday|prime day|best deals?|on sale|gift guide|buying guide|"
    r"save \$?\d+|up to \d+%\s*off|\d+%\s*off|lowest price|price drop|coupon|promo code|"
    r"wordle|connections hints|strands hints|mini crossword|merino wool|best .* to buy)\b",
    re.I,
)
RUMOR_SOFT_SOURCES = frozenset({"MacRumors"})
GOOGLE_TRENDS_RSS = "https://trends.google.com/trending/rss?geo={geo}"
AMOUNT_PATTERN = re.compile(r"(?:US\$|AU\$|CA\$|USD|INR|EUR|GBP|AUD|CAD|JPY|Rs\.?|[₹$€£¥])\s*\d[\d,.]*", re.I)
ATOM = "{http://www.w3.org/2005/Atom}"
MAX_BYTES = 4_000_000
MAX_IMAGE_BYTES = 8_000_000
MAX_CSS_BYTES = 350_000
_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_RGB_COLOR_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*[\d.]+)?\s*\)", re.I)
_CSS_ACCENT_VAR_RE = re.compile(
    r"--[a-z0-9_-]*(?:accent|brand|primary|highlight|theme|link|cta|tint|fill)[a-z0-9_-]*\s*:\s*([^;}{]+)",
    re.I,
)
_CSS_BG_DECL_RE = re.compile(
    r"(?:--[a-z0-9_-]*(?:bg|background|surface|canvas)[a-z0-9_-]*|background(?:-color)?)\s*:\s*([^;}{]+)",
    re.I,
)
_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
_NON_PHOTO_IMAGE = re.compile(
    r"(?:favicon|apple-touch-icon|/(?:icons?|avatars?|logos?|badges?|sprites?)/|"
    r"(?:^|[/_-])(?:logo|avatar|icon|badge|sprite|pixel|spacer|placeholder)[._-]|"
    r"/_next/image|\.(?:svg|ico|gif)(?:$|[?#]))",
    re.I,
)
_SKIP_CONTAINER_HINT = re.compile(
    r"(?:author|byline|bio[-_]|[-_]bio\b|related[-_]?(?:posts?|articles?)|"
    r"newsletter|subscribe|affiliate|disclaimer|comment[-_]?list|comments|sidebar|breadcrumb|social[-_]?share)",
    re.I,
)
_BOILERPLATE_OR_BIO = re.compile(
    r"cookies|privacy policy|sign up|subscribe|all rights reserved|affiliate links?|earn a commission|"
    r"i['’]ve been writing|i have been writing|throughout my (?:writing )?career|"
    r"gives me deep insight|when (?:he|she|they)['’]?s? not writing|follow (?:him|her|them|me) on",
    re.I,
)


def approved_url(url: str, host: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https" and parsed.hostname in PUBLISHER_HOSTS.get(host, (host,))
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443)
            and not any(ord(c) < 33 or c == "\\" for c in url)
        )
    except ValueError:
        return False


def approved_image_url(url: str) -> bool:
    """Validate that an image URL is a clean public HTTPS asset (never private/local)."""
    if not url or any(ord(c) < 33 or c == "\\" for c in url):
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or "." not in host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or host in {"localhost", "localhost.localdomain"}
        or host.endswith((".local", ".internal", ".localhost", ".localdomain", ".arpa"))
    ):
        return False
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if not ip.is_global:
            return False
    except ValueError:
        pass
    return not _NON_PHOTO_IMAGE.search(url)


def fetch_image_bytes(url: str, contact: str) -> tuple[bytes, str, str]:
    """Download an official source image cleanly with public-HTTPS redirect and size caps."""
    for _ in range(4):
        if not approved_image_url(url):
            raise ValueError("Source image URL is not an approved public HTTPS asset.")
        with requests.get(
            url,
            headers={
                "User-Agent": f"DailyTechNewsBot/1.0 ({contact})",
                "Accept": "image/webp,image/png,image/jpeg,image/*;q=0.8",
            },
            timeout=(4, 10),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("Missing image redirect target.")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("Expected a complete image response.")
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and (not content_type.startswith("image/") or "svg" in content_type):
                raise ValueError("Source asset is not a raster image.")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    raise ValueError("Source image exceeds the download limit.")
                chunks.append(chunk)
            return b"".join(chunks), url, content_type
    raise ValueError("Too many image redirects.")


def fetch_source(url: str, host: str, contact: str) -> tuple[bytes, str, str]:
    """Check every redirect before requesting it; cap downloaded bytes."""
    for _ in range(4):
        if not approved_url(url, host):
            raise ValueError("Source URL left the approved HTTPS domain.")
        with requests.get(
            url, headers={"User-Agent": f"DailyTechNewsBot/1.0 ({contact})"},
            timeout=(3, 8), allow_redirects=False, stream=True,
        ) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("Missing redirect target.")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("Expected a complete source document.")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Source document exceeds the download limit.")
                chunks.append(chunk)
            return b"".join(chunks), url, response.headers.get("Content-Type", "").lower()
    raise ValueError("Too many source redirects.")


def parse_date(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        raise ValueError("Source date lacks a time zone.")
    return parsed.astimezone(timezone.utc)


def feed_items(content: bytes) -> list[ET.Element]:
    """Normalize Atom into RSS-shaped entries; enclosure links are never articles."""
    root = ET.fromstring(content)
    if root.tag == "rss" and root.find("channel") is not None:
        return root.findall("./channel/item")
    if root.tag != ATOM + "feed":
        raise ValueError("Not an RSS or Atom news feed.")
    items = []
    for entry in root.findall(ATOM + "entry"):
        item = ET.Element("item")
        for target, original in (("title", "title"), ("description", "summary")):
            ET.SubElement(item, target).text = entry.findtext(ATOM + original, "")
        links = [link for link in entry.findall(ATOM + "link")
                 if link.get("rel", "alternate") == "alternate"
                 and link.get("type", "text/html") == "text/html"]
        ET.SubElement(item, "link").text = links[0].get("href", "") if links else ""
        published = entry.findtext(ATOM + "published")
        item.set("date_kind", "published" if published else "updated")
        ET.SubElement(item, "pubDate").text = published or entry.findtext(ATOM + "updated", "")
        items.append(item)
    return items


class _NewsroomLinks(HTMLParser):
    """Discover only visible article links, not URLs hidden in scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.href = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.parts = []

    def handle_data(self, data):
        if self.href:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.parts)))
            self.href = None


def newsroom_links(source: str, content: bytes, base_url: str, host: str) -> list[str]:
    """Sitemap lastmod/listing dates rank discovery only; never prove publication."""
    candidates = []
    if source == "JPMorganChase":
        root = ET.fromstring(content)
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        if root.tag != ns + "urlset":
            raise ValueError("Expected the official URL sitemap.")
        candidates = [(node.findtext(ns + "loc", ""), node.findtext(ns + "lastmod", ""))
                      for node in root.findall(ns + "url")]
    else:
        parser = _NewsroomLinks()
        parser.feed(content.decode("utf-8", errors="replace"))
        for href, text in parser.links:
            match = VISIBLE_DATE.search(text)
            if source == "Figma" and not match:
                continue  # Its category/navigation links share the /blog/<slug> route.
            stamp = ""
            if match:
                for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
                    try:
                        stamp = datetime.strptime(match.group(), fmt).date().isoformat()
                        break
                    except ValueError:
                        continue
            candidates.append((href, stamp))
    # Keep listing order for undated/tied links; check the newest dated links first.
    candidates.sort(key=lambda pair: pair[1], reverse=True)
    urls = []
    for href, _ in candidates:
        url = urljoin(base_url, href)
        if (approved_url(url, host) and re.fullmatch(NEWSROOM_PATHS[source], urlsplit(url).path)
                and not urlsplit(url).query and not urlsplit(url).fragment and url not in urls):
            urls.append(url)
    return urls[:MAX_NEWSROOM_ARTICLES]


def article_publication_dates(parser) -> list[datetime]:
    """Read explicit publication dates; date-only values carry day precision."""
    dates = []
    for value in parser.dates:
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}Z?", value):
                dates.append(datetime.fromisoformat(value.rstrip("Z")).replace(tzinfo=timezone.utc))
            else:
                dates.append(parse_date(value))
        except (ValueError, TypeError, OverflowError):
            continue
    return dates


def load_newsroom(source: str, content: bytes, url: str, host: str, contact: str):
    """Read each original article for its title/date; cache its bytes for verification."""
    links = newsroom_links(source, content, url, host)
    if not links:
        raise ValueError("No supported article links in official newsroom.")
    items, cache = [], {}
    for link in links:
        try:
            document = fetch_source(link, host, contact)
            body, final_url, mime = document
            if "html" not in mime:
                continue
            parser = ArticleEvidence()
            parser.feed(body.decode("utf-8", errors="replace"))
            parser.close()
            dates = article_publication_dates(parser)
            if not dates or not parser.headings:
                continue
            title = (parser.h1_headings or parser.headings)[0].strip()
            if not title:
                continue
            item = ET.Element("item", date_kind="article")
            for tag, text in (("title", title), ("link", final_url), ("pubDate", min(dates).isoformat())):
                ET.SubElement(item, tag).text = text
            items.append(item)
            cache[final_url] = document
        except (requests.RequestException, ValueError) as error:
            LOGGER.warning("%s newsroom article unavailable (%s); skipping.", source, type(error).__name__)
    if not items:
        raise ValueError("Newsroom articles have no usable original headline/publication metadata.")
    return items, cache


def _parse_srcset_best(srcset: str) -> str:
    """Return the highest-resolution candidate URL from an HTML srcset string."""
    best_url = ""
    best_score = -1.0
    for part in srcset.split(","):
        tokens = part.strip().split()
        if not tokens:
            continue
        candidate = tokens[0]
        score = 1.0
        if len(tokens) > 1:
            desc = tokens[1].lower()
            try:
                if desc.endswith("w"):
                    score = float(desc[:-1])
                elif desc.endswith("x"):
                    score = float(desc[:-1]) * 1000.0
            except ValueError:
                pass
        if score > best_score:
            best_score = score
            best_url = candidate
    return best_url


def _parse_dim(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^\s*(\d+)", str(value))
    return int(match.group(1)) if match else None


class ArticleEvidence(HTMLParser):
    """Read page headings, publication metadata, paragraphs, media, and theme tokens inside main/article."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings, self.paragraphs, self.dates, self.canonicals = [], [], [], []
        self.h1_headings = []
        self.meta_images, self.schema_images, self.article_images = [], [], []
        self.theme_colors, self.color_schemes, self.stylesheet_urls = [], [], []
        self.inline_css_parts: list[str] = []
        self.svg_colors: list[str] = []
        self.scope = self.skip = 0
        self.skip_tag_stack: list[str] = []
        self.in_style = False
        self.capture = None
        self.parts = []
        self.json_parts = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.json_parts = []
        if tag == "style":
            self.in_style = True
        hint_blob = f"{attrs.get('class', '')} {attrs.get('id', '')}"
        if tag in {"nav", "footer", "aside", "script", "style", "form", "noscript"}:
            self.skip += 1
        elif tag in {"div", "section", "p", "figure", "header"} and _SKIP_CONTAINER_HINT.search(hint_blob):
            self.skip += 1
            self.skip_tag_stack.append(tag)
        if tag in {"article", "main"}:
            self.scope += 1
        inline_style = attrs.get("style", "")
        if inline_style and len(self.inline_css_parts) < 120:
            self.inline_css_parts.append(inline_style[:400])
        if tag in {"path", "rect", "circle", "polygon", "svg"} and len(self.svg_colors) < 80:
            for attr_name in ("fill", "stroke"):
                val = (attrs.get(attr_name) or "").strip()
                if val.startswith("#") or val.lower().startswith("rgb"):
                    self.svg_colors.append(val)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name", "")).lower()
            value = attrs.get("content", "")
            if key in {"og:title", "twitter:title"}:
                self.headings.append(value)
            if key in {"article:published_time", "datepublished", "date", "pubdate"}:
                self.dates.append(value)
            if key in {"og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"} and value:
                self.meta_images.append((key, value.strip()))
            if key in {"theme-color", "msapplication-tilecolor"} and value:
                self.theme_colors.append(value.strip())
            if key == "color-scheme" and value:
                self.color_schemes.append(value.strip().lower())
        if tag == "link":
            rel_tokens = set((attrs.get("rel") or "").lower().split())
            href = (attrs.get("href") or "").strip()
            if "canonical" in rel_tokens and href:
                self.canonicals.append(href)
            if "stylesheet" in rel_tokens and href and len(self.stylesheet_urls) < 6:
                self.stylesheet_urls.append(href)
        if not self.skip and self.scope and tag in {"img", "source"}:
            if tag == "source":
                media_type = (attrs.get("type") or "").lower()
                if media_type and not media_type.startswith("image/"):
                    return
                candidate = _parse_srcset_best(attrs.get("srcset", ""))
                alt, w, h = "", None, None
            else:
                srcset_best = _parse_srcset_best(attrs.get("srcset", ""))
                candidate = (
                    attrs.get("src")
                    or attrs.get("data-src")
                    or attrs.get("data-lazy-src")
                    or srcset_best
                    or ""
                ).strip()
                if candidate.startswith("data:") and srcset_best:
                    candidate = srcset_best
                alt = (attrs.get("alt") or "").strip()
                w = _parse_dim(attrs.get("width"))
                h = _parse_dim(attrs.get("height"))
            if candidate and not candidate.startswith("data:"):
                if (w is not None and w < 320) or (h is not None and h < 200):
                    return
                if not _NON_PHOTO_IMAGE.search(alt):
                    self.article_images.append(candidate)
        if self.capture == "h1" and tag in {"p", "h1", "h2", "h3", "div", "section", "article"}:
            self._flush_capture()
        if not self.skip and self.capture is None:
            if tag == "h1" or (tag == "p" and self.scope):
                self.capture, self.parts = tag, []

    def _flush_capture(self) -> None:
        if not self.capture:
            return
        text = " ".join("".join(self.parts).split())
        if self.capture == "h1":
            if text:
                self.headings.append(text)
                self.h1_headings.append(text)
        elif len(text) >= 50 and not _BOILERPLATE_OR_BIO.search(text):
            self.paragraphs.append(text)
        self.capture = None
        self.parts = []

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
        if tag == "script" and self.json_parts is not None:
            try:
                self._schema(json.loads("".join(self.json_parts)))
            except (ValueError, TypeError, RecursionError):
                pass
            self.json_parts = None
        if tag in {"nav", "footer", "aside", "script", "style", "form", "noscript"}:
            self.skip = max(0, self.skip - 1)
        elif self.skip_tag_stack and self.skip_tag_stack[-1] == tag:
            self.skip_tag_stack.pop()
            self.skip = max(0, self.skip - 1)
        if tag in {"article", "main"}:
            self.scope = max(0, self.scope - 1)
        if tag == self.capture:
            self._flush_capture()
        elif self.capture == "h1" and tag in {"header", "section", "article", "main", "div"}:
            self._flush_capture()

    def handle_data(self, data):
        if self.in_style and len(self.inline_css_parts) < 120:
            self.inline_css_parts.append(data[:8000])
        if self.json_parts is not None:
            self.json_parts.append(data)
        if self.capture and not self.skip:
            self.parts.append(data)

    def _add_schema_image(self, value) -> None:
        if isinstance(value, str) and value.strip():
            self.schema_images.append(value.strip())
        elif isinstance(value, dict):
            for key in ("url", "contentUrl"):
                if isinstance(value.get(key), str) and value[key].strip():
                    self.schema_images.append(value[key].strip())
        elif isinstance(value, list):
            for item in value:
                self._add_schema_image(item)

    def _schema(self, node):
        if isinstance(node, list):
            for item in node:
                self._schema(item)
        elif isinstance(node, dict):
            types = node.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if isinstance(types, list) and set(types) & {"NewsArticle", "Article", "BlogPosting", "TechArticle"}:
                if isinstance(node.get("datePublished"), str):
                    self.dates.append(node["datePublished"])
                if isinstance(node.get("headline"), str):
                    self.headings.append(node["headline"])
                if "image" in node:
                    self._add_schema_image(node["image"])
                if "thumbnailUrl" in node:
                    self._add_schema_image(node["thumbnailUrl"])
            if "@graph" in node:
                self._schema(node["@graph"])


def _parse_rgb_token(token: str) -> tuple[int, int, int] | None:
    """Parse #rgb, #rrggbb, or rgb(r,g,b) into an (R, G, B) tuple."""
    text = token.strip()
    m_hex = _HEX_COLOR_RE.search(text)
    if m_hex:
        h = m_hex.group(0)[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m_rgb = _RGB_COLOR_RE.search(text)
    if m_rgb:
        vals = tuple(int(m_rgb.group(i)) for i in (1, 2, 3))
        if all(0 <= v <= 255 for v in vals):
            return vals
    return None


def _color_chroma(rgb: tuple[int, int, int]) -> int:
    return max(rgb) - min(rgb)


def _color_luma(rgb: tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def parse_css_theme_tokens(css_text: str) -> dict:
    """Extract chromatic accents, dark/light surfaces, and serif/sans hints from raw CSS."""
    accent_counts: Counter[tuple[int, int, int]] = Counter()
    bg_counts: Counter[tuple[int, int, int]] = Counter()

    for match in _CSS_ACCENT_VAR_RE.finditer(css_text):
        rgb = _parse_rgb_token(match.group(1))
        if rgb and _color_chroma(rgb) >= 32:
            accent_counts[rgb] += 4

    for match in _CSS_BG_DECL_RE.finditer(css_text):
        rgb = _parse_rgb_token(match.group(1))
        if rgb:
            bg_counts[rgb] += 2

    for match in _HEX_COLOR_RE.finditer(css_text[:200_000]):
        rgb = _parse_rgb_token(match.group(0))
        if rgb and _color_chroma(rgb) >= 36:
            accent_counts[rgb] += 1

    serif_hits = 0
    sans_hits = 0
    for match in _FONT_FAMILY_RE.finditer(css_text[:200_000]):
        val = match.group(1).lower()
        if any(k in val for k in ("georgia", "garamond", "times", "merriweather", "playfair", "tiempos", "newsreader", "serif")) and "sans-serif" not in val:
            serif_hits += 1
        elif any(k in val for k in ("inter", "helvetica", "arial", "sf pro", "roboto", "sans-serif", "segoe", "geist", "sohne")):
            sans_hits += 1

    font_hint = ""
    if serif_hits > sans_hits and serif_hits > 0:
        font_hint = "serif"
    elif sans_hits > 0:
        font_hint = "sans"

    return {
        "accents": [list(rgb) for rgb, _ in accent_counts.most_common(6)],
        "backgrounds": [list(rgb) for rgb, _ in bg_counts.most_common(4)],
        "font_hint": font_hint,
    }


def extract_source_theme(parser: ArticleEvidence, base_url: str, allowed_host: str) -> dict:
    """Build a structured live theme summary directly from the verified source HTML."""
    meta_rgbs = [rgb for raw in parser.theme_colors if (rgb := _parse_rgb_token(raw)) is not None]
    css_blob = "\n".join(parser.inline_css_parts)
    parsed_css = parse_css_theme_tokens(css_blob)

    svg_counts: Counter[tuple[int, int, int]] = Counter()
    for raw in parser.svg_colors:
        rgb = _parse_rgb_token(raw)
        if rgb and _color_chroma(rgb) >= 36:
            svg_counts[rgb] += 1

    accents: list[list[int]] = []
    seen: set[tuple[int, int, int]] = set()
    for candidate in (
        [rgb for rgb in meta_rgbs if _color_chroma(rgb) >= 30]
        + [tuple(c) for c in parsed_css["accents"]]
        + [rgb for rgb, _ in svg_counts.most_common(4)]
    ):
        if candidate not in seen:
            seen.add(candidate)
            accents.append(list(candidate))

    backgrounds: list[list[int]] = []
    seen_bg: set[tuple[int, int, int]] = set()
    for candidate in meta_rgbs + [tuple(c) for c in parsed_css["backgrounds"]]:
        if candidate not in seen_bg:
            seen_bg.add(candidate)
            backgrounds.append(list(candidate))

    polarity = ""
    if any("dark" in cs and "light" not in cs for cs in parser.color_schemes):
        polarity = "dark"
    elif meta_rgbs:
        polarity = "dark" if _color_luma(meta_rgbs[0]) < 115 else "light"
    elif backgrounds:
        polarity = "dark" if _color_luma(tuple(backgrounds[0])) < 115 else "light"

    stylesheets: list[str] = []
    for raw_href in parser.stylesheet_urls:
        full_url = urljoin(base_url, raw_href)
        if full_url not in stylesheets and approved_url(full_url, allowed_host):
            stylesheets.append(full_url)

    return {
        "polarity": polarity,
        "accents": accents[:6],
        "backgrounds": backgrounds[:4],
        "font_hint": parsed_css["font_hint"],
        "stylesheet_urls": stylesheets[:3],
    }


def enrich_theme_from_stylesheets(theme: dict, allowed_host: str, contact: str, max_sheets: int = 2) -> dict:
    """Optionally scrape up to 2 approved same-domain stylesheets to enrich live source colors."""
    merged = {
        "polarity": theme.get("polarity", ""),
        "accents": list(theme.get("accents") or []),
        "backgrounds": list(theme.get("backgrounds") or []),
        "font_hint": theme.get("font_hint", ""),
        "stylesheet_urls": list(theme.get("stylesheet_urls") or []),
    }
    if len(merged["accents"]) >= 3 and merged["font_hint"]:
        return merged

    seen_acc = {tuple(c) for c in merged["accents"]}
    seen_bg = {tuple(c) for c in merged["backgrounds"]}
    fetched = 0
    for url in merged["stylesheet_urls"]:
        if fetched >= max_sheets or not approved_url(url, allowed_host):
            continue
        try:
            with requests.get(
                url,
                headers={"User-Agent": f"DailyTechNewsBot/1.0 ({contact})"},
                timeout=(3, 5),
                allow_redirects=False,
                stream=True,
            ) as resp:
                if resp.status_code != 200:
                    continue
                chunks, size = [], 0
                for chunk in resp.iter_content(32768):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_CSS_BYTES:
                        break
                css_text = b"".join(chunks).decode("utf-8", errors="ignore")
            fetched += 1
            tokens = parse_css_theme_tokens(css_text)
            for c in tokens["accents"]:
                tup = tuple(c)
                if tup not in seen_acc:
                    seen_acc.add(tup)
                    merged["accents"].append(c)
            for c in tokens["backgrounds"]:
                tup = tuple(c)
                if tup not in seen_bg:
                    seen_bg.add(tup)
                    merged["backgrounds"].append(c)
            if not merged["font_hint"] and tokens["font_hint"]:
                merged["font_hint"] = tokens["font_hint"]
            if not merged["polarity"] and merged["backgrounds"]:
                merged["polarity"] = "dark" if _color_luma(tuple(merged["backgrounds"][0])) < 115 else "light"
        except (requests.RequestException, ValueError):
            continue
    merged["accents"] = merged["accents"][:6]
    merged["backgrounds"] = merged["backgrounds"][:4]
    return merged


def collect_article_images(parser: ArticleEvidence, base_url: str, max_urls: int = 8) -> list[str]:
    """Resolve and prioritize verified HTTPS image URLs embedded in the official article."""
    meta_rank = {"og:image:secure_url": 0, "og:image": 1, "twitter:image": 2, "twitter:image:src": 3}
    ordered_meta = [url for _, url in sorted(parser.meta_images, key=lambda pair: meta_rank.get(pair[0], 9))]
    raw_candidates = ordered_meta + parser.schema_images + parser.article_images
    resolved: list[str] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        full_url = urljoin(base_url, raw.strip())
        if full_url not in seen and approved_image_url(full_url):
            seen.add(full_url)
            resolved.append(full_url)
            if len(resolved) >= max_urls:
                break
    return resolved


def is_rumor_story(title: str, source: str = "", paragraphs: list[str] | None = None) -> bool:
    """Detect whether a story is an unconfirmed leak/rumor so it is always labeled explicitly."""
    if RUMOR_PATTERN.search(title or ""):
        return True
    if source in RUMOR_SOFT_SOURCES and re.search(
        r"\b(could|may|might|expected|reported|analyst|kuo|gurman|ross young|supply chain)\b",
        title or "",
        re.I,
    ):
        return True
    lead = " ".join((paragraphs or [])[:2])
    return bool(lead and RUMOR_PATTERN.search(lead))


def fetch_google_trends(geos: tuple[str, ...] = ("US", "IN"), contact: str = "local preview") -> list[str]:
    """Best-effort fetch of live Google Trends daily RSS topics (free, zero API keys)."""
    terms: list[str] = []
    seen: set[str] = set()
    for geo in geos:
        url = GOOGLE_TRENDS_RSS.format(geo=geo)
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": f"DailyTechNewsBot/1.0 ({contact})"},
                timeout=(3, 5),
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall("./channel/item"):
                raw = (item.findtext("title") or "").strip()
                norm = " ".join(raw.split())
                if norm and norm.lower() not in seen:
                    seen.add(norm.lower())
                    terms.append(norm)
        except (requests.RequestException, ET.ParseError, ValueError):
            continue
    return terms


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", unescape(text)).casefold())


def price_evidence(paragraphs: list[str]) -> list[dict]:
    """Require amount/currency and an explicit market in the same paragraph.

    Do not infer a market from currency or convert a manufacturer's announced
    price to a current retail price. Ambiguous dollar signs do not qualify.
    """
    markets = (
        (r"(?<!\w)(?:United States|U\.S\.|US market|USA)(?!\w)", "United States", "USD", r"(?:US\$|USD|\$)"),
        (r"\bIndia\b", "India", "INR", r"(?:INR|Rs\.?|₹)"),
        (r"\b(?:United Kingdom|UK)\b", "United Kingdom", "GBP", r"(?:GBP|£)"),
        (r"\bCanada\b", "Canada", "CAD", r"(?:CAD|CA\$|\$)"),
        (r"\bAustralia\b", "Australia", "AUD", r"(?:AUD|AU\$|\$)"),
        (r"\bJapan\b", "Japan", "JPY", r"(?:JPY|¥)"),
        (r"\b(?:Germany|France|Eurozone|European Union)\b", None, "EUR", r"(?:EUR|€)"),
    )
    evidence = []
    for text in paragraphs:
        dollar_markets = sum(bool(re.search(pattern, text, re.I))
                             for pattern, _, code, _ in markets if code in {"USD", "CAD", "AUD"})
        for market_pattern, market, currency, amount_prefix in markets:
            match = re.search(market_pattern, text, re.I)
            if not match:
                continue
            if dollar_markets > 1:
                amount_prefix = amount_prefix.replace("|\\$", "")
            amounts = re.findall(amount_prefix + r"\s*\d[\d,.]*", text, re.I)
            if amounts:
                evidence.append({"market": market or match.group(), "currency": currency,
                                 "amounts": amounts, "quote": text, "basis": "publisher announcement"})
    return evidence


def verify_article(story: dict, contact: str, now: datetime, max_age_hours: int, document=None) -> dict:
    """Reject an unverifiable page rather than filling gaps with generated text."""
    content, final_url, content_type = document or fetch_source(story["source_url"], story["allowed_host"], contact)
    if not approved_url(final_url, story["allowed_host"]):
        raise ValueError("Cached article left the approved source domain.")
    if "html" not in content_type:
        raise ValueError("Article response is not HTML.")
    parser = ArticleEvidence()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    title_words = _words(story["text"])
    if len(title_words) < 3 or not any(
        _words(heading)[:len(title_words)] == title_words for heading in parser.headings
    ):
        raise ValueError("Original page does not confirm the feed headline.")
    for link in parser.canonicals:
        canonical = urljoin(final_url, link)
        if (not approved_url(canonical, story["allowed_host"])
                or urlsplit(canonical).path.rstrip("/") != urlsplit(final_url).path.rstrip("/")):
            raise ValueError("Article canonical URL does not identify the requested source page.")
    published = story["published"]
    dates = article_publication_dates(parser)
    if dates:
        published = min(dates)  # An old page update cannot masquerade as new news.
    elif story.get("date_kind") == "updated":
        raise ValueError("Atom update time is not a confirmed publication date.")
    if not now - timedelta(hours=max_age_hours) <= published <= now:
        raise ValueError("Original publication is stale or future dated.")
    paragraphs = list(dict.fromkeys(parser.paragraphs))
    prices = price_evidence(paragraphs)
    if (PRICE_PATTERN.search(story["text"]) or AMOUNT_PATTERN.search(story["text"])) and not prices:
        raise ValueError("Price story lacks a sourced amount, currency and explicit market.")
    priced_quotes = {item["quote"] for item in prices}
    # Avoid relaying ambiguous price figures even in otherwise non-price news.
    paragraphs = [p for p in paragraphs if not AMOUNT_PATTERN.search(p) or p in priced_quotes]
    # Put price scope before a quote so captions/cards cannot present launch
    # pricing as a live retailer quote when later text is shortened.
    labeled_prices = []
    for price in prices:
        labeled_prices.append(
            f"Announced price — {price['market']}, {price['currency']}, {published:%Y-%m-%d} "
            f"(not a live retailer quote): {price['quote']}"
        )
    paragraphs = labeled_prices + [p for p in paragraphs if p not in priced_quotes]
    image_urls = collect_article_images(parser, final_url)
    source_theme = extract_source_theme(parser, final_url, story["allowed_host"])
    rumor_flag = is_rumor_story(story["text"], story.get("source", ""), paragraphs)
    return {
        "source_url": final_url, "published": published,
        "paragraphs": paragraphs[:12], "summary": "", "content_blocks": [],
        "image_urls": image_urls,
        "source_theme": source_theme,
        "is_rumor": rumor_flag,
        "price_evidence": prices,
        "verification": {
            "checked_at": datetime.now(timezone.utc).isoformat(), "article_url": final_url,
            "feed_timestamp": story["published"].isoformat(),
            "headline_matched": True, "sha256": hashlib.sha256(content).hexdigest(),
            "publication_date_basis": "article metadata" if dates else "publisher RSS pubDate",
            "date_precision": "day (UTC midnight used for sorting)" if any(
                re.fullmatch(r"\d{4}-\d{2}-\d{2}Z?", date) for date in parser.dates
            ) else "timestamp",
            "scope": "Publisher provenance and source wording; claims are not independently fact-checked.",
        },
    }
