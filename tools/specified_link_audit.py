from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from specified_link_injector import (
    HTML_LINK_PATTERN,
    INTERNAL_LINK_PATTERN,
    MARKDOWN_LINK_PATTERN,
    SpecifiedLinkInjectionResult,
    scan_specified_markdown,
)
from specified_link_planner import (
    SpecifiedLinkPlan,
    calculate_specified_link_batch_caps,
)
from specified_link_registry import (
    MAX_SPECIFIED_LINKS_PER_ARTICLE,
    SpecifiedLinkContractError,
    SpecifiedLinkPreflightResult,
    SpecifiedLinkRegistry,
    compute_specified_link_version,
    normalize_specified_anchor,
    validate_preflight_result,
)


LEGAL_SHORTFALLS = frozenset(
    {
        "INSUFFICIENT_SPECIFIED_CLUSTER_CANDIDATES",
        "SPECIFIED_BATCH_CAP_EXHAUSTED",
        "NO_SAFE_SPECIFIED_LINK_POINT",
    }
)


@dataclass(frozen=True)
class SpecifiedLinkAuditEvent:
    code: str
    article_slug: str
    entry_id: str | None
    stage: str
    message: str


@dataclass(frozen=True)
class SpecifiedLinkArticleAudit:
    article_slug: str
    specified_links: int
    unique_specified_urls: int
    duplicate_specified_urls: int
    duplicate_anchors: int
    invalid_urls: int
    unapproved_urls: int
    cluster_mismatches: int
    protected_zone_violations: int
    malformed_links: int
    placement_failures: int
    per_article_limit_exceeded: int
    pre_existing_links_mutated: int
    internal_links_mutated: int
    provenance_missing: int
    specified_link_version: str
    config_version: str
    shortfall_reason: str | None
    final_status: str
    errors: tuple[SpecifiedLinkAuditEvent, ...]
    warnings: tuple[SpecifiedLinkAuditEvent, ...]


@dataclass(frozen=True)
class SpecifiedLinkAuditInput:
    source_slug: str
    source_cluster: str
    batch_id: str
    pre_markdown: str
    post_markdown: str
    plan: SpecifiedLinkPlan
    injection_result: SpecifiedLinkInjectionResult


@dataclass(frozen=True)
class SpecifiedLinkBatchAudit:
    articles: tuple[SpecifiedLinkArticleAudit, ...]
    url_usage: Mapping[str, int]
    url_anchor_pair_usage: Mapping[tuple[str, str], int]
    anchor_usage: Mapping[str, int]
    per_url_cap: int
    per_pair_cap: int
    per_anchor_cap: int
    violations: tuple[SpecifiedLinkAuditEvent, ...]
    final_status: str


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _event(
    errors: list[SpecifiedLinkAuditEvent],
    code: str,
    slug: str,
    stage: str,
    message: str,
    entry_id: str | None = None,
) -> None:
    errors.append(SpecifiedLinkAuditEvent(code, slug, entry_id, stage, message))


def _counter_delta(left: Counter[str], right: Counter[str]) -> int:
    return sum((left - right).values()) + sum((right - left).values())


def _link_counters(markdown: str) -> tuple[Counter[str], Counter[str], Counter[str]]:
    return (
        Counter(match.group(0) for match in MARKDOWN_LINK_PATTERN.finditer(markdown)),
        Counter(match.group(0) for match in HTML_LINK_PATTERN.finditer(markdown)),
        Counter(match.group(0) for match in INTERNAL_LINK_PATTERN.finditer(markdown)),
    )


def verify_internal_links_unchanged(
    pre_markdown: str,
    post_markdown: str,
    *,
    placements: Sequence[object] = (),
) -> bool:
    reversed_markdown = post_markdown
    for placement in sorted(placements, key=lambda item: item.start, reverse=True):
        expected = f"[{placement.anchor}]({placement.url})"
        if reversed_markdown[placement.start : placement.end] != expected:
            return False
        reversed_markdown = (
            reversed_markdown[: placement.start]
            + placement.anchor
            + reversed_markdown[placement.end :]
        )
    return (
        Counter(INTERNAL_LINK_PATTERN.findall(pre_markdown))
        == Counter(INTERNAL_LINK_PATTERN.findall(reversed_markdown))
    )


