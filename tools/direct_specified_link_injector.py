from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from direct_specified_link_planner import (
    INSUFFICIENT_UNIQUE_DIRECT_TARGETS,
    DirectSelectedEntry,
    DirectSpecifiedLinkPlan,
    compute_direct_distribution_seed,
)
from direct_specified_link_registry import (
    DIRECT_APPROVAL_SOURCE,
    DIRECT_CONFIG_VERSION,
    DirectSpecifiedLinkContractError,
    DirectSpecifiedLinkRegistry,
    validate_direct_registry,
)


NATURAL_ANCHOR = "NATURAL_ANCHOR"
VISIBLE_REFERENCE = "VISIBLE_REFERENCE"
NO_SAFE_DIRECT_REFERENCE_POINT = "NO_SAFE_DIRECT_REFERENCE_POINT"

HEADING_PATTERN = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
FENCE_PATTERN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]\r\n]+\]\([^\)\r\n]*\)")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]\r\n]*\]\([^\)\r\n]*\)")
HTML_LINK_PATTERN = re.compile(r"<a\b[^>]*>.*?</a\s*>", re.IGNORECASE | re.DOTALL)
HTML_TAG_PATTERN = re.compile(r"</?[A-Za-z][^>\r\n]*>")
INLINE_CODE_PATTERN = re.compile(r"(`+)[^\r\n]*?\1")
LIQUID_PATTERN = re.compile(r"(?:\{\{.*?\}\}|\{%.*?%\})")
BARE_URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>()]+")
INTERNAL_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]\r\n]+\]\(\./[^\)\r\n]+\.html\)")


@dataclass(frozen=True)
class DirectParagraph:
    index: int
    start: int
    end: int
    text: str
    eligible: bool


@dataclass(frozen=True)
class DirectMarkdownScanResult:
    paragraphs: tuple[DirectParagraph, ...]
    reference_offset: int
    newline: str
    related_start: int | None
    endraw_start: int | None


@dataclass(frozen=True)
class DirectRequestedEntry:
    entry_id: str
    url: str
    canonical_url: str
    anchor: str
    normalized_anchor: str
    approval_source: str


@dataclass(frozen=True)
class DirectPlacedEntry:
    entry_id: str
    url: str
    anchor: str
    placement_type: str
    paragraph_index: int | None
    reference_index: int | None
    start: int
    end: int
    mutation_start: int
    mutation_end: int
    natural_anchor_found: bool


@dataclass(frozen=True)
class DirectSkippedEntry:
    entry_id: str
    reason: str


@dataclass(frozen=True)
class DirectSpecifiedLinkInjectionResult:
    batch_id: str
    source_slug: str
    direct_registry_version: str
    config_version: str
    requested_entries: tuple[DirectRequestedEntry, ...]
    placed_entries: tuple[DirectPlacedEntry, ...]
    skipped_entries: tuple[DirectSkippedEntry, ...]
    pre_sha256: str
    post_sha256: str
    status: str
    shortfall_reason: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class DirectSpecifiedLinkInjectionOutcome:
    markdown: str
    result: DirectSpecifiedLinkInjectionResult


@dataclass(frozen=True)
class _Edit:
    entry: DirectSelectedEntry
    placement_type: str
    baseline_start: int
    baseline_end: int
    replacement: str
    content_start: int
    content_end: int
    paragraph_index: int | None
    reference_index: int | None


def _fail(code: str, message: str, *, entry_id: str | None = None) -> None:
    raise DirectSpecifiedLinkContractError(code, message, entry_id=entry_id)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line_records(text: str) -> list[tuple[int, int, str]]:
    records: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        records.append((offset, offset + len(content), content))
        offset += len(line)
    if not records and text == "":
        return []
    if offset < len(text):
        records.append((offset, len(text), text[offset:]))
    return records


