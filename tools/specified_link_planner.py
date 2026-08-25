from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from specified_link_registry import (
    ALLOWED_CLUSTERS,
    DEFAULT_SPECIFIED_LINKS_PER_ARTICLE,
    ID_PATTERN,
    MAX_SPECIFIED_LINKS_PER_ARTICLE,
    SPECIFIED_LINK_CONFIG_VERSION,
    SpecifiedLinkContractError,
    SpecifiedLinkPreflightResult,
    SpecifiedLinkRegistry,
    SpecifiedLinkSpec,
    compute_specified_link_version,
    validate_preflight_result,
)


@dataclass(frozen=True)
class SpecifiedLinkSourceArticle:
    slug: str
    cluster: str


@dataclass(frozen=True)
class SpecifiedLinkSelectedEntry:
    entry_id: str
    canonical_url: str
    anchor: str
    normalized_anchor: str
    cluster: str
    url_usage_before: int
    url_usage_after: int
    pair_usage_before: int
    pair_usage_after: int
    anchor_usage_before: int
    anchor_usage_after: int
    deterministic_hash: str


@dataclass(frozen=True)
class SpecifiedLinkFilteredEntry:
    entry_id: str
    reason_code: str
    message: str


@dataclass(frozen=True)
class SpecifiedLinkPlan:
    batch_id: str
    source_slug: str
    source_cluster: str
    specified_link_version: str
    config_version: str
    configured_max: int
    requested_links: int
    selected_links: int
    selected_entries: tuple[SpecifiedLinkSelectedEntry, ...]
    filtered_entries: tuple[SpecifiedLinkFilteredEntry, ...]
    shortfall_reason: str | None
    status: str


@dataclass(frozen=True)
class SpecifiedLinkBatchCaps:
    batch_size: int
    per_url_batch_cap: int
    per_url_anchor_pair_batch_cap: int
    per_anchor_batch_cap: int


@dataclass(frozen=True)
class SpecifiedLinkBatchUsage:
    url_usage: Mapping[str, int]
    url_anchor_pair_usage: Mapping[tuple[str, str], int]
    anchor_usage: Mapping[str, int]


@dataclass(frozen=True)
class SpecifiedLinkBatchPlanResult:
    plans: tuple[SpecifiedLinkPlan, ...]
    usage: SpecifiedLinkBatchUsage
    caps: SpecifiedLinkBatchCaps
    final_status: str


def _fail(code: str, message: str, *, entry_id: str | None = None) -> None:
    raise SpecifiedLinkContractError(code, message, entry_id=entry_id)


def calculate_specified_link_batch_caps(batch_size: int) -> SpecifiedLinkBatchCaps:
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        _fail("INVALID_SPECIFIED_INPUT_FORMAT", "batch_size 必须为正整数")
    return SpecifiedLinkBatchCaps(
        batch_size=batch_size,
        per_url_batch_cap=max(1, min(10, math.ceil(batch_size * 0.20))),
        per_url_anchor_pair_batch_cap=max(1, min(5, math.ceil(batch_size * 0.10))),
        per_anchor_batch_cap=max(1, min(10, math.ceil(batch_size * 0.15))),
    )


