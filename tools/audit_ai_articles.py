from pathlib import Path
import re
import argparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_FILE = PROJECT_ROOT / "input" / "articles-gate5.txt"
ARTICLES_DIR = PROJECT_ROOT / "articles"


def load_specs(input_file):
    specs = []

    for line in input_file.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = line.strip()

        if not line:
            continue

        slug, title = line.split("|", 1)

        specs.append(
            (
                slug.strip(),
                title.strip(),
            )
        )

    return specs


def extract_front_matter(text):
    title_match = re.search(
        r'^title:\s*"(.*)"$',
        text,
        re.MULTILINE,
    )

    description_match = re.search(
        r'^description:\s*"(.*)"$',
        text,
        re.MULTILINE,
    )

    title = (
        title_match.group(1)
        if title_match
        else ""
    )

    description = (
        description_match.group(1)
        if description_match
        else ""
    )

    return title, description


def main():
    parser = argparse.ArgumentParser(
        description="AI Article Quality Audit"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_FILE,
        help="指定需要审计的文章输入文件",
    )
    args = parser.parse_args()

    input_file = args.input
    if not input_file.is_absolute():
        input_file = PROJECT_ROOT / input_file

    specs = load_specs(input_file)

    print("=" * 90)
    print("Gate 5 AI Article Quality Audit")
    print("=" * 90)

    passed = 0
    failed = 0

    for index, (slug, expected_title) in enumerate(
        specs,
        start=1,
    ):
        path = ARTICLES_DIR / f"{slug}.md"

        problems = []

        if not path.exists():
            print(
                f"[{index}/10] FAIL "
                f"{slug}: 文件不存在"
            )
            failed += 1
            continue

        text = path.read_text(
            encoding="utf-8-sig"
        )

        title, description = extract_front_matter(
            text
        )

        h1_count = sum(
            1
            for line in text.splitlines()
            if line.startswith("# ")
        )

        h2_count = sum(
            1
            for line in text.splitlines()
            if line.startswith("## ")
        )

        h3_count = sum(
            1
            for line in text.splitlines()
            if line.startswith("### ")
        )

        body_chars = len(text)

        if title != expected_title:
            problems.append("TITLE_MISMATCH")

        if len(description) < 40:
            problems.append("DESCRIPTION_TOO_SHORT")

        if len(description) > 160:
            problems.append("DESCRIPTION_TOO_LONG")

        if h1_count != 1:
            problems.append(
                f"H1_COUNT={h1_count}"
            )

        if h2_count < 4:
            problems.append(
                f"H2_TOO_FEW={h2_count}"
            )

        if body_chars < 2500:
            problems.append(
                f"CONTENT_TOO_SHORT={body_chars}"
            )

        status = (
            "PASS"
            if not problems
            else "FAIL"
        )

        print(
            f"[{index}/10] {status} | "
            f"{slug} | "
            f"chars={body_chars} | "
            f"desc={len(description)} | "
            f"H1={h1_count} | "
            f"H2={h2_count} | "
            f"H3={h3_count}"
        )

        if problems:
            print(
                "    "
                + ", ".join(problems)
            )
            failed += 1
        else:
            passed += 1

    print()
    print("-" * 90)
    print(f"PASS：{passed}")
    print(f"FAIL：{failed}")
    print(f"TOTAL：{len(specs)}")
    print("-" * 90)

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()