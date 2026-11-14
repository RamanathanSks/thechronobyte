"""Offline behavior tests: all network access is mocked or blocked."""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch
from xml.sax.saxutils import escape

import requests

import post_daily as bot


class DailyThreadsPostTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.enterContext(
            patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network call"))
        )
        self.topic = {
            "source": "NVIDIA",
            "text": "NVIDIA announces a new GPU for machine learning.",
            "summary": "The new architecture improves inference throughput and energy efficiency for data centers.",
            "source_url": "https://blogs.nvidia.com/blog/new-gpu/",
            "published": datetime(2026, 11, 13, 12, tzinfo=timezone.utc),
            "topic_tag": "AI Hardware",
        }
        self.now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)

    @staticmethod
    def response(payload, status=200):
        response = requests.Response()
        response.status_code = status
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

    def test_newest_relevant_story_wins_and_extracts_html_summary_and_topic(self):
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
        ]
        with patch.object(bot.requests, "get", side_effect=feeds) as get:
            topic = bot.get_topic_of_the_day(self.now)
        self.assertEqual(topic["source"], "Google AI")
        self.assertEqual(topic["text"], "Google announces a new Gemini model")
        self.assertEqual(topic["summary"], "Faster reasoning & multimodal context.")
        self.assertEqual(topic["topic_tag"], "Google Gemini")
        self.assertEqual(get.call_count, len(bot.NEWS_FEEDS))
        self.assertIn("timeout", get.call_args.kwargs)
        self.assertIn("User-Agent", get.call_args.kwargs["headers"])

    def test_content_encoded_fallback_and_script_stripping(self):
        html_content = "<script>alert(1)</script><p>First paragraph.</p><p>Second paragraph.</p>"
        with patch.object(bot.requests, "get", return_value=self.feed([{"content": html_content}])):
            topic = bot.get_topic_of_the_day(self.now)
        self.assertEqual(topic["summary"], "First paragraph. Second paragraph.")

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
        feeds = [requests.Timeout(), self.feed([{}]), self.feed([]), self.feed([]), self.feed([])]
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
        with patch.object(bot.requests, "get", return_value=self.feed([{"title": title}])):
            topic = bot.get_topic_of_the_day(self.now)
        self.assertEqual(topic["text"], "AI & GPUs: A new model")

    def test_no_groq_key_builds_readable_post_without_raw_url(self):
        post_text = bot.generate_post(self.topic)
        self.assertEqual(
            post_text,
            "NVIDIA | 2026-11-13\n\n"
            "NVIDIA announces a new GPU for machine learning.\n\n"
            "The new architecture improves inference throughput and energy efficiency for data centers.",
        )
        self.assertNotIn("https://", post_text)

    def test_summary_that_starts_with_title_is_not_duplicated(self):
        topic = {
            **self.topic,
            "source": "OpenAI",
            "text": "Introducing ChatGPT Wallet",
            "summary": "Introducing ChatGPT Wallet, a secure way for agents to complete purchases.",
        }
        post_text = bot.generate_post(topic)
        self.assertEqual(
            post_text,
            "OpenAI | 2026-11-13\n\n"
            "Introducing ChatGPT Wallet, a secure way for agents to complete purchases.",
        )

    def test_long_summaries_and_unicode_fit_within_500_limit(self):
        for summary in ("New machine learning research. " * 100, "界😀" * 300, "x" * 700):
            with self.subTest(summary=summary[:25]):
                post_text = bot.generate_post({**self.topic, "summary": summary})
                self.assertLessEqual(len(post_text), 500)
                self.assertLessEqual(bot._post_weight(post_text), 500)

    def test_topic_tag_selection_respects_threads_rules(self):
        cases = (
            ({"source": "OpenAI", "text": "ChatGPT update"}, "OpenAI"),
            ({"source": "Google AI", "text": "Gemini 4 release"}, "Google Gemini"),
            ({"source": "AMD", "text": "New EPYC processor"}, "AI Hardware"),
            ({"source": "Microsoft Research", "text": "New neural architecture"}, "Machine Learning"),
            ({"source": "Microsoft Research", "text": "AI policy update"}, "Artificial Intelligence"),
        )
        for sample, expected in cases:
            tag = bot._pick_topic_tag(sample)
            self.assertEqual(tag, expected)
            self.assertNotIn(".", tag)
            self.assertNotIn("&", tag)
            self.assertLessEqual(len(tag), 50)

    def test_valid_groq_rewrite_uses_requested_model(self):
        os.environ["GROQ_API_KEY"] = "test-groq-key"
        payload = {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": "NVIDIA unveiled a new ML GPU focused on faster inference and efficiency."},
            }]
        }
        with patch.object(bot.requests, "post", return_value=self.response(payload)) as post:
            post_text = bot.generate_post(self.topic)
        self.assertIn("NVIDIA unveiled a new ML GPU", post_text)
        self.assertTrue(post_text.startswith("NVIDIA | 2026-11-13\n\n"))
        self.assertNotIn("https://", post_text)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "llama-3.1-8b-instant")
        self.assertIn("timeout", post.call_args.kwargs)
        post.assert_called_once()

    def test_bad_groq_responses_fall_back(self):
        fallback = bot.generate_post(self.topic)
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
                    self.assertEqual(bot.generate_post(self.topic), fallback)

    def test_groq_errors_fall_back_without_leaking_key(self):
        fallback = bot.generate_post(self.topic)
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
                        self.assertEqual(bot.generate_post(self.topic), fallback)
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

    def test_threads_two_step_container_with_topic_reply_control_and_link_card(self):
        self.credentials()
        responses = [
            self.response({"id": "container-111"}),
            self.response({"id": "post-999"}),
        ]
        status_responses = [
            self.response({"id": "container-111", "status": "IN_PROGRESS"}),
            self.response({"id": "container-111", "status": "FINISHED"}),
        ]
        with (
            patch.object(bot.requests, "post", side_effect=responses) as post,
            patch.object(bot.requests, "get", side_effect=status_responses) as get,
            patch.object(bot.time, "sleep") as sleep,
        ):
            post_id = bot.post_to_threads(
                "NVIDIA news",
                self.topic["source_url"],
                topic_tag="AI. & Hardware",
                reply_control="followers_only",
            )
        self.assertEqual(post_id, "post-999")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(2.0)

        first_call, second_call = post.call_args_list
        self.assertEqual(first_call.args[0], "https://graph.threads.net/v1.0/1234567890/threads")
        self.assertEqual(first_call.kwargs["data"], {
            "media_type": "TEXT",
            "text": "NVIDIA news",
            "link_attachment": self.topic["source_url"],
            "reply_control": "followers_only",
            "topic_tag": "AI  Hardware",
            "access_token": "test-threads-token",
        })
        self.assertEqual(first_call.kwargs["timeout"], (5, 20))

        self.assertEqual(second_call.args[0], "https://graph.threads.net/v1.0/1234567890/threads_publish")
        self.assertEqual(second_call.kwargs["data"], {
            "creation_id": "container-111",
            "access_token": "test-threads-token",
        })
        self.assertEqual(second_call.kwargs["timeout"], (5, 20))

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
            with patch.object(bot, "post_to_threads") as post:
                with self.assertLogs(bot.LOGGER, level="INFO") as logs:
                    self.assertEqual(bot.main([]), 0)
        post.assert_not_called()
        combined_logs = " ".join(logs.output)
        self.assertIn("DRY RUN", combined_logs)
        self.assertIn("Topic: AI Hardware", combined_logs)

    def test_main_only_posts_with_explicit_false_and_passes_topic_tag(self):
        os.environ["DRY_RUN"] = "false"
        with patch.object(bot, "get_topic_of_the_day", return_value=self.topic):
            with patch.object(bot, "post_to_threads", return_value="999") as post:
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
            with patch.object(bot, "generate_post") as generate, patch.object(bot, "post_to_threads") as post:
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


if __name__ == "__main__":
    unittest.main()
