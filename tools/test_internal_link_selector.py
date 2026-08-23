from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from article_spec import ArticleSpec
from internal_link_registry import RegistryEntry, RegistrySnapshot, compute_registry_version
from internal_link_selector import (
    BatchRegistryEntry,
    SelectionError,
    TargetRecord,
    calculate_inbound_cap,
    candidate_hash,
    plan_batch,
    resolve_candidates,
    score_relevance,
)


def spec(slug: str, cluster: str = "content-seo", title: str | None = None) -> ArticleSpec:
    return ArticleSpec(slug, title or slug.replace("-", " "), cluster, "explicit")


def entry(
    slug: str,
    cluster: str = "content-seo",
    *,
    title: str | None = None,
    published: bool = True,
    eligible: bool = True,
) -> RegistryEntry:
    return RegistryEntry(
        slug=slug,
        title=title or slug.replace("-", " "),
        cluster=cluster,
        cluster_source="explicit",
        source_batch="production-batch-001.txt",
        markdown_path=f"articles/{slug}.md",
        relative_url=f"./{slug}.html",
        canonical_url=f"https://example.invalid/articles/{slug}.html",
        published=published,
        eligible_as_target=eligible,
    )


def snapshot(entries) -> RegistrySnapshot:
    entries = tuple(entries)
    batches = (
        "production-batch-001.txt",
        "production-batch-002.txt",
        "production-batch-003.txt",
        "production-batch-004.txt",
    )
    version = compute_registry_version(entries, source_batches=batches)
    return RegistrySnapshot(entries, batches, "1", version)


def many_entries(count: int, cluster: str = "content-seo"):
    return [entry(f"content-target-{index:03d}", cluster) for index in range(count)]


