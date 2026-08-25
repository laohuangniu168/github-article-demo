import dataclasses
import hashlib
import unittest

from specified_link_injector import (
    SpecifiedLinkInjectionOutcome,
    inject_specified_links,
    scan_specified_markdown,
)
from specified_link_planner import (
    SpecifiedLinkFilteredEntry,
    SpecifiedLinkPlan,
    SpecifiedLinkSelectedEntry,
    compute_specified_link_candidate_hash,
)
from specified_link_registry import (
    SPECIFIED_LINK_CONFIG_VERSION,
    SpecifiedLinkContractError,
    build_specified_link_registry,
    parse_specified_link_lines,
)


class SpecifiedLinkInjectorTests(unittest.TestCase):
    def registry(self, entries):
        lines = [
            f"{entry_id}|https://{host}.real-domain.tld/{path}|{anchor}|{cluster}\n"
            for entry_id, host, path, anchor, cluster in entries
        ]
        return build_specified_link_registry(parse_specified_link_lines(lines))

    def basic_registry(self):
        return self.registry(
            [
                ("entry-alpha", "alpha", "page", "Alpha Anchor", "technical-seo"),
                ("entry-beta", "beta", "page", "Beta Anchor", "technical-seo"),
                ("entry-gamma", "gamma", "page", "Gamma Anchor", "technical-seo"),
            ]
        )

    def selected(self, entry, registry):
        return SpecifiedLinkSelectedEntry(
            entry_id=entry.id,
            canonical_url=entry.canonical_url,
            anchor=entry.anchor,
            normalized_anchor=entry.normalized_anchor,
            cluster=entry.cluster,
            url_usage_before=0,
            url_usage_after=1,
            pair_usage_before=0,
            pair_usage_after=1,
            anchor_usage_before=0,
            anchor_usage_after=1,
            deterministic_hash=compute_specified_link_candidate_hash(
                batch_id="batch-001",
                source_slug="new-article",
                specified_link_version=registry.specified_link_version,
                config_version=registry.config_version,
                entry_id=entry.id,
            ),
        )

    def plan(self, registry=None, entry_ids=("entry-alpha",), requested=None, status="PASS", reason=None):
        registry = registry or self.basic_registry()
        by_id = {entry.id: entry for entry in registry.entries}
        selected = tuple(self.selected(by_id[entry_id], registry) for entry_id in entry_ids)
        requested = len(selected) if requested is None else requested
        return SpecifiedLinkPlan(
            batch_id="batch-001",
            source_slug="new-article",
            source_cluster="technical-seo",
            specified_link_version=registry.specified_link_version,
            config_version=registry.config_version,
            configured_max=requested,
            requested_links=requested,
            selected_links=len(selected),
            selected_entries=selected,
            filtered_entries=(SpecifiedLinkFilteredEntry("filtered", "SPECIFIED_CLUSTER_MISMATCH", "filtered"),),
            shortfall_reason=reason,
            status=status,
        )

    def markdown(self, body, newline="\n"):
        text = "---\ntitle: \"Synthetic\"\n---\n{% raw %}\n# Synthetic\n\n" + body + "\n{% endraw %}\n"
        return text.replace("\n", newline)

    def inject(self, markdown, registry=None, plan=None, **changes):
        registry = registry or self.basic_registry()
        plan = plan or self.plan(registry)
        values = {
            "source_slug": "new-article",
            "source_cluster": "technical-seo",
            "baseline_markdown": markdown,
            "plan": plan,
            "registry": registry,
            "batch_id": "batch-001",
            "specified_link_version": registry.specified_link_version,
            "config_version": registry.config_version,
            "protected_slug_set": (),
        }
        values.update(changes)
        return inject_specified_links(**values)

    def assert_code(self, code, callback):
        with self.assertRaises(SpecifiedLinkContractError) as context:
            callback()
        self.assertEqual(context.exception.code, code)

    def test_plain_paragraph_anchor_success(self):
        outcome = self.inject(self.markdown("正文包含 Alpha Anchor 自然短语。"))
        self.assertIn("[Alpha Anchor](https://alpha.real-domain.tld/page)", outcome.markdown)
        self.assertEqual(outcome.result.status, "PASS")

    def test_same_anchor_multiple_occurrences_uses_first(self):
        baseline = self.markdown("Alpha Anchor 第一次出现。\n\nAlpha Anchor 第二次出现。")
        outcome = self.inject(baseline)
        self.assertLess(outcome.result.placed_entries[0].start, outcome.markdown.rfind("Alpha Anchor"))

    def test_first_unsafe_second_safe(self):
        baseline = self.markdown("`Alpha Anchor` 只在代码中。\n\n这里有 Alpha Anchor 安全短语。")
        outcome = self.inject(baseline)
        self.assertIn("这里有 [Alpha Anchor]", outcome.markdown)

    def test_one_link_per_paragraph(self):
        registry = self.basic_registry()
        plan = self.plan(registry, ("entry-alpha", "entry-beta"), requested=2)
        outcome = self.inject(self.markdown("Alpha Anchor 与 Beta Anchor 在同一段。"), registry, plan)
        self.assertEqual(len(outcome.result.placed_entries), 1)
        self.assertEqual(len(outcome.result.skipped_entries), 1)

    def test_two_entries_use_different_paragraphs(self):
        registry = self.basic_registry()
        plan = self.plan(registry, ("entry-alpha", "entry-beta"), requested=2)
        outcome = self.inject(self.markdown("Alpha Anchor 第一段。\n\nBeta Anchor 第二段。"), registry, plan)
        self.assertEqual(len(outcome.result.placed_entries), 2)
        self.assertNotEqual(*(item.paragraph_index for item in outcome.result.placed_entries))

    def test_front_matter_is_protected(self):
        baseline = "---\ntitle: \"Alpha Anchor\"\n---\n{% raw %}\n# H1\n\n没有正文锚点。\n{% endraw %}\n"
        self.assertEqual(self.inject(baseline).result.skipped_entries[0].reason, "NO_SAFE_SPECIFIED_LINK_POINT")

    def test_h1_is_protected(self):
        baseline = self.markdown("没有正文。") .replace("# Synthetic", "# Alpha Anchor")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_h2_to_h6_are_protected(self):
        for level in range(2, 7):
            with self.subTest(level=level):
                baseline = self.markdown("#" * level + " Alpha Anchor\n\n没有正文。")
                self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_backtick_fence_is_protected(self):
        baseline = self.markdown("```text\nAlpha Anchor\n```\n\n没有正文。")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_tilde_fence_is_protected(self):
        baseline = self.markdown("~~~text\nAlpha Anchor\n~~~\n\n没有正文。")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_inline_code_is_protected(self):
        baseline = self.markdown("正文只有 `Alpha Anchor`。")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_markdown_link_paragraph_is_protected(self):
        baseline = self.markdown("[Existing](https://existing.real-domain.tld/) 和 Alpha Anchor。")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_markdown_image_paragraph_is_protected(self):
        baseline = self.markdown("![Image](image.png) 和 Alpha Anchor。")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_bare_url_paragraph_is_protected(self):
        baseline = self.markdown("https://site.real-domain.tld/Alpha Anchor")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_html_tag_paragraph_is_protected(self):
        baseline = self.markdown("<span title=\"Alpha Anchor\">Alpha Anchor</span>")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_html_comment_is_protected(self):
        baseline = self.markdown("<!-- Alpha Anchor -->\n\n没有正文。")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_liquid_tag_is_protected(self):
        baseline = self.markdown("正文只有 {{ Alpha Anchor }}。")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_raw_boundary_is_protected(self):
        registry = self.registry([("entry-raw", "raw", "page", "{% raw %}", "technical-seo")])
        plan = self.plan(registry, ("entry-raw",))
        baseline = "---\ntitle: \"X\"\n---\n{% raw %}\n没有正文。\n{% endraw %}\n"
        self.assertEqual(len(self.inject(baseline, registry, plan).result.placed_entries), 0)

    def test_plain_body_inside_raw_is_allowed(self):
        outcome = self.inject(self.markdown("raw内部有 Alpha Anchor。"))
        self.assertEqual(len(outcome.result.placed_entries), 1)
        self.assertEqual(outcome.markdown.count("{% raw %}"), 1)
        self.assertEqual(outcome.markdown.count("{% endraw %}"), 1)

    def test_related_articles_block_is_protected(self):
        baseline = self.markdown("## 相关阅读\n\nAlpha Anchor\n\n- [Internal](./internal.html)")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_paragraph_after_next_h2_leaves_related_block(self):
        baseline = self.markdown("## 相关阅读\n\n无关内容。\n\n## 后续\n\nAlpha Anchor。")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 1)

    def test_existing_internal_link_is_preserved(self):
        baseline = self.markdown("[Internal](./internal.html)\n\nAlpha Anchor。")
        outcome = self.inject(baseline)
        self.assertEqual(outcome.markdown.count("[Internal](./internal.html)"), 1)

    def test_existing_external_markdown_link_is_preserved(self):
        baseline = self.markdown("[External](https://external.real-domain.tld/)\n\nAlpha Anchor。")
        outcome = self.inject(baseline)
        self.assertEqual(outcome.markdown.count("[External](https://external.real-domain.tld/)"), 1)

    def test_existing_html_link_is_preserved(self):
        baseline = self.markdown("<a href=\"https://external.real-domain.tld/\">External</a>\n\nAlpha Anchor。")
        outcome = self.inject(baseline)
        self.assertIn("<a href=\"https://external.real-domain.tld/\">External</a>", outcome.markdown)

    def test_exact_anchor_not_normalized_match(self):
        baseline = self.markdown("正文只有 alpha anchor 小写文本。")
        self.assertEqual(len(self.inject(baseline).result.placed_entries), 0)

    def test_duplicate_url_plan_fails_closed(self):
        registry = self.registry(
            [
                ("entry-a", "same", "page", "Alpha Anchor", "technical-seo"),
                ("entry-b", "same", "page", "Beta Anchor", "technical-seo"),
            ]
        )
        plan = self.plan(registry, ("entry-a", "entry-b"), requested=2)
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: self.inject(self.markdown("Alpha Anchor\n\nBeta Anchor"), registry, plan))

    def test_duplicate_normalized_anchor_plan_fails_closed(self):
        registry = self.registry(
            [
                ("entry-a", "one", "page", "Shared Anchor", "technical-seo"),
                ("entry-b", "two", "page", "shared anchor", "technical-seo"),
            ]
        )
        plan = self.plan(registry, ("entry-a", "entry-b"), requested=2)
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: self.inject(self.markdown("Shared Anchor"), registry, plan))

    def test_version_mismatch_fails(self):
        self.assert_code("SPECIFIED_LINK_VERSION_MISMATCH", lambda: self.inject(self.markdown("Alpha Anchor"), specified_link_version="slr1:wrong"))

    def test_config_version_mismatch_fails(self):
        self.assert_code("SPECIFIED_LINK_VERSION_MISMATCH", lambda: self.inject(self.markdown("Alpha Anchor"), config_version="wrong"))

    def test_source_mismatch_fails(self):
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: self.inject(self.markdown("Alpha Anchor"), source_slug="other-source"))

    def test_batch_mismatch_fails(self):
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: self.inject(self.markdown("Alpha Anchor"), batch_id="other-batch"))

    def test_cluster_mismatch_fails(self):
        registry = self.basic_registry()
        plan = dataclasses.replace(self.plan(registry), source_cluster="content-seo")
        self.assert_code("SPECIFIED_CLUSTER_MISMATCH", lambda: self.inject(self.markdown("Alpha Anchor"), registry, plan, source_cluster="content-seo"))

    def test_unknown_registry_entry_fails(self):
        registry = self.basic_registry()
        selected = dataclasses.replace(self.plan(registry).selected_entries[0], entry_id="unknown")
        plan = dataclasses.replace(self.plan(registry), selected_entries=(selected,))
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: self.inject(self.markdown("Alpha Anchor"), registry, plan))

    def test_entry_identity_mismatch_fails(self):
        registry = self.basic_registry()
        selected = dataclasses.replace(self.plan(registry).selected_entries[0], anchor="Tampered")
        plan = dataclasses.replace(self.plan(registry), selected_entries=(selected,))
        self.assert_code("UNAPPROVED_SPECIFIED_URL", lambda: self.inject(self.markdown("Alpha Anchor"), registry, plan))

    def test_protected_production_source_fails(self):
        self.assert_code(
            "EXISTING_PRODUCTION_MUTATION_ATTEMPT",
            lambda: self.inject(self.markdown("Alpha Anchor"), protected_slug_set={"new-article"}),
        )

    def test_no_anchor_is_placement_shortfall(self):
        outcome = self.inject(self.markdown("没有任何匹配锚点。"))
        self.assertEqual(outcome.result.status, "PASS_WITH_SHORTFALL")
        self.assertEqual(outcome.result.shortfall_reason, "NO_SAFE_SPECIFIED_LINK_POINT")

    def test_planner_shortfall_provenance_is_preserved(self):
        registry = self.basic_registry()
        plan = self.plan(
            registry,
            ("entry-alpha",),
            requested=2,
            status="PASS_WITH_SHORTFALL",
            reason="INSUFFICIENT_SPECIFIED_CLUSTER_CANDIDATES",
        )
        outcome = self.inject(self.markdown("Alpha Anchor。"), registry, plan)
        self.assertIn("PLANNER_SHORTFALL:INSUFFICIENT_SPECIFIED_CLUSTER_CANDIDATES", outcome.result.warnings)
        self.assertEqual(outcome.result.status, "PASS_WITH_SHORTFALL")

    def test_planner_and_placement_shortfalls_are_both_preserved(self):
        registry = self.basic_registry()
        plan = self.plan(
            registry,
            ("entry-alpha",),
            requested=2,
            status="PASS_WITH_SHORTFALL",
            reason="SPECIFIED_BATCH_CAP_EXHAUSTED",
        )
        outcome = self.inject(self.markdown("没有匹配。"), registry, plan)
        self.assertEqual(len(outcome.result.warnings), 2)
        self.assertIn("PLANNER_SHORTFALL:SPECIFIED_BATCH_CAP_EXHAUSTED", outcome.result.warnings)
        self.assertIn("PLACEMENT_SHORTFALL:NO_SAFE_SPECIFIED_LINK_POINT", outcome.result.warnings)

    def test_deterministic_repeat(self):
        baseline = self.markdown("Alpha Anchor。")
        first = self.inject(baseline)
        second = self.inject(baseline)
        self.assertEqual(first, second)

    def test_mutation_reversal_equals_baseline(self):
        baseline = self.markdown("Alpha Anchor。")
        outcome = self.inject(baseline)
        restored = outcome.markdown
        for placement in sorted(outcome.result.placed_entries, key=lambda item: item.start, reverse=True):
            restored = restored[: placement.start] + placement.anchor + restored[placement.end :]
        self.assertEqual(restored, baseline)

    def test_post_sha_is_correct(self):
        outcome = self.inject(self.markdown("Alpha Anchor。"))
        self.assertEqual(outcome.result.post_sha256, hashlib.sha256(outcome.markdown.encode()).hexdigest())

    def test_pre_sha_is_correct(self):
        baseline = self.markdown("Alpha Anchor。")
        outcome = self.inject(baseline)
        self.assertEqual(outcome.result.pre_sha256, hashlib.sha256(baseline.encode()).hexdigest())

    def test_placement_offsets_point_to_full_link(self):
        outcome = self.inject(self.markdown("Alpha Anchor。"))
        placement = outcome.result.placed_entries[0]
        self.assertEqual(
            outcome.markdown[placement.start : placement.end],
            f"[{placement.anchor}]({placement.url})",
        )

    def test_crlf_is_preserved(self):
        baseline = self.markdown("Alpha Anchor。", newline="\r\n")
        outcome = self.inject(baseline)
        restored = outcome.markdown
        placement = outcome.result.placed_entries[0]
        restored = restored[: placement.start] + placement.anchor + restored[placement.end :]
        self.assertEqual(restored, baseline)

    def test_does_not_create_fixed_resource_blocks(self):
        outcome = self.inject(self.markdown("Alpha Anchor。"))
        for heading in ("Recommended Resources", "推荐资源", "友情链接", "相关阅读2"):
            self.assertNotIn(heading, outcome.markdown)

    def test_unsafe_anchor_markup_is_skipped(self):
        registry = self.registry([("entry-bracket", "bracket", "page", "[Alpha]", "technical-seo")])
        plan = self.plan(registry, ("entry-bracket",))
        outcome = self.inject(self.markdown("正文有 [Alpha] 字样。"), registry, plan)
        self.assertEqual(len(outcome.result.placed_entries), 0)

    def test_unsafe_url_parentheses_is_skipped(self):
        registry = self.registry([("entry-paren", "paren", "page-(x)", "Alpha Anchor", "technical-seo")])
        plan = self.plan(registry, ("entry-paren",))
        outcome = self.inject(self.markdown("Alpha Anchor。"), registry, plan)
        self.assertEqual(len(outcome.result.placed_entries), 0)

    def test_malformed_front_matter_fails(self):
        self.assert_code("SPECIFIED_PROTECTED_ZONE_VIOLATION", lambda: self.inject("Alpha Anchor"))

    def test_unclosed_fence_fails(self):
        baseline = self.markdown("```\nAlpha Anchor")
        self.assert_code("SPECIFIED_PROTECTED_ZONE_VIOLATION", lambda: self.inject(baseline))

    def test_unclosed_html_comment_fails(self):
        baseline = self.markdown("<!-- Alpha Anchor")
        self.assert_code("SPECIFIED_PROTECTED_ZONE_VIOLATION", lambda: self.inject(baseline))

    def test_html_comment_marker_inside_fence_is_ignored(self):
        baseline = self.markdown("```html\n<!-- Alpha Anchor\n```\n\n没有正文锚点。")
        outcome = self.inject(baseline)
        self.assertEqual(len(outcome.result.placed_entries), 0)

    def test_html_comment_marker_inside_inline_code_is_ignored(self):
        baseline = self.markdown("正文展示 `<!-- Alpha Anchor` 示例。")
        outcome = self.inject(baseline)
        self.assertEqual(len(outcome.result.placed_entries), 0)

    def test_unclosed_raw_fails(self):
        baseline = "---\ntitle: \"X\"\n---\n{% raw %}\nAlpha Anchor\n"
        self.assert_code("SPECIFIED_PROTECTED_ZONE_VIOLATION", lambda: self.inject(baseline))

    def test_result_requested_entries_match_plan_identity(self):
        registry = self.basic_registry()
        outcome = self.inject(self.markdown("Alpha Anchor。"), registry)
        requested = outcome.result.requested_entries[0]
        selected = self.plan(registry).selected_entries[0]
        self.assertEqual(
            (requested.entry_id, requested.canonical_url, requested.anchor, requested.normalized_anchor, requested.cluster),
            (selected.entry_id, selected.canonical_url, selected.anchor, selected.normalized_anchor, selected.cluster),
        )

    def test_scan_reports_required_token_types(self):
        scan = scan_specified_markdown(
            self.markdown("`code` {{ liquid }}\n\n[link](./a.html)\n\n<img src=\"x\">\n\nhttps://site.real-domain.tld/")
        )
        kinds = {token.kind for token in scan.tokens}
        self.assertTrue({"front_matter", "heading", "inline_code", "liquid_tag", "markdown_link", "html_tag", "bare_url"} <= kinds)


if __name__ == "__main__":
    unittest.main()
