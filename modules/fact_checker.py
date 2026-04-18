from __future__ import annotations

from typing import Sequence

from modules.llm_client import LLMClientError, generate_text
from modules.utils import PROJECT_ROOT, json_loads_safe, render_prompt_template, shorten, split_sentences, unique_preserve


PROMPT_PATH = PROJECT_ROOT / "prompts" / "fact_check_prompt.txt"
HIGH_RISK_PHRASES = ["包过", "一定能办", "100%成功", "无需材料", "当天办好", "不用审核"]
CLAIM_HINTS = ("天", "工作日", "入口", "网址", "公众号", "小程序", "条件", "材料", "必须", "即可", "直接")


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_official_snippets(official_docs: Sequence[object], max_items: int = 3) -> str:
    parts = []
    for row in list(official_docs)[:max_items]:
        parts.append(
            f"标题：{row['title']}\n链接：{row['url']}\n摘录：{shorten(row['content_text'], 420)}"
        )
    return "\n\n".join(parts)


def _token_overlap_supported(sentence: str, official_docs: Sequence[object]) -> bool:
    sentence_tokens = {token for token in sentence if token.strip()}
    if not sentence_tokens:
        return True
    for row in official_docs:
        official_text = str(row["title"]) + str(row["content_text"][:800])
        overlap = sum(1 for token in sentence_tokens if token in official_text)
        if overlap >= max(4, len(sentence_tokens) // 5):
            return True
    return False


def _rule_based_check(draft_text: str, official_docs: Sequence[object]) -> tuple[list[str], list[str], list[str]]:
    risk_hits = [phrase for phrase in HIGH_RISK_PHRASES if phrase in draft_text]
    suspicious_sentences: list[str] = []
    notes: list[str] = []

    if risk_hits:
        notes.append("命中高风险表述：" + "、".join(risk_hits))

    if not official_docs:
        notes.append("未关联到官方资料，草稿缺少事实支撑。")

    for sentence in split_sentences(draft_text):
        if any(phrase in sentence for phrase in HIGH_RISK_PHRASES):
            suspicious_sentences.append(sentence)
            continue
        if any(hint in sentence for hint in CLAIM_HINTS) and not _token_overlap_supported(sentence, official_docs):
            suspicious_sentences.append(sentence)

    if suspicious_sentences:
        notes.append(f"发现 {len(unique_preserve(suspicious_sentences))} 条可能缺少官方支撑的句子。")

    return risk_hits, unique_preserve(suspicious_sentences), notes


def _llm_assisted_check(draft_text: str, official_docs: Sequence[object]) -> tuple[str | None, list[str], list[str]]:
    if not official_docs:
        return None, [], []
    prompt = render_prompt_template(
        _load_prompt(),
        draft_text=draft_text,
        official_snippets=build_official_snippets(official_docs),
    )
    try:
        raw = generate_text(prompt)
    except LLMClientError:
        return None, [], []
    parsed = json_loads_safe(raw, default={})
    if not isinstance(parsed, dict):
        return None, [], []
    return (
        str(parsed.get("fact_status")) if parsed.get("fact_status") else None,
        [str(item) for item in parsed.get("fact_notes", []) if str(item).strip()],
        [str(item) for item in parsed.get("suspicious_sentences", []) if str(item).strip()],
    )


def check_draft(draft_text: str, official_docs: Sequence[object]) -> dict[str, object]:
    referenced_docs = [str(row["title"]) for row in list(official_docs)[:3]]
    risk_hits, suspicious_sentences, notes = _rule_based_check(draft_text, official_docs)
    llm_status, llm_notes, llm_suspicious = _llm_assisted_check(draft_text, official_docs)

    notes.extend(llm_notes)
    suspicious_sentences.extend(llm_suspicious)
    suspicious_sentences = unique_preserve(suspicious_sentences)
    notes = unique_preserve(notes)

    fact_status = "pass"
    if risk_hits or not referenced_docs or llm_status == "fail":
        fact_status = "fail"
    elif suspicious_sentences or llm_status == "warning":
        fact_status = "warning"

    if llm_status == "pass" and fact_status == "warning" and not suspicious_sentences:
        fact_status = "pass"

    if not notes:
        notes = ["未发现明显高风险表述，仍建议人工复核最新官方口径。"]

    return {
        "fact_status": fact_status,
        "fact_notes": "；".join(notes),
        "suspicious_sentences": suspicious_sentences,
        "referenced_docs": referenced_docs,
        "high_risk_hits": risk_hits,
    }
