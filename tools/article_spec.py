from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

CLUSTERS = frozenset(
    {
        "baidu-crawl",
        "baidu-indexing",
        "baidu-seo",
        "technical-seo",
        "keyword-research",
        "content-seo",
        "site-architecture",
        "internal-linking",
        "github-pages",
        "markdown-static-site",
        "unclassified",
    }
)

CLUSTER_SOURCES = frozenset(
    {
        "explicit",
        "inferred",
        "unclassified",
    }
)

INFERENCE_RULES_VERSION = "1"


@dataclass(frozen=True)
class InferenceRule:
    cluster: str
    terms: tuple[str, ...]


SLUG_INFERENCE_RULES = (
    InferenceRule("baidu-crawl", ("baidu-crawl-", "baidu-crawler-", "baidu-deep-page-crawling")),
    InferenceRule("baidu-indexing", ("baidu-indexing-", "baidu-website-indexing", "baidu-new-site-indexing")),
    InferenceRule("baidu-seo", ("baidu-seo-", "baidu-long-tail-keywords", "baidu-search-resource-", "baidu-dead-link-")),
    InferenceRule("technical-seo", ("technical-seo-", "seo-canonical-", "seo-robots-txt-", "seo-website-crawlability", "seo-indexing-troubleshooting")),
    InferenceRule("keyword-research", ("seo-keyword-", "seo-long-tail-", "seo-core-keyword-", "seo-commercial-keyword-", "seo-informational-keywords", "seo-topic-cluster-keywords")),
    InferenceRule("content-seo", ("seo-content-", "seo-title-description-", "seo-page-title-", "seo-meta-description-", "seo-heading-", "seo-image-")),
    InferenceRule("internal-linking", ("seo-internal-link-", "seo-related-content-links", "seo-orphan-page-", "seo-broken-internal-links", "seo-contextual-internal-links")),
    InferenceRule("site-architecture", ("website-url-structure-", "website-sitemap-", "seo-navigation-", "seo-breadcrumb-", "seo-category-", "seo-tag-page-", "seo-pagination-", "seo-click-depth-", "seo-footer-link-", "seo-site-architecture-", "seo-directory-", "seo-url-hierarchy-", "seo-hub-spoke-", "seo-silo-", "seo-taxonomy-", "seo-faceted-", "seo-search-result-", "seo-filter-page-", "seo-archive-page-", "seo-author-page-", "seo-date-archive-", "seo-sitewide-links-")),
    InferenceRule("github-pages", ("github-pages-",)),
    InferenceRule("markdown-static-site", ("markdown-", "static-site-")),
)

TITLE_INFERENCE_RULES = (
    InferenceRule("baidu-crawl", ("百度蜘蛛", "蜘蛛抓取")),
    InferenceRule("baidu-indexing", ("百度收录",)),
    InferenceRule("technical-seo", ("技术seo",)),
    InferenceRule("github-pages", ("github pages",)),
    InferenceRule("markdown-static-site", ("markdown", "静态网站")),
)


@dataclass(frozen=True)
class ArticleSpec:
    slug: str
    title: str
    cluster: str
    cluster_source: str


class ArticleSpecError(ValueError):
    def __init__(self, code: str, line_number: int, message: str) -> None:
        self.code = code
        self.line_number = line_number
        self.message = message
        super().__init__(f"{code} line={line_number}: {message}")


def _matched_clusters(
    value: str,
    rules: Iterable[InferenceRule],
    *,
    prefix_only: bool,
) -> set[str]:
    normalized = value.casefold()
    return {
        rule.cluster
        for rule in rules
        if any(
            normalized.startswith(term.casefold())
            if prefix_only
            else term.casefold() in normalized
            for term in rule.terms
        )
    }


def infer_cluster(
    slug: str,
    title: str,
    *,
    slug_rules: Iterable[InferenceRule] = SLUG_INFERENCE_RULES,
    title_rules: Iterable[InferenceRule] = TITLE_INFERENCE_RULES,
    line_number: int = 0,
) -> tuple[str, str]:
    for value, rules, level in (
        (slug, slug_rules, "slug"),
        (title, title_rules, "title"),
    ):
        matches = _matched_clusters(
            value,
            rules,
            prefix_only=level == "slug",
        )
        if len(matches) > 1:
            raise ArticleSpecError(
                "AMBIGUOUS_CLUSTER_INFERENCE",
                line_number,
                f"{level} 同时命中多个 cluster：{', '.join(sorted(matches))}",
            )
        if matches:
            return next(iter(matches)), "inferred"

    return "unclassified", "unclassified"


def parse_article_specs(path: Path) -> list[ArticleSpec]:
    if not path.exists():
        raise ArticleSpecError("INVALID_INPUT_FORMAT", 0, f"输入文件不存在：{path}")

    specs: list[ArticleSpec] = []
    seen_slugs: set[str] = set()
    seen_titles: set[str] = set()

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue

        fields = line.split("|")
        if len(fields) not in {2, 3}:
            raise ArticleSpecError(
                "INVALID_INPUT_FORMAT",
                line_number,
                "每个非空行必须恰好包含 2 或 3 个字段",
            )

        slug = fields[0].strip().lower()
        title = fields[1].strip()
        explicit_cluster = fields[2].strip() if len(fields) == 3 else ""

        if not slug or not title:
            raise ArticleSpecError(
                "INVALID_INPUT_FORMAT",
                line_number,
                "slug/title 不能为空",
            )
        if not SLUG_PATTERN.fullmatch(slug):
            raise ArticleSpecError(
                "INVALID_INPUT_FORMAT",
                line_number,
                f"slug 非法：{slug}",
            )
        if explicit_cluster and explicit_cluster not in CLUSTERS:
            raise ArticleSpecError(
                "INVALID_CLUSTER",
                line_number,
                f"不受支持的 cluster：{explicit_cluster}",
            )
        if slug in seen_slugs:
            raise ArticleSpecError(
                "INVALID_INPUT_FORMAT",
                line_number,
                f"duplicate slug：{slug}",
            )
        if title in seen_titles:
            raise ArticleSpecError(
                "INVALID_INPUT_FORMAT",
                line_number,
                f"duplicate title：{title}",
            )

        if explicit_cluster:
            cluster = explicit_cluster
            cluster_source = "explicit"
        else:
            cluster, cluster_source = infer_cluster(
                slug,
                title,
                line_number=line_number,
            )

        seen_slugs.add(slug)
        seen_titles.add(title)
        specs.append(ArticleSpec(slug, title, cluster, cluster_source))

    return specs