def _protected_mutation_code(pre_markdown: str, reversed_markdown: str) -> str:
    try:
        pre_scan = scan_specified_markdown(pre_markdown)
        post_scan = scan_specified_markdown(reversed_markdown)
    except SpecifiedLinkContractError:
        return "SPECIFIED_PROTECTED_ZONE_VIOLATION"
    protected_kinds = {
        "front_matter",
        "heading",
        "fenced_code",
        "inline_code",
        "liquid_tag",
        "raw_boundary_line",
        "markdown_image",
        "bare_url",
        "html_tag",
        "html_comment",
    }
    pre_tokens = Counter((token.kind, token.text) for token in pre_scan.tokens if token.kind in protected_kinds)
    post_tokens = Counter((token.kind, token.text) for token in post_scan.tokens if token.kind in protected_kinds)
    if pre_tokens != post_tokens or pre_scan.raw_boundaries != post_scan.raw_boundaries:
        return "SPECIFIED_PROTECTED_ZONE_VIOLATION"
    pre_md, pre_html, pre_internal = _link_counters(pre_markdown)
    post_md, post_html, post_internal = _link_counters(reversed_markdown)
    if pre_internal != post_internal:
        return "INTERNAL_LINK_MUTATED"
    if pre_md != post_md or pre_html != post_html:
        return "PRE_EXISTING_LINK_MUTATED"
    return "PRE_EXISTING_LINK_MUTATED"


