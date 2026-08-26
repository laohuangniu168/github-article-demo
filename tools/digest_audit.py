from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from digest_generator import (
    DigestGeneratedContent,
    DigestRenderResult,
    render_digest_markdown,
)
from digest_planner import DigestArticlePlan
from digest_registry import DigestRegistry, compute_digest_registry_version


FINAL_STATUS_PASS = "PASS"
FINAL_STATUS_FAIL = "FAIL"

_H1_PATTERN = re.compile(r"^# (.+)$", re.MULTILINE)
_H2_PATTERN = re.compile(r"^## (.+)$", re.MULTILINE)
_H3_PATTERN = re.compile(r"^### (.+)$", re.MULTILINE)
_REFERENCE_PATTERN = re.compile(r"^\| 详见 \[([^\]\r\n]+)\]\(([^()\s<>\r\n]+)\)$")
_MARKDOWN_LINK_PATTERN = re.compile(r"!?\[([^\]\r\n]+)\]\(([^()\s<>\r\n]+)\)")
_HTML_PATTERN = re.compile(r"</?[A-Za-z][^>]*>")
_UNSAFE_TOKENS = (
    "<script",
    "<iframe",
    "<style",
    "javascript:",
    "data:",
    "onclick=",
    "onerror=",
    "display:none",
    "visibility:hidden",
    "font-size:0",
)


@dataclass(frozen=True)
class DigestAuditIssue:
    code: str
    message: str
    entry_id: str | None = None
    field: str | None = None
    expected: Any = None
    actual: Any = None


@dataclass(frozen=True)
class DigestAuditResult:
    digest_id: str
    filename: str
    status: str
    input_entry_count: int
    registry_entry_count: int
    plan_entry_count: int
    ai_entry_count: int
    rendered_entry_count: int
    rendered_href_count: int
    h1_count: int
    h2_count: int
    h3_count: int
    raw_count: int
    endraw_count: int
    raw_endraw_valid: bool
    missing_entry_ids: tuple[str, ...]
    duplicate_entry_ids: tuple[str, ...]
    unknown_entry_ids: tuple[str, ...]
    missing_urls: tuple[str, ...]
    duplicate_urls: tuple[str, ...]
    extra_urls: tuple[str, ...]
    title_mismatches: tuple[str, ...]
    url_mismatches: tuple[str, ...]
    malformed_links: tuple[str, ...]
    unsafe_markup: tuple[str, ...]
    errors: tuple[DigestAuditIssue, ...]
    warnings: tuple[DigestAuditIssue, ...]
    markdown_sha256: str
    deterministic_reconstruction: bool


def _add(
    errors: list[DigestAuditIssue],
    code: str,
    message: str,
    *,
    entry_id: str | None = None,
    field: str | None = None,
    expected: Any = None,
    actual: Any = None,
) -> None:
    issue = DigestAuditIssue(
        code=code,
        message=message,
        entry_id=entry_id,
        field=field,
        expected=expected,
        actual=actual,
    )
    if issue not in errors:
        errors.append(issue)


def _parse_front_matter(markdown: str, errors: list[DigestAuditIssue]) -> dict[str, str]:
    lines = markdown.splitlines()
    if not lines or lines[0] != "---":
        _add(errors, "DIGEST_AUDIT_FRONT_MATTER_INVALID", "Markdown 未以 Front Matter 开始")
        return {}
    delimiters = [index for index, line in enumerate(lines) if line == "---"]
    if len(delimiters) != 2 or delimiters[1] < 2:
        _add(
            errors,
            "DIGEST_AUDIT_FRONT_MATTER_INVALID",
            "Front Matter 必须恰好包含一组起止 delimiter",
            expected=2,
            actual=len(delimiters),
        )
        return {}
    values: dict[str, str] = {}
    for line in lines[1 : delimiters[1]]:
        if ":" not in line:
            _add(errors, "DIGEST_AUDIT_FRONT_MATTER_INVALID", "Front Matter 字段格式非法")
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if key in values:
            _add(errors, "DIGEST_AUDIT_FRONT_MATTER_INVALID", f"Front Matter 字段重复：{key}")
            continue
        try:
            value = json.loads(raw_value.strip())
        except json.JSONDecodeError:
            value = raw_value.strip()
        if not isinstance(value, str):
            _add(errors, "DIGEST_AUDIT_FRONT_MATTER_INVALID", f"Front Matter 字段必须为字符串：{key}")
            continue
        values[key] = value
    if not values.get("title") or not values.get("description"):
        _add(errors, "DIGEST_AUDIT_FRONT_MATTER_INVALID", "Front Matter 缺少非空 title 或 description")
    return values


