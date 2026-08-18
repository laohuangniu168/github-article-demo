from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI


DEFAULT_MODEL = "gpt-5.6"


@dataclass(frozen=True)
class GeneratedArticle:
    title: str
    description: str
    markdown: str


def require_api_key() -> None:
    """确认 OpenAI API Key 已通过环境变量配置。"""

    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "未检测到 OPENAI_API_KEY 环境变量，拒绝调用 AI。"
        )


def build_prompt(title: str) -> str:
    """为单篇文章构建写作要求。"""

    return f"""
你是一名中文 SEO 内容编辑。

请围绕下面的主题撰写一篇真实、有信息价值的中文教程文章：

文章标题：
{title}

写作要求：

1. 文章必须紧密回答标题对应的搜索意图。
2. 不要写空泛的套话，不要机械重复标题。
3. 正文目标约 1500～2500 个中文字。
4. 使用清晰的 Markdown 结构。
5. 不要在正文中再次输出一级标题 #。
6. 使用 4～7 个有实际意义的二级标题 ##。
7. 必要时可以使用三级标题 ###。
8. 可以使用列表、步骤和代码块。
9. 涉及 GitHub Pages、SEO 或技术配置时，不得虚构不存在的功能。
10. 不要声称某项 SEO 操作一定能够提高排名或保证收录。
11. 不要关键词堆砌。
12. 不要输出“作为 AI”“以下是文章”等无关说明。
13. 不要输出 YAML Front Matter。
14. description 必须自然、独立，不要简单复制标题。
15. description 建议控制在约 60～120 个中文字符。
16. 正文结尾应有自然总结，但不要机械使用固定模板。
17. 只返回下面规定的格式，不要增加其他字段。

严格返回：

DESCRIPTION:
这里填写 description

CONTENT:
这里填写 Markdown 正文
""".strip()


def parse_response(title: str, output: str) -> GeneratedArticle:
    """解析模型返回结果，并拒绝不完整内容。"""

    text = output.strip()

    description_marker = "DESCRIPTION:"
    content_marker = "CONTENT:"

    if description_marker not in text:
        raise ValueError("AI 输出缺少 DESCRIPTION 字段")

    if content_marker not in text:
        raise ValueError("AI 输出缺少 CONTENT 字段")

    description_part, content_part = text.split(content_marker, 1)

    description = description_part.split(
        description_marker,
        1,
    )[1].strip()

    markdown = content_part.strip()

    if not description:
        raise ValueError("AI description 为空")

    if not markdown:
        raise ValueError("AI 正文为空")

    if markdown.startswith("# "):
        raise ValueError(
            "AI 正文包含一级标题，拒绝写入，避免重复 H1"
        )

    if len(markdown) < 800:
        raise ValueError(
            f"AI 正文过短：{len(markdown)} 字符"
        )

    h2_count = sum(
        1
        for line in markdown.splitlines()
        if line.startswith("## ")
    )

    if h2_count < 4:
        raise ValueError(
            f"AI 正文 H2 数量不足：{h2_count}"
        )

    return GeneratedArticle(
        title=title,
        description=description,
        markdown=markdown,
    )


def generate_article(
    title: str,
    model: str = DEFAULT_MODEL,
) -> GeneratedArticle:
    """
    调用 OpenAI 生成一篇文章。

    本函数只返回内容：
    - 不写文件
    - 不执行 Git
    - 不执行 Push
    """

    require_api_key()

    client = OpenAI()

    response = client.responses.create(
        model=model,
        input=build_prompt(title),
    )

    output = response.output_text

    if not output:
        raise RuntimeError("OpenAI API 返回了空内容")

    return parse_response(
        title=title,
        output=output,
    )