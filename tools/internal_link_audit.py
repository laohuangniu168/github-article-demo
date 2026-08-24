from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from article_spec import ArticleSpec
from internal_link_injector import InjectionResult, normalize_anchor
from internal_link_registry import CANONICAL_BASE, RegistryEntry, RegistrySnapshot, compute_registry_version
from internal_link_selector import (
    MIN_RELEVANCE_SCORE,
    SAME_BATCH_MAX_PERCENT,
    BatchRegistryEntry,
    LinkSelectionPlan,
    TargetRecord,
    score_relevance,
)


ALLOWED_SHORTFALL_REASONS = frozenset(
    {"INSUFFICIENT_RELEVANT_CANDIDATES", "INBOUND_CAP_EXHAUSTED", "INSUFFICIENT_SAFE_INJECTION_POINTS"}
)
STRICT_INTERNAL_URL = re.compile(r"\./([a-z0-9]+(?:-[a-z0-9]+)*)\.html\Z")
LINK_RE = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\n]*)\)")
IMAGE_RE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")
INLINE_CODE_RE = re.compile(r"(`+)[^\n]*?\1")
LIQUID_RE = re.compile(r"(?:\{\{.*?\}\}|\{%.*?%\})")
HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>\n]*>")
ANCHOR_MIN_LENGTH = 2
ANCHOR_MAX_LENGTH = 40
RELATED_MAX = 10


@dataclass(frozen=True)
class ParsedLink:
    anchor: str
    url: str
    line_number: int
    zone: str
    related: bool


@dataclass(frozen=True)
class AuditEvent:
    code: str
    target_slug: str
    message: str


@dataclass(frozen=True)
class InternalLinkAuditResult:
    article_slug: str
    internal_links: int
    unique_targets: int
    body_links: int
    related_links: int
    same_batch_links: int
    self_links: int
    duplicate_targets: int
    broken_targets: int
    invalid_targets: int
    out_of_registry_targets: int
    code_block_injections: int
    front_matter_injections: int
    inline_code_injections: int
    liquid_injections: int
    html_attribute_injections: int
    html_comment_injections: int
    malformed_markdown_links: int
    anchor_duplicates: int
    cluster_distribution: Mapping[str, object]
    shortfall_reason: str | None
    warnings: tuple[str, ...]
    registry_version: str
    config_version: str
    events: tuple[AuditEvent, ...]
    final_status: str


@dataclass(frozen=True)
class BatchInboundViolation:
    target_slug: str
    actual_inbound_sources: int
    cap: int


@dataclass(frozen=True)
class BatchAuditResult:
    article_results: tuple[InternalLinkAuditResult, ...]
    inbound_cap: int
    inbound_violations: tuple[BatchInboundViolation, ...]
    final_status: str


