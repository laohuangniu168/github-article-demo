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


DIRECT_CONTRACT_VERSION = "v1.1.1-direct-d2"
DIRECT_SCHEMA_VERSION = "1"
DIRECT_CONFIG_VERSION = "v1.1.1-direct-default-1"
DIRECT_APPROVAL_SOURCE = "USER_INPUT"

DIRECT_ALLOWED_SCHEMES = frozenset({"http", "https"})
DIRECT_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DIRECT_HOST_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
DIRECT_FORBIDDEN_HOSTS = (
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
DIRECT_MARKDOWN_DESTINATION_BREAKERS = frozenset("()<>")
DIRECT_MARKDOWN_ANCHOR_BREAKERS = frozenset("[]\\")


class DirectSpecifiedLinkContractError(RuntimeError):
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
class DirectSpecifiedLinkSpec:
    id: str
    url: str
    canonical_url: str
    anchor: str
    normalized_anchor: str
    approval_source: str
    source_filename: str
    source_line: int


@dataclass(frozen=True)
class DirectSpecifiedLinkRegistry:
    schema_version: str
    config_version: str
    entries: tuple[DirectSpecifiedLinkSpec, ...]
    direct_registry_version: str


def _fail(
    code: str,
    message: str,
    *,
    line_number: int | None = None,
    entry_id: str | None = None,
) -> None:
    raise DirectSpecifiedLinkContractError(
        code,
        message,
        line_number=line_number,
        entry_id=entry_id,
    )


def _has_control_or_whitespace(value: str) -> bool:
    return any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)


def _is_forbidden_host(hostname: str) -> bool:
    return any(hostname == suffix or hostname.endswith("." + suffix) for suffix in DIRECT_FORBIDDEN_HOSTS)


def canonicalize_direct_url(url: str) -> str:
    value = url.strip()
    if not value:
        _fail("INVALID_DIRECT_URL", "DIRECT URL 不能为空")
    if "\\" in value:
        _fail("INVALID_DIRECT_URL", "DIRECT URL 不允许反斜杠")
    if _has_control_or_whitespace(value):
        _fail("INVALID_DIRECT_URL", "DIRECT URL 不允许空白或控制字符")
    if any(character in value for character in DIRECT_MARKDOWN_DESTINATION_BREAKERS):
        _fail("INVALID_DIRECT_URL", "DIRECT URL 含破坏 Markdown destination 的字符")

    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        _fail("INVALID_DIRECT_URL", f"DIRECT URL 解析失败：{exc}")

    scheme = parsed.scheme.lower()
    if scheme not in DIRECT_ALLOWED_SCHEMES:
        _fail("DIRECT_UNSAFE_SCHEME", "DIRECT URL 仅允许 HTTP 或 HTTPS")
    if parsed.username is not None or parsed.password is not None:
        _fail("INVALID_DIRECT_URL", "DIRECT URL 不允许 userinfo")

    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        _fail("INVALID_DIRECT_URL", f"DIRECT URL host/port 非法：{exc}")
    if not hostname:
        _fail("INVALID_DIRECT_URL", "DIRECT URL hostname 不能为空")
    if not hostname.isascii():
        _fail("INVALID_DIRECT_URL", "DIRECT URL hostname 仅允许 ASCII DNS 名称")

    hostname = hostname.lower()
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        _fail("INVALID_DIRECT_URL", "DIRECT URL 不允许 IP literal")

    if hostname.endswith(".") or ".." in hostname or len(hostname) > 253:
        _fail("INVALID_DIRECT_URL", "DIRECT URL hostname 非法")
    labels = hostname.split(".")
    if any(not DIRECT_HOST_LABEL_PATTERN.fullmatch(label) for label in labels):
        _fail("INVALID_DIRECT_URL", "DIRECT URL hostname 含非法 label")
    if _is_forbidden_host(hostname):
        _fail("INVALID_DIRECT_URL", "DIRECT URL 不允许本地、保留或示例 hostname")

    default_port = 80 if scheme == "http" else 443
    if port not in (None, default_port):
        _fail("INVALID_DIRECT_URL", "DIRECT URL 仅允许与协议匹配的默认端口")

    path = parsed.path or "/"
    if any(segment in {".", ".."} for segment in path.split("/")):
        _fail("INVALID_DIRECT_URL", "DIRECT URL path 不允许 dot segment")
    return urlunsplit((scheme, hostname, path, parsed.query, parsed.fragment))