def scan_direct_specified_markdown(text: str) -> DirectMarkdownScanResult:
    newline = "\r\n" if "\r\n" in text else "\n"
    records = _line_records(text)
    front_end = -1
    if records and records[0][2].strip() == "---":
        for index in range(1, len(records)):
            if records[index][2].strip() == "---":
                front_end = index
                break
        if front_end == -1:
            _fail("DIRECT_MARKDOWN_UNSAFE", "YAML Front Matter 未闭合")

    paragraphs: list[DirectParagraph] = []
    fence_marker: str | None = None
    html_comment = False
    raw_depth = 0
    raw_seen = False
    related = False
    related_start: int | None = None
    endraw_start: int | None = None

    for index, (start, end, line) in enumerate(records):
        stripped = line.strip()
        protected = index <= front_end
        fence_match = FENCE_PATTERN.match(line)
        in_container = False
        if fence_marker is not None:
            protected = True
            in_container = True
            if fence_match and fence_match.group(1)[0] == fence_marker[0] and len(fence_match.group(1)) >= len(fence_marker):
                fence_marker = None
        elif not protected and fence_match:
            protected = True
            in_container = True
            fence_marker = fence_match.group(1)

        if not in_container:
            if html_comment:
                protected = True
                in_container = True
                if "-->" in line:
                    html_comment = False
            elif not protected and "<!--" in line:
                protected = True
                in_container = True
                if "-->" not in line.split("<!--", 1)[1]:
                    html_comment = True

        if not in_container and not protected:
            raw_open = "{% raw %}" in line
            raw_close = "{% endraw %}" in line
            if raw_open or raw_close:
                protected = True
                if raw_open:
                    if raw_depth != 0 or raw_seen:
                        _fail("DIRECT_MARKDOWN_UNSAFE", "raw 标签嵌套或重复")
                    raw_depth = 1
                    raw_seen = True
                if raw_close:
                    if raw_depth != 1:
                        _fail("DIRECT_MARKDOWN_UNSAFE", "endraw 缺少匹配 raw")
                    raw_depth = 0
                    endraw_start = start

            if stripped == "## 相关阅读":
                related = True
                related_start = start
            if HEADING_PATTERN.match(line):
                protected = True
            if "{%" in line or "{{" in line:
                if not LIQUID_PATTERN.search(line):
                    _fail("DIRECT_MARKDOWN_UNSAFE", "Liquid 结构无法安全判断")
                protected = True
            token_patterns = (
                MARKDOWN_LINK_PATTERN,
                MARKDOWN_IMAGE_PATTERN,
                HTML_TAG_PATTERN,
                INLINE_CODE_PATTERN,
                BARE_URL_PATTERN,
            )
            if any(pattern.search(line) for pattern in token_patterns):
                protected = True
        if related:
            protected = True
        if stripped:
            paragraphs.append(DirectParagraph(len(paragraphs), start, end, line, not protected))

    if fence_marker is not None:
        _fail("DIRECT_MARKDOWN_UNSAFE", "fenced code block 未闭合")
    if html_comment:
        _fail("DIRECT_MARKDOWN_UNSAFE", "HTML comment 未闭合")
    if raw_depth != 0:
        _fail("DIRECT_MARKDOWN_UNSAFE", "raw/endraw 未闭合")
    if raw_seen and endraw_start is None:
        _fail("DIRECT_MARKDOWN_UNSAFE", "raw/endraw 边界不完整")

    if related_start is not None:
        reference_offset = related_start
    elif endraw_start is not None:
        reference_offset = endraw_start
    else:
        reference_offset = len(text)
    return DirectMarkdownScanResult(tuple(paragraphs), reference_offset, newline, related_start, endraw_start)


def _validate_identity(
    *,
    source_slug: str,
    plan: DirectSpecifiedLinkPlan,
    registry: DirectSpecifiedLinkRegistry,
    batch_id: str,
    direct_registry_version: str,
    config_version: str,
) -> tuple[DirectSelectedEntry, ...]:
    try:
        validate_direct_registry(registry, expected_version=direct_registry_version)
    except DirectSpecifiedLinkContractError as exc:
        _fail("DIRECT_REGISTRY_VERSION_MISMATCH", exc.message)
    identities = (
        plan.batch_id == batch_id,
        plan.source_slug == source_slug,
        plan.direct_registry_version == direct_registry_version,
        registry.direct_registry_version == direct_registry_version,
        plan.config_version == config_version,
        registry.config_version == config_version == DIRECT_CONFIG_VERSION,
        plan.selected_links == len(plan.selected_entries),
        plan.requested_links == plan.configured_direct_links_per_article,
        0 <= plan.selected_links <= plan.requested_links,
    )
    if not all(identities):
        _fail("DIRECT_REGISTRY_VERSION_MISMATCH", "caller、Plan、Registry identity/count 不一致")

    entries = {entry.id: entry for entry in registry.entries}
    sorted_ids = {entry.id: index for index, entry in enumerate(sorted(registry.entries, key=lambda item: item.id))}
    seed = compute_direct_distribution_seed(
        batch_id=batch_id,
        direct_registry_version=direct_registry_version,
        config_version=config_version,
    )
    urls: set[str] = set()
    for selected in plan.selected_entries:
        entry = entries.get(selected.entry_id)
        if entry is None:
            _fail("UNAPPROVED_DIRECT_URL", "Plan entry 不存在于DIRECT Registry", entry_id=selected.entry_id)
        expected = (
            entry.canonical_url,
            entry.url,
            entry.anchor,
            entry.normalized_anchor,
            entry.approval_source,
            sorted_ids[entry.id],
        )
        actual = (
            selected.canonical_url,
            selected.url,
            selected.anchor,
            selected.normalized_anchor,
            selected.approval_source,
            selected.registry_index,
        )
        deterministic_key = hashlib.sha256(
            f"{seed}\n{source_slug}\n{selected.entry_id}\n{selected.distribution_index}".encode("utf-8")
        ).hexdigest()
        if actual != expected or selected.deterministic_key != deterministic_key or entry.approval_source != DIRECT_APPROVAL_SOURCE:
            _fail("UNAPPROVED_DIRECT_URL", "Plan entry identity/provenance 与Registry不一致", entry_id=entry.id)
        if entry.canonical_url in urls:
            _fail("UNAPPROVED_DIRECT_URL", "同一文章canonical URL重复", entry_id=entry.id)
        urls.add(entry.canonical_url)
    return tuple(plan.selected_entries)


