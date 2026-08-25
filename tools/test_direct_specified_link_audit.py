from __future__ import annotations

import dataclasses
import hashlib
import unittest
from pathlib import Path

from direct_specified_link_audit import (
    DirectSpecifiedLinkAuditInput,
    audit_direct_specified_link_article,
    audit_direct_specified_link_batch,
    verify_direct_internal_links_unchanged,
)
from direct_specified_link_injector import inject_direct_specified_links
from direct_specified_link_planner import DirectSourceArticle, plan_direct_specified_links_for_batch
from direct_specified_link_registry import build_direct_registry, parse_direct_link_lines


class DirectSpecifiedLinkAuditTests(unittest.TestCase):
    def registry(self, count=3, same_anchor=False):
        lines = []
        for index in range(count):
            scheme = "http" if index % 2 == 0 else "https"
            anchor = "共同锚文本" if same_anchor else f"目标锚文本 {index}"
            lines.append(f"target-{index:03d}|{scheme}://host-{index}.real-domain.tld/Article//Path{index}?q={index}#Part{index}|{anchor}")
        return build_direct_registry(parse_direct_link_lines(lines, source_filename="user-approved.txt"))

    def baseline(self, body="普通正文。", newline="\n", related=True):
        tail = "\n\n## 相关阅读\n\n- [内部链接](./inside.html)" if related else ""
        value = "---\ntitle: T\ndescription: D\n---\n\n# T\n\n{% raw %}\n\n" + body + tail + "\n\n{% endraw %}\n"
        return value.replace("\n", newline)

    def case(self, count=3, configured=None, body=None, slug="source-one", registry=None, batch="direct-batch", newline="\n"):
        registry = registry or self.registry(count)
        configured = count if configured is None else configured
        plan = plan_direct_specified_links_for_batch(
            (DirectSourceArticle(slug),), registry, batch_id=batch, configured_direct_links_per_article=configured,
            direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
        ).plans[0]
        if body is None:
            body = "自然段包含" + (plan.selected_entries[0].anchor if plan.selected_entries else "无") + "并保持原意。"
        pre = self.baseline(body, newline)
        outcome = inject_direct_specified_links(
            source_slug=slug, markdown=pre, plan=plan, registry=registry, batch_id=batch,
            direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
        )
        return registry, plan, pre, outcome

    def audit(self, registry, plan, pre, outcome, **changes):
        values = dict(source_slug=plan.source_slug, batch_id=plan.batch_id, pre_markdown=pre,
                      post_markdown=outcome.markdown, plan=plan, injection_result=outcome.result, registry=registry)
        values.update(changes)
        return audit_direct_specified_link_article(**values)

    def assert_code(self, result, code):
        self.assertEqual(result.final_status, "FAIL")
        self.assertIn(code, {item.code for item in result.errors})

    def mutate(self, outcome, old, new, *, repair_sha=True):
        post = outcome.markdown.replace(old, new, 1)
        result = outcome.result
        if repair_sha:
            result = dataclasses.replace(result, post_sha256=hashlib.sha256(post.encode()).hexdigest())
        return dataclasses.replace(outcome, markdown=post, result=result)

    def test_natural_reference_and_identity_pass(self):
        registry, plan, pre, outcome = self.case(3)
        result = self.audit(registry, plan, pre, outcome)
        self.assertEqual(result.final_status, "PASS")
        self.assertEqual((result.natural_anchor_links, result.visible_reference_links), (1, 2))
        self.assertTrue(verify_direct_internal_links_unchanged(pre, outcome.markdown, placements=outcome.result.placed_entries))

    def test_reference_only_and_natural_only(self):
        registry, plan, pre, outcome = self.case(2, body="不含自然锚文本。")
        self.assertEqual(self.audit(registry, plan, pre, outcome).visible_reference_links, 2)
        registry, plan, pre, outcome = self.case(1)
        result = self.audit(registry, plan, pre, outcome)
        self.assertEqual((result.natural_anchor_links, result.visible_reference_links), (1, 0))

    def test_quantities_and_line_endings(self):
        for count in (1, 2, 5, 10, 20, 30):
            for newline in ("\n", "\r\n"):
                with self.subTest(count=count, newline=repr(newline)):
                    registry, plan, pre, outcome = self.case(count, newline=newline)
                    result = self.audit(registry, plan, pre, outcome)
                    self.assertEqual(result.final_status, "PASS")
                    self.assertEqual(result.placed_links, count)

    def test_same_anchor_different_url(self):
        registry = self.registry(2, same_anchor=True)
        registry, plan, pre, outcome = self.case(2, registry=registry)
        self.assertEqual(self.audit(registry, plan, pre, outcome).final_status, "PASS")

    def test_planner_shortfall(self):
        registry, plan, pre, outcome = self.case(1, configured=2)
        result = self.audit(registry, plan, pre, outcome)
        self.assertEqual(result.final_status, "PASS_WITH_SHORTFALL")
        self.assertEqual(result.shortfall_reason, "INSUFFICIENT_UNIQUE_DIRECT_TARGETS")

    def test_forged_entry_url_anchor_and_offsets(self):
        registry, plan, pre, outcome = self.case(2)
        placement = outcome.result.placed_entries[0]
        cases = (
            (dataclasses.replace(placement, entry_id="forged"), "UNAPPROVED_DIRECT_URL"),
            (dataclasses.replace(placement, url="https://evil.real-domain.tld/"), "DIRECT_URL_MISMATCH"),
            (dataclasses.replace(placement, anchor="伪造锚文本"), "DIRECT_ANCHOR_MISMATCH"),
            (dataclasses.replace(placement, start=placement.start + 1), "DIRECT_PLACEMENT_MISMATCH"),
        )
        for forged, code in cases:
            with self.subTest(code=code):
                result_obj = dataclasses.replace(outcome.result, placed_entries=(forged, *outcome.result.placed_entries[1:]))
                self.assert_code(self.audit(registry, plan, pre, outcome, injection_result=result_obj), code)

    def test_sha_and_version_forgery(self):
        registry, plan, pre, outcome = self.case()
        for field, value, code in (
            ("pre_sha256", "0" * 64, "DIRECT_PROVENANCE_MISSING"),
            ("post_sha256", "0" * 64, "POST_INJECTION_SHA_MISMATCH"),
            ("direct_registry_version", "dlr1:bad", "DIRECT_REGISTRY_VERSION_MISMATCH"),
        ):
            forged = dataclasses.replace(outcome.result, **{field: value})
            self.assert_code(self.audit(registry, plan, pre, outcome, injection_result=forged), code)

    def test_delete_and_extra_unapproved_link(self):
        registry, plan, pre, outcome = self.case(2)
        placed = outcome.result.placed_entries[0]
        deleted = self.mutate(outcome, f"[{placed.anchor}]({placed.url})", placed.anchor)
        self.assert_code(self.audit(registry, plan, pre, deleted), "DIRECT_PLACEMENT_MISMATCH")
        extra = self.mutate(outcome, "{% endraw %}", "[bad](https://evil.real-domain.tld/)\n{% endraw %}")
        self.assert_code(self.audit(registry, plan, pre, extra), "DIRECT_BASELINE_RECONSTRUCTION_FAILED")

    def test_exact_url_tampering(self):
        registry, plan, pre, outcome = self.case(2)
        url = outcome.result.placed_entries[0].url
        switched = url.replace("http://", "https://") if url.startswith("http://") else url.replace("https://", "http://")
        variants = (switched, url.replace("//Path", "/Path"),
                    url.replace("?q=", "?x="), url.replace("#Part", "#part"), url.replace("Path", "path"))
        for variant in variants:
            with self.subTest(variant=variant):
                changed = self.mutate(outcome, url, variant)
                self.assert_code(self.audit(registry, plan, pre, changed), "DIRECT_PLACEMENT_MISMATCH")

    def test_reference_moved_and_existing_mutations(self):
        registry, plan, pre, outcome = self.case(1, body="无自然命中。")
        line = f"| 详见 [{plan.selected_entries[0].anchor}]({plan.selected_entries[0].url})"
        moved = self.mutate(outcome, line, "")
        moved = self.mutate(moved, "- [内部链接]", line + "\n- [内部链接]")
        self.assert_code(self.audit(registry, plan, pre, moved), "DIRECT_PLACEMENT_MISMATCH")
        for old, new, code in (
            ("title: T", "title: Changed", "DIRECT_PROTECTED_ZONE_VIOLATION"),
            ("# T", "# Changed", "DIRECT_PROTECTED_ZONE_VIOLATION"),
            ("[内部链接](./inside.html)", "[改变](./inside.html)", "INTERNAL_LINK_MUTATED"),
            ("{% endraw %}", "{% raw %}", "DIRECT_PROTECTED_ZONE_VIOLATION"),
        ):
            changed = self.mutate(outcome, old, new)
            self.assert_code(self.audit(registry, plan, pre, changed), code)

    def test_code_liquid_html_and_existing_markdown_preserved(self):
        body = "```md\n[looks](https://code.real-domain.tld/)\n```\n\n`inline` {{ value }}\n\n[旧链接](https://old.real-domain.tld/)\n\n<a href=\"https://html.real-domain.tld/\">old</a>"
        registry, plan, pre, outcome = self.case(2, body=body)
        self.assertEqual(self.audit(registry, plan, pre, outcome).final_status, "PASS")
        for old, new, code in (
            ("[旧链接]", "[新链接]", "PRE_EXISTING_LINK_MUTATED"),
            (">old</a>", ">new</a>", "PRE_EXISTING_LINK_MUTATED"),
            ("inline", "changed", "DIRECT_PROTECTED_ZONE_VIOLATION"),
            ("{{ value }}", "{{ changed }}", "DIRECT_PROTECTED_ZONE_VIOLATION"),
            ("looks", "changed", "DIRECT_PROTECTED_ZONE_VIOLATION"),
        ):
            changed = self.mutate(outcome, old, new)
            self.assert_code(self.audit(registry, plan, pre, changed), code)

    def test_protected_existing_production(self):
        registry, plan, pre, outcome = self.case()
        self.assert_code(self.audit(registry, plan, pre, outcome, protected_slug_set={plan.source_slug}),
                         "EXISTING_PRODUCTION_MUTATION_ATTEMPT")

    def test_twenty_url_ten_article_batch(self):
        registry = self.registry(20)
        sources = tuple(DirectSourceArticle(f"source-{index:02d}") for index in range(10))
        planned = plan_direct_specified_links_for_batch(
            sources, registry, batch_id="acceptance-20", configured_direct_links_per_article=2,
            direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
        )
        inputs = []
        for plan in planned.plans:
            pre = self.baseline("自然段包含" + plan.selected_entries[0].anchor + "。")
            outcome = inject_direct_specified_links(
                source_slug=plan.source_slug, markdown=pre, plan=plan, registry=registry,
                batch_id=planned.batch_id, direct_registry_version=registry.direct_registry_version,
                config_version=registry.config_version,
            )
            inputs.append(DirectSpecifiedLinkAuditInput(plan.source_slug, planned.batch_id, pre, outcome.markdown, plan, outcome.result))
        result = audit_direct_specified_link_batch(inputs, registry=registry)
        self.assertEqual((result.requested_total, result.selected_total, result.placed_total), (20, 20, 20))
        self.assertEqual((result.article_failures, result.duplicate_article_url_violations,
                          result.provenance_violations, result.final_status), (0, 0, 0, "PASS"))

    def test_thirty_single_article(self):
        registry, plan, pre, outcome = self.case(30)
        result = self.audit(registry, plan, pre, outcome)
        self.assertEqual((result.selected_links, result.placed_links, result.final_status), (30, 30, "PASS"))

    def test_three_tracked_production_formats_read_only(self):
        root = Path(__file__).resolve().parent.parent
        tracked = []
        for batch_name in ("production-batch-001.txt", "production-batch-002.txt", "production-batch-003.txt", "production-batch-004.txt", "internal-link-production-batch-010.txt"):
            for line in (root / "input" / batch_name).read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    tracked.append(line.split("|", 1)[0].strip())
        texts = {slug: (root / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig") for slug in tracked}
        chosen = []
        predicates = (lambda text: "```" in text, lambda text: "](./" in text, lambda text: text.count("##") >= 3)
        for predicate in predicates:
            slug = next(slug for slug, text in texts.items() if predicate(text) and slug not in chosen)
            chosen.append(slug)
        registry = self.registry(3)
        for slug in chosen:
            planned = plan_direct_specified_links_for_batch(
                (DirectSourceArticle(slug),), registry, batch_id="readonly-format", configured_direct_links_per_article=1,
                direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
            ).plans[0]
            pre = texts[slug]
            outcome = inject_direct_specified_links(
                source_slug=slug, markdown=pre, plan=planned, registry=registry, batch_id="readonly-format",
                direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
            )
            self.assertEqual(self.audit(registry, planned, pre, outcome).final_status, "PASS")


if __name__ == "__main__":
    unittest.main()
