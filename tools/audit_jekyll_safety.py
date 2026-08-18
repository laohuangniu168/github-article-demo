from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "input" / "articles-gate5.txt"
ARTICLES_DIR = PROJECT_ROOT / "articles"


def load_slugs() -> list[str]:
    slugs: list[str] = []

    for raw_line in INPUT_FILE.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = raw_line.strip()

        if not line:
            continue

        slug, _ = line.split("|", 1)
        slugs.append(slug.strip())

    return slugs


def audit_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    problems: list[str] = []

    raw_count = text.count("{% raw %}")
    endraw_count = text.count("{% endraw %}")

    if raw_count != 1:
        problems.append(f"RAW_COUNT={raw_count}")

    if endraw_count != 1:
        problems.append(f"ENDRAW_COUNT={endraw_count}")

    raw_pos = text.find("{% raw %}")
    endraw_pos = text.find("{% endraw %}")

    if raw_pos == -1 or endraw_pos == -1:
        return problems

    if raw_pos >= endraw_pos:
        problems.append("RAW_BOUNDARY_ORDER_INVALID")
        return problems

    before = text[:raw_pos]
    after = text[endraw_pos + len("{% endraw %}") :]

    if "{%" in before or "{{" in before:
        problems.append("LIQUID_BEFORE_RAW")

    if "{%" in after or "{{" in after:
        problems.append("LIQUID_AFTER_ENDRAW")

    return problems


def main() -> int:
    slugs = load_slugs()

    passed = 0
    failed = 0

    print("=" * 80)
    print("Gate 5 Jekyll Liquid Safety Audit")
    print("=" * 80)

    for index, slug in enumerate(slugs, start=1):
        path = ARTICLES_DIR / f"{slug}.md"

        if not path.exists():
            print(f"[{index}/10] FAIL | {slug} | FILE_NOT_FOUND")
            failed += 1
            continue

        problems = audit_file(path)

        if problems:
            print(
                f"[{index}/10] FAIL | {slug} | "
                + ", ".join(problems)
            )
            failed += 1
        else:
            print(f"[{index}/10] PASS | {slug}")
            passed += 1

    print()
    print("-" * 80)
    print(f"PASS：{passed}")
    print(f"FAIL：{failed}")
    print(f"TOTAL：{len(slugs)}")
    print("-" * 80)

    if failed:
        return 1

    print("FINAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())