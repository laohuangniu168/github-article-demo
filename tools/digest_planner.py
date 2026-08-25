from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Sequence

from digest_registry import (
    DIGEST_CONFIG_VERSION,
    DigestRegistry,
    DigestRegistryEntry,
    compute_digest_registry_version,
)


MIN_DIGEST_ENTRIES = 20
MAX_DIGEST_ENTRIES = 150
DEFAULT_LINKS_PER_DIGEST = 50
FINAL_STATUS_PASS = "PASS"

_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class DigestArticlePlan:
    batch_id: str
    digest_index: int
    digest_id: str
    filename: str
    digest_registry_version: str
    config_version: str
    entry_count: int
    entry_ids: tuple[str, ...]
    entry_identities: tuple[str, ...]
    plan_hash: str


@dataclass(frozen=True)
class DigestBatchPlanResult:
    batch_id: str
    digest_registry_version: str
    config_version: str
    registry_entry_count: int
    planned_entry_count: int
    digest_count: int
    plans: tuple[DigestArticlePlan, ...]
    distribution: tuple[int, ...]
    final_status: str


class DigestPlannerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise DigestPlannerError(code, message)


def _validate_batch_id(batch_id: str) -> None:
    if (
        not isinstance(batch_id, str)
        or not batch_id
        or batch_id != batch_id.strip()
        or _CONTROL_PATTERN.search(batch_id)
    ):
        _fail("INVALID_DIGEST_PLANNER_CONFIG", "batch_id 必须是非空、无外围空白或控制字符的字符串")


def _validate_registry(registry: DigestRegistry) -> tuple[DigestRegistryEntry, ...]:
    entries = tuple(sorted(registry.entries, key=lambda item: item.normalized_identity))
    ids = [entry.id for entry in entries]
    identities = [entry.normalized_identity for entry in entries]
    if len(ids) != len(set(ids)) or len(identities) != len(set(identities)):
        _fail("DIGEST_ENTRY_DUPLICATION", "Registry 包含重复 entry id 或 identity")
    expected_version = compute_digest_registry_version(
        entries,
        schema_version=registry.schema_version,
        config_version=registry.config_version,
    )
    if expected_version != registry.digest_registry_version:
        _fail("DIGEST_REGISTRY_VERSION_MISMATCH", "Registry payload 与 digest_registry_version 不一致")
    if len(entries) < MIN_DIGEST_ENTRIES:
        _fail(
            "INSUFFICIENT_DIGEST_ENTRIES",
            f"Digest Planner 至少需要 {MIN_DIGEST_ENTRIES} entries",
        )
    return entries


def _balanced_distribution(total: int, count: int) -> tuple[int, ...]:
    base, remainder = divmod(total, count)
    distribution = tuple(base + (1 if index < remainder else 0) for index in range(count))
    if min(distribution) < MIN_DIGEST_ENTRIES or max(distribution) > MAX_DIGEST_ENTRIES:
        _fail(
            "DIGEST_DISTRIBUTION_IMPOSSIBLE",
            f"无法将 {total} entries 分为 {count} 篇且每篇保持 20-150",
        )
    return distribution


def _distribution_by_links(total: int, links_per_digest: int) -> tuple[int, ...]:
    count, remainder = divmod(total, links_per_digest)
    if remainder:
        count += 1
    if count == 1:
        return (total,)
    if remainder == 0 or remainder >= MIN_DIGEST_ENTRIES:
        return (links_per_digest,) * (count - 1) + ((remainder,) if remainder else (links_per_digest,))
    return _balanced_distribution(total, count)


def _validate_parameters(
    links_per_digest: int | None,
    digest_count: int | None,
) -> None:
    if links_per_digest is not None and digest_count is not None:
        _fail("INVALID_DIGEST_PLANNER_CONFIG", "links_per_digest 与 digest_count 互斥")
    if links_per_digest is not None and (
        isinstance(links_per_digest, bool)
        or not isinstance(links_per_digest, int)
        or not MIN_DIGEST_ENTRIES <= links_per_digest <= MAX_DIGEST_ENTRIES
    ):
        _fail("INVALID_DIGEST_PLANNER_CONFIG", "links_per_digest 必须为 20-150 整数")
    if digest_count is not None and (
        isinstance(digest_count, bool) or not isinstance(digest_count, int) or digest_count <= 0
    ):
        _fail("INVALID_DIGEST_PLANNER_CONFIG", "digest_count 必须为正整数")


