import hashlib
import tempfile
import unittest
from pathlib import Path

from internal_link_generation_adapter import (
    GenerationAdapterError,
    project_generation_input,
    validate_generation_input,
    write_projection,
)


class GenerationAdapterTests(unittest.TestCase):
    def project(self, text: str, batch_id: str = "batch-adapter"):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "canonical.txt"
            path.write_text(text, encoding="utf-8", newline="\n")
            return project_generation_input(path, batch_id)

    def test_two_field_canonical_input_is_compatible(self):
        result = self.project("technical-seo-cache-check|缓存检查指南\n")
        self.assertEqual(result.generation_bytes, "technical-seo-cache-check|缓存检查指南\n".encode())

    def test_three_field_canonical_input_projects_two_fields(self):
        result = self.project("page-one|页面标题|content-seo\n")
        self.assertEqual(result.generation_bytes, "page-one|页面标题\n".encode())

    def test_explicit_cluster_is_preserved_only_in_mapping(self):
        result = self.project("page-one|页面标题|content-seo\n")
        self.assertEqual(result.mappings[0].cluster, "content-seo")
        self.assertNotIn(b"content-seo", result.generation_bytes)

    def test_generation_title_does_not_contain_cluster(self):
        result = self.project("page-one|页面标题|technical-seo\n")
        self.assertEqual(result.mappings[0].generation_title, "页面标题")

    def test_slug_order_is_preserved(self):
        result = self.project("page-b|标题乙|content-seo\npage-a|标题甲|technical-seo\n")
        self.assertEqual([x.slug for x in result.mappings], ["page-b", "page-a"])

    def test_invalid_fourth_field_fails_closed(self):
        with self.assertRaisesRegex(GenerationAdapterError, "INVALID_INPUT_FORMAT"):
            self.project("page-one|标题|content-seo|extra\n")

    def test_invalid_cluster_fails_closed(self):
        with self.assertRaisesRegex(GenerationAdapterError, "INVALID_CLUSTER"):
            self.project("page-one|标题|not-a-cluster\n")

    def test_duplicate_slug_has_specific_error(self):
        with self.assertRaisesRegex(GenerationAdapterError, "DUPLICATE_SLUG"):
            self.project("page-one|标题甲\npage-one|标题乙\n")

    def test_duplicate_title_has_specific_error(self):
        with self.assertRaisesRegex(GenerationAdapterError, "DUPLICATE_TITLE"):
            self.project("page-one|同一标题\npage-two|同一标题\n")

    def test_deterministic_bytes_and_sha(self):
        text = "page-one|标题|content-seo\n"
        first = self.project(text)
        second = self.project(text)
        self.assertEqual(first.generation_bytes, second.generation_bytes)
        self.assertEqual(first.generation_input_sha256, second.generation_input_sha256)
        self.assertEqual(first.generation_input_sha256, hashlib.sha256(first.generation_bytes).hexdigest())

    def test_count_mismatch_fails_closed(self):
        with self.assertRaisesRegex(GenerationAdapterError, "GENERATION_INPUT_COUNT_MISMATCH"):
            validate_generation_input(b"", (object(),))

    def test_slug_and_title_mismatch_fail_closed(self):
        result = self.project("page-one|标题|content-seo\n")
        specs = tuple(type("Spec", (), {"slug": x.slug, "title": x.canonical_title})() for x in result.mappings)
        with self.assertRaisesRegex(GenerationAdapterError, "GENERATION_INPUT_SLUG_MISMATCH"):
            validate_generation_input("page-two|标题\n".encode(), specs)
        with self.assertRaisesRegex(GenerationAdapterError, "GENERATION_INPUT_TITLE_MISMATCH"):
            validate_generation_input("page-one|其他标题\n".encode(), specs)

    def test_write_projection_uses_sha_bound_filename_and_mapping(self):
        projection = self.project("page-one|标题|content-seo\n", "batch-003")
        with tempfile.TemporaryDirectory() as temp:
            generation, mapping = write_projection(projection, Path(temp))
            self.assertIn(projection.canonical_input_sha256, generation.name)
            self.assertEqual(generation.read_bytes(), projection.generation_bytes)
            self.assertTrue(mapping.is_file())

    def test_fifty_article_projection(self):
        text = "".join(f"page-{i:02d}|标题{i:02d}|content-seo\n" for i in range(50))
        result = self.project(text, "batch-050")
        self.assertEqual(len(result.mappings), 50)
        self.assertEqual(len(result.generation_bytes.decode().splitlines()), 50)


if __name__ == "__main__":
    unittest.main()