class InternalLinkSelectorTests(unittest.TestCase):
    def resolve(self, source, entries, **kwargs):
        snap = snapshot(entries)
        return resolve_candidates(
            source,
            snap,
            batch_extension=kwargs.get("extension", ()),
            batch_source_slugs=kwargs.get("batch_source_slugs", set()),
            batch_id="batch-test",
            config_version="config-1",
            expected_registry_version=kwargs.get("expected_registry_version", snap.registry_version),
            expected_config_version=kwargs.get("expected_config_version", "config-1"),
            inbound_sources=kwargs.get("inbound_sources", {}),
            inbound_cap=kwargs.get("inbound_cap", 10),
            file_exists=kwargs.get("file_exists", lambda path: True),
        )

    def test_self_filtered(self):
        candidates, events, _, _ = self.resolve(spec("same"), [entry("same")])
        self.assertFalse(candidates)
        self.assertIn("SELF_LINK_REJECTED", {event.code for event in events})

    def test_ineligible_filtered(self):
        candidates, events, _, _ = self.resolve(spec("source"), [entry("target", eligible=False)])
        self.assertFalse(candidates)
        self.assertIn("REGISTRY_TARGET_INELIGIBLE", {event.code for event in events})

    def test_unpublished_filtered(self):
        candidates, events, _, _ = self.resolve(spec("source"), [entry("target", published=False)])
        self.assertFalse(candidates)
        self.assertIn("UNPUBLISHED_TARGET_REJECTED", {event.code for event in events})

    def test_missing_markdown_file_filtered(self):
        candidates, events, _, _ = self.resolve(spec("source"), [entry("target")], file_exists=lambda path: False)
        self.assertFalse(candidates)
        self.assertIn("REGISTRY_TARGET_MISSING", {event.code for event in events})

    def test_missing_registry_entry_filtered(self):
        extension = (BatchRegistryEntry("", "target", "content-seo", "articles/target.md"),)
        candidates, events, _, _ = self.resolve(spec("source"), [], extension=extension)
        self.assertFalse(candidates)
        self.assertIn("REGISTRY_TARGET_MISSING", {event.code for event in events})

    def test_malformed_registry_entry_filtered(self):
        extension = (BatchRegistryEntry("target", "target", "not-a-cluster", "articles/target.md"),)
        candidates, events, _, _ = self.resolve(spec("source"), [], extension=extension)
        self.assertFalse(candidates)
        self.assertIn("MALFORMED_REGISTRY_ENTRY", {event.code for event in events})

    def test_duplicate_target_filtered(self):
        frozen = entry("target")
        extension = BatchRegistryEntry("target", "target", "content-seo", "articles/target.md")
        _, events, _, _ = self.resolve(spec("source"), [frozen], extension=(extension,))
        self.assertIn("DUPLICATE_TARGET_REJECTED", {event.code for event in events})

    def test_below_threshold_filtered(self):
        candidates, events, _, _ = self.resolve(spec("source"), [entry("unrelated", "technical-seo")])
        self.assertFalse(candidates)
        self.assertIn("RELEVANCE_BELOW_THRESHOLD", {event.code for event in events})

    def test_same_cluster_adds_50(self):
        target = TargetRecord("target", "目标", "content-seo", "x", True, True, True, "frozen_registry", False)
        score, reasons = score_relevance(spec("source"), target)
        self.assertEqual(score, 50)
        self.assertIn("same_cluster:+50", reasons)

    def test_topic_terms_capped_at_30(self):
        source = spec("crawl-indexing-sitemap", "unclassified", "抓取 收录 Sitemap 状态码")
        target = TargetRecord("crawl-indexing-sitemap-status-code", "抓取 收录 Sitemap 状态码", "unclassified", "x", True, True, True, "frozen_registry", False)
        score, reasons = score_relevance(source, target)
        self.assertEqual(score, 30)
        self.assertTrue(any(reason.endswith(":+30") for reason in reasons))

    def test_complementary_adds_15(self):
        source = spec("content-audit-source", "unclassified", "内容审计")
        target = TargetRecord("content-pruning-target", "内容清理", "unclassified", "x", True, True, True, "frozen_registry", False)
        score, reasons = score_relevance(source, target)
        self.assertEqual(score, 25)
        self.assertIn("complementary_intent:+15", reasons)

    def test_cross_cluster_adds_10(self):
        source = spec("plain-source", "content-seo", "普通主题")
        target = TargetRecord("plain-target", "另一主题", "internal-linking", "x", True, True, True, "frozen_registry", False)
        score, reasons = score_relevance(source, target)
        self.assertEqual(score, 10)
        self.assertIn("allowed_cross_cluster:+10", reasons)

    def test_score_capped_at_100(self):
        source = spec("internal-link-problem-architecture-content", "internal-linking", "内链 问题 结构 内容 诊断")
        target = TargetRecord("internal-link-fix-architecture-content", "内链 修复 结构 内容 排查", "internal-linking", "x", True, True, True, "frozen_registry", False)
        score, _ = score_relevance(source, target)
        self.assertEqual(score, 95)
        self.assertLessEqual(score, 100)

    def test_generic_terms_do_not_inflate_score(self):
        source = spec("generic-one", "unclassified", "SEO网站优化完整指南")
        target = TargetRecord("generic-two", "SEO网站优化实战方法", "technical-seo", "x", True, True, True, "frozen_registry", False)
        score, _ = score_relevance(source, target)
        self.assertEqual(score, 0)

    def test_inbound_cap_10_batch(self):
        self.assertEqual(calculate_inbound_cap(10), 2)

    def test_inbound_cap_20_batch(self):
        self.assertEqual(calculate_inbound_cap(20), 4)

    def test_inbound_cap_50_batch(self):
        self.assertEqual(calculate_inbound_cap(50), 10)

    def test_inbound_cap_100_batch(self):
        self.assertEqual(calculate_inbound_cap(100), 20)

    def test_inbound_cap_reached_filters_candidate(self):
        inbound = {"target": {"one", "two"}}
        candidates, events, _, _ = self.resolve(
            spec("source"),
            [entry("target")],
            inbound_sources=inbound,
            inbound_cap=2,
        )
        self.assertFalse(candidates)
        self.assertIn("INBOUND_CAP_REACHED", {event.code for event in events})

    def test_same_batch_35_percent(self):
        sources = [spec(f"source-{index:02d}") for index in range(10)]
        frozen = snapshot(many_entries(160))
        extension = [BatchRegistryEntry(source.slug, source.title, source.cluster, f"articles/{source.slug}.md") for source in sources]
        result = plan_batch(sources, frozen, batch_extension=extension, batch_id="b", config_version="c", file_exists=lambda path: True)
        self.assertTrue(all(plan.same_batch_links * 100 <= plan.internal_links * 35 for plan in result.plans))

    def test_deterministic_candidate_hash(self):
        first = candidate_hash("b", "s", "r", "c", "t")
        self.assertEqual(first, candidate_hash("b", "s", "r", "c", "t"))

    def test_deterministic_target_order(self):
        source = spec("source")
        entries = many_entries(40)
        first = self.resolve(source, entries)[0]
        second = self.resolve(source, reversed(entries))[0]
        self.assertEqual([item.target_slug for item in first], [item.target_slug for item in second])

    def test_deterministic_batch_plan(self):
        sources = [spec(f"source-{index:02d}") for index in range(10)]
        snap = snapshot(many_entries(160))
        first = plan_batch(sources, snap, batch_id="b", config_version="c", file_exists=lambda path: True)
        second = plan_batch(list(reversed(sources)), snap, batch_id="b", config_version="c", file_exists=lambda path: True)
        self.assertEqual(first, second)

    def test_different_sources_get_different_combinations(self):
        sources = [spec("source-one"), spec("source-two")]
        snap = snapshot(many_entries(80))
        result = plan_batch(sources, snap, batch_id="b", config_version="c", file_exists=lambda path: True)
        combinations = [tuple(target.target_slug for target in plan.selected_targets) for plan in result.plans]
        self.assertNotEqual(combinations[0], combinations[1])

    def test_no_forced_reciprocal(self):
        sources = [spec("article-a", "content-seo"), spec("article-b", "technical-seo")]
        frozen = many_entries(80, "content-seo") + [
            entry(f"technical-target-{index:03d}", "technical-seo")
            for index in range(80)
        ]
        extension = [
            BatchRegistryEntry(source.slug, source.title, source.cluster, f"articles/{source.slug}.md")
            for source in sources
        ]
        result = plan_batch(sources, snapshot(frozen), batch_extension=extension, batch_id="b", config_version="c", file_exists=lambda path: True)
        selected = {plan.source_slug: {target.target_slug for target in plan.selected_targets} for plan in result.plans}
        self.assertFalse("article-b" in selected["article-a"] or "article-a" in selected["article-b"])

    def test_no_forced_ring(self):
        sources = [
            spec("article-a", "content-seo"),
            spec("article-b", "technical-seo"),
            spec("article-c", "keyword-research"),
        ]
        frozen = []
        for cluster in ("content-seo", "technical-seo", "keyword-research"):
            frozen.extend(entry(f"{cluster}-target-{index:03d}", cluster) for index in range(60))
        extension = [
            BatchRegistryEntry(source.slug, source.title, source.cluster, f"articles/{source.slug}.md")
            for source in sources
        ]
        result = plan_batch(sources, snapshot(frozen), batch_extension=extension, batch_id="b", config_version="c", file_exists=lambda path: True)
        selected = {plan.source_slug: {target.target_slug for target in plan.selected_targets} for plan in result.plans}
        self.assertFalse("article-b" in selected["article-a"] and "article-c" in selected["article-b"] and "article-a" in selected["article-c"])

    def test_no_alphabetical_neighbor_rule(self):
        sources = [spec("article-a", "content-seo"), spec("article-b", "technical-seo")]
        extension = [
            BatchRegistryEntry(source.slug, source.title, source.cluster, f"articles/{source.slug}.md")
            for source in sources
        ]
        result = plan_batch(
            sources,
            snapshot(many_entries(80)),
            batch_extension=extension,
            batch_id="b",
            config_version="c",
            file_exists=lambda path: True,
        )
        first_targets = {target.target_slug for target in result.plans[0].selected_targets}
        self.assertNotIn("article-b", first_targets)

    def test_configured_max_respected(self):
        result = plan_batch([spec("source")], snapshot(many_entries(80)), batch_id="b", config_version="c", configured_max=25, file_exists=lambda path: True)
        self.assertEqual(result.plans[0].internal_links, 25)

    def test_selection_24_to_30_when_sufficient(self):
        sources = [spec(f"source-{index:02d}") for index in range(10)]
        result = plan_batch(sources, snapshot(many_entries(160)), batch_id="b", config_version="c", file_exists=lambda path: True)
        self.assertTrue(all(24 <= plan.internal_links <= 30 for plan in result.plans))

    def test_20_to_23_is_pass(self):
        result = plan_batch([spec("source")], snapshot(many_entries(22)), batch_id="b", config_version="c", file_exists=lambda path: True)
        self.assertEqual((result.plans[0].internal_links, result.plans[0].status), (22, "PASS"))

    def test_below_20_is_shortfall(self):
        result = plan_batch([spec("source")], snapshot(many_entries(12)), batch_id="b", config_version="c", file_exists=lambda path: True)
        self.assertEqual(result.plans[0].status, "PASS_WITH_SHORTFALL")
        self.assertEqual(result.plans[0].shortfall_reason, "INSUFFICIENT_RELEVANT_CANDIDATES")

    def test_registry_version_mismatch_fails(self):
        snap = snapshot(many_entries(2))
        with self.assertRaisesRegex(SelectionError, "REGISTRY_VERSION_MISMATCH"):
            plan_batch([spec("source")], snap, batch_id="b", config_version="c", expected_registry_version="wrong", file_exists=lambda path: True)

    def test_config_version_mismatch_fails(self):
        snap = snapshot(many_entries(2))
        with self.assertRaisesRegex(SelectionError, "CONFIG_VERSION_MISMATCH"):
            plan_batch([spec("source")], snap, batch_id="b", config_version="c", expected_config_version="wrong", file_exists=lambda path: True)

    def test_frozen_registry_source_accepted(self):
        candidates = self.resolve(spec("source"), [entry("target")])[0]
        self.assertEqual(candidates[0].source, "frozen_registry")

    def test_batch_registry_extension_source_accepted(self):
        extension = (BatchRegistryEntry("target", "target", "content-seo", "articles/target.md"),)
        candidates = self.resolve(spec("source"), [], extension=extension)[0]
        self.assertEqual(candidates[0].source, "batch_registry_extension")

    def test_failed_batch_target_excluded(self):
        extension = (BatchRegistryEntry("target", "target", "content-seo", "articles/target.md", content_quality_pass=False),)
        candidates, events, _, _ = self.resolve(spec("source"), [], extension=extension)
        self.assertFalse(candidates)
        self.assertIn("CONTENT_QUALITY_NOT_PASSED", {event.code for event in events})

    def test_global_inbound_load_maintained(self):
        sources = [spec(f"source-{index:02d}") for index in range(10)]
        result = plan_batch(sources, snapshot(many_entries(160)), batch_id="b", config_version="c", file_exists=lambda path: True)
        self.assertTrue(result.inbound_loads)
        self.assertLessEqual(max(result.inbound_loads.values()), result.inbound_cap)

    def test_final_inbound_distribution_validation(self):
        sources = [spec(f"source-{index:02d}") for index in range(20)]
        result = plan_batch(sources, snapshot(many_entries(160)), batch_id="b", config_version="c", file_exists=lambda path: True)
        self.assertEqual(result.inbound_cap, 4)
        self.assertLessEqual(max(result.inbound_loads.values()), 4)


if __name__ == "__main__":
    unittest.main()
