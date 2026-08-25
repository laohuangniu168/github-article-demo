from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from specified_link_planner import SpecifiedLinkPlan, SpecifiedLinkSelectedEntry
from specified_link_registry import (
    ALLOWED_CLUSTERS,
    SpecifiedLinkContractError,
    SpecifiedLinkRegistry,
    SpecifiedLinkSpec,
    compute_specified_link_version,
)


@dataclass(frozen=True)
class SpecifiedLinkTokenSpan:
    kind: str
    start: int
    end: int
    paragraph_index: int | None
    text: str


@dataclass(frozen=True)
class SpecifiedLinkParagraph:
    index: int
    start: int
    end: int
    text: str
    eligible: bool
    protected_spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class SpecifiedLinkScanResult:
    tokens: tuple[SpecifiedLinkTokenSpan, ...]
    paragraphs: tuple[SpecifiedLinkParagraph, ...]
    raw_boundaries: tuple[str, ...]


@dataclass(frozen=True)
class SpecifiedLinkRequestedEntry:
    entry_id: str
    canonical_url: str
    anchor: str
    normalized_anchor: str
    cluster: str


@dataclass(frozen=True)
class SpecifiedLinkPlacement:
    entry_id: str
    url: str
    anchor: str
    paragraph_index: int
    start: int
    end: int


@dataclass(frozen=True)
class SpecifiedLinkSkippedEntry:
    entry_id: str
    reason: str


@dataclass(frozen=True)
class SpecifiedLinkInjectionResult:
    batch_id: str
    source_slug: str
    specified_link_version: str
    config_version: str
    requested_entries: tuple[SpecifiedLinkRequestedEntry, ...]
    placed_entries: tuple[SpecifiedLinkPlacement, ...]
    skipped_entries: tuple[SpecifiedLinkSkippedEntry, ...]
    pre_sha256: str
    post_sha256: str
    status: str
    shortfall_reason: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SpecifiedLinkInjectionOutcome:
    markdown: str
    result: SpecifiedLinkInjectionResult


@dataclass(frozen=True)
class _PendingPlacement:
    entry_id: str
    url: str
    anchor: str
    paragraph_index: int
    baseline_start: int
    baseline_end: int
    markup: str


MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)(?P<link>\[[^\]\r\n]+\]\([^\)\r\n]*\))")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]\r\n]*\]\([^\)\r\n]*\)")
INLINE_CODE_PATTERN = re.compile(r"(`+)[^\r\n]*?\1")
LIQUID_PATTERN = re.compile(r"(?:\{\{.*?\}\}|\{%.*?%\})")
HTML_TAG_PATTERN = re.compile(r"</?[A-Za-z][^>\r\n]*>")
HTML_LINK_PATTERN = re.compile(r"<a\b[^>]*>.*?</a\s*>", re.IGNORECASE | re.DOTALL)
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
BARE_URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>()]+")
INTERNAL_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]\r\n]+\]\(\./[^\)\r\n]+\.html\)")


def _fail(code: str, message: str, *, entry_id: str | None = None) -> None:
    raise SpecifiedLinkContractError(code, message, entry_id=entry_id)


