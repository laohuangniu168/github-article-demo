from __future__ import annotations

import argparse
import re
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_FILE = PROJECT_ROOT / "input" / "articles-gate5.txt"
ARTICLES_DIR = PROJECT_ROOT / "articles"

WARN_THRESHOLD = 0.45
FAIL_THRESHOLD = 0.60


def load_slugs(input_file: Path) -> list[str]:
    slugs = []

    for raw_line in input_file.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = raw_line.strip()

        if not line:
            continue

        slug, _ = line.split("|", 1)
        slugs.append(slug.strip())

    return slugs


def normalize_article(text: str) -> str:
    # 去掉 YAML Front Matter
    text = re.sub(
        r"\A---\s*\n.*?\n---\s*\n",
        "",
        text,
        flags=re.DOTALL,
    )

    # 去掉 Markdown 标记和空白，重点比较实际文字内容
    text = re.sub(r"[#*`>\[\]()_-]", "", text)
    text = re.sub(r"\s+", "", text)

    return text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Article Similarity Audit"
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

    slugs = load_slugs(input_file)

    articles: dict[str, str] = {}

    for slug in slugs:
        path = ARTICLES_DIR / f"{slug}.md"

        if not path.exists():
            print(f"[FAIL] 文件不存在：{path.name}")
            return 1

        articles[slug] = normalize_article(
            path.read_text(encoding="utf-8-sig")
        )

    results = []

    for left, right in combinations(slugs, 2):
        ratio = SequenceMatcher(
            None,
            articles[left],
            articles[right],
            autojunk=False,
        ).ratio()

        results.append(
            (ratio, left, right)
        )

    results.sort(reverse=True)

    print("=" * 90)
    print("Gate 5 Article Similarity Audit")
    print("=" * 90)

    print()
    print("相似度最高的 10 组：")
    print("-" * 90)

    for ratio, left, right in results[:10]:
        print(
            f"{ratio:.2%} | "
            f"{left} <-> {right}"
        )

    max_ratio, max_left, max_right = results[0]

    warn_pairs = [
        item
        for item in results
        if item[0] >= WARN_THRESHOLD
    ]

    fail_pairs = [
        item
        for item in results
        if item[0] >= FAIL_THRESHOLD
    ]

    print()
    print("-" * 90)
    print(
        f"最高相似度：{max_ratio:.2%} | "
        f"{max_left} <-> {max_right}"
    )
    print(f">= 45% 的组合：{len(warn_pairs)}")
    print(f">= 60% 的组合：{len(fail_pairs)}")

    if fail_pairs:
        print("FINAL: FAIL")
        return 1

    if warn_pairs:
        print("FINAL: PASS_WITH_WARNING")
        return 0

    print("FINAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())