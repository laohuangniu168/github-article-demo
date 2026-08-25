from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit


CONTRACT_VERSION = "v1.1.1-gate2"
SPECIFIED_LINK_SCHEMA_VERSION = "1"
SPECIFIED_LINK_CONFIG_VERSION = "v1.1.1-default-1"
SPECIFIED_LINK_EVIDENCE_VERSION = "1"

DEFAULT_SPECIFIED_LINKS_PER_ARTICLE = 1
DEFAULT_SPECIFIED_LINKS_TARGET_MAX = 2
MAX_SPECIFIED_LINKS_PER_ARTICLE = 3
SPECIFIED_ANCHOR_MIN_LENGTH = 2
SPECIFIED_ANCHOR_MAX_LENGTH = 40

ALLOWED_SCHEMES = frozenset({"http", "https"})
HTTPS_REQUIRED = "HTTPS_REQUIRED"  # Legacy error-code compatibility; not used for valid HTTP.
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HOST_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
ALLOWED_CLUSTERS = frozenset(
    {
        "baidu-crawl",
        "baidu-indexing",
        "baidu-seo",
        "technical-seo",
        "keyword-research",
        "content-seo",
        "site-architecture",
        "internal-linking",
        "github-pages",
        "markdown-static-site",
    }
)
FORBIDDEN_ANCHORS = frozenset(
    {"点击这里", "查看更多", "更多内容", "click here", "read more", "learn more"}
)
FORBIDDEN_HOSTS = (
    "local",
    "internal",
    "localhost",
    "test",
    "invalid",
    "example",
    "example.com",
    "example.net",
    "example.org",
)
PREFLIGHT_ERROR_CODES = frozenset(
    {
        "TARGET_URL_REDIRECT",
        "TARGET_URL_HTTP_ERROR",
        "TARGET_URL_DNS_ERROR",
        "TARGET_URL_TLS_ERROR",
        "TARGET_URL_TIMEOUT",
        "TARGET_URL_CONNECTION_ERROR",
    }
)
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class SpecifiedLinkContractError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        line_number: int | None = None,
        entry_id: str | None = None,
    ) -> None:
        self.code = code
        self.line_number = line_number
        self.entry_id = entry_id
        self.message = message
        context = []
        if line_number is not None:
            context.append(f"line={line_number}")
        if entry_id is not None:
            context.append(f"entry_id={entry_id}")
        suffix = f" ({', '.join(context)})" if context else ""
        super().__init__(f"{code}: {message}{suffix}")


@dataclass(frozen=True)
class SpecifiedLinkSpec:
    id: str
    url: str
    canonical_url: str
    anchor: str
    normalized_anchor: str
    cluster: str
    source_filename: str
    source_line: int


@dataclass(frozen=True)
class SpecifiedLinkRegistry:
    schema_version: str
    config_version: str
    entries: tuple[SpecifiedLinkSpec, ...]
    specified_link_version: str


@dataclass(frozen=True)
class SpecifiedLinkPreflightResult:
    entry_id: str
    configured_url: str
    canonical_url: str
    status_code: int | None
    redirect_location: str | None
    checked_at: str
    result: str
    error_code: str | None


def _fail(
    code: str,
    message: str,
    *,
    line_number: int | None = None,
    entry_id: str | None = None,
) -> None:
    raise SpecifiedLinkContractError(
        code,
        message,
        line_number=line_number,
        entry_id=entry_id,
    )


def _is_forbidden_host(hostname: str) -> bool:
    return any(hostname == suffix or hostname.endswith("." + suffix) for suffix in FORBIDDEN_HOSTS)


