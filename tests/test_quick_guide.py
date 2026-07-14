"""Tests for the dependency-free CAM Quick Guide builder."""

import tempfile
import unittest
from pathlib import Path

from tools import build_quick_guide as guide


class QuickGuideTests(unittest.TestCase):
    def test_production_guide_has_seven_task_pages_and_local_images(self):
        document, pages = guide.render_markdown(guide.DEFAULT_SOURCE)

        self.assertEqual(pages, 7)
        self.assertEqual(document.count('<section class="task">'), 7)
        self.assertIn("Task 7 of 7", document)
        self.assertNotIn('src="quick_guide_images/', document)

        for target in guide.DEFAULT_SOURCE.parent.joinpath(
            "quick_guide_images"
        ).glob("*.svg"):
            self.assertIn(target.resolve().as_uri(), document)

    def test_markdown_subset_renders_lists_callouts_and_inline_styles(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "guide.md"
            source.write_text(
                "# Test Guide\n\n"
                "## First task\n\n"
                "1. Use **Build** and `file.txt`.\n\n"
                "> Keep it safe.\n\n"
                "![A visual](image.svg)\n",
                encoding="utf-8",
            )

            document, pages = guide.render_markdown(source)

        self.assertEqual(pages, 1)
        self.assertIn("<ol>", document)
        self.assertIn("<strong>Build</strong>", document)
        self.assertIn("<code>file.txt</code>", document)
        self.assertIn("<blockquote>", document)
        self.assertIn("image.svg", document)

    def test_source_without_task_heading_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "guide.md"
            source.write_text("# No task pages\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "level-two"):
                guide.render_markdown(source)


if __name__ == "__main__":
    unittest.main()