def audit_specified_link_article(
    *,
    source_slug: str,
    source_cluster: str,
    batch_id: str,
    pre_markdown: str,
    post_markdown: str,
    plan: SpecifiedLinkPlan,
    injection_result: SpecifiedLinkInjectionResult,
    registry: SpecifiedLinkRegistry,
    preflight_results: Sequence[SpecifiedLinkPreflightResult],
) -> SpecifiedLinkArticleAudit:
    errors: list[SpecifiedLinkAuditEvent] = []
    warnings: list[SpecifiedLinkAuditEvent] = []
    entries = {entry.id: entry for entry in registry.entries}
    preflights = {item.entry_id: item for item in preflight_results}

    computed_version = compute_specified_link_version(
        registry.entries,
        schema_version=registry.schema_version,
        config_version=registry.config_version,
    )
    identities = (
        plan.source_slug == source_slug,
        injection_result.source_slug == source_slug,
        plan.source_cluster == source_cluster,
        plan.batch_id == batch_id,
        injection_result.batch_id == batch_id,
        plan.specified_link_version == registry.specified_link_version,
        injection_result.specified_link_version == registry.specified_link_version,
        computed_version == registry.specified_link_version,
        plan.config_version == registry.config_version,
        injection_result.config_version == registry.config_version,
    )
    if not all(identities):
        _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "provenance", "source/batch/version/config/Registry identity 不一致")
    if injection_result.pre_sha256 != _sha(pre_markdown):
        _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "provenance", "pre_specified_sha256 不匹配")
    if injection_result.post_sha256 != _sha(post_markdown):
        _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "provenance", "post_specified_sha256 不匹配")

    if plan.configured_max not in {1, 2, 3} or plan.requested_links != plan.configured_max:
        _event(errors, "SPECIFIED_ARTICLE_CAP_EXCEEDED", source_slug, "contract", "configured_max/requested_links 非法")
    if plan.selected_links != len(plan.selected_entries):
        _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "plan", "selected_links 与 selected_entries 不闭合")

    requested = injection_result.requested_entries
    if len(requested) != plan.selected_links:
        _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "injection", "requested_entries 与 Plan selected 不闭合")
    for index, requested_entry in enumerate(requested):
        if index >= len(plan.selected_entries):
            break
        selected = plan.selected_entries[index]
        if (
            requested_entry.entry_id,
            requested_entry.canonical_url,
            requested_entry.anchor,
            requested_entry.normalized_anchor,
            requested_entry.cluster,
        ) != (
            selected.entry_id,
            selected.canonical_url,
            selected.anchor,
            selected.normalized_anchor,
            selected.cluster,
        ):
            _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "injection", "Plan 与 InjectionResult requested identity 不一致", requested_entry.entry_id)

    placed_ids = [placement.entry_id for placement in injection_result.placed_entries]
    skipped_ids = [skipped.entry_id for skipped in injection_result.skipped_entries]
    if Counter(placed_ids + skipped_ids) != Counter(item.entry_id for item in requested):
        _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "injection", "placed/skipped/requested 无法闭合")

    placed_urls: list[str] = []
    placed_anchors: list[str] = []
    valid_placements: list[object] = []
    for placement in injection_result.placed_entries:
        entry = entries.get(placement.entry_id)
        if entry is None:
            _event(errors, "UNAPPROVED_SPECIFIED_URL", source_slug, "registry", "placement entry 不存在", placement.entry_id)
            continue
        placed_urls.append(placement.url)
        placed_anchors.append(normalize_specified_anchor(placement.anchor))
        if (placement.url, placement.anchor) != (entry.canonical_url, entry.anchor):
            _event(errors, "UNAPPROVED_SPECIFIED_URL", source_slug, "placement", "URL/anchor 与 Registry 不一致", entry.id)
        if entry.cluster != source_cluster:
            _event(errors, "SPECIFIED_CLUSTER_MISMATCH", source_slug, "cluster", "source 与 target cluster 不一致", entry.id)
        selected = next((item for item in plan.selected_entries if item.entry_id == entry.id), None)
        if selected is None or (
            selected.canonical_url,
            selected.anchor,
            selected.normalized_anchor,
            selected.cluster,
        ) != (entry.canonical_url, entry.anchor, entry.normalized_anchor, entry.cluster):
            _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "plan", "placement 缺少匹配 Plan identity", entry.id)
        preflight = preflights.get(entry.id)
        if preflight is None:
            _event(errors, "UNAPPROVED_SPECIFIED_URL", source_slug, "preflight", "缺少 Preflight evidence", entry.id)
        else:
            try:
                validate_preflight_result(preflight, registry)
                if preflight.result != "PASS" or preflight.status_code is None or not 200 <= preflight.status_code <= 299:
                    raise SpecifiedLinkContractError("UNAPPROVED_SPECIFIED_URL", "Preflight 非 PASS")
            except SpecifiedLinkContractError:
                _event(errors, "UNAPPROVED_SPECIFIED_URL", source_slug, "preflight", "Preflight identity/status 非 PASS", entry.id)
        expected = f"[{entry.anchor}]({entry.canonical_url})"
        if placement.start < 0 or placement.end > len(post_markdown) or post_markdown[placement.start : placement.end] != expected:
            _event(errors, "MALFORMED_SPECIFIED_LINK", source_slug, "placement", "placement offset 未精确命中规范 Markdown link", entry.id)
        else:
            valid_placements.append(placement)

    duplicate_urls = sum(count - 1 for count in Counter(placed_urls).values() if count > 1)
    duplicate_anchors = sum(count - 1 for count in Counter(placed_anchors).values() if count > 1)
    if duplicate_urls:
        _event(errors, "DUPLICATE_SPECIFIED_URL", source_slug, "article", "同一 article canonical URL 重复")
    if duplicate_anchors:
        _event(errors, "DUPLICATE_SPECIFIED_ANCHOR", source_slug, "article", "同一 article normalized anchor 重复")
    article_cap = int(len(injection_result.placed_entries) > plan.configured_max or plan.configured_max > MAX_SPECIFIED_LINKS_PER_ARTICLE)
    if article_cap:
        _event(errors, "SPECIFIED_ARTICLE_CAP_EXCEEDED", source_slug, "article", "per-article cap exceeded")

    reversed_markdown = post_markdown
    reversal_ok = len(valid_placements) == len(injection_result.placed_entries)
    if reversal_ok:
        for placement in sorted(valid_placements, key=lambda item: item.start, reverse=True):
            expected = f"[{placement.anchor}]({placement.url})"
            if reversed_markdown[placement.start : placement.end] != expected:
                reversal_ok = False
                break
            reversed_markdown = reversed_markdown[: placement.start] + placement.anchor + reversed_markdown[placement.end :]
    mutation_code = None
    if not reversal_ok or reversed_markdown != pre_markdown:
        mutation_code = _protected_mutation_code(pre_markdown, reversed_markdown)
        _event(errors, mutation_code, source_slug, "preservation", "移除 provenance placements 后无法精确还原 baseline")
    if not verify_internal_links_unchanged(pre_markdown, post_markdown, placements=valid_placements):
        if mutation_code != "INTERNAL_LINK_MUTATED":
            _event(errors, "INTERNAL_LINK_MUTATED", source_slug, "preservation", "Internal Links URL/anchor/count/placement 发生变化")

    shortfall = injection_result.shortfall_reason
    placed_count = len(injection_result.placed_entries)
    if errors:
        status = "FAIL"
    elif placed_count == plan.requested_links:
        if shortfall is not None or plan.shortfall_reason is not None or injection_result.skipped_entries:
            _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "shortfall", "无 shortfall 但 evidence 声明 shortfall")
            status = "FAIL"
        else:
            status = "PASS"
    else:
        planner_shortfall = plan.shortfall_reason if plan.selected_links < plan.requested_links else None
        placement_shortfall = "NO_SAFE_SPECIFIED_LINK_POINT" if injection_result.skipped_entries else None
        expected_shortfall = placement_shortfall or planner_shortfall
        warning_strings = set(injection_result.warnings)
        warning_ok = (
            (not planner_shortfall or f"PLANNER_SHORTFALL:{planner_shortfall}" in warning_strings)
            and (not placement_shortfall or "PLACEMENT_SHORTFALL:NO_SAFE_SPECIFIED_LINK_POINT" in warning_strings)
        )
        if expected_shortfall not in LEGAL_SHORTFALLS or shortfall != expected_shortfall or not warning_ok:
            _event(errors, "SPECIFIED_PROVENANCE_MISSING", source_slug, "shortfall", "shortfall provenance 不闭合")
            status = "FAIL"
        else:
            warnings.append(SpecifiedLinkAuditEvent(expected_shortfall, source_slug, None, "shortfall", "合法 shortfall provenance"))
            status = "PASS_WITH_SHORTFALL"

    codes = Counter(event.code for event in errors)
    return SpecifiedLinkArticleAudit(
        article_slug=source_slug,
        specified_links=placed_count,
        unique_specified_urls=len(set(placed_urls)),
        duplicate_specified_urls=duplicate_urls,
        duplicate_anchors=duplicate_anchors,
        invalid_urls=codes["INVALID_SPECIFIED_URL"],
        unapproved_urls=codes["UNAPPROVED_SPECIFIED_URL"],
        cluster_mismatches=codes["SPECIFIED_CLUSTER_MISMATCH"],
        protected_zone_violations=codes["SPECIFIED_PROTECTED_ZONE_VIOLATION"],
        malformed_links=codes["MALFORMED_SPECIFIED_LINK"],
        placement_failures=codes["MALFORMED_SPECIFIED_LINK"],
        per_article_limit_exceeded=codes["SPECIFIED_ARTICLE_CAP_EXCEEDED"],
        pre_existing_links_mutated=codes["PRE_EXISTING_LINK_MUTATED"],
        internal_links_mutated=codes["INTERNAL_LINK_MUTATED"],
        provenance_missing=codes["SPECIFIED_PROVENANCE_MISSING"],
        specified_link_version=registry.specified_link_version,
        config_version=registry.config_version,
        shortfall_reason=shortfall,
        final_status="FAIL" if errors else status,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def audit_specified_link_batch(
    audit_inputs: Sequence[SpecifiedLinkAuditInput],
    *,
    registry: SpecifiedLinkRegistry,
    preflight_results: Sequence[SpecifiedLinkPreflightResult],
) -> SpecifiedLinkBatchAudit:
    caps = calculate_specified_link_batch_caps(len(audit_inputs))
    articles: list[SpecifiedLinkArticleAudit] = []
    url_sources: dict[str, set[str]] = defaultdict(set)
    pair_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    anchor_sources: dict[str, set[str]] = defaultdict(set)
    violations: list[SpecifiedLinkAuditEvent] = []
    for item in audit_inputs:
        result = audit_specified_link_article(
            source_slug=item.source_slug,
            source_cluster=item.source_cluster,
            batch_id=item.batch_id,
            pre_markdown=item.pre_markdown,
            post_markdown=item.post_markdown,
            plan=item.plan,
            injection_result=item.injection_result,
            registry=registry,
            preflight_results=preflight_results,
        )
        articles.append(result)
        for placement in item.injection_result.placed_entries:
            entry = next((candidate for candidate in registry.entries if candidate.id == placement.entry_id), None)
            if entry is None:
                continue
            url_sources[entry.canonical_url].add(item.source_slug)
            pair_sources[(entry.canonical_url, entry.normalized_anchor)].add(item.source_slug)
            anchor_sources[entry.normalized_anchor].add(item.source_slug)
    for usage, cap, code, stage in (
        (url_sources, caps.per_url_batch_cap, "SPECIFIED_URL_BATCH_CAP_EXCEEDED", "url_cap"),
        (pair_sources, caps.per_url_anchor_pair_batch_cap, "SPECIFIED_PAIR_BATCH_CAP_EXCEEDED", "pair_cap"),
        (anchor_sources, caps.per_anchor_batch_cap, "SPECIFIED_ANCHOR_BATCH_CAP_EXCEEDED", "anchor_cap"),
    ):
        for key, sources in usage.items():
            if len(sources) > cap:
                violations.append(SpecifiedLinkAuditEvent(code, "<batch>", None, stage, f"{key!r}: {len(sources)} > {cap}"))
    if violations or any(article.final_status == "FAIL" for article in articles):
        status = "FAIL"
    elif any(article.final_status == "PASS_WITH_SHORTFALL" for article in articles):
        status = "PASS_WITH_SHORTFALL"
    else:
        status = "PASS"
    return SpecifiedLinkBatchAudit(
        articles=tuple(articles),
        url_usage={key: len(value) for key, value in url_sources.items()},
        url_anchor_pair_usage={key: len(value) for key, value in pair_sources.items()},
        anchor_usage={key: len(value) for key, value in anchor_sources.items()},
        per_url_cap=caps.per_url_batch_cap,
        per_pair_cap=caps.per_url_anchor_pair_batch_cap,
        per_anchor_cap=caps.per_anchor_batch_cap,
        violations=tuple(violations),
        final_status=status,
    )
