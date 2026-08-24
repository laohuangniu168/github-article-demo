from __future__ import annotations

import re
import sys
import unittest
from dataclasses import replace
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from internal_link_injector import inject_links, normalize_anchor, scan_markdown
from internal_link_registry import RegistryEntry, RegistrySnapshot, compute_registry_version
from internal_link_selector import LinkSelectionPlan, SelectedTarget


def registry_entry(slug: str, title: str | None = None, eligible: bool = True) -> RegistryEntry:
    title = title or f"{slug} 主题方法"
    return RegistryEntry(
        slug=slug,
        title=title,
        cluster="content-seo",
        cluster_source="explicit",
        source_batch="production-batch-001.txt",
        markdown_path=f"articles/{slug}.md",
        relative_url=f"./{slug}.html",
        canonical_url=f"https://example.invalid/{slug}.html",
        published=True,
        eligible_as_target=eligible,
    )


def make_registry(count: int = 30) -> RegistrySnapshot:
    entries = tuple(
        registry_entry(f"target-{index:02d}", f"独特主题{index:02d}优化方法")
        for index in range(count)
    )
    batches = (
        "production-batch-001.txt",
        "production-batch-002.txt",
        "production-batch-003.txt",
        "production-batch-004.txt",
    )
    version = compute_registry_version(entries, source_batches=batches)
    return RegistrySnapshot(entries, batches, "1", version)


def make_plan(registry: RegistrySnapshot, count: int = 30, source_slug: str = "new-article") -> LinkSelectionPlan:
    targets = tuple(
        SelectedTarget(
            target_slug=entry.slug,
            target_cluster=entry.cluster,
            relevance_score=60,
            relevance_reasons=("same_cluster:+50",),
            source="frozen_registry",
            same_batch=False,
            inbound_load_before=0,
            inbound_load_after=1,
            deterministic_hash=f"{index:064x}",
        )
        for index, entry in enumerate(registry.entries[:count])
    )
    return LinkSelectionPlan(
        batch_id="batch-5",
        source_slug=source_slug,
        source_cluster="content-seo",
        registry_version=registry.registry_version,
        config_version="config-5",
        configured_max=30,
        selected_targets=targets,
        filtered_candidates=(),
        internal_links=len(targets),
        same_batch_links=0,
        same_batch_ratio=0.0,
        shortfall_reason=None,
        status="PASS",
    )


def article_text(
    registry: RegistrySnapshot,
    *,
    include_summary: bool = True,
    paragraph_targets: int = 21,
) -> str:
    sections = []
    for section in range(7):
        lines = [f"## 章节{section + 1}", ""]
        for offset in range(3):
            index = section * 3 + offset
            if index >= paragraph_targets:
                break
            title = registry.entries[index].title.replace("优化", "").replace("方法", "")
            lines.extend([f"本段自然讨论{title}的实际应用。", ""])
        sections.append("\n".join(lines))
    summary = "## 总结\n\n本文完成总结。\n\n" if include_summary else ""
    return (
        "---\n"
        "title: \"新文章\"\n"
        "description: \"用于安全注入测试的新文章描述。\"\n"
        "---\n\n"
        "# 新文章\n\n"
        "{% raw %}\n\n"
        + "\n".join(sections)
        + "\n"
        + summary
        + "{% endraw %}\n"
    )


