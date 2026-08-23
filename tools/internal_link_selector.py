from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from article_spec import ArticleSpec, CLUSTERS, SLUG_PATTERN
from internal_link_registry import (
    PROJECT_ROOT,
    RegistryEntry,
    RegistrySnapshot,
    compute_registry_version,
)


MIN_RELEVANCE_SCORE = 40
DEFAULT_CONFIGURED_MAX = 30
MIN_CONFIGURED_MAX = 20
MAX_CONFIGURED_MAX = 50
SAME_BATCH_MAX_PERCENT = 35
TOPIC_TERMS_VERSION = "1"
RELATIONSHIPS_VERSION = "1"

STOP_TERMS = frozenset(
    {
        "seo",
        "website",
        "site",
        "guide",
        "method",
        "optimization",
        "完整",
        "方法",
        "指南",
        "实战",
        "优化",
        "网站",
    }
)

CONTROLLED_TOPIC_TERMS: Mapping[str, tuple[str, ...]] = {
    "crawl": ("crawl", "crawler", "crawling", "蜘蛛", "抓取"),
    "log-analysis": ("log-analysis", "日志分析", "日志验证"),
    "indexing": ("indexing", "index-", "收录"),
    "sitemap": ("sitemap", "网站地图"),
    "diagnosis": ("diagnosis", "诊断"),
    "troubleshooting": ("troubleshooting", "排查"),
    "fix": ("fix", "repair", "修复", "解决"),
    "problem": ("problem", "error", "异常", "问题"),
    "keyword-research": ("keyword-research", "关键词研究", "关键词挖掘"),
    "keyword-mapping": ("keyword-mapping", "关键词与页面映射", "关键词目标页面"),
    "keyword": ("keyword", "关键词", "长尾词"),
    "content-audit": ("content-audit", "内容审计"),
    "content-pruning": ("content-pruning", "内容清理", "低价值内容"),
    "content": ("content", "内容", "文章"),
    "migration": ("migration", "迁移", "改版"),
    "redirect": ("redirect", "重定向", "301"),
    "http-404": ("404", "soft-404"),
    "status-code": ("status-code", "状态码", "5xx"),
    "internal-link": ("internal-link", "internal-links", "内链", "锚文本"),
    "orphan-page": ("orphan-page", "孤立页面"),
    "architecture": ("architecture", "structure", "hierarchy", "架构", "结构", "层级"),
    "navigation": ("navigation", "导航", "面包屑"),
    "canonical": ("canonical", "规范化"),
    "robots": ("robots", "noindex", "nofollow"),
    "performance": ("performance", "speed", "性能", "速度", "响应时间"),
}

COMPLEMENTARY_INTENTS = frozenset(
    {
        frozenset(("diagnosis", "fix")),
        frozenset(("problem", "troubleshooting")),
        frozenset(("crawl", "log-analysis")),
        frozenset(("indexing", "sitemap")),
        frozenset(("keyword-research", "keyword-mapping")),
        frozenset(("content-audit", "content-pruning")),
        frozenset(("migration", "redirect")),
        frozenset(("http-404", "status-code")),
        frozenset(("internal-link", "orphan-page")),
    }
)

CROSS_CLUSTER_RELATIONSHIPS = frozenset(
    {
        frozenset(("baidu-crawl", "baidu-indexing")),
        frozenset(("baidu-seo", "keyword-research")),
        frozenset(("baidu-seo", "content-seo")),
        frozenset(("technical-seo", "site-architecture")),
        frozenset(("site-architecture", "internal-linking")),
        frozenset(("content-seo", "internal-linking")),
    }
)


@dataclass(frozen=True)
class BatchRegistryEntry:
    slug: str
    title: str
    cluster: str
    markdown_path: str
    published: bool = True
    eligible_as_target: bool = True
    content_quality_pass: bool = True


@dataclass(frozen=True)
class TargetRecord:
    slug: str
    title: str
    cluster: str
    markdown_path: str
    published: bool
    eligible_as_target: bool
    content_quality_pass: bool
    source: str
    same_batch: bool


@dataclass(frozen=True)
class FilterEvent:
    code: str
    source_slug: str
    target_slug: str
    stage: str
    message: str


