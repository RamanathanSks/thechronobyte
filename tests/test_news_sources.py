"""Offline provenance, freshness, price-scope and broad-category regression tests."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests

import news_sources as news
import post_daily as bot


class SourceChecks(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network")))
        self.now = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
        self.story = {
            "source": "NVIDIA", "allowed_host": "blogs.nvidia.com",
            "text": "NVIDIA announces a new GPU",
            "source_url": "https://blogs.nvidia.com/blog/gpu/",
            "published": self.now - timedelta(hours=24), "summary": "Unverified RSS summary",
        }
        self.body = "The company says its new GPU will be available to developers later this month."

    def page(self, title=None, extra="", body=None):
        title = title or self.story["text"]
        return (f'<html><head><meta property="og:title" content="{title}">{extra}</head>'
                f'<body><nav><p>Navigation text should never become article context for a story.</p></nav>'
                f'<main><h1>{title}</h1><p>{body or self.body}</p></main></body></html>').encode()

    def verify(self, html=None, story=None, content_type="text/html"):
        with patch.object(news, "fetch_source", return_value=(html or self.page(), self.story["source_url"], content_type)):
            return news.verify_article(story or self.story, "test", self.now, 72)

    def test_verified_page_has_source_evidence_and_no_rss_fallback(self):
        result = self.verify()
        self.assertTrue(result["verification"]["headline_matched"])
        self.assertEqual(len(result["verification"]["sha256"]), 64)
        self.assertEqual(result["paragraphs"], [self.body])
        self.assertEqual(result["summary"], "")
        self.assertEqual(result["content_blocks"], [])

    def test_headline_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "headline"):
            self.verify(self.page(title="Unrelated home page without this news"))

    def test_non_html_and_empty_article_rejected(self):
        for body, mime in ((b"{}", "application/json"), (b"<html>Access denied</html>", "text/html")):
            with self.subTest(mime=mime), self.assertRaises(ValueError):
                self.verify(body, content_type=mime)

    def test_canonical_must_identify_same_article_on_same_host(self):
        for url in ("https://evil.example/story", "https://blogs.nvidia.com/another-story/"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "canonical"):
                self.verify(self.page(extra=f'<link rel="canonical" href="{url}">'))

    def test_old_or_future_article_metadata_overrides_recent_feed_date(self):
        for value in ("2025-11-14T10:00:00Z", "2026-11-16T10:00:00Z"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "stale or future"):
                self.verify(self.page(extra=f'<meta property="article:published_time" content="{value}">'))

    def test_atom_updated_timestamp_requires_original_publication_metadata(self):
        topic = {**self.story, "date_kind": "updated"}
        with self.assertRaisesRegex(ValueError, "publication date"):
            self.verify(story=topic)
        result = self.verify(self.page(extra='<script type="application/ld+json">'
                             '{"@type":"NewsArticle","datePublished":"2026-11-14T12:00:00Z"}'
                             '</script>'), topic)
        self.assertEqual(result["published"], self.story["published"])

    def test_price_story_requires_amount_currency_and_market(self):
        topic = {**self.story, "text": "NVIDIA announces GPU price changes"}
        with self.assertRaisesRegex(ValueError, "Price story"):
            self.verify(self.page(title=topic["text"], body="This GPU starts at $599 and is now available through authorized sellers."), topic)

    def test_price_context_is_labeled_and_original_quote_is_preserved(self):
        text = "The GPU launches in the United States at USD 599 and availability starts next month."
        topic = {**self.story, "text": "NVIDIA announces GPU prices"}
        result = self.verify(self.page(title=topic["text"], body=text), topic)
        price = result["price_evidence"][0]
        self.assertEqual((price["market"], price["currency"], price["amounts"]), ("United States", "USD", ["USD 599"]))
        self.assertEqual(price["quote"], text)
        self.assertIn("not a live retailer quote", result["paragraphs"][0])
        self.assertIn("2026-11-14", result["paragraphs"][0])

    def test_ram_price_in_india_keeps_inr(self):
        quotes = news.price_evidence(["This 32 GB DDR5 RAM kit is announced in India at INR 12,999 including tax."])
        self.assertEqual(quotes[0]["currency"], "INR")
        self.assertEqual(quotes[0]["amounts"], ["INR 12,999"])

    def test_ambiguous_multi_market_dollar_price_not_inferred(self):
        self.assertEqual(news.price_evidence(["Available in Canada and the United States for $599."]), [])
        self.assertEqual(news.price_evidence(["The RAM price is $99 for this configuration."]), [])

    def test_ambiguous_price_paragraph_removed_from_non_price_story(self):
        result = self.verify(self.page(body="The new model is available for $599 from select shops in participating markets."))
        self.assertEqual(result["paragraphs"], [])

    def test_atom_article_link_never_selects_enclosure(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>Apple launches a new iPhone</title><updated>2026-11-14T10:00:00Z</updated>
          <link rel="enclosure" href="https://www.apple.com/image.jpg" type="image/jpeg"/>
          <link href="https://www.apple.com/newsroom/iphone/"/>
          </entry></feed>'''
        item = news.feed_items(xml)[0]
        self.assertEqual(item.findtext("link"), "https://www.apple.com/newsroom/iphone/")
        self.assertEqual(item.get("date_kind"), "updated")
        self.assertEqual(news.parse_date(item.findtext("pubDate")).tzinfo, timezone.utc)

    def test_unrecognized_feed_and_naive_dates_rejected(self):
        with self.assertRaises(ValueError):
            news.feed_items(b"<html>not a feed</html>")
        with self.assertRaises(ValueError):
            news.parse_date("2026-11-14T12:00:00")

    def test_host_check_rejects_lookalikes_http_credentials_and_control_characters(self):
        for url in ("https://blogs.nvidia.com.evil.example/a", "http://blogs.nvidia.com/a",
                    "https://user:pass@blogs.nvidia.com/a", "https://blogs.nvidia.com:8080/a",
                    "https://blogs.nvidia.com/a\n", "https://blogs.nvidia.com\\evil.example"):
            with self.subTest(url=url):
                self.assertFalse(news.approved_url(url, "blogs.nvidia.com"))

    @staticmethod
    def response(status=200, body=b"test", **headers):
        response = requests.Response()
        response.status_code = status
        response.headers.update(headers)
        response._content = body
        response._content_consumed = True
        return response

    def test_off_domain_redirect_not_requested(self):
        response = self.response(302, Location="https://evil.example/story")
        with patch.object(news.requests, "get", return_value=response) as get:
            with self.assertRaisesRegex(ValueError, "approved HTTPS"):
                news.fetch_source(self.story["source_url"], self.story["allowed_host"], "test")
        get.assert_called_once()
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_same_domain_redirect_and_size_limit(self):
        responses = [self.response(301, Location="/new"), self.response(body=b"article")]
        with patch.object(news.requests, "get", side_effect=responses):
            body, url, _ = news.fetch_source(self.story["source_url"], self.story["allowed_host"], "test")
        self.assertEqual((body, url), (b"article", "https://blogs.nvidia.com/new"))
        with patch.object(news, "MAX_BYTES", 2), patch.object(news.requests, "get", return_value=self.response()):
            with self.assertRaisesRegex(ValueError, "download limit"):
                news.fetch_source(self.story["source_url"], self.story["allowed_host"], "test")

    def test_expanded_topics_and_hashtags_do_not_label_everything_ai(self):
        cases = (("Xbox", "New game launches", "Video Games"),
                 ("Apple", "iPhone launches globally", "Mobile Phones"),
                 ("Samsung", "DDR5 RAM price update", "Component Prices"),
                 ("Meta", "New social platform features", "Tech Industry"),
                 ("Microsoft", "Windows security improvements", "Tech Industry"),
                 ("NASA", "Artemis mission update", "Space Programs"))
        for source, title, expected in cases:
            with self.subTest(title=title):
                topic = {**self.story, "source": source, "text": title}
                self.assertEqual(bot._pick_topic_tag(topic), expected)
                self.assertNotIn("#ArtificialIntelligence", bot._pick_instagram_hashtags(topic))

    def test_strict_default_never_calls_groq_even_with_key(self):
        os.environ["GROQ_API_KEY"] = "fake-key"
        with patch.object(bot, "_call_groq", side_effect=AssertionError("Must not rewrite")):
            posts = bot.generate_thread(self.story)
            caption = bot.generate_instagram_caption(self.story)
        self.assertIn(self.story["text"], posts[0])
        self.assertIn(self.story["text"], caption)

    def test_candidate_that_fails_verification_is_skipped_for_next_story(self):
        xml = b'''<rss><channel>
          <item><title>New GPU story</title><link>https://blogs.nvidia.com/new/</link><pubDate>Sat, 14 Nov 2026 13:00:00 GMT</pubDate></item>
          <item><title>Older GPU story</title><link>https://blogs.nvidia.com/older/</link><pubDate>Sat, 14 Nov 2026 12:00:00 GMT</pubDate></item>
          </channel></rss>'''
        evidence = {"paragraphs": [], "verification": {"checked_at": self.now.isoformat(), "sha256": "fixture", "publication_date_basis": "RSS"}}
        with patch.object(bot, "NEWS_FEEDS", (news.NEWS_FEEDS[1],)), \
             patch.object(bot, "fetch_source", return_value=(xml, "", "")), \
             patch.object(bot, "verify_article", side_effect=[ValueError("Unconfirmed"), evidence]), \
             patch.object(bot, "_fetch_recent_thread_texts", return_value=[]):
            result = bot.get_topic_of_the_day(self.now)
        self.assertEqual(result["text"], "Older GPU story")

    def test_newest_confirmed_publication_wins_over_recent_feed_update(self):
        xml = b'''<rss><channel>
          <item><title>Updated GPU story</title><link>https://blogs.nvidia.com/updated/</link><pubDate>Sat, 14 Nov 2026 13:00:00 GMT</pubDate></item>
          <item><title>New GPU story</title><link>https://blogs.nvidia.com/new/</link><pubDate>Sat, 14 Nov 2026 12:00:00 GMT</pubDate></item>
          </channel></rss>'''
        def verified(story, *_):
            age = 48 if "updated/" in story["source_url"] else 24
            return {"published": self.now - timedelta(hours=age), "paragraphs": [],
                    "verification": {"checked_at": self.now.isoformat(), "sha256": "fixture", "publication_date_basis": "article"}}
        with patch.object(bot, "NEWS_FEEDS", (news.NEWS_FEEDS[1],)), \
             patch.object(bot, "fetch_source", return_value=(xml, "", "")), \
             patch.object(bot, "verify_article", side_effect=verified), \
             patch.object(bot, "_fetch_recent_thread_texts", return_value=[]):
            result = bot.get_topic_of_the_day(self.now)
        self.assertEqual(result["text"], "New GPU story")

    def test_requested_companies_and_additional_publishers_are_registered(self):
        sources = {source for source, _, _ in news.NEWS_FEEDS}
        required = {"Figma", "Anthropic", "JPMorganChase", "Notion", "Amazon", "Comcast",
                    "AWS", "Google DeepMind", "GitHub", "Cloudflare", "Cisco", "IBM", "Salesforce"}
        self.assertTrue(required <= sources)
        self.assertEqual(len(sources), len(news.NEWS_FEEDS))
        for _, url, host in news.NEWS_FEEDS:
            self.assertTrue(news.approved_url(url, host))

    def test_figma_discovery_skips_categories_and_orders_dated_articles(self):
        html = b'''<a href="/blog/design-systems/">Design systems</a>
        <a href="/blog/old-story/">Older article November 3, 2026</a>
        <a href="/blog/new-story/">New article November 14, 2026</a>
        <a href="https://evil.example/blog/fake/">Fake November 15, 2026</a>'''
        links = news.newsroom_links("Figma", html, "https://www.figma.com/blog/", "www.figma.com")
        self.assertEqual(links, ["https://www.figma.com/blog/new-story/", "https://www.figma.com/blog/old-story/"])

    def test_newsroom_links_are_deduplicated_and_bounded(self):
        html = ''.join(f'<a href="/news/item-{n}">News {n}</a>' * 2 for n in range(15)).encode()
        links = news.newsroom_links("Anthropic", html, "https://www.anthropic.com/news", "www.anthropic.com")
        self.assertEqual(len(links), news.MAX_NEWSROOM_ARTICLES)
        self.assertEqual(len(links), len(set(links)))

    def test_jpm_sitemap_only_discovers_technology_articles(self):
        xml = b'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://www.jpmorganchase.com/ir/earnings</loc><lastmod>2026-11-15</lastmod></url>
        <url><loc>https://www.jpmorganchase.com/about/technology/blog/ai</loc><lastmod>2026-11-14</lastmod></url>
        <url><loc>https://evil.example/about/technology/blog/fake</loc><lastmod>2026-11-15</lastmod></url>
        </urlset>'''
        self.assertEqual(news.newsroom_links("JPMorganChase", xml, "https://www.jpmorganchase.com/sitemap.xml", "www.jpmorganchase.com"),
                         ["https://www.jpmorganchase.com/about/technology/blog/ai"])

    def test_newsroom_metadata_comes_from_article_not_listing_text(self):
        listing = b'<a href="/blog/gpu/">Misleading title November 15, 2026</a>'
        article = self.page(extra='<meta property="article:published_time" content="2026-11-01T12:00:00Z">')
        url = "https://www.figma.com/blog/gpu/"
        with patch.object(news, "fetch_source", return_value=(article, url, "text/html")) as fetch:
            items, cache = news.load_newsroom("Figma", listing, "https://www.figma.com/blog/", "www.figma.com", "test")
        self.assertEqual(items[0].findtext("title"), self.story["text"])
        self.assertEqual(items[0].findtext("pubDate"), "2026-11-01T12:00:00+00:00")
        self.assertEqual(cache[url][0], article)
        fetch.assert_called_once()

    def test_newsroom_does_not_use_update_time_or_make_up_missing_dates(self):
        listing = b'<a href="/news/gpu">GPU news</a>'
        page = self.page(extra='<meta property="article:modified_time" content="2026-11-14T12:00:00Z">')
        with patch.object(news, "fetch_source", return_value=(page, "https://www.anthropic.com/news/gpu", "text/html")):
            with self.assertRaisesRegex(ValueError, "publication metadata"):
                news.load_newsroom("Anthropic", listing, "https://www.anthropic.com/news", "www.anthropic.com", "test")

    def test_cached_newsroom_article_is_verified_without_a_second_download(self):
        document = (self.page(), self.story["source_url"], "text/html")
        with patch.object(news, "fetch_source", side_effect=AssertionError("Duplicate download")):
            result = news.verify_article(self.story, "test", self.now, 72, document=document)
        self.assertTrue(result["verification"]["headline_matched"])
        with self.assertRaisesRegex(ValueError, "approved source"):
            news.verify_article(self.story, "test", self.now, 72, document=(self.page(), "https://evil.example", "text/html"))

    def test_publisher_calendar_dates_keep_day_precision(self):
        html = self.page(extra='<script type="application/ld+json">'
                         '{"@type":"NewsArticle","datePublished":"2026-11-14Z"}</script>')
        result = self.verify(html, {**self.story, "date_kind": "updated"})
        self.assertEqual(result["published"].hour, 0)
        self.assertIn("day", result["verification"]["date_precision"])

    def test_deepmind_has_only_the_explicit_google_publisher_alias(self):
        self.assertTrue(news.approved_url("https://blog.google/ai/story", "deepmind.google"))
        for host in ("evil.google", "blog.google.evil.example", "google.com", "googleusercontent.com"):
            self.assertFalse(news.approved_url("https://" + host + "/story", "deepmind.google"))
        self.assertFalse(news.approved_url("https://blog.google/story", "www.anthropic.com"))

    def test_source_load_failure_does_not_hide_other_sources(self):
        def fetch(url, *_):
            if "comcast" in url:
                raise requests.Timeout()
            return b"<rss><channel/></rss>", url, "application/rss+xml"
        with patch.object(bot, "fetch_source", side_effect=fetch):
            failed = bot._load_news_source(("Comcast", "https://corporate.comcast.com/press", "corporate.comcast.com"), "test")
            healthy = bot._load_news_source(("Amazon", "https://www.aboutamazon.com/rss/feed.rss", "www.aboutamazon.com"), "test")
        self.assertEqual(failed["error"], "Timeout")
        self.assertEqual(healthy["items"], [])

    def test_new_company_topic_tags(self):
        for source, title, expected in (
            ("Anthropic", "Claude introduces new tools", "Claude"),
            ("Figma", "Figma improves collaboration", "Design Tools"),
            ("Notion", "New workspace features", "Productivity"),
            ("JPMorganChase", "Digital payment infrastructure", "Financial Technology"),
            ("Comcast", "Faster broadband connections", "Connectivity"),
            ("AWS", "New cloud infrastructure", "Cloud Computing"),
        ):
            with self.subTest(source=source):
                self.assertEqual(bot._pick_topic_tag({"source": source, "text": title}), expected)


if __name__ == "__main__":
    unittest.main()