def _generated_ids(generated_content: DigestGeneratedContent) -> list[str]:
    return [entry.entry_id for section in generated_content.sections for entry in section.entries]


def _reference_lines(markdown: str) -> tuple[list[tuple[str, str]], list[str]]:
    references: list[tuple[str, str]] = []
    malformed: list[str] = []
    for line in markdown.splitlines():
        if "| 详见" not in line:
            continue
        match = _REFERENCE_PATTERN.fullmatch(line)
        if match is None:
            malformed.append(line)
        else:
            references.append((match.group(1), match.group(2)))
    return references, malformed


def _raw_structure_valid(markdown: str) -> bool:
    lines = markdown.splitlines()
    raw_positions = [index for index, line in enumerate(lines) if line == "{% raw %}"]
    end_positions = [index for index, line in enumerate(lines) if line == "{% endraw %}"]
    if len(raw_positions) != 1 or len(end_positions) != 1:
        return False
    raw_index, end_index = raw_positions[0], end_positions[0]
    h1_positions = [index for index, line in enumerate(lines) if line.startswith("# ")]
    if len(h1_positions) != 1 or not h1_positions[0] < raw_index < end_index:
        return False
    return all(not line.strip() for line in lines[end_index + 1 :])


def audit_digest_article(
    *,
    registry: DigestRegistry,
    plan: DigestArticlePlan,
    generated_content: DigestGeneratedContent,
    render_result: DigestRenderResult,
    published_date: str,
) -> DigestAuditResult:
    errors: list[DigestAuditIssue] = []
    warnings: list[DigestAuditIssue] = []
    markdown = render_result.markdown if isinstance(render_result.markdown, str) else ""
    registry_by_id = {entry.id: entry for entry in registry.entries}

    try:
        expected_registry_version = compute_digest_registry_version(
            registry.entries,
            schema_version=registry.schema_version,
            config_version=registry.config_version,
        )
    except Exception as exc:
        expected_registry_version = ""
        _add(errors, "DIGEST_AUDIT_REGISTRY_VERSION_MISMATCH", f"Registry 无法重算：{type(exc).__name__}")
    if (
        expected_registry_version != registry.digest_registry_version
        or plan.digest_registry_version != registry.digest_registry_version
    ):
        _add(
            errors,
            "DIGEST_AUDIT_REGISTRY_VERSION_MISMATCH",
            "Plan、Registry payload 与 Registry version 不一致",
            expected=registry.digest_registry_version,
            actual=plan.digest_registry_version,
        )

    plan_ids = list(plan.entry_ids)
    if plan.entry_count != len(plan_ids) or plan.entry_count != len(plan.entry_identities):
        _add(errors, "DIGEST_AUDIT_ENTRY_IDENTITY_MISMATCH", "Plan entry count/identity arrays 不一致")
    for index, entry_id in enumerate(plan_ids):
        entry = registry_by_id.get(entry_id)
        if entry is None:
            _add(errors, "DIGEST_AUDIT_UNKNOWN_ENTRY", "Plan entry 不在 Registry", entry_id=entry_id)
            continue
        if index >= len(plan.entry_identities) or plan.entry_identities[index] != entry.normalized_identity:
            _add(
                errors,
                "DIGEST_AUDIT_ENTRY_IDENTITY_MISMATCH",
                "Plan entry identity 与 Registry 不一致",
                entry_id=entry_id,
                expected=entry.normalized_identity,
                actual=plan.entry_identities[index] if index < len(plan.entry_identities) else None,
            )

    if render_result.filename != plan.filename:
        _add(
            errors,
            "DIGEST_AUDIT_FILENAME_MISMATCH",
            "Render filename 不是 Planner filename",
            field="filename",
            expected=plan.filename,
            actual=render_result.filename,
        )
    if generated_content.digest_id != plan.digest_id or render_result.digest_id != plan.digest_id:
        _add(
            errors,
            "DIGEST_AUDIT_DIGEST_ID_MISMATCH",
            "GeneratedContent/RenderResult digest_id 与 Plan 不一致",
            expected=plan.digest_id,
            actual=(generated_content.digest_id, render_result.digest_id),
        )

    generated_ids = _generated_ids(generated_content)
    expected_id_set = set(plan_ids)
    seen: set[str] = set()
    duplicate_ids: set[str] = set()
    unknown_ids: set[str] = set()
    for entry_id in generated_ids:
        if entry_id in seen:
            duplicate_ids.add(entry_id)
        seen.add(entry_id)
        if entry_id not in expected_id_set:
            unknown_ids.add(entry_id)
    missing_ids = expected_id_set - set(generated_ids)
    if missing_ids:
        _add(errors, "DIGEST_AUDIT_ENTRY_MISSING", "GeneratedContent 缺少 Plan entries", actual=sorted(missing_ids))
    if duplicate_ids:
        _add(errors, "DIGEST_AUDIT_ENTRY_DUPLICATED", "GeneratedContent entries 重复", actual=sorted(duplicate_ids))
    if unknown_ids:
        _add(errors, "DIGEST_AUDIT_UNKNOWN_ENTRY", "GeneratedContent 包含未知 entries", actual=sorted(unknown_ids))

    front_matter = _parse_front_matter(markdown, errors)
    if front_matter.get("title") != generated_content.digest_title:
        _add(
            errors,
            "DIGEST_AUDIT_TITLE_MISMATCH",
            "Front Matter title 与 GeneratedContent 不一致",
            expected=generated_content.digest_title,
            actual=front_matter.get("title"),
        )
    h1_values = _H1_PATTERN.findall(markdown)
    h2_values = _H2_PATTERN.findall(markdown)
    h3_values = _H3_PATTERN.findall(markdown)
    if h1_values != [generated_content.digest_title]:
        _add(errors, "DIGEST_AUDIT_H1_INVALID", "H1 必须恰好等于 digest title", expected=[generated_content.digest_title], actual=h1_values)
    expected_sections = [section.name for section in generated_content.sections]
    if h2_values != expected_sections:
        _add(errors, "DIGEST_AUDIT_SECTION_MISMATCH", "H2 顺序/名称与 GeneratedContent 不一致", expected=expected_sections, actual=h2_values)

    expected_entries = []
    expected_titles: list[str] = []
    expected_urls: list[str] = []
    expected_summaries: list[str] = []
    expected_membership: list[tuple[str, str]] = []
    for section in generated_content.sections:
        for generated_entry in section.entries:
            entry = registry_by_id.get(generated_entry.entry_id)
            if entry is None:
                continue
            expected_entries.append(entry)
            expected_titles.append(entry.title)
            expected_urls.append(entry.url_exact)
            expected_summaries.append(generated_entry.summary)
            expected_membership.append((section.name, entry.title))

    title_mismatches: list[str] = []
    if h3_values != expected_titles:
        for index in range(max(len(h3_values), len(expected_titles))):
            expected = expected_titles[index] if index < len(expected_titles) else None
            actual = h3_values[index] if index < len(h3_values) else None
            if expected != actual:
                title_mismatches.append(f"{index}:{expected!r}!={actual!r}")
        _add(errors, "DIGEST_AUDIT_TITLE_MISMATCH", "H3 titles 与 Registry authority 不一致", expected=expected_titles, actual=h3_values)

    references, malformed_links = _reference_lines(markdown)
    all_links = [(match.group(1), match.group(2)) for match in _MARKDOWN_LINK_PATTERN.finditer(markdown)]
    reference_set = list(references)
    if malformed_links:
        _add(errors, "DIGEST_AUDIT_REFERENCE_FORMAT_INVALID", "存在 malformed Digest reference", actual=malformed_links)
    if all_links != reference_set:
        _add(errors, "DIGEST_AUDIT_EXTRA_HREF", "存在非冻结 Reference 格式的 Markdown link", actual=all_links)
    actual_anchors = [anchor for anchor, _ in references]
    actual_urls = [url for _, url in references]
    if actual_anchors != expected_titles:
        _add(errors, "DIGEST_AUDIT_TITLE_MISMATCH", "Reference anchors 与 Registry titles 不一致", expected=expected_titles, actual=actual_anchors)
    url_mismatches: list[str] = []
    if actual_urls != expected_urls:
        for index in range(max(len(actual_urls), len(expected_urls))):
            expected = expected_urls[index] if index < len(expected_urls) else None
            actual = actual_urls[index] if index < len(actual_urls) else None
            if expected != actual:
                url_mismatches.append(f"{index}:{expected!r}!={actual!r}")
        _add(errors, "DIGEST_AUDIT_URL_MISMATCH", "Reference URLs 与 Registry url_exact 不一致", expected=expected_urls, actual=actual_urls)

    missing_urls = sorted(url for url in set(expected_urls) if actual_urls.count(url) == 0)
    duplicate_urls = sorted(url for url in set(expected_urls) if actual_urls.count(url) > 1)
    extra_urls = sorted(url for url in set(actual_urls) if url not in set(expected_urls))
    if missing_urls:
        _add(errors, "DIGEST_AUDIT_URL_MISMATCH", "缺少 Registry URL", actual=missing_urls)
    if duplicate_urls:
        _add(errors, "DIGEST_AUDIT_URL_MISMATCH", "Registry URL 重复", actual=duplicate_urls)
    if extra_urls:
        _add(errors, "DIGEST_AUDIT_EXTRA_HREF", "存在 Registry 之外的 href", actual=extra_urls)

    raw_count = markdown.count("{% raw %}")
    endraw_count = markdown.count("{% endraw %}")
    raw_valid = _raw_structure_valid(markdown)
    if not raw_valid:
        _add(errors, "DIGEST_AUDIT_RAW_BOUNDARY_INVALID", "raw/endraw 数量、顺序或正文边界非法")
    date_line = f"发布日期：{published_date}"
    if markdown.splitlines().count(date_line) != 1:
        _add(errors, "DIGEST_AUDIT_PUBLISHED_DATE_MISMATCH", "发布日期与 caller 输入不一致", expected=date_line)

    unsafe_markup: list[str] = []
    folded = markdown.casefold()
    html_matches = _HTML_PATTERN.findall(markdown)
    if html_matches:
        unsafe_markup.extend(html_matches)
        _add(errors, "DIGEST_AUDIT_HTML_MARKUP_FORBIDDEN", "Digest Markdown 禁止 HTML 标签", actual=html_matches)
    for token in _UNSAFE_TOKENS:
        if token in folded:
            unsafe_markup.append(token)
    liquid_lines = [line for line in markdown.splitlines() if "{%" in line and line not in ("{% raw %}", "{% endraw %}")]
    if liquid_lines:
        unsafe_markup.extend(liquid_lines)
    if unsafe_markup:
        _add(errors, "DIGEST_AUDIT_AI_LEAKAGE", "最终 Markdown 包含不安全 markup", actual=unsafe_markup)
    for line in markdown.splitlines():
        if ("http://" in line.casefold() or "https://" in line.casefold()) and _REFERENCE_PATTERN.fullmatch(line) is None:
            _add(errors, "DIGEST_AUDIT_AI_LEAKAGE", "裸 URL 或非 Reference URL", actual=line)

    expected_block_lines: list[tuple[str, str, str, str]] = []
    for section, entry, summary in zip(
        [section.name for section in generated_content.sections for _ in section.entries],
        expected_entries,
        expected_summaries,
    ):
        expected_block_lines.append((section, entry.title, summary, entry.url_exact))
    actual_blocks: list[tuple[str, str, str, str]] = []
    lines = markdown.splitlines()
    current_section: str | None = None
    for index, line in enumerate(lines):
        if line.startswith("## "):
            current_section = line[3:]
        if line.startswith("### "):
            title = line[4:]
            summary = lines[index + 2] if index + 2 < len(lines) else ""
            reference_line = lines[index + 4] if index + 4 < len(lines) else ""
            match = _REFERENCE_PATTERN.fullmatch(reference_line)
            actual_blocks.append((current_section or "", title, summary, match.group(2) if match else ""))
    if actual_blocks != expected_block_lines:
        _add(errors, "DIGEST_AUDIT_STRUCTURE_INVALID", "Section/H3/Summary/Reference block 不符合 GeneratedContent", expected=expected_block_lines, actual=actual_blocks)
        if [block[2] for block in actual_blocks] != expected_summaries:
            _add(errors, "DIGEST_AUDIT_SUMMARY_MISMATCH", "Summary 与 GeneratedContent 不一致")
        if [(block[0], block[1]) for block in actual_blocks] != expected_membership:
            _add(errors, "DIGEST_AUDIT_SECTION_MEMBERSHIP_MISMATCH", "Entry section membership 不一致")

    computed_sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    if computed_sha != render_result.sha256:
        _add(errors, "DIGEST_AUDIT_RENDER_SHA_MISMATCH", "RenderResult SHA 与 Markdown 不一致", expected=computed_sha, actual=render_result.sha256)
    if (
        render_result.entry_count != plan.entry_count
        or render_result.rendered_entry_count != len(h3_values)
        or render_result.rendered_href_count != len(references)
    ):
        _add(errors, "DIGEST_AUDIT_RENDER_COUNT_MISMATCH", "RenderResult 自报计数与独立解析不一致")

    deterministic_reconstruction = False
    try:
        reconstructed = render_digest_markdown(
            plan=plan,
            registry=registry,
            generated_content=generated_content,
            published_date=published_date,
        )
        deterministic_reconstruction = (
            reconstructed.markdown == markdown
            and reconstructed.sha256 == render_result.sha256
            and reconstructed.filename == render_result.filename
        )
    except Exception as exc:
        _add(errors, "DIGEST_AUDIT_DETERMINISTIC_RECONSTRUCTION_MISMATCH", f"确定性重建失败：{type(exc).__name__}")
    if not deterministic_reconstruction:
        _add(errors, "DIGEST_AUDIT_DETERMINISTIC_RECONSTRUCTION_MISMATCH", "确定性重建与 RenderResult 不一致")

    return DigestAuditResult(
        digest_id=plan.digest_id,
        filename=plan.filename,
        status=FINAL_STATUS_FAIL if errors else FINAL_STATUS_PASS,
        input_entry_count=plan.entry_count,
        registry_entry_count=sum(1 for entry_id in plan_ids if entry_id in registry_by_id),
        plan_entry_count=len(plan_ids),
        ai_entry_count=len(generated_ids),
        rendered_entry_count=len(h3_values),
        rendered_href_count=len(references),
        h1_count=len(h1_values),
        h2_count=len(h2_values),
        h3_count=len(h3_values),
        raw_count=raw_count,
        endraw_count=endraw_count,
        raw_endraw_valid=raw_valid,
        missing_entry_ids=tuple(sorted(missing_ids)),
        duplicate_entry_ids=tuple(sorted(duplicate_ids)),
        unknown_entry_ids=tuple(sorted(unknown_ids)),
        missing_urls=tuple(missing_urls),
        duplicate_urls=tuple(duplicate_urls),
        extra_urls=tuple(extra_urls),
        title_mismatches=tuple(title_mismatches),
        url_mismatches=tuple(url_mismatches),
        malformed_links=tuple(malformed_links),
        unsafe_markup=tuple(unsafe_markup),
        errors=tuple(errors),
        warnings=tuple(warnings),
        markdown_sha256=computed_sha,
        deterministic_reconstruction=deterministic_reconstruction,
    )
