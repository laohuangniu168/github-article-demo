from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from direct_specified_link_injector import (
    HTML_LINK_PATTERN,
    INTERNAL_LINK_PATTERN,
    MARKDOWN_LINK_PATTERN,
    NATURAL_ANCHOR,
    NO_SAFE_DIRECT_REFERENCE_POINT,
    VISIBLE_REFERENCE,
    DirectSpecifiedLinkInjectionResult,
    scan_direct_specified_markdown,
)
from direct_specified_link_planner import (
    INSUFFICIENT_UNIQUE_DIRECT_TARGETS,
    DirectSpecifiedLinkPlan,
)
from direct_specified_link_registry import (
    DIRECT_APPROVAL_SOURCE,
    DirectSpecifiedLinkContractError,
    DirectSpecifiedLinkRegistry,
    compute_direct_registry_version,
)


LEGAL_SHORTFALLS = frozenset({INSUFFICIENT_UNIQUE_DIRECT_TARGETS, NO_SAFE_DIRECT_REFERENCE_POINT})
LINK_PARTS = re.compile(r"(?<!!)\[([^\]\r\n]+)\]\(([^\)\r\n]*)\)")


@dataclass(frozen=True)
class DirectSpecifiedLinkAuditEvent:
    code: str
    article_slug: str
    entry_id: str | None
    stage: str
    message: str


@dataclass(frozen=True)
class DirectSpecifiedLinkArticleAudit:
    article_slug: str
    direct_links: int
    natural_anchor_links: int
    visible_reference_links: int
    unique_direct_urls: int
    duplicate_direct_urls: int
    unapproved_urls: int
    url_mismatches: int
    anchor_mismatches: int
    protected_zone_violations: int
    malformed_links: int
    placement_failures: int
    pre_existing_links_mutated: int
    internal_links_mutated: int
    provenance_missing: int
    direct_registry_version: str
    config_version: str
    requested_links: int
    selected_links: int
    placed_links: int
    skipped_links: int
    shortfall_reason: str | None
    errors: tuple[DirectSpecifiedLinkAuditEvent, ...]
    warnings: tuple[DirectSpecifiedLinkAuditEvent, ...]
    final_status: str


@dataclass(frozen=True)
class DirectSpecifiedLinkAuditInput:
    source_slug: str
    batch_id: str
    pre_markdown: str
    post_markdown: str
    plan: DirectSpecifiedLinkPlan
    injection_result: DirectSpecifiedLinkInjectionResult


@dataclass(frozen=True)
class DirectSpecifiedLinkBatchAudit:
    batch_id: str
    source_count: int
    requested_total: int
    selected_total: int
    placed_total: int
    natural_total: int
    reference_total: int
    skipped_total: int
    entry_usage: Mapping[str, int]
    duplicate_article_url_violations: int
    provenance_violations: int
    article_failures: int
    articles: tuple[DirectSpecifiedLinkArticleAudit, ...]
    violations: tuple[DirectSpecifiedLinkAuditEvent, ...]
    final_status: str


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _add(events: list[DirectSpecifiedLinkAuditEvent], code: str, slug: str, stage: str,
         message: str, entry_id: str | None = None) -> None:
    events.append(DirectSpecifiedLinkAuditEvent(code, slug, entry_id, stage, message))


def _ordered_links(pattern: re.Pattern[str], markdown: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in pattern.finditer(markdown))


def _remove_provenance_edits(post: str, placements: Sequence[object]) -> tuple[str, bool]:
    inverse: list[tuple[int, int, str]] = []
    reference_ranges: set[tuple[int, int]] = set()
    ok = True
    for item in placements:
        if item.placement_type == NATURAL_ANCHOR:
            expected = f"[{item.anchor}]({item.url})"
            if not (0 <= item.start <= item.end <= len(post)) or post[item.start:item.end] != expected:
                ok = False
            if (item.start, item.end) != (item.mutation_start, item.mutation_end):
                ok = False
            inverse.append((item.mutation_start, item.mutation_end, item.anchor))
        elif item.placement_type == VISIBLE_REFERENCE:
            expected = f"| 详见 [{item.anchor}]({item.url})"
            if not (0 <= item.start <= item.end <= len(post)) or post[item.start:item.end] != expected:
                ok = False
            reference_ranges.add((item.mutation_start, item.mutation_end))
        else:
            ok = False
    inverse.extend((start, end, "") for start, end in reference_ranges)
    rebuilt = post
    for start, end, replacement in sorted(inverse, reverse=True):
        if not 0 <= start <= end <= len(rebuilt):
            ok = False
            continue
        rebuilt = rebuilt[:start] + replacement + rebuilt[end:]
    return rebuilt, ok