class InternalLinkInjectorTests(unittest.TestCase):
    def inject(self, markdown: str, count: int = 30, **kwargs):
        registry = kwargs.get("registry", make_registry())
        plan = kwargs.get("plan", make_plan(registry, count=count))
        return inject_links(
            markdown,
            article_slug=kwargs.get("article_slug", "new-article"),
            plan=plan,
            registry=registry,
            registry_version=kwargs.get("registry_version", registry.registry_version),
            config_version=kwargs.get("config_version", "config-5"),
            batch_id=kwargs.get("batch_id", "batch-5"),
            protected_slugs=kwargs.get("protected_slugs", ()),
        )

    def protected_fixture(self, fragment: str, target_text: str = "独特主题00"):
        registry = make_registry()
        markdown = (
            "---\ntitle: \"独特主题00\"\ndescription: \"描述\"\n---\n\n"
            "# 独特主题00\n\n{% raw %}\n\n## 章节\n\n"
            + fragment
            + "\n\n普通安全段落。\n\n## 总结\n\n结束。\n\n{% endraw %}\n"
        )
        outcome = self.inject(markdown, count=1, registry=registry)
        self.assertIn(target_text, outcome.markdown)
        self.assertNotIn("[独特主题00](./target-00.html)", outcome.markdown)
        return outcome

    def test_front_matter_not_injected(self):
        self.protected_fixture("普通正文。")

    def test_h1_not_injected(self):
        self.protected_fixture("普通正文。")

    def test_h2_heading_not_injected(self):
        self.protected_fixture("普通正文。")

    def test_backtick_fence_not_injected(self):
        self.protected_fixture("```text\n独特主题00\n```")

    def test_tilde_fence_not_injected(self):
        self.protected_fixture("~~~text\n独特主题00\n~~~")

    def test_inline_code_not_injected(self):
        self.protected_fixture("这里是 `独特主题00` 示例。")

    def test_existing_markdown_link_not_injected(self):
        self.protected_fixture("已有 [独特主题00](./old.html) 链接。")

    def test_markdown_image_not_injected(self):
        self.protected_fixture("图片 ![独特主题00](./image.png) 示例。")

    def test_bare_url_not_injected(self):
        self.protected_fixture("地址 https://example.com/独特主题00 结束。")

    def test_html_tag_not_injected(self):
        self.protected_fixture("标签 <span>独特主题00</span> 示例。")

    def test_html_attribute_not_injected(self):
        self.protected_fixture('<a title="独特主题00">普通文字</a>')

    def test_html_comment_not_injected(self):
        self.protected_fixture("<!-- 独特主题00 -->")

    def test_liquid_tag_not_injected(self):
        self.protected_fixture("{{ 独特主题00 }}")

    def test_raw_boundary_not_injected(self):
        self.protected_fixture("普通正文。")

    def test_normal_paragraph_injected(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry), count=1, registry=registry)
        self.assertIn("[独特主题00]", outcome.markdown)

    def test_one_body_link_per_paragraph(self):
        registry = make_registry()
        markdown = article_text(registry, paragraph_targets=1).replace("独特主题00", "独特主题00和独特主题01", 1)
        outcome = self.inject(markdown, count=2, registry=registry)
        body = [placement for placement in outcome.result.placements if placement.placement_type == "body"]
        self.assertEqual(len({placement.paragraph_index for placement in body}), len(body))

    def test_three_body_links_per_h2(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry), registry=registry)
        counts = {}
        for placement in outcome.result.placements:
            if placement.placement_type == "body":
                counts[placement.h2_section] = counts.get(placement.h2_section, 0) + 1
        self.assertLessEqual(max(counts.values()), 3)

    def test_body_target_unique(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry), registry=registry)
        slugs = [placement.target_slug for placement in outcome.result.placements if placement.placement_type == "body"]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_anchor_normalization_unique(self):
        self.assertEqual(normalize_anchor("  Test， "), "test")
        registry = make_registry()
        outcome = self.inject(article_text(registry), registry=registry)
        keys = [normalize_anchor(item.anchor_text) for item in outcome.result.placements]
        self.assertEqual(len(keys), len(set(keys)))

    def test_related_block_generated(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry), registry=registry)
        self.assertEqual(outcome.markdown.count("## 相关阅读"), 1)

    def test_related_before_final_summary(self):
        registry = make_registry()
        output = self.inject(article_text(registry), registry=registry).markdown
        self.assertLess(output.rfind("## 相关阅读"), output.rfind("## 总结"))

    def test_related_before_endraw_without_summary(self):
        registry = make_registry()
        output = self.inject(article_text(registry, include_summary=False), registry=registry).markdown
        self.assertLess(output.rfind("## 相关阅读"), output.rfind("{% endraw %}"))

    def test_related_max_ten(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry, paragraph_targets=0), registry=registry)
        self.assertLessEqual(outcome.result.related_links, 10)

    def test_body_related_targets_do_not_overlap(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry), registry=registry)
        body = {item.target_slug for item in outcome.result.placements if item.placement_type == "body"}
        related = {item.target_slug for item in outcome.result.placements if item.placement_type == "related"}
        self.assertFalse(body & related)

    def test_source_slug_mismatch_fails(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry), registry=registry, article_slug="wrong")
        self.assertEqual((outcome.result.final_status, outcome.result.events[0].code), ("FAIL", "SOURCE_SLUG_MISMATCH"))

    def test_registry_version_mismatch_fails(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry), registry=registry, registry_version="wrong")
        self.assertEqual(outcome.result.events[0].code, "REGISTRY_VERSION_MISMATCH")

    def test_config_version_mismatch_fails(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry), registry=registry, config_version="wrong")
        self.assertEqual(outcome.result.events[0].code, "CONFIG_VERSION_MISMATCH")

    def test_non_registry_target_fails(self):
        registry = make_registry()
        plan = make_plan(registry, 1)
        bad = replace(plan.selected_targets[0], target_slug="missing")
        outcome = self.inject(article_text(registry), registry=registry, plan=replace(plan, selected_targets=(bad,)))
        self.assertEqual(outcome.result.events[0].code, "REGISTRY_TARGET_MISSING")

    def test_self_target_fails(self):
        registry = make_registry()
        plan = make_plan(registry, 1)
        bad = replace(plan.selected_targets[0], target_slug="new-article")
        outcome = self.inject(article_text(registry), registry=registry, plan=replace(plan, selected_targets=(bad,)))
        self.assertEqual(outcome.result.events[0].code, "SELF_LINK_REJECTED")

    def test_duplicate_target_fails(self):
        registry = make_registry()
        plan = make_plan(registry, 2)
        duplicate = replace(plan, selected_targets=(plan.selected_targets[0], plan.selected_targets[0]))
        outcome = self.inject(article_text(registry), registry=registry, plan=duplicate)
        self.assertEqual(outcome.result.events[0].code, "DUPLICATE_TARGET_REJECTED")

    def test_old_production_mutation_fails(self):
        registry = make_registry()
        plan = make_plan(registry, 1, source_slug="old-article")
        outcome = self.inject(article_text(registry), registry=registry, plan=plan, article_slug="old-article", protected_slugs={"old-article"})
        self.assertEqual(outcome.result.events[0].code, "EXISTING_PRODUCTION_MUTATION_ATTEMPT")

    def test_deterministic(self):
        registry = make_registry()
        markdown = article_text(registry)
        self.assertEqual(self.inject(markdown, registry=registry), self.inject(markdown, registry=registry))

    def test_original_text_preserved_except_links_and_related(self):
        registry = make_registry()
        markdown = article_text(registry)
        outcome = self.inject(markdown, registry=registry)
        stripped = re.sub(r"\[([^\]]+)\]\(\./[a-z0-9-]+\.html\)", r"\1", outcome.markdown)
        stripped = re.sub(r"## 相关阅读\n\n(?:- .*\n)+\n", "", stripped)
        self.assertEqual(stripped, markdown)

    def test_injected_markdown_scans(self):
        registry = make_registry()
        scan_markdown(self.inject(article_text(registry), registry=registry).markdown)

    def test_raw_boundaries_unchanged(self):
        registry = make_registry()
        markdown = article_text(registry)
        output = self.inject(markdown, registry=registry).markdown
        self.assertEqual((output.count("{% raw %}"), output.count("{% endraw %}")), (1, 1))
        self.assertLess(output.index("{% raw %}"), output.index("{% endraw %}"))

    def test_no_body_anchor_moves_to_related(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry, paragraph_targets=0), count=5, registry=registry)
        self.assertEqual((outcome.result.body_links, outcome.result.related_links), (0, 5))

    def test_related_full_records_no_safe_point(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry, paragraph_targets=0), registry=registry)
        self.assertEqual(outcome.result.related_links, 10)
        self.assertIn("NO_SAFE_INJECTION_POINT", {event.code for event in outcome.result.events})

    def test_shortfall_reason_is_safe_points_only(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry, paragraph_targets=0), registry=registry)
        self.assertEqual(outcome.result.final_status, "PASS_WITH_SHORTFALL")
        self.assertIn("INSUFFICIENT_SAFE_INJECTION_POINTS", outcome.result.warnings)


if __name__ == "__main__":
    unittest.main()