def _find_natural_anchor(
    entry: DirectSelectedEntry,
    scan: DirectMarkdownScanResult,
    used_spans: Sequence[tuple[int, int]],
) -> tuple[int, int, int] | None:
    for paragraph in scan.paragraphs:
        if not paragraph.eligible:
            continue
        search = paragraph.start
        while search < paragraph.end:
            position = paragraph.text.find(entry.anchor, search - paragraph.start)
            if position == -1:
                break
            start = paragraph.start + position
            end = start + len(entry.anchor)
            if not any(start < used_end and end > used_start for used_start, used_end in used_spans):
                return paragraph.index, start, end
            search = end
    return None


def _reference_replacement(text: str, offset: int, lines: Sequence[str], newline: str) -> tuple[str, list[tuple[int, int]]]:
    before = text[:offset]
    after = text[offset:]
    prefix = "" if not before or before.endswith(newline + newline) else (newline if before.endswith(newline) else newline + newline)
    suffix = "" if not after or after.startswith(newline + newline) else (newline if after.startswith(newline) else newline + newline)
    body = newline.join(lines)
    replacement = prefix + body + suffix
    spans: list[tuple[int, int]] = []
    cursor = len(prefix)
    for line in lines:
        spans.append((cursor, cursor + len(line)))
        cursor += len(line) + len(newline)
    return replacement, spans


def _existing_link_counters(markdown: str) -> tuple[Counter[str], Counter[str], Counter[str]]:
    return (
        Counter(match.group(0) for match in MARKDOWN_LINK_PATTERN.finditer(markdown)),
        Counter(match.group(0) for match in HTML_LINK_PATTERN.finditer(markdown)),
        Counter(match.group(0) for match in INTERNAL_LINK_PATTERN.finditer(markdown)),
    )


