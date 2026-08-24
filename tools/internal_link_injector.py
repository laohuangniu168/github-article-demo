from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from article_spec import SLUG_PATTERN
from internal_link_registry import CANONICAL_BASE, RegistryEntry, RegistrySnapshot, compute_registry_version
from internal_link_selector import (
    CONTROLLED_TOPIC_TERMS,
    LinkSelectionPlan,
)


BODY_TARGET_RATIO = 0.70
BODY_TARGET_RATIO_MIN = 0.60
BODY_TARGET_RATIO_MAX = 0.80
MAX_BODY_LINKS_PER_PARAGRAPH = 1
MAX_BODY_LINKS_PER_H2_SECTION = 3
RELATED_MIN = 4
RELATED_TARGET_MIN = 8
RELATED_MAX = 10
ANCHOR_MIN_LENGTH = 2
ANCHOR_MAX_LENGTH = 40
BATCH_EXTENSION_VERSION_PREFIX = "ilx1:"

FORBIDDEN_ANCHORS = frozenset(
    {
        "点击这里",
        "更多内容",
        "查看详情",
        "read more",
        "click here",
    }
)

SIMPLIFY_TERMS = (
    "SEO",
    "seo",
    "完整",
    "实战",
    "指南",
    "教程",
    "方法",
    "优化",
)


@dataclass(frozen=True)
class TokenSpan:
    kind: str
    start: int
    end: int
    line_number: int
    paragraph_index: int | None
    h2_section: str | None
    text: str


@dataclass(frozen=True)
class ScanResult:
    tokens: tuple[TokenSpan, ...]
    plain_spans: tuple[TokenSpan, ...]
    raw_start: int
    endraw_start: int
    final_summary_start: int | None
    paragraph_count: int


@dataclass(frozen=True)
class BatchExtensionEntry:
    slug: str
    title: str
    cluster: str
    batch_id: str
    markdown_path: str
    relative_url: str
    canonical_url: str
    quality_status: str
    published: bool
    eligible_as_target: bool


@dataclass(frozen=True)
class BatchRegistryExtension:
    entries: tuple[BatchExtensionEntry, ...]
    batch_id: str
    extension_version: str


def compute_batch_extension_version(entries: Sequence[BatchExtensionEntry]) -> str:
    payload = "\n".join(
        "|".join((entry.slug, entry.title, entry.cluster, entry.markdown_path, entry.quality_status))
        for entry in sorted(entries, key=lambda item: item.slug)
    )
    return BATCH_EXTENSION_VERSION_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AnchorSelection:
    anchor_text: str
    anchor_source: str
    source_span: tuple[int, int]
    target_slug: str
    normalization_key: str


@dataclass(frozen=True)
class Placement:
    target_slug: str
    anchor_text: str
    anchor_source: str
    placement_type: str
    h2_section: str | None
    paragraph_index: int | None
    source_span: tuple[int, int] | None
    written_link: str


@dataclass(frozen=True)
class SkippedTarget:
    target_slug: str
    reason: str


@dataclass(frozen=True)
class InjectionEvent:
    code: str
    article_slug: str
    target_slug: str
    stage: str
    message: str


@dataclass(frozen=True)
class InjectionResult:
    article_slug: str
    batch_id: str
    registry_version: str
    config_version: str
    requested_targets: int
    body_links: int
    related_links: int
    skipped_targets: tuple[SkippedTarget, ...]
    placements: tuple[Placement, ...]
    warnings: tuple[str, ...]
    events: tuple[InjectionEvent, ...]
    final_status: str


@dataclass(frozen=True)
class InjectionOutcome:
    markdown: str
    result: InjectionResult


class ScannerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


INLINE_PATTERNS = (
    ("markdown_image", re.compile(r"!\[[^\]\n]*\]\([^\)\n]*\)")),
    ("markdown_link", re.compile(r"(?<!!)\[[^\]\n]+\]\([^\)\n]*\)")),
    ("inline_code", re.compile(r"(`+)[^\n]*?\1")),
    ("liquid_tag", re.compile(r"(?:\{\{.*?\}\}|\{%.*?%\})")),
    ("html_tag", re.compile(r"</?[A-Za-z][^>\n]*>")),
    ("bare_url", re.compile(r"(?:https?://|www\.)[^\s<>()]+")),
)


