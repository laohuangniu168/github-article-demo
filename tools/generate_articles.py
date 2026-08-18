from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "input" / "articles.txt"
OUTPUT_DIR = PROJECT_ROOT / "articles"

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ArticleSpec:
    slug: str
    title: str


def load_articles(path: Path) -> list[ArticleSpec]:
    """
    读取文章定义。

    输入格式：
    slug|title
    """

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
            raise ValueError(
                f"发现重复 slug：{slug}"
            )

        if title in seen_titles:
            raise ValueError(
                f"发现重复标题：{title}"
            )

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


def build_article(article: ArticleSpec) -> str:
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


def generate_articles(
    articles: list[ArticleSpec],
) -> tuple[list[Path], list[Path]]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    skipped: list[Path] = []

    for article in articles:
        output_file = OUTPUT_DIR / f"{article.slug}.md"

        if output_file.exists():
            skipped.append(output_file)
            continue

        content = build_article(article)

        output_file.write_text(
            content,
            encoding="utf-8",
            newline="\n",
        )

        created.append(output_file)

    return created, skipped


def main() -> int:
    print("=" * 60)
    print("GitHub Article Generator v1.1")
    print("=" * 60)

    print(f"输入文件：{INPUT_FILE}")
    print(f"输出目录：{OUTPUT_DIR}")
    print()

    try:
        articles = load_articles(INPUT_FILE)
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

    created, skipped = generate_articles(articles)

    print()
    print("生成结果")
    print("-" * 60)

    for path in created:
        print(
            f"[CREATED] "
            f"{path.relative_to(PROJECT_ROOT)}"
        )

    for path in skipped:
        print(
            f"[SKIPPED] "
            f"{path.relative_to(PROJECT_ROOT)}"
        )

    print("-" * 60)
    print(f"新生成：{len(created)}")
    print(f"已存在跳过：{len(skipped)}")

    print()
    print("安全边界：")
    print("- 未执行 git add")
    print("- 未执行 git commit")
    print("- 未执行 git push")
    print("- 未覆盖已有文章")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())