from __future__ import annotations
import json
from pathlib import Path

import streamlit as st

from modules import article_importer, db, draft_generator, fact_checker, image_generator, keyword_extractor, official_sync, topic_generator
from modules.utils import clean_text, load_env, save_export_bytes, save_export_file, shorten


load_env()
db.init_db()

st.set_page_config(page_title="百家号内容 MVP", page_icon="📝", layout="wide")


def row_dicts(rows):
    return [dict(row) for row in rows]


def render_article_import_page() -> None:
    st.title("页面 1：竞品文章导入")
    left, right = st.columns(2)

    with left:
        st.subheader("手动录入")
        with st.form("manual_article_form"):
            title = st.text_input("标题")
            source_name = st.text_input("来源名称", value="竞品手动录入")
            source_url = st.text_input("来源链接")
            publish_time = st.text_input("发布时间", placeholder="2026-04-17")
            content = st.text_area("正文", height=280)
            submitted = st.form_submit_button("保存文章")
        if submitted:
            try:
                article_id = article_importer.import_manual_article(
                    title=title,
                    content=content,
                    source_name=source_name,
                    source_url=source_url,
                    publish_time=publish_time,
                )
                st.success(f"文章已保存，ID={article_id}")
            except ValueError as exc:
                st.error(str(exc))

    with right:
        st.subheader("CSV 批量导入")
        uploaded = st.file_uploader("上传 CSV", type=["csv"])
        if uploaded and st.button("开始导入 CSV"):
            result = article_importer.import_csv_file(uploaded)
            st.success(f"导入完成：成功 {result['imported']}，跳过 {result['skipped']}")
            if result["errors"]:
                st.warning("\n".join(result["errors"][:5]))

    st.subheader("文章列表")
    st.caption(f"当前共 {db.count_articles()} 篇文章")
    st.dataframe(row_dicts(db.list_articles(limit=200)), use_container_width=True, hide_index=True)


def render_keyword_page() -> None:
    st.title("页面 2：关键词库")
    left, right, third = st.columns([1, 1, 2])
    with left:
        if st.button("从文章重建关键词"):
            stats = keyword_extractor.rebuild_keyword_tables()
            st.success(f"已处理 {stats['article_count']} 篇文章，写入 {stats['keyword_count']} 个关键词。")
    with right:
        search = st.text_input("搜索关键词")
    with third:
        categories = ["全部"] + db.list_keyword_categories()
        category = st.selectbox("分类筛选", categories, index=0)

    rows = db.list_keywords(search=search, category=category)
    st.metric("关键词数量", len(rows))
    st.dataframe(row_dicts(rows), use_container_width=True, hide_index=True)


def render_official_sync_page() -> None:
    st.title("页面 3：官方资料同步")
    inserted = db.seed_default_sources()
    if inserted:
        st.info(f"已初始化 {inserted} 个白名单来源。")

    limit = st.slider("每个来源抓取详情页上限", min_value=3, max_value=20, value=10)
    if st.button("一键同步官方资料"):
        with st.spinner("正在同步深圳公安官网白名单资料..."):
            summary = official_sync.sync_all_sources(detail_limit=limit)
        st.success(
            f"同步完成：新增 {summary['inserted']}，更新 {summary['updated']}，校验未变 {summary['verified']}，失败 {summary['failed']}"
        )
        for source_result in summary["sources"]:
            with st.expander(source_result["source_name"], expanded=False):
                st.write(
                    {
                        "inserted": source_result["inserted"],
                        "updated": source_result["updated"],
                        "verified": source_result["verified"],
                        "failed": source_result["failed"],
                    }
                )
                if source_result["errors"]:
                    st.warning("\n".join(source_result["errors"][:10]))

    st.subheader("白名单来源")
    st.dataframe(row_dicts(db.list_official_sources()), use_container_width=True, hide_index=True)

    st.subheader("官方资料列表")
    doc_search = st.text_input("搜索官方资料标题或正文")
    docs = db.list_official_docs(search=doc_search, limit=200)
    st.caption(f"当前共 {db.count_official_docs()} 篇官方资料")
    st.dataframe(row_dicts(docs), use_container_width=True, hide_index=True)

    if docs:
        options = {f"{row['id']} - {row['title']}": int(row["id"]) for row in docs}
        selected_label = st.selectbox("查看资料详情", list(options.keys()))
        detail = db.get_official_doc(options[selected_label])
        if detail:
            st.markdown(f"**标题**：{detail['title']}")
            st.markdown(f"**来源**：{detail['source_name']}")
            st.markdown(f"**链接**：{detail['url']}")
            st.markdown(f"**发布日期**：{detail['publish_date'] or '未解析到'}")
            facts = json.loads(detail["facts_json"]) if detail["facts_json"] else {}
            st.markdown("**facts_json**")
            st.json(facts)
            st.markdown("**正文**")
            st.text_area("official_doc_detail", value=detail["content_text"], height=340, label_visibility="collapsed")


