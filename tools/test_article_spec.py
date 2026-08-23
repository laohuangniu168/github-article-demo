from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from article_spec import ArticleSpecError, parse_article_specs


class ArticleSpecParserTests(unittest.TestCase):
    def parse(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "articles.txt"
            path.write_text(text, encoding="utf-8")
            return parse_article_specs(path)

    def assert_code(self, code: str, text: str) -> None:
        with self.assertRaises(ArticleSpecError) as raised:
            self.parse(text)
        self.assertEqual(raised.exception.code, code)
        self.assertGreaterEqual(raised.exception.line_number, 1)

    def test_valid_two_fields(self) -> None:
        spec = self.parse("github-pages-guide|GitHub Pages 指南\n")[0]
        self.assertEqual((spec.slug, spec.title), ("github-pages-guide", "GitHub Pages 指南"))
        self.assertEqual((spec.cluster, spec.cluster_source), ("github-pages", "inferred"))

    def test_valid_three_fields(self) -> None:
        spec = self.parse("custom-slug|标题|content-seo\n")[0]
        self.assertEqual((spec.cluster, spec.cluster_source), ("content-seo", "explicit"))

    def test_empty_third_cluster_uses_inference(self) -> None:
        spec = self.parse("technical-seo-audit|标题|   \n")[0]
        self.assertEqual((spec.cluster, spec.cluster_source), ("technical-seo", "inferred"))

    def test_invalid_fourth_field(self) -> None:
        self.assert_code("INVALID_INPUT_FORMAT", "slug|title|content-seo|extra\n")

    def test_invalid_slug(self) -> None:
        self.assert_code("INVALID_INPUT_FORMAT", "Bad Slug|title\n")

    def test_empty_title(self) -> None:
        self.assert_code("INVALID_INPUT_FORMAT", "valid-slug|   \n")

    def test_invalid_explicit_cluster(self) -> None:
        self.assert_code("INVALID_CLUSTER", "valid-slug|title|unknown\n")

    def test_duplicate_slug(self) -> None:
        self.assert_code("INVALID_INPUT_FORMAT", "same|一\nsame|二\n")

    def test_duplicate_title(self) -> None:
        self.assert_code("INVALID_INPUT_FORMAT", "one|相同\ntwo|相同\n")

    def test_inferred_cluster(self) -> None:
        spec = self.parse("seo-keyword-research|关键词研究\n")[0]
        self.assertEqual((spec.cluster, spec.cluster_source), ("keyword-research", "inferred"))

    def test_unclassified(self) -> None:
        spec = self.parse("plain-topic|普通主题\n")[0]
        self.assertEqual((spec.cluster, spec.cluster_source), ("unclassified", "unclassified"))

    def test_ambiguous_cluster(self) -> None:
        self.assert_code(
            "AMBIGUOUS_CLUSTER_INFERENCE",
            "plain-topic|百度蜘蛛抓取与百度收录分析\n",
        )


if __name__ == "__main__":
    unittest.main()