@dataclass(frozen=True)
class Candidate:
    target_slug: str
    target_cluster: str
    relevance_score: int
    relevance_reasons: tuple[str, ...]
    source: str
    same_batch: bool
    current_inbound_load: int
    deterministic_hash: str


@dataclass(frozen=True)
class SelectedTarget:
    target_slug: str
    target_cluster: str
    relevance_score: int
    relevance_reasons: tuple[str, ...]
    source: str
    same_batch: bool
    inbound_load_before: int
    inbound_load_after: int
    deterministic_hash: str


@dataclass(frozen=True)
class LinkSelectionPlan:
    batch_id: str
    source_slug: str
    source_cluster: str
    registry_version: str
    config_version: str
    configured_max: int
    selected_targets: tuple[SelectedTarget, ...]
    filtered_candidates: tuple[FilterEvent, ...]
    internal_links: int
    same_batch_links: int
    same_batch_ratio: float
    shortfall_reason: str | None
    status: str


@dataclass(frozen=True)
class BatchSelectionResult:
    plans: tuple[LinkSelectionPlan, ...]
    inbound_loads: Mapping[str, int]
    inbound_cap: int


class SelectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def calculate_inbound_cap(batch_size: int) -> int:
    if batch_size <= 0:
        raise SelectionError("INVALID_BATCH_SIZE", "batch_size 必须大于 0")
    return max(2, math.ceil(batch_size * 0.20))


def extract_topic_terms(slug: str, title: str) -> frozenset[str]:
    value = f"{slug.casefold()}\n{title.casefold()}"
    return frozenset(
        topic
        for topic, aliases in CONTROLLED_TOPIC_TERMS.items()
        if any(alias.casefold() in value for alias in aliases)
    )


def score_relevance(
    source: ArticleSpec,
    target: TargetRecord,
) -> tuple[int, tuple[str, ...]]:
    score = 0
    reasons: list[str] = []
    source_terms = extract_topic_terms(source.slug, source.title)
    target_terms = extract_topic_terms(target.slug, target.title)

    if source.cluster == target.cluster and source.cluster != "unclassified":
        score += 50
        reasons.append("same_cluster:+50")

    shared_terms = sorted(source_terms & target_terms)
    topic_points = min(len(shared_terms) * 10, 30)
    if topic_points:
        score += topic_points
        reasons.append(f"shared_terms:{','.join(shared_terms)}:+{topic_points}")

    complementary = any(
        (
            left in source_terms
            and right not in source_terms
            and right in target_terms
            and left not in target_terms
        )
        or (
            right in source_terms
            and left not in source_terms
            and left in target_terms
            and right not in target_terms
        )
        for left, right in (tuple(pair) for pair in COMPLEMENTARY_INTENTS)
    )
    if complementary:
        score += 15
        reasons.append("complementary_intent:+15")

    relationship = frozenset((source.cluster, target.cluster))
    if source.cluster != target.cluster and relationship in CROSS_CLUSTER_RELATIONSHIPS:
        score += 10
        reasons.append("allowed_cross_cluster:+10")

    return min(score, 100), tuple(reasons)


def candidate_hash(
    batch_id: str,
    source_slug: str,
    registry_version: str,
    config_version: str,
    target_slug: str,
) -> str:
    seed_material = "\n".join(
        (batch_id, source_slug, registry_version, config_version, target_slug)
    )
    return hashlib.sha256(seed_material.encode("utf-8")).hexdigest()


def _target_records(
    snapshot: RegistrySnapshot,
    batch_extension: Sequence[BatchRegistryEntry],
    batch_source_slugs: set[str],
) -> list[TargetRecord]:
    records = [
        TargetRecord(
            slug=entry.slug,
            title=entry.title,
            cluster=entry.cluster,
            markdown_path=entry.markdown_path,
            published=entry.published,
            eligible_as_target=entry.eligible_as_target,
            content_quality_pass=True,
            source="frozen_registry",
            same_batch=entry.slug in batch_source_slugs,
        )
        for entry in snapshot.entries
    ]
    records.extend(
        TargetRecord(
            slug=entry.slug,
            title=entry.title,
            cluster=entry.cluster,
            markdown_path=entry.markdown_path,
            published=entry.published,
            eligible_as_target=entry.eligible_as_target,
            content_quality_pass=entry.content_quality_pass,
            source="batch_registry_extension",
            same_batch=entry.slug in batch_source_slugs,
        )
        for entry in batch_extension
    )
    return records


