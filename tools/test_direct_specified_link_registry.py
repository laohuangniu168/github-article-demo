from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

from direct_specified_link_registry import (
    DIRECT_APPROVAL_SOURCE,
    DIRECT_CONFIG_VERSION,
    DIRECT_SCHEMA_VERSION,
    DirectSpecifiedLinkContractError,
    build_direct_registry,
    canonicalize_direct_url,
    normalize_direct_anchor,
    parse_direct_link_lines,
    validate_direct_registry,
)


class DirectSpecifiedLinkRegistryTests(unittest.TestCase):
    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(DirectSpecifiedLinkContractError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def entries(self, lines=None, source_filename="direct.txt"):
        lines = lines or [
            "target-001|http://news.real-domain.tld/Article/A|新闻 A\n",
            "target-002|https://docs.real-domain.tld/path|文档 B\n",
        ]
        return parse_direct_link_lines(lines, source_filename=source_filename)

    def test_legal_http(self):
        self.assertEqual(self.entries()[0].canonical_url, "http://news.real-domain.tld/Article/A")

    def test_legal_https(self):
        self.assertEqual(self.entries()[1].canonical_url, "https://docs.real-domain.tld/path")

    def test_default_ports_canonicalized(self):
        self.assertEqual(canonicalize_direct_url("HTTP://News.Real-Domain.TLD:80/A"), "http://news.real-domain.tld/A")
        self.assertEqual(canonicalize_direct_url("HTTPS://Docs.Real-Domain.TLD:443/B"), "https://docs.real-domain.tld/B")

    def test_http_https_identity_separated(self):
        entries = self.entries([
            "target-http|http://host.real-domain.tld/path|来源\n",
            "target-https|https://host.real-domain.tld/path|来源\n",
        ])
        self.assertNotEqual(entries[0].canonical_url, entries[1].canonical_url)

    def test_path_case_preserved(self):
        self.assertEqual(canonicalize_direct_url("http://host.real-domain.tld/Article/AbC"), "http://host.real-domain.tld/Article/AbC")

    def test_double_slash_path_preserved(self):
        value = "http://host.real-domain.tld/Article/details//123.shtml"
        self.assertEqual(canonicalize_direct_url(value), value)

    def test_empty_path_becomes_slash(self):
        self.assertEqual(canonicalize_direct_url("https://host.real-domain.tld"), "https://host.real-domain.tld/")

    def test_query_and_fragment_preserved(self):
        value = "https://host.real-domain.tld/Path?A=1&b=%29#Part-2"
        self.assertEqual(canonicalize_direct_url(value), value)

    def test_userinfo_rejected(self):
        self.assert_code("INVALID_DIRECT_URL", lambda: canonicalize_direct_url("https://user@host.real-domain.tld/path"))

    def test_localhost_rejected(self):
        self.assert_code("INVALID_DIRECT_URL", lambda: canonicalize_direct_url("http://localhost/path"))

    def test_ip_literal_rejected(self):
        for value in ("http://127.0.0.1/path", "http://[::1]/path"):
            with self.subTest(value=value):
                self.assert_code("INVALID_DIRECT_URL", lambda value=value: canonicalize_direct_url(value))

    def test_unsafe_schemes_rejected(self):
        for value in ("javascript:alert", "data:text/plain,x", "file:///tmp/x", "mailto:a@b.test"):
            with self.subTest(value=value):
                self.assert_code("DIRECT_UNSAFE_SCHEME", lambda value=value: canonicalize_direct_url(value))

    def test_control_whitespace_and_backslash_rejected(self):
        for value in (
            "https://host.real-domain.tld/a b",
            "https://host.real-domain.tld/a\nb",
            "https:\\host.real-domain.tld\\path",
        ):
            with self.subTest(value=value):
                self.assert_code("INVALID_DIRECT_URL", lambda value=value: canonicalize_direct_url(value))

    def test_markdown_destination_breakers_rejected(self):
        for character in "()<>":
            with self.subTest(character=character):
                self.assert_code(
                    "INVALID_DIRECT_URL",
                    lambda character=character: canonicalize_direct_url(f"https://host.real-domain.tld/a{character}b"),
                )

    def test_invalid_hostname_rejected(self):
        for value in ("https://-bad.real-domain.tld/path", "https://bad..real-domain.tld/path", "https://例子.测试/path"):
            with self.subTest(value=value):
                self.assert_code("INVALID_DIRECT_URL", lambda value=value: canonicalize_direct_url(value))

    def test_non_default_and_mismatched_ports_rejected(self):
        for value in ("http://host.real-domain.tld:443/path", "https://host.real-domain.tld:80/path", "https://host.real-domain.tld:8443/path"):
            with self.subTest(value=value):
                self.assert_code("INVALID_DIRECT_URL", lambda value=value: canonicalize_direct_url(value))

    def test_dot_segments_rejected(self):
        for value in ("https://host.real-domain.tld/a/./b", "https://host.real-domain.tld/a/../b"):
            with self.subTest(value=value):
                self.assert_code("INVALID_DIRECT_URL", lambda value=value: canonicalize_direct_url(value))

    def test_exactly_three_fields_required(self):
        for line in ("id|https://host.real-domain.tld/", "id|https://host.real-domain.tld/|A|extra"):
            with self.subTest(line=line):
                self.assert_code("INVALID_DIRECT_INPUT_FORMAT", lambda line=line: parse_direct_link_lines([line]))

    def test_comment_has_no_special_semantics(self):
        self.assert_code("INVALID_DIRECT_INPUT_FORMAT", lambda: parse_direct_link_lines(["# comment"]))

    def test_empty_and_invalid_id_rejected(self):
        for line in ("|https://host.real-domain.tld/|Anchor", "Bad_ID|https://host.real-domain.tld/|Anchor"):
            with self.subTest(line=line):
                self.assert_code("INVALID_DIRECT_INPUT_FORMAT", lambda line=line: parse_direct_link_lines([line]))

    def test_duplicate_id_rejected(self):
        self.assert_code(
            "DUPLICATE_DIRECT_LINK_ID",
            lambda: self.entries([
                "same|https://one.real-domain.tld/|One\n",
                "same|https://two.real-domain.tld/|Two\n",
            ]),
        )

    def test_empty_anchor_rejected(self):
        self.assert_code("EMPTY_DIRECT_ANCHOR", lambda: parse_direct_link_lines(["id|https://host.real-domain.tld/|  "]))

    def test_invalid_anchor_rejected(self):
        for anchor in ("bad[anchor", "bad]anchor", "bad\\anchor", "bad\x00anchor"):
            with self.subTest(anchor=anchor):
                self.assert_code(
                    "INVALID_DIRECT_ANCHOR",
                    lambda anchor=anchor: parse_direct_link_lines([f"id|https://host.real-domain.tld/|{anchor}"]),
                )

    def test_duplicate_url_normalized_anchor_rejected(self):
        self.assert_code(
            "DUPLICATE_DIRECT_URL_ANCHOR",
            lambda: self.entries([
                "one|HTTPS://HOST.REAL-DOMAIN.TLD:443/path|Ａ Anchor\n",
                "two|https://host.real-domain.tld/path|Ａ   ANCHOR\n",
            ]),
        )

    def test_same_url_different_anchor_allowed(self):
        entries = self.entries([
            "one|https://host.real-domain.tld/path|Anchor One\n",
            "two|https://host.real-domain.tld/path|Anchor Two\n",
        ])
        self.assertEqual(len(entries), 2)

    def test_different_url_same_anchor_allowed(self):
        entries = self.entries([
            "one|https://one.real-domain.tld/path|Same Anchor\n",
            "two|https://two.real-domain.tld/path|Same Anchor\n",
        ])
        self.assertEqual(len(entries), 2)

    def test_unicode_anchor_determinism_and_punctuation_preserved(self):
        self.assertEqual(normalize_direct_anchor("  ÉCOLE　新闻！  "), "école 新闻！")
        entry = parse_direct_link_lines(["id|https://host.real-domain.tld/|  ÉCOLE　新闻！  "])[0]
        self.assertEqual((entry.anchor, entry.normalized_anchor), ("ÉCOLE　新闻！", "école 新闻！"))

    def test_version_stable_for_input_order(self):
        first = build_direct_registry(self.entries())
        second = build_direct_registry(self.entries(list(reversed([
            "target-001|http://news.real-domain.tld/Article/A|新闻 A\n",
            "target-002|https://docs.real-domain.tld/path|文档 B\n",
        ]))))
        self.assertEqual(first.direct_registry_version, second.direct_registry_version)

    def test_version_ignores_source_filename_and_line(self):
        first_entries = self.entries(source_filename="one.txt")
        shifted_entries = parse_direct_link_lines(["\n", *[
            "target-001|http://news.real-domain.tld/Article/A|新闻 A\n",
            "target-002|https://docs.real-domain.tld/path|文档 B\n",
        ]], source_filename="two.txt")
        first = build_direct_registry(first_entries)
        second = build_direct_registry(shifted_entries)
        self.assertEqual(first.direct_registry_version, second.direct_registry_version)

    def test_url_and_anchor_changes_change_version(self):
        base = build_direct_registry(self.entries()).direct_registry_version
        changed_url = build_direct_registry(self.entries([
            "target-001|http://news.real-domain.tld/Article/Changed|新闻 A\n",
            "target-002|https://docs.real-domain.tld/path|文档 B\n",
        ])).direct_registry_version
        changed_anchor = build_direct_registry(self.entries([
            "target-001|http://news.real-domain.tld/Article/A|变化标题\n",
            "target-002|https://docs.real-domain.tld/path|文档 B\n",
        ])).direct_registry_version
        self.assertEqual(len({base, changed_url, changed_anchor}), 3)

    def test_model_is_explicitly_user_approved(self):
        entry = self.entries()[0]
        self.assertEqual(entry.approval_source, DIRECT_APPROVAL_SOURCE)
        forged = dataclasses.replace(entry, approval_source="SCRAPED")
        self.assert_code("INVALID_DIRECT_INPUT_FORMAT", lambda: build_direct_registry((forged,)))

    def test_registry_versions_and_validation(self):
        registry = build_direct_registry(self.entries())
        self.assertEqual((registry.schema_version, registry.config_version), (DIRECT_SCHEMA_VERSION, DIRECT_CONFIG_VERSION))
        self.assertTrue(registry.direct_registry_version.startswith("dlr1:"))
        self.assertIs(validate_direct_registry(registry), registry)
        self.assert_code(
            "DIRECT_REGISTRY_VERSION_MISMATCH",
            lambda: validate_direct_registry(registry, expected_version="dlr1:" + "0" * 64),
        )

    def test_no_network_or_openai_symbols(self):
        import direct_specified_link_registry as module

        source = Path(module.__file__).read_text(encoding="utf-8").lower()
        for forbidden in ("requests", "httpx", "socket", "openai", "urlopen", "urllib.request"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
