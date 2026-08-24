from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from article_spec import ArticleSpec, ArticleSpecError, parse_article_specs


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_DIR = PROJECT_ROOT / "sandbox_evidence"


@dataclass(frozen=True)
class GenerationMapping:
    slug: str
    canonical_title: str
    cluster: str
    generation_title: str


@dataclass(frozen=True)
class GenerationProjection:
    batch_id: str
    canonical_input_sha256: str
    generation_input_sha256: str
    generation_bytes: bytes
    mappings: tuple[GenerationMapping, ...]


class GenerationAdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _map_parser_error(error: ArticleSpecError) -> GenerationAdapterError:
    if "duplicate slug" in error.message:
        code = "DUPLICATE_SLUG"
    elif "duplicate title" in error.message:
        code = "DUPLICATE_TITLE"
    else:
        code = error.code
    return GenerationAdapterError(code, error.message)


def _generation_bytes(specs: tuple[ArticleSpec, ...]) -> bytes:
    text = "".join(f"{spec.slug}|{spec.title}\n" for spec in specs)
    return text.encode("utf-8")


def validate_generation_input(
    generation_bytes: bytes,
    specs: tuple[ArticleSpec, ...],
) -> None:
    try:
        lines = generation_bytes.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise GenerationAdapterError("INVALID_INPUT_FORMAT", "Generation input 不是 UTF-8") from exc

    if len(lines) != len(specs):
        raise GenerationAdapterError(
            "GENERATION_INPUT_COUNT_MISMATCH",
            f"canonical={len(specs)}, generation={len(lines)}",
        )

    for index, (line, spec) in enumerate(zip(lines, specs), start=1):
        slug, marker, title = line.partition("|")
        if not marker or "|" in title:
            raise GenerationAdapterError(
                "INVALID_INPUT_FORMAT",
                f"generation line={index} 必须恰好包含两个字段",
            )
        if slug != spec.slug:
            raise GenerationAdapterError(
                "GENERATION_INPUT_SLUG_MISMATCH",
                f"line={index}, canonical={spec.slug!r}, generation={slug!r}",
            )
        if title != spec.title:
            raise GenerationAdapterError(
                "GENERATION_INPUT_TITLE_MISMATCH",
                f"line={index}, canonical={spec.title!r}, generation={title!r}",
            )


def project_generation_input(canonical_input: Path, batch_id: str) -> GenerationProjection:
    try:
        parsed = parse_article_specs(canonical_input)
    except ArticleSpecError as exc:
        raise _map_parser_error(exc) from exc

    specs = tuple(parsed)
    generation_bytes = _generation_bytes(specs)
    validate_generation_input(generation_bytes, specs)
    mappings = tuple(
        GenerationMapping(spec.slug, spec.title, spec.cluster, spec.title)
        for spec in specs
    )
    return GenerationProjection(
        batch_id=batch_id,
        canonical_input_sha256=hashlib.sha256(canonical_input.read_bytes()).hexdigest(),
        generation_input_sha256=hashlib.sha256(generation_bytes).hexdigest(),
        generation_bytes=generation_bytes,
        mappings=mappings,
    )


def write_projection(
    projection: GenerationProjection,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
) -> tuple[Path, Path]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{projection.batch_id}-{projection.canonical_input_sha256}-generation-input"
    generation_path = evidence_dir / f"{stem}.txt"
    mapping_path = evidence_dir / f"{stem}.mapping.json"
    generation_path.write_bytes(projection.generation_bytes)
    mapping_payload = {
        "batch_id": projection.batch_id,
        "canonical_article_count": len(projection.mappings),
        "canonical_input_sha256": projection.canonical_input_sha256,
        "generation_article_count": len(projection.mappings),
        "generation_input_sha256": projection.generation_input_sha256,
        "mappings": [asdict(item) for item in projection.mappings],
        "schema_version": "1",
    }
    mapping_path.write_text(
        json.dumps(mapping_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return generation_path, mapping_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal Link canonical-to-generation input adapter")
    parser.add_argument("--input", type=Path, required=True, help="Canonical slug|title[|cluster] input")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    canonical_input = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    evidence_dir = args.evidence_dir if args.evidence_dir.is_absolute() else PROJECT_ROOT / args.evidence_dir
    try:
        projection = project_generation_input(canonical_input, args.batch_id)
        print(f"Canonical articles: {len(projection.mappings)}")
        print(f"Generation articles: {len(projection.mappings)}")
        print(f"Canonical input SHA-256: {projection.canonical_input_sha256}")
        print(f"Generation input SHA-256: {projection.generation_input_sha256}")
        print("Slug mismatch: 0")
        print("Title mismatch: 0")
        print("CLUSTER_PROVENANCE=CANONICAL_INPUT")
        if args.dry_run:
            print("DRY RUN: no files written")
        else:
            generation_path, mapping_path = write_projection(projection, evidence_dir)
            print(f"Generation input: {generation_path}")
            print(f"Mapping evidence: {mapping_path}")
        print("FINAL: PASS")
        return 0
    except (OSError, GenerationAdapterError) as exc:
        print(f"[FAIL] {exc}")
        print("FINAL: FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
