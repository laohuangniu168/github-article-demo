import dataclasses
import hashlib
import re
import unittest
from pathlib import Path

from specified_link_audit import (
    SpecifiedLinkAuditInput,
    audit_specified_link_article,
    audit_specified_link_batch,
    verify_internal_links_unchanged,
)
from specified_link_injector import inject_specified_links, scan_specified_markdown
from specified_link_planner import (
    SpecifiedLinkFilteredEntry,
    SpecifiedLinkPlan,
    SpecifiedLinkSelectedEntry,
    calculate_specified_link_batch_caps,
    compute_specified_link_candidate_hash,
)
from specified_link_registry import (
    SpecifiedLinkPreflightResult,
    build_specified_link_registry,
    parse_specified_link_lines,
)


class SpecifiedLinkAuditTests(unittest.TestCase):
    def registry(self, count=4, *, same_anchor=False):
        clusters = ("technical-seo", "baidu-seo", "content-seo", "technical-seo")
        lines = []
        for index in range(count):
            anchor = "Shared Anchor" if same_anchor else f"Anchor {index}"
            lines.append(
                f"entry-{index}|https://host-{index}.real-domain.tld/page|{anchor}|{clusters[index % len(clusters)]}\n"
            )
        return build_specified_link_registry(parse_specified_link_lines(lines))

    def preflights(self, registry):
        return tuple(
            SpecifiedLinkPreflightResult(
                entry.id, entry.url, entry.canonical_url, 200, None, "2026-08-25T00:00:00Z", "PASS", None
            )
            for entry in registry.entries
        )

    def selected(self, entry, registry, slug="new-article", batch_id="batch-001"):
        return SpecifiedLinkSelectedEntry(
            entry.id,
            entry.canonical_url,
            entry.anchor,
            entry.normalized_anchor,
            entry.cluster,
            0,
            1,
            0,
            1,
            0,
            1,
            compute_specified_link_candidate_hash(
                batch_id=batch_id,
                source_slug=slug,
                specified_link_version=registry.specified_link_version,
                config_version=registry.config_version,
                entry_id=entry.id,
            ),
        )

    def plan(self, registry, *, slug="new-article", cluster="technical-seo", entry_ids=("entry-0",), requested=None, reason=None, batch_id="batch-001"):
        entries = {entry.id: entry for entry in registry.entries}
        selected = tuple(self.selected(entries[entry_id], registry, slug, batch_id) for entry_id in entry_ids)
        requested = len(selected) if requested is None else requested
        return SpecifiedLinkPlan(
            batch_id,
            slug,
            cluster,
            registry.specified_link_version,
            registry.config_version,
            requested,
            requested,
            len(selected),
            selected,
            (SpecifiedLinkFilteredEntry("entry-x", "SPECIFIED_CLUSTER_MISMATCH", "filtered"),),
            reason,
            "PASS" if reason is None else "PASS_WITH_SHORTFALL",
        )

    def markdown(self, body="正文自然包含 Anchor 0 作为术语。", newline="\n"):
        text = "---\ntitle: T\ndescription: D\n---\n\n# T\n\n{% raw %}\n\n" + body + "\n\n{% endraw %}\n"
        return text.replace("\n", newline)

    def case(self, *, registry=None, plan=None, baseline=None, slug="new-article", cluster="technical-seo", batch_id="batch-001"):
        registry = registry or self.registry()
        plan = plan or self.plan(registry, slug=slug, cluster=cluster, batch_id=batch_id)
        baseline = baseline or self.markdown()
        outcome = inject_specified_links(
            source_slug=slug,
            source_cluster=cluster,
            baseline_markdown=baseline,
            plan=plan,
            registry=registry,
            batch_id=batch_id,
            specified_link_version=registry.specified_link_version,
            config_version=registry.config_version,
        )
        return registry, plan, baseline, outcome

    def audit(self, registry, plan, baseline, outcome, **changes):
        values = dict(
            source_slug=plan.source_slug,
            source_cluster=plan.source_cluster,
            batch_id=plan.batch_id,
            pre_markdown=baseline,
            post_markdown=outcome.markdown,
            plan=plan,
            injection_result=outcome.result,
            registry=registry,
            preflight_results=self.preflights(registry),
        )
        values.update(changes)
        return audit_specified_link_article(**values)

    def mutate_post(self, outcome, post):
        result = dataclasses.replace(outcome.result, post_sha256=hashlib.sha256(post.encode()).hexdigest())
        return dataclasses.replace(outcome, markdown=post, result=result)

    def assert_fail_code(self, result, code):
        self.assertEqual(result.final_status, "FAIL")
        self.assertIn(code, {event.code for event in result.errors})

    def test_normal_pass(self):
        registry, plan, baseline, outcome = self.case()
        result = self.audit(registry, plan, baseline, outcome)
        self.assertEqual(result.final_status, "PASS")
        self.assertEqual(result.specified_links, 1)

    def test_no_safe_point_shortfall(self):
        registry = self.registry()
        plan = self.plan(registry)
        baseline = self.markdown("正文没有目标短语。")
        registry, plan, baseline, outcome = self.case(registry=registry, plan=plan, baseline=baseline)
        self.assertEqual(self.audit(registry, plan, baseline, outcome).final_status, "PASS_WITH_SHORTFALL")

    def test_planner_candidate_shortfall(self):
        registry = self.registry()
        plan = self.plan(registry, requested=2, reason="INSUFFICIENT_SPECIFIED_CLUSTER_CANDIDATES")
        registry, plan, baseline, outcome = self.case(registry=registry, plan=plan)
        self.assertEqual(self.audit(registry, plan, baseline, outcome).final_status, "PASS_WITH_SHORTFALL")

    def test_planner_cap_shortfall(self):
        registry = self.registry()
        plan = self.plan(registry, requested=2, reason="SPECIFIED_BATCH_CAP_EXHAUSTED")
        registry, plan, baseline, outcome = self.case(registry=registry, plan=plan)
        self.assertEqual(self.audit(registry, plan, baseline, outcome).final_status, "PASS_WITH_SHORTFALL")

    def test_forged_result(self):
        registry, plan, baseline, outcome = self.case()
        forged = dataclasses.replace(outcome.result, requested_entries=())
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "SPECIFIED_PROVENANCE_MISSING")

    def test_wrong_source_slug(self):
        registry, plan, baseline, outcome = self.case()
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, source_slug="wrong"), "SPECIFIED_PROVENANCE_MISSING")

    def test_wrong_batch_id(self):
        registry, plan, baseline, outcome = self.case()
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, batch_id="wrong"), "SPECIFIED_PROVENANCE_MISSING")

    def test_wrong_specified_version(self):
        registry, plan, baseline, outcome = self.case()
        forged = dataclasses.replace(outcome.result, specified_link_version="slr1:wrong")
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "SPECIFIED_PROVENANCE_MISSING")

    def test_wrong_config_version(self):
        registry, plan, baseline, outcome = self.case()
        forged = dataclasses.replace(outcome.result, config_version="wrong")
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "SPECIFIED_PROVENANCE_MISSING")

    def test_wrong_pre_sha(self):
        registry, plan, baseline, outcome = self.case()
        forged = dataclasses.replace(outcome.result, pre_sha256="0" * 64)
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "SPECIFIED_PROVENANCE_MISSING")

    def test_wrong_post_sha(self):
        registry, plan, baseline, outcome = self.case()
        forged = dataclasses.replace(outcome.result, post_sha256="0" * 64)
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "SPECIFIED_PROVENANCE_MISSING")

    def test_missing_registry_entry(self):
        registry, plan, baseline, outcome = self.case()
        placement = dataclasses.replace(outcome.result.placed_entries[0], entry_id="absent")
        forged = dataclasses.replace(outcome.result, placed_entries=(placement,))
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "UNAPPROVED_SPECIFIED_URL")

    def test_url_tamper(self):
        registry, plan, baseline, outcome = self.case()
        placement = dataclasses.replace(outcome.result.placed_entries[0], url="https://evil.real-domain.tld/")
        forged = dataclasses.replace(outcome.result, placed_entries=(placement,))
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "UNAPPROVED_SPECIFIED_URL")

    def test_anchor_tamper(self):
        registry, plan, baseline, outcome = self.case()
        placement = dataclasses.replace(outcome.result.placed_entries[0], anchor="Wrong Anchor")
        forged = dataclasses.replace(outcome.result, placed_entries=(placement,))
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "UNAPPROVED_SPECIFIED_URL")

    def test_normalized_anchor_tamper(self):
        registry, plan, baseline, outcome = self.case()
        requested = dataclasses.replace(outcome.result.requested_entries[0], normalized_anchor="wrong")
        forged = dataclasses.replace(outcome.result, requested_entries=(requested,))
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "SPECIFIED_PROVENANCE_MISSING")

    def test_cluster_tamper(self):
        registry, plan, baseline, outcome = self.case()
        requested = dataclasses.replace(outcome.result.requested_entries[0], cluster="baidu-seo")
        forged = dataclasses.replace(outcome.result, requested_entries=(requested,))
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "SPECIFIED_PROVENANCE_MISSING")

    def test_placement_offset_wrong(self):
        registry, plan, baseline, outcome = self.case()
        placement = dataclasses.replace(outcome.result.placed_entries[0], start=outcome.result.placed_entries[0].start + 1)
        forged = dataclasses.replace(outcome.result, placed_entries=(placement,))
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, injection_result=forged), "MALFORMED_SPECIFIED_LINK")

    def test_duplicate_url_and_anchor(self):
        registry, plan, baseline, outcome = self.case()
        placement = outcome.result.placed_entries[0]
        forged = dataclasses.replace(outcome.result, placed_entries=(placement, placement))
        result = self.audit(registry, plan, baseline, outcome, injection_result=forged)
        self.assert_fail_code(result, "DUPLICATE_SPECIFIED_URL")
        self.assertIn("DUPLICATE_SPECIFIED_ANCHOR", {event.code for event in result.errors})

    def test_article_cap_exceeded(self):
        registry, plan, baseline, outcome = self.case()
        bad_plan = dataclasses.replace(plan, configured_max=4, requested_links=4)
        self.assert_fail_code(self.audit(registry, bad_plan, baseline, outcome), "SPECIFIED_ARTICLE_CAP_EXCEEDED")

    def test_missing_preflight(self):
        registry, plan, baseline, outcome = self.case()
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, preflight_results=()), "UNAPPROVED_SPECIFIED_URL")

    def test_failed_preflight(self):
        registry, plan, baseline, outcome = self.case()
        entry = registry.entries[0]
        failed = SpecifiedLinkPreflightResult(entry.id, entry.url, entry.canonical_url, 500, None, "x", "FAIL", "TARGET_URL_HTTP_ERROR")
        self.assert_fail_code(self.audit(registry, plan, baseline, outcome, preflight_results=(failed,)), "UNAPPROVED_SPECIFIED_URL")

    def test_protected_and_existing_mutations(self):
        mutations = {
            "front": ("title: T", "title: Changed", "SPECIFIED_PROTECTED_ZONE_VIOLATION"),
            "heading": ("# T", "# Changed", "SPECIFIED_PROTECTED_ZONE_VIOLATION"),
            "fence": ("```text\ncode\n```", "```text\nchanged\n```", "SPECIFIED_PROTECTED_ZONE_VIOLATION"),
            "inline": ("`inline`", "`changed`", "SPECIFIED_PROTECTED_ZONE_VIOLATION"),
            "liquid": ("{{ value }}", "{{ changed }}", "SPECIFIED_PROTECTED_ZONE_VIOLATION"),
            "html": ('<span class="x">x</span>', '<span class="y">x</span>', "SPECIFIED_PROTECTED_ZONE_VIOLATION"),
            "comment": ("<!-- x -->", "<!-- y -->", "SPECIFIED_PROTECTED_ZONE_VIOLATION"),
            "markdown": ("[old](https://old.real-domain.tld/)", "[new](https://old.real-domain.tld/)", "PRE_EXISTING_LINK_MUTATED"),
            "html_link": ('<a href="https://old.real-domain.tld/">old</a>', '<a href="https://old.real-domain.tld/">new</a>', "PRE_EXISTING_LINK_MUTATED"),
            "internal": ("[Inside](./inside.html)", "[Changed](./inside.html)", "INTERNAL_LINK_MUTATED"),
            "related": ("## 相关阅读", "## Changed", "SPECIFIED_PROTECTED_ZONE_VIOLATION"),
        }
        for name, (old, new, code) in mutations.items():
            with self.subTest(name=name):
                body = f"Anchor 0 自然出现。\n\n{old}"
                registry, plan, baseline, outcome = self.case(baseline=self.markdown(body))
                post = outcome.markdown.replace(old, new)
                changed = self.mutate_post(outcome, post)
                self.assert_fail_code(self.audit(registry, plan, baseline, changed), code)

    def test_raw_boundary_mutation(self):
        registry, plan, baseline, outcome = self.case()
        post = outcome.markdown.replace("{% raw %}", "{% raw  %}", 1)
        changed = self.mutate_post(outcome, post)
        self.assert_fail_code(self.audit(registry, plan, baseline, changed), "SPECIFIED_PROTECTED_ZONE_VIOLATION")

    def test_internal_url_and_count_mutation(self):
        for old, new in (("./inside.html", "./other.html"), ("[Inside](./inside.html)", "")):
            with self.subTest(new=new):
                registry, plan, baseline, outcome = self.case(baseline=self.markdown("Anchor 0。\n\n[Inside](./inside.html)"))
                changed = self.mutate_post(outcome, outcome.markdown.replace(old, new))
                self.assert_fail_code(self.audit(registry, plan, baseline, changed), "INTERNAL_LINK_MUTATED")

    def test_baseline_external_links_not_misidentified(self):
        baseline = self.markdown("Anchor 0。\n\n[old](https://host-0.real-domain.tld/other)\n\nhttps://host-0.real-domain.tld/bare")
        registry, plan, baseline, outcome = self.case(baseline=baseline)
        result = self.audit(registry, plan, baseline, outcome)
        self.assertEqual((result.final_status, result.specified_links), ("PASS", 1))

    def test_code_lookalikes_not_misidentified(self):
        body = "Anchor 0。\n\n```md\n[fake](https://fake.real-domain.tld/)\n```\n\n`[fake](https://fake.real-domain.tld/)`"
        registry, plan, baseline, outcome = self.case(baseline=self.markdown(body))
        self.assertEqual(self.audit(registry, plan, baseline, outcome).final_status, "PASS")

    def test_crlf_preserved(self):
        registry, plan, baseline, outcome = self.case(baseline=self.markdown(newline="\r\n"))
        self.assertEqual(self.audit(registry, plan, baseline, outcome).final_status, "PASS")
        self.assertEqual(outcome.markdown.count("\n"), outcome.markdown.count("\r\n"))

    def test_multiple_links_requested_three(self):
        registry = self.registry()
        plan = self.plan(registry, entry_ids=("entry-0", "entry-3", "entry-1"), requested=3)
        plan = dataclasses.replace(plan, source_cluster="technical-seo", selected_entries=plan.selected_entries[:2], selected_links=2, shortfall_reason="INSUFFICIENT_SPECIFIED_CLUSTER_CANDIDATES", status="PASS_WITH_SHORTFALL")
        baseline = self.markdown("Anchor 0 出现。\n\nAnchor 3 出现。")
        registry, plan, baseline, outcome = self.case(registry=registry, plan=plan, baseline=baseline)
        self.assertEqual(self.audit(registry, plan, baseline, outcome).final_status, "PASS_WITH_SHORTFALL")

    def test_specified_not_counted_as_internal(self):
        registry, plan, baseline, outcome = self.case(baseline=self.markdown("Anchor 0。\n\n[Inside](./inside.html)"))
        self.assertTrue(verify_internal_links_unchanged(baseline, outcome.markdown, placements=outcome.result.placed_entries))

    def test_batch_caps_formulas(self):
        expected = {10: (2, 1, 2), 20: (4, 2, 3), 50: (10, 5, 8), 100: (10, 5, 10)}
        for size, values in expected.items():
            caps = calculate_specified_link_batch_caps(size)
            self.assertEqual((caps.per_url_batch_cap, caps.per_url_anchor_pair_batch_cap, caps.per_anchor_batch_cap), values)

    def test_batch_usage_counts_distinct_sources(self):
        registry, plan, baseline, outcome = self.case()
        item = SpecifiedLinkAuditInput("new-article", "technical-seo", "batch-001", baseline, outcome.markdown, plan, outcome.result)
        result = audit_specified_link_batch((item,), registry=registry, preflight_results=self.preflights(registry))
        self.assertEqual(result.url_usage[registry.entries[0].canonical_url], 1)

    def test_batch_url_cap_violation(self):
        registry = self.registry()
        items = []
        for index in range(6):
            slug = f"source-{index}"
            plan = self.plan(registry, slug=slug, batch_id="batch-many")
            registry, plan, baseline, outcome = self.case(registry=registry, plan=plan, slug=slug, batch_id="batch-many")
            items.append(SpecifiedLinkAuditInput(slug, "technical-seo", "batch-many", baseline, outcome.markdown, plan, outcome.result))
        result = audit_specified_link_batch(items, registry=registry, preflight_results=self.preflights(registry))
        self.assertEqual(result.final_status, "FAIL")
        self.assertIn("SPECIFIED_URL_BATCH_CAP_EXCEEDED", {event.code for event in result.violations})

    def test_batch_pair_and_anchor_caps(self):
        registry = self.registry()
        items = []
        for index in range(2):
            slug = f"source-{index}"
            plan = self.plan(registry, slug=slug, batch_id="batch-two")
            registry, plan, baseline, outcome = self.case(registry=registry, plan=plan, slug=slug, batch_id="batch-two")
            items.append(SpecifiedLinkAuditInput(slug, "technical-seo", "batch-two", baseline, outcome.markdown, plan, outcome.result))
        result = audit_specified_link_batch(items, registry=registry, preflight_results=self.preflights(registry))
        codes = {event.code for event in result.violations}
        self.assertIn("SPECIFIED_PAIR_BATCH_CAP_EXCEEDED", codes)
        self.assertIn("SPECIFIED_ANCHOR_BATCH_CAP_EXCEEDED", codes)

    def test_real_format_fences_headings_links(self):
        body = "## Section\n\nAnchor 0 正文。\n\n```md\n[look](./fake.html)\n```\n\n### More\n\n`[inline](./fake.html)` 与 [Existing](./inside.html) 及 [Web](https://web.real-domain.tld/)"
        registry, plan, baseline, outcome = self.case(baseline=self.markdown(body))
        result = self.audit(registry, plan, baseline, outcome)
        self.assertEqual(result.final_status, "PASS")
        self.assertEqual((result.protected_zone_violations, result.internal_links_mutated, result.pre_existing_links_mutated), (0, 0, 0))

    def test_three_real_repository_formats_in_memory(self):
        cases = (
            ("baidu-crawl-budget-guide", "baidu-crawl"),
            ("technical-seo-https-guide", "technical-seo"),
            ("seo-internal-link-audit", "internal-linking"),
        )
        for slug, cluster in cases:
            with self.subTest(slug=slug):
                baseline = Path("articles", f"{slug}.md").read_text(encoding="utf-8")
                scan = scan_specified_markdown(baseline)
                anchor = next(
                    match.group(0)
                    for paragraph in scan.paragraphs if paragraph.eligible
                    for match in [re.search(r"[A-Za-z0-9_\u0080-\uffff]{4,12}", paragraph.text)]
                    if match is not None
                )
                registry = build_specified_link_registry(
                    parse_specified_link_lines(
                        [f"real-entry|https://approved.real-domain.tld/{slug}|{anchor}|{cluster}\n"]
                    )
                )
                entry = registry.entries[0]
                selected = self.selected(entry, registry, slug, "real-format-batch")
                plan = SpecifiedLinkPlan(
                    "real-format-batch", slug, cluster, registry.specified_link_version,
                    registry.config_version, 1, 1, 1, (selected,), (), None, "PASS",
                )
                registry, plan, baseline, outcome = self.case(
                    registry=registry, plan=plan, baseline=baseline, slug=slug,
                    cluster=cluster, batch_id="real-format-batch",
                )
                result = self.audit(registry, plan, baseline, outcome)
                self.assertEqual(result.final_status, "PASS")
                self.assertEqual(
                    (result.protected_zone_violations, result.internal_links_mutated, result.pre_existing_links_mutated),
                    (0, 0, 0),
                )


if __name__ == "__main__":
    unittest.main()