def render_draft_page() -> None:
    st.title("页面 4：选题与出稿")
    keyword_options = db.list_keyword_choices()
    if not keyword_options:
        st.info("请先导入文章并在关键词页生成关键词。")
        return

    success_message = st.session_state.pop("draft_generation_success", None)
    if success_message:
        st.success(success_message)

    error_message = st.session_state.pop("draft_generation_error", None)
    if error_message:
        st.error(error_message)

    image_success_message = st.session_state.pop("image_generation_success", None)
    if image_success_message:
        st.success(image_success_message)

    image_error_message = st.session_state.pop("image_generation_error", None)
    if image_error_message:
        st.error(image_error_message)

    main_keyword = st.selectbox("主关键词", keyword_options)
    default_related = [keyword for keyword in keyword_options if keyword != main_keyword][:5]
    related_keywords = st.multiselect("相关关键词", keyword_options, default=default_related)

    if st.button("生成 5 个选题"):
        try:
            topics = topic_generator.generate_topics(main_keyword, related_keywords)
            st.session_state["generated_topics"] = topics
        except Exception as exc:
            st.error(str(exc))

    topics = st.session_state.get("generated_topics", [])
    if topics:
        selected_topic = st.radio("选择一个选题", topics, key="selected_topic")
    else:
        selected_topic = ""

    official_docs = db.search_official_docs(main_keyword, limit=8)
    if official_docs:
        st.markdown("**匹配到的官方资料**")
        for row in official_docs:
            st.write(f"- {row['title']} ({row['publish_date'] or '未标注日期'})")
    else:
        st.warning("当前关键词没有匹配到官方资料，生成草稿时会使用保守表达。")

    draft_title = st.text_input("草稿标题", value=selected_topic)
    pending_request = st.session_state.get("pending_draft_request")
    if pending_request:
        st.info("正在生成文章初稿，请稍候，生成完成后会自动显示结果。")
        with st.spinner("正在基于选题和官方资料生成文章初稿..."):
            try:
                content = draft_generator.generate_draft(
                    topic=pending_request["topic"],
                    main_keyword=pending_request["main_keyword"],
                    related_keywords=pending_request["related_keywords"],
                    official_docs=pending_request["official_docs"],
                )
                st.session_state["draft_content"] = content
                st.session_state["draft_title"] = pending_request["title"]
                draft_id = db.save_draft(
                    topic=pending_request["topic"],
                    main_keyword=pending_request["main_keyword"],
                    title=pending_request["title"],
                    content=content,
                )
                st.session_state["current_draft_id"] = draft_id
                st.session_state["generated_cover_image"] = None
                st.session_state["generated_cover_image_name"] = None
                st.session_state["draft_generation_success"] = f"草稿已生成并保存，ID={draft_id}"
            except Exception as exc:
                st.session_state["draft_generation_error"] = str(exc)
            finally:
                st.session_state["pending_draft_request"] = None
        st.rerun()

    if st.button("生成文章初稿", disabled=not selected_topic or pending_request is not None):
        st.session_state["pending_draft_request"] = {
            "topic": selected_topic,
            "main_keyword": main_keyword,
            "related_keywords": related_keywords,
            "official_docs": [dict(row) for row in official_docs],
            "title": draft_title or selected_topic,
        }
        st.rerun()

    if st.session_state.get("draft_content"):
        edited_title = st.text_input("编辑标题", value=st.session_state.get("draft_title", ""), key="edit_draft_title")
        edited_content = st.text_area(
            "编辑草稿",
            value=st.session_state["draft_content"],
            height=520,
            key="edit_draft_content",
        )
        if st.button("保存当前编辑稿"):
            draft_id = st.session_state.get("current_draft_id")
            if draft_id:
                db.update_draft(draft_id, edited_title, edited_content)
                st.session_state["draft_title"] = edited_title
                st.session_state["draft_content"] = edited_content
                st.success("草稿已更新。")

        default_image_prompt = image_generator.build_cover_prompt(
            title=st.session_state.get("draft_title", edited_title),
            article_content=st.session_state.get("draft_content", edited_content),
            main_keyword=main_keyword,
        )
        prompt_cache_key = (
            st.session_state.get("current_draft_id"),
            st.session_state.get("draft_title", edited_title),
            st.session_state.get("draft_content", edited_content),
            main_keyword,
        )
        if st.session_state.get("cover_image_prompt_seed") != prompt_cache_key:
            st.session_state["cover_image_prompt"] = default_image_prompt
            st.session_state["cover_image_prompt_seed"] = prompt_cache_key

        st.subheader("封面图生成")
        image_size = st.selectbox(
            "图片尺寸",
            ["1536x1024", "1024x1024", "1024x1536"],
            index=0,
            help="默认推荐横版 1536x1024，适合文章封面。",
        )
        image_quality = st.selectbox(
            "图片质量",
            ["medium", "low", "high"],
            index=0,
            help="质量越高越慢，也可能更贵。",
        )
        image_prompt = st.text_area(
            "封面图提示词",
            key="cover_image_prompt",
            height=180,
        )

        pending_image_request = st.session_state.get("pending_image_request")
        if pending_image_request:
            st.info("正在生成封面图，请稍候，生成完成后会自动显示预览。")
            with st.spinner("正在生成封面图..."):
                try:
                    image_bytes = image_generator.generate_image(
                        prompt=pending_image_request["prompt"],
                        size=pending_image_request["size"],
                        quality=pending_image_request["quality"],
                    )
                    st.session_state["generated_cover_image"] = image_bytes
                    st.session_state["generated_cover_image_name"] = pending_image_request["filename"]
                    st.session_state["image_generation_success"] = "封面图已生成。"
                except Exception as exc:
                    st.session_state["image_generation_error"] = str(exc)
                finally:
                    st.session_state["pending_image_request"] = None
            st.rerun()

        if st.button("生成封面图", disabled=not image_prompt.strip() or pending_image_request is not None):
            draft_id = st.session_state.get("current_draft_id") or "current"
            st.session_state["pending_image_request"] = {
                "prompt": image_prompt,
                "size": image_size,
                "quality": image_quality,
                "filename": f"draft_{draft_id}_cover.png",
            }
            st.rerun()

        generated_cover_image = st.session_state.get("generated_cover_image")
        generated_cover_image_name = st.session_state.get("generated_cover_image_name", "draft_cover.png")
        if generated_cover_image:
            st.image(generated_cover_image, caption="已生成封面图", use_container_width=True)
            image_col1, image_col2 = st.columns(2)
            with image_col1:
                st.download_button(
                    "下载 PNG",
                    data=generated_cover_image,
                    file_name=generated_cover_image_name,
                    mime="image/png",
                )
            with image_col2:
                if st.button("保存 PNG 到 exports/"):
                    path = save_export_bytes(generated_cover_image_name, generated_cover_image)
                    st.success(f"已保存到 {path}")