def inject_direct_specified_links(
    *,
    source_slug: str,
    markdown: str,
    plan: DirectSpecifiedLinkPlan,
    registry: DirectSpecifiedLinkRegistry,
    batch_id: str,
    direct_registry_version: str,
    config_version: str,
    protected_slug_set: Iterable[str] = (),
) -> DirectSpecifiedLinkInjectionOutcome:
    if source_slug in set(protected_slug_set):
        _fail("EXISTING_PRODUCTION_MUTATION_ATTEMPT", "Existing Production禁止DIRECT注入")
    selected = _validate_identity(
        source_slug=source_slug,
        plan=plan,
        registry=registry,
        batch_id=batch_id,
        direct_registry_version=direct_registry_version,
        config_version=config_version,
    )
    scan = scan_direct_specified_markdown(markdown)
    requested = tuple(
        DirectRequestedEntry(
            entry.entry_id,
            entry.url,
            entry.canonical_url,
            entry.anchor,
            entry.normalized_anchor,
            entry.approval_source,
        )
        for entry in selected
    )

    edits: list[_Edit] = []
    used_spans: list[tuple[int, int]] = []
    references: list[DirectSelectedEntry] = []
    for entry in selected:
        natural = _find_natural_anchor(entry, scan, used_spans)
        if natural is None:
            references.append(entry)
            continue
        paragraph_index, start, end = natural
        markup = f"[{entry.anchor}]({entry.url})"
        edits.append(_Edit(entry, NATURAL_ANCHOR, start, end, markup, 0, len(markup), paragraph_index, None))
        used_spans.append((start, end))

    if references:
        lines = [f"| 详见 [{entry.anchor}]({entry.url})" for entry in references]
        replacement, spans = _reference_replacement(markdown, scan.reference_offset, lines, scan.newline)
        for reference_index, (entry, (start, end)) in enumerate(zip(references, spans)):
            edits.append(
                _Edit(
                    entry,
                    VISIBLE_REFERENCE,
                    scan.reference_offset,
                    scan.reference_offset,
                    replacement if reference_index == 0 else "",
                    start,
                    end,
                    None,
                    reference_index,
                )
            )

    primary_edits = [edit for edit in edits if edit.placement_type == NATURAL_ANCHOR or edit.reference_index == 0]
    primary_edits.sort(key=lambda edit: (edit.baseline_start, edit.baseline_end))
    output_parts: list[str] = []
    cursor = 0
    placement_positions: dict[str, tuple[int, int, int, int]] = {}
    for edit in primary_edits:
        if edit.baseline_start < cursor:
            _fail("DIRECT_MARKDOWN_UNSAFE", "DIRECT placement发生重叠")
        output_parts.append(markdown[cursor : edit.baseline_start])
        post_mutation_start = sum(len(part) for part in output_parts)
        output_parts.append(edit.replacement)
        post_mutation_end = post_mutation_start + len(edit.replacement)
        if edit.placement_type == NATURAL_ANCHOR:
            placement_positions[edit.entry.entry_id] = (
                post_mutation_start,
                post_mutation_end,
                post_mutation_start,
                post_mutation_end,
            )
        else:
            for reference_edit in (item for item in edits if item.placement_type == VISIBLE_REFERENCE):
                placement_positions[reference_edit.entry.entry_id] = (
                    post_mutation_start + reference_edit.content_start,
                    post_mutation_start + reference_edit.content_end,
                    post_mutation_start,
                    post_mutation_end,
                )
        cursor = edit.baseline_end
    output_parts.append(markdown[cursor:])
    output = "".join(output_parts)

    placed: list[DirectPlacedEntry] = []
    edit_by_id = {edit.entry.entry_id: edit for edit in edits}
    for entry in selected:
        edit = edit_by_id[entry.entry_id]
        start, end, mutation_start, mutation_end = placement_positions[entry.entry_id]
        placed.append(
            DirectPlacedEntry(
                entry.entry_id,
                entry.url,
                entry.anchor,
                edit.placement_type,
                edit.paragraph_index,
                edit.reference_index,
                start,
                end,
                mutation_start,
                mutation_end,
                edit.placement_type == NATURAL_ANCHOR,
            )
        )

    pre_md, pre_html, pre_internal = _existing_link_counters(markdown)
    post_md, post_html, post_internal = _existing_link_counters(output)
    injected = Counter(f"[{entry.anchor}]({entry.url})" for entry in selected)
    if post_md - injected != pre_md or post_html != pre_html:
        _fail("PRE_EXISTING_LINK_MUTATED", "Existing Markdown/HTML links发生变化")
    if post_internal != pre_internal:
        _fail("INTERNAL_LINK_MUTATED", "Existing Internal Links发生变化")

    reversed_output = output
    reference_ranges = {
        (item.mutation_start, item.mutation_end)
        for item in placed
        if item.placement_type == VISIBLE_REFERENCE
    }
    inverse: list[tuple[int, int, str]] = [
        (item.mutation_start, item.mutation_end, item.anchor)
        for item in placed
        if item.placement_type == NATURAL_ANCHOR
    ]
    inverse.extend((start, end, "") for start, end in reference_ranges)
    for start, end, replacement in sorted(inverse, reverse=True):
        reversed_output = reversed_output[:start] + replacement + reversed_output[end:]
    if reversed_output != markdown:
        _fail("DIRECT_MARKDOWN_UNSAFE", "移除DIRECT edits后无法精确恢复baseline")

    warnings: list[str] = []
    if plan.status == "PASS_WITH_SHORTFALL" and plan.shortfall_reason == INSUFFICIENT_UNIQUE_DIRECT_TARGETS:
        warnings.append(f"PLANNER_SHORTFALL:{INSUFFICIENT_UNIQUE_DIRECT_TARGETS}")
    skipped: tuple[DirectSkippedEntry, ...] = ()
    status = "PASS" if not warnings else "PASS_WITH_SHORTFALL"
    shortfall_reason = plan.shortfall_reason if warnings else None
    result = DirectSpecifiedLinkInjectionResult(
        batch_id=batch_id,
        source_slug=source_slug,
        direct_registry_version=direct_registry_version,
        config_version=config_version,
        requested_entries=requested,
        placed_entries=tuple(placed),
        skipped_entries=skipped,
        pre_sha256=_sha(markdown),
        post_sha256=_sha(output),
        status=status,
        shortfall_reason=shortfall_reason,
        warnings=tuple(warnings),
    )
    return DirectSpecifiedLinkInjectionOutcome(output, result)