def normalize_direct_anchor(anchor: str) -> str:
    normalized = unicodedata.normalize("NFC", anchor).casefold()
    return " ".join(normalized.split())


def validate_direct_anchor(anchor: str, *, entry_id: str | None = None) -> tuple[str, str]:
    value = anchor.strip()
    if not value:
        _fail("EMPTY_DIRECT_ANCHOR", "DIRECT anchor 不能为空", entry_id=entry_id)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail("INVALID_DIRECT_ANCHOR", "DIRECT anchor 不允许控制字符", entry_id=entry_id)
    if any(character in value for character in DIRECT_MARKDOWN_ANCHOR_BREAKERS):
        _fail("INVALID_DIRECT_ANCHOR", "DIRECT anchor 含破坏 Markdown link text 的字符", entry_id=entry_id)
    normalized = normalize_direct_anchor(value)
    if not normalized:
        _fail("EMPTY_DIRECT_ANCHOR", "DIRECT anchor 归一化后为空", entry_id=entry_id)
    return value, normalized


def validate_direct_spec(spec: DirectSpecifiedLinkSpec) -> None:
    if not DIRECT_ID_PATTERN.fullmatch(spec.id):
        _fail("INVALID_DIRECT_INPUT_FORMAT", "DIRECT ID 格式非法", entry_id=spec.id or None)
    canonical = canonicalize_direct_url(spec.url)
    if canonical != spec.canonical_url:
        _fail("INVALID_DIRECT_URL", "DIRECT canonical URL 与输入不一致", entry_id=spec.id)
    anchor, normalized_anchor = validate_direct_anchor(spec.anchor, entry_id=spec.id)
    if anchor != spec.anchor or normalized_anchor != spec.normalized_anchor:
        _fail("INVALID_DIRECT_ANCHOR", "DIRECT anchor identity 不一致", entry_id=spec.id)
    if spec.approval_source != DIRECT_APPROVAL_SOURCE:
        _fail("INVALID_DIRECT_INPUT_FORMAT", "DIRECT target 必须来自 USER_INPUT", entry_id=spec.id)


def parse_direct_link_lines(
    lines: Iterable[str],
    *,
    source_filename: str = "<memory>",
) -> tuple[DirectSpecifiedLinkSpec, ...]:
    entries: list[DirectSpecifiedLinkSpec] = []
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue
        fields = line.split("|")
        if len(fields) != 3:
            _fail(
                "INVALID_DIRECT_INPUT_FORMAT",
                "每个非空行必须恰好包含 id|url|anchor 三个字段",
                line_number=line_number,
            )
        entry_id, raw_url, raw_anchor = (field.strip() for field in fields)
        if not entry_id or not raw_url:
            _fail("INVALID_DIRECT_INPUT_FORMAT", "DIRECT 字段不能为空", line_number=line_number)
        if not DIRECT_ID_PATTERN.fullmatch(entry_id):
            _fail(
                "INVALID_DIRECT_INPUT_FORMAT",
                "DIRECT ID 格式非法",
                line_number=line_number,
                entry_id=entry_id,
            )
        if entry_id in seen_ids:
            _fail(
                "DUPLICATE_DIRECT_LINK_ID",
                "DIRECT ID 重复",
                line_number=line_number,
                entry_id=entry_id,
            )

        if not raw_anchor:
            _fail("EMPTY_DIRECT_ANCHOR", "DIRECT anchor 不能为空", line_number=line_number, entry_id=entry_id)
        canonical_url = canonicalize_direct_url(raw_url)
        anchor, normalized_anchor = validate_direct_anchor(raw_anchor, entry_id=entry_id)
        pair = (canonical_url, normalized_anchor)
        if pair in seen_pairs:
            _fail(
                "DUPLICATE_DIRECT_URL_ANCHOR",
                "DIRECT canonical URL + normalized anchor 重复",
                line_number=line_number,
                entry_id=entry_id,
            )

        entry = DirectSpecifiedLinkSpec(
            id=entry_id,
            url=raw_url,
            canonical_url=canonical_url,
            anchor=anchor,
            normalized_anchor=normalized_anchor,
            approval_source=DIRECT_APPROVAL_SOURCE,
            source_filename=source_filename,
            source_line=line_number,
        )
        validate_direct_spec(entry)
        entries.append(entry)
        seen_ids.add(entry_id)
        seen_pairs.add(pair)
    return tuple(entries)


