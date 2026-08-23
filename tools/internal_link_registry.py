from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from article_spec import ArticleSpecError, parse_article_specs


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_SCHEMA_VERSION = "1"
CANONICAL_BASE = "https://laohuangniu168.github.io/github-article-demo/articles/"
SOURCE_BATCHES = (
    "production-batch-001.txt",
    "production-batch-002.txt",
    "production-batch-003.txt",
    "production-batch-004.txt",
)
EXPECTED_BATCH_COUNTS = (10, 20, 50, 100)


@dataclass(frozen=True)
class RegistryEntry:
    slug: str
    title: str
    cluster: str
    cluster_source: str
    source_batch: str
    markdown_path: str
    relative_url: str
    canonical_url: str
    published: bool
    eligible_as_target: bool


@dataclass(frozen=True)
class RegistrySnapshot:
    entries: tuple[RegistryEntry, ...]
    source_batches: tuple[str, ...]
    registry_schema_version: str
    registry_version: str


class RegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _read_front_matter_title(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    match = re.match(r'\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)', text, re.DOTALL)
    if not match:
        raise RegistryError("TITLE_MISMATCH", f"Front Matter 不完整：{path.name}")

    title_match = re.search(r'^title:\s*"(.*)"\s*$', match.group("body"), re.MULTILINE)
    if not title_match:
        raise RegistryError("TITLE_MISMATCH", f"Front Matter title 不存在：{path.name}")
    return title_match.group(1)


def _canonical_payload(
    entries: Sequence[RegistryEntry],
    source_batches: Sequence[str],
    schema_version: str,
    canonical_base: str,
) -> dict[str, object]:
    return {
        "canonical_base": canonical_base,
        "entries": [
            {
                "cluster": entry.cluster,
                "eligible_as_target": entry.eligible_as_target,
                "published": entry.published,
                "slug": entry.slug,
                "source_batch": entry.source_batch,
                "title": entry.title,
            }
            for entry in sorted(entries, key=lambda item: item.slug)
        ],
        "registry_schema_version": schema_version,
        "source_batches": list(source_batches),
    }


def compute_registry_version(
    entries: Sequence[RegistryEntry],
    *,
    source_batches: Sequence[str] = SOURCE_BATCHES,
    schema_version: str = REGISTRY_SCHEMA_VERSION,
    canonical_base: str = CANONICAL_BASE,
) -> str:
    payload = _canonical_payload(entries, source_batches, schema_version, canonical_base)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "ilr1:" + hashlib.sha256(encoded).hexdigest()


def validate_registry(
    snapshot: RegistrySnapshot,
    *,
    expected_schema_version: str = REGISTRY_SCHEMA_VERSION,
    expected_source_batches: Sequence[str] = SOURCE_BATCHES,
) -> None:
    if snapshot.registry_schema_version != expected_schema_version:
        raise RegistryError("REGISTRY_SCHEMA_MISMATCH", "registry schema version 不一致")
    if snapshot.source_batches != tuple(expected_source_batches):
        raise RegistryError("SOURCE_BATCH_MISMATCH", "Registry source batch 列表不一致")
    if len({entry.slug for entry in snapshot.entries}) != len(snapshot.entries):
        raise RegistryError("DUPLICATE_SLUG", "Registry 中存在重复 slug")
    if any(not entry.published or not entry.eligible_as_target for entry in snapshot.entries):
        raise RegistryError("REGISTRY_TARGET_INELIGIBLE", "Registry 中存在不合格 target")

    expected_version = compute_registry_version(
        snapshot.entries,
        source_batches=snapshot.source_batches,
        schema_version=snapshot.registry_schema_version,
    )
    if snapshot.registry_version != expected_version:
        raise RegistryError("REGISTRY_VERSION_MISMATCH", "Registry version 与 payload 不一致")


def build_registry(
    project_root: Path = PROJECT_ROOT,
    *,
    source_batches: Sequence[str] = SOURCE_BATCHES,
    expected_batch_counts: Sequence[int] = EXPECTED_BATCH_COUNTS,
) -> RegistrySnapshot:
    if tuple(source_batches) != SOURCE_BATCHES:
        raise RegistryError("SOURCE_BATCH_MISMATCH", "只允许四个 Frozen Production Batch")
    if len(expected_batch_counts) != len(SOURCE_BATCHES):
        raise RegistryError("SOURCE_BATCH_MISMATCH", "Batch count contract 长度错误")

    entries: list[RegistryEntry] = []
    seen_slugs: set[str] = set()

    for batch_name, expected_count in zip(source_batches, expected_batch_counts):
        batch_path = project_root / "input" / batch_name
        try:
            specs = parse_article_specs(batch_path)
        except ArticleSpecError as exc:
            raise RegistryError(exc.code, str(exc)) from exc
        if len(specs) != expected_count:
            raise RegistryError(
                "SOURCE_BATCH_COUNT_MISMATCH",
                f"{batch_name}: expected={expected_count}, actual={len(specs)}",
            )

        for spec in specs:
            if spec.slug in seen_slugs:
                raise RegistryError("DUPLICATE_SLUG", f"跨 Batch 重复 slug：{spec.slug}")

            markdown_path = Path("articles") / f"{spec.slug}.md"
            article_path = project_root / markdown_path
            if not article_path.exists():
                raise RegistryError("REGISTRY_TARGET_MISSING", f"文章不存在：{markdown_path.as_posix()}")

            front_matter_title = _read_front_matter_title(article_path)
            if front_matter_title != spec.title:
                raise RegistryError(
                    "TITLE_MISMATCH",
                    f"{spec.slug}: input={spec.title!r}, front_matter={front_matter_title!r}",
                )

            seen_slugs.add(spec.slug)
            entries.append(
                RegistryEntry(
                    slug=spec.slug,
                    title=spec.title,
                    cluster=spec.cluster,
                    cluster_source=spec.cluster_source,
                    source_batch=batch_name,
                    markdown_path=markdown_path.as_posix(),
                    relative_url=f"./{spec.slug}.html",
                    canonical_url=f"{CANONICAL_BASE}{spec.slug}.html",
                    published=True,
                    eligible_as_target=True,
                )
            )

    sorted_entries = tuple(sorted(entries, key=lambda item: item.slug))
    snapshot = RegistrySnapshot(
        entries=sorted_entries,
        source_batches=tuple(source_batches),
        registry_schema_version=REGISTRY_SCHEMA_VERSION,
        registry_version=compute_registry_version(sorted_entries, source_batches=source_batches),
    )
    validate_registry(snapshot)
    return snapshot


def compute_article_hashes(
    snapshot: RegistrySnapshot,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, str]:
    return {
        entry.slug: hashlib.sha256((project_root / entry.markdown_path).read_bytes()).hexdigest()
        for entry in snapshot.entries
    }


def verify_article_hashes(
    baseline: Mapping[str, str],
    snapshot: RegistrySnapshot,
    project_root: Path = PROJECT_ROOT,
) -> None:
    current = compute_article_hashes(snapshot, project_root)
    if dict(baseline) != current:
        changed = sorted(set(baseline) | set(current), key=str.casefold)
        changed = [slug for slug in changed if baseline.get(slug) != current.get(slug)]
        raise RegistryError(
            "EXISTING_PRODUCTION_MUTATION_ATTEMPT",
            "Frozen production SHA 不一致：" + ", ".join(changed),
        )


def snapshot_as_dict(snapshot: RegistrySnapshot) -> dict[str, object]:
    return {
        "entries": [asdict(entry) for entry in snapshot.entries],
        "registry_schema_version": snapshot.registry_schema_version,
        "registry_version": snapshot.registry_version,
        "source_batches": list(snapshot.source_batches),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen Internal Link Target Registry")
    parser.add_argument("--json", action="store_true", help="输出只读 Registry JSON")
    args = parser.parse_args()

    try:
        snapshot = build_registry()
    except (OSError, RegistryError) as exc:
        print(f"[FAIL] {exc}")
        return 1

    if args.json:
        print(json.dumps(snapshot_as_dict(snapshot), ensure_ascii=False, sort_keys=True))
        return 0

    distribution = Counter(entry.cluster for entry in snapshot.entries)
    print(f"Registry entries: {len(snapshot.entries)}")
    print(f"Registry version: {snapshot.registry_version}")
    for cluster in sorted(distribution):
        print(f"{cluster}: {distribution[cluster]}")
    print("FINAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
