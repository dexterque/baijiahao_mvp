from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules import cover_generator, db, wechatsync_client  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将本地草稿同步到百家号草稿箱。")
    parser.add_argument("--draft-id", type=int, help="指定要同步的草稿 ID。")
    parser.add_argument(
        "--checked-only",
        action="store_true",
        help="只选择 fact_status=checked 的最新草稿。",
    )
    parser.add_argument(
        "--platform",
        default="baijiahao",
        help="目标平台，默认 baijiahao。",
    )
    parser.add_argument(
        "--generate-cover",
        action="store_true",
        help="同步前基于草稿标题和正文生成封面图。",
    )
    parser.add_argument(
        "--cover-size",
        default="1536x1024",
        help="封面图尺寸，默认 1536x1024。",
    )
    parser.add_argument(
        "--cover-quality",
        default="medium",
        help="封面图质量，默认 medium，可选 low、medium、high。",
    )
    parser.add_argument(
        "--cover-provider",
        default="local",
        help="封面图生成器，默认 local，可选 local、met、auto、openai。",
    )
    return parser.parse_args()


def choose_draft(draft_id: int | None, checked_only: bool):
    if draft_id is not None:
        return db.get_draft(draft_id)

    drafts = db.list_drafts(limit=200)
    if checked_only:
        for row in drafts:
            if row["fact_status"] == "checked":
                return row
        return None
    return drafts[0] if drafts else None


def main() -> int:
    args = parse_args()
    db.init_db()
    draft = choose_draft(args.draft_id, args.checked_only)
    if not draft:
        print("未找到可同步的草稿。", file=sys.stderr)
        return 1

    title = draft["title"] or draft["topic"] or f"draft_{draft['id']}"
    cover_input: str | None = None
    if args.generate_cover:
        cover_result = cover_generator.generate_cover_asset(
            draft_id=int(draft["id"]),
            title=title,
            article_content=str(draft["content"]),
            main_keyword=str(draft["main_keyword"] or ""),
            provider=args.cover_provider,
            size=args.cover_size,
            quality=args.cover_quality,
        )
        cover_input = str(cover_result["path"])

    try:
        result = wechatsync_client.sync_draft_to_platform(
            draft_id=int(draft["id"]),
            title=title,
            content=str(draft["content"]),
            platform=args.platform,
            cover=cover_input,
        )
    except Exception as exc:
        db.update_draft_sync_status(int(draft["id"]), args.platform, "failed", str(exc))
        print(str(exc), file=sys.stderr)
        return 1

    db.update_draft_sync_status(
        int(draft["id"]),
        str(result["platform"]),
        "synced",
        str(result["output"]),
    )
    print(f"草稿 {draft['id']} 已同步到 {result['platform']} 草稿箱。")
    print(f"Markdown: {result['markdown_path']}")
    print(result["output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