def parse_direct_link_file(path: Path) -> tuple[DirectSpecifiedLinkSpec, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return parse_direct_link_lines(handle, source_filename=path.name)


def _canonical_payload(
    entries: Sequence[DirectSpecifiedLinkSpec],
    *,
    schema_version: str,
    config_version: str,
) -> dict[str, object]:
    return {
        "config_version": config_version,
        "entries": [
            {
                "anchor": entry.anchor,
                "approval_source": entry.approval_source,
                "canonical_url": entry.canonical_url,
                "id": entry.id,
                "normalized_anchor": entry.normalized_anchor,
            }
            for entry in sorted(entries, key=lambda item: item.id)
        ],
        "schema_version": schema_version,
    }


def compute_direct_registry_version(
    entries: Sequence[DirectSpecifiedLinkSpec],
    *,
    schema_version: str = DIRECT_SCHEMA_VERSION,
    config_version: str = DIRECT_CONFIG_VERSION,
) -> str:
    payload = _canonical_payload(entries, schema_version=schema_version, config_version=config_version)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "dlr1:" + hashlib.sha256(encoded).hexdigest()


def build_direct_registry(
    entries: Sequence[DirectSpecifiedLinkSpec],
    *,
    schema_version: str = DIRECT_SCHEMA_VERSION,
    config_version: str = DIRECT_CONFIG_VERSION,
) -> DirectSpecifiedLinkRegistry:
    sorted_entries = tuple(sorted(entries, key=lambda item: item.id))
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for entry in sorted_entries:
        validate_direct_spec(entry)
        if entry.id in seen_ids:
            _fail("DUPLICATE_DIRECT_LINK_ID", "DIRECT ID 重复", entry_id=entry.id)
        pair = (entry.canonical_url, entry.normalized_anchor)
        if pair in seen_pairs:
            _fail("DUPLICATE_DIRECT_URL_ANCHOR", "DIRECT URL + anchor 重复", entry_id=entry.id)
        seen_ids.add(entry.id)
        seen_pairs.add(pair)
    version = compute_direct_registry_version(
        sorted_entries,
        schema_version=schema_version,
        config_version=config_version,
    )
    return DirectSpecifiedLinkRegistry(schema_version, config_version, sorted_entries, version)


def validate_direct_registry(
    registry: DirectSpecifiedLinkRegistry,
    *,
    expected_version: str | None = None,
) -> DirectSpecifiedLinkRegistry:
    rebuilt = build_direct_registry(
        registry.entries,
        schema_version=registry.schema_version,
        config_version=registry.config_version,
    )
    required = expected_version or registry.direct_registry_version
    if rebuilt.direct_registry_version != registry.direct_registry_version or required != registry.direct_registry_version:
        _fail("DIRECT_REGISTRY_VERSION_MISMATCH", "DIRECT Registry version 不一致")
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description="DIRECT Specified Link Parser / Registry (read-only)")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        entries = parse_direct_link_file(args.input)
        registry = build_direct_registry(entries)
    except (OSError, DirectSpecifiedLinkContractError) as exc:
        print(f"[FAIL] {exc}")
        return 1

    schemes = Counter(urlsplit(entry.canonical_url).scheme for entry in registry.entries)
    print(f"Count: {len(registry.entries)}")
    print(f"Registry Version: {registry.direct_registry_version}")
    for scheme in sorted(schemes):
        print(f"{scheme}: {schemes[scheme]}")
    for entry in registry.entries:
        print(f"{entry.id} | {entry.canonical_url} | {entry.anchor} | {entry.approval_source}")
    print("FINAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
