from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from direct_specified_link_registry import (
    DIRECT_APPROVAL_SOURCE,
    DIRECT_CONFIG_VERSION,
    DirectSpecifiedLinkContractError,
    DirectSpecifiedLinkRegistry,
    DirectSpecifiedLinkSpec,
    validate_direct_registry,
)


DIRECT_SOURCE_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MIN_DIRECT_LINKS_PER_ARTICLE = 1
MAX_DIRECT_LINKS_PER_ARTICLE = 30
INSUFFICIENT_UNIQUE_DIRECT_TARGETS = "INSUFFICIENT_UNIQUE_DIRECT_TARGETS"


@dataclass(frozen=True)
class DirectSourceArticle:
    slug: str


@dataclass(frozen=True)
class DirectSelectedEntry:
    entry_id: str
    canonical_url: str
    url: str
    anchor: str
    normalized_anchor: str
    approval_source: str
    registry_index: int
    distribution_index: int
    deterministic_key: str


@dataclass(frozen=True)
class DirectSpecifiedLinkPlan:
    batch_id: str
    source_slug: str
    direct_registry_version: str
    config_version: str
    configured_direct_links_per_article: int
    requested_links: int
    selected_links: int
    selected_entries: tuple[DirectSelectedEntry, ...]
    shortfall_reason: str | None
    status: str


@dataclass(frozen=True)
class DirectSpecifiedLinkBatchPlanResult:
    batch_id: str
    direct_registry_version: str
    config_version: str
    source_count: int
    entry_count: int
    requested_total: int
    selected_total: int
    plans: tuple[DirectSpecifiedLinkPlan, ...]
    entry_usage: Mapping[str, int]
    final_status: str


def _fail(code: str, message: str, *, entry_id: str | None = None) -> None:
    raise DirectSpecifiedLinkContractError(code, message, entry_id=entry_id)


def _validate_sources(sources: Sequence[DirectSourceArticle]) -> tuple[DirectSourceArticle, ...]:
    if not sources:
        _fail("INVALID_DIRECT_SOURCE", "DIRECT source articles 不能为空")
    seen: set[str] = set()
    validated: list[DirectSourceArticle] = []
    for source in sources:
        if not isinstance(source, DirectSourceArticle) or not DIRECT_SOURCE_SLUG_PATTERN.fullmatch(source.slug):
            _fail("INVALID_DIRECT_SOURCE", "DIRECT source slug 非法")
        if source.slug in seen:
            _fail("DUPLICATE_DIRECT_SOURCE_SLUG", "DIRECT source slug 重复", entry_id=source.slug)
        seen.add(source.slug)
        validated.append(source)
    return tuple(sorted(validated, key=lambda item: item.slug))


def _validate_config(configured_direct_links_per_article: int) -> None:
    if (
        isinstance(configured_direct_links_per_article, bool)
        or not isinstance(configured_direct_links_per_article, int)
        or not MIN_DIRECT_LINKS_PER_ARTICLE
        <= configured_direct_links_per_article
        <= MAX_DIRECT_LINKS_PER_ARTICLE
    ):
        _fail("INVALID_DIRECT_PLANNER_CONFIG", "configured_direct_links_per_article 必须为 1–30 整数")


def compute_direct_distribution_seed(
    *,
    batch_id: str,
    direct_registry_version: str,
    config_version: str,
) -> str:
    payload = f"{batch_id}\n{direct_registry_version}\n{config_version}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _deterministic_key(
    *,
    seed: str,
    source_slug: str,
    entry_id: str,
    distribution_index: int,
) -> str:
    payload = f"{seed}\n{source_slug}\n{entry_id}\n{distribution_index}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_registry_identity(
    registry: DirectSpecifiedLinkRegistry,
    *,
    direct_registry_version: str,
    config_version: str,
) -> tuple[DirectSpecifiedLinkSpec, ...]:
    try:
        validate_direct_registry(registry, expected_version=direct_registry_version)
    except DirectSpecifiedLinkContractError as exc:
        _fail("DIRECT_REGISTRY_VERSION_MISMATCH", exc.message)
    if config_version != DIRECT_CONFIG_VERSION or registry.config_version != config_version:
        _fail("DIRECT_REGISTRY_VERSION_MISMATCH", "DIRECT config version 不一致")
    entries = tuple(sorted(registry.entries, key=lambda item: item.id))
    if any(entry.approval_source != DIRECT_APPROVAL_SOURCE for entry in entries):
        _fail("INVALID_DIRECT_ENTRY_IDENTITY", "DIRECT entry 缺少 USER_INPUT approval provenance")
    return entries


