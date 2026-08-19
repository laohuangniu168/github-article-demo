from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "input" / "articles.txt"


@dataclass(frozen=True)
class ArticleSpec:
    slug: str
    title: str


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Git 命令失败：git {' '.join(args)}\n"
            f"{result.stderr.strip()}"
        )

    return result.stdout.strip()


def resolve_input_file(path: Path) -> Path:
    if path.is_absolute():
        return path

    return PROJECT_ROOT / path


def load_articles(path: Path) -> list[ArticleSpec]:
    if not path.exists():
        raise FileNotFoundError(
            f"输入文件不存在：{path}"
        )

    articles: list[ArticleSpec] = []

    for line_number, raw_line in enumerate(
        path.read_text(
            encoding="utf-8-sig"
        ).splitlines(),
        start=1,
    ):
        line = raw_line.strip()

        if not line:
            continue

        if "|" not in line:
            raise ValueError(
                f"第 {line_number} 行格式错误："
                "必须使用 slug|title"
            )

        slug, title = line.split("|", 1)

        slug = slug.strip()
        title = title.strip()

        if not slug or not title:
            raise ValueError(
                f"第 {line_number} 行 slug/title 不能为空"
            )

        articles.append(
            ArticleSpec(
                slug=slug,
                title=title,
            )
        )

    return articles


def assert_clean_worktree() -> None:
    status = run_git(
        "status",
        "--porcelain",
        "--untracked-files=all",
    )

    if status:
        raise RuntimeError(
            "工作区不是 clean 状态，拒绝进入发布编排。\n"
            + status
        )


def get_git_state() -> tuple[str, str]:
    head = run_git(
        "rev-parse",
        "HEAD",
    )

    origin_main = run_git(
        "rev-parse",
        "origin/main",
    )

    return head, origin_main


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Controlled GitHub Article Publisher"
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="文章输入文件",
    )

    parser.add_argument(
        "--ai",
        action="store_true",
        help="声明后续正式流程使用 AI 内容生成",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="Gate 6.2 仅允许 dry-run",
    )

    args = parser.parse_args()

    input_file = resolve_input_file(
        args.input
    )

    print("=" * 72)
    print("Controlled GitHub Article Publisher v0.1")
    print("=" * 72)

    print("执行模式：DRY RUN ONLY")
    print(
        "内容模式："
        + ("AI" if args.ai else "LOCAL TEMPLATE")
    )
    print(f"输入文件：{input_file}")
    print()

    try:
        assert_clean_worktree()

        head, origin_main = get_git_state()

        articles = load_articles(
            input_file
        )

    except Exception as exc:
        print(f"[BLOCKED] {exc}")
        return 1

    print("Git Preflight")
    print("-" * 72)
    print(f"HEAD：{head}")
    print(f"origin/main：{origin_main}")
    print("Working Tree：CLEAN")

    if head != origin_main:
        print()
        print(
            "[BLOCKED] HEAD 与 origin/main 不一致。"
        )
        return 1

    print()
    print("Article Plan")
    print("-" * 72)

    for index, article in enumerate(
        articles,
        start=1,
    ):
        print(
            f"[{index}/{len(articles)}] "
            f"{article.slug}.md"
            f" -> {article.title}"
        )

    print()
    print("Safety Boundary")
    print("-" * 72)
    print("- 未调用 OpenAI API")
    print("- 未生成文章")
    print("- 未修改任何文件")
    print("- 未执行 git add")
    print("- 未执行 git commit")
    print("- 未执行 git push")

    print()
    print("FINAL: DRY_RUN_PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())