def verify_direct_internal_links_unchanged(
    pre_markdown: str,
    post_markdown: str,
    *,
    placements: Sequence[object] = (),
) -> bool:
    rebuilt, ok = _remove_provenance_edits(post_markdown, placements)
    return ok and _ordered_links(INTERNAL_LINK_PATTERN, pre_markdown) == _ordered_links(INTERNAL_LINK_PATTERN, rebuilt)


def _reference_replacement(text: str, offset: int, lines: Sequence[str], newline: str) -> str:
    before, after = text[:offset], text[offset:]
    prefix = "" if not before or before.endswith(newline + newline) else (newline if before.endswith(newline) else newline + newline)
    suffix = "" if not after or after.startswith(newline + newline) else (newline if after.startswith(newline) else newline + newline)
    return prefix + newline.join(lines) + suffix


def _preservation_code(pre: str, rebuilt: str) -> str:
    if _ordered_links(INTERNAL_LINK_PATTERN, pre) != _ordered_links(INTERNAL_LINK_PATTERN, rebuilt):
        return "INTERNAL_LINK_MUTATED"
    if (_ordered_links(MARKDOWN_LINK_PATTERN, pre) != _ordered_links(MARKDOWN_LINK_PATTERN, rebuilt)
            or _ordered_links(HTML_LINK_PATTERN, pre) != _ordered_links(HTML_LINK_PATTERN, rebuilt)):
        return "PRE_EXISTING_LINK_MUTATED"
    try:
        before, after = scan_direct_specified_markdown(pre), scan_direct_specified_markdown(rebuilt)
        if (before.related_start, before.endraw_start, before.newline) != (after.related_start, after.endraw_start, after.newline):
            return "DIRECT_PROTECTED_ZONE_VIOLATION"
    except DirectSpecifiedLinkContractError:
        return "DIRECT_PROTECTED_ZONE_VIOLATION"
    return "DIRECT_PROTECTED_ZONE_VIOLATION"


