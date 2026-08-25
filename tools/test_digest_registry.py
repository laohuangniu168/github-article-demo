from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from digest_registry import (
    DIGEST_CONFIG_VERSION,
    DIGEST_SCHEMA_VERSION,
    DigestContractError,
    build_digest_registry,
    compute_digest_normalized_identity,
    parse_digest_file,
    parse_digest_lines,
    validate_digest_title,
    validate_digest_url,
)


class DigestRegistryTests(unittest.TestCase):
    def assert_error(self, code: str, text: str) -> DigestContractError:
        with self.assertRaises(DigestContractError) as caught:
            parse_digest_lines(text, source_filename="test.txt")
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_single_http(self):
        entry = parse_digest_lines("http://example.com/a|标题")[0]
        self.assertEqual("http://example.com/a", entry.url_exact)

    def test_single_https(self):
        entry = parse_digest_lines("https://example.com/a|标题")[0]
        self.assertEqual("https://example.com/a", entry.url_exact)

    def test_mixed_http_https(self):
        entries = parse_digest_lines("http://a.com/x|甲\nhttps://b.com/y|乙")
        self.assertEqual(2, len(entries))

    def test_utf8_chinese_title(self):
        self.assertEqual("中文资讯标题", parse_digest_lines("https://a.com|中文资讯标题")[0].title)

    def test_bom_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "digest.txt")
            path.write_bytes("\ufeffhttps://a.com|标题\n".encode("utf-8"))
            self.assertEqual(1, len(parse_digest_file(path)))

    def test_non_utf8_file_fails_structurally(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "digest.txt")
            path.write_bytes(b"\xff\xfe\x00")
            with self.assertRaises(DigestContractError) as caught:
                parse_digest_file(path)
            self.assertEqual("INVALID_DIGEST_INPUT_FORMAT", caught.exception.code)

    def test_blank_lines_ignored(self):
        self.assertEqual(1, len(parse_digest_lines("\nhttps://a.com|标题\n\n")))

    def test_outer_whitespace_trimmed(self):
        entry = parse_digest_lines("  https://a.com/x  |  标题  ")[0]
        self.assertEqual(("https://a.com/x", "标题"), (entry.url_exact, entry.title))

    def test_one_field_fails(self):
        self.assert_error("INVALID_DIGEST_INPUT_FORMAT", "https://a.com")

    def test_hash_prefix_is_not_a_comment(self):
        error = self.assert_error("INVALID_DIGEST_INPUT_FORMAT", "# not a comment")
        self.assertEqual(1, error.line_number)

    def test_three_fields_fail(self):
        self.assert_error("INVALID_DIGEST_INPUT_FORMAT", "https://a.com|标题|extra")

    def test_extra_pipe_fails(self):
        self.assert_error("INVALID_DIGEST_INPUT_FORMAT", "https://a.com|标|题")

    def test_empty_url_fails(self):
        self.assert_error("INVALID_DIGEST_URL", " |标题")

    def test_empty_title_fails(self):
        self.assert_error("INVALID_DIGEST_TITLE", "https://a.com| ")

    def test_non_http_scheme_fails(self):
        self.assert_error("INVALID_DIGEST_URL", "javascript:alert|标题")

    def test_missing_hostname_fails(self):
        self.assert_error("INVALID_DIGEST_URL", "https:///path|标题")

    def test_url_control_character_fails(self):
        with self.assertRaises(DigestContractError) as caught:
            validate_digest_url("https://a.com/\x01x", 7)
        self.assertEqual(("INVALID_DIGEST_URL", 7), (caught.exception.code, caught.exception.line_number))

    def test_url_newline_fails(self):
        with self.assertRaises(DigestContractError):
            validate_digest_url("https://a.com/a\nb")

    def test_uppercase_scheme_is_preserved(self):
        url = "HTTP://example.com/Path"
        self.assertEqual(url, validate_digest_url(url))

    def test_url_internal_whitespace_fails(self):
        with self.assertRaises(DigestContractError):
            validate_digest_url("https://a.com/a b")

    def test_url_parentheses_fail(self):
        for value in ("https://a.com/a(b", "https://a.com/a)b"):
            with self.subTest(value=value), self.assertRaises(DigestContractError):
                validate_digest_url(value)

    def test_url_angle_brackets_fail(self):
        for value in ("https://a.com/<x", "https://a.com/>x"):
            with self.subTest(value=value), self.assertRaises(DigestContractError):
                validate_digest_url(value)

    def test_url_backslash_fails(self):
        with self.assertRaises(DigestContractError):
            validate_digest_url("https://a.com/a\\b")

    def test_title_brackets_fail(self):
        for title in ("标题[甲", "标题]甲"):
            with self.subTest(title=title), self.assertRaises(DigestContractError):
                validate_digest_title(title)

    def test_title_backslash_fails(self):
        with self.assertRaises(DigestContractError):
            validate_digest_title("标题\\甲")

    def test_title_control_fails(self):
        with self.assertRaises(DigestContractError):
            validate_digest_title("标题\x7f")

    def test_title_newline_fails(self):
        with self.assertRaises(DigestContractError):
            validate_digest_title("标题\n第二行")

    def test_title_length_limit(self):
        self.assertEqual(200, len(validate_digest_title("字" * 200)))
        with self.assertRaises(DigestContractError):
            validate_digest_title("字" * 201)

    def test_chinese_punctuation_allowed(self):
        title = "标题：甲，乙。为什么？很好！《资料》“说明”（测试）·连接—结束"
        self.assertEqual(title, validate_digest_title(title))

    def test_double_slash_path_preserved(self):
        url = "http://example.com/Article/details//123.shtml"
        self.assertEqual(url, parse_digest_lines(f"{url}|标题")[0].url_exact)

    def test_query_preserved(self):
        url = "http://example.com/?ArTicle/details/10316ifx.shtml"
        self.assertEqual(url, parse_digest_lines(f"{url}|标题")[0].url_exact)

    def test_fragment_preserved(self):
        url = "https://example.com/path?a=1&b=2#section"
        self.assertEqual(url, parse_digest_lines(f"{url}|标题")[0].url_exact)

    def test_path_case_preserved(self):
        url = "https://example.com/Path/Case"
        self.assertEqual(url, parse_digest_lines(f"{url}|标题")[0].url_exact)

    def test_trailing_slash_identity_separation(self):
        self.assertNotEqual(
            compute_digest_normalized_identity("https://a.com/page"),
            compute_digest_normalized_identity("https://a.com/page/"),
        )

    def test_http_https_identity_separation(self):
        self.assertNotEqual(
            compute_digest_normalized_identity("http://a.com/page"),
            compute_digest_normalized_identity("https://a.com/page"),
        )

    def test_duplicate_exact_url_fails(self):
        error = self.assert_error("DUPLICATE_DIGEST_URL", "https://a.com/x|甲\nhttps://a.com/x|甲")
        self.assertEqual((2, 1), (error.line_number, error.first_line_number))

    def test_same_url_different_title_still_duplicate(self):
        self.assert_error("DUPLICATE_DIGEST_URL", "https://a.com/x|甲\nhttps://a.com/x|乙")

    def test_same_hostname_different_path_allowed(self):
        self.assertEqual(2, len(parse_digest_lines("https://a.com/x|甲\nhttps://a.com/y|乙")))

    def test_same_path_different_query_allowed(self):
        self.assertEqual(2, len(parse_digest_lines("https://a.com/x?a=1|甲\nhttps://a.com/x?a=2|乙")))

    def test_same_query_different_fragment_allowed(self):
        self.assertEqual(2, len(parse_digest_lines("https://a.com/x?a=1#x|甲\nhttps://a.com/x?a=1#y|乙")))

    def test_normalized_identity_exact_algorithm(self):
        url = "https://Example.com/Path?a=1#X"
        self.assertEqual(hashlib.sha256(url.encode("utf-8")).hexdigest(), compute_digest_normalized_identity(url))

    def test_entry_id_algorithm(self):
        entry = parse_digest_lines("https://a.com/x|甲")[0]
        self.assertEqual("de-" + entry.normalized_identity[:16], entry.id)

    def test_registry_versions_and_constants(self):
        registry = build_digest_registry(parse_digest_lines("https://a.com/x|甲"))
        self.assertEqual(("1", "v1.2-digest-default-1"), (DIGEST_SCHEMA_VERSION, DIGEST_CONFIG_VERSION))
        self.assertRegex(registry.digest_registry_version, r"^dgr1:[0-9a-f]{64}$")

    def test_registry_version_deterministic(self):
        entries = parse_digest_lines("https://a.com/x|甲\nhttps://b.com/y|乙")
        self.assertEqual(build_digest_registry(entries).digest_registry_version, build_digest_registry(entries).digest_registry_version)

    def test_input_reorder_version_unchanged(self):
        left = parse_digest_lines("https://a.com/x|甲\nhttps://b.com/y|乙", source_filename="one.txt")
        right = parse_digest_lines("https://b.com/y|乙\nhttps://a.com/x|甲", source_filename="two.txt")
        self.assertEqual(build_digest_registry(left).digest_registry_version, build_digest_registry(right).digest_registry_version)

    def test_source_filename_version_unchanged(self):
        a = parse_digest_lines("https://a.com/x|甲", source_filename="a.txt")
        b = parse_digest_lines("https://a.com/x|甲", source_filename="b.txt")
        self.assertEqual(build_digest_registry(a).digest_registry_version, build_digest_registry(b).digest_registry_version)

    def test_source_line_version_unchanged(self):
        a = parse_digest_lines("https://a.com/x|甲", source_filename="a.txt")
        b = parse_digest_lines("\n\nhttps://a.com/x|甲", source_filename="a.txt")
        self.assertNotEqual(a[0].source_line, b[0].source_line)
        self.assertEqual(build_digest_registry(a).digest_registry_version, build_digest_registry(b).digest_registry_version)

    def test_provenance_preserved(self):
        entries = parse_digest_lines("\nhttps://b.com/y|乙\n\nhttps://a.com/x|甲", source_filename="source.txt")
        by_url = {entry.url_exact: entry for entry in build_digest_registry(entries).entries}
        self.assertEqual(("source.txt", 2), (by_url["https://b.com/y"].source_filename, by_url["https://b.com/y"].source_line))
        self.assertEqual(4, by_url["https://a.com/x"].source_line)

    def test_url_change_changes_version(self):
        a = build_digest_registry(parse_digest_lines("https://a.com/x|甲"))
        b = build_digest_registry(parse_digest_lines("https://a.com/y|甲"))
        self.assertNotEqual(a.digest_registry_version, b.digest_registry_version)

    def test_title_change_changes_version(self):
        a = build_digest_registry(parse_digest_lines("https://a.com/x|甲"))
        b = build_digest_registry(parse_digest_lines("https://a.com/x|乙"))
        self.assertNotEqual(a.digest_registry_version, b.digest_registry_version)

    def test_http_to_https_changes_version(self):
        a = build_digest_registry(parse_digest_lines("http://a.com/x|甲"))
        b = build_digest_registry(parse_digest_lines("https://a.com/x|甲"))
        self.assertNotEqual(a.digest_registry_version, b.digest_registry_version)

    def test_registry_entries_sorted_by_identity(self):
        registry = build_digest_registry(parse_digest_lines("https://b.com/y|乙\nhttps://a.com/x|甲"))
        identities = [entry.normalized_identity for entry in registry.entries]
        self.assertEqual(sorted(identities), identities)

    def test_identity_collision_fails(self):
        entries = parse_digest_lines("https://a.com/x|甲\nhttps://b.com/y|乙")
        collided = (entries[0], replace(entries[1], id=entries[0].id))
        with self.assertRaises(DigestContractError) as caught:
            build_digest_registry(collided)
        self.assertEqual("DIGEST_IDENTITY_COLLISION", caught.exception.code)

    def test_hash_collision_detected_while_parsing(self):
        hashes = ["a" * 64, "a" * 16 + "b" * 48]
        with patch("digest_registry.compute_digest_normalized_identity", side_effect=hashes):
            self.assert_error("DIGEST_IDENTITY_COLLISION", "https://a.com/x|甲\nhttps://b.com/y|乙")

    def test_hash_has_no_environment_inputs(self):
        url = "https://a.com/x"
        self.assertEqual(compute_digest_normalized_identity(url), compute_digest_normalized_identity(url))

    def test_no_network_or_openai_imports(self):
        source = Path(__file__).with_name("digest_registry.py").read_text(encoding="utf-8")
        forbidden = ("requests", "urllib.request", "http.client", "socket", "httpx", "aiohttp", "openai")
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