def _event(code: str, source_slug: str, target_slug: str, message: str) -> FilterEvent:
    return FilterEvent(code, source_slug, target_slug, "candidate_filter", message)


def resolve_candidates(
    source: ArticleSpec,
    snapshot: RegistrySnapshot,
    *,
    batch_extension: Sequence[BatchRegistryEntry],
    batch_source_slugs: set[str],
    batch_id: str,
    config_version: str,
    expected_registry_version: str,
    expected_config_version: str,
    inbound_sources: Mapping[str, set[str]],
    inbound_cap: int,
    file_exists: Callable[[str], bool],
) -> tuple[list[Candidate], list[FilterEvent], int, int]:
    if snapshot.registry_version != expected_registry_version:
        raise SelectionError("REGISTRY_VERSION_MISMATCH", "Registry version 不一致")
    computed_version = compute_registry_version(
        snapshot.entries,
        source_batches=snapshot.source_batches,
        schema_version=snapshot.registry_schema_version,
    )
    if computed_version != snapshot.registry_version:
        raise SelectionError("REGISTRY_VERSION_MISMATCH", "Registry payload 与 version 不一致")
    if config_version != expected_config_version:
        raise SelectionError("CONFIG_VERSION_MISMATCH", "Config version 不一致")

    records = _target_records(snapshot, batch_extension, batch_source_slugs)
    before_filters = len(records)
    after_hard_filters = 0
    candidates: list[Candidate] = []
    events: list[FilterEvent] = []
    seen: set[str] = set()

    for target in sorted(records, key=lambda item: (item.slug, item.source)):
        if not target.slug:
            events.append(_event("REGISTRY_TARGET_MISSING", source.slug, "", "target slug 缺失"))
            continue
        if target.slug in seen:
            events.append(_event("DUPLICATE_TARGET_REJECTED", source.slug, target.slug, "target 重复"))
            continue
        seen.add(target.slug)
        if target.slug == source.slug:
            events.append(_event("SELF_LINK_REJECTED", source.slug, target.slug, "禁止 self link"))
            continue
        if not SLUG_PATTERN.fullmatch(target.slug) or not target.title or target.cluster not in CLUSTERS:
            events.append(_event("MALFORMED_REGISTRY_ENTRY", source.slug, target.slug, "Registry entry 非法"))
            continue
        if not target.published:
            events.append(_event("UNPUBLISHED_TARGET_REJECTED", source.slug, target.slug, "target 未发布"))
            continue
        if not target.eligible_as_target:
            events.append(_event("REGISTRY_TARGET_INELIGIBLE", source.slug, target.slug, "target 不合格"))
            continue
        if target.source == "batch_registry_extension" and not target.content_quality_pass:
            events.append(_event("CONTENT_QUALITY_NOT_PASSED", source.slug, target.slug, "新 Batch target 质量未 PASS"))
            continue
        if not file_exists(target.markdown_path):
            events.append(_event("REGISTRY_TARGET_MISSING", source.slug, target.slug, "Markdown 文件不存在"))
            continue

        current_load = len(inbound_sources.get(target.slug, set()))
        if current_load >= inbound_cap:
            events.append(_event("INBOUND_CAP_REACHED", source.slug, target.slug, "target 已达到 inbound cap"))
            continue

        after_hard_filters += 1
        score, reasons = score_relevance(source, target)
        if score < MIN_RELEVANCE_SCORE:
            events.append(
                FilterEvent(
                    "RELEVANCE_BELOW_THRESHOLD",
                    source.slug,
                    target.slug,
                    "relevance_filter",
                    f"score={score} < {MIN_RELEVANCE_SCORE}",
                )
            )
            continue

        candidates.append(
            Candidate(
                target_slug=target.slug,
                target_cluster=target.cluster,
                relevance_score=score,
                relevance_reasons=reasons,
                source=target.source,
                same_batch=target.same_batch,
                current_inbound_load=current_load,
                deterministic_hash=candidate_hash(
                    batch_id,
                    source.slug,
                    snapshot.registry_version,
                    config_version,
                    target.slug,
                ),
            )
        )

    candidates.sort(
        key=lambda item: (
            -item.relevance_score,
            item.current_inbound_load,
            item.deterministic_hash,
            item.target_slug,
        )
    )
    return candidates, events, before_filters, after_hard_filters