def audit_direct_specified_link_article(
    *,
    source_slug: str,
    batch_id: str,
    pre_markdown: str,
    post_markdown: str,
    plan: DirectSpecifiedLinkPlan,
    injection_result: DirectSpecifiedLinkInjectionResult,
    registry: DirectSpecifiedLinkRegistry,
    direct_registry_version: str | None = None,
    config_version: str | None = None,
    protected_slug_set: Iterable[str] = (),
    informational_preflight: object | None = None,
) -> DirectSpecifiedLinkArticleAudit:
    del informational_preflight
    errors: list[DirectSpecifiedLinkAuditEvent] = []
    warnings: list[DirectSpecifiedLinkAuditEvent] = []
    entries = {entry.id: entry for entry in registry.entries}
    caller_version = direct_registry_version or registry.direct_registry_version
    caller_config = config_version or registry.config_version
    recomputed = compute_direct_registry_version(
        registry.entries, schema_version=registry.schema_version, config_version=registry.config_version
    )
    identity = (
        caller_version == recomputed == registry.direct_registry_version == plan.direct_registry_version
        == injection_result.direct_registry_version
        and caller_config == registry.config_version == plan.config_version == injection_result.config_version
        and source_slug == plan.source_slug == injection_result.source_slug
        and batch_id == plan.batch_id == injection_result.batch_id
    )
    if not identity:
        _add(errors, "DIRECT_REGISTRY_VERSION_MISMATCH", source_slug, "identity", "caller/Registry/Plan/Injection identity不一致")
    if source_slug in set(protected_slug_set):
        _add(errors, "EXISTING_PRODUCTION_MUTATION_ATTEMPT", source_slug, "protection", "Existing Production禁止DIRECT mutation")
    if injection_result.pre_sha256 != _sha(pre_markdown):
        _add(errors, "DIRECT_PROVENANCE_MISSING", source_slug, "sha", "pre SHA不匹配")
    if injection_result.post_sha256 != _sha(post_markdown):
        _add(errors, "POST_INJECTION_SHA_MISMATCH", source_slug, "sha", "post SHA不匹配")
    if plan.selected_links != len(plan.selected_entries) or plan.requested_links != plan.configured_direct_links_per_article:
        _add(errors, "DIRECT_PROVENANCE_MISSING", source_slug, "plan", "Plan count无法闭合")

    selected = {item.entry_id: item for item in plan.selected_entries}
    requested = injection_result.requested_entries
    if len(requested) != plan.selected_links:
        _add(errors, "DIRECT_PROVENANCE_MISSING", source_slug, "injection", "requested与selected数量不闭合")
    for item in requested:
        chosen, entry = selected.get(item.entry_id), entries.get(item.entry_id)
        expected = None if entry is None else (
            entry.url, entry.canonical_url, entry.anchor, entry.normalized_anchor, entry.approval_source
        )
        actual = (item.url, item.canonical_url, item.anchor, item.normalized_anchor, item.approval_source)
        if chosen is None or expected != actual or not entry or entry.approval_source != DIRECT_APPROVAL_SOURCE:
            _add(errors, "DIRECT_PROVENANCE_MISSING", source_slug, "requested", "requested缺少USER_INPUT Registry provenance", item.entry_id)
        elif not entry.source_filename or entry.source_line < 1:
            _add(errors, "DIRECT_PROVENANCE_MISSING", source_slug, "registry", "source file/line不可追溯", item.entry_id)

    placed_ids = [item.entry_id for item in injection_result.placed_entries]
    skipped_ids = [item.entry_id for item in injection_result.skipped_entries]
    if Counter(placed_ids + skipped_ids) != Counter(item.entry_id for item in requested):
        _add(errors, "DIRECT_PROVENANCE_MISSING", source_slug, "closure", "placed/skipped/requested不闭合")

    urls: list[str] = []
    natural = reference = 0
    for item in injection_result.placed_entries:
        entry, chosen = entries.get(item.entry_id), selected.get(item.entry_id)
        if entry is None or chosen is None:
            _add(errors, "UNAPPROVED_DIRECT_URL", source_slug, "placement", "entry不在Registry或Plan", item.entry_id)
            continue
        urls.append(item.url)
        if item.url != entry.url or chosen.url != entry.url:
            _add(errors, "DIRECT_URL_MISMATCH", source_slug, "placement", "URL未逐字符保持Registry identity", item.entry_id)
        if item.anchor != entry.anchor or chosen.anchor != entry.anchor:
            _add(errors, "DIRECT_ANCHOR_MISMATCH", source_slug, "placement", "anchor未逐字符保持Registry identity", item.entry_id)
        expected = f"[{entry.anchor}]({entry.url})"
        if not (0 <= item.start <= item.end <= len(post_markdown)) or post_markdown[item.start:item.end] not in (expected, "| 详见 " + expected):
            _add(errors, "DIRECT_PLACEMENT_MISMATCH", source_slug, "placement", "placement span未命中精确markup", item.entry_id)
        if item.placement_type == NATURAL_ANCHOR:
            natural += 1
            if not item.natural_anchor_found or item.paragraph_index is None or item.reference_index is not None:
                _add(errors, "DIRECT_PLACEMENT_MISMATCH", source_slug, "natural", "Natural provenance字段非法", item.entry_id)
        elif item.placement_type == VISIBLE_REFERENCE:
            reference += 1
            if item.natural_anchor_found or item.paragraph_index is not None or item.reference_index is None:
                _add(errors, "DIRECT_PLACEMENT_MISMATCH", source_slug, "reference", "Reference provenance字段非法", item.entry_id)
        else:
            _add(errors, "DIRECT_PLACEMENT_MISMATCH", source_slug, "placement", "未知placement type", item.entry_id)

    duplicate_urls = sum(value - 1 for value in Counter(urls).values() if value > 1)
    if duplicate_urls:
        _add(errors, "UNAPPROVED_DIRECT_URL", source_slug, "article", "同一article canonical URL重复")

    expected_injected = Counter(f"[{item.anchor}]({item.url})" for item in injection_result.placed_entries)
    unexpected_links = Counter(_ordered_links(MARKDOWN_LINK_PATTERN, post_markdown)) - (
        Counter(_ordered_links(MARKDOWN_LINK_PATTERN, pre_markdown)) + expected_injected
    )
    if unexpected_links:
        _add(errors, "UNAPPROVED_DIRECT_URL", source_slug, "markdown", "post含Registry/Plan之外的新增Markdown link")

    rebuilt, placement_ok = _remove_provenance_edits(post_markdown, injection_result.placed_entries)
    if not placement_ok:
        _add(errors, "MALFORMED_DIRECT_LINK", source_slug, "syntax", "DIRECT link/reference语法或offset损坏")
    if rebuilt != pre_markdown:
        code = _preservation_code(pre_markdown, rebuilt)
        _add(errors, code, source_slug, "preservation", "移除DIRECT mutations后无法逐字符恢复baseline")
        _add(errors, "DIRECT_BASELINE_RECONSTRUCTION_FAILED", source_slug, "reconstruction", "baseline reconstruction失败")
    if not verify_direct_internal_links_unchanged(pre_markdown, post_markdown, placements=injection_result.placed_entries):
        if not any(event.code == "INTERNAL_LINK_MUTATED" for event in errors):
            _add(errors, "INTERNAL_LINK_MUTATED", source_slug, "preservation", "Internal Link anchor/URL/count/order变化")

    if reference:
        scan = scan_direct_specified_markdown(pre_markdown)
        refs = sorted((item for item in injection_result.placed_entries if item.placement_type == VISIBLE_REFERENCE),
                      key=lambda item: item.reference_index)
        expected_lines = [f"| 详见 [{item.anchor}]({item.url})" for item in refs]
        expected_replacement = _reference_replacement(pre_markdown, scan.reference_offset, expected_lines, scan.newline)
        ranges = {(item.mutation_start, item.mutation_end) for item in refs}
        if len(ranges) != 1:
            _add(errors, "DIRECT_PLACEMENT_MISMATCH", source_slug, "reference", "Reference mutation range不唯一")
        else:
            start, end = next(iter(ranges))
            if post_markdown[start:end] != expected_replacement:
                _add(errors, "DIRECT_PROTECTED_ZONE_VIOLATION", source_slug, "reference", "Reference位置/格式不符合D4规则")

    pre_md = Counter(_ordered_links(MARKDOWN_LINK_PATTERN, pre_markdown))
    rebuilt_md = Counter(_ordered_links(MARKDOWN_LINK_PATTERN, rebuilt))
    pre_html = _ordered_links(HTML_LINK_PATTERN, pre_markdown)
    rebuilt_html = _ordered_links(HTML_LINK_PATTERN, rebuilt)
    if pre_md != rebuilt_md or pre_html != rebuilt_html:
        if not any(event.code == "PRE_EXISTING_LINK_MUTATED" for event in errors):
            _add(errors, "PRE_EXISTING_LINK_MUTATED", source_slug, "preservation", "Existing Markdown/HTML links变化")

    planner_shortfall = plan.shortfall_reason if plan.selected_links < plan.requested_links else None
    injector_shortfall = NO_SAFE_DIRECT_REFERENCE_POINT if injection_result.skipped_entries else None
    shortfall = injector_shortfall or planner_shortfall
    warning_strings = set(injection_result.warnings)
    shortfall_ok = (
        shortfall in LEGAL_SHORTFALLS
        and injection_result.shortfall_reason == shortfall
        and (not planner_shortfall or f"PLANNER_SHORTFALL:{planner_shortfall}" in warning_strings)
        and (not injector_shortfall or f"PLACEMENT_SHORTFALL:{injector_shortfall}" in warning_strings)
        and all(item.reason == NO_SAFE_DIRECT_REFERENCE_POINT for item in injection_result.skipped_entries)
    )
    if shortfall is None:
        if injection_result.shortfall_reason is not None or plan.shortfall_reason is not None or injection_result.skipped_entries:
            _add(errors, "DIRECT_PROVENANCE_MISSING", source_slug, "shortfall", "伪造shortfall evidence")
        status = "PASS"
    elif shortfall_ok:
        warnings.append(DirectSpecifiedLinkAuditEvent(shortfall, source_slug, None, "shortfall", "合法shortfall provenance"))
        status = "PASS_WITH_SHORTFALL"
    else:
        _add(errors, "DIRECT_PROVENANCE_MISSING", source_slug, "shortfall", "shortfall provenance不闭合")
        status = "FAIL"
    if errors:
        status = "FAIL"
    codes = Counter(event.code for event in errors)
    return DirectSpecifiedLinkArticleAudit(
        source_slug, len(injection_result.placed_entries), natural, reference, len(set(urls)), duplicate_urls,
        codes["UNAPPROVED_DIRECT_URL"], codes["DIRECT_URL_MISMATCH"], codes["DIRECT_ANCHOR_MISMATCH"],
        codes["DIRECT_PROTECTED_ZONE_VIOLATION"], codes["MALFORMED_DIRECT_LINK"],
        codes["DIRECT_PLACEMENT_MISMATCH"], codes["PRE_EXISTING_LINK_MUTATED"], codes["INTERNAL_LINK_MUTATED"],
        codes["DIRECT_PROVENANCE_MISSING"], registry.direct_registry_version, registry.config_version,
        plan.requested_links, plan.selected_links, len(injection_result.placed_entries),
        len(injection_result.skipped_entries), shortfall, tuple(errors), tuple(warnings), status,
    )


