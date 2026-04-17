from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def ensure_directories() -> None:
    (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "exports").mkdir(parents=True, exist_ok=True)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_whitespace_inline(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def parse_date_text(text: str | None) -> str | None:
    if not text:
        return None
    text = normalize_whitespace_inline(text)
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if not match:
        return None
    year, month, day = match.groups()
    try:
        return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def extract_json_block(text: str) -> str | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return text
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        return match.group(1)
    return None


def json_loads_safe(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        block = extract_json_block(text)
        if not block:
            return default
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            return default


def split_sentences(text: str) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*", normalized)
    return [item.strip() for item in parts if item.strip()]


def shorten(text: str, max_chars: int = 220) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def save_export_file(filename: str, content: str) -> Path:
    ensure_directories()
    path = PROJECT_ROOT / "exports" / filename
    path.write_text(content, encoding="utf-8")
    return path


def env_or_default(name: str, default: str) -> str:
    load_env()
    return os.getenv(name, default)

