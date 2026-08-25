from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlsplit


DIGEST_SCHEMA_VERSION = "1"
DIGEST_CONFIG_VERSION = "v1.2-digest-default-1"
ENTRY_ID_PREFIX = "de-"
ENTRY_ID_HEX_LENGTH = 16
TITLE_MAX_CODEPOINTS = 200
ALLOWED_SCHEMES = frozenset({"http", "https"})

_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_URL_MARKDOWN_DANGEROUS = frozenset("()<>\\")
_TITLE_MARKDOWN_DANGEROUS = frozenset("[]\\")


@dataclass(frozen=True)
class DigestRegistryEntry:
    id: str
    url_exact: str
    title: str
    normalized_identity: str
    source_filename: str
    source_line: int


@dataclass(frozen=True)
class DigestRegistry:
    schema_version: str
    config_version: str
    entries: tuple[DigestRegistryEntry, ...]
    digest_registry_version: str


class DigestContractError(ValueError):
    def __init__(
        self,
        code: str,
        line_number: int,
        message: str,
        *,
        url: str | None = None,
        first_line_number: int | None = None,
    ) -> None:
        self.code = code
        self.line_number = line_number
        self.message = message
        self.url = url
        self.first_line_number = first_line_number
        super().__init__(f"{code} line={line_number}: {message}")


def compute_digest_normalized_identity(url_exact: str) -> str:
    return hashlib.sha256(url_exact.encode("utf-8")).hexdigest()


def _entry_id(normalized_identity: str) -> str:
    return ENTRY_ID_PREFIX + normalized_identity[:ENTRY_ID_HEX_LENGTH]


def validate_digest_url(url: str, line_number: int = 0) -> str:
    url_exact = url.strip()
    if not url_exact:
        raise DigestContractError(
            "INVALID_DIGEST_URL", line_number, "URL 不能为空", url=url_exact
        )
    if _CONTROL_PATTERN.search(url_exact) or any(character.isspace() for character in url_exact):
        raise DigestContractError(
            "INVALID_DIGEST_URL", line_number, "URL 不允许控制字符或内部 whitespace", url=url_exact
        )
    dangerous = sorted(set(url_exact) & _URL_MARKDOWN_DANGEROUS)
    if dangerous:
        raise DigestContractError(
            "INVALID_DIGEST_URL",
            line_number,
            f"URL 包含不安全的 Markdown destination 字符：{''.join(dangerous)}",
            url=url_exact,
        )
    try:
        parsed = urlsplit(url_exact)
        hostname = parsed.hostname
    except ValueError as exc:
        raise DigestContractError(
            "INVALID_DIGEST_URL", line_number, f"URL 结构非法：{exc}", url=url_exact
        ) from exc
    if parsed.scheme.casefold() not in ALLOWED_SCHEMES:
        raise DigestContractError(
            "INVALID_DIGEST_URL", line_number, "URL scheme 必须为 http 或 https", url=url_exact
        )
    if not hostname:
        raise DigestContractError(
            "INVALID_DIGEST_URL", line_number, "URL 缺少 hostname", url=url_exact
        )
    return url_exact


def validate_digest_title(title: str, line_number: int = 0) -> str:
    normalized = title.strip()
    if not normalized:
        raise DigestContractError("INVALID_DIGEST_TITLE", line_number, "Title 不能为空")
    if _CONTROL_PATTERN.search(normalized):
        raise DigestContractError("INVALID_DIGEST_TITLE", line_number, "Title 不允许控制字符或换行")
    if len(normalized) > TITLE_MAX_CODEPOINTS:
        raise DigestContractError(
            "INVALID_DIGEST_TITLE",
            line_number,
            f"Title 长度必须为 1-{TITLE_MAX_CODEPOINTS} Unicode code points",
        )
    dangerous = sorted(set(normalized) & _TITLE_MARKDOWN_DANGEROUS)
    if dangerous:
        raise DigestContractError(
            "INVALID_DIGEST_TITLE",
            line_number,
            f"Title 包含不安全的 Markdown link text 字符：{''.join(dangerous)}",
        )
    return normalized


