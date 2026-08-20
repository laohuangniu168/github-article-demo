from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from ai_content_generator import generate_article


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "input" / "articles.txt"
OUTPUT_DIR = PROJECT_ROOT / "articles"

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ArticleSpec:
    slug: str
    title: str


def strip_trailing_whitespace(text: str) -> str:
    """删除每行末尾的空格和 Tab，保留其余字符与换行结构。"""

    return re.sub(
        r"[ \t]+(?=\r?$)",
        "",
        text,
        flags=re.MULTILINE,
    )


def load_articles(path: Path) -> list[ArticleSpec]:
    if not path.exists():
        raise FileNotFoundError(f"输入文件不存在：{path}")

    text = path.read_text(encoding="utf-8-sig")

    articles: list[ArticleSpec] = []
    seen_slugs: set[str] = set()
    seen_titles: set[str] = set()

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        if not line:
            continue

        if "|" not in line:
            raise ValueError(
                f"第 {line_number} 行格式错误，必须使用 slug|title：{line}"
            )

        slug, title = line.split("|", 1)

        slug = slug.strip().lower()
        title = title.strip()

        if not slug:
            raise ValueError(f"第 {line_number} 行 slug 为空")

        if not title:
            raise ValueError(f"第 {line_number} 行 title 为空")

        if not SLUG_PATTERN.fullmatch(slug):
            raise ValueError(
                f"第 {line_number} 行 slug 非法：{slug}。"
                "只允许小写英文字母、数字和单个连字符。"
            )

        if slug in seen_slugs:
            raise ValueError(f"发现重复 slug：{slug}")

        if title in seen_titles:
            raise ValueError(f"发现重复标题：{title}")

        seen_slugs.add(slug)
        seen_titles.add(title)

        articles.append(
            ArticleSpec(
                slug=slug,
                title=title,
            )
        )

    return articles


def make_description(title: str) -> str:
    return (
        f"本文围绕“{title}”进行介绍，"
        "整理相关基础知识、使用方法和注意事项，"
        "方便读者快速了解相关内容。"
    )


def build_template_article(article: ArticleSpec) -> str:
    title = article.title
    description = make_description(title)

    return f"""---
title: "{title}"
description: "{description}"
---

# {title}

本文主要介绍 **{title}** 相关内容。

## 基础介绍

在实际使用过程中，需要根据具体需求选择合适的方法，并保持内容结构清晰。

## 使用方法

可以按照实际业务需求逐步完成配置、检查和验证。

对于网站内容而言，建议保持标题、正文和页面主题一致。

## 内容优化

文章内容应当尽量清晰、完整，并合理使用标题层级组织不同章节。

同时可以通过相关文章之间的内部链接建立内容关联。

## 相关文章

[GitHub Pages SEO 指南](./github-pages-seo-guide.html)

[GitHub Pages 建站入门教程](./github-pages-beginner-guide.html)

## 总结

以上是关于 **{title}** 的基础介绍。

后续可以根据实际需求继续补充更加详细的内容。
"""


def build_ai_article(article: ArticleSpec) -> str:
    generated = generate_article(article.title)

    return f"""---
title: "{generated.title}"
description: "{generated.description}"
---

# {generated.title}

{{% raw %}}

{generated.markdown}

{{% endraw %}}
"""


def generate_articles(
    articles: list[ArticleSpec],
    use_ai: bool,
) -> tuple[list[Path], list[Path], list[tuple[ArticleSpec, str]]]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    skipped: list[Path] = []
    failed: list[tuple[ArticleSpec, str]] = []

    for index, article in enumerate(articles, start=1):
        output_file = OUTPUT_DIR / f"{article.slug}.md"

        if output_file.exists():
            print(
                f"[{index}/{len(articles)}] "
                f"[SKIPPED] {output_file.relative_to(PROJECT_ROOT)}"
            )
            skipped.append(output_file)
            continue

        print(
            f"[{index}/{len(articles)}] "
            f"开始生成：{article.title}"
        )

        try:
            if use_ai:
                content = build_ai_article(article)
            else:
                content = build_template_article(article)

            content = strip_trailing_whitespace(content)

            output_file.write_text(
                content,
                encoding="utf-8",
                newline="\n",
            )

            created.append(output_file)

            print(
                f"[{index}/{len(articles)}] "
                f"[CREATED] {output_file.relative_to(PROJECT_ROOT)}"
            )

        except Exception as exc:
            failed.append((article, str(exc)))

            print(
                f"[{index}/{len(articles)}] "
                f"[FAILED] {article.slug}：{exc}"
            )

    return created, skipped, failed


def resolve_input_file(input_path: Path) -> Path:
    if input_path.is_absolute():
        return input_path

    return PROJECT_ROOT / input_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GitHub Article Generator"
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_FILE,
        help="指定文章输入文件，默认使用 input/articles.txt",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只验证输入并显示发布计划，不生成文章文件",
    )

    parser.add_argument(
        "--ai",
        action="store_true",
        help="使用 OpenAI API 生成差异化文章正文",
    )

    args = parser.parse_args()

    input_file = resolve_input_file(args.input)

    print("=" * 60)
    print("GitHub Article Generator v1.2")
    print("=" * 60)

    print(f"输入文件：{input_file}")
    print(f"输出目录：{OUTPUT_DIR}")

    if args.ai:
        print("内容模式：AI")
    else:
        print("内容模式：LOCAL TEMPLATE")

    if args.dry_run:
        print("执行模式：DRY RUN")
    else:
        print("执行模式：WRITE")

    print()

    try:
        articles = load_articles(input_file)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    if not articles:
        print("[ERROR] 输入文件中没有有效文章。")
        return 1

    print(f"有效文章数量：{len(articles)}")

    print()
    print("发布计划")
    print("-" * 60)

    for article in articles:
        print(
            f"{article.slug}.md"
            f" -> {article.title}"
        )

    if args.dry_run:
        print()
        print("DRY RUN")
        print("-" * 60)
        print("输入验证通过。")
        print(f"计划文章数量：{len(articles)}")

        if args.ai:
            print("AI 模式已请求，但 DRY RUN 不调用 OpenAI API。")

        print("未生成任何文章文件。")
        print("未产生文章生成 API 调用。")
        print("-" * 60)
        return 0

    print()
    print("开始生成")
    print("-" * 60)

    created, skipped, failed = generate_articles(
        articles=articles,
        use_ai=args.ai,
    )

    print()
    print("生成结果")
    print("-" * 60)
    print(f"新生成：{len(created)}")
    print(f"已存在跳过：{len(skipped)}")
    print(f"生成失败：{len(failed)}")

    if failed:
        print()
        print("失败清单")
        print("-" * 60)

        for article, error in failed:
            print(
                f"[FAILED] {article.slug}"
                f" -> {article.title}"
                f" -> {error}"
            )

    print()
    print("安全边界：")
    print("- 未执行 git add")
    print("- 未执行 git commit")
    print("- 未执行 git push")
    print("- 未覆盖已有文章")

    if failed:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
