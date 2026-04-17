from __future__ import annotations

import csv
import io
from typing import BinaryIO

from modules import db
from modules.utils import clean_text


CSV_FIELD_ALIASES = {
    "title": ["title", "标题"],
    "content": ["content", "正文", "内容"],
    "source_name": ["source_name", "来源", "来源名称"],
    "source_url": ["source_url", "链接", "URL", "url"],
    "publish_time": ["publish_time", "发布时间", "日期"],
}


def import_manual_article(
    title: str,
    content: str,
    source_name: str = "",
    source_url: str = "",
    publish_time: str = "",
) -> int:
    title = clean_text(title)
    content = clean_text(content)
    if not title or not content:
        raise ValueError("标题和正文不能为空。")
    return db.insert_article(title, content, clean_text(source_name), clean_text(source_url), clean_text(publish_time))


def _pick_field(row: dict[str, str], field_name: str) -> str:
    for alias in CSV_FIELD_ALIASES[field_name]:
        if alias in row and row[alias]:
            return clean_text(row[alias])
    return ""


def import_csv_file(file_obj: BinaryIO) -> dict[str, object]:
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    content = file_obj.read()
    if isinstance(content, bytes):
        decoded = content.decode("utf-8-sig", errors="ignore")
    else:
        decoded = str(content)
    reader = csv.DictReader(io.StringIO(decoded))
    imported = 0
    skipped = 0
    errors: list[str] = []
    for index, row in enumerate(reader, start=2):
        title = _pick_field(row, "title")
        body = _pick_field(row, "content")
        source_name = _pick_field(row, "source_name")
        source_url = _pick_field(row, "source_url")
        publish_time = _pick_field(row, "publish_time")
        if not title or not body:
            skipped += 1
            continue
        try:
            db.insert_article(title, body, source_name, source_url, publish_time)
            imported += 1
        except Exception as exc:  # pragma: no cover
            errors.append(f"第 {index} 行导入失败：{exc}")
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }
