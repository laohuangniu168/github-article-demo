from __future__ import annotations

import re
import unittest
from dataclasses import replace
from pathlib import Path

from digest_planner import (
    DEFAULT_LINKS_PER_DIGEST,
    MAX_DIGEST_ENTRIES,
    MIN_DIGEST_ENTRIES,
    DigestPlannerError,
    plan_digest_articles,
)
from digest_registry import DIGEST_CONFIG_VERSION, build_digest_registry, parse_digest_lines


def make_registry(count: int, *, reverse: bool = False, prefix_blanks: int = 0, source: str = "input.txt"):
    lines = [f"https://example.com/item/{index:04d}|Title {index:04d}" for index in range(count)]
    if reverse:
        lines.reverse()
    text = "\n" * prefix_blanks + "\n".join(lines)
    return build_digest_registry(parse_digest_lines(text, source_filename=source))


def plan(registry, **kwargs):
    return plan_digest_articles(
        registry,
        batch_id=kwargs.pop("batch_id", "digest-batch-001"),
        digest_registry_version=kwargs.pop("digest_registry_version", registry.digest_registry_version),
        config_version=kwargs.pop("config_version", DIGEST_CONFIG_VERSION),
        **kwargs,
    )


class DigestPlannerTests(unittest.TestCase):
    def assert_code(self, code: str, registry=None, **kwargs):
        registry = registry or make_registry(20)
        with self.assertRaises(DigestPlannerError) as caught:
            plan(registry, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def test_constants(self):
        self.assertEqual((20, 150, 50), (MIN_DIGEST_ENTRIES, MAX_DIGEST_ENTRIES, DEFAULT_LINKS_PER_DIGEST))

    def test_20_default(self):
        self.assertEqual((20,), plan(make_registry(20)).distribution)

    def test_21_default(self):
        self.assertEqual((21,), plan(make_registry(21)).distribution)

    def test_49_default(self):
        self.assertEqual((49,), plan(make_registry(49)).distribution)

    def test_50_default(self):
        self.assertEqual((50,), plan(make_registry(50)).distribution)

    def test_51_default(self):
        self.assertEqual((51,), plan(make_registry(51)).distribution)

    def test_60_default(self):
        self.assertEqual((60,), plan(make_registry(60)).distribution)

    def test_80_default(self):
        self.assertEqual((80,), plan(make_registry(80)).distribution)

    def test_99_default(self):
        self.assertEqual((99,), plan(make_registry(99)).distribution)

    def test_100_default(self):
        self.assertEqual((100,), plan(make_registry(100)).distribution)

    def test_101_default(self):
        self.assertEqual((101,), plan(make_registry(101)).distribution)

    def test_149_default(self):
        self.assertEqual((149,), plan(make_registry(149)).distribution)

    def test_150_default(self):
        self.assertEqual((150,), plan(make_registry(150)).distribution)

    def test_151_default_rebalanced(self):
        self.assertEqual((38, 38, 38, 37), plan(make_registry(151)).distribution)

    def test_200_default(self):
        self.assertEqual((50, 50, 50, 50), plan(make_registry(200)).distribution)

    def test_500_default(self):
        self.assertEqual((50,) * 10, plan(make_registry(500)).distribution)

    def test_explicit_links_20(self):
        self.assertEqual((20, 20, 20, 20), plan(make_registry(80), links_per_digest=20).distribution)

    def test_explicit_links_21_rebalances_small_tail(self):
        self.assertEqual((20, 20, 20, 20), plan(make_registry(80), links_per_digest=21).distribution)

    def test_explicit_links_50_normal_tail(self):
        self.assertEqual((50, 50, 20), plan(make_registry(120), links_per_digest=50).distribution)

    def test_explicit_links_50_small_tail_rebalanced(self):
        self.assertEqual((35, 35, 35), plan(make_registry(105), links_per_digest=50).distribution)

    def test_explicit_links_100_single_digest(self):
        result = plan(make_registry(100), links_per_digest=100)
        self.assertEqual((100,), result.distribution)

    def test_explicit_links_149(self):
        self.assertEqual((149, 20), plan(make_registry(169), links_per_digest=149).distribution)

    def test_explicit_links_150(self):
        self.assertEqual((150, 20), plan(make_registry(170), links_per_digest=150).distribution)

    def test_digest_count_1(self):
        self.assertEqual((100,), plan(make_registry(100), digest_count=1).distribution)

    def test_digest_count_2_even(self):
        self.assertEqual((50, 50), plan(make_registry(100), digest_count=2).distribution)

    def test_digest_count_2_odd(self):
        self.assertEqual((51, 50), plan(make_registry(101), digest_count=2).distribution)

    def test_digest_count_3(self):
        self.assertEqual((34, 33, 33), plan(make_registry(100), digest_count=3).distribution)

    def test_digest_count_5(self):
        self.assertEqual((20,) * 5, plan(make_registry(100), digest_count=5).distribution)

    def test_digest_count_10(self):
        self.assertEqual((50,) * 10, plan(make_registry(500), digest_count=10).distribution)

    def test_less_than_20_fails(self):
        self.assert_code("INSUFFICIENT_DIGEST_ENTRIES", make_registry(19))

    def test_links_19_fails(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", links_per_digest=19)

    def test_links_151_fails(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", links_per_digest=151)

    def test_links_bool_fails(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", links_per_digest=True)

    def test_links_float_fails(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", links_per_digest=50.0)

    def test_digest_count_zero_fails(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", digest_count=0)

    def test_digest_count_bool_fails(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", digest_count=True)

    def test_digest_count_too_high_fails(self):
        self.assert_code("DIGEST_DISTRIBUTION_IMPOSSIBLE", make_registry(100), digest_count=6)

    def test_digest_count_too_low_for_max_fails(self):
        self.assert_code("DIGEST_DISTRIBUTION_IMPOSSIBLE", make_registry(500), digest_count=2)

    def test_parameters_mutually_exclusive(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", links_per_digest=50, digest_count=2)

    def test_registry_version_argument_mismatch(self):
        self.assert_code("DIGEST_REGISTRY_VERSION_MISMATCH", digest_registry_version="dgr1:" + "0" * 64)

    def test_config_version_mismatch(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", config_version="wrong")

    def test_empty_batch_id_fails(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", batch_id="")

    def test_batch_id_outer_space_fails(self):
        self.assert_code("INVALID_DIGEST_PLANNER_CONFIG", batch_id=" bad ")

    def test_result_counts_and_status(self):
        result = plan(make_registry(120), links_per_digest=50)
        self.assertEqual((120, 120, 3, "PASS"), (result.registry_entry_count, result.planned_entry_count, result.digest_count, result.final_status))

    def test_complete_unique_coverage(self):
        registry = make_registry(151)
        result = plan(registry)
        planned = [entry_id for article in result.plans for entry_id in article.entry_ids]
        self.assertEqual(len(registry.entries), len(planned))
        self.assertEqual(len(planned), len(set(planned)))
        self.assertEqual({entry.id for entry in registry.entries}, set(planned))

    def test_digest_indices_and_ids(self):
        result = plan(make_registry(200))
        self.assertEqual([1, 2, 3, 4], [p.digest_index for p in result.plans])
        self.assertEqual(["digest-001", "digest-002", "digest-003", "digest-004"], [p.digest_id for p in result.plans])

    def test_filename_contract(self):
        result = plan(make_registry(200))
        for article in result.plans:
            self.assertRegex(article.filename, r"^digest-[0-9a-f]{8}-[0-9]{3}\.md$")

    def test_filename_same_batch_is_stable(self):
        registry = make_registry(100)
        self.assertEqual(plan(registry).plans[0].filename, plan(registry).plans[0].filename)

    def test_batch_id_changes_filename(self):
        registry = make_registry(100)
        self.assertNotEqual(plan(registry, batch_id="batch-a").plans[0].filename, plan(registry, batch_id="batch-b").plans[0].filename)

    def test_plan_hash_format(self):
        self.assertRegex(plan(make_registry(50)).plans[0].plan_hash, r"^[0-9a-f]{64}$")

    def test_plan_hash_deterministic(self):
        registry = make_registry(50)
        self.assertEqual(plan(registry).plans[0].plan_hash, plan(registry).plans[0].plan_hash)

    def test_batch_id_changes_plan_hash(self):
        registry = make_registry(50)
        self.assertNotEqual(plan(registry, batch_id="batch-a").plans[0].plan_hash, plan(registry, batch_id="batch-b").plans[0].plan_hash)

    def test_registry_change_changes_plan_hash(self):
        self.assertNotEqual(plan(make_registry(50)).plans[0].plan_hash, plan(make_registry(51)).plans[0].plan_hash)

    def test_assignment_change_changes_plan_hash(self):
        registry = make_registry(100)
        self.assertNotEqual(plan(registry, links_per_digest=100).plans[0].plan_hash, plan(registry, links_per_digest=50).plans[0].plan_hash)

    def test_input_order_reorder_mapping_unchanged(self):
        left = plan(make_registry(100, reverse=False))
        right = plan(make_registry(100, reverse=True))
        self.assertEqual(left, right)

    def test_registry_entries_reorder_mapping_unchanged(self):
        registry = make_registry(100)
        reordered = replace(registry, entries=tuple(reversed(registry.entries)))
        self.assertEqual(plan(registry), plan(reordered))

    def test_source_filename_change_mapping_unchanged(self):
        self.assertEqual(plan(make_registry(100, source="a.txt")), plan(make_registry(100, source="b.txt")))

    def test_source_line_change_mapping_unchanged(self):
        self.assertEqual(plan(make_registry(100, prefix_blanks=0)), plan(make_registry(100, prefix_blanks=3)))

    def test_registry_duplicate_guard(self):
        registry = make_registry(20)
        duplicate = replace(registry, entries=registry.entries + (registry.entries[0],))
        self.assert_code("DIGEST_ENTRY_DUPLICATION", duplicate)

    def test_registry_payload_version_guard(self):
        registry = make_registry(20)
        changed = replace(registry, entries=(replace(registry.entries[0], title="Changed"),) + registry.entries[1:])
        self.assert_code("DIGEST_REGISTRY_VERSION_MISMATCH", changed)

    def test_all_plan_entry_counts_match_arrays(self):
        result = plan(make_registry(151))
        for article in result.plans:
            self.assertEqual(article.entry_count, len(article.entry_ids))
            self.assertEqual(article.entry_count, len(article.entry_identities))

    def test_no_forbidden_runtime_dependencies_or_fields(self):
        source = Path(__file__).with_name("digest_planner.py").read_text(encoding="utf-8")
        forbidden = (
            "requests", "urllib.request", "http.client", "socket", "httpx", "aiohttp", "openai",
            "random", "uuid", "time.time", "datetime.now", "section", "summary", "markdown", "href",
            "internal_link", "direct_link", "cluster", "preflight", "http_status",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source.casefold())


if __name__ == "__main__":
    unittest.main()
