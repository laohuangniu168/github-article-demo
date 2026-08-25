import dataclasses
import unittest

from specified_link_planner import (
    SpecifiedLinkSourceArticle,
    calculate_specified_link_batch_caps,
    compute_specified_link_candidate_hash,
    plan_specified_links_for_batch,
)
from specified_link_registry import (
    SPECIFIED_LINK_CONFIG_VERSION,
    SpecifiedLinkContractError,
    SpecifiedLinkPreflightResult,
    build_specified_link_registry,
    parse_specified_link_lines,
)


class SpecifiedLinkPlannerTests(unittest.TestCase):
    def registry(self, rows):
        lines = [f"{entry_id}|https://{host}.real-domain.tld/{path}|{anchor}|{cluster}\n" for entry_id, host, path, anchor, cluster in rows]
        return build_specified_link_registry(parse_specified_link_lines(lines))

    def preflights(self, registry):
        return tuple(
            SpecifiedLinkPreflightResult(
                entry.id, entry.url, entry.canonical_url, 200, None,
                "2026-08-25T00:00:00Z", "PASS", None,
            )
            for entry in registry.entries
        )

    def sources(self, count, cluster="technical-seo"):
        return tuple(SpecifiedLinkSourceArticle(f"source-{index:03d}", cluster) for index in range(count))

    def basic_registry(self, count=6, cluster="technical-seo"):
        return self.registry(
            [(f"entry-{index:03d}", f"seo-{index}", f"page-{index}", f"Anchor {index}", cluster) for index in range(count)]
        )

    def plan(self, sources=None, registry=None, configured_max=1, **kwargs):
        registry = registry or self.basic_registry()
        sources = sources or self.sources(10)
        return plan_specified_links_for_batch(
            sources,
            registry,
            self.preflights(registry),
            batch_id="planner-batch",
            configured_max=configured_max,
            **kwargs,
        )

    def assert_code(self, code, callback):
        with self.assertRaises(SpecifiedLinkContractError) as context:
            callback()
        self.assertEqual(context.exception.code, code)

    def test_configured_max_1_2_3(self):
        for value in (1, 2, 3):
            with self.subTest(value=value):
                result = self.plan(sources=self.sources(1), configured_max=value)
                self.assertEqual(result.plans[0].requested_links, value)
                self.assertEqual(result.plans[0].selected_links, value)

    def test_invalid_configured_max(self):
        for value in (0, 4, True):
            with self.subTest(value=value):
                self.assert_code("INVALID_SPECIFIED_INPUT_FORMAT", lambda item=value: self.plan(configured_max=item))

    def test_source_validation(self):
        registry = self.basic_registry()
        for source in (
            SpecifiedLinkSourceArticle("Bad_Slug", "technical-seo"),
            SpecifiedLinkSourceArticle("valid-slug", "unclassified"),
        ):
            with self.subTest(source=source):
                self.assert_code("INVALID_SPECIFIED_INPUT_FORMAT", lambda item=source: self.plan(sources=(item,), registry=registry))

    def test_exact_cluster_and_mismatch_filter(self):
        registry = self.registry(
            [
                ("entry-tech", "tech", "a", "Tech Anchor", "technical-seo"),
                ("entry-content", "content", "a", "Content Anchor", "content-seo"),
            ]
        )
        plan = self.plan(sources=self.sources(1), registry=registry).plans[0]
        self.assertEqual([item.entry_id for item in plan.selected_entries], ["entry-tech"])
        self.assertIn("SPECIFIED_CLUSTER_MISMATCH", [item.reason_code for item in plan.filtered_entries])

    def test_batch_cap_exact_values(self):
        expected = {10: (2, 1, 2), 20: (4, 2, 3), 50: (10, 5, 8), 100: (10, 5, 10)}
        for size, values in expected.items():
            with self.subTest(size=size):
                caps = calculate_specified_link_batch_caps(size)
                self.assertEqual(
                    (caps.per_url_batch_cap, caps.per_url_anchor_pair_batch_cap, caps.per_anchor_batch_cap),
                    values,
                )

    def test_url_cap_for_10_20_50_100(self):
        for size in (10, 20, 50, 100):
            with self.subTest(size=size):
                registry = self.registry(
                    [(f"entry-{i}", "shared", "page", f"Anchor {i}", "technical-seo") for i in range(12)]
                )
                result = self.plan(sources=self.sources(size), registry=registry)
                self.assertLessEqual(max(result.usage.url_usage.values(), default=0), result.caps.per_url_batch_cap)

    def test_pair_cap_for_10_20_50_100(self):
        for size in (10, 20, 50, 100):
            with self.subTest(size=size):
                registry = self.registry([("entry-one", "pair", "page", "Shared Pair", "technical-seo")])
                result = self.plan(sources=self.sources(size), registry=registry)
                self.assertEqual(max(result.usage.url_anchor_pair_usage.values()), result.caps.per_url_anchor_pair_batch_cap)

    def test_anchor_cap_for_10_20_50_100(self):
        for size in (10, 20, 50, 100):
            with self.subTest(size=size):
                registry = self.registry(
                    [(f"entry-{i}", f"host-{i}", "page", "Shared Anchor", "technical-seo") for i in range(12)]
                )
                result = self.plan(sources=self.sources(size), registry=registry)
                self.assertEqual(max(result.usage.anchor_usage.values()), result.caps.per_anchor_batch_cap)

    def test_same_url_different_anchor_local_uniqueness(self):
        registry = self.registry(
            [
                ("entry-a", "shared", "page", "Alpha", "technical-seo"),
                ("entry-b", "shared", "page", "Beta", "technical-seo"),
                ("entry-c", "other", "page", "Gamma", "technical-seo"),
            ]
        )
        plan = self.plan(sources=self.sources(1), registry=registry, configured_max=3).plans[0]
        urls = [item.canonical_url for item in plan.selected_entries]
        self.assertEqual(len(urls), len(set(urls)))

    def test_same_anchor_different_url_local_uniqueness(self):
        registry = self.registry(
            [
                ("entry-a", "one", "page", "Shared", "technical-seo"),
                ("entry-b", "two", "page", "Shared", "technical-seo"),
                ("entry-c", "three", "page", "Other", "technical-seo"),
            ]
        )
        plan = self.plan(sources=self.sources(1), registry=registry, configured_max=3).plans[0]
        anchors = [item.normalized_anchor for item in plan.selected_entries]
        self.assertEqual(len(anchors), len(set(anchors)))

    def test_usage_before_after_and_distinct_source_counting(self):
        registry = self.basic_registry(3)
        result = self.plan(sources=self.sources(3), registry=registry)
        for plan in result.plans:
            selected = plan.selected_entries[0]
            self.assertEqual(selected.url_usage_after, selected.url_usage_before + 1)
            self.assertEqual(selected.pair_usage_after, selected.pair_usage_before + 1)
            self.assertEqual(selected.anchor_usage_after, selected.anchor_usage_before + 1)
        self.assertEqual(sum(result.usage.url_usage.values()), 3)

    def test_candidate_hash_exact_seed(self):
        first = compute_specified_link_candidate_hash(
            batch_id="batch", source_slug="source", specified_link_version="slr1:x",
            config_version="config", entry_id="entry",
        )
        second = compute_specified_link_candidate_hash(
            batch_id="batch", source_slug="source", specified_link_version="slr1:x",
            config_version="config", entry_id="entry",
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_source_input_reorder_is_deterministic(self):
        registry = self.basic_registry(8)
        sources = self.sources(20)
        first = self.plan(sources=sources, registry=registry)
        second = self.plan(sources=tuple(reversed(sources)), registry=registry)
        mapping = lambda result: {plan.source_slug: tuple(item.entry_id for item in plan.selected_entries) for plan in result.plans}
        self.assertEqual(mapping(first), mapping(second))

    def test_registry_entry_reorder_is_deterministic(self):
        registry = self.basic_registry(8)
        reversed_registry = dataclasses.replace(registry, entries=tuple(reversed(registry.entries)))
        first = self.plan(registry=registry)
        second = self.plan(registry=reversed_registry)
        self.assertEqual(first.plans, second.plans)

    def test_missing_preflight_fails_batch(self):
        registry = self.basic_registry(2)
        self.assert_code(
            "UNAPPROVED_SPECIFIED_URL",
            lambda: plan_specified_links_for_batch(
                self.sources(1), registry, self.preflights(registry)[:1], batch_id="batch"
            ),
        )

    def test_failed_preflight_fails_batch(self):
        registry = self.basic_registry(1)
        failed = dataclasses.replace(
            self.preflights(registry)[0], status_code=404, result="FAIL", error_code="TARGET_URL_HTTP_ERROR"
        )
        self.assert_code(
            "TARGET_URL_HTTP_ERROR",
            lambda: plan_specified_links_for_batch(self.sources(1), registry, (failed,), batch_id="batch"),
        )

    def test_version_and_config_mismatch_fail(self):
        registry = self.basic_registry(1)
        self.assert_code("SPECIFIED_LINK_VERSION_MISMATCH", lambda: self.plan(registry=registry, specified_link_version="slr1:wrong"))
        self.assert_code("SPECIFIED_LINK_VERSION_MISMATCH", lambda: self.plan(registry=registry, config_version="wrong"))

    def test_pass_status(self):
        plan = self.plan(sources=self.sources(1), configured_max=2).plans[0]
        self.assertEqual((plan.status, plan.shortfall_reason), ("PASS", None))

    def test_cluster_candidate_shortfall(self):
        registry = self.registry([("entry-content", "content", "page", "Content", "content-seo")])
        plan = self.plan(sources=self.sources(1), registry=registry).plans[0]
        self.assertEqual((plan.status, plan.shortfall_reason), ("PASS_WITH_SHORTFALL", "INSUFFICIENT_SPECIFIED_CLUSTER_CANDIDATES"))

    def test_cap_shortfall_and_priority(self):
        registry = self.registry(
            [
                ("entry-pair", "pair", "page", "Pair", "technical-seo"),
                ("entry-other-cluster", "content", "page", "Content", "content-seo"),
            ]
        )
        result = self.plan(sources=self.sources(10), registry=registry)
        shortfalls = [plan for plan in result.plans if plan.status == "PASS_WITH_SHORTFALL"]
        self.assertTrue(shortfalls)
        self.assertTrue(all(plan.shortfall_reason == "SPECIFIED_BATCH_CAP_EXHAUSTED" for plan in shortfalls))

    def test_usage_balancing_prevents_fixed_target(self):
        registry = self.basic_registry(10)
        result = self.plan(sources=self.sources(10), registry=registry)
        selected = [plan.selected_entries[0].entry_id for plan in result.plans]
        self.assertGreater(len(set(selected)), 1)

    def test_not_simple_entry_id_round_robin(self):
        registry = self.basic_registry(10)
        result = self.plan(sources=self.sources(10), registry=registry)
        actual = [plan.selected_entries[0].entry_id for plan in result.plans]
        simple = [entry.id for entry in registry.entries[:10]]
        self.assertNotEqual(actual, simple)

    def test_synthetic_batch_summaries_have_no_failures(self):
        registry = self.basic_registry(20)
        for size in (10, 20, 50, 100):
            with self.subTest(size=size):
                result = self.plan(sources=self.sources(size), registry=registry, configured_max=2)
                self.assertNotIn("FAIL", [plan.status for plan in result.plans])
                self.assertLessEqual(max(result.usage.url_usage.values(), default=0), result.caps.per_url_batch_cap)
                self.assertLessEqual(max(result.usage.url_anchor_pair_usage.values(), default=0), result.caps.per_url_anchor_pair_batch_cap)
                self.assertLessEqual(max(result.usage.anchor_usage.values(), default=0), result.caps.per_anchor_batch_cap)

    def test_plan_identity_and_schema(self):
        registry = self.basic_registry(3)
        plan = self.plan(sources=self.sources(1), registry=registry).plans[0]
        self.assertEqual(plan.batch_id, "planner-batch")
        self.assertEqual(plan.source_cluster, "technical-seo")
        self.assertEqual(plan.specified_link_version, registry.specified_link_version)
        self.assertEqual(plan.config_version, SPECIFIED_LINK_CONFIG_VERSION)


if __name__ == "__main__":
    unittest.main()
