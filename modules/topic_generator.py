from __future__ import annotations

from modules import db
from modules.llm_client import generate_text
from modules.utils import PROJECT_ROOT, extract_json_block, json_loads_safe, render_prompt_template, shorten, unique_preserve


PROMPT_PATH = PROJECT_ROOT / "prompts" / "topic_prompt.txt"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def generate_topics(main_keyword: str, related_keywords: list[str] | None = None) -> list[str]:
    related_keywords = related_keywords or []
    related_docs = db.search_official_docs(main_keyword, limit=3)
    official_context = "\n".join(
        f"- {row['title']}: {shorten(row['content_text'], 120)}"
        for row in related_docs
    ) or "暂无匹配到足够的官方资料，请保持保守表达。"
    prompt = render_prompt_template(
        _load_prompt(),
        main_keyword=main_keyword,
        related_keywords="、".join(related_keywords) if related_keywords else "无",
        official_context=official_context,
    )
    raw = generate_text(prompt)
    json_block = extract_json_block(raw)
    parsed = json_loads_safe(json_block or raw, default=[])
    if isinstance(parsed, list):
        topics = [str(item).strip() for item in parsed]
    else:
        topics = [line.strip("-• ").strip() for line in raw.splitlines() if line.strip()]
    topics = [topic for topic in unique_preserve(topics) if topic and len(topic) <= 28]
    return topics[:5]