def canonicalize_specified_url(url: str) -> str:
    value = url.strip()
    if not value:
        _fail("INVALID_SPECIFIED_URL", "URL 不能为空")
    if "\\" in value:
        _fail("INVALID_SPECIFIED_URL", "URL 不允许反斜杠")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        _fail("INVALID_SPECIFIED_URL", "URL 不允许空白或控制字符")

    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        _fail("INVALID_SPECIFIED_URL", f"URL 解析失败：{exc}")

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        _fail("INVALID_SPECIFIED_URL", "Specified Link 仅允许 HTTP 或 HTTPS")
    if parsed.query:
        _fail("URL_QUERY_NOT_ALLOWED", "URL 不允许 query string")
    if parsed.fragment:
        _fail("URL_FRAGMENT_NOT_ALLOWED", "URL 不允许 fragment")
    if parsed.username is not None or parsed.password is not None:
        _fail("INVALID_SPECIFIED_URL", "URL 不允许 userinfo")

    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        _fail("INVALID_SPECIFIED_URL", f"URL host/port 非法：{exc}")
    if not hostname:
        _fail("INVALID_SPECIFIED_URL", "URL hostname 不能为空")
    if not hostname.isascii():
        _fail("INVALID_SPECIFIED_URL", "URL hostname 仅允许 ASCII DNS 名称")

    hostname = hostname.lower()
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        _fail("LOCAL_OR_IP_TARGET_REJECTED", "不允许 IP literal target")

    if hostname.endswith(".") or ".." in hostname:
        _fail("INVALID_SPECIFIED_URL", "URL hostname label 非法")
    if len(hostname) > 253:
        _fail("INVALID_SPECIFIED_URL", "URL hostname 过长")
    labels = hostname.split(".")
    if any(not HOST_LABEL_PATTERN.fullmatch(label) for label in labels):
        _fail("INVALID_SPECIFIED_URL", "URL hostname 含非法 label")
    if _is_forbidden_host(hostname):
        _fail("LOCAL_OR_IP_TARGET_REJECTED", "不允许本地、保留或示例 target")
    default_port = 80 if scheme == "http" else 443
    if port not in (None, default_port):
        _fail("INVALID_SPECIFIED_URL", "URL 仅允许与协议匹配的默认端口")

    path = parsed.path or "/"
    if any(segment in {".", ".."} for segment in path.split("/")):
        _fail("INVALID_SPECIFIED_URL", "URL path 不允许 dot segment")
    netloc = hostname
    return urlunsplit((scheme, netloc, path, "", ""))