def _line_offsets(text: str) -> list[tuple[int, str]]:
    offsets: list[tuple[int, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        offsets.append((cursor, line))
        cursor += len(line)
    if text and not text.endswith(("\n", "\r")) and not offsets:
        offsets.append((0, text))
    return offsets


def _overlaps(start: int, end: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _global_html_comment_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    front_matter = True
    fence_marker: str | None = None
    comment_start: int | None = None
    for line_number, (offset, line) in enumerate(_line_offsets(text), start=1):
        content = line.rstrip("\r\n")
        if front_matter:
            if line_number > 1 and content == "---":
                front_matter = False
            continue
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", content)
        if comment_start is None and fence_marker is not None:
            if fence_match and fence_match.group(1)[0] == fence_marker[0] and len(fence_match.group(1)) >= len(fence_marker):
                fence_marker = None
            continue
        if comment_start is None and fence_match:
            fence_marker = fence_match.group(1)
            continue

        inline_code = tuple((match.start(), match.end()) for match in INLINE_CODE_PATTERN.finditer(content))
        cursor = 0
        while cursor < len(content):
            marker = "<!--" if comment_start is None else "-->"
            position = content.find(marker, cursor)
            if position == -1:
                break
            if _overlaps(position, position + len(marker), inline_code):
                cursor = position + 1
                continue
            if comment_start is None:
                comment_start = offset + position
            else:
                spans.append((comment_start, offset + position + len(marker)))
                comment_start = None
            cursor = position + len(marker)
    if comment_start is not None:
        _fail("SPECIFIED_PROTECTED_ZONE_VIOLATION", "HTML comment 未闭合或顺序非法")
    return tuple(spans)


def _paragraph_details(
    text: str,
    index: int,
    start: int,
    end: int,
    *,
    related: bool,
    html_comment_spans: Sequence[tuple[int, int]],
) -> tuple[SpecifiedLinkParagraph, list[SpecifiedLinkTokenSpan]]:
    paragraph_text = text[start:end]
    tokens: list[SpecifiedLinkTokenSpan] = []
    protected: list[tuple[int, int]] = []
    whole_paragraph_protected = related
    patterns = (
        ("markdown_image", MARKDOWN_IMAGE_PATTERN, True),
        ("markdown_link", MARKDOWN_LINK_PATTERN, True),
        ("inline_code", INLINE_CODE_PATTERN, False),
        ("liquid_tag", LIQUID_PATTERN, False),
        ("html_tag", HTML_TAG_PATTERN, True),
        ("bare_url", BARE_URL_PATTERN, True),
    )
    for kind, pattern, protect_whole in patterns:
        for match in pattern.finditer(paragraph_text):
            absolute = (start + match.start(), start + match.end())
            protected.append(absolute)
            tokens.append(
                SpecifiedLinkTokenSpan(kind, absolute[0], absolute[1], index, text[absolute[0] : absolute[1]])
            )
            whole_paragraph_protected = whole_paragraph_protected or protect_whole
    for comment_start, comment_end in html_comment_spans:
        if _overlaps(start, end, ((comment_start, comment_end),)):
            protected.append((comment_start, comment_end))
            tokens.append(
                SpecifiedLinkTokenSpan(
                    "html_comment",
                    comment_start,
                    comment_end,
                    index,
                    text[comment_start:comment_end],
                )
            )
            whole_paragraph_protected = True
    protected = sorted(set(protected))
    return (
        SpecifiedLinkParagraph(
            index=index,
            start=start,
            end=end,
            text=paragraph_text,
            eligible=not whole_paragraph_protected,
            protected_spans=tuple(protected),
        ),
        tokens,
    )


def scan_specified_markdown(text: str) -> SpecifiedLinkScanResult:
    lines = _line_offsets(text)
    if not lines or lines[0][1].rstrip("\r\n") != "---":
        _fail("SPECIFIED_PROTECTED_ZONE_VIOLATION", "文章必须以 YAML Front Matter 开始")

    html_comment_spans = _global_html_comment_spans(text)
    tokens: list[SpecifiedLinkTokenSpan] = []
    paragraphs: list[SpecifiedLinkParagraph] = []
    raw_boundaries: list[str] = []
    front_matter = True
    front_matter_closed = False
    fence_marker: str | None = None
    raw_depth = 0
    related = False
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    paragraph_related = False

    def flush_paragraph() -> None:
        nonlocal paragraph_start, paragraph_end, paragraph_related
        if paragraph_start is None or paragraph_end is None:
            return
        paragraph, paragraph_tokens = _paragraph_details(
            text,
            len(paragraphs),
            paragraph_start,
            paragraph_end,
            related=paragraph_related,
            html_comment_spans=html_comment_spans,
        )
        paragraphs.append(paragraph)
        tokens.extend(paragraph_tokens)
        paragraph_start = None
        paragraph_end = None
        paragraph_related = False

    for line_number, (offset, line) in enumerate(lines, start=1):
        content = line.rstrip("\r\n")
        line_end = offset + len(line)
        if front_matter:
            tokens.append(SpecifiedLinkTokenSpan("front_matter", offset, line_end, None, line))
            if line_number > 1 and content == "---":
                front_matter = False
                front_matter_closed = True
            continue

        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", content)
        if fence_marker is not None:
            flush_paragraph()
            tokens.append(SpecifiedLinkTokenSpan("fenced_code", offset, line_end, None, line))
            if fence_match and fence_match.group(1)[0] == fence_marker[0] and len(fence_match.group(1)) >= len(fence_marker):
                fence_marker = None
            continue
        if fence_match:
            flush_paragraph()
            fence_marker = fence_match.group(1)
            tokens.append(SpecifiedLinkTokenSpan("fenced_code", offset, line_end, None, line))
            continue

        boundary = re.fullmatch(r"\s*{%\s*(raw|endraw)\s*%}\s*", content)
        if boundary:
            flush_paragraph()
            kind = boundary.group(1)
            if kind == "raw":
                raw_depth += 1
            else:
                raw_depth -= 1
            if raw_depth not in {0, 1}:
                _fail("SPECIFIED_PROTECTED_ZONE_VIOLATION", "raw/endraw 数量或顺序非法")
            raw_boundaries.append(content)
            tokens.append(SpecifiedLinkTokenSpan("raw_boundary_line", offset, line_end, None, line))
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", content)
        if heading:
            flush_paragraph()
            if len(heading.group(1)) == 2:
                related = heading.group(2) == "相关阅读"
            tokens.append(SpecifiedLinkTokenSpan("heading", offset, line_end, None, line))
            continue
        if not content.strip():
            flush_paragraph()
            continue
        if paragraph_start is None:
            paragraph_start = offset
            paragraph_related = related
        paragraph_end = line_end

    flush_paragraph()
    if not front_matter_closed:
        _fail("SPECIFIED_PROTECTED_ZONE_VIOLATION", "YAML Front Matter 未闭合")
    if fence_marker is not None:
        _fail("SPECIFIED_PROTECTED_ZONE_VIOLATION", "fenced code block 未闭合")
    if raw_depth != 0:
        _fail("SPECIFIED_PROTECTED_ZONE_VIOLATION", "raw/endraw 未闭合")
    return SpecifiedLinkScanResult(tuple(tokens), tuple(paragraphs), tuple(raw_boundaries))


def _validate_plan_identity(
    *,
    source_slug: str,
    source_cluster: str,
    plan: SpecifiedLinkPlan,
    registry: SpecifiedLinkRegistry,
    batch_id: str,
    specified_link_version: str,
    config_version: str,
) -> tuple[SpecifiedLinkSpec, ...]:
    computed_version = compute_specified_link_version(
        registry.entries,
        schema_version=registry.schema_version,
        config_version=registry.config_version,
    )
    versions = {
        plan.specified_link_version,
        specified_link_version,
        registry.specified_link_version,
        computed_version,
    }
    if len(versions) != 1 or plan.config_version != config_version or registry.config_version != config_version:
        _fail("SPECIFIED_LINK_VERSION_MISMATCH", "Plan、caller 与 Registry version/config 不一致")
    if plan.batch_id != batch_id or plan.source_slug != source_slug or plan.source_cluster != source_cluster:
        _fail("UNAPPROVED_SPECIFIED_URL", "Plan source/batch identity 不一致")
    if source_cluster not in ALLOWED_CLUSTERS:
        _fail("SPECIFIED_CLUSTER_MISMATCH", "source cluster 非法")
    if plan.selected_links != len(plan.selected_entries) or plan.requested_links != plan.configured_max:
        _fail("UNAPPROVED_SPECIFIED_URL", "Plan count identity 不一致")
    if plan.selected_links > plan.requested_links:
        _fail("UNAPPROVED_SPECIFIED_URL", "Plan selected_links 超过 requested_links")

    registry_entries = {entry.id: entry for entry in registry.entries}
    resolved: list[SpecifiedLinkSpec] = []
    urls: set[str] = set()
    anchors: set[str] = set()
    for selected in plan.selected_entries:
        entry = registry_entries.get(selected.entry_id)
        if entry is None:
            _fail("UNAPPROVED_SPECIFIED_URL", "Plan entry 不存在于 Registry", entry_id=selected.entry_id)
        identity = (
            selected.canonical_url,
            selected.anchor,
            selected.normalized_anchor,
            selected.cluster,
        )
        registry_identity = (
            entry.canonical_url,
            entry.anchor,
            entry.normalized_anchor,
            entry.cluster,
        )
        if identity != registry_identity:
            _fail("UNAPPROVED_SPECIFIED_URL", "Plan entry identity 与 Registry 不一致", entry_id=entry.id)
        if entry.cluster != source_cluster:
            _fail("SPECIFIED_CLUSTER_MISMATCH", "Plan entry cluster 与 source 不一致", entry_id=entry.id)
        if entry.canonical_url in urls or entry.normalized_anchor in anchors:
            _fail("UNAPPROVED_SPECIFIED_URL", "Plan 违反article-local URL/anchor唯一性", entry_id=entry.id)
        urls.add(entry.canonical_url)
        anchors.add(entry.normalized_anchor)
        resolved.append(entry)
    return tuple(resolved)


def _is_safe_markdown_link(entry: SpecifiedLinkSpec) -> bool:
    return (
        not any(character in entry.anchor for character in "[]\r\n")
        and not any(character in entry.canonical_url for character in "()\r\n")
    )


def _find_safe_anchor(
    entry: SpecifiedLinkSpec,
    scan: SpecifiedLinkScanResult,
    used_paragraphs: set[int],
) -> tuple[int, int, int] | None:
    if not _is_safe_markdown_link(entry):
        return None
    for paragraph in scan.paragraphs:
        if not paragraph.eligible or paragraph.index in used_paragraphs:
            continue
        search_from = paragraph.start
        while search_from < paragraph.end:
            position = scan_text_find(scan, entry.anchor, search_from, paragraph.end)
            if position == -1:
                break
            anchor_end = position + len(entry.anchor)
            if not _overlaps(position, anchor_end, paragraph.protected_spans):
                return paragraph.index, position, anchor_end
            search_from = position + 1
    return None


def scan_text_find(scan: SpecifiedLinkScanResult, needle: str, start: int, end: int) -> int:
    for paragraph in scan.paragraphs:
        if paragraph.start <= start <= paragraph.end and paragraph.end >= end:
            relative_start = start - paragraph.start
            relative_end = end - paragraph.start
            relative = paragraph.text.find(needle, relative_start, relative_end)
            return -1 if relative == -1 else paragraph.start + relative
    return -1


def _extract_existing_links(markdown: str) -> tuple[Counter[str], Counter[str], Counter[str]]:
    markdown_links = Counter(match.group(0) for match in MARKDOWN_LINK_PATTERN.finditer(markdown))
    html_links = Counter(match.group(0) for match in HTML_LINK_PATTERN.finditer(markdown))
    internal_links = Counter(match.group(0) for match in INTERNAL_LINK_PATTERN.finditer(markdown))
    return markdown_links, html_links, internal_links


def _verify_preservation(
    baseline: str,
    post_markdown: str,
    placements: Sequence[SpecifiedLinkPlacement],
    baseline_scan: SpecifiedLinkScanResult,
) -> None:
    pre_markdown_links, pre_html, pre_internal = _extract_existing_links(baseline)
    post_markdown_links, post_html, post_internal = _extract_existing_links(post_markdown)
    injected = Counter(f"[{placement.anchor}]({placement.url})" for placement in placements)
    if post_markdown_links - injected != pre_markdown_links:
        _fail("PRE_EXISTING_LINK_MUTATED", "既有 Markdown links 发生变化")
    if post_html != pre_html:
        _fail("PRE_EXISTING_LINK_MUTATED", "既有 HTML links 发生变化")
    if post_internal != pre_internal:
        _fail("INTERNAL_LINK_MUTATED", "既有 Internal Links 发生变化")
    post_scan = scan_specified_markdown(post_markdown)
    if post_scan.raw_boundaries != baseline_scan.raw_boundaries:
        _fail("SPECIFIED_PROTECTED_ZONE_VIOLATION", "raw/endraw boundary 发生变化")

    reversed_markdown = post_markdown
    for placement in sorted(placements, key=lambda item: item.start, reverse=True):
        expected = f"[{placement.anchor}]({placement.url})"
        if reversed_markdown[placement.start : placement.end] != expected:
            _fail("POST_INJECTION_SHA_MISMATCH", "placement offset 与post Markdown不一致", entry_id=placement.entry_id)
        reversed_markdown = (
            reversed_markdown[: placement.start]
            + placement.anchor
            + reversed_markdown[placement.end :]
        )
    if reversed_markdown != baseline:
        _fail("PRE_EXISTING_LINK_MUTATED", "移除注入markup后无法还原baseline")


def inject_specified_links(
    *,
    source_slug: str,
    source_cluster: str,
    baseline_markdown: str,
    plan: SpecifiedLinkPlan,
    registry: SpecifiedLinkRegistry,
    batch_id: str,
    specified_link_version: str,
    config_version: str,
    protected_slug_set: Iterable[str] = (),
) -> SpecifiedLinkInjectionOutcome:
    if source_slug in set(protected_slug_set):
        _fail("EXISTING_PRODUCTION_MUTATION_ATTEMPT", "Frozen production article 不可注入")
    resolved = _validate_plan_identity(
        source_slug=source_slug,
        source_cluster=source_cluster,
        plan=plan,
        registry=registry,
        batch_id=batch_id,
        specified_link_version=specified_link_version,
        config_version=config_version,
    )
    pre_sha256 = hashlib.sha256(baseline_markdown.encode("utf-8")).hexdigest()
    scan = scan_specified_markdown(baseline_markdown)
    requested = tuple(
        SpecifiedLinkRequestedEntry(
            entry.id,
            entry.canonical_url,
            entry.anchor,
            entry.normalized_anchor,
            entry.cluster,
        )
        for entry in resolved
    )
    pending: list[_PendingPlacement] = []
    skipped: list[SpecifiedLinkSkippedEntry] = []
    used_paragraphs: set[int] = set()
    for entry in resolved:
        match = _find_safe_anchor(entry, scan, used_paragraphs)
        if match is None:
            skipped.append(SpecifiedLinkSkippedEntry(entry.id, "NO_SAFE_SPECIFIED_LINK_POINT"))
            continue
        paragraph_index, start, end = match
        markup = f"[{entry.anchor}]({entry.canonical_url})"
        pending.append(
            _PendingPlacement(
                entry.id,
                entry.canonical_url,
                entry.anchor,
                paragraph_index,
                start,
                end,
                markup,
            )
        )
        used_paragraphs.add(paragraph_index)

    output = baseline_markdown
    for placement in sorted(pending, key=lambda item: item.baseline_start, reverse=True):
        output = output[: placement.baseline_start] + placement.markup + output[placement.baseline_end :]

    shifts = 0
    placements_by_baseline = sorted(pending, key=lambda item: item.baseline_start)
    placement_offsets: dict[str, tuple[int, int]] = {}
    for placement in placements_by_baseline:
        post_start = placement.baseline_start + shifts
        post_end = post_start + len(placement.markup)
        placement_offsets[placement.entry_id] = (post_start, post_end)
        shifts += len(placement.markup) - len(placement.anchor)
    placed = tuple(
        SpecifiedLinkPlacement(
            placement.entry_id,
            placement.url,
            placement.anchor,
            placement.paragraph_index,
            placement_offsets[placement.entry_id][0],
            placement_offsets[placement.entry_id][1],
        )
        for placement in pending
    )
    _verify_preservation(baseline_markdown, output, placed, scan)

    warnings: list[str] = []
    if plan.status == "PASS_WITH_SHORTFALL" and plan.shortfall_reason:
        warnings.append(f"PLANNER_SHORTFALL:{plan.shortfall_reason}")
    if skipped:
        warnings.append("PLACEMENT_SHORTFALL:NO_SAFE_SPECIFIED_LINK_POINT")
    if warnings:
        status = "PASS_WITH_SHORTFALL"
        shortfall_reason = "NO_SAFE_SPECIFIED_LINK_POINT" if skipped else plan.shortfall_reason
    else:
        status = "PASS"
        shortfall_reason = None
    post_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
    result = SpecifiedLinkInjectionResult(
        batch_id=batch_id,
        source_slug=source_slug,
        specified_link_version=specified_link_version,
        config_version=config_version,
        requested_entries=requested,
        placed_entries=placed,
        skipped_entries=tuple(skipped),
        pre_sha256=pre_sha256,
        post_sha256=post_sha256,
        status=status,
        shortfall_reason=shortfall_reason,
        warnings=tuple(warnings),
    )
    return SpecifiedLinkInjectionOutcome(output, result)
