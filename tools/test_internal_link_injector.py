from __future__ import annotations

import re
import sys
import unittest
from dataclasses import replace
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from internal_link_injector import (
    BatchExtensionEntry,
    BatchRegistryExtension,
    compute_batch_extension_version,
    inject_links,
    normalize_anchor,
    scan_markdown,
)
from internal_link_registry import CANONICAL_BASE, RegistryEntry, RegistrySnapshot, compute_registry_version
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


def extension_entry(slug: str = "batch-target", **changes) -> BatchExtensionEntry:
    values = dict(
        slug=slug,
        title="批次目标内容优化指南",
        cluster="content-seo",
        batch_id="batch-5",
        markdown_path=f"articles/{slug}.md",
        relative_url=f"./{slug}.html",
        canonical_url=f"{CANONICAL_BASE}{slug}.html",
        quality_status="PASS",
        published=True,
        eligible_as_target=True,
    )
    values.update(changes)
    return BatchExtensionEntry(**values)


def make_extension(entries: tuple[BatchExtensionEntry, ...] | None = None, **changes) -> BatchRegistryExtension:
    entries = entries or (extension_entry(),)
    values = dict(entries=entries, batch_id="batch-5", extension_version=compute_batch_extension_version(entries))
    values.update(changes)
    return BatchRegistryExtension(**values)


def extension_plan(registry: RegistrySnapshot, *, mixed: bool = False, target_slug: str = "batch-target", source: str = "batch_registry_extension") -> LinkSelectionPlan:
    selected = []
    if mixed:
        selected.extend(
            SelectedTarget(entry.slug, "content-seo", 60, ("same_cluster:+50",), "frozen_registry", False, 0, 1, f"{index:064x}")
            for index, entry in enumerate(registry.entries[:3])
        )
    selected.append(SelectedTarget(target_slug, "content-seo", 60, ("same_cluster:+50",), source, True, 0, 1, "1" * 64))
    return replace(make_plan(registry, count=0), selected_targets=tuple(selected), internal_links=len(selected), same_batch_links=1)