def plan_direct_specified_links_for_batch(
    sources: Sequence[DirectSourceArticle],
    registry: DirectSpecifiedLinkRegistry,
    *,
    batch_id: str,
    configured_direct_links_per_article: int,
    direct_registry_version: str,
    config_version: str,
) -> DirectSpecifiedLinkBatchPlanResult:
    if not isinstance(batch_id, str) or not batch_id or batch_id != batch_id.strip():
        _fail("INVALID_DIRECT_PLANNER_CONFIG", "batch_id 不能为空或包含首尾空白")
    _validate_config(configured_direct_links_per_article)
    sorted_sources = _validate_sources(sources)
    entries = _validate_registry_identity(
        registry,
        direct_registry_version=direct_registry_version,
        config_version=config_version,
    )

    seed = compute_direct_distribution_seed(
        batch_id=batch_id,
        direct_registry_version=direct_registry_version,
        config_version=config_version,
    )
    entry_count = len(entries)
    offset = int(seed, 16) % entry_count if entry_count else 0
    sequence = entries[offset:] + entries[:offset]
    sequence_positions = {entry.id: index for index, entry in enumerate(sequence)}
    registry_indices = {entry.id: index for index, entry in enumerate(entries)}
    usage = {entry.id: 0 for entry in entries}
    plans: list[DirectSpecifiedLinkPlan] = []
    cursor = 0
    distribution_index = 0

    for source in sorted_sources:
        selected: list[DirectSelectedEntry] = []
        used_urls: set[str] = set()
        for _ in range(configured_direct_links_per_article):
            eligible = [entry for entry in sequence if entry.canonical_url not in used_urls]
            if not eligible:
                distribution_index += 1
                continue
            minimum_usage = min(usage[entry.id] for entry in eligible)
            balanced = [entry for entry in eligible if usage[entry.id] == minimum_usage]
            chosen = min(
                balanced,
                key=lambda entry: (
                    (sequence_positions[entry.id] - cursor) % entry_count,
                    entry.id,
                ),
            )
            position = sequence_positions[chosen.id]
            selected.append(
                DirectSelectedEntry(
                    entry_id=chosen.id,
                    canonical_url=chosen.canonical_url,
                    url=chosen.url,
                    anchor=chosen.anchor,
                    normalized_anchor=chosen.normalized_anchor,
                    approval_source=chosen.approval_source,
                    registry_index=registry_indices[chosen.id],
                    distribution_index=distribution_index,
                    deterministic_key=_deterministic_key(
                        seed=seed,
                        source_slug=source.slug,
                        entry_id=chosen.id,
                        distribution_index=distribution_index,
                    ),
                )
            )
            usage[chosen.id] += 1
            used_urls.add(chosen.canonical_url)
            cursor = (position + 1) % entry_count
            distribution_index += 1

        selected_count = len(selected)
        if selected_count == configured_direct_links_per_article:
            status = "PASS"
            shortfall_reason = None
        else:
            status = "PASS_WITH_SHORTFALL"
            shortfall_reason = INSUFFICIENT_UNIQUE_DIRECT_TARGETS
        plans.append(
            DirectSpecifiedLinkPlan(
                batch_id=batch_id,
                source_slug=source.slug,
                direct_registry_version=direct_registry_version,
                config_version=config_version,
                configured_direct_links_per_article=configured_direct_links_per_article,
                requested_links=configured_direct_links_per_article,
                selected_links=selected_count,
                selected_entries=tuple(selected),
                shortfall_reason=shortfall_reason,
                status=status,
            )
        )

    requested_total = len(sorted_sources) * configured_direct_links_per_article
    selected_total = sum(plan.selected_links for plan in plans)
    final_status = "PASS" if selected_total == requested_total else "PASS_WITH_SHORTFALL"
    return DirectSpecifiedLinkBatchPlanResult(
        batch_id=batch_id,
        direct_registry_version=direct_registry_version,
        config_version=config_version,
        source_count=len(sorted_sources),
        entry_count=entry_count,
        requested_total=requested_total,
        selected_total=selected_total,
        plans=tuple(plans),
        entry_usage=dict(sorted(usage.items())),
        final_status=final_status,
    )
