from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import fields, replace
from pathlib import Path

from digest_audit import DigestAuditIssue, DigestAuditResult, audit_digest_article
from digest_generator import parse_digest_response, render_digest_markdown
from digest_planner import plan_digest_articles
from digest_registry import DIGEST_CONFIG_VERSION, build_digest_registry, parse_digest_lines


SUMMARY = "围绕该标题形成简短资讯概览，提示相关背景、发展方向以及后续值得持续观察的重点。"


def make_case(count: int = 20):
    lines = []
    for index in range(count):
        scheme = "http" if index % 2 == 0 else "https"
        suffix = "?Query=One#Part" if index == 0 else ("/" if index == 1 else "")
        lines.append(f"{scheme}://Example.COM/Article//Item%2F{index:03d}{suffix}|新闻标题 {index:03d}")
    registry = build_digest_registry(parse_digest_lines("\n".join(lines)))
    plan = plan_digest_articles(
        registry,
        batch_id="digest-audit-fixture",
        digest_count=1,
        digest_registry_version=registry.digest_registry_version,
        config_version=DIGEST_CONFIG_VERSION,
    ).plans[0]
    midpoint = max(1, count // 2)
    payload = {
        "digest_title": "Hot News Digest 热点新闻汇编",
        "sections": [
            {
                "name": "国内要闻",
                "entries": [{"entry_id": entry_id, "summary": SUMMARY} for entry_id in plan.entry_ids[:midpoint]],
            },
            {
                "name": "产业科技",
                "entries": [{"entry_id": entry_id, "summary": SUMMARY} for entry_id in plan.entry_ids[midpoint:]],
            },
        ],
    }
    generated = parse_digest_response(
        plan=plan,
        registry=registry,
        output=json.dumps(payload, ensure_ascii=False),
        generation_model="fake",
        generation_attempts=1,
    )
    rendered = render_digest_markdown(
        plan=plan,
        registry=registry,
        generated_content=generated,
        published_date="2026-08-26",
    )
    return registry, plan, generated, rendered


def with_markdown(rendered, markdown: str, *, correct_sha: bool = True):
    sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest() if correct_sha else rendered.sha256
    return replace(rendered, markdown=markdown, sha256=sha)


def audit(case):
    registry, plan, generated, rendered = case
    return audit_digest_article(
        registry=registry,
        plan=plan,
        generated_content=generated,
        render_result=rendered,
        published_date="2026-08-26",
    )


class DigestAuditTests(unittest.TestCase):
    def assert_fail_code(self, case, code):
        result = audit(case)
        self.assertEqual("FAIL", result.status)
        self.assertIn(code, {error.code for error in result.errors})
        return result

    def mutate(self, transform, count=20, *, correct_sha=True):
        registry, plan, generated, rendered = make_case(count)
        markdown = transform(rendered.markdown, registry, plan, generated)
        return registry, plan, generated, with_markdown(rendered, markdown, correct_sha=correct_sha)

    def test_valid_20_50_100_pass(self):
        for count in (20, 50, 100):
            with self.subTest(count=count):
                result = audit(make_case(count))
                self.assertEqual("PASS", result.status)
                self.assertEqual((count,) * 6, (
                    result.input_entry_count,
                    result.registry_entry_count,
                    result.plan_entry_count,
                    result.ai_entry_count,
                    result.rendered_entry_count,
                    result.rendered_href_count,
                ))
                self.assertTrue(result.deterministic_reconstruction)

    def test_valid_result_counts_and_boundaries(self):
        result = audit(make_case())
        self.assertEqual((1, 2, 20, 1, 1, True), (result.h1_count, result.h2_count, result.h3_count, result.raw_count, result.endraw_count, result.raw_endraw_valid))
        self.assertEqual((), result.errors)
        self.assertEqual((), result.warnings)

    def test_structured_schema(self):
        result_names = {field.name for field in fields(DigestAuditResult)}
        issue_names = {field.name for field in fields(DigestAuditIssue)}
        self.assertTrue({"errors", "warnings", "missing_urls", "extra_urls", "markdown_sha256"} <= result_names)
        self.assertEqual({"code", "message", "entry_id", "field", "expected", "actual"}, issue_names)

    def test_registry_version_mismatch(self):
        registry, plan, generated, rendered = make_case()
        self.assert_fail_code((registry, replace(plan, digest_registry_version="dgr1:" + "0" * 64), generated, rendered), "DIGEST_AUDIT_REGISTRY_VERSION_MISMATCH")

    def test_digest_id_mismatch(self):
        registry, plan, generated, rendered = make_case()
        self.assert_fail_code((registry, plan, replace(generated, digest_id="wrong"), rendered), "DIGEST_AUDIT_DIGEST_ID_MISMATCH")

    def test_filename_mismatch(self):
        registry, plan, generated, rendered = make_case()
        self.assert_fail_code((registry, plan, generated, replace(rendered, filename="wrong.md")), "DIGEST_AUDIT_FILENAME_MISMATCH")

    def test_render_sha_mismatch(self):
        registry, plan, generated, rendered = make_case()
        self.assert_fail_code((registry, plan, generated, replace(rendered, sha256="0" * 64)), "DIGEST_AUDIT_RENDER_SHA_MISMATCH")

    def test_missing_generated_entry(self):
        registry, plan, generated, rendered = make_case()
        section = replace(generated.sections[0], entries=generated.sections[0].entries[1:])
        self.assert_fail_code((registry, plan, replace(generated, sections=(section,) + generated.sections[1:]), rendered), "DIGEST_AUDIT_ENTRY_MISSING")

    def test_duplicate_generated_entry(self):
        registry, plan, generated, rendered = make_case()
        section = replace(generated.sections[0], entries=generated.sections[0].entries + (generated.sections[0].entries[0],))
        self.assert_fail_code((registry, plan, replace(generated, sections=(section,) + generated.sections[1:]), rendered), "DIGEST_AUDIT_ENTRY_DUPLICATED")

    def test_unknown_generated_entry(self):
        registry, plan, generated, rendered = make_case()
        entry = replace(generated.sections[0].entries[0], entry_id="de-unknown")
        section = replace(generated.sections[0], entries=(entry,) + generated.sections[0].entries[1:])
        self.assert_fail_code((registry, plan, replace(generated, sections=(section,) + generated.sections[1:]), rendered), "DIGEST_AUDIT_UNKNOWN_ENTRY")

    def test_missing_href(self):
        case = self.mutate(lambda md, r, p, g: md.replace(next(line for line in md.splitlines() if line.startswith("| 详见")) + "\n", "", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_duplicate_href(self):
        case = self.mutate(lambda md, r, p, g: md.replace("{% endraw %}", next(line for line in md.splitlines() if line.startswith("| 详见")) + "\n\n{% endraw %}"))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_extra_href(self):
        case = self.mutate(lambda md, r, p, g: md.replace("{% endraw %}", "| 详见 [Extra](https://github.com/extra)\n\n{% endraw %}"))
        self.assert_fail_code(case, "DIGEST_AUDIT_EXTRA_HREF")

    def test_wrong_href(self):
        case = self.mutate(lambda md, r, p, g: md.replace(r.entries[0].url_exact, "http://wrong.example/item", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_http_to_https_mutation(self):
        case = self.mutate(lambda md, r, p, g: md.replace("http://", "https://", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_https_to_http_mutation(self):
        case = self.mutate(lambda md, r, p, g: md.replace("https://", "http://", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_double_slash_mutation(self):
        case = self.mutate(lambda md, r, p, g: md.replace("/Article//", "/Article/", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_query_mutation(self):
        case = self.mutate(lambda md, r, p, g: md.replace("?Query=One", "?Query=Two", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_fragment_mutation(self):
        case = self.mutate(lambda md, r, p, g: md.replace("#Part", "#Changed", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_path_case_mutation(self):
        case = self.mutate(lambda md, r, p, g: md.replace("/Article/", "/article/", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_trailing_slash_mutation(self):
        case = self.mutate(lambda md, r, p, g: md.replace("Item%2F001/)", "Item%2F001)", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_URL_MISMATCH")

    def test_h3_title_mismatch(self):
        case = self.mutate(lambda md, r, p, g: md.replace("### " + r.entries[0].title, "### 改写标题", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_TITLE_MISMATCH")

    def test_link_anchor_mismatch(self):
        case = self.mutate(lambda md, r, p, g: md.replace("[" + r.entries[0].title + "]", "[改写标题]", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_TITLE_MISMATCH")

    def test_h3_missing_and_duplicate(self):
        for mode in ("missing", "duplicate"):
            with self.subTest(mode=mode):
                def transform(md, r, p, g):
                    line = next(line for line in md.splitlines() if line.startswith("### "))
                    return md.replace(line + "\n", "", 1) if mode == "missing" else md.replace(line, line + "\n\n" + line, 1)
                self.assert_fail_code(self.mutate(transform), "DIGEST_AUDIT_TITLE_MISMATCH")

    def test_summary_mismatch(self):
        case = self.mutate(lambda md, r, p, g: md.replace(SUMMARY, SUMMARY + "发生改写。", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_SUMMARY_MISMATCH")

    def test_section_moved(self):
        def transform(md, r, p, g):
            first_h3 = next(line for line in md.splitlines() if line.startswith("### "))
            block = first_h3 + "\n\n" + SUMMARY + "\n\n" + next(line for line in md.splitlines() if line.startswith("| 详见")) + "\n\n"
            return md.replace(block, "", 1).replace("{% endraw %}", block + "{% endraw %}")
        self.assert_fail_code(self.mutate(transform), "DIGEST_AUDIT_SECTION_MEMBERSHIP_MISMATCH")

    def test_section_name_mismatch(self):
        case = self.mutate(lambda md, r, p, g: md.replace("## 国内要闻", "## 改名栏目", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_SECTION_MISMATCH")

    def test_front_matter_missing_duplicate_malformed(self):
        transforms = (
            lambda md, r, p, g: md.replace("---\n", "", 1),
            lambda md, r, p, g: "---\ntitle: \"Extra\"\n---\n" + md,
            lambda md, r, p, g: md.replace('title: "Hot News Digest 热点新闻汇编"', "title"),
        )
        for transform in transforms:
            with self.subTest(transform=transform):
                self.assert_fail_code(self.mutate(transform), "DIGEST_AUDIT_FRONT_MATTER_INVALID")

    def test_h1_missing_duplicate_wrong(self):
        transforms = (
            lambda md, r, p, g: md.replace("# Hot News Digest 热点新闻汇编\n", "", 1),
            lambda md, r, p, g: md.replace("# Hot News Digest 热点新闻汇编", "# Hot News Digest 热点新闻汇编\n\n# Extra", 1),
            lambda md, r, p, g: md.replace("# Hot News Digest 热点新闻汇编", "# Wrong", 1),
        )
        for transform in transforms:
            with self.subTest(transform=transform):
                self.assert_fail_code(self.mutate(transform), "DIGEST_AUDIT_H1_INVALID")

    def test_raw_boundary_mutations(self):
        transforms = (
            lambda md, r, p, g: md.replace("{% raw %}\n", "", 1),
            lambda md, r, p, g: md.replace("{% endraw %}\n", "", 1),
            lambda md, r, p, g: md.replace("{% raw %}", "{% raw %}\n{% raw %}", 1),
            lambda md, r, p, g: md.replace("{% raw %}", "TEMP", 1).replace("{% endraw %}", "{% raw %}", 1).replace("TEMP", "{% endraw %}", 1),
        )
        for transform in transforms:
            with self.subTest(transform=transform):
                self.assert_fail_code(self.mutate(transform), "DIGEST_AUDIT_RAW_BOUNDARY_INVALID")

    def test_published_date_mismatch(self):
        case = self.mutate(lambda md, r, p, g: md.replace("发布日期：2026-08-26", "发布日期：2026-08-27", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_PUBLISHED_DATE_MISMATCH")

    def test_html_and_active_markup_injection(self):
        variants = ("<a href=x>bad</a>", "<script>x</script>", "<iframe>x</iframe>", "<style>x</style>", "javascript:bad", "data:text/plain,bad")
        for variant in variants:
            with self.subTest(variant=variant):
                case = self.mutate(lambda md, r, p, g, v=variant: md.replace("{% endraw %}", v + "\n{% endraw %}"))
                result = audit(case)
                self.assertEqual("FAIL", result.status)
                self.assertTrue({"DIGEST_AUDIT_HTML_MARKUP_FORBIDDEN", "DIGEST_AUDIT_AI_LEAKAGE"} & {e.code for e in result.errors})

    def test_markdown_link_inside_html_block(self):
        case = self.mutate(lambda md, r, p, g: md.replace("| 详见", "<p>\n| 详见", 1).replace(")\n\n###", ")\n</p>\n\n###", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_HTML_MARKUP_FORBIDDEN")

    def test_deterministic_reconstruction_mismatch(self):
        case = self.mutate(lambda md, r, p, g: md.replace("发布日期：2026-08-26", "发布日期：2026-08-27", 1))
        self.assert_fail_code(case, "DIGEST_AUDIT_DETERMINISTIC_RECONSTRUCTION_MISMATCH")

    def test_reference_clickable_source_format(self):
        registry, plan, generated, rendered = make_case()
        self.assertRegex(rendered.markdown, r"(?m)^\| 详见 \[[^\]]+\]\(http[^\s]+\)$")
        self.assertNotIn("<p>", rendered.markdown)
        self.assertEqual("PASS", audit((registry, plan, generated, rendered)).status)

    def test_no_network_random_openai_or_file_write(self):
        source = Path(__file__).with_name("digest_audit.py").read_text(encoding="utf-8").casefold()
        forbidden = (
            "requests", "urllib", "socket", "httpx", "aiohttp", "openai", "random", "uuid",
            "time.time", "datetime.now", "date.today", "write_text", "open(",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
