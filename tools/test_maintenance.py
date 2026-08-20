from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from generate_articles import strip_trailing_whitespace
import verify_public_urls


class TrailingWhitespaceTests(unittest.TestCase):
    def test_removes_normal_line_trailing_spaces(self) -> None:
        self.assertEqual(strip_trailing_whitespace("正文   \n下一行"), "正文\n下一行")

    def test_removes_list_line_trailing_spaces(self) -> None:
        self.assertEqual(strip_trailing_whitespace("- 列表项  \n"), "- 列表项\n")

    def test_removes_fenced_code_trailing_spaces_only(self) -> None:
        source = "```python\nvalue = 'a b'   \n```\n"
        expected = "```python\nvalue = 'a b'\n```\n"
        self.assertEqual(strip_trailing_whitespace(source), expected)

    def test_removes_trailing_tabs(self) -> None:
        self.assertEqual(strip_trailing_whitespace("正文\t\t\n"), "正文\n")

    def test_preserves_text_without_trailing_whitespace(self) -> None:
        source = "正文包含 空格\n```\nvalue = 1\n```\n"
        self.assertEqual(strip_trailing_whitespace(source), source)


class PublicUrlVerifierTests(unittest.TestCase):
    def test_loads_slug_from_batch_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.txt"
            path.write_text("first-slug|标题\nsecond-slug|标题二\n", encoding="utf-8")
            self.assertEqual(
                verify_public_urls.load_slugs(path),
                ["first-slug", "second-slug"],
            )

    def test_rejects_markdown_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.txt"
            path.write_text("[https://example.com](https://example.com)\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Markdown"):
                verify_public_urls.load_slugs(path)

    def test_counts_pass_and_failure_without_retry(self) -> None:
        with patch.object(
            verify_public_urls,
            "request_status",
            side_effect=[200, 404],
        ) as request_status:
            passed, failed = verify_public_urls.verify_urls(
                ["first", "second"],
                verify_public_urls.DEFAULT_BASE_URL,
                5.0,
            )

        self.assertEqual((passed, failed), (1, 1))
        self.assertEqual(request_status.call_count, 2)


if __name__ == "__main__":
    unittest.main()
