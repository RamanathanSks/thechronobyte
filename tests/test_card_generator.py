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

    def test_all_card_themes_render_distinct_valid_jpegs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sizes = []
            for theme in cg.CARD_THEMES:
                out = cg.render_news_card(self.topic, Path(tmpdir) / f"{theme}.jpg", theme=theme)
                with Image.open(out) as img:
                    self.assertEqual(img.size, (1080, 1350))
                    self.assertEqual(img.mode, "RGB")
                sizes.append(out.read_bytes())
            self.assertEqual(len(set(sizes)), len(cg.CARD_THEMES))

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

    def test_carousel_renders_multiple_1080x1350_slides_across_all_themes(self):
        rich_topic = {
            **self.topic,
            "paragraphs": [
                f"Paragraph {idx}: Concrete benchmark results and deployment architecture details from the official engineering release for enterprise teams and researchers."
                for idx in range(1, 9)
            ],
            "discussion_prompt": "Would you trust an AI agent with controlled checkout permissions?",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            cover_bytes = []
            for theme in cg.CARD_THEMES:
                slides = cg.render_news_carousel(
                    rich_topic,
                    Path(tmpdir) / theme,
                    theme=theme,
                    max_slides=5,
                    stem="deck",
                )
                self.assertGreaterEqual(len(slides), 3)
                self.assertLessEqual(len(slides), 5)
                for slide in slides:
                    self.assertTrue(slide.is_file())
                    with Image.open(slide) as img:
                        self.assertEqual(img.format, "JPEG")
                        self.assertEqual(img.size, (1080, 1350))
                        self.assertEqual(img.mode, "RGB")
                cover_bytes.append(slides[0].read_bytes())
            self.assertEqual(len(set(cover_bytes)), len(cg.CARD_THEMES))

    def test_carousel_uses_source_images_and_adapts_layout_without_error(self):
        hero_landscape = Image.new("RGB", (1600, 900), (24, 92, 168))
        chart_rgba = Image.new("RGBA", (1400, 900), (240, 244, 248, 220))
        wide_banner = Image.new("RGB", (2400, 800), (220, 86, 48))

        rich_topic = {
            **self.topic,
            "source": "Apple",
            "topic_tag": "Mobile Phones",
            "paragraphs": [
                "Apple unveiled the next-generation neural engine with 2.4x faster on-device inference.",
                "Updated camera pipelines improve low-light dynamic range across all pro models.",
                "Battery optimization delivers 18% longer video playback in real-world testing.",
                "Available globally starting next Friday with updated developer SDK support.",
            ],
            "discussion_prompt": "Which hardware upgrade makes the biggest difference for daily use?",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            slides = cg.render_news_carousel(
                rich_topic,
                Path(tmpdir) / "apple_photos",
                max_slides=5,
                stem="apple",
                source_images=[hero_landscape, chart_rgba],
            )
            self.assertGreaterEqual(len(slides), 3)
            for slide in slides:
                with Image.open(slide) as img:
                    self.assertEqual((img.format, img.size, img.mode), ("JPEG", (1080, 1350), "RGB"))

            spec = cg._compose_post_template(
                rich_topic, cg._coerce_source_images([wide_banner], rich_topic), None, cg._topic_seed(rich_topic)
            )
            self.assertNotEqual(spec["layout"], "full_bleed_hero")

            # No static pre-defined company palette table; palettes come live from source CSS & photos.
            self.assertFalse(hasattr(cg, "SOURCE_PALETTES"))
            css_theme = {
                "polarity": "dark",
                "accents": [[230, 88, 42], [68, 196, 152]],
                "backgrounds": [[20, 20, 19]],
                "font_hint": "serif",
            }
            live_pal = cg._resolve_live_palette(cg._coerce_source_images([hero_landscape], rich_topic), css_theme, 42)
            self.assertEqual(live_pal["origin"], "scraped_css+source_photo")
            photo_only_pal = cg._resolve_live_palette(cg._coerce_source_images([wide_banner], rich_topic), None, 42)
            self.assertEqual(photo_only_pal["origin"], "source_photo")
            self.assertNotEqual(live_pal["accent"], photo_only_pal["accent"])

            # Legacy theme aliases stay supported cleanly.
            legacy_out = cg.render_news_card(
                rich_topic,
                Path(tmpdir) / "legacy.jpg",
                theme="dark_duotone",
                source_images=[hero_landscape],
                source_theme=css_theme,
            )
            self.assertTrue(legacy_out.is_file())

            rumor_out = cg.render_news_card(
                {**rich_topic, "is_rumor": True},
                Path(tmpdir) / "rumor.jpg",
                theme="dark_duotone",
                source_images=[hero_landscape],
                source_theme=css_theme,
            )
            self.assertNotEqual(legacy_out.read_bytes(), rumor_out.read_bytes())


if __name__ == "__main__":
    unittest.main()