def compute_specified_link_candidate_hash(
    *,
    batch_id: str,
    source_slug: str,
    specified_link_version: str,
    config_version: str,
    entry_id: str,
) -> str:
    seed = "\n".join(
        (batch_id, source_slug, specified_link_version, config_version, entry_id)
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _validate_sources(
    sources: Sequence[SpecifiedLinkSourceArticle],
) -> tuple[SpecifiedLinkSourceArticle, ...]:
    if not sources:
        _fail("INVALID_SPECIFIED_INPUT_FORMAT", "source articles 不能为空")
    seen: set[str] = set()
    validated: list[SpecifiedLinkSourceArticle] = []
    for source in sources:
        if not ID_PATTERN.fullmatch(source.slug):
            _fail("INVALID_SPECIFIED_INPUT_FORMAT", "source slug 非法", entry_id=source.slug)
        if source.cluster not in ALLOWED_CLUSTERS:
            _fail("INVALID_SPECIFIED_INPUT_FORMAT", "source cluster 非法", entry_id=source.slug)
        if source.slug in seen:
            _fail("INVALID_SPECIFIED_INPUT_FORMAT", "source slug 重复", entry_id=source.slug)
        seen.add(source.slug)
        validated.append(source)
    return tuple(sorted(validated, key=lambda item: item.slug))


def _validate_registry_identity(
    registry: SpecifiedLinkRegistry,
    *,
    specified_link_version: str,
    config_version: str,
) -> None:
    computed = compute_specified_link_version(
        registry.entries,
        schema_version=registry.schema_version,
        config_version=registry.config_version,
    )
    versions = {specified_link_version, registry.specified_link_version, computed}
    if len(versions) != 1:
        _fail("SPECIFIED_LINK_VERSION_MISMATCH", "Specified Link Registry version 不一致")
    if config_version != SPECIFIED_LINK_CONFIG_VERSION or registry.config_version != config_version:
        _fail("SPECIFIED_LINK_VERSION_MISMATCH", "Specified Link config version 不一致")


def _validate_preflights(
    registry: SpecifiedLinkRegistry,
    preflight_results: Sequence[SpecifiedLinkPreflightResult],
) -> None:
    expected_ids = {entry.id for entry in registry.entries}
    actual_ids = [result.entry_id for result in preflight_results]
    if len(set(actual_ids)) != len(actual_ids) or set(actual_ids) != expected_ids:
        _fail("UNAPPROVED_SPECIFIED_URL", "每个 Registry entry 必须恰有一个 Preflight result")
    for result in preflight_results:
        validate_preflight_result(result, registry)
        if result.result != "PASS" or result.status_code is None or not 200 <= result.status_code <= 299:
            code = result.error_code or "UNAPPROVED_SPECIFIED_URL"
            _fail(code, "Preflight 非 PASS，不得进入 Planner", entry_id=result.entry_id)


def _usage_count(usage: Mapping[object, set[str]], key: object) -> int:
    return len(usage.get(key, set()))


def _candidate_sort_key(
    entry: SpecifiedLinkSpec,
    *,
    source: SpecifiedLinkSourceArticle,
    batch_id: str,
    registry: SpecifiedLinkRegistry,
    url_usage: Mapping[str, set[str]],
    pair_usage: Mapping[tuple[str, str], set[str]],
    anchor_usage: Mapping[str, set[str]],
) -> tuple[object, ...]:
    pair = (entry.canonical_url, entry.normalized_anchor)
    candidate_hash = compute_specified_link_candidate_hash(
        batch_id=batch_id,
        source_slug=source.slug,
        specified_link_version=registry.specified_link_version,
        config_version=registry.config_version,
        entry_id=entry.id,
    )
    return (
        0 if source.cluster == entry.cluster else 1,
        _usage_count(url_usage, entry.canonical_url),
        _usage_count(anchor_usage, entry.normalized_anchor),
        _usage_count(pair_usage, pair),
        candidate_hash,
        entry.id,
    )


def _filter_reason(
    entry: SpecifiedLinkSpec,
    *,
    selected_urls: set[str],
    selected_anchors: set[str],
    url_usage: Mapping[str, set[str]],
    pair_usage: Mapping[tuple[str, str], set[str]],
    anchor_usage: Mapping[str, set[str]],
    caps: SpecifiedLinkBatchCaps,
) -> tuple[str, str] | None:
    pair = (entry.canonical_url, entry.normalized_anchor)
    if entry.canonical_url in selected_urls:
        return "SPECIFIED_URL_BATCH_CAP_REACHED", "article-local canonical URL uniqueness reached"
    if entry.normalized_anchor in selected_anchors:
        return "SPECIFIED_ANCHOR_BATCH_CAP_REACHED", "article-local normalized anchor uniqueness reached"
    if _usage_count(url_usage, entry.canonical_url) >= caps.per_url_batch_cap:
        return "SPECIFIED_URL_BATCH_CAP_REACHED", "per URL batch cap reached"
    if _usage_count(pair_usage, pair) >= caps.per_url_anchor_pair_batch_cap:
        return "SPECIFIED_PAIR_BATCH_CAP_REACHED", "per URL+anchor pair batch cap reached"
    if _usage_count(anchor_usage, entry.normalized_anchor) >= caps.per_anchor_batch_cap:
        return "SPECIFIED_ANCHOR_BATCH_CAP_REACHED", "per anchor batch cap reached"
    return None


def _plan_for_source(
    source: SpecifiedLinkSourceArticle,
    *,
    registry: SpecifiedLinkRegistry,
    batch_id: str,
    configured_max: int,
    caps: SpecifiedLinkBatchCaps,
    url_usage: dict[str, set[str]],
    pair_usage: dict[tuple[str, str], set[str]],
    anchor_usage: dict[str, set[str]],
) -> SpecifiedLinkPlan:
    selected: list[SpecifiedLinkSelectedEntry] = []
    filtered: list[SpecifiedLinkFilteredEntry] = []
    remaining: list[SpecifiedLinkSpec] = []
    cap_filtered = False

    for entry in sorted(registry.entries, key=lambda item: item.id):
        if entry.cluster != source.cluster:
            filtered.append(
                SpecifiedLinkFilteredEntry(
                    entry.id,
                    "SPECIFIED_CLUSTER_MISMATCH",
                    "source cluster 与 Specified Link cluster 不一致",
                )
            )
        else:
            remaining.append(entry)

    selected_urls: set[str] = set()
    selected_anchors: set[str] = set()
    while len(selected) < configured_max and remaining:
        eligible: list[SpecifiedLinkSpec] = []
        next_remaining: list[SpecifiedLinkSpec] = []
        for entry in remaining:
            reason = _filter_reason(
                entry,
                selected_urls=selected_urls,
                selected_anchors=selected_anchors,
                url_usage=url_usage,
                pair_usage=pair_usage,
                anchor_usage=anchor_usage,
                caps=caps,
            )
            if reason is None:
                eligible.append(entry)
            else:
                code, message = reason
                filtered.append(SpecifiedLinkFilteredEntry(entry.id, code, message))
                cap_filtered = True

        if not eligible:
            remaining = next_remaining
            break

        eligible.sort(
            key=lambda entry: _candidate_sort_key(
                entry,
                source=source,
                batch_id=batch_id,
                registry=registry,
                url_usage=url_usage,
                pair_usage=pair_usage,
                anchor_usage=anchor_usage,
            )
        )
        chosen = eligible[0]
        remaining = eligible[1:]
        pair = (chosen.canonical_url, chosen.normalized_anchor)
        url_before = _usage_count(url_usage, chosen.canonical_url)
        pair_before = _usage_count(pair_usage, pair)
        anchor_before = _usage_count(anchor_usage, chosen.normalized_anchor)
        url_usage.setdefault(chosen.canonical_url, set()).add(source.slug)
        pair_usage.setdefault(pair, set()).add(source.slug)
        anchor_usage.setdefault(chosen.normalized_anchor, set()).add(source.slug)
        selected_urls.add(chosen.canonical_url)
        selected_anchors.add(chosen.normalized_anchor)
        selected.append(
            SpecifiedLinkSelectedEntry(
                entry_id=chosen.id,
                canonical_url=chosen.canonical_url,
                anchor=chosen.anchor,
                normalized_anchor=chosen.normalized_anchor,
                cluster=chosen.cluster,
                url_usage_before=url_before,
                url_usage_after=_usage_count(url_usage, chosen.canonical_url),
                pair_usage_before=pair_before,
                pair_usage_after=_usage_count(pair_usage, pair),
                anchor_usage_before=anchor_before,
                anchor_usage_after=_usage_count(anchor_usage, chosen.normalized_anchor),
                deterministic_hash=compute_specified_link_candidate_hash(
                    batch_id=batch_id,
                    source_slug=source.slug,
                    specified_link_version=registry.specified_link_version,
                    config_version=registry.config_version,
                    entry_id=chosen.id,
                ),
            )
        )

    if len(selected) == configured_max:
        status = "PASS"
        shortfall_reason = None
    else:
        status = "PASS_WITH_SHORTFALL"
        shortfall_reason = (
            "SPECIFIED_BATCH_CAP_EXHAUSTED"
            if cap_filtered
            else "INSUFFICIENT_SPECIFIED_CLUSTER_CANDIDATES"
        )

    return SpecifiedLinkPlan(
        batch_id=batch_id,
        source_slug=source.slug,
        source_cluster=source.cluster,
        specified_link_version=registry.specified_link_version,
        config_version=registry.config_version,
        configured_max=configured_max,
        requested_links=configured_max,
        selected_links=len(selected),
        selected_entries=tuple(selected),
        filtered_entries=tuple(filtered),
        shortfall_reason=shortfall_reason,
        status=status,
    )


def plan_specified_links_for_batch(
    sources: Sequence[SpecifiedLinkSourceArticle],
    registry: SpecifiedLinkRegistry,
    preflight_results: Sequence[SpecifiedLinkPreflightResult],
    *,
    batch_id: str,
    configured_max: int = DEFAULT_SPECIFIED_LINKS_PER_ARTICLE,
    specified_link_version: str | None = None,
    config_version: str = SPECIFIED_LINK_CONFIG_VERSION,
) -> SpecifiedLinkBatchPlanResult:
    if not batch_id or batch_id != batch_id.strip():
        _fail("INVALID_SPECIFIED_INPUT_FORMAT", "batch_id 不能为空或包含首尾空白")
    if isinstance(configured_max, bool) or not isinstance(configured_max, int) or not 1 <= configured_max <= MAX_SPECIFIED_LINKS_PER_ARTICLE:
        _fail("INVALID_SPECIFIED_INPUT_FORMAT", "invalid configured_max: 必须为 1–3")

    sorted_sources = _validate_sources(sources)
    expected_version = specified_link_version or registry.specified_link_version
    _validate_registry_identity(
        registry,
        specified_link_version=expected_version,
        config_version=config_version,
    )
    _validate_preflights(registry, preflight_results)
    caps = calculate_specified_link_batch_caps(len(sorted_sources))
    url_usage: dict[str, set[str]] = {}
    pair_usage: dict[tuple[str, str], set[str]] = {}
    anchor_usage: dict[str, set[str]] = {}
    plans = tuple(
        _plan_for_source(
            source,
            registry=registry,
            batch_id=batch_id,
            configured_max=configured_max,
            caps=caps,
            url_usage=url_usage,
            pair_usage=pair_usage,
            anchor_usage=anchor_usage,
        )
        for source in sorted_sources
    )
    usage = SpecifiedLinkBatchUsage(
        url_usage={key: len(value) for key, value in sorted(url_usage.items())},
        url_anchor_pair_usage={key: len(value) for key, value in sorted(pair_usage.items())},
        anchor_usage={key: len(value) for key, value in sorted(anchor_usage.items())},
    )
    final_status = "PASS" if all(plan.status == "PASS" for plan in plans) else "PASS_WITH_SHORTFALL"
    return SpecifiedLinkBatchPlanResult(plans, usage, caps, final_status)
