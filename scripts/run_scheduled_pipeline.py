from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules import db, draft_generator, fact_checker, image_generator, keyword_extractor, official_sync, topic_generator, wechatsync_client  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="定时生成文章并同步到百家号草稿箱。")
    parser.add_argument("--main-keyword", help="指定主关键词，不传时自动取关键词库第一名。")
    parser.add_argument(
        "--related-keyword-count",
        type=int,
        default=5,
        help="自动附带的相关关键词数量，默认 5。",
    )
    parser.add_argument(
        "--topic-index",
        type=int,
        default=0,
        help="选题下标，默认取第 1 个。",
    )
    parser.add_argument(
        "--sync-official",
        action="store_true",
        help="运行前先同步官方资料。",
    )
    parser.add_argument(
        "--official-detail-limit",
        type=int,
        default=10,
        help="官方资料同步时每个来源抓取详情页上限，默认 10。",
    )
    parser.add_argument(
        "--rebuild-keywords",
        action="store_true",
        help="运行前先从竞品文章重建关键词。",
    )
    parser.add_argument(
        "--strict-fact-check",
        action="store_true",
        help="仅当轻量校验结果为 pass 时才推送到百家号草稿箱。",
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="只生成和校验，不推送草稿箱。",
    )
    parser.add_argument(
        "--skip-cover-generation",
        action="store_true",
        help="跳过封面图生成；默认会基于文章标题和正文生成封面图。",
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
        "--platform",
        default="baijiahao",
        help="目标平台，默认 baijiahao。",
    )
    return parser.parse_args()


def choose_main_keyword(explicit_keyword: str | None) -> str:
    if explicit_keyword:
        return explicit_keyword.strip()
    keyword_choices = db.list_keyword_choices(limit=50)
    if not keyword_choices:
        raise RuntimeError("关键词库为空。请先导入竞品文章，并至少执行一次关键词重建。")
    return keyword_choices[0]


def choose_related_keywords(main_keyword: str, count: int) -> list[str]:
    keyword_choices = db.list_keyword_choices(limit=max(20, count + 5))
    return [keyword for keyword in keyword_choices if keyword != main_keyword][: max(count, 0)]


def choose_topic(topics: list[str], topic_index: int) -> str:
    if not topics:
        raise RuntimeError("没有生成出可用选题。")
    if topic_index < 0 or topic_index >= len(topics):
        raise RuntimeError(f"topic-index 超出范围，可选范围是 0 到 {len(topics) - 1}。")
    return topics[topic_index]


def print_step(message: str) -> None:
    print(f"[pipeline] {message}")


def main() -> int:
    args = parse_args()
    db.init_db()

    if args.sync_official:
        print_step("开始同步官方资料")
        sync_summary = official_sync.sync_all_sources(detail_limit=max(args.official_detail_limit, 1))
        print_step(
            "官方资料同步完成："
            f"新增 {sync_summary['inserted']}，更新 {sync_summary['updated']}，"
            f"校验未变 {sync_summary['verified']}，失败 {sync_summary['failed']}"
        )

    if args.rebuild_keywords:
        print_step("开始重建关键词")
        keyword_stats = keyword_extractor.rebuild_keyword_tables()
        print_step(
            f"关键词重建完成：处理 {keyword_stats['article_count']} 篇文章，"
            f"写入 {keyword_stats['keyword_count']} 个关键词"
        )

    main_keyword = choose_main_keyword(args.main_keyword)
    related_keywords = choose_related_keywords(main_keyword, args.related_keyword_count)
    print_step(f"主关键词：{main_keyword}")
    if related_keywords:
        print_step(f"相关关键词：{'、'.join(related_keywords)}")

    topics = topic_generator.generate_topics(main_keyword, related_keywords)
    topic = choose_topic(topics, args.topic_index)
    print_step(f"已选选题：{topic}")

    official_docs = db.search_official_docs(main_keyword, limit=8)
    print_step(f"匹配到 {len(official_docs)} 篇官方资料")

    draft_content = draft_generator.generate_draft(
        topic=topic,
        main_keyword=main_keyword,
        related_keywords=related_keywords,
        official_docs=official_docs,
    )
    draft_id = db.save_draft(
        topic=topic,
        main_keyword=main_keyword,
        title=topic,
        content=draft_content,
    )
    print_step(f"草稿已保存，ID={draft_id}")

    fact_result = fact_checker.check_draft(draft_content, official_docs)
    db.update_draft_fact_check(
        draft_id,
        str(fact_result["fact_status"]),
        str(fact_result["fact_notes"]),
    )
    print_step(
        "轻量校验完成："
        f"状态={fact_result['fact_status']}，说明={fact_result['fact_notes']}"
    )

    cover_data_uri: str | None = None
    if not args.skip_cover_generation:
        print_step("开始生成封面图")
        cover_prompt = image_generator.build_cover_prompt(
            title=topic,
            article_content=draft_content,
            main_keyword=main_keyword,
        )
        cover_image = image_generator.generate_image(
            prompt=cover_prompt,
            size=args.cover_size,
            quality=args.cover_quality,
        )
        cover_filename = image_generator.build_cover_filename(draft_id)
        cover_path = image_generator.save_cover_image(cover_image, cover_filename)
        cover_data_uri = image_generator.build_image_data_uri(cover_image)
        print_step(f"封面图已生成：{cover_path}")

    if args.skip_sync:
        print_step("已按参数跳过草稿箱同步")
        return 0

    fact_status = str(fact_result["fact_status"])
    can_sync = fact_status in {"pass", "warning"}
    if args.strict_fact_check:
        can_sync = fact_status == "pass"
    if not can_sync:
        message = (
            f"草稿 {draft_id} 未推送到 {args.platform}："
            f"轻量校验结果为 {fact_status}。"
            "当前启用了严格校验，只允许 pass 推送。"
        )
        db.update_draft_sync_status(draft_id, args.platform, "skipped", message)
        print_step(message)
        return 1

    try:
        sync_result = wechatsync_client.sync_draft_to_platform(
            draft_id=draft_id,
            title=topic,
            content=draft_content,
            platform=args.platform,
            cover=cover_data_uri,
        )
    except Exception as exc:
        db.update_draft_sync_status(draft_id, args.platform, "failed", str(exc))
        print_step(f"草稿箱同步失败：{exc}")
        return 1

    db.update_draft_sync_status(
        draft_id,
        str(sync_result["platform"]),
        "synced",
        str(sync_result["output"]),
    )
    print_step(f"已同步到 {sync_result['platform']} 草稿箱")
    print_step(f"Markdown 导出：{sync_result['markdown_path']}")
    print(sync_result["output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