def _select_for_source(
    source: ArticleSpec,
    snapshot: RegistrySnapshot,
    *,
    batch_extension: Sequence[BatchRegistryEntry],
    batch_source_slugs: set[str],
    batch_id: str,
    config_version: str,
    expected_registry_version: str,
    expected_config_version: str,
    configured_max: int,
    inbound_sources: dict[str, set[str]],
    inbound_cap: int,
    file_exists: Callable[[str], bool],
) -> LinkSelectionPlan:
    candidates, events, _, _ = resolve_candidates(
        source,
        snapshot,
        batch_extension=batch_extension,
        batch_source_slugs=batch_source_slugs,
        batch_id=batch_id,
        config_version=config_version,
        expected_registry_version=expected_registry_version,
        expected_config_version=expected_config_version,
        inbound_sources=inbound_sources,
        inbound_cap=inbound_cap,
        file_exists=file_exists,
    )

    same_batch_quota = math.floor(configured_max * SAME_BATCH_MAX_PERCENT / 100)
    chosen: list[Candidate] = []
    same_batch_count = 0
    inbound_blocked = any(event.code == "INBOUND_CAP_REACHED" for event in events)

    for candidate in candidates:
        if len(chosen) >= configured_max:
            break
        current_load = len(inbound_sources.get(candidate.target_slug, set()))
        if current_load >= inbound_cap:
            inbound_blocked = True
            events.append(_event("INBOUND_CAP_REACHED", source.slug, candidate.target_slug, "target 已达到 inbound cap"))
            continue
        if candidate.same_batch and same_batch_count >= same_batch_quota:
            events.append(_event("SAME_BATCH_LIMIT_REACHED", source.slug, candidate.target_slug, "达到 same-batch 选择上限"))
            continue
        chosen.append(candidate)
        if candidate.same_batch:
            same_batch_count += 1

    while chosen and same_batch_count * 100 > len(chosen) * SAME_BATCH_MAX_PERCENT:
        remove_index = next(
            index
            for index in range(len(chosen) - 1, -1, -1)
            if chosen[index].same_batch
        )
        removed = chosen.pop(remove_index)
        same_batch_count -= 1
        events.append(_event("SAME_BATCH_LIMIT_REACHED", source.slug, removed.target_slug, "最终比例复核移除"))

    selected: list[SelectedTarget] = []
    for candidate in chosen:
        sources = inbound_sources.setdefault(candidate.target_slug, set())
        before = len(sources)
        sources.add(source.slug)
        selected.append(
            SelectedTarget(
                target_slug=candidate.target_slug,
                target_cluster=candidate.target_cluster,
                relevance_score=candidate.relevance_score,
                relevance_reasons=candidate.relevance_reasons,
                source=candidate.source,
                same_batch=candidate.same_batch,
                inbound_load_before=before,
                inbound_load_after=len(sources),
                deterministic_hash=candidate.deterministic_hash,
            )
        )

    internal_links = len(selected)
    same_batch_links = sum(target.same_batch for target in selected)
    ratio = same_batch_links / internal_links if internal_links else 0.0
    if internal_links < MIN_CONFIGURED_MAX:
        shortfall_reason = (
            "INBOUND_CAP_EXHAUSTED"
            if inbound_blocked
            else "INSUFFICIENT_RELEVANT_CANDIDATES"
        )
        status = "PASS_WITH_SHORTFALL"
        events.append(
            FilterEvent(
                "LINK_COUNT_SHORTFALL",
                source.slug,
                "",
                "selection_summary",
                shortfall_reason,
            )
        )
    else:
        shortfall_reason = None
        status = "PASS"

    return LinkSelectionPlan(
        batch_id=batch_id,
        source_slug=source.slug,
        source_cluster=source.cluster,
        registry_version=snapshot.registry_version,
        config_version=config_version,
        configured_max=configured_max,
        selected_targets=tuple(selected),
        filtered_candidates=tuple(events),
        internal_links=internal_links,
        same_batch_links=same_batch_links,
        same_batch_ratio=ratio,
        shortfall_reason=shortfall_reason,
        status=status,
    )