def render_fact_check_page() -> None:
    st.title("页面 5：轻量校验")
    drafts = db.list_drafts()
    if not drafts:
        st.info("请先在上一页生成并保存草稿。")
        return

    options = {f"{row['id']} - {row['title'] or row['topic']}": int(row["id"]) for row in drafts}
    selected_label = st.selectbox("选择草稿", list(options.keys()))
    draft = db.get_draft(options[selected_label])
    if not draft:
        st.warning("未找到草稿。")
        return

    official_docs = db.search_official_docs(draft["main_keyword"] or "", limit=5)
    st.markdown(f"**主关键词**：{draft['main_keyword'] or '未记录'}")
    st.markdown(f"**当前状态**：{draft['fact_status'] or 'unchecked'}")
    st.text_area("draft_preview", value=draft["content"], height=320, label_visibility="collapsed")

    if st.button("执行轻量校验"):
        result = fact_checker.check_draft(draft["content"], official_docs)
        db.update_draft_fact_check(int(draft["id"]), str(result["fact_status"]), str(result["fact_notes"]))
        st.session_state["fact_result"] = result
        st.success(f"校验完成：{result['fact_status']}")

    result = st.session_state.get("fact_result")
    if result:
        st.markdown(f"**整体状态**：`{result['fact_status']}`")
        st.markdown(f"**问题摘要**：{result['fact_notes']}")
        if result["high_risk_hits"]:
            st.markdown("**命中的高风险表述**")
            for phrase in result["high_risk_hits"]:
                st.write(f"- {phrase}")
        if result["suspicious_sentences"]:
            st.markdown("**存疑句**")
            for sentence in result["suspicious_sentences"]:
                st.write(f"- {sentence}")
        if result["referenced_docs"]:
            st.markdown("**参考官方资料标题**")
            for title in result["referenced_docs"]:
                st.write(f"- {title}")

    txt_content = clean_text(draft["content"])
    md_content = f"# {draft['title'] or draft['topic']}\n\n{txt_content}\n"
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "下载 TXT",
            data=txt_content,
            file_name=f"draft_{draft['id']}.txt",
            mime="text/plain",
        )
        if st.button("保存 TXT 到 exports/"):
            path = save_export_file(f"draft_{draft['id']}.txt", txt_content)
            st.success(f"已保存到 {path}")
    with col2:
        st.download_button(
            "下载 Markdown",
            data=md_content,
            file_name=f"draft_{draft['id']}.md",
            mime="text/markdown",
        )
        if st.button("保存 Markdown 到 exports/"):
            path = save_export_file(f"draft_{draft['id']}.md", md_content)
            st.success(f"已保存到 {path}")


def render_home_metrics() -> None:
    articles_count = db.count_articles()
    official_docs_count = db.count_official_docs()
    drafts_count = len(db.list_drafts(limit=1000))
    col1, col2, col3 = st.columns(3)
    col1.metric("竞品文章", articles_count)
    col2.metric("官方资料", official_docs_count)
    col3.metric("草稿数量", drafts_count)
    st.caption("竞品文章只负责提关键词和标题风格；官方资料只负责提供事实；LLM 只负责组织语言。")


PAGES = {
    "竞品文章导入": render_article_import_page,
    "关键词库": render_keyword_page,
    "官方资料同步": render_official_sync_page,
    "选题与出稿": render_draft_page,
    "轻量校验": render_fact_check_page,
}


st.sidebar.title("百家号内容 MVP")
page = st.sidebar.radio("导航", list(PAGES.keys()))
render_home_metrics()
st.divider()
PAGES[page]()
