"""Offline tests for the 1080x1350 editorial news card generator."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

import card_generator as cg


class CardGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.topic = {
            "source": "OpenAI",
            "topic_tag": "OpenAI",
            "text": "Introducing ChatGPT Wallet for secure agentic purchases",
            "summary": "A secure way for agents to complete purchases with user approval.",
            "paragraphs": [
                "We are introducing ChatGPT Wallet, setting a new bar for secure payments by agents without exposing actual card details.",
                "Built in partnership with American Express, Mastercard, and Visa, it rolls out first to ChatGPT Pro subscribers.",
            ],
            "source_url": "https://openai.com/index/introducing-chatgpt-wallet",
            "published": datetime(2026, 11, 13, 15, tzinfo=timezone.utc),
        }

    def test_renders_exact_1080x1350_jpeg_card(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = cg.render_news_card(self.topic, Path(tmpdir) / "card.jpg")
            self.assertTrue(out.is_file())
            with Image.open(out) as img:
                self.assertEqual(img.format, "JPEG")
                self.assertEqual(img.size, (1080, 1350))
                self.assertEqual(img.mode, "RGB")

    def test_handles_very_long_headlines_and_paragraphs_without_error(self):
        long_topic = {
            **self.topic,
            "source": "NVIDIA",
            "topic_tag": "AI Hardware",
            "text": "NVIDIA announces next-generation accelerated computing platform " * 4,
            "paragraphs": ["Long technical paragraph with detailed metrics. " * 40],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            out = cg.render_news_card(long_topic, Path(tmpdir) / "long.jpg")
            self.assertGreater(out.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
