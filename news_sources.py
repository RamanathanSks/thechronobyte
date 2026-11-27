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
}
REQUIRES_TECH_MATCH = frozenset({"Amazon", "Comcast", "IBM"})
NEWSROOM_PATHS = {
    "Figma": r"^/blog/[^/]+/?$",
    "Anthropic": r"^/news/[^/]+/?$",
    "Notion": r"^/blog/[^/]+/?$",
    "JPMorganChase": r"^/about/technology/blog/[^/]+/?$",
    "Comcast": r"^/(?:press/releases|stories|news-information/news-feed)/.+$",
}
MAX_NEWSROOM_ARTICLES = 6
# Observed official migration: DeepMind articles redirect to Google's own blog.
# This is an explicit publisher exception, not permission to follow arbitrary hosts.
PUBLISHER_HOSTS = {"deepmind.google": ("deepmind.google", "blog.google")}
VISIBLE_DATE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b"
)
PRICE_PATTERN = re.compile(r"\b(pric(?:e|es|ing)|msrp|costs?|discounts?|retail\s+offers?)\b", re.I)
RUMOR_PATTERN = re.compile(r"\b(rumou?rs?|unconfirmed|leaked?|speculation|reportedly)\b", re.I)
AMOUNT_PATTERN = re.compile(r"(?:US\$|AU\$|CA\$|USD|INR|EUR|GBP|AUD|CAD|JPY|Rs\.?|[₹$€£¥])\s*\d[\d,.]*", re.I)
ATOM = "{http://www.w3.org/2005/Atom}"
MAX_BYTES = 4_000_000
MAX_IMAGE_BYTES = 8_000_000
_NON_PHOTO_IMAGE = re.compile(
    r"(?:favicon|apple-touch-icon|/(?:icons?|avatars?|logos?|badges?|sprites?)/|"
    r"(?:^|[/_-])(?:logo|avatar|icon|badge|sprite|pixel|spacer|placeholder)[._-]|"
    r"/_next/image|\.(?:svg|ico|gif)(?:$|[?#]))",
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
    """Read page headings, publication metadata, paragraphs and media inside main/article."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings, self.paragraphs, self.dates, self.canonicals = [], [], [], []
        self.h1_headings = []
        self.meta_images, self.schema_images, self.article_images = [], [], []
        self.scope = self.skip = 0
        self.capture = None
        self.parts = []
        self.json_parts = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.json_parts = []
        if tag in {"nav", "footer", "aside", "script", "style", "form", "noscript"}:
            self.skip += 1
        if tag in {"article", "main"}:
            self.scope += 1
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name", "")).lower()
            value = attrs.get("content", "")
            if key in {"og:title", "twitter:title"}:
                self.headings.append(value)
            if key in {"article:published_time", "datepublished", "date", "pubdate"}:
                self.dates.append(value)
            if key in {"og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"} and value:
                self.meta_images.append((key, value.strip()))
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href", ""))
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
        elif len(text) >= 50 and not re.search(r"cookies|privacy policy|sign up|subscribe|all rights reserved", text, re.I):
            self.paragraphs.append(text)
        self.capture = None
        self.parts = []

    def handle_endtag(self, tag):
        if tag == "script" and self.json_parts is not None:
            try:
                self._schema(json.loads("".join(self.json_parts)))
            except (ValueError, TypeError, RecursionError):
                pass
            self.json_parts = None
        if tag in {"nav", "footer", "aside", "script", "style", "form", "noscript"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"article", "main"}:
            self.scope = max(0, self.scope - 1)
        if tag == self.capture:
            self._flush_capture()
        elif self.capture == "h1" and tag in {"header", "section", "article", "main", "div"}:
            self._flush_capture()

    def handle_data(self, data):
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
            elif isinstance(types, list) and "ImageObject" in types:
                self._add_schema_image(node)
            if "@graph" in node:
                self._schema(node["@graph"])


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
    return {
        "source_url": final_url, "published": published,
        "paragraphs": paragraphs[:12], "summary": "", "content_blocks": [],
        "image_urls": image_urls,
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