def _batch_hash(batch_id: str, registry_version: str, config_version: str) -> str:
    payload = {
        "batch_id": batch_id,
        "config_version": config_version,
        "digest_registry_version": registry_version,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:8]


def _plan_hash(
    *,
    batch_id: str,
    digest_index: int,
    digest_id: str,
    filename: str,
    digest_registry_version: str,
    config_version: str,
    entry_ids: Sequence[str],
) -> str:
    payload = {
        "batch_id": batch_id,
        "config_version": config_version,
        "digest_id": digest_id,
        "digest_index": digest_index,
        "digest_registry_version": digest_registry_version,
        "entry_ids": list(entry_ids),
        "filename": filename,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def plan_digest_articles(
    registry: DigestRegistry,
    *,
    batch_id: str,
    links_per_digest: int | None = None,
    digest_count: int | None = None,
    digest_registry_version: str,
    config_version: str,
) -> DigestBatchPlanResult:
    if not isinstance(registry, DigestRegistry):
        _fail("INVALID_DIGEST_PLANNER_CONFIG", "registry 必须是 DigestRegistry")
    _validate_batch_id(batch_id)
    _validate_parameters(links_per_digest, digest_count)
    if digest_registry_version != registry.digest_registry_version:
        _fail("DIGEST_REGISTRY_VERSION_MISMATCH", "调用方 Registry Version 与 Registry 不一致")
    if config_version != DIGEST_CONFIG_VERSION or config_version != registry.config_version:
        _fail("INVALID_DIGEST_PLANNER_CONFIG", "config_version 不匹配")

    entries = _validate_registry(registry)
    total = len(entries)
    implicit_default = links_per_digest is None and digest_count is None
    if digest_count is not None:
        distribution = _balanced_distribution(total, digest_count)
    elif implicit_default and total <= MAX_DIGEST_ENTRIES:
        distribution = (total,)
    else:
        target = DEFAULT_LINKS_PER_DIGEST if links_per_digest is None else links_per_digest
        distribution = _distribution_by_links(total, target)

    prefix = _batch_hash(batch_id, digest_registry_version, config_version)
    plans: list[DigestArticlePlan] = []
    offset = 0
    for digest_index, entry_count in enumerate(distribution, start=1):
        assigned = entries[offset : offset + entry_count]
        offset += entry_count
        digest_id = f"digest-{digest_index:03d}"
        filename = f"digest-{prefix}-{digest_index:03d}.md"
        entry_ids = tuple(entry.id for entry in assigned)
        identities = tuple(entry.normalized_identity for entry in assigned)
        plans.append(
            DigestArticlePlan(
                batch_id=batch_id,
                digest_index=digest_index,
                digest_id=digest_id,
                filename=filename,
                digest_registry_version=digest_registry_version,
                config_version=config_version,
                entry_count=entry_count,
                entry_ids=entry_ids,
                entry_identities=identities,
                plan_hash=_plan_hash(
                    batch_id=batch_id,
                    digest_index=digest_index,
                    digest_id=digest_id,
                    filename=filename,
                    digest_registry_version=digest_registry_version,
                    config_version=config_version,
                    entry_ids=entry_ids,
                ),
            )
        )

    planned_ids = [entry_id for plan in plans for entry_id in plan.entry_ids]
    registry_ids = [entry.id for entry in entries]
    if len(planned_ids) != len(set(planned_ids)):
        _fail("DIGEST_ENTRY_DUPLICATION", "Plan 包含重复 entry")
    if planned_ids != registry_ids:
        _fail("DIGEST_ENTRY_MISSING", "Plan 未完整覆盖 Registry canonical order")
    return DigestBatchPlanResult(
        batch_id=batch_id,
        digest_registry_version=digest_registry_version,
        config_version=config_version,
        registry_entry_count=total,
        planned_entry_count=len(planned_ids),
        digest_count=len(plans),
        plans=tuple(plans),
        distribution=distribution,
        final_status=FINAL_STATUS_PASS,
    )