def parse_digest_lines(
    text: str,
    *,
    source_filename: str = "<memory>",
) -> tuple[DigestRegistryEntry, ...]:
    entries: list[DigestRegistryEntry] = []
    first_lines: dict[str, int] = {}
    entry_ids: dict[str, str] = {}

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split("|")
        if len(fields) != 2:
            raise DigestContractError(
                "INVALID_DIGEST_INPUT_FORMAT",
                line_number,
                "每个非空行必须恰好包含两个字段：URL|Title",
            )
        url_exact = validate_digest_url(fields[0], line_number)
        title = validate_digest_title(fields[1], line_number)
        if url_exact in first_lines:
            raise DigestContractError(
                "DUPLICATE_DIGEST_URL",
                line_number,
                f"URL 重复，首次出现于 line={first_lines[url_exact]}",
                url=url_exact,
                first_line_number=first_lines[url_exact],
            )
        identity = compute_digest_normalized_identity(url_exact)
        entry_id = _entry_id(identity)
        previous_identity = entry_ids.get(entry_id)
        if previous_identity is not None and previous_identity != identity:
            raise DigestContractError(
                "DIGEST_IDENTITY_COLLISION",
                line_number,
                f"Entry ID collision：{entry_id}",
                url=url_exact,
            )
        first_lines[url_exact] = line_number
        entry_ids[entry_id] = identity
        entries.append(
            DigestRegistryEntry(
                id=entry_id,
                url_exact=url_exact,
                title=title,
                normalized_identity=identity,
                source_filename=source_filename,
                source_line=line_number,
            )
        )
    return tuple(entries)


def parse_digest_file(path: Path) -> tuple[DigestRegistryEntry, ...]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise DigestContractError(
            "INVALID_DIGEST_INPUT_FORMAT", 0, "输入文件必须为 UTF-8"
        ) from exc
    return parse_digest_lines(text, source_filename=path.name)


def _canonical_payload(
    entries: Sequence[DigestRegistryEntry],
    schema_version: str,
    config_version: str,
) -> dict[str, object]:
    return {
        "config_version": config_version,
        "entries": [
            {
                "id": entry.id,
                "normalized_identity": entry.normalized_identity,
                "title": entry.title,
                "url_exact": entry.url_exact,
            }
            for entry in sorted(entries, key=lambda item: item.normalized_identity)
        ],
        "schema_version": schema_version,
    }


def compute_digest_registry_version(
    entries: Sequence[DigestRegistryEntry],
    *,
    schema_version: str = DIGEST_SCHEMA_VERSION,
    config_version: str = DIGEST_CONFIG_VERSION,
) -> str:
    payload = _canonical_payload(entries, schema_version, config_version)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "dgr1:" + hashlib.sha256(encoded).hexdigest()


def build_digest_registry(
    entries: Iterable[DigestRegistryEntry],
    *,
    schema_version: str = DIGEST_SCHEMA_VERSION,
    config_version: str = DIGEST_CONFIG_VERSION,
) -> DigestRegistry:
    ordered = tuple(sorted(entries, key=lambda item: item.normalized_identity))
    seen_ids: dict[str, str] = {}
    seen_urls: dict[str, int] = {}
    for entry in ordered:
        if entry.url_exact in seen_urls:
            raise DigestContractError(
                "DUPLICATE_DIGEST_URL",
                entry.source_line,
                f"URL 重复，首次出现于 line={seen_urls[entry.url_exact]}",
                url=entry.url_exact,
                first_line_number=seen_urls[entry.url_exact],
            )
        prior = seen_ids.get(entry.id)
        if prior is not None and prior != entry.normalized_identity:
            raise DigestContractError(
                "DIGEST_IDENTITY_COLLISION",
                entry.source_line,
                f"Entry ID collision：{entry.id}",
                url=entry.url_exact,
            )
        seen_urls[entry.url_exact] = entry.source_line
        seen_ids[entry.id] = entry.normalized_identity
    return DigestRegistry(
        schema_version=schema_version,
        config_version=config_version,
        entries=ordered,
        digest_registry_version=compute_digest_registry_version(
            ordered, schema_version=schema_version, config_version=config_version
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Digest Registry / Input Parser (read only)")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        entries = parse_digest_file(args.input)
        registry = build_digest_registry(entries)
    except (OSError, DigestContractError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"Entry Count: {len(registry.entries)}")
    print(f"HTTP Count: {sum(e.url_exact.casefold().startswith('http://') for e in registry.entries)}")
    print(f"HTTPS Count: {sum(e.url_exact.casefold().startswith('https://') for e in registry.entries)}")
    print(f"Registry Version: {registry.digest_registry_version}")
    for entry in registry.entries:
        print(f"{entry.id} | line={entry.source_line} | {entry.url_exact} | {entry.title}")
    print("FINAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