def normalize_anchor(text: str) -> str:
    collapsed = " ".join(text.strip().split())
    folded = "".join(
        chr(ord(character) + 32)
        if "A" <= character <= "Z"
        else character
        for character in collapsed
    )
    start = 0
    end = len(folded)
    while start < end and unicodedata.category(folded[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(folded[end - 1]).startswith("P"):
        end -= 1
    return folded[start:end].strip()


def _line_offsets(text: str) -> list[tuple[int, str]]:
    offsets: list[tuple[int, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        offsets.append((cursor, line))
        cursor += len(line)
    if not text or (text and not text.endswith(("\n", "\r"))):
        if not offsets or offsets[-1][0] + len(offsets[-1][1]) < len(text):
            offsets.append((cursor, text[cursor:]))
    return offsets


def _inline_protected_spans(line: str, absolute_start: int) -> list[tuple[str, int, int]]:
    found: list[tuple[str, int, int]] = []
    for kind, pattern in INLINE_PATTERNS:
        for match in pattern.finditer(line):
            found.append((kind, absolute_start + match.start(), absolute_start + match.end()))
    found.sort(key=lambda item: (item[1], -(item[2] - item[1])))
    merged: list[tuple[str, int, int]] = []
    for item in found:
        if merged and item[1] < merged[-1][2]:
            if item[2] > merged[-1][2]:
                merged[-1] = (merged[-1][0], merged[-1][1], item[2])
            continue
        merged.append(item)
    return merged


def scan_markdown(text: str) -> ScanResult:
    lines = _line_offsets(text)
    if not lines or lines[0][1].rstrip("\r\n") != "---":
        raise ScannerError("INVALID_FRONT_MATTER", "文章必须以 YAML Front Matter 开始")

    tokens: list[TokenSpan] = []
    plain_spans: list[TokenSpan] = []
    front_matter = True
    front_matter_closed = False
    fence_marker: str | None = None
    html_comment = False
    current_h2: str | None = None
    paragraph_index = -1
    paragraph_open = False
    raw_positions: list[int] = []
    endraw_positions: list[int] = []
    summary_positions: list[int] = []

    for line_number, (offset, line) in enumerate(lines, start=1):
        content = line.rstrip("\r\n")
        line_end = offset + len(line)

        if front_matter:
            tokens.append(TokenSpan("front_matter", offset, line_end, line_number, None, None, line))
            if line_number > 1 and content == "---":
                front_matter = False
                front_matter_closed = True
            continue

        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", content)
        if fence_marker is not None:
            tokens.append(TokenSpan("fenced_code", offset, line_end, line_number, None, current_h2, line))
            if fence_match and fence_match.group(1)[0] == fence_marker[0] and len(fence_match.group(1)) >= len(fence_marker):
                fence_marker = None
            paragraph_open = False
            continue
        if fence_match:
            fence_marker = fence_match.group(1)
            tokens.append(TokenSpan("fenced_code", offset, line_end, line_number, None, current_h2, line))
            paragraph_open = False
            continue

        boundary = re.fullmatch(r"\s*{%\s*(raw|endraw)\s*%}\s*", content)
        if boundary:
            kind = "raw_boundary_line"
            tokens.append(TokenSpan(kind, offset, line_end, line_number, None, current_h2, line))
            if boundary.group(1) == "raw":
                raw_positions.append(offset)
            else:
                endraw_positions.append(offset)
            paragraph_open = False
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", content)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            if level == 2:
                current_h2 = title
                if title == "总结":
                    summary_positions.append(offset)
            tokens.append(TokenSpan("heading", offset, line_end, line_number, None, current_h2, line))
            paragraph_open = False
            continue

        if not content.strip():
            paragraph_open = False
            continue

        if not paragraph_open:
            paragraph_index += 1
            paragraph_open = True

        line_text_end = offset + len(content)
        # Mixed Markdown/HTML lines are renderer-sensitive. Gate 5 permits
        # injection only into normal Markdown prose, so protect the whole line.
        if re.search(r"</?[A-Za-z][^>\n]*>", content):
            tokens.append(TokenSpan("html_line", offset, line_text_end, line_number, paragraph_index, current_h2, line))
            continue
        protected: list[tuple[str, int, int]] = []
        cursor = 0
        while cursor < len(content):
            if html_comment:
                close = content.find("-->", cursor)
                if close == -1:
                    protected.append(("html_comment", offset + cursor, line_text_end))
                    cursor = len(content)
                else:
                    protected.append(("html_comment", offset + cursor, offset + close + 3))
                    html_comment = False
                    cursor = close + 3
                continue
            opening = content.find("<!--", cursor)
            inline_end = opening if opening != -1 else len(content)
            protected.extend(_inline_protected_spans(content[cursor:inline_end], offset + cursor))
            if opening == -1:
                cursor = len(content)
            else:
                close = content.find("-->", opening + 4)
                if close == -1:
                    protected.append(("html_comment", offset + opening, line_text_end))
                    html_comment = True
                    cursor = len(content)
                else:
                    protected.append(("html_comment", offset + opening, offset + close + 3))
                    cursor = close + 3

        protected.sort(key=lambda item: item[1])
        plain_cursor = offset
        for kind, start, end in protected:
            if start > plain_cursor:
                plain_spans.append(
                    TokenSpan("paragraph", plain_cursor, start, line_number, paragraph_index, current_h2, text[plain_cursor:start])
                )
            tokens.append(TokenSpan(kind, start, end, line_number, paragraph_index, current_h2, text[start:end]))
            plain_cursor = max(plain_cursor, end)
        if plain_cursor < line_text_end:
            plain_spans.append(
                TokenSpan("paragraph", plain_cursor, line_text_end, line_number, paragraph_index, current_h2, text[plain_cursor:line_text_end])
            )

    if not front_matter_closed:
        raise ScannerError("INVALID_FRONT_MATTER", "YAML Front Matter 未闭合")
    if fence_marker is not None:
        raise ScannerError("MALFORMED_MARKDOWN", "fenced code block 未闭合")
    if html_comment:
        raise ScannerError("MALFORMED_MARKDOWN", "HTML comment 未闭合")
    if len(raw_positions) != 1 or len(endraw_positions) != 1 or raw_positions[0] >= endraw_positions[0]:
        raise ScannerError("INVALID_RAW_BOUNDARY", "必须存在唯一且有序的 raw/endraw")

    valid_plain = tuple(
        span
        for span in plain_spans
        if raw_positions[0] < span.start < endraw_positions[0]
    )
    valid_summaries = [
        position
        for position in summary_positions
        if raw_positions[0] < position < endraw_positions[0]
    ]
    return ScanResult(
        tokens=tuple(tokens),
        plain_spans=valid_plain,
        raw_start=raw_positions[0],
        endraw_start=endraw_positions[0],
        final_summary_start=valid_summaries[-1] if valid_summaries else None,
        paragraph_count=paragraph_index + 1,
    )


def _simplified_title(title: str) -> str:
    simplified = title
    for term in SIMPLIFY_TERMS:
        simplified = simplified.replace(term, "")
    simplified = re.sub(r"[\s\-—_:：·]+", " ", simplified).strip(" ，。！？；：,.!?;:-—")
    return " ".join(simplified.split())


def _anchor_phrases(entry: RegistryEntry) -> list[tuple[str, str]]:
    phrases: list[tuple[str, str]] = []
    simplified = _simplified_title(entry.title)
    if ANCHOR_MIN_LENGTH <= len(simplified) <= ANCHOR_MAX_LENGTH and simplified != entry.title:
        phrases.append((simplified, "simplified_target_title"))

    value = f"{entry.slug.casefold()}\n{entry.title.casefold()}"
    aliases: set[str] = set()
    for topic_aliases in CONTROLLED_TOPIC_TERMS.values():
        if any(alias.casefold() in value for alias in topic_aliases):
            aliases.update(
                alias
                for alias in topic_aliases
                if ANCHOR_MIN_LENGTH <= len(alias) <= ANCHOR_MAX_LENGTH
            )
    for alias in sorted(aliases, key=lambda item: (-len(item), item.casefold())):
        phrases.append((alias, "controlled_target_term"))

    if ANCHOR_MIN_LENGTH <= len(entry.title) <= ANCHOR_MAX_LENGTH:
        phrases.append((entry.title, "natural_source_phrase"))
    return phrases


def _ascii_fold(text: str) -> str:
    return "".join(chr(ord(character) + 32) if "A" <= character <= "Z" else character for character in text)


def _find_anchor(
    span: TokenSpan,
    entry: RegistryEntry,
    used_normalizations: set[str],
) -> AnchorSelection | None:
    folded_span = _ascii_fold(span.text)
    for phrase, anchor_source in _anchor_phrases(entry):
        folded_phrase = _ascii_fold(phrase)
        relative = folded_span.find(folded_phrase)
        if relative == -1:
            continue
        anchor_text = span.text[relative : relative + len(phrase)]
        normalization_key = normalize_anchor(anchor_text)
        if not ANCHOR_MIN_LENGTH <= len(anchor_text.strip()) <= ANCHOR_MAX_LENGTH:
            continue
        if not normalization_key or normalization_key in used_normalizations:
            continue
        if normalization_key in FORBIDDEN_ANCHORS:
            continue
        return AnchorSelection(
            anchor_text=anchor_text,
            anchor_source=anchor_source,
            source_span=(span.start + relative, span.start + relative + len(phrase)),
            target_slug=entry.slug,
            normalization_key=normalization_key,
        )
    return None


def _hard_fail(
    markdown: str,
    article_slug: str,
    plan: LinkSelectionPlan,
    code: str,
    message: str,
    target_slug: str = "",
) -> InjectionOutcome:
    event = InjectionEvent(code, article_slug, target_slug, "integrity", message)
    return InjectionOutcome(
        markdown,
        InjectionResult(
            article_slug=article_slug,
            batch_id=plan.batch_id,
            registry_version=plan.registry_version,
            config_version=plan.config_version,
            requested_targets=len(plan.selected_targets),
            body_links=0,
            related_links=0,
            skipped_targets=(),
            placements=(),
            warnings=(),
            events=(event,),
            final_status="FAIL",
        ),
    )


def inject_links(
    markdown: str,
    *,
    article_slug: str,
    plan: LinkSelectionPlan,
    registry: RegistrySnapshot,
    registry_version: str,
    config_version: str,
    batch_id: str,
    protected_slugs: Iterable[str] = (),
    batch_extension: BatchRegistryExtension | None = None,
    extension_version: str | None = None,
    file_exists: Callable[[str], bool] | None = None,
) -> InjectionOutcome:
    if article_slug in set(protected_slugs):
        return _hard_fail(markdown, article_slug, plan, "EXISTING_PRODUCTION_MUTATION_ATTEMPT", "Frozen production article 不可注入")
    if article_slug != plan.source_slug:
        return _hard_fail(markdown, article_slug, plan, "SOURCE_SLUG_MISMATCH", "article_slug 与 SelectionPlan 不一致")
    if not batch_id or batch_id != plan.batch_id:
        return _hard_fail(markdown, article_slug, plan, "BATCH_ID_MISMATCH", "batch_id 缺失或不一致")
    if registry_version != registry.registry_version or plan.registry_version != registry.registry_version:
        return _hard_fail(markdown, article_slug, plan, "REGISTRY_VERSION_MISMATCH", "Registry version 不一致")
    computed_version = compute_registry_version(
        registry.entries,
        source_batches=registry.source_batches,
        schema_version=registry.registry_schema_version,
    )
    if computed_version != registry.registry_version:
        return _hard_fail(markdown, article_slug, plan, "REGISTRY_VERSION_MISMATCH", "Registry payload 与 version 不一致")
    if config_version != plan.config_version:
        return _hard_fail(markdown, article_slug, plan, "CONFIG_VERSION_MISMATCH", "Config version 不一致")

    frozen_entries = {entry.slug: entry for entry in registry.entries}
    extension_entries = {entry.slug: entry for entry in batch_extension.entries} if batch_extension else {}
    file_exists = file_exists or (lambda path: (Path(__file__).resolve().parent.parent / path).is_file())
    selected_slugs = [target.target_slug for target in plan.selected_targets]
    if len(selected_slugs) != len(set(selected_slugs)):
        return _hard_fail(markdown, article_slug, plan, "DUPLICATE_TARGET_REJECTED", "SelectionPlan target 重复")
    resolved_entries: dict[str, RegistryEntry | BatchExtensionEntry] = {}
    for selected_target in plan.selected_targets:
        target_slug = selected_target.target_slug
        if target_slug == article_slug:
            return _hard_fail(markdown, article_slug, plan, "SELF_LINK_REJECTED", "SelectionPlan 包含 self target", target_slug)
        if selected_target.source == "frozen_registry":
            entry = frozen_entries.get(target_slug)
            if entry is None:
                code = "TARGET_SOURCE_MISMATCH" if target_slug in extension_entries else "REGISTRY_TARGET_MISSING"
                return _hard_fail(markdown, article_slug, plan, code, "Frozen Registry target 来源不一致或不存在", target_slug)
            if not entry.published or not entry.eligible_as_target or not SLUG_PATTERN.fullmatch(entry.slug):
                return _hard_fail(markdown, article_slug, plan, "REGISTRY_TARGET_INELIGIBLE", "Frozen Registry target 不合格", target_slug)
        elif selected_target.source == "batch_registry_extension":
            if batch_extension is None:
                return _hard_fail(markdown, article_slug, plan, "BATCH_EXTENSION_REQUIRED", "SelectionPlan 需要 Batch Registry Extension", target_slug)
            if batch_extension.batch_id != batch_id:
                return _hard_fail(markdown, article_slug, plan, "BATCH_ID_MISMATCH", "Extension batch_id 不一致", target_slug)
            computed_extension_version = compute_batch_extension_version(batch_extension.entries)
            if not extension_version or extension_version != batch_extension.extension_version or extension_version != computed_extension_version:
                return _hard_fail(markdown, article_slug, plan, "BATCH_EXTENSION_VERSION_MISMATCH", "Extension version 不一致", target_slug)
            entry = extension_entries.get(target_slug)
            if entry is None:
                code = "TARGET_SOURCE_MISMATCH" if target_slug in frozen_entries else "BATCH_EXTENSION_TARGET_MISSING"
                return _hard_fail(markdown, article_slug, plan, code, "Batch Extension target 来源不一致或不存在", target_slug)
            if entry.batch_id != batch_id:
                return _hard_fail(markdown, article_slug, plan, "BATCH_ID_MISMATCH", "target batch_id 不一致", target_slug)
            if entry.quality_status != "PASS" or not entry.published:
                return _hard_fail(markdown, article_slug, plan, "BATCH_TARGET_QUALITY_NOT_PASS", "Batch target quality 未通过", target_slug)
            if not entry.eligible_as_target or not SLUG_PATTERN.fullmatch(entry.slug):
                return _hard_fail(markdown, article_slug, plan, "REGISTRY_TARGET_INELIGIBLE", "Batch target 不合格", target_slug)
            if entry.relative_url != f"./{target_slug}.html" or entry.canonical_url != f"{CANONICAL_BASE}{target_slug}.html":
                return _hard_fail(markdown, article_slug, plan, "REGISTRY_TARGET_INELIGIBLE", "Batch target URL 不符合合同", target_slug)
            if not file_exists(entry.markdown_path):
                return _hard_fail(markdown, article_slug, plan, "BATCH_EXTENSION_TARGET_MISSING", "Batch target Markdown 不存在", target_slug)
        else:
            return _hard_fail(markdown, article_slug, plan, "TARGET_SOURCE_MISMATCH", "未知 target source", target_slug)
        resolved_entries[target_slug] = entry

    try:
        scan = scan_markdown(markdown)
    except ScannerError as exc:
        return _hard_fail(markdown, article_slug, plan, exc.code, exc.message)
    if sum(1 for token in scan.tokens if token.kind == "heading" and token.text.rstrip("\r\n") == "## 相关阅读"):
        return _hard_fail(markdown, article_slug, plan, "RELATED_BLOCK_ALREADY_EXISTS", "文章已存在相关阅读 block")

    requested = len(selected_slugs)
    related_reserve = RELATED_MIN if requested >= RELATED_MIN else 0
    body_target = min(
        int(requested * BODY_TARGET_RATIO + 0.5),
        max(0, requested - related_reserve),
    )
    body_target = min(body_target, int(requested * BODY_TARGET_RATIO_MAX + 0.999999))

    used_paragraphs: set[int] = set()
    section_counts: dict[str | None, int] = {}
    used_normalizations: set[str] = set()
    body_slugs: set[str] = set()
    placements: list[Placement] = []
    replacements: list[tuple[int, int, str]] = []
    remaining: list[str] = []

    for target_slug in selected_slugs:
        if len(body_slugs) >= body_target:
            remaining.append(target_slug)
            continue
        entry = resolved_entries[target_slug]
        chosen: tuple[TokenSpan, AnchorSelection] | None = None
        ordered_spans = sorted(
            scan.plain_spans,
            key=lambda span: (
                section_counts.get(span.h2_section, 0),
                span.paragraph_index if span.paragraph_index is not None else 10**9,
                span.start,
            ),
        )
        for span in ordered_spans:
            if span.paragraph_index is None or span.paragraph_index in used_paragraphs:
                continue
            if section_counts.get(span.h2_section, 0) >= MAX_BODY_LINKS_PER_H2_SECTION:
                continue
            anchor = _find_anchor(span, entry, used_normalizations)
            if anchor is not None:
                chosen = (span, anchor)
                break
        if chosen is None:
            remaining.append(target_slug)
            continue

        span, anchor = chosen
        written_link = f"./{target_slug}.html"
        replacement = f"[{anchor.anchor_text}]({written_link})"
        replacements.append((anchor.source_span[0], anchor.source_span[1], replacement))
        used_paragraphs.add(span.paragraph_index)
        section_counts[span.h2_section] = section_counts.get(span.h2_section, 0) + 1
        used_normalizations.add(anchor.normalization_key)
        body_slugs.add(target_slug)
        placements.append(
            Placement(
                target_slug=target_slug,
                anchor_text=anchor.anchor_text,
                anchor_source=anchor.anchor_source,
                placement_type="body",
                h2_section=span.h2_section,
                paragraph_index=span.paragraph_index,
                source_span=anchor.source_span,
                written_link=written_link,
            )
        )

    related_slugs: list[str] = []
    skipped: list[SkippedTarget] = []
    events: list[InjectionEvent] = []
    for target_slug in remaining:
        if target_slug in body_slugs:
            continue
        entry = resolved_entries[target_slug]
        normalized = normalize_anchor(entry.title)
        if (
            len(related_slugs) < RELATED_MAX
            and ANCHOR_MIN_LENGTH <= len(entry.title.strip()) <= ANCHOR_MAX_LENGTH
            and normalized
            and normalized not in used_normalizations
            and normalized not in FORBIDDEN_ANCHORS
        ):
            related_slugs.append(target_slug)
            used_normalizations.add(normalized)
            placements.append(
                Placement(
                    target_slug=target_slug,
                    anchor_text=entry.title,
                    anchor_source="related_full_title",
                    placement_type="related",
                    h2_section="相关阅读",
                    paragraph_index=None,
                    source_span=None,
                    written_link=f"./{target_slug}.html",
                )
            )
        else:
            skipped.append(SkippedTarget(target_slug, "NO_SAFE_INJECTION_POINT"))
            events.append(
                InjectionEvent(
                    "NO_SAFE_INJECTION_POINT",
                    article_slug,
                    target_slug,
                    "placement",
                    "无安全 Body anchor 且 Related 已满或 anchor 不合法",
                )
            )

    related_block = ""
    if related_slugs:
        related_lines = ["## 相关阅读", ""]
        related_lines.extend(
            f"- [{resolved_entries[slug].title}](./{slug}.html)"
            for slug in related_slugs
        )
        related_block = "\n".join(related_lines) + "\n\n"
        insertion_position = scan.final_summary_start or scan.endraw_start
        replacements.append((insertion_position, insertion_position, related_block))

    output = markdown
    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        output = output[:start] + replacement + output[end:]

    try:
        output_scan = scan_markdown(output)
    except ScannerError as exc:
        return _hard_fail(markdown, article_slug, plan, "MALFORMED_MARKDOWN", exc.message)
    if output.count("{% raw %}") != markdown.count("{% raw %}") or output.count("{% endraw %}") != markdown.count("{% endraw %}"):
        return _hard_fail(markdown, article_slug, plan, "PROTECTED_ZONE_VIOLATION", "raw/endraw 数量变化")
    if output_scan.raw_start >= output_scan.endraw_start:
        return _hard_fail(markdown, article_slug, plan, "PROTECTED_ZONE_VIOLATION", "raw/endraw 顺序变化")

    warnings: list[str] = []
    body_links = len(body_slugs)
    related_links = len(related_slugs)
    placed = body_links + related_links
    if body_links < body_target or related_links < min(RELATED_TARGET_MIN, requested):
        warnings.append("PLACEMENT_TARGET_NOT_MET")
    if placed < requested:
        warnings.append("INSUFFICIENT_SAFE_INJECTION_POINTS")
        status = "PASS_WITH_SHORTFALL"
    else:
        status = "PASS"

    return InjectionOutcome(
        output,
        InjectionResult(
            article_slug=article_slug,
            batch_id=batch_id,
            registry_version=registry_version,
            config_version=config_version,
            requested_targets=requested,
            body_links=body_links,
            related_links=related_links,
            skipped_targets=tuple(skipped),
            placements=tuple(placements),
            warnings=tuple(dict.fromkeys(warnings)),
            events=tuple(events),
            final_status=status,
        ),
    )
