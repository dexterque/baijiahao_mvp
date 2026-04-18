from __future__ import annotations

from typing import Any

import requests

from modules import db
from modules.official_parser import OfficialParserError, fetch_html, parse_listing_page, parse_remote_resource
from modules.utils import compute_hash, split_sentences, unique_preserve


FACT_RULES = {
    "conditions": ("条件", "符合", "满足", "适用", "对象", "申请人", "申请条件"),
    "materials": ("材料", "证件", "证明", "提交", "原件", "复印件"),
    "process": ("流程", "办理", "申请", "受理", "审核", "迁入", "预约"),
}


def extract_facts_json(content_text: str, bucket_limit: int = 8) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "conditions": [],
        "materials": [],
        "process": [],
    }
    for sentence in split_sentences(content_text):
        for bucket, keywords in FACT_RULES.items():
            if len(buckets[bucket]) >= bucket_limit:
                continue
            if any(keyword in sentence for keyword in keywords):
                buckets[bucket].append(sentence)
    return {key: unique_preserve(value) for key, value in buckets.items()}


def sync_single_source(source: Any, detail_limit: int = 12) -> dict[str, Any]:
    result = {
        "source_id": int(source["id"]),
        "source_name": source["name"],
        "inserted": 0,
        "updated": 0,
        "verified": 0,
        "failed": 0,
        "errors": [],
    }
    try:
        listing_html = fetch_html(source["url"])
        entries = parse_listing_page(
            listing_html,
            base_url=source["url"],
            source_type=source["source_type"],
            limit=detail_limit,
        )
        if not entries:
            entries = [
                {
                    "title": source["name"],
                    "url": source["url"],
                    "publish_date": None,
                    "category": source["source_type"],
                }
            ]
    except Exception as exc:
        result["failed"] += 1
        result["errors"].append(f"{source['name']} 列表页抓取失败：{exc}")
        db.mark_source_synced(int(source["id"]))
        return result

    for entry in entries:
        try:
            detail = parse_remote_resource(
                str(entry["url"]),
                fallback_title=str(entry["title"]),
                fallback_publish_date=entry["publish_date"],
            )
            action = db.upsert_official_doc(
                source_id=int(source["id"]),
                title=detail["title"] or str(entry["title"]),
                url=str(entry["url"]),
                category=str(entry["category"] or source["source_type"]),
                publish_date=detail["publish_date"] or entry["publish_date"],
                content_text=str(detail["content_text"]),
                facts_json=extract_facts_json(str(detail["content_text"])),
                content_hash=compute_hash(str(detail["content_text"])),
            )
            result[action] += 1
        except (OfficialParserError, requests.RequestException, ValueError) as exc:
            result["failed"] += 1
            result["errors"].append(f"{entry['url']} 抓取失败：{exc}")
        except Exception as exc:  # pragma: no cover
            result["failed"] += 1
            result["errors"].append(f"{entry['url']} 未知错误：{exc}")

    db.mark_source_synced(int(source["id"]))
    return result


def sync_all_sources(detail_limit: int = 12) -> dict[str, Any]:
    summary = {
        "sources": [],
        "inserted": 0,
        "updated": 0,
        "verified": 0,
        "failed": 0,
    }
    for source in db.list_enabled_sources():
        source_result = sync_single_source(source, detail_limit=detail_limit)
        summary["sources"].append(source_result)
        summary["inserted"] += source_result["inserted"]
        summary["updated"] += source_result["updated"]
        summary["verified"] += source_result["verified"]
        summary["failed"] += source_result["failed"]
    return summary