def cap_case(registry: RegistrySnapshot, *, actual_total: int, same_batch: int, same_batch_in_body: bool = False):
    extension_entries = tuple(
        extension_entry(f"batch-target-{index:02d}", title=f"批次独特主题{index:02d}方法")
        for index in range(same_batch)
    )
    extension = make_extension(extension_entries)
    body_count = actual_total - 10
    frozen_targets = list(registry.entries[:15])
    body_frozen = frozen_targets[:body_count]
    selected = []
    body_lines = []
    if same_batch_in_body:
        body_batch = extension_entries[:1]
        body_frozen = frozen_targets[: max(0, body_count - len(body_batch))]
        body_entries = list(body_batch) + body_frozen
    else:
        body_entries = body_frozen
    for index, entry in enumerate(body_entries):
        is_batch = isinstance(entry, BatchExtensionEntry)
        selected.append(
            SelectedTarget(
                entry.slug, entry.cluster, 60, ("same_cluster:+50",),
                "batch_registry_extension" if is_batch else "frozen_registry",
                is_batch, 0, 1, f"{index + 1:064x}",
            )
        )
        body_lines.extend([f"## 正文{index + 1}", "", f"这里自然讨论{entry.title}的实际应用。", ""])
    already_batch = sum(item.same_batch for item in selected)
    for index, entry in enumerate(extension_entries[already_batch:], start=len(selected)):
        selected.append(SelectedTarget(entry.slug, entry.cluster, 60, ("same_cluster:+50",), "batch_registry_extension", True, 0, 1, f"{index + 1:064x}"))
    used_frozen = {item.target_slug for item in selected if not item.same_batch}
    for entry in frozen_targets:
        if entry.slug in used_frozen:
            continue
        index = len(selected)
        selected.append(SelectedTarget(entry.slug, entry.cluster, 60, ("same_cluster:+50",), "frozen_registry", False, 0, 1, f"{index + 1:064x}"))
        if len(selected) == 20:
            break
    plan = replace(
        make_plan(registry, count=0),
        selected_targets=tuple(selected),
        internal_links=len(selected),
        same_batch_links=sum(item.same_batch for item in selected),
        same_batch_ratio=sum(item.same_batch for item in selected) / len(selected),
    )
    markdown = (
        '---\ntitle: "新文章"\ndescription: "用于最终比例修复测试。"\n---\n\n'
        '# 新文章\n\n{% raw %}\n\n' + "\n".join(body_lines)
        + '## 总结\n\n结束。\n\n{% endraw %}\n'
    )
    return markdown, plan, extension


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
            batch_extension=kwargs.get("batch_extension"),
            extension_version=kwargs.get("extension_version"),
            file_exists=kwargs.get("file_exists"),
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

    def extension_inject(self, *, extension=None, plan=None, registry=None, **kwargs):
        registry = registry or make_registry()
        extension = extension if extension is not None else make_extension()
        plan = plan or extension_plan(registry)
        return self.inject(
            article_text(registry, paragraph_targets=0),
            registry=registry,
            plan=plan,
            batch_extension=extension,
            extension_version=kwargs.pop("extension_version", extension.extension_version if extension else None),
            file_exists=kwargs.pop("file_exists", lambda _: True),
            **kwargs,
        )

    def test_batch_extension_target_injects(self):
        registry = make_registry()
        outcome = self.extension_inject(registry=registry, plan=extension_plan(registry, mixed=True))
        self.assertNotEqual(outcome.result.final_status, "FAIL")
        self.assertIn("./batch-target.html", outcome.markdown)

    def test_frozen_and_batch_targets_inject(self):
        registry = make_registry()
        outcome = self.extension_inject(registry=registry, plan=extension_plan(registry, mixed=True))
        self.assertEqual(outcome.result.requested_targets, 4)
        self.assertIn("./target-00.html", outcome.markdown)
        self.assertIn("./batch-target.html", outcome.markdown)

    def test_extension_required(self):
        registry = make_registry()
        outcome = self.inject(article_text(registry), registry=registry, plan=extension_plan(registry))
        self.assertEqual(outcome.result.events[0].code, "BATCH_EXTENSION_REQUIRED")

    def test_extension_target_missing(self):
        registry = make_registry()
        empty = make_extension((extension_entry("other-target"),))
        outcome = self.extension_inject(registry=registry, extension=empty, plan=extension_plan(registry))
        self.assertEqual(outcome.result.events[0].code, "BATCH_EXTENSION_TARGET_MISSING")

    def test_extension_version_mismatch(self):
        outcome = self.extension_inject(extension_version="ilx1:wrong")
        self.assertEqual(outcome.result.events[0].code, "BATCH_EXTENSION_VERSION_MISMATCH")

    def test_extension_batch_id_mismatch(self):
        extension = make_extension(batch_id="other-batch")
        outcome = self.extension_inject(extension=extension)
        self.assertEqual(outcome.result.events[0].code, "BATCH_ID_MISMATCH")

    def test_extension_source_mismatch(self):
        registry = make_registry()
        plan = extension_plan(registry, source="frozen_registry")
        outcome = self.extension_inject(registry=registry, plan=plan)
        self.assertEqual(outcome.result.events[0].code, "TARGET_SOURCE_MISMATCH")

    def test_frozen_source_mismatch(self):
        registry = make_registry()
        plan = extension_plan(registry, target_slug="target-00")
        outcome = self.extension_inject(registry=registry, plan=plan)
        self.assertEqual(outcome.result.events[0].code, "TARGET_SOURCE_MISMATCH")

    def test_batch_quality_must_pass(self):
        entry = extension_entry(quality_status="FAIL")
        outcome = self.extension_inject(extension=make_extension((entry,)))
        self.assertEqual(outcome.result.events[0].code, "BATCH_TARGET_QUALITY_NOT_PASS")

    def test_batch_target_must_be_eligible(self):
        entry = extension_entry(eligible_as_target=False)
        outcome = self.extension_inject(extension=make_extension((entry,)))
        self.assertEqual(outcome.result.events[0].code, "REGISTRY_TARGET_INELIGIBLE")

    def test_batch_relative_url_must_be_standard(self):
        entry = extension_entry(relative_url="../batch-target.html")
        outcome = self.extension_inject(extension=make_extension((entry,)))
        self.assertEqual(outcome.result.events[0].code, "REGISTRY_TARGET_INELIGIBLE")

    def test_batch_markdown_must_exist(self):
        outcome = self.extension_inject(file_exists=lambda _: False)
        self.assertEqual(outcome.result.events[0].code, "BATCH_EXTENSION_TARGET_MISSING")

    def test_extension_does_not_pollute_frozen_registry(self):
        registry = make_registry()
        before = registry.entries
        self.extension_inject(registry=registry)
        self.assertEqual(registry.entries, before)
        self.assertNotIn("batch-target", {entry.slug for entry in registry.entries})

    def test_extension_injection_is_deterministic(self):
        self.assertEqual(self.extension_inject(), self.extension_inject())

    def cap_outcome(self, actual_total: int, same_batch: int, *, same_batch_in_body: bool = False):
        registry = make_registry()
        markdown, plan, extension = cap_case(
            registry,
            actual_total=actual_total,
            same_batch=same_batch,
            same_batch_in_body=same_batch_in_body,
        )
        outcome = self.inject(
            markdown,
            registry=registry,
            plan=plan,
            batch_extension=extension,
            extension_version=extension.extension_version,
            file_exists=lambda _: True,
        )
        selected = {item.target_slug: item for item in plan.selected_targets}
        actual_same = sum(selected[item.target_slug].same_batch for item in outcome.result.placements)
        return markdown, outcome, actual_same

    def test_post_placement_ratio_within_cap_is_unchanged(self):
        _, outcome, same = self.cap_outcome(12, 4)
        self.assertEqual((len(outcome.result.placements), same), (12, 4))
        self.assertNotIn("SAME_BATCH_LIMIT_REACHED", {event.code for event in outcome.result.events})

    def test_post_placement_five_of_twelve_removes_minimum(self):
        _, outcome, same = self.cap_outcome(12, 5)
        self.assertEqual((len(outcome.result.placements), same), (10, 3))
        removed = [item for item in outcome.result.skipped_targets if item.reason == "SAME_BATCH_LIMIT_REACHED"]
        self.assertEqual(len(removed), 2)

    def test_post_placement_five_of_fourteen_removes_minimum(self):
        _, outcome, same = self.cap_outcome(14, 5)
        self.assertEqual((len(outcome.result.placements), same), (13, 4))
        self.assertLessEqual(same * 100, len(outcome.result.placements) * 35)

    def test_post_placement_four_of_twelve_needs_no_removal(self):
        _, outcome, same = self.cap_outcome(12, 4)
        self.assertEqual((len(outcome.result.placements), same), (12, 4))

    def test_post_placement_rebalance_is_deterministic(self):
        self.assertEqual(self.cap_outcome(12, 5), self.cap_outcome(12, 5))

    def test_post_placement_related_is_removed_before_body(self):
        _, outcome, _ = self.cap_outcome(12, 5, same_batch_in_body=True)
        removed = {
            event.target_slug
            for event in outcome.result.events
            if event.code == "SAME_BATCH_LIMIT_REACHED"
        }
        body_same = next(
            item.target_slug
            for item in outcome.result.placements
            if item.placement_type == "body" and item.target_slug.startswith("batch-target-")
        )
        self.assertNotIn(body_same, removed)

    def test_post_placement_body_removal_restores_literal_text(self):
        registry = make_registry()
        long_entries = tuple(replace(entry, title=f"无法用于相关阅读的超长标题{index:02d}" + "超长" * 20) for index, entry in enumerate(registry.entries))
        registry = RegistrySnapshot(
            long_entries,
            registry.source_batches,
            registry.registry_schema_version,
            compute_registry_version(long_entries, source_batches=registry.source_batches),
        )
        extension_entries = tuple(extension_entry(f"batch-target-{index:02d}", title=f"批次正文主题{index:02d}") for index in range(5))
        extension = make_extension(extension_entries)
        selected = [
            SelectedTarget(entry.slug, entry.cluster, 60, ("same_cluster:+50",), "batch_registry_extension", True, 0, 1, f"{index:064x}")
            for index, entry in enumerate(extension_entries)
        ]
        selected.extend(
            SelectedTarget(entry.slug, entry.cluster, 60, ("same_cluster:+50",), "frozen_registry", False, 0, 1, f"{index + 5:064x}")
            for index, entry in enumerate(registry.entries[:15])
        )
        plan = replace(make_plan(registry, 0), selected_targets=tuple(selected), internal_links=20, same_batch_links=5, same_batch_ratio=.25)
        paragraphs = "\n\n".join(f"## 章节{index}\n\n这里自然讨论{entry.title}的应用。" for index, entry in enumerate(extension_entries))
        markdown = f'---\ntitle: "新文章"\n---\n\n# 新文章\n\n{{% raw %}}\n\n{paragraphs}\n\n## 总结\n\n结束。\n\n{{% endraw %}}\n'
        outcome = self.inject(markdown, registry=registry, plan=plan, batch_extension=extension, extension_version=extension.extension_version, file_exists=lambda _: True)
        removed_body = [event for event in outcome.result.events if event.code == "SAME_BATCH_LIMIT_REACHED"]
        stripped = re.sub(r"\[([^\]]+)\]\(\./[a-z0-9-]+\.html\)", r"\1", outcome.markdown)
        stripped = re.sub(r"## 相关阅读\n\n(?:- .*\n)+\n", "", stripped)
        self.assertEqual(stripped, markdown)
        self.assertTrue(removed_body)
        self.assertTrue(all(event.stage == "post_placement_rebalance" for event in removed_body))

    def test_post_placement_related_removal_keeps_list_valid(self):
        _, outcome, _ = self.cap_outcome(12, 5)
        self.assertEqual(outcome.markdown.count("## 相关阅读"), 1)
        self.assertNotRegex(outcome.markdown, r"## 相关阅读\n\n\n")
        scan_markdown(outcome.markdown)

    def test_post_placement_shortfall_has_real_provenance(self):
        _, outcome, same = self.cap_outcome(12, 5)
        self.assertEqual(outcome.result.final_status, "PASS_WITH_SHORTFALL")
        self.assertIn("SAME_BATCH_LIMIT_REACHED", outcome.result.warnings)
        self.assertLessEqual(same * 100, len(outcome.result.placements) * 35)

    def test_post_placement_rebalance_introduces_no_invalid_links(self):
        _, outcome, _ = self.cap_outcome(12, 5)
        targets = [item.target_slug for item in outcome.result.placements]
        self.assertEqual(len(targets), len(set(targets)))
        self.assertNotIn("new-article", targets)
        self.assertFalse(any(event.code in {"MALFORMED_MARKDOWN", "PROTECTED_ZONE_VIOLATION"} for event in outcome.result.events))


if __name__ == "__main__":
    unittest.main()
