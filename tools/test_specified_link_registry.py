import dataclasses
import tempfile
import unittest
from pathlib import Path

from specified_link_registry import (
    ALLOWED_CLUSTERS,
    ALLOWED_SCHEMES,
    HTTPS_REQUIRED,
    SpecifiedLinkContractError,
    SpecifiedLinkPreflightResult,
    build_specified_link_registry,
    canonicalize_specified_url,
    normalize_specified_anchor,
    parse_specified_link_file,
    parse_specified_link_lines,
    validate_preflight_result,
)


class SpecifiedLinkRegistryTests(unittest.TestCase):
    def parse(self, text: str, source: str = "links.txt"):
        return parse_specified_link_lines(text.splitlines(keepends=True), source_filename=source)

    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(SpecifiedLinkContractError) as context:
            callback()
        self.assertEqual(context.exception.code, code)

    def one(self, *, url="https://domain.com/seo/", anchor="SEO优化", cluster="baidu-seo"):
        entries = self.parse(f"main-seo-001|{url}|{anchor}|{cluster}\n")
        return build_specified_link_registry(entries)

    def preflight(self, registry, **changes):
        entry = registry.entries[0]
        values = {
            "entry_id": entry.id,
            "configured_url": entry.url,
            "canonical_url": entry.canonical_url,
            "status_code": 200,
            "redirect_location": None,
            "checked_at": "2026-08-25T00:00:00Z",
            "result": "PASS",
            "error_code": None,
        }
        values.update(changes)
        return SpecifiedLinkPreflightResult(**values)

    def test_legal_four_field_input_and_provenance(self):
        entry = self.parse(" main-seo-001 | https://domain.com/SEO/ | SEO优化 | baidu-seo \n", "source.txt")[0]
        self.assertEqual(entry.id, "main-seo-001")
        self.assertEqual(entry.anchor, "SEO优化")
        self.assertEqual(entry.source_filename, "source.txt")
        self.assertEqual(entry.source_line, 1)

    def test_three_fields_fail(self):
        self.assert_code("INVALID_SPECIFIED_INPUT_FORMAT", lambda: self.parse("id|https://domain.com/|anchor\n"))

    def test_five_fields_fail(self):
        self.assert_code("INVALID_SPECIFIED_INPUT_FORMAT", lambda: self.parse("id|https://domain.com/|anchor|baidu-seo|x\n"))

    def test_empty_field_fails(self):
        self.assert_code("INVALID_SPECIFIED_INPUT_FORMAT", lambda: self.parse("id||anchor|baidu-seo\n"))

    def test_comment_line_is_not_supported(self):
        self.assert_code("INVALID_SPECIFIED_INPUT_FORMAT", lambda: self.parse("# comment\n"))

    def test_invalid_ids_fail(self):
        for entry_id in ("Main-SEO", "main_seo", "main seo", "-main", "main-", "main--seo", "中文id"):
            with self.subTest(entry_id=entry_id):
                self.assert_code(
                    "INVALID_SPECIFIED_INPUT_FORMAT",
                    lambda value=entry_id: self.parse(f"{value}|https://domain.com/|anchor|baidu-seo\n"),
                )

    def test_duplicate_id_fails(self):
        text = "id-one|https://domain.com/a|Alpha|baidu-seo\nid-one|https://domain.com/b|Beta|baidu-seo\n"
        self.assert_code("DUPLICATE_SPECIFIED_LINK_ID", lambda: self.parse(text))

    def test_file_parser_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "links.txt"
            path.write_text("id-one|https://domain.com/|Anchor|baidu-seo\n", encoding="utf-8-sig")
            self.assertEqual(len(parse_specified_link_file(path)), 1)

    def test_https_canonicalization(self):
        self.assertEqual(canonicalize_specified_url("HTTPS://Domain.COM"), "https://domain.com/")
        self.assertEqual(canonicalize_specified_url("https://Domain.com:443/SEO/"), "https://domain.com/SEO/")

    def test_allowed_schemes_are_http_and_https(self):
        self.assertEqual(ALLOWED_SCHEMES, frozenset({"http", "https"}))
        self.assertEqual(HTTPS_REQUIRED, "HTTPS_REQUIRED")

    def test_http_is_accepted_and_default_port_is_removed(self):
        self.assertEqual(canonicalize_specified_url("HTTP://Domain.COM"), "http://domain.com/")
        self.assertEqual(canonicalize_specified_url("http://Domain.com:80/SEO/"), "http://domain.com/SEO/")

    def test_scheme_port_mismatch_and_non_default_ports_fail(self):
        for url in (
            "http://domain.com:443/",
            "http://domain.com:81/",
            "https://domain.com:80/",
            "https://domain.com:444/",
        ):
            with self.subTest(url=url):
                self.assert_code("INVALID_SPECIFIED_URL", lambda value=url: canonicalize_specified_url(value))

    def test_path_case_and_trailing_slash_are_preserved(self):
        self.assertEqual(canonicalize_specified_url("https://domain.com/SEO"), "https://domain.com/SEO")
        self.assertNotEqual(canonicalize_specified_url("https://domain.com/page"), canonicalize_specified_url("https://domain.com/page/"))

    def test_legal_http_does_not_trigger_legacy_https_required(self):
        self.assertEqual(canonicalize_specified_url("http://domain.com/"), "http://domain.com/")

    def test_other_schemes_fail(self):
        for url in ("javascript:alert(1)", "data:text/plain,x", "file:///tmp/x", "mailto:a@b.com", "ftp://domain.com/"):
            with self.subTest(url=url):
                self.assert_code("INVALID_SPECIFIED_URL", lambda value=url: canonicalize_specified_url(value))

    def test_http_query_and_fragment_fail(self):
        self.assert_code("URL_QUERY_NOT_ALLOWED", lambda: canonicalize_specified_url("http://domain.com/?a=1"))
        self.assert_code("URL_FRAGMENT_NOT_ALLOWED", lambda: canonicalize_specified_url("http://domain.com/#x"))

    def test_http_userinfo_local_ip_forbidden_host_and_dot_segment_fail(self):
        cases = (
            ("INVALID_SPECIFIED_URL", "http://user:pass@domain.com/"),
            ("LOCAL_OR_IP_TARGET_REJECTED", "http://localhost/"),
            ("LOCAL_OR_IP_TARGET_REJECTED", "http://127.0.0.1/"),
            ("LOCAL_OR_IP_TARGET_REJECTED", "http://sub.example.com/"),
            ("INVALID_SPECIFIED_URL", "http://domain.com/a/../b"),
        )
        for code, url in cases:
            with self.subTest(url=url):
                self.assert_code(code, lambda value=url: canonicalize_specified_url(value))

    def test_http_and_https_are_distinct_canonical_identities(self):
        http = canonicalize_specified_url("http://domain.com/page")
        https = canonicalize_specified_url("https://domain.com/page")
        self.assertNotEqual(http, https)
        entries = self.parse(
            "id-http|http://domain.com/page|HTTP Anchor|baidu-seo\n"
            "id-https|https://domain.com/page|HTTPS Anchor|baidu-seo\n"
        )
        registry = build_specified_link_registry(entries)
        self.assertEqual({entry.canonical_url for entry in registry.entries}, {http, https})

    def test_query_and_fragment_fail(self):
        self.assert_code("URL_QUERY_NOT_ALLOWED", lambda: canonicalize_specified_url("https://domain.com/?a=1"))
        self.assert_code("URL_FRAGMENT_NOT_ALLOWED", lambda: canonicalize_specified_url("https://domain.com/#x"))

    def test_userinfo_and_non_default_port_fail(self):
        self.assert_code("INVALID_SPECIFIED_URL", lambda: canonicalize_specified_url("https://user:pass@domain.com/"))
        self.assert_code("INVALID_SPECIFIED_URL", lambda: canonicalize_specified_url("https://domain.com:444/"))

    def test_ip_literals_fail(self):
        self.assert_code("LOCAL_OR_IP_TARGET_REJECTED", lambda: canonicalize_specified_url("https://127.0.0.1/"))
        self.assert_code("LOCAL_OR_IP_TARGET_REJECTED", lambda: canonicalize_specified_url("https://[::1]/"))

    def test_forbidden_hosts_and_subdomains_fail(self):
        hosts = (
            "localhost", "site.local", "site.internal", "site.test", "site.invalid", "site.example",
            "example.com", "sub.example.com", "example.net", "sub.example.net", "example.org", "sub.example.org",
        )
        for host in hosts:
            with self.subTest(host=host):
                self.assert_code("LOCAL_OR_IP_TARGET_REJECTED", lambda value=host: canonicalize_specified_url(f"https://{value}/"))

    def test_dns_boundary_does_not_reject_notexample(self):
        self.assertEqual(canonicalize_specified_url("https://notexample.com/"), "https://notexample.com/")

    def test_malformed_hosts_fail(self):
        for url in ("https://domain.com./", "https://domain..com/", "https://-domain.com/", "https://domain_.com/", "https:///path"):
            with self.subTest(url=url):
                self.assert_code("INVALID_SPECIFIED_URL", lambda value=url: canonicalize_specified_url(value))

    def test_non_ascii_hostname_fails(self):
        self.assert_code("INVALID_SPECIFIED_URL", lambda: canonicalize_specified_url("https://例子.com/"))

    def test_dot_segments_backslash_and_whitespace_fail(self):
        for url in ("https://domain.com/a/../b", "https://domain.com/./b", "https://domain.com/a\\b", "https://domain.com/a b"):
            with self.subTest(url=url):
                self.assert_code("INVALID_SPECIFIED_URL", lambda value=url: canonicalize_specified_url(value))

    def test_percent_encoding_is_preserved(self):
        self.assertEqual(canonicalize_specified_url("https://domain.com/%2fSEO"), "https://domain.com/%2fSEO")

    def test_anchor_normalization(self):
        self.assertEqual(normalize_specified_anchor("  ，ＳＥＯ   Guide！  "), "ｓｅｏ guide")
        self.assertEqual(normalize_specified_anchor("E\u0301"), normalize_specified_anchor("É"))
        self.assertEqual(normalize_specified_anchor("Straße"), "strasse")

    def test_anchor_length_limits(self):
        self.assert_code("INVALID_SPECIFIED_ANCHOR_LENGTH", lambda: self.one(anchor="A"))
        self.assert_code("INVALID_SPECIFIED_ANCHOR_LENGTH", lambda: self.one(anchor="A" * 41))

    def test_empty_normalized_anchor_fails(self):
        self.assert_code("EMPTY_SPECIFIED_ANCHOR", lambda: self.one(anchor="！！"))

    def test_forbidden_anchors_fail(self):
        for anchor in ("点击这里", "查看更多", "更多内容", "Click Here", "READ MORE", "learn more"):
            with self.subTest(anchor=anchor):
                self.assert_code("FORBIDDEN_SPECIFIED_ANCHOR", lambda value=anchor: self.one(anchor=value))

    def test_all_allowed_clusters(self):
        for index, cluster in enumerate(sorted(ALLOWED_CLUSTERS)):
            with self.subTest(cluster=cluster):
                entry = self.parse(f"entry-{index}|https://domain.com/{index}|Anchor {index}|{cluster}\n")[0]
                self.assertEqual(entry.cluster, cluster)

    def test_invalid_clusters_fail(self):
        for cluster in ("unclassified", "unknown"):
            with self.subTest(cluster=cluster):
                self.assert_code("INVALID_SPECIFIED_CLUSTER", lambda value=cluster: self.one(cluster=value))

    def test_duplicate_canonical_url_and_normalized_anchor_fails(self):
        text = "id-one|https://DOMAIN.com:443/a|SEO Guide|baidu-seo\nid-two|https://domain.com/a|  seo   guide  |baidu-seo\n"
        self.assert_code("DUPLICATE_SPECIFIED_URL_ANCHOR", lambda: self.parse(text))

    def test_same_url_different_anchor_is_allowed(self):
        text = "id-one|https://domain.com/a|Alpha|baidu-seo\nid-two|https://domain.com/a|Beta|baidu-seo\n"
        self.assertEqual(len(self.parse(text)), 2)

    def test_same_anchor_different_url_is_allowed(self):
        text = "id-one|https://domain.com/a|Alpha|baidu-seo\nid-two|https://domain.com/b|Alpha|baidu-seo\n"
        self.assertEqual(len(self.parse(text)), 2)

    def test_registry_is_sorted_and_version_is_deterministic(self):
        entries = self.parse("id-b|https://domain.com/b|Beta|baidu-seo\nid-a|https://domain.com/a|Alpha|baidu-seo\n")
        first = build_specified_link_registry(entries)
        second = build_specified_link_registry(tuple(reversed(entries)))
        self.assertEqual([entry.id for entry in first.entries], ["id-a", "id-b"])
        self.assertEqual(first.specified_link_version, second.specified_link_version)
        self.assertTrue(first.specified_link_version.startswith("slr1:"))

    def test_source_provenance_does_not_affect_version(self):
        original = self.parse("id-one|https://domain.com/a|Alpha|baidu-seo\n", "a.txt")[0]
        changed = dataclasses.replace(original, source_filename="b.txt", source_line=99)
        self.assertEqual(
            build_specified_link_registry((original,)).specified_link_version,
            build_specified_link_registry((changed,)).specified_link_version,
        )

    def test_business_fields_change_version(self):
        base = self.parse("id-one|https://domain.com/a|Alpha|baidu-seo\n")[0]
        versions = {
            build_specified_link_registry((base,)).specified_link_version,
            build_specified_link_registry((dataclasses.replace(base, url="https://domain.com/b", canonical_url="https://domain.com/b"),)).specified_link_version,
            build_specified_link_registry((dataclasses.replace(base, anchor="Beta", normalized_anchor="beta"),)).specified_link_version,
            build_specified_link_registry((dataclasses.replace(base, cluster="content-seo"),)).specified_link_version,
        }
        self.assertEqual(len(versions), 4)

    def test_preflight_2xx_pass(self):
        registry = self.one()
        for status in (200, 204, 299):
            with self.subTest(status=status):
                result = self.preflight(registry, status_code=status)
                self.assertIs(validate_preflight_result(result, registry), result)

    def test_preflight_redirects_validate_as_failures(self):
        registry = self.one()
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                result = self.preflight(
                    registry, status_code=status, redirect_location="https://domain.com/final",
                    result="FAIL", error_code="TARGET_URL_REDIRECT",
                )
                self.assertIs(validate_preflight_result(result, registry), result)

    def test_preflight_http_failures(self):
        registry = self.one()
        for status in (404, 500):
            with self.subTest(status=status):
                result = self.preflight(registry, status_code=status, result="FAIL", error_code="TARGET_URL_HTTP_ERROR")
                self.assertIs(validate_preflight_result(result, registry), result)

    def test_preflight_transport_failures(self):
        registry = self.one()
        for code in (
            "TARGET_URL_DNS_ERROR",
            "TARGET_URL_TLS_ERROR",
            "TARGET_URL_TIMEOUT",
            "TARGET_URL_CONNECTION_ERROR",
        ):
            with self.subTest(code=code):
                result = self.preflight(registry, status_code=None, result="FAIL", error_code=code)
                self.assertIs(validate_preflight_result(result, registry), result)

    def test_http_preflight_direct_2xx_and_connection_error(self):
        registry = self.one(url="http://domain.com/seo/")
        direct = self.preflight(registry, status_code=204)
        self.assertIs(validate_preflight_result(direct, registry), direct)
        connection = self.preflight(
            registry,
            status_code=None,
            result="FAIL",
            error_code="TARGET_URL_CONNECTION_ERROR",
        )
        self.assertIs(validate_preflight_result(connection, registry), connection)

    def test_http_preflight_tls_error_is_rejected(self):
        registry = self.one(url="http://domain.com/seo/")
        result = self.preflight(
            registry,
            status_code=None,
            result="FAIL",
            error_code="TARGET_URL_TLS_ERROR",
        )
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: validate_preflight_result(result, registry))

    def test_preflight_entry_identity_mismatch_fails(self):
        registry = self.one()
        result = self.preflight(registry, entry_id="other")
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: validate_preflight_result(result, registry))

    def test_preflight_url_identity_mismatch_fails(self):
        registry = self.one()
        configured = self.preflight(registry, configured_url="https://domain.com/other")
        canonical = self.preflight(registry, canonical_url="https://domain.com/other")
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: validate_preflight_result(configured, registry))
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: validate_preflight_result(canonical, registry))

    def test_preflight_inconsistent_success_fails(self):
        registry = self.one()
        result = self.preflight(registry, status_code=404)
        self.assert_code("TARGET_URL_HTTP_ERROR", lambda: validate_preflight_result(result, registry))

    def test_error_exposes_structured_context(self):
        try:
            self.parse("bad_id|https://domain.com/|Anchor|baidu-seo\n")
        except SpecifiedLinkContractError as exc:
            self.assertEqual(exc.code, "INVALID_SPECIFIED_INPUT_FORMAT")
            self.assertEqual(exc.line_number, 1)
            self.assertEqual(exc.entry_id, "bad_id")
        else:
            self.fail("expected SpecifiedLinkContractError")


if __name__ == "__main__":
    unittest.main()