def _overlaps(start: int, end: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(start < right and end > left for left, right in spans)


def _scan_markdown(markdown: str) -> tuple[list[ParsedLink], int, list[str], int]:
    lines = markdown.splitlines(keepends=True)
    links: list[ParsedLink] = []
    malformed = 0
    related_headers = 0
    related_errors: list[str] = []
    front = bool(lines and lines[0].rstrip("\r\n") == "---")
    front_closed = False
    fence: str | None = None
    html_comment = False
    raw_count = endraw_count = 0
    related = False

    for number, raw_line in enumerate(lines, 1):
        line = raw_line.rstrip("\r\n")
        if front:
            zone = "front_matter"
            if number > 1 and line == "---":
                front = False
                front_closed = True
        else:
            fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
            if fence:
                zone = "fenced_code"
                if fence_match and fence_match.group(1)[0] == fence[0] and len(fence_match.group(1)) >= len(fence):
                    fence = None
            elif fence_match:
                fence = fence_match.group(1)
                zone = "fenced_code"
            elif re.fullmatch(r"\s*{%\s*(raw|endraw)\s*%}\s*", line):
                zone = "raw_boundary_line"
                if "endraw" in line:
                    endraw_count += 1
                    related = False
                else:
                    raw_count += 1
            elif re.match(r"^#\s+", line):
                zone = "h1"
                related = False
            elif re.match(r"^##\s+", line):
                zone = "heading"
                related = line.strip() == "## 相关阅读"
                if related:
                    related_headers += 1
            else:
                zone = "paragraph"

        inline_spans = [(m.start(), m.end()) for m in INLINE_CODE_RE.finditer(line)]
        liquid_spans = [(m.start(), m.end()) for m in LIQUID_RE.finditer(line)]
        html_spans = [(m.start(), m.end()) for m in HTML_TAG_RE.finditer(line)]
        comment_spans: list[tuple[int, int]] = []
        cursor = 0
        while cursor < len(line):
            if html_comment:
                close = line.find("-->", cursor)
                if close < 0:
                    comment_spans.append((cursor, len(line)))
                    break
                comment_spans.append((cursor, close + 3)); html_comment = False; cursor = close + 3
            else:
                opening = line.find("<!--", cursor)
                if opening < 0:
                    break
                close = line.find("-->", opening + 4)
                if close < 0:
                    comment_spans.append((opening, len(line))); html_comment = True; break
                comment_spans.append((opening, close + 3)); cursor = close + 3

        image_spans = [(m.start(), m.end()) for m in IMAGE_RE.finditer(line)]
        strict_spans: list[tuple[int, int]] = []
        for match in LINK_RE.finditer(line):
            if _overlaps(match.start(), match.end(), image_spans):
                continue
            strict_spans.append((match.start(), match.end()))
            link_zone = zone
            if _overlaps(match.start(), match.end(), inline_spans): link_zone = "inline_code"
            elif _overlaps(match.start(), match.end(), liquid_spans): link_zone = "liquid_tag"
            elif _overlaps(match.start(), match.end(), comment_spans): link_zone = "html_comment"
            elif _overlaps(match.start(), match.end(), html_spans): link_zone = "html_attribute"
            links.append(ParsedLink(match.group(1), match.group(2), number, link_zone, related))

        internal_hint = ".html" in line or "./" in line
        if internal_hint:
            remnants = line
            for left, right in sorted(strict_spans + image_spans, reverse=True):
                remnants = remnants[:left] + (" " * (right - left)) + remnants[right:]
            if "[" in remnants or "](" in remnants:
                malformed += 1
            if re.search(r"\[[^\]]*\[[^\]]+\]\([^)]+\)[^\]]*\]\([^)]+\)", line):
                malformed += 1

        if related and zone == "paragraph" and line.strip():
            if not re.fullmatch(r"\s*[-*+]\s+\[[^\]\n]+\]\([^)\n]+\)\s*", line):
                related_errors.append(f"line {number}")

    if not front_closed or fence or html_comment or raw_count != 1 or endraw_count != 1:
        malformed += 1
    if related_headers > 1:
        related_errors.append("multiple related blocks")
    return links, malformed, related_errors, related_headers


def audit_article(
    markdown: str,
    *,
    source: ArticleSpec,
    plan: LinkSelectionPlan,
    registry: RegistrySnapshot,
    registry_version: str,
    config_version: str,
    batch_id: str,
    injection_result: InjectionResult | None = None,
    batch_extension: Sequence[BatchRegistryEntry] = (),
    configured_max: int | None = None,
    file_exists: Callable[[str], bool] | None = None,
    protected_hashes: Mapping[str, str] | None = None,
    current_hashes: Mapping[str, str] | None = None,
) -> InternalLinkAuditResult:
    events: list[AuditEvent] = []
    warnings: list[str] = []
    hard_fail = False
    configured_max = configured_max or plan.configured_max
    file_exists = file_exists or (lambda path: Path(path).is_file())

    def fail(code: str, slug: str = "", message: str = "") -> None:
        nonlocal hard_fail
        hard_fail = True; events.append(AuditEvent(code, slug, message or code))

    computed = compute_registry_version(registry.entries, source_batches=registry.source_batches, schema_version=registry.registry_schema_version)
    versions = [registry_version, plan.registry_version, registry.registry_version, computed]
    if injection_result is not None: versions.append(injection_result.registry_version)
    if len(set(versions)) != 1: fail("REGISTRY_VERSION_MISMATCH")
    configs = [config_version, plan.config_version]
    if injection_result is not None: configs.append(injection_result.config_version)
    if len(set(configs)) != 1: fail("CONFIG_VERSION_MISMATCH")
    if plan.source_slug != source.slug or plan.batch_id != batch_id: fail("SOURCE_OR_BATCH_MISMATCH")
    if protected_hashes is not None and current_hashes is not None and dict(protected_hashes) != dict(current_hashes):
        fail("EXISTING_PRODUCTION_MUTATION_ATTEMPT")

    frozen = {e.slug: e for e in registry.entries}
    extension = {e.slug: e for e in batch_extension}
    planned = {e.target_slug: e for e in plan.selected_targets}
    links, malformed, related_errors, _ = _scan_markdown(markdown)
    malformed += len(related_errors)
    if malformed: fail("MALFORMED_MARKDOWN_LINK")

    targets: list[str] = []
    body = related_count = same_batch = self_links = broken = invalid = out = 0
    protected_counts = Counter()
    anchors: list[str] = []
    cluster_counts = Counter()
    for link in links:
        looks_internal = ".html" in link.url or link.url.startswith(("./", "../", "/"))
        if not looks_internal:
            continue
        match = STRICT_INTERNAL_URL.fullmatch(link.url)
        if not match:
            invalid += 1; fail("INVALID_INTERNAL_URL", message=link.url); continue
        slug = match.group(1); targets.append(slug); anchors.append(normalize_anchor(link.anchor))
        if link.related: related_count += 1
        else: body += 1
        zone_codes = {
            "front_matter": "front_matter_injections", "h1": "front_matter_injections",
            "fenced_code": "code_block_injections", "inline_code": "inline_code_injections",
            "liquid_tag": "liquid_injections", "raw_boundary_line": "liquid_injections",
            "html_attribute": "html_attribute_injections", "html_comment": "html_comment_injections",
        }
        if link.zone in zone_codes:
            protected_counts[zone_codes[link.zone]] += 1; fail("PROTECTED_ZONE_VIOLATION", slug, link.zone)
        if slug == source.slug: self_links += 1; fail("SELF_LINK_REJECTED", slug)
        record = frozen.get(slug)
        ext = extension.get(slug)
        if record is None and ext is None:
            out += 1; fail("OUT_OF_REGISTRY_TARGET", slug); continue
        same = ext is not None
        if same: same_batch += 1
        if slug not in planned: fail("TARGET_NOT_IN_SELECTION_PLAN", slug)
        elif planned[slug].same_batch != same: fail("SAME_BATCH_MARKER_MISMATCH", slug)
        if record is not None:
            valid_entry = record.published and record.eligible_as_target and record.relative_url == link.url and record.canonical_url == CANONICAL_BASE + slug + ".html"
            path = record.markdown_path
            cluster = record.cluster
            title = record.title
        else:
            valid_entry = bool(ext and ext.published and ext.eligible_as_target and ext.content_quality_pass)
            path = ext.markdown_path
            cluster = ext.cluster
            title = ext.title
        if not valid_entry:
            invalid += 1; fail("INVALID_REGISTRY_TARGET", slug)
        if not file_exists(path):
            broken += 1; fail("BROKEN_TARGET", slug)
        target = TargetRecord(slug, title, cluster, path, True, True, True, "batch_extension" if same else "frozen_registry", same)
        score, _ = score_relevance(source, target)
        if score < MIN_RELEVANCE_SCORE: fail("RELEVANCE_BELOW_THRESHOLD", slug)
        cluster_counts[cluster] += 1

    duplicates = sum(count - 1 for count in Counter(targets).values() if count > 1)
    if duplicates: fail("DUPLICATE_TARGET_REJECTED")
    normalized = [a for a in anchors if a]
    anchor_duplicates = sum(count - 1 for count in Counter(normalized).values() if count > 1)
    if anchor_duplicates: fail("ANCHOR_DUPLICATE")
    if any(not a or not ANCHOR_MIN_LENGTH <= len(a) <= ANCHOR_MAX_LENGTH for a in anchors): fail("ANCHOR_LENGTH_INVALID")
    if related_count > RELATED_MAX: fail("RELATED_MAX_EXCEEDED")
    total = body + related_count
    if total > configured_max: fail("CONFIGURED_MAX_EXCEEDED")
    if same_batch * 100 > total * SAME_BATCH_MAX_PERCENT: fail("SAME_BATCH_CAP_EXCEEDED")
    if 24 <= total <= 30 and related_count < 8: warnings.append("PLACEMENT_TARGET_NOT_MET")
    reason = plan.shortfall_reason
    if total < 20 and reason not in ALLOWED_SHORTFALL_REASONS:
        fail("INVALID_SHORTFALL_REASON")
    if hard_fail: status = "FAIL"
    elif total < 20: status = "PASS_WITH_SHORTFALL"
    else: status = "PASS"
    same_cluster = cluster_counts.get(source.cluster, 0) if source.cluster != "unclassified" else 0
    return InternalLinkAuditResult(
        source.slug, total, len(set(targets)), body, related_count, same_batch, self_links, duplicates,
        broken, invalid, out, protected_counts["code_block_injections"], protected_counts["front_matter_injections"],
        protected_counts["inline_code_injections"], protected_counts["liquid_injections"],
        protected_counts["html_attribute_injections"], protected_counts["html_comment_injections"], malformed,
        anchor_duplicates, {"same_cluster": same_cluster, "cross_cluster": total - same_cluster,
        "unclassified": cluster_counts.get("unclassified", 0), "per_cluster_counts": dict(sorted(cluster_counts.items()))},
        reason, tuple(warnings), registry_version, config_version, tuple(events), status,
    )


def audit_batch(results: Sequence[InternalLinkAuditResult], article_targets: Mapping[str, Sequence[str]]) -> BatchAuditResult:
    cap = max(2, math.ceil(len(results) * 0.20))
    inbound: dict[str, set[str]] = defaultdict(set)
    for source, targets in article_targets.items():
        for target in set(targets): inbound[target].add(source)
    violations = tuple(BatchInboundViolation(t, len(s), cap) for t, s in sorted(inbound.items()) if len(s) > cap)
    status = "FAIL" if violations or any(r.final_status == "FAIL" for r in results) else "PASS"
    return BatchAuditResult(tuple(results), cap, violations, status)