def normalize_specified_anchor(anchor: str) -> str:
    normalized = unicodedata.normalize("NFC", anchor).casefold()
    normalized = " ".join(normalized.split())
    start = 0
    end = len(normalized)
    while start < end and unicodedata.category(normalized[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(normalized[end - 1]).startswith("P"):
        end -= 1
    return normalized[start:end].strip()


def validate_specified_link_spec(spec: SpecifiedLinkSpec) -> None:
    if not ID_PATTERN.fullmatch(spec.id):
        _fail(
            "INVALID_SPECIFIED_INPUT_FORMAT",
            "Specified Link ID 格式非法",
            line_number=spec.source_line,
            entry_id=spec.id or None,
        )
    canonical = canonicalize_specified_url(spec.url)
    if canonical != spec.canonical_url:
        _fail("INVALID_SPECIFIED_URL", "canonical URL 与原 URL 不一致", entry_id=spec.id)
    if not SPECIFIED_ANCHOR_MIN_LENGTH <= len(spec.anchor) <= SPECIFIED_ANCHOR_MAX_LENGTH:
        _fail(
            "INVALID_SPECIFIED_ANCHOR_LENGTH",
            "anchor 长度必须为 2–40 Unicode code points",
            line_number=spec.source_line,
            entry_id=spec.id,
        )
    normalized_anchor = normalize_specified_anchor(spec.anchor)
    if not normalized_anchor:
        _fail("EMPTY_SPECIFIED_ANCHOR", "anchor 归一化后为空", entry_id=spec.id)
    if normalized_anchor != spec.normalized_anchor:
        _fail("INVALID_SPECIFIED_INPUT_FORMAT", "normalized anchor 不一致", entry_id=spec.id)
    if normalized_anchor in FORBIDDEN_ANCHORS:
        _fail("FORBIDDEN_SPECIFIED_ANCHOR", "禁止泛化 anchor", entry_id=spec.id)
    if spec.cluster not in ALLOWED_CLUSTERS:
        _fail("INVALID_SPECIFIED_CLUSTER", "Specified Link cluster 非法", entry_id=spec.id)


def parse_specified_link_lines(
    lines: Iterable[str],
    *,
    source_filename: str = "<memory>",
) -> tuple[SpecifiedLinkSpec, ...]:
    entries: list[SpecifiedLinkSpec] = []
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue
        fields = line.split("|")
        if len(fields) != 4:
            _fail(
                "INVALID_SPECIFIED_INPUT_FORMAT",
                "每个非空行必须恰好包含四个字段",
                line_number=line_number,
            )
        entry_id, raw_url, raw_anchor, cluster = (field.strip() for field in fields)
        if not all((entry_id, raw_url, raw_anchor, cluster)):
            _fail("INVALID_SPECIFIED_INPUT_FORMAT", "Specified Link 字段不能为空", line_number=line_number)
        if not ID_PATTERN.fullmatch(entry_id):
            _fail(
                "INVALID_SPECIFIED_INPUT_FORMAT",
                "Specified Link ID 格式非法",
                line_number=line_number,
                entry_id=entry_id,
            )
        if entry_id in seen_ids:
            _fail(
                "DUPLICATE_SPECIFIED_LINK_ID",
                "Specified Link ID 重复",
                line_number=line_number,
                entry_id=entry_id,
            )

        canonical_url = canonicalize_specified_url(raw_url)
        if not SPECIFIED_ANCHOR_MIN_LENGTH <= len(raw_anchor) <= SPECIFIED_ANCHOR_MAX_LENGTH:
            _fail(
                "INVALID_SPECIFIED_ANCHOR_LENGTH",
                "anchor 长度必须为 2–40 Unicode code points",
                line_number=line_number,
                entry_id=entry_id,
            )
        normalized_anchor = normalize_specified_anchor(raw_anchor)
        if not normalized_anchor:
            _fail("EMPTY_SPECIFIED_ANCHOR", "anchor 归一化后为空", line_number=line_number, entry_id=entry_id)
        if normalized_anchor in FORBIDDEN_ANCHORS:
            _fail(
                "FORBIDDEN_SPECIFIED_ANCHOR",
                "禁止泛化 anchor",
                line_number=line_number,
                entry_id=entry_id,
            )
        if cluster not in ALLOWED_CLUSTERS:
            _fail(
                "INVALID_SPECIFIED_CLUSTER",
                "Specified Link cluster 非法",
                line_number=line_number,
                entry_id=entry_id,
            )
        pair = (canonical_url, normalized_anchor)
        if pair in seen_pairs:
            _fail(
                "DUPLICATE_SPECIFIED_URL_ANCHOR",
                "canonical URL + normalized anchor 重复",
                line_number=line_number,
                entry_id=entry_id,
            )

        spec = SpecifiedLinkSpec(
            id=entry_id,
            url=raw_url,
            canonical_url=canonical_url,
            anchor=raw_anchor,
            normalized_anchor=normalized_anchor,
            cluster=cluster,
            source_filename=source_filename,
            source_line=line_number,
        )
        validate_specified_link_spec(spec)
        entries.append(spec)
        seen_ids.add(entry_id)
        seen_pairs.add(pair)

    return tuple(entries)


def parse_specified_link_file(path: Path) -> tuple[SpecifiedLinkSpec, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return parse_specified_link_lines(handle, source_filename=path.name)


def _canonical_payload(
    entries: Sequence[SpecifiedLinkSpec],
    *,
    schema_version: str,
    config_version: str,
) -> dict[str, object]:
    return {
        "config_version": config_version,
        "entries": [
            {
                "anchor": entry.anchor,
                "canonical_url": entry.canonical_url,
                "cluster": entry.cluster,
                "id": entry.id,
                "normalized_anchor": entry.normalized_anchor,
            }
            for entry in sorted(entries, key=lambda item: item.id)
        ],
        "schema_version": schema_version,
    }


def compute_specified_link_version(
    entries: Sequence[SpecifiedLinkSpec],
    *,
    schema_version: str = SPECIFIED_LINK_SCHEMA_VERSION,
    config_version: str = SPECIFIED_LINK_CONFIG_VERSION,
) -> str:
    payload = _canonical_payload(
        entries,
        schema_version=schema_version,
        config_version=config_version,
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "slr1:" + hashlib.sha256(encoded).hexdigest()


def build_specified_link_registry(
    entries: Sequence[SpecifiedLinkSpec],
    *,
    schema_version: str = SPECIFIED_LINK_SCHEMA_VERSION,
    config_version: str = SPECIFIED_LINK_CONFIG_VERSION,
) -> SpecifiedLinkRegistry:
    sorted_entries = tuple(sorted(entries, key=lambda item: item.id))
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for entry in sorted_entries:
        validate_specified_link_spec(entry)
        if entry.id in seen_ids:
            _fail("DUPLICATE_SPECIFIED_LINK_ID", "Specified Link ID 重复", entry_id=entry.id)
        pair = (entry.canonical_url, entry.normalized_anchor)
        if pair in seen_pairs:
            _fail("DUPLICATE_SPECIFIED_URL_ANCHOR", "canonical URL + normalized anchor 重复", entry_id=entry.id)
        seen_ids.add(entry.id)
        seen_pairs.add(pair)
    version = compute_specified_link_version(
        sorted_entries,
        schema_version=schema_version,
        config_version=config_version,
    )
    return SpecifiedLinkRegistry(schema_version, config_version, sorted_entries, version)


def _expected_preflight_error(status_code: int | None, error_code: str | None) -> str | None:
    if status_code is not None:
        if 200 <= status_code <= 299:
            return None
        if status_code in REDIRECT_STATUS_CODES:
            return "TARGET_URL_REDIRECT"
        if 400 <= status_code <= 599:
            return "TARGET_URL_HTTP_ERROR"
        return "TARGET_URL_HTTP_ERROR"
    if error_code in {
        "TARGET_URL_DNS_ERROR",
        "TARGET_URL_TLS_ERROR",
        "TARGET_URL_TIMEOUT",
        "TARGET_URL_CONNECTION_ERROR",
    }:
        return error_code
    return "TARGET_URL_HTTP_ERROR"


def validate_preflight_result(
    preflight: SpecifiedLinkPreflightResult,
    registry: SpecifiedLinkRegistry,
) -> SpecifiedLinkPreflightResult:
    entries = {entry.id: entry for entry in registry.entries}
    entry = entries.get(preflight.entry_id)
    if entry is None:
        _fail("UNAPPROVED_SPECIFIED_URL", "Preflight entry ID 不存在", entry_id=preflight.entry_id)
    if preflight.configured_url != entry.url or preflight.canonical_url != entry.canonical_url:
        _fail("UNAPPROVED_SPECIFIED_URL", "Preflight URL 与 Registry identity 不一致", entry_id=preflight.entry_id)
    if preflight.result not in {"PASS", "FAIL"}:
        _fail("UNAPPROVED_SPECIFIED_URL", "Preflight result 必须为 PASS 或 FAIL", entry_id=preflight.entry_id)
    if entry.canonical_url.startswith("http://") and preflight.error_code == "TARGET_URL_TLS_ERROR":
        _fail("UNAPPROVED_SPECIFIED_URL", "HTTP target 不适用 TLS failure", entry_id=preflight.entry_id)

    expected_error = _expected_preflight_error(preflight.status_code, preflight.error_code)
    if expected_error is None:
        if preflight.result != "PASS" or preflight.error_code is not None or preflight.redirect_location is not None:
            _fail("UNAPPROVED_SPECIFIED_URL", "2xx Preflight evidence 不一致", entry_id=preflight.entry_id)
        return preflight

    if preflight.result != "FAIL" or preflight.error_code != expected_error:
        _fail(expected_error, "Preflight failure evidence 不一致", entry_id=preflight.entry_id)
    if expected_error == "TARGET_URL_REDIRECT" and not preflight.redirect_location:
        _fail("TARGET_URL_REDIRECT", "重定向 evidence 缺少 Location", entry_id=preflight.entry_id)
    if expected_error != "TARGET_URL_REDIRECT" and preflight.redirect_location is not None:
        _fail("UNAPPROVED_SPECIFIED_URL", "非重定向 evidence 不得包含 Location", entry_id=preflight.entry_id)
    return preflight


def main() -> int:
    parser = argparse.ArgumentParser(description="Specified Link Parser / Registry (read-only)")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        entries = parse_specified_link_file(args.input)
        registry = build_specified_link_registry(entries)
    except (OSError, SpecifiedLinkContractError) as exc:
        print(f"[FAIL] {exc}")
        return 1

    clusters = Counter(entry.cluster for entry in registry.entries)
    print(f"Count: {len(registry.entries)}")
    print(f"Registry Version: {registry.specified_link_version}")
    for cluster in sorted(clusters):
        print(f"{cluster}: {clusters[cluster]}")
    for entry in registry.entries:
        print(f"{entry.id} | {entry.canonical_url} | {entry.anchor} | {entry.cluster}")
    print("FINAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
