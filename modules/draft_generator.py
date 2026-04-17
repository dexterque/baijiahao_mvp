from __future__ import annotations

from typing import Sequence

from modules.llm_client import generate_text
from modules.utils import PROJECT_ROOT, shorten


PROMPT_PATH = PROJECT_ROOT / "prompts" / "article_prompt.txt"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_official_snippets(official_docs: Sequence[object], max_items: int = 5) -> str:
    snippets = []
    for row in list(official_docs)[:max_items]:
        snippets.append(
            "\n".join(
                [
                    f"标题：{row['title']}",
                    f"链接：{row['url']}",
                    f"日期：{row['publish_date'] or '未标注'}",
                    f"正文摘录：{shorten(row['content_text'], 380)}",
                ]
            )
        )
    return "\n\n".join(snippets) if snippets else "暂无官方资料，必须使用保守表达，避免写死细节。"


def generate_draft(
    topic: str,
    main_keyword: str,
    related_keywords: list[str],
    official_docs: Sequence[object],
) -> str:
    prompt = _load_prompt().format(
        topic=topic,
        main_keyword=main_keyword,
        related_keywords="、".join(related_keywords) if related_keywords else "无",
        official_snippets=build_official_snippets(official_docs),
    )
    return generate_text(prompt)

