from __future__ import annotations

from openai import APIConnectionError, APITimeoutError, OpenAI

from modules.utils import env_or_default, load_env


class LLMClientError(RuntimeError):
    pass


def _client() -> tuple[OpenAI, str, str]:
    load_env()
    base_url = env_or_default("MODEL_BASE_URL", "http://127.0.0.1:10531/v1")
    api_key = env_or_default("MODEL_API_KEY", "dummy")
    model_name = env_or_default("MODEL_NAME", "gpt-5.4")
    return OpenAI(base_url=base_url, api_key=api_key, timeout=60.0), model_name, base_url


def generate_text(prompt: str) -> str:
    client, model_name, base_url = _client()
    try:
        response = client.chat.completions.create(
            model=model_name,
            temperature=0.4,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个谨慎、事实优先的中文助手。",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
    except (APIConnectionError, APITimeoutError) as exc:
        raise LLMClientError(
            f"无法连接本地模型网关：{base_url}。请先启动 openai-oauth，并确认 /v1/models 可访问。"
        ) from exc
    except Exception as exc:
        raise LLMClientError(f"模型调用失败：{exc}") from exc

    if not response.choices:
        raise LLMClientError("模型没有返回可用结果。")
    message = response.choices[0].message.content
    if isinstance(message, list):
        text_parts = [part.text for part in message if getattr(part, "type", None) == "text"]
        return "\n".join(text_parts).strip()
    return (message or "").strip()

