from __future__ import annotations

import dataclasses
import inspect
import unittest

from direct_specified_link_injector import (
    NATURAL_ANCHOR,
    VISIBLE_REFERENCE,
    inject_direct_specified_links,
    scan_direct_specified_markdown,
)
from direct_specified_link_planner import DirectSourceArticle, plan_direct_specified_links_for_batch
from direct_specified_link_registry import DirectSpecifiedLinkContractError, build_direct_registry, parse_direct_link_lines


class DirectSpecifiedLinkInjectorTests(unittest.TestCase):
    def assert_code(self, code, callback):
        with self.assertRaises(DirectSpecifiedLinkContractError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def registry(self, count=2, *, same_anchor=False):
        lines = []
        for index in range(count):
            anchor = "同一标题" if same_anchor else f"目标标题 {index}"
            scheme = "http" if index % 2 == 0 else "https"
            url = f"{scheme}://host-{index}.real-domain.tld/Article//Path{index}?x={index}#Part{index}"
            lines.append(f"target-{index:03d}|{url}|{anchor}")
        return build_direct_registry(parse_direct_link_lines(lines, source_filename="approved.txt"))

    def plan(self, registry, slug="new-article", configured=None, batch_id="batch-direct"):
        configured = configured or len(registry.entries)
        result = plan_direct_specified_links_for_batch(
            (DirectSourceArticle(slug),), registry, batch_id=batch_id,
            configured_direct_links_per_article=configured,
            direct_registry_version=registry.direct_registry_version,
            config_version=registry.config_version,
        )
        return result.plans[0]

    def markdown(self, body="正文没有自然目标。", newline="\n", related=True):
        tail = "\n\n## 相关阅读\n\n- [内部](./inside.html)" if related else ""
        value = f"---\ntitle: T\ndescription: D\n---\n\n# T\n\n{{% raw %}}\n\n{body}{tail}\n\n{{% endraw %}}\n"
        return value.replace("\n", newline)

    def inject(self, registry=None, plan=None, markdown=None, slug="new-article", batch_id="batch-direct", protected=()):
        registry = registry or self.registry()
        plan = plan or self.plan(registry, slug=slug, batch_id=batch_id)
        markdown = markdown or self.markdown()
        return inject_direct_specified_links(
            source_slug=slug, markdown=markdown, plan=plan, registry=registry,
            batch_id=batch_id, direct_registry_version=registry.direct_registry_version,
            config_version=registry.config_version, protected_slug_set=protected,
        )

    def test_natural_then_reference(self):
        registry = self.registry(2)
        plan = self.plan(registry)
        natural = plan.selected_entries[0]
        baseline = self.markdown(f"国内要闻包含{natural.anchor}相关内容。")
        outcome = self.inject(registry, plan, baseline)
        types = [entry.placement_type for entry in outcome.result.placed_entries]
        self.assertEqual(types.count(NATURAL_ANCHOR), 1)
        self.assertEqual(types.count(VISIBLE_REFERENCE), 1)
        self.assertIn(f"[{natural.anchor}]({natural.url})", outcome.markdown)

    def test_reference_format_and_before_related(self):
        outcome = self.inject()
        self.assertIn("| 详见 [", outcome.markdown)
        self.assertLess(outcome.markdown.index("| 详见 ["), outcome.markdown.index("## 相关阅读"))

    def test_reference_before_endraw_without_related(self):
        baseline = self.markdown(related=False)
        outcome = self.inject(markdown=baseline)
        self.assertLess(outcome.markdown.index("| 详见 ["), outcome.markdown.index("{% endraw %}"))

    def test_reference_appends_without_raw(self):
        baseline = "# Title\n\n正文。\n"
        outcome = self.inject(markdown=baseline)
        self.assertTrue(outcome.markdown.rstrip().endswith(")"))

    def test_url_semantics_preserved(self):
        registry = self.registry(2)
        outcome = self.inject(registry=registry, plan=self.plan(registry))
        for entry in registry.entries:
            self.assertIn(entry.url, outcome.markdown)
            self.assertIn("//Path", entry.url)
            self.assertIn("?x=", entry.url)
            self.assertIn("#Part", entry.url)

    def test_protected_existing_production(self):
        self.assert_code("EXISTING_PRODUCTION_MUTATION_ATTEMPT", lambda: self.inject(protected={"new-article"}))

    def test_identity_mismatches(self):
        registry = self.registry(2)
        plan = self.plan(registry)
        cases = (
            ("batch", dict(batch_id="wrong")),
            ("slug", dict(slug="wrong")),
        )
        for name, changes in cases:
            with self.subTest(name=name):
                self.assert_code("DIRECT_REGISTRY_VERSION_MISMATCH", lambda changes=changes: self.inject(registry, plan, **changes))

    def test_forged_selected_identity(self):
        registry = self.registry(2)
        plan = self.plan(registry)
        forged_entry = dataclasses.replace(plan.selected_entries[0], url="https://evil.real-domain.tld/")
        forged = dataclasses.replace(plan, selected_entries=(forged_entry, *plan.selected_entries[1:]))
        self.assert_code("UNAPPROVED_DIRECT_URL", lambda: self.inject(registry, forged))

    def test_duplicate_canonical_url_forgery(self):
        registry = self.registry(2)
        plan = self.plan(registry)
        duplicate = dataclasses.replace(plan.selected_entries[1], canonical_url=plan.selected_entries[0].canonical_url)
        forged = dataclasses.replace(plan, selected_entries=(plan.selected_entries[0], duplicate))
        self.assert_code("UNAPPROVED_DIRECT_URL", lambda: self.inject(registry, forged))

    def test_same_anchor_different_urls_allowed(self):
        registry = self.registry(2, same_anchor=True)
        outcome = self.inject(registry, self.plan(registry))
        self.assertEqual(len(outcome.result.placed_entries), 2)

    def test_internal_and_external_links_unchanged(self):
        baseline = self.markdown("正文。[旧外链](https://old.real-domain.tld/)\n\n<a href=\"https://html.real-domain.tld/\">old</a>")
        outcome = self.inject(markdown=baseline)
        for value in ("[旧外链](https://old.real-domain.tld/)", '<a href="https://html.real-domain.tld/">old</a>', "[内部](./inside.html)"):
            self.assertEqual(outcome.markdown.count(value), baseline.count(value))

    def test_scanner_protected_positions_fall_back(self):
        protected_bodies = (
            "## 目标标题 0",
            "```md\n目标标题 0\n```",
            "~~~md\n目标标题 0\n~~~",
            "`目标标题 0`",
            "[目标标题 0](https://old.real-domain.tld/)",
            "![目标标题 0](image.png)",
            "https://host.real-domain.tld/目标标题 0",
            '<span title="目标标题 0">x</span>',
            "<!-- 目标标题 0 -->",
            "{{ 目标标题 0 }}",
        )
        registry = self.registry(1)
        plan = self.plan(registry)
        for body in protected_bodies:
            with self.subTest(body=body):
                outcome = self.inject(registry, plan, self.markdown(body))
                self.assertEqual(outcome.result.placed_entries[0].placement_type, VISIBLE_REFERENCE)

    def test_related_anchor_falls_back_before_related(self):
        registry = self.registry(1)
        plan = self.plan(registry)
        baseline = self.markdown("正文。") .replace("- [内部]", f"- {plan.selected_entries[0].anchor} [内部]")
        outcome = self.inject(registry, plan, baseline)
        self.assertEqual(outcome.result.placed_entries[0].placement_type, VISIBLE_REFERENCE)

    def test_related_liquid_and_comment_lookalikes_inside_fence_are_not_structure(self):
        registry = self.registry(1)
        plan = self.plan(registry)
        body = "```md\n## 相关阅读\n{{ broken\n<!-- open\n目标标题 0\n```\n\n普通正文。"
        outcome = self.inject(registry, plan, self.markdown(body, related=False))
        self.assertEqual(outcome.result.placed_entries[0].placement_type, VISIBLE_REFERENCE)
        self.assertLess(outcome.markdown.index("| 详见 ["), outcome.markdown.index("{% endraw %}"))

    def test_multiple_raw_pairs_fail_closed(self):
        markdown = "{% raw %}\na\n{% endraw %}\n{% raw %}\nb\n{% endraw %}"
        self.assert_code("DIRECT_MARKDOWN_UNSAFE", lambda: self.inject(markdown=markdown))

    def test_malformed_structures_fail_closed(self):
        cases = (
            "---\ntitle: x\n",
            "```md\ncode",
            "<!-- open",
            "{% raw %}\nbody",
            "{% endraw %}",
            "{{ broken",
        )
        for markdown in cases:
            with self.subTest(markdown=markdown):
                self.assert_code("DIRECT_MARKDOWN_UNSAFE", lambda markdown=markdown: self.inject(markdown=markdown))

    def test_lf_and_crlf_preserved(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                baseline = self.markdown(newline=newline)
                outcome = self.inject(markdown=baseline)
                if newline == "\r\n":
                    self.assertEqual(outcome.markdown.count("\n"), outcome.markdown.count("\r\n"))
                else:
                    self.assertNotIn("\r\n", outcome.markdown)

    def test_determinism(self):
        first = self.inject()
        second = self.inject()
        self.assertEqual(first, second)

    def test_quantity_1_2_5_10_20_30(self):
        for count in (1, 2, 5, 10, 20, 30):
            with self.subTest(count=count):
                registry = self.registry(count)
                outcome = self.inject(registry, self.plan(registry, configured=count))
                self.assertEqual(len(outcome.result.placed_entries), count)
                self.assertEqual(outcome.result.status, "PASS")

    def test_planner_shortfall_provenance(self):
        registry = self.registry(1)
        plan = self.plan(registry, configured=2)
        outcome = self.inject(registry, plan)
        self.assertEqual(outcome.result.status, "PASS_WITH_SHORTFALL")
        self.assertIn("PLANNER_SHORTFALL:INSUFFICIENT_UNIQUE_DIRECT_TARGETS", outcome.result.warnings)

    def test_twenty_url_ten_article_simulation(self):
        registry = self.registry(20)
        sources = tuple(DirectSourceArticle(f"source-{index:02d}") for index in range(10))
        batch = plan_direct_specified_links_for_batch(
            sources, registry, batch_id="simulation", configured_direct_links_per_article=2,
            direct_registry_version=registry.direct_registry_version, config_version=registry.config_version,
        )
        natural = reference = placed = 0
        for index, plan in enumerate(batch.plans):
            anchor = plan.selected_entries[0].anchor
            outcome = self.inject(registry, plan, self.markdown(f"正文包含{anchor}。"), slug=plan.source_slug, batch_id="simulation")
            placed += len(outcome.result.placed_entries)
            natural += sum(item.placement_type == NATURAL_ANCHOR for item in outcome.result.placed_entries)
            reference += sum(item.placement_type == VISIBLE_REFERENCE for item in outcome.result.placed_entries)
        self.assertEqual((batch.requested_total, placed, natural, reference), (20, 20, 10, 10))

    def test_placement_offsets_point_to_exact_markup(self):
        outcome = self.inject()
        for item in outcome.result.placed_entries:
            value = outcome.markdown[item.start:item.end]
            if item.placement_type == NATURAL_ANCHOR:
                self.assertEqual(value, f"[{item.anchor}]({item.url})")
            else:
                self.assertEqual(value, f"| 详见 [{item.anchor}]({item.url})")

    def test_scanner_api(self):
        scan = scan_direct_specified_markdown(self.markdown())
        self.assertIsNotNone(scan.related_start)
        self.assertLess(scan.reference_offset, len(self.markdown()))

    def test_no_network_openai_or_d5_symbols(self):
        import direct_specified_link_injector as module

        source = inspect.getsource(module).lower()
        for forbidden in ("requests", "httpx", "socket", "openai", "urlopen", "urllib.request", "auditresult", "batchaudit"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