def validate_batch_result(result: BatchSelectionResult) -> None:
    if result.inbound_loads and max(result.inbound_loads.values()) > result.inbound_cap:
        raise SelectionError("INBOUND_CAP_EXCEEDED", "最终 inbound load 超限")
    for plan in result.plans:
        if plan.internal_links > plan.configured_max:
            raise SelectionError("CONFIGURED_MAX_EXCEEDED", plan.source_slug)
        if plan.same_batch_links * 100 > plan.internal_links * SAME_BATCH_MAX_PERCENT:
            raise SelectionError("SAME_BATCH_CAP_EXCEEDED", plan.source_slug)
        if any(target.target_slug == plan.source_slug for target in plan.selected_targets):
            raise SelectionError("SELF_LINK_SELECTED", plan.source_slug)
        if len({target.target_slug for target in plan.selected_targets}) != plan.internal_links:
            raise SelectionError("DUPLICATE_TARGET_SELECTED", plan.source_slug)


def plan_batch(
    sources: Sequence[ArticleSpec],
    snapshot: RegistrySnapshot,
    *,
    batch_extension: Sequence[BatchRegistryEntry] = (),
    batch_id: str,
    config_version: str,
    configured_max: int = DEFAULT_CONFIGURED_MAX,
    expected_registry_version: str | None = None,
    expected_config_version: str | None = None,
    file_exists: Callable[[str], bool] | None = None,
) -> BatchSelectionResult:
    if not sources:
        raise SelectionError("INVALID_BATCH_SIZE", "sources 不能为空")
    if not MIN_CONFIGURED_MAX <= configured_max <= MAX_CONFIGURED_MAX:
        raise SelectionError("INVALID_CONFIGURED_MAX", "configured_max 必须位于 20-50")

    expected_registry_version = expected_registry_version or snapshot.registry_version
    expected_config_version = expected_config_version or config_version
    file_exists = file_exists or (lambda path: (PROJECT_ROOT / path).is_file())
    ordered_sources = sorted(sources, key=lambda item: item.slug)
    if len({source.slug for source in ordered_sources}) != len(ordered_sources):
        raise SelectionError("DUPLICATE_SOURCE", "Batch source slug 重复")

    inbound_cap = calculate_inbound_cap(len(ordered_sources))
    inbound_sources: dict[str, set[str]] = {}
    batch_source_slugs = {source.slug for source in ordered_sources}
    plans = [
        _select_for_source(
            source,
            snapshot,
            batch_extension=batch_extension,
            batch_source_slugs=batch_source_slugs,
            batch_id=batch_id,
            config_version=config_version,
            expected_registry_version=expected_registry_version,
            expected_config_version=expected_config_version,
            configured_max=configured_max,
            inbound_sources=inbound_sources,
            inbound_cap=inbound_cap,
            file_exists=file_exists,
        )
        for source in ordered_sources
    ]
    result = BatchSelectionResult(
        plans=tuple(plans),
        inbound_loads={slug: len(source_slugs) for slug, source_slugs in sorted(inbound_sources.items())},
        inbound_cap=inbound_cap,
    )
    validate_batch_result(result)
    return result


def analyze_source_candidates(
    source: ArticleSpec,
    snapshot: RegistrySnapshot,
    *,
    batch_id: str = "frozen-analysis",
    config_version: str = "v1.1-default-1",
) -> dict[str, object]:
    candidates, events, before, after = resolve_candidates(
        source,
        snapshot,
        batch_extension=(),
        batch_source_slugs=set(),
        batch_id=batch_id,
        config_version=config_version,
        expected_registry_version=snapshot.registry_version,
        expected_config_version=config_version,
        inbound_sources={},
        inbound_cap=10**9,
        file_exists=lambda path: (PROJECT_ROOT / path).is_file(),
    )
    return {
        "source": source.slug,
        "cluster": source.cluster,
        "candidate_count_before_filters": before,
        "candidate_count_after_filters": after,
        "candidates_at_or_above_threshold": len(candidates),
        "top_10": candidates[:10],
        "filtered_candidates": events,
    }
