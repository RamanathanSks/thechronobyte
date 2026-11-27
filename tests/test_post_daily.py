"""Offline behavior tests: all network access is mocked or blocked."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

import requests

import post_daily as bot


class DailyThreadsPostTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        # These tests focus on the existing publishing pipeline. New source
        # boundary/verification behavior is tested directly in test_news_sources.
        self.enterContext(patch.object(bot, "NEWS_FEEDS", bot.NEWS_FEEDS[:5]))
        self.enterContext(patch.object(bot, "SOURCE_FETCH_WORKERS", 1))
        self.enterContext(patch.object(bot, "fetch_source", side_effect=self.mock_feed_fetch))
        self.enterContext(patch.object(bot, "verify_article", side_effect=self.mock_verify_article))
        self.enterContext(
            patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network call"))
        )
        self.topic = {
            "source": "NVIDIA",
            "allowed_host": "blogs.nvidia.com",
            "text": "NVIDIA announces a new GPU for machine learning.",
            "summary": "The new architecture improves inference throughput and energy efficiency for data centers.",
            "paragraphs": [
                (
                    "Early benchmarks show up to 2.4x faster token generation across large multimodal "
                    "workloads while reducing rack power draw across hyperscale deployments and enterprise clusters."
                ),
                (
                    "Cloud providers and enterprise AI teams will begin deploying the new systems globally "
                    "early next quarter alongside updated CUDA libraries, compiler optimizations, and reference designs."
                ),
            ],
            "source_url": "https://blogs.nvidia.com/blog/new-gpu/",
            "published": datetime(2026, 11, 13, 12, tzinfo=timezone.utc),
            "topic_tag": "AI Hardware",
        }
        self.now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)

    def mock_feed_fetch(self, url, host, contact):
        response = bot.requests.get(url)
        response.raise_for_status()
        return response.content, url, "application/rss+xml"

    def mock_verify_article(self, topic, contact, now, hours):
        return {
            "paragraphs": bot._fetch_article_paragraphs(topic["source_url"], topic["allowed_host"], contact),
            "summary": "", "content_blocks": [],
            "verification": {"checked_at": now.isoformat(), "sha256": "fixture",
                             "publication_date_basis": "test fixture"},
        }

    @staticmethod
    def response(payload, status=200, url="", headers=None):
        response = requests.Response()
        response.status_code = status
        response.url = url
        if headers:
            response.headers.update(headers)
        response._content = (
            payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
        )
        return response

    def credentials(self):
        # Deliberately fake test values, never real credentials.
        os.environ.update({
            "THREADS_USER_ID": "1234567890",
            "THREADS_ACCESS_TOKEN": "test-threads-token",
        })

    def feed(self, entries):
        items = []
        for entry in entries:
            title = escape(entry.get("title", self.topic["text"]))
            link = escape(entry.get("link", self.topic["source_url"]))
            published = escape(entry.get("date", format_datetime(self.topic["published"])))
            desc_xml = f"<description>{escape(entry['description'])}</description>" if "description" in entry else ""
            content_xml = (
                f"<content:encoded>{escape(entry['content'])}</content:encoded>" if "content" in entry else ""
            )
            items.append(
                f"<item><title>{title}</title><link>{link}</link><pubDate>{published}</pubDate>"
                f"{desc_xml}{content_xml}</item>"
            )
        response = self.response({})
        response._content = (
            '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
            + "".join(items)
            + "</channel></rss>"
        ).encode()
        return response

    def test_newest_relevant_story_wins_and_fetches_article_paragraphs(self):
        article_html = (
            "<nav><p>Navigation links that should be skipped even when long enough.</p></nav>"
            "<article>"
            "<p>We use cookies — Accept cookies to continue reading this site.</p>"
            "<p>Google is rolling out faster reasoning and deeper multimodal search across 120 countries starting today.</p>"
            "<p>Developers can also test the new capabilities directly in Search Labs and the Gemini API.</p>"
            "</article>"
        )
        feeds = [
            self.feed([]),
            self.feed([{}]),
            self.feed([{
                "title": "Google announces a new Gemini model",
                "link": "https://blog.google/new-gemini/",
                "date": format_datetime(self.now - timedelta(hours=1)),
                "description": '<img src="https://blog.google/hero.webp"><p>Faster reasoning &amp; multimodal context.</p>',
            }]),
            self.feed([]),
            self.feed([]),
            self.response(article_html, url="https://blog.google/new-gemini/", headers={"Content-Type": "text/html"}),
            self.response("<p>The older NVIDIA article has additional information about its new GPU.</p>",
                          url=self.topic["source_url"], headers={"Content-Type": "text/html"}),
        ]
        with patch.object(bot.requests, "get", side_effect=feeds):
            topic = bot.get_topic_of_the_day(self.now)
        self.assertEqual(topic["source"], "Google AI")
        self.assertEqual(topic["topic_tag"], "Google Gemini")
        self.assertEqual(len(topic["paragraphs"]), 2)
        self.assertIn("120 countries", topic["paragraphs"][0])

    def test_article_fetch_ignores_off_host_redirects_and_failures(self):
        redirected = self.response(
            "<p>Off-domain paragraph that must not be read from external host.</p>",
            url="https://evil.example/phish",
            headers={"Content-Type": "text/html"},
        )
        with patch.object(bot.requests, "get", return_value=redirected):
            self.assertEqual(bot._fetch_article_paragraphs("https://blog.google/x", "blog.google", "test"), [])
        with patch.object(bot.requests, "get", side_effect=requests.Timeout):
            self.assertEqual(bot._fetch_article_paragraphs("https://blog.google/x", "blog.google", "test"), [])

    def test_deduplication_skips_already_posted_story_for_fresh_story(self):
        self.credentials()
        recent_threads = self.response({
            "data": [{"id": "1", "text": "⚡ OpenAI just shared: Old posted AI story"}]
        })
        feed_with_two = self.feed([
            {
                "title": "Old posted AI story",
                "link": "https://openai.com/news/old-story",
                "date": format_datetime(self.now - timedelta(hours=1)),
            },
            {
                "title": "Fresh unposted AI story",
                "link": "https://openai.com/news/fresh-story",
                "date": format_datetime(self.now - timedelta(hours=3)),
            },
        ])
        article_resp = self.response("<p>Fresh article paragraph with concrete technical details for readers.</p>")
        side_effects = [
            feed_with_two,
            self.feed([]),
            self.feed([]),
            self.feed([]),
            self.feed([]),
            recent_threads,
            article_resp,
        ]
        with patch.object(bot.requests, "get", side_effect=side_effects):
            topic = bot.get_topic_of_the_day(self.now)
        self.assertEqual(topic["text"], "Fresh unposted AI story")

    def test_content_encoded_fallback_and_script_stripping(self):
        html_content = "<script>alert(1)</script><p>First paragraph.</p><p>Second paragraph.</p>"
        side_effects = [
            self.feed([]),
            self.feed([{"content": html_content}]),
            self.feed([]),
            self.feed([]),
            self.feed([]),
            self.response(""),
        ]
        with patch.object(bot.requests, "get", side_effect=side_effects):
            topic = bot.get_topic_of_the_day(self.now)
        self.assertEqual(topic["summary"], "")  # No RSS-only fallback after verification.

    def test_default_date_is_utc(self):
        with patch.object(bot, "datetime") as clock:
            clock.now.return_value = self.now
            with patch.object(bot.requests, "get", return_value=self.feed([])):
                self.assertIsNone(bot.get_topic_of_the_day())
            clock.now.assert_called_once_with(timezone.utc)

    def test_empty_feeds_skip(self):
        with patch.object(bot.requests, "get", return_value=self.feed([])):
            self.assertIsNone(bot.get_topic_of_the_day(self.now))

    def test_stale_future_undated_irrelevant_and_off_domain_stories_are_excluded(self):
        bad_entries = [
            {"date": format_datetime(self.now - timedelta(hours=73))},
            {"date": format_datetime(self.now + timedelta(minutes=1))},
            {"date": ""},
            {"date": "invalid"},
            {"date": "Fri, 13 Nov 2026 12:00:00"},
            {"title": "Company celebrates its anniversary"},
            {"title": "GPU company announces financial results"},
            {"link": "https://example.com/ai-story"},
            {"link": "https://blogs.nvidia.com.evil.example/ai"},
            {"link": "https://evil.example@blogs.nvidia.com/ai"},
            {"link": "http://blogs.nvidia.com/ai"},
            {"link": "https://blogs.nvidia.com:8443/ai"},
        ]
        for entry in bad_entries:
            with self.subTest(entry=entry):
                with patch.object(bot.requests, "get", return_value=self.feed([entry])):
                    self.assertIsNone(bot.get_topic_of_the_day(self.now))

    def test_freshness_window_is_configurable_and_validated(self):
        os.environ["MAX_NEWS_AGE_HOURS"] = "12"
        with patch.object(bot.requests, "get", return_value=self.feed([{}])):
            self.assertIsNone(bot.get_topic_of_the_day(self.now))
        for value in ("bad", "0", "169"):
            os.environ["MAX_NEWS_AGE_HOURS"] = value
            with self.assertRaises(ValueError):
                bot.get_topic_of_the_day(self.now)

    def test_one_failed_feed_does_not_block_other_sources(self):
        feeds = [
            requests.Timeout(),
            self.feed([{}]),
            self.feed([]),
            self.feed([]),
            self.feed([]),
            self.response(""),
        ]
        with patch.object(bot.requests, "get", side_effect=feeds):
            self.assertEqual(bot.get_topic_of_the_day(self.now)["source"], "NVIDIA")

    def test_all_failed_or_malformed_feeds_raise(self):
        for response in (self.response({}, 503), self.response({}), self.response("not XML")):
            with self.subTest(status=response.status_code):
                with patch.object(bot.requests, "get", return_value=response):
                    with self.assertRaisesRegex(ValueError, "All news feeds failed"):
                        bot.get_topic_of_the_day(self.now)

    def test_rss_title_preserves_source_wording_and_unescapes_entities(self):
        title = "AI &amp; GPUs: A new model"
        side_effects = [
            self.feed([]),
            self.feed([{"title": title}]),
            self.feed([]),
            self.feed([]),
            self.feed([]),
            self.response(""),
        ]
        with patch.object(bot.requests, "get", side_effect=side_effects):
            topic = bot.get_topic_of_the_day(self.now)
        self.assertEqual(topic["text"], "AI & GPUs: A new model")

    def test_generate_thread_creates_rich_two_part_thread_without_raw_urls(self):
        posts = bot.generate_thread(self.topic)
        self.assertEqual(len(posts), 2)
        for post in posts:
            self.assertLessEqual(len(post), 500)
            self.assertLessEqual(bot._post_weight(post), 500)
            self.assertNotIn("https://", post)
        self.assertIn("NVIDIA", posts[0])
        self.assertIn("2.4x faster token generation", posts[0])
        self.assertIn("early next quarter", posts[0])
        self.assertIn("data centers", posts[1])
        self.assertIn("?", posts[1])

    def test_generate_thread_single_post_includes_question_when_short(self):
        short_topic = {**self.topic, "paragraphs": []}
        posts = bot.generate_thread(short_topic)
        self.assertEqual(len(posts), 1)
        self.assertIn("?", posts[0])
        self.assertLessEqual(bot._post_weight(posts[0]), 500)

    def test_long_summaries_and_unicode_fit_within_500_limit(self):
        for summary in ("New machine learning research. " * 100, "界😀" * 300, "x" * 700):
            with self.subTest(summary=summary[:25]):
                for post in bot.generate_thread({**self.topic, "summary": summary, "paragraphs": []}):
                    self.assertLessEqual(len(post), 500)
                    self.assertLessEqual(bot._post_weight(post), 500)

    def test_topic_tag_selection_respects_threads_rules(self):
        cases = (
            ({"source": "OpenAI", "text": "ChatGPT update"}, "OpenAI"),
            ({"source": "Google AI", "text": "Gemini 4 release"}, "Google Gemini"),
            ({"source": "AMD", "text": "New EPYC processor"}, "Computer Hardware"),
            ({"source": "Microsoft Research", "text": "New neural architecture"}, "Machine Learning"),
            ({"source": "Microsoft Research", "text": "AI policy update"}, "Artificial Intelligence"),
        )
        for sample, expected in cases:
            tag = bot._pick_topic_tag(sample)
            self.assertEqual(tag, expected)
            self.assertNotIn(".", tag)
            self.assertNotIn("&", tag)
            self.assertLessEqual(len(tag), 50)

    def test_valid_groq_two_part_thread_uses_requested_model(self):
        os.environ["STRICT_SOURCE_MODE"] = "false"  # Legacy experimental rewriting.
        os.environ["GROQ_API_KEY"] = "test-groq-key"
        payload = {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": (
                        "NVIDIA just raised the bar for data-center inference.\n\n"
                        "---THREAD_BREAK---\n\n"
                        "Systems roll out next quarter with 2.4x speedups. Ready to upgrade?"
                    )
                },
            }]
        }
        with patch.object(bot.requests, "post", return_value=self.response(payload)) as post:
            posts = bot.generate_thread(self.topic)
        self.assertEqual(len(posts), 2)
        self.assertIn("raised the bar", posts[0])
        self.assertIn("Ready to upgrade?", posts[1])
        self.assertEqual(post.call_args.kwargs["json"]["model"], "llama-3.1-8b-instant")
        post.assert_called_once()

    def test_bad_groq_responses_fall_back(self):
        os.environ["STRICT_SOURCE_MODE"] = "false"
        fallback = bot.generate_thread(self.topic)
        os.environ["GROQ_API_KEY"] = "test-groq-key"
        payloads = [None, {}, {"choices": []}]
        for content, reason in (
            (None, "stop"),
            ("", "stop"),
            ("Too long " * 150, "stop"),
            ("Truncated sentence", "length"),
            ("See https://example.com", "stop"),
            ("Hi @someone", "stop"),
            ("Great #AINews", "stop"),
            ("See a.co", "stop"),
        ):
            payloads.append({"choices": [{"finish_reason": reason, "message": {"content": content}}]})
        for payload in payloads:
            with self.subTest(payload=payload):
                with patch.object(bot.requests, "post", return_value=self.response(payload)):
                    self.assertEqual(bot.generate_thread(self.topic), fallback)

    def test_groq_errors_fall_back_without_leaking_key(self):
        os.environ["STRICT_SOURCE_MODE"] = "false"
        fallback = bot.generate_thread(self.topic)
        os.environ["GROQ_API_KEY"] = "test-groq-key"
        errors = (
            requests.Timeout("test-groq-key"),
            requests.HTTPError("test-groq-key"),
            requests.exceptions.JSONDecodeError("test-groq-key", "invalid", 0),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with patch.object(bot.requests, "post", side_effect=error):
                    with self.assertLogs(bot.LOGGER, level="WARNING") as logs:
                        self.assertEqual(bot.generate_thread(self.topic), fallback)
                self.assertNotIn("test-groq-key", " ".join(logs.output))

    def test_post_requires_credentials_and_valid_user_id_and_reply_control(self):
        with self.assertRaisesRegex(ValueError, "THREADS_USER_ID, THREADS_ACCESS_TOKEN"):
            bot.post_to_threads("A technology headline.", self.topic["source_url"])
        os.environ.update({"THREADS_USER_ID": "../bad", "THREADS_ACCESS_TOKEN": "tok"})
        with self.assertRaisesRegex(ValueError, "THREADS_USER_ID"):
            bot.post_to_threads("A technology headline.", self.topic["source_url"])
        self.credentials()
        os.environ["THREADS_REPLY_CONTROL"] = "invalid_mode"
        with self.assertRaisesRegex(ValueError, "THREADS_REPLY_CONTROL"):
            bot.post_to_threads("A technology headline.", self.topic["source_url"])

    def test_post_rejects_empty_and_oversized_posts(self):
        self.credentials()
        for post_text in (" ", "a" * 501, "界" * 170):
            with self.subTest(post_text=post_text[:10]):
                with self.assertRaises(ValueError):
                    bot.post_to_threads(post_text, self.topic["source_url"])

    def test_publish_thread_creates_two_part_chain_with_reply_to_id(self):
        self.credentials()
        post_responses = [
            self.response({"id": "container-1"}),
            self.response({"id": "post-1"}),
            self.response({"id": "container-2"}),
            self.response({"id": "post-2"}),
        ]
        status_responses = [
            self.response({"id": "container-1", "status": "IN_PROGRESS"}),
            self.response({"id": "container-1", "status": "FINISHED"}),
            self.response({"id": "container-2", "status": "FINISHED"}),
        ]
        with (
            patch.object(bot.requests, "post", side_effect=post_responses) as post,
            patch.object(bot.requests, "get", side_effect=status_responses),
            patch.object(bot.time, "sleep") as sleep,
        ):
            ids = bot.publish_thread(["Part 1", "Part 2"], self.topic["source_url"], topic_tag="AI. & Hardware")
        self.assertEqual(ids, ["post-1", "post-2"])
        sleep.assert_called_once_with(2.0)

        root_create = post.call_args_list[0].kwargs["data"]
        self.assertEqual(root_create["topic_tag"], "AI  Hardware")
        self.assertEqual(root_create["link_attachment"], self.topic["source_url"])
        self.assertNotIn("reply_to_id", root_create)

        reply_create = post.call_args_list[2].kwargs["data"]
        self.assertEqual(reply_create["reply_to_id"], "post-1")
        self.assertNotIn("topic_tag", reply_create)
        self.assertNotIn("link_attachment", reply_create)

    def test_publish_thread_warns_if_followup_reply_fails_after_root(self):
        self.credentials()
        post_responses = [
            self.response({"id": "container-1"}),
            self.response({"id": "post-1"}),
            requests.Timeout("reply failed"),
        ]
        with (
            patch.object(bot.requests, "post", side_effect=post_responses),
            patch.object(bot.requests, "get", return_value=self.response({"status": "FINISHED"})),
            self.assertLogs(bot.LOGGER, level="WARNING") as logs,
        ):
            ids = bot.publish_thread(["Part 1", "Part 2"], self.topic["source_url"], topic_tag="OpenAI")
        self.assertEqual(ids, ["post-1"])
        self.assertIn("already published", " ".join(logs.output))

    def test_container_error_prevents_publish(self):
        self.credentials()
        with (
            patch.object(bot.requests, "post", return_value=self.response({"id": "container-111"})) as post,
            patch.object(
                bot.requests,
                "get",
                return_value=self.response({"id": "container-111", "status": "ERROR", "error_message": "Bad link"}),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Bad link"):
                bot.post_to_threads("A fact.", self.topic["source_url"])
        post.assert_called_once()

    def test_publish_timeout_is_not_retried(self):
        self.credentials()
        with (
            patch.object(bot.requests, "post", side_effect=[self.response({"id": "container-111"}), requests.Timeout]) as post,
            patch.object(bot.requests, "get", return_value=self.response({"status": "FINISHED"})),
        ):
            with self.assertRaises(requests.Timeout):
                bot.post_to_threads("A fact.", self.topic["source_url"])
        self.assertEqual(post.call_count, 2)

    def test_missing_container_or_post_id_fails(self):
        self.credentials()
        with patch.object(bot.requests, "post", return_value=self.response({})):
            with self.assertRaisesRegex(ValueError, "container ID"):
                bot.post_to_threads("A fact.", self.topic["source_url"])
        with (
            patch.object(bot.requests, "post", side_effect=[self.response({"id": "container-111"}), self.response({})]),
            patch.object(bot.requests, "get", return_value=self.response({"status": "FINISHED"})),
        ):
            with self.assertRaisesRegex(ValueError, "post ID"):
                bot.post_to_threads("A fact.", self.topic["source_url"])

    def test_refresh_token_and_github_actions_guard(self):
        with patch.object(
            bot.requests, "get", return_value=self.response({"access_token": "new-tok", "expires_in": 5183944})
        ) as get:
            payload = bot.refresh_threads_token("old-tok")
        self.assertEqual(payload["access_token"], "new-tok")
        self.assertEqual(get.call_args.kwargs["params"], {
            "grant_type": "th_refresh_token",
            "access_token": "old-tok",
        })

        os.environ["GITHUB_ACTIONS"] = "true"
        os.environ["THREADS_ACCESS_TOKEN"] = "old-tok"
        self.assertEqual(bot.main(["--refresh-token"]), 1)

    def test_main_previews_by_default_without_credentials(self):
        with patch.object(bot, "get_topic_of_the_day", return_value=self.topic):
            with patch.object(bot, "publish_thread") as post:
                with self.assertLogs(bot.LOGGER, level="INFO") as logs:
                    self.assertEqual(bot.main([]), 0)
        post.assert_not_called()
        combined_logs = " ".join(logs.output)
        self.assertIn("DRY RUN", combined_logs)
        self.assertIn("Topic: AI Hardware", combined_logs)

    def test_main_only_posts_with_explicit_false_and_passes_topic_tag(self):
        os.environ["DRY_RUN"] = "false"
        with patch.object(bot, "get_topic_of_the_day", return_value=self.topic):
            with patch.object(bot, "publish_thread", return_value=["999"]) as post:
                self.assertEqual(bot.main([]), 0)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["topic_tag"], "AI Hardware")

    def test_main_invalid_mode_fails_before_fetching(self):
        os.environ["DRY_RUN"] = "typo"
        with patch.object(bot, "get_topic_of_the_day") as get:
            self.assertEqual(bot.main([]), 1)
        get.assert_not_called()

    def test_main_skips_empty_feed_without_generation_or_post(self):
        with patch.object(bot, "get_topic_of_the_day", return_value=None):
            with patch.object(bot, "generate_thread") as generate, patch.object(bot, "publish_thread") as post:
                self.assertEqual(bot.main([]), 0)
        generate.assert_not_called()
        post.assert_not_called()

    def test_main_http_error_returns_nonzero_without_leaking_token(self):
        self.credentials()
        os.environ["DRY_RUN"] = "false"
        response = self.response({"error": {"code": 190, "message": "bad token test-threads-token"}}, 401)
        response.url = "https://graph.threads.net/v1.0/1234567890/threads"
        with patch.object(bot, "get_topic_of_the_day", return_value=self.topic):
            with patch.object(bot.requests, "post", return_value=response):
                with self.assertLogs(bot.LOGGER, level="ERROR") as logs:
                    self.assertEqual(bot.main([]), 1)
        combined = " ".join(logs.output)
        self.assertNotIn("test-threads-token", combined)
        self.assertIn("401", combined)
        self.assertIn("code=190", combined)

    def test_instagram_caption_template_has_hook_cta_hashtags_and_no_raw_urls(self):
        caption = bot.generate_instagram_caption(self.topic)
        first_line = caption.splitlines()[0]
        self.assertLessEqual(len(first_line), 125)
        self.assertIn("@thechronobyte", caption)
        self.assertIn("link in bio", caption.lower())
        self.assertIn("#NVIDIA", caption)
        self.assertIn("#TheChronoByte", caption)
        self.assertNotIn("https://", caption)
        self.assertLessEqual(len(caption), bot.MAX_IG_CAPTION_LENGTH)

    def test_instagram_caption_groq_validation_and_fallback(self):
        os.environ["STRICT_SOURCE_MODE"] = "false"
        os.environ["GROQ_API_KEY"] = "test-groq-key"
        valid_groq = self.response({
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": (
                        "⚡ NVIDIA just changed the math for local AI workloads.\n\n"
                        "**Throughput doubled** while cutting rack power across training clusters.\n\n"
                        "Would you run this on-prem or in the cloud?"
                    ),
                },
            }]
        })
        with patch.object(bot.requests, "post", return_value=valid_groq):
            caption = bot.generate_instagram_caption(self.topic)
        self.assertIn("Throughput doubled while cutting rack power", caption)
        self.assertNotIn("**", caption)
        self.assertIn("@thechronobyte", caption)
        self.assertIn("#NVIDIA", caption)

        bad_groq = self.response({
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": "Check https://blogs.nvidia.com/bad-link for more #spam"},
            }]
        })
        with (
            patch.object(bot.requests, "post", return_value=bad_groq),
            self.assertLogs(bot.LOGGER, level="WARNING") as logs,
        ):
            fallback = bot.generate_instagram_caption(self.topic)
        self.assertNotIn("https://", fallback)
        self.assertIn("@thechronobyte", fallback)
        self.assertIn("using the template", " ".join(logs.output))

    def test_main_save_card_writes_image_and_caption_without_posting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            card_path = Path(tmpdir) / "card.jpg"
            with (
                patch.object(bot, "get_topic_of_the_day", return_value=self.topic),
                patch.object(bot, "publish_thread") as post,
                self.assertLogs(bot.LOGGER, level="INFO") as logs,
            ):
                rc = bot.main(["--save-card", str(card_path)])
            self.assertEqual(rc, 0)
            post.assert_not_called()
            self.assertTrue(card_path.is_file())
            caption_path = card_path.with_suffix(".caption.txt")
            self.assertTrue(caption_path.is_file())
            caption_text = caption_path.read_text(encoding="utf-8")
            self.assertIn("@thechronobyte", caption_text)
            self.assertIn("#NVIDIA", caption_text)
            self.assertIn("Instagram Caption Preview", " ".join(logs.output))

    def test_post_to_instagram_creates_polls_and_publishes_photo(self):
        os.environ["IG_USER_ID"] = "17841400001234"
        os.environ["IG_ACCESS_TOKEN"] = "test-ig-token"
        post_resps = [
            self.response({"id": "ig-container-1"}),
            self.response({"id": "ig-media-999"}),
        ]
        get_resps = [
            self.response({"id": "ig-container-1", "status_code": "IN_PROGRESS"}),
            self.response({"id": "ig-container-1", "status_code": "FINISHED"}),
        ]
        with (
            patch.object(bot.requests, "post", side_effect=post_resps) as post,
            patch.object(bot.requests, "get", side_effect=get_resps) as get,
            patch.object(bot.time, "sleep") as sleep,
        ):
            media_id = bot.post_to_instagram("https://example.com/card.jpg", "Test caption")
        self.assertEqual(media_id, "ig-media-999")
        sleep.assert_called_once_with(3.0)
        self.assertEqual(post.call_args_list[0].args[0], f"{bot.INSTAGRAM_API_BASE}/17841400001234/media")
        self.assertEqual(post.call_args_list[0].kwargs["data"]["image_url"], "https://example.com/card.jpg")
        self.assertEqual(get.call_args_list[0].kwargs["params"], {"fields": "status_code,status"})
        self.assertEqual(post.call_args_list[1].args[0], f"{bot.INSTAGRAM_API_BASE}/17841400001234/media_publish")

    def test_instagram_container_error_raises_without_publish(self):
        os.environ["IG_USER_ID"] = "17841400001234"
        os.environ["IG_ACCESS_TOKEN"] = "test-ig-token"
        with (
            patch.object(bot.requests, "post", return_value=self.response({"id": "ig-c1"})) as post,
            patch.object(bot.requests, "get", return_value=self.response({"status_code": "ERROR", "status": "Invalid aspect"})),
        ):
            with self.assertRaisesRegex(ValueError, "Invalid aspect"):
                bot.post_to_instagram("https://example.com/card.jpg", "Caption")
        post.assert_called_once()

    def test_refresh_instagram_token_and_github_guard(self):
        with patch.object(
            bot.requests, "get", return_value=self.response({"access_token": "new-ig-tok", "expires_in": 5183944})
        ) as get:
            payload = bot.refresh_instagram_token("old-ig-tok")
        self.assertEqual(payload["access_token"], "new-ig-tok")
        self.assertEqual(get.call_args.kwargs["params"], {
            "grant_type": "ig_refresh_token",
            "access_token": "old-ig-tok",
        })
        os.environ["GITHUB_ACTIONS"] = "true"
        os.environ["IG_ACCESS_TOKEN"] = "old-ig-tok"
        self.assertEqual(bot.main(["--refresh-ig-token"]), 1)

    def test_resolve_card_image_url_supports_imgbb_github_and_explicit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            card = Path(tmpdir) / "20261113-abcd1234.jpg"
            card.write_bytes(b"fakejpegbytes")

            with self.assertRaisesRegex(ValueError, "public HTTPS image host"):
                bot._resolve_card_image_url(card)

            os.environ["IMGBB_API_KEY"] = "imgbb-secret"
            with patch.object(
                bot.requests, "post", return_value=self.response({"data": {"url": "https://i.ibb.co/x/card.jpg"}})
            ):
                self.assertEqual(bot._resolve_card_image_url(card), "https://i.ibb.co/x/card.jpg")
            del os.environ["IMGBB_API_KEY"]

            os.environ["GITHUB_TOKEN"] = "gh-secret"
            os.environ["GITHUB_REPOSITORY"] = "RamanathanSks/thechronobyte"
            get_resps = [self.response({}, 404), self.response({}, 404)]
            post_resps = [
                self.response({"sha": "b1"}, 201),
                self.response({"sha": "t1"}, 201),
                self.response({"sha": "c1"}, 201),
                self.response({"ref": "refs/heads/ig-media"}, 201),
            ]
            with (
                patch.object(bot.requests, "get", side_effect=get_resps),
                patch.object(bot.requests, "post", side_effect=post_resps),
                patch.object(bot.requests, "put", return_value=self.response({"content": {"sha": "f1"}}, 201)),
                patch.object(bot.time, "sleep"),
            ):
                raw_url = bot._resolve_card_image_url(card)
            self.assertEqual(
                raw_url,
                "https://raw.githubusercontent.com/RamanathanSks/thechronobyte/ig-media/cards/20261113-abcd1234.jpg",
            )

            os.environ["IG_IMAGE_URL"] = "https://cdn.example.com/override.jpg"
            self.assertEqual(bot._resolve_card_image_url(card), "https://cdn.example.com/override.jpg")

    def test_main_dry_run_previews_both_and_live_isolates_failures_without_leaks(self):
        os.environ["DRY_RUN"] = "true"
        os.environ["ENABLE_INSTAGRAM"] = "true"
        with (
            patch.object(bot, "get_topic_of_the_day", return_value=self.topic),
            patch.object(bot, "publish_thread") as pub_t,
            patch.object(bot, "publish_instagram_card") as pub_ig,
            self.assertLogs(bot.LOGGER, level="INFO") as logs,
        ):
            self.assertEqual(bot.main([]), 0)
        pub_t.assert_not_called()
        pub_ig.assert_not_called()
        self.assertIn("no Instagram request made", " ".join(logs.output))

        os.environ["DRY_RUN"] = "false"
        os.environ["IG_ACCESS_TOKEN"] = "secret-ig-token"
        err_resp = self.response({"error": {"code": 10, "message": "failed for secret-ig-token"}}, 403)
        http_err = requests.HTTPError(response=err_resp)
        with (
            patch.object(bot, "get_topic_of_the_day", return_value=self.topic),
            patch.object(bot, "publish_thread", return_value=["t-1"]),
            patch.object(bot, "publish_instagram_card", side_effect=http_err),
            self.assertLogs(bot.LOGGER, level="INFO") as logs,
        ):
            rc = bot.main([])
        self.assertEqual(rc, 1)
        combined = " ".join(logs.output)
        self.assertIn("Posted successfully to Threads", combined)
        self.assertIn("Instagram publish failed", combined)
        self.assertNotIn("secret-ig-token", combined)

    def test_step_summary_and_publish_instagram_card_logs_without_secret_leaks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "summary.md"
            os.environ.update({
                "DRY_RUN": "true",
                "ENABLE_THREADS": "true",
                "ENABLE_INSTAGRAM": "true",
                "THREADS_USER_ID": "12345",
                "THREADS_ACCESS_TOKEN": "top-secret-threads",
                "IG_USER_ID": "67890",
                "IG_ACCESS_TOKEN": "top-secret-ig",
                "GITHUB_TOKEN": "top-secret-gh",
                "GITHUB_REPOSITORY": "RamanathanSks/thechronobyte",
                "GROQ_API_KEY": "top-secret-groq",
                "GITHUB_STEP_SUMMARY": str(summary_file),
            })
            with (
                patch.object(bot, "get_topic_of_the_day", return_value=self.topic),
                patch.object(bot, "generate_thread", return_value=["Part 1 hook?"]),
                patch.object(bot, "generate_instagram_caption", return_value="Hook line\n\n#AI #TheChronoByte"),
                self.assertLogs(level="INFO") as logs,
            ):
                rc = bot.main([])
            self.assertEqual(rc, 0)
            log_text = " ".join(logs.output)
            self.assertIn("[0/6 Config]", log_text)
            self.assertIn("[4/6 Card]", log_text)
            self.assertIn("DRY RUN pipeline completed", log_text)
            summary_text = summary_file.read_text(encoding="utf-8")
            self.assertIn("Chrono Byte Daily Run (DRY RUN)", summary_text)
            self.assertIn(self.topic["source_url"], summary_text)
            for secret in ("top-secret-threads", "top-secret-ig", "top-secret-gh", "top-secret-groq"):
                self.assertNotIn(secret, log_text)
                self.assertNotIn(secret, summary_text)

    def test_publish_instagram_card_logs_permalink_end_to_end(self):
        os.environ.update({
            "IG_USER_ID": "17841400001234",
            "IG_ACCESS_TOKEN": "secret-ig-tok",
            "IG_IMAGE_URL": "https://cdn.example.com/card.jpg",
        })
        post_resps = [
            self.response({"id": "ig-c-1"}),
            self.response({"id": "ig-m-42"}),
        ]
        get_resps = [
            self.response({"status_code": "FINISHED"}),
            self.response({"id": "ig-m-42", "permalink": "https://www.instagram.com/p/TEST123/"}),
        ]
        with (
            patch.object(bot.requests, "post", side_effect=post_resps),
            patch.object(bot.requests, "get", side_effect=get_resps),
            self.assertLogs(level="INFO") as logs,
        ):
            media_id = bot.publish_instagram_card(self.topic, "Caption body #TheChronoByte")
        self.assertEqual(media_id, "ig-m-42")
        combined = " ".join(logs.output)
        self.assertIn("https://www.instagram.com/p/TEST123/", combined)
        self.assertNotIn("secret-ig-tok", combined)

    def test_post_instagram_carousel_publishes_children_and_parent(self):
        os.environ["IG_USER_ID"] = "17841400001234"
        os.environ["IG_ACCESS_TOKEN"] = "secret-ig-tok"
        urls = [
            "https://cdn.example.com/s1.jpg",
            "https://cdn.example.com/s2.jpg",
            "https://cdn.example.com/s3.jpg",
        ]
        post_resps = [
            self.response({"id": "child-1"}),
            self.response({"id": "child-2"}),
            self.response({"id": "child-3"}),
            self.response({"id": "parent-c"}),
            self.response({"id": "carousel-m-1"}),
        ]
        with (
            patch.object(bot.requests, "post", side_effect=post_resps) as post,
            patch.object(bot.requests, "get", return_value=self.response({"status_code": "FINISHED"})),
        ):
            media_id = bot.post_instagram_carousel(urls, "Multi-card breakdown #TheChronoByte")
        self.assertEqual(media_id, "carousel-m-1")
        self.assertEqual(post.call_count, 5)
        self.assertEqual(post.call_args_list[0].kwargs["data"]["is_carousel_item"], "true")
        self.assertEqual(post.call_args_list[3].kwargs["data"]["media_type"], "CAROUSEL")
        self.assertEqual(post.call_args_list[3].kwargs["data"]["children"], "child-1,child-2,child-3")
        self.assertEqual(post.call_args_list[4].kwargs["data"]["creation_id"], "parent-c")

    def test_publish_instagram_card_uploads_and_publishes_multi_slide_carousel(self):
        os.environ.update({
            "IG_USER_ID": "17841400001234",
            "IG_ACCESS_TOKEN": "secret-ig-tok",
            "IMGBB_API_KEY": "secret-imgbb-key",
        })
        rich_topic = {
            **self.topic,
            "paragraphs": [
                f"Paragraph {i}: Detailed AI hardware architecture benchmarks, memory bandwidth scaling, and power efficiency metrics across data center clusters."
                for i in range(1, 8)
            ],
        }
        with (
            patch.object(
                bot,
                "_upload_to_imgbb",
                side_effect=lambda p, _: f"https://i.ibb.co/demo/{p.name}",
            ) as upload,
            patch.object(bot, "post_instagram_carousel", return_value="ig-car-99") as pub,
            patch.object(
                bot.requests,
                "get",
                return_value=self.response({"id": "ig-car-99", "permalink": "https://www.instagram.com/p/CAROUSEL/"}),
            ),
        ):
            media_id = bot.publish_instagram_card(rich_topic, "Deep dive caption #TheChronoByte")
        self.assertEqual(media_id, "ig-car-99")
        self.assertGreaterEqual(upload.call_count, 3)
        uploaded_urls = pub.call_args.args[0]
        self.assertGreaterEqual(len(uploaded_urls), 3)
        self.assertTrue(all(u.startswith("https://i.ibb.co/demo/") for u in uploaded_urls))

    def test_prepare_source_images_downloads_filters_and_deduplicates(self):
        import io
        from PIL import Image, ImageDraw

        def jpeg_bytes(size, color, stripe=False):
            img = Image.new("RGB", size, color)
            if stripe:
                d = ImageDraw.Draw(img)
                d.rectangle((0, 0, size[0] // 2, size[1]), fill=(255, 255, 255))
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            return buf.getvalue()

        hero_bytes = jpeg_bytes((1200, 800), (20, 80, 180), stripe=True)
        tiny_bytes = jpeg_bytes((180, 120), (200, 40, 40))
        second_bytes = jpeg_bytes((1000, 1000), (16, 150, 90))
        topic = {
            **self.topic,
            "image_urls": [
                "https://blogs.nvidia.com/hero.jpg",
                "https://blogs.nvidia.com/hero-copy.jpg",
                "https://blogs.nvidia.com/tiny.jpg",
                "https://blogs.nvidia.com/chart.jpg",
            ],
            "feed_image_urls": ["https://blogs.nvidia.com/feed.jpg"],
        }
        side_effects = [
            (hero_bytes, "https://blogs.nvidia.com/hero.jpg", "image/jpeg"),
            (hero_bytes, "https://blogs.nvidia.com/hero-copy.jpg", "image/jpeg"),
            (tiny_bytes, "https://blogs.nvidia.com/tiny.jpg", "image/jpeg"),
            (second_bytes, "https://blogs.nvidia.com/chart.jpg", "image/jpeg"),
        ]
        with patch.object(bot, "fetch_image_bytes", side_effect=side_effects):
            imgs = bot._prepare_source_images(topic, max_images=2)
        self.assertEqual(len(imgs), 2)
        self.assertEqual(imgs[0]["image"].size, (1200, 800))
        self.assertEqual(imgs[1]["image"].size, (1000, 1000))


if __name__ == "__main__":
    unittest.main()
