from __future__ import annotations

import dataclasses
import inspect
import unittest

from direct_specified_link_planner import (
    DirectSourceArticle,
    plan_direct_specified_links_for_batch,
)
from direct_specified_link_registry import (
    DIRECT_CONFIG_VERSION,
    DirectSpecifiedLinkContractError,
    build_direct_registry,
    parse_direct_link_lines,
)


class DirectSpecifiedLinkPlannerTests(unittest.TestCase):
    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(DirectSpecifiedLinkContractError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def registry(self, count: int, *, same_url: bool = False, same_anchor: bool = False):
        lines = []
        for index in range(count):
            url_index = 0 if same_url else index
            anchor_index = 0 if same_anchor else index
            lines.append(
                f"target-{index:03d}|https://host-{url_index}.real-domain.tld/Path//{url_index}|Anchor {anchor_index}\n"
            )
        return build_direct_registry(parse_direct_link_lines(lines, source_filename="approved-direct.txt"))

    def sources(self, count: int):
        return tuple(DirectSourceArticle(f"source-{index:03d}") for index in range(count))

    def plan(self, source_count=10, entry_count=20, configured=2, batch_id="batch-direct-001", registry=None):
        registry = registry or self.registry(entry_count)
        return plan_direct_specified_links_for_batch(
            self.sources(source_count),
            registry,
            batch_id=batch_id,
            configured_direct_links_per_article=configured,
            direct_registry_version=registry.direct_registry_version,
            config_version=registry.config_version,
        )

    def mapping(self, result):
        return {plan.source_slug: tuple(entry.entry_id for entry in plan.selected_entries) for plan in result.plans}

    def assert_balanced(self, result):
        values = list(result.entry_usage.values())
        self.assertLessEqual(max(values) - min(values), 1)

    def test_configured_legal_values(self):
        for configured in (1, 2, 5, 10, 20, 30):
            with self.subTest(configured=configured):
                result = self.plan(source_count=1, entry_count=30, configured=configured)
                self.assertEqual((result.requested_total, result.selected_total), (configured, configured))

    def test_configured_invalid_values(self):
        for configured in (0, 31, -1, True, False, "2", 2.0):
            with self.subTest(configured=configured):
                self.assert_code(
                    "INVALID_DIRECT_PLANNER_CONFIG",
                    lambda configured=configured: self.plan(configured=configured),
                )

    def test_configured_has_no_default(self):
        parameter = inspect.signature(plan_direct_specified_links_for_batch).parameters[
            "configured_direct_links_per_article"
        ]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_source_scales(self):
        for count in (1, 10, 20, 50):
            with self.subTest(count=count):
                result = self.plan(source_count=count, entry_count=10, configured=1)
                self.assertEqual((result.source_count, result.selected_total), (count, count))

    def test_entry_scales(self):
        for count in (1, 2, 10, 20, 50):
            with self.subTest(count=count):
                result = self.plan(source_count=1, entry_count=count, configured=min(count, 2))
                self.assertEqual((result.entry_count, result.selected_total), (count, min(count, 2)))

    def test_twenty_urls_ten_articles_two_each(self):
        result = self.plan(source_count=10, entry_count=20, configured=2)
        self.assertEqual((result.requested_total, result.selected_total, result.final_status), (20, 20, "PASS"))
        self.assertEqual(set(result.entry_usage.values()), {1})

    def test_ten_urls_ten_articles_two_each(self):
        result = self.plan(source_count=10, entry_count=10, configured=2)
        self.assertEqual((result.requested_total, result.selected_total), (20, 20))
        self.assertEqual(set(result.entry_usage.values()), {2})

    def test_twenty_urls_ten_articles_ten_each_balanced(self):
        result = self.plan(source_count=10, entry_count=20, configured=10)
        self.assertEqual(result.selected_total, 100)
        self.assertEqual(set(result.entry_usage.values()), {5})

    def test_general_usage_balance(self):
        for source_count, entry_count, configured in ((7, 20, 3), (20, 50, 5), (50, 10, 7)):
            with self.subTest(values=(source_count, entry_count, configured)):
                self.assert_balanced(self.plan(source_count, entry_count, configured))

    def test_article_local_duplicate_url_blocked(self):
        result = self.plan(source_count=1, entry_count=1, configured=2)
        plan = result.plans[0]
        self.assertEqual((plan.selected_links, plan.status, plan.shortfall_reason), (1, "PASS_WITH_SHORTFALL", "INSUFFICIENT_UNIQUE_DIRECT_TARGETS"))

    def test_same_url_different_anchor_not_repeated_in_article(self):
        registry = self.registry(3, same_url=True)
        result = self.plan(source_count=2, configured=3, registry=registry)
        for plan in result.plans:
            self.assertEqual(plan.selected_links, 1)
            self.assertEqual(len({entry.canonical_url for entry in plan.selected_entries}), 1)

    def test_same_url_different_anchor_can_rotate_across_articles(self):
        registry = self.registry(3, same_url=True)
        result = self.plan(source_count=3, configured=1, registry=registry)
        self.assertEqual(set(result.entry_usage.values()), {1})

    def test_different_urls_same_anchor_allowed_in_article(self):
        registry = self.registry(3, same_anchor=True)
        result = self.plan(source_count=1, configured=3, registry=registry)
        selected = result.plans[0].selected_entries
        self.assertEqual(len(selected), 3)
        self.assertEqual(len({entry.normalized_anchor for entry in selected}), 1)

    def test_source_input_order_independent(self):
        registry = self.registry(20)
        sources = self.sources(10)
        first = plan_direct_specified_links_for_batch(
            sources, registry, batch_id="batch", configured_direct_links_per_article=2,
            direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
        )
        second = plan_direct_specified_links_for_batch(
            tuple(reversed(sources)), registry, batch_id="batch", configured_direct_links_per_article=2,
            direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
        )
        self.assertEqual(self.mapping(first), self.mapping(second))

    def test_registry_tuple_order_independent(self):
        registry = self.registry(20)
        reordered = dataclasses.replace(registry, entries=tuple(reversed(registry.entries)))
        first = self.plan(registry=registry)
        second = self.plan(registry=reordered)
        self.assertEqual(self.mapping(first), self.mapping(second))

    def test_same_batch_is_fully_deterministic(self):
        first = self.plan()
        second = self.plan()
        self.assertEqual(first, second)

    def test_different_batch_can_change_offset(self):
        baseline = self.mapping(self.plan(batch_id="batch-0"))
        alternatives = [self.mapping(self.plan(batch_id=f"batch-{index}")) for index in range(1, 20)]
        self.assertTrue(any(candidate != baseline for candidate in alternatives))

    def test_registry_version_mismatch_hard_fail(self):
        registry = self.registry(10)
        self.assert_code(
            "DIRECT_REGISTRY_VERSION_MISMATCH",
            lambda: plan_direct_specified_links_for_batch(
                self.sources(2), registry, batch_id="batch", configured_direct_links_per_article=2,
                direct_registry_version="dlr1:" + "0" * 64, config_version=registry.config_version,
            ),
        )

    def test_config_version_mismatch_hard_fail(self):
        registry = self.registry(10)
        self.assert_code(
            "DIRECT_REGISTRY_VERSION_MISMATCH",
            lambda: plan_direct_specified_links_for_batch(
                self.sources(2), registry, batch_id="batch", configured_direct_links_per_article=2,
                direct_registry_version=registry.direct_registry_version, config_version="wrong",
            ),
        )

    def test_duplicate_source_slug_hard_fail(self):
        registry = self.registry(2)
        self.assert_code(
            "DUPLICATE_DIRECT_SOURCE_SLUG",
            lambda: plan_direct_specified_links_for_batch(
                (DirectSourceArticle("same"), DirectSourceArticle("same")), registry,
                batch_id="batch", configured_direct_links_per_article=1,
                direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
            ),
        )

    def test_invalid_source_slug_hard_fail(self):
        registry = self.registry(2)
        for slug in ("", "Bad_Slug", "../bad", "with space"):
            with self.subTest(slug=slug):
                self.assert_code(
                    "INVALID_DIRECT_SOURCE",
                    lambda slug=slug: plan_direct_specified_links_for_batch(
                        (DirectSourceArticle(slug),), registry, batch_id="batch",
                        configured_direct_links_per_article=1,
                        direct_registry_version=registry.direct_registry_version,
                        config_version=registry.config_version,
                    ),
                )

    def test_empty_sources_hard_fail(self):
        registry = self.registry(2)
        self.assert_code(
            "INVALID_DIRECT_SOURCE",
            lambda: plan_direct_specified_links_for_batch(
                (), registry, batch_id="batch", configured_direct_links_per_article=1,
                direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
            ),
        )

    def test_invalid_batch_id_hard_fail(self):
        for batch_id in ("", " batch", "batch ", None):
            with self.subTest(batch_id=batch_id):
                self.assert_code("INVALID_DIRECT_PLANNER_CONFIG", lambda batch_id=batch_id: self.plan(batch_id=batch_id))

    def test_selected_identity_is_exact_registry_identity(self):
        registry = self.registry(10)
        entries = {entry.id: entry for entry in registry.entries}
        result = self.plan(source_count=2, configured=5, registry=registry)
        for plan in result.plans:
            for selected in plan.selected_entries:
                entry = entries[selected.entry_id]
                self.assertEqual(
                    (selected.canonical_url, selected.url, selected.anchor, selected.normalized_anchor, selected.approval_source),
                    (entry.canonical_url, entry.url, entry.anchor, entry.normalized_anchor, entry.approval_source),
                )

    def test_result_counts_and_usage_close(self):
        result = self.plan(source_count=10, entry_count=20, configured=2)
        self.assertEqual(result.selected_total, sum(plan.selected_links for plan in result.plans))
        self.assertEqual(result.selected_total, sum(result.entry_usage.values()))
        self.assertTrue(all(plan.requested_links == plan.configured_direct_links_per_article for plan in result.plans))

    def test_no_preflight_or_cluster_model(self):
        fields = set(DirectSourceArticle.__dataclass_fields__)
        self.assertEqual(fields, {"slug"})
        signature = set(inspect.signature(plan_direct_specified_links_for_batch).parameters)
        self.assertNotIn("preflight_results", signature)
        self.assertNotIn("cluster", signature)

    def test_no_network_openai_or_d4_symbols(self):
        import direct_specified_link_planner as module

        source = inspect.getsource(module).lower()
        for forbidden in (
            "requests", "httpx", "socket", "openai", "urlopen", "urllib.request",
            "markdown", "placement", "injectionresult", "auditresult", "pre_sha", "post_sha",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
