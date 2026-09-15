"""Production Baseline v2: fixed release membership, exact Git content bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Iterable, Mapping

PRODUCTION_BASELINE_SCHEMA_VERSION = 2
PRODUCTION_BASELINE_ALGORITHM_VERSION = "git-content-sha256-manifest-v1"
PRODUCTION_BASELINE_V2_STATUS = "ACTIVE"
LEGACY_PRODUCTION_AGGREGATE_SHA = "3fb3db1c70213e92ed1134f06b84f1408ffd0be66789247b79987fde0a621f4e"
RELEASE_COMMIT = "2e3af01a520145648244eb235cf0f30651982818"
PRODUCTION_BATCHES = (
    ("production-batch-001.txt", 10),
    ("production-batch-002.txt", 20),
    ("production-batch-003.txt", 50),
    ("production-batch-004.txt", 100),
    ("internal-link-production-batch-010.txt", 10),
    ("direct-specified-link-production-010.txt", 10),
)
_PATH = re.compile(r"articles/[a-z0-9]+(?:-[a-z0-9]+)*\.md\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class ProductionBaselineError(ValueError):
    """Fail closed when repository content or the baseline contract is invalid."""


def _git(root: Path | str, *args: str) -> bytes:
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1",
               GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True,
            env=env, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProductionBaselineError("GIT_REPOSITORY_CONTENT_UNAVAILABLE") from exc


def _resolve_commit(root: Path | str, revision: str) -> str:
    value = _git(root, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise ProductionBaselineError("INVALID_COMMIT_IDENTITY")
    return value


def _repository_bytes(root: Path | str, commit: str, path: str) -> bytes:
    return _git(root, "show", commit + ":" + path)


def _production_paths(root: Path | str) -> list[str]:
    paths = []
    for name, count in PRODUCTION_BATCHES:
        try:
            text = _repository_bytes(root, RELEASE_COMMIT, "input/" + name).decode("utf-8-sig")
        except UnicodeError as exc:
            raise ProductionBaselineError("INVALID_RELEASE_INPUT_ENCODING") from exc
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) != count:
            raise ProductionBaselineError("PRODUCTION_FILE_SELECTION_COUNT_MISMATCH")
        for line in lines:
            fields = line.split("|")
            path = "articles/" + fields[0].strip() + ".md"
            if len(fields) not in (2, 3) or not _PATH.fullmatch(path):
                raise ProductionBaselineError("INVALID_RELEASE_PRODUCTION_PATH")
            paths.append(path)
    if len(paths) != 200 or len(set(paths)) != 200:
        raise ProductionBaselineError("PRODUCTION_FILE_SELECTION_DUPLICATE_OR_MISSING")
    return sorted(paths, key=lambda path: path.encode("utf-8"))


def build_production_baseline_manifest(
    project_root: Path | str, *, revision: str = "HEAD",
) -> list[dict[str, str]]:
    """Build the fixed 200-file manifest; never read articles from the worktree."""
    commit = RELEASE_COMMIT if revision == RELEASE_COMMIT else _resolve_commit(project_root, revision)
    return [
        {"relative_path": path, "repository_content_sha256": hashlib.sha256(
            _repository_bytes(project_root, commit, path)).hexdigest()}
        for path in _production_paths(project_root)
    ]


def canonical_manifest_bytes(manifest: Iterable[Mapping[str, str]]) -> bytes:
    """Serialize path-sorted records as compact UTF-8 JSON, no BOM or final LF."""
    rows = []
    seen = set()
    for entry in manifest:
        if not isinstance(entry, Mapping) or set(entry) != {"relative_path", "repository_content_sha256"}:
            raise ProductionBaselineError("INVALID_MANIFEST_FIELDS")
        path, digest = entry["relative_path"], entry["repository_content_sha256"]
        if not isinstance(path, str) or not _PATH.fullmatch(path):
            raise ProductionBaselineError("INVALID_MANIFEST_PATH")
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise ProductionBaselineError("INVALID_CONTENT_SHA256")
        if path in seen:
            raise ProductionBaselineError("DUPLICATE_MANIFEST_PATH")
        seen.add(path)
        rows.append(dict(entry))
    if not rows:
        raise ProductionBaselineError("EMPTY_MANIFEST")
    rows.sort(key=lambda row: row["relative_path"].encode("utf-8"))
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_production_aggregate(manifest: Iterable[Mapping[str, str]]) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def verify_production_baseline(
    project_root: Path | str, manifest: Iterable[Mapping[str, str]] | None = None,
) -> dict[str, object]:
    """Verify HEAD against the immutable release; optionally check a supplied manifest."""
    commit = _resolve_commit(project_root, "HEAD")
    current = build_production_baseline_manifest(project_root, revision=commit)
    expected = build_production_baseline_manifest(project_root, revision=RELEASE_COMMIT)
    if current != expected:
        raise ProductionBaselineError("PRODUCTION_CONTENT_DRIFT")
    canonical = canonical_manifest_bytes(current)
    if manifest is not None and canonical_manifest_bytes(manifest) != canonical:
        raise ProductionBaselineError("PRODUCTION_MANIFEST_IDENTITY_MISMATCH")
    aggregate = hashlib.sha256(canonical).hexdigest()
    return {
        "status": "PASS", "production_baseline_v2_status": PRODUCTION_BASELINE_V2_STATUS,
        "schema_version": PRODUCTION_BASELINE_SCHEMA_VERSION,
        "algorithm_version": PRODUCTION_BASELINE_ALGORITHM_VERSION,
        "canonical_source": "GIT_REPOSITORY_CONTENT", "head": commit,
        "release_identity": RELEASE_COMMIT, "manifest_entry_count": len(current),
        "manifest_sha256": aggregate, "aggregate_sha256": aggregate,
        "content_drift": False, "missing": 0, "duplicate": 0, "unknown": 0,
        "legacy_production_aggregate_sha": LEGACY_PRODUCTION_AGGREGATE_SHA,
        "legacy_algorithm": "UNKNOWN", "legacy_sha_reproducible": False,
        "legacy_content_drift_indicator": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    try:
        report = verify_production_baseline(args.project_root)
    except ProductionBaselineError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}))
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