def audit_direct_specified_link_batch(
    audit_inputs: Sequence[DirectSpecifiedLinkAuditInput],
    *,
    registry: DirectSpecifiedLinkRegistry,
    direct_registry_version: str | None = None,
    config_version: str | None = None,
    protected_slug_set: Iterable[str] = (),
) -> DirectSpecifiedLinkBatchAudit:
    articles = tuple(audit_direct_specified_link_article(
        source_slug=item.source_slug, batch_id=item.batch_id, pre_markdown=item.pre_markdown,
        post_markdown=item.post_markdown, plan=item.plan, injection_result=item.injection_result,
        registry=registry, direct_registry_version=direct_registry_version, config_version=config_version,
        protected_slug_set=protected_slug_set,
    ) for item in audit_inputs)
    batch_ids = {item.batch_id for item in audit_inputs}
    violations: list[DirectSpecifiedLinkAuditEvent] = []
    if len(batch_ids) > 1:
        _add(violations, "DIRECT_PROVENANCE_MISSING", "<batch>", "batch", "batch_id不唯一")
    usage: dict[str, int] = defaultdict(int)
    for item in audit_inputs:
        for placed in item.injection_result.placed_entries:
            usage[placed.entry_id] += 1
    failures = sum(article.final_status == "FAIL" for article in articles)
    status = "FAIL" if failures or violations else (
        "PASS_WITH_SHORTFALL" if any(article.final_status == "PASS_WITH_SHORTFALL" for article in articles) else "PASS"
    )
    return DirectSpecifiedLinkBatchAudit(
        next(iter(batch_ids), ""), len(audit_inputs), sum(a.requested_links for a in articles),
        sum(a.selected_links for a in articles), sum(a.placed_links for a in articles),
        sum(a.natural_anchor_links for a in articles), sum(a.visible_reference_links for a in articles),
        sum(a.skipped_links for a in articles), dict(sorted(usage.items())),
        sum(a.duplicate_direct_urls for a in articles), sum(a.provenance_missing for a in articles), failures,
        articles, tuple(violations), status,
    )
