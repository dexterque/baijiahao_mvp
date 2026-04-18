from __future__ import annotations

import random
import re
from pathlib import Path

import requests
from PIL import Image, ImageOps

from modules.utils import PROJECT_ROOT, clean_text, ensure_directories


SEARCH_URL = "https://collectionapi.metmuseum.org/public/collection/v1/search"
OBJECT_URL = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{object_id}"
BLOCKLIST_TERMS = {
    "nude",
    "nudity",
    "battle",
    "war",
    "martyrdom",
    "crucifixion",
    "death",
    "skull",
    "execution",
}
ALLOWED_CLASSIFICATIONS = {
    "Paintings",
    "Prints",
    "Drawings",
    "Photographs",
    "Illustrated Books",
    "Albums",
}


class MetCoverProviderError(RuntimeError):
    pass


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": "baijiahao-mvp/1.0",
            "Accept": "application/json",
        }
    )
    return session


def _query_candidates(title: str, main_keyword: str, article_content: str) -> list[str]:
    text = " ".join([clean_text(title), clean_text(main_keyword), clean_text(article_content[:600])])
    queries: list[str] = []

    if any(word in text for word in ["入户", "户口", "迁入", "深圳", "办理"]):
        queries.extend(["architecture", "city", "harbor", "street"])
    if any(word in text for word in ["材料", "申请", "表格", "流程", "指南"]):
        queries.extend(["manuscript", "letter", "writing", "interior"])
    if any(word in text for word in ["教育", "学校", "学习", "考试"]):
        queries.extend(["school", "study", "library"])
    if any(word in text for word in ["政策", "知识", "说明", "解读"]):
        queries.extend(["scholar", "book", "print"])

    queries.extend(["architecture", "landscape", "harbor", "street", "garden"])
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        deduped.append(query)
    return deduped[:8]


def _title_is_allowed(title: str) -> bool:
    normalized = clean_text(title).lower()
    return not any(term in normalized for term in BLOCKLIST_TERMS)


def _search_object_ids(session: requests.Session, query: str, limit: int = 20) -> list[int]:
    response = session.get(
        SEARCH_URL,
        params={"hasImages": "true", "q": query},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    object_ids = payload.get("objectIDs") or []
    return [int(object_id) for object_id in object_ids[:limit]]


def _fetch_object(session: requests.Session, object_id: int) -> dict[str, object]:
    response = session.get(OBJECT_URL.format(object_id=object_id), timeout=30)
    response.raise_for_status()
    return dict(response.json())


def _collect_candidates(session: requests.Session, queries: list[str], per_query_limit: int = 20) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    for query in queries:
        for object_id in _search_object_ids(session, query=query, limit=per_query_limit):
            if object_id in seen_ids:
                continue
            seen_ids.add(object_id)
            try:
                item = _fetch_object(session, object_id)
            except Exception:
                continue
            if not item.get("isPublicDomain"):
                continue
            if not _title_is_allowed(str(item.get("title", ""))):
                continue
            classification = str(item.get("classification") or "")
            if classification and classification not in ALLOWED_CLASSIFICATIONS:
                continue
            image_url = str(item.get("primaryImage") or item.get("primaryImageSmall") or "").strip()
            image_url_small = str(item.get("primaryImageSmall") or "").strip()
            if not image_url:
                continue
            item["image_url"] = image_url
            item["image_url_small"] = image_url_small
            candidates.append(item)
            if len(candidates) >= 18:
                return candidates
    return candidates


def _download_image(session: requests.Session, image_urls: list[str]) -> bytes:
    last_error: Exception | None = None
    for image_url in image_urls:
        if not clean_text(image_url):
            continue
        try:
            response = session.get(image_url, timeout=60)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            last_error = exc
    raise MetCoverProviderError(f"下载 The Met 图片失败：{last_error}")


def _resize_cover(image_bytes: bytes, size: str) -> bytes:
    match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", size.strip())
    if not match:
        raise MetCoverProviderError(f"无效的封面尺寸：{size}")
    width, height = int(match.group(1)), int(match.group(2))
    with Image.open(Path("/dev/null") if False else __import__("io").BytesIO(image_bytes)) as image:
        converted = image.convert("RGB")
        fitted = ImageOps.fit(converted, (width, height), method=Image.Resampling.LANCZOS)
        buffer = __import__("io").BytesIO()
        fitted.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def _save_cover_bytes(image_bytes: bytes, draft_id: int) -> Path:
    ensure_directories()
    target_path = PROJECT_ROOT / "exports" / "covers" / f"draft_{draft_id}_cover.png"
    target_path.write_bytes(image_bytes)
    return target_path


def generate_met_cover(
    draft_id: int,
    title: str,
    article_content: str,
    main_keyword: str,
    size: str = "1536x1024",
) -> dict[str, object]:
    session = _session()
    queries = _query_candidates(title=title, main_keyword=main_keyword, article_content=article_content)
    candidates = _collect_candidates(session, queries=queries)
    if not candidates:
        raise MetCoverProviderError("The Met 未找到合适的公版作品封面候选。")

    selected = random.SystemRandom().choice(candidates)
    original_bytes = _download_image(
        session,
        [
            str(selected.get("image_url") or ""),
            str(selected.get("image_url_small") or ""),
        ],
    )
    cover_bytes = _resize_cover(original_bytes, size=size)
    output_path = _save_cover_bytes(cover_bytes, draft_id=draft_id)
    return {
        "provider": "met",
        "path": output_path,
        "bytes": cover_bytes,
        "source_title": selected.get("title"),
        "source_artist": selected.get("artistDisplayName"),
        "source_object_id": selected.get("objectID"),
        "source_image_url": selected.get("image_url"),
    }
