from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import urlparse

import httpx
import requests
from openai import APIConnectionError, APITimeoutError, OpenAI

from modules.utils import PROJECT_ROOT, clean_text, ensure_directories, env_or_default, load_env, shorten


class ImageGenerationError(RuntimeError):
    pass


def _should_ignore_env_proxy(base_url: str) -> bool:
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _client() -> tuple[OpenAI, str, str]:
    load_env()
    base_url = env_or_default("IMAGE_BASE_URL", env_or_default("MODEL_BASE_URL", "http://127.0.0.1:10531/v1"))
    api_key = env_or_default("IMAGE_API_KEY", env_or_default("MODEL_API_KEY", "dummy"))
    model_name = env_or_default("IMAGE_MODEL_NAME", "gpt-image-1")
    http_client = httpx.Client(timeout=120.0, trust_env=False) if _should_ignore_env_proxy(base_url) else None
    return OpenAI(base_url=base_url, api_key=api_key, timeout=120.0, http_client=http_client), model_name, base_url


def build_cover_prompt(title: str, article_content: str, main_keyword: str = "") -> str:
    cleaned_title = clean_text(title) or "深圳政务办事解读"
    cleaned_keyword = clean_text(main_keyword)
    article_excerpt = shorten(clean_text(article_content), 280)
    focus_line = f"主题关键词：{cleaned_keyword}" if cleaned_keyword else "主题关键词：深圳政务办事"
    return clean_text(
        f"""
        请生成一张适合中文政务服务类内容封面的横版图片。
        画面要求：真实感、清晰、专业、可信，适合“深圳办事指南/政策解读”类文章封面。
        不要在图片中加入任何文字、标题、水印、Logo、二维码、边框或拼贴元素。
        色调以明亮、干净、现代为主，可以加入深圳城市公共服务氛围、窗口办理、材料表单、证件、城市建筑等视觉线索。
        {focus_line}
        文章标题：{cleaned_title}
        文章摘要：{article_excerpt}
        构图要求：16:9 横版封面，主体明确，留出适合后期排版标题的干净区域，但不要直接渲染文字。
        """
    )


def generate_image(
    prompt: str,
    size: str = "1536x1024",
    quality: str = "medium",
    output_format: str = "png",
) -> bytes:
    client, model_name, base_url = _client()
    try:
        response = client.images.generate(
            model=model_name,
            prompt=prompt,
            size=size,
            quality=quality,
            output_format=output_format,
        )
    except (APIConnectionError, APITimeoutError) as exc:
        raise ImageGenerationError(
            f"无法连接图片生成网关：{base_url}。请先启动 openai-oauth，并确认图像接口可访问。"
        ) from exc
    except Exception as exc:
        raise ImageGenerationError(
            f"图片生成失败：{exc}。如果你当前的 openai-oauth 网关不支持 Images API，请切换到支持图片生成的网关或模型。"
        ) from exc

    if not getattr(response, "data", None):
        raise ImageGenerationError("图片生成接口没有返回可用结果。")

    image_result = response.data[0]
    b64_json = getattr(image_result, "b64_json", None)
    if b64_json:
        return base64.b64decode(b64_json)

    image_url = getattr(image_result, "url", None)
    if image_url:
        download = requests.get(image_url, timeout=60)
        download.raise_for_status()
        return download.content

    raise ImageGenerationError("图片生成接口返回了未知格式，未拿到图片数据。")


def build_cover_filename(draft_id: int, output_format: str = "png") -> str:
    return f"draft_{draft_id}_cover.{output_format}"


def save_cover_image(image_bytes: bytes, filename: str) -> Path:
    ensure_directories()
    path = PROJECT_ROOT / "exports" / filename
    path.write_bytes(image_bytes)
    return path


def build_image_data_uri(image_bytes: bytes, mime_type: str = "image/png") -> str:
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
