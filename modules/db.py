from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from modules.utils import PROJECT_ROOT, ensure_directories, load_env, now_str


DEFAULT_OFFICIAL_SOURCES = [
    {
        "name": "深圳市公安局官网首页",
        "url": "https://ga.sz.gov.cn/",
        "source_type": "homepage",
        "is_enabled": 1,
    },
    {
        "name": "户政知识库",
        "url": "https://ga.sz.gov.cn/JMHD/YWZSK/HJGL_ZS/",
        "source_type": "knowledge_base",
        "is_enabled": 1,
    },
    {
        "name": "户籍迁入相关公开入口",
        "url": "https://ga.sz.gov.cn/ZDYW/ZDYWRK/",
        "source_type": "migration_entry",
        "is_enabled": 1,
    },
    {
        "name": "申请材料相关公开入口",
        "url": "https://ga.sz.gov.cn/WSBS/",
        "source_type": "materials_entry",
        "is_enabled": 1,
    },
    {
        "name": "通知公告相关公开入口",
        "url": "https://ga.sz.gov.cn/szsgajgkml/szsgajgkml/qt/tzgg/",
        "source_type": "notice_entry",
        "is_enabled": 1,
    },
]


def get_database_path() -> Path:
    load_env()
    ensure_directories()
    raw_path = os.getenv("DATABASE_PATH", "data/baijiahao.db")
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_database_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_directories()
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source_name TEXT,
                source_url TEXT,
                publish_time TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE,
                category TEXT,
                freq INTEGER DEFAULT 0,
                article_count INTEGER DEFAULT 0,
                last_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS article_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                weight REAL DEFAULT 0,
                FOREIGN KEY(article_id) REFERENCES articles(id)
            );

            CREATE TABLE IF NOT EXISTS official_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                source_type TEXT,
                is_enabled INTEGER DEFAULT 1,
                last_synced_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS official_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                category TEXT,
                publish_date TEXT,
                content_text TEXT NOT NULL,
                facts_json TEXT,
                content_hash TEXT NOT NULL,
                last_verified_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES official_sources(id)
            );

            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                main_keyword TEXT,
                title TEXT,
                content TEXT NOT NULL,
                fact_status TEXT DEFAULT 'unchecked',
                fact_notes TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
    seed_default_sources()


def seed_default_sources() -> int:
    inserted = 0
    with get_connection() as conn:
        for source in DEFAULT_OFFICIAL_SOURCES:
            existing = conn.execute(
                "SELECT id FROM official_sources WHERE url = ?",
                (source["url"],),
            ).fetchone()
            if existing:
                continue
            timestamp = now_str()
            conn.execute(
                """
                INSERT INTO official_sources (
                    name, url, source_type, is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source["name"],
                    source["url"],
                    source["source_type"],
                    source["is_enabled"],
                    timestamp,
                    timestamp,
                ),
            )
            inserted += 1
    return inserted


def insert_article(
    title: str,
    content: str,
    source_name: str = "",
    source_url: str = "",
    publish_time: str = "",
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO articles (
                title, content, source_name, source_url, publish_time, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, content, source_name, source_url, publish_time, now_str()),
        )
        return int(cursor.lastrowid)


def list_articles(limit: int = 200) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM articles
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def count_articles() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM articles").fetchone()
        return int(row["count"])


def get_all_articles() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM articles ORDER BY id ASC").fetchall()


def replace_keywords(
    keyword_rows: list[dict[str, Any]],
    article_keyword_rows: list[dict[str, Any]],
) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM article_keywords")
        conn.execute("DELETE FROM keywords")
        for row in keyword_rows:
            conn.execute(
                """
                INSERT INTO keywords (keyword, category, freq, article_count, last_seen)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["keyword"],
                    row["category"],
                    row["freq"],
                    row["article_count"],
                    row["last_seen"],
                ),
            )
        for row in article_keyword_rows:
            conn.execute(
                """
                INSERT INTO article_keywords (article_id, keyword, weight)
                VALUES (?, ?, ?)
                """,
                (row["article_id"], row["keyword"], row["weight"]),
            )


def list_keywords(search: str = "", category: str = "全部", limit: int = 500) -> list[sqlite3.Row]:
    sql = "SELECT * FROM keywords WHERE 1 = 1"
    params: list[Any] = []
    if search:
        sql += " AND keyword LIKE ?"
        params.append(f"%{search}%")
    if category and category != "全部":
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY freq DESC, article_count DESC, keyword ASC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


def list_keyword_categories() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM keywords WHERE category IS NOT NULL AND category != '' ORDER BY category"
        ).fetchall()
    return [row["category"] for row in rows]


def list_keyword_choices(limit: int = 200) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT keyword FROM keywords
            ORDER BY article_count DESC, freq DESC, keyword ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [row["keyword"] for row in rows]


def list_enabled_sources() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM official_sources WHERE is_enabled = 1 ORDER BY id ASC"
        ).fetchall()


def list_official_sources() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM official_sources ORDER BY id ASC").fetchall()


def mark_source_synced(source_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE official_sources
            SET last_synced_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now_str(), now_str(), source_id),
        )


def upsert_official_doc(
    source_id: int,
    title: str,
    url: str,
    category: str,
    publish_date: str | None,
    content_text: str,
    facts_json: dict[str, Any],
    content_hash: str,
) -> str:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id, content_hash FROM official_docs WHERE url = ?",
            (url,),
        ).fetchone()
        timestamp = now_str()
        serialized_facts = json.dumps(facts_json, ensure_ascii=False)
        if not existing:
            conn.execute(
                """
                INSERT INTO official_docs (
                    source_id, title, url, category, publish_date,
                    content_text, facts_json, content_hash,
                    last_verified_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    title,
                    url,
                    category,
                    publish_date,
                    content_text,
                    serialized_facts,
                    content_hash,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            return "inserted"

        if existing["content_hash"] == content_hash:
            conn.execute(
                """
                UPDATE official_docs
                SET last_verified_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, existing["id"]),
            )
            return "verified"

        conn.execute(
            """
            UPDATE official_docs
            SET source_id = ?, title = ?, category = ?, publish_date = ?,
                content_text = ?, facts_json = ?, content_hash = ?,
                last_verified_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                source_id,
                title,
                category,
                publish_date,
                content_text,
                serialized_facts,
                content_hash,
                timestamp,
                timestamp,
                existing["id"],
            ),
        )
        return "updated"


def list_official_docs(search: str = "", limit: int = 200) -> list[sqlite3.Row]:
    sql = """
        SELECT d.*, s.name AS source_name
        FROM official_docs d
        JOIN official_sources s ON s.id = d.source_id
        WHERE 1 = 1
    """
    params: list[Any] = []
    if search:
        sql += " AND (d.title LIKE ? OR d.content_text LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    sql += " ORDER BY COALESCE(d.publish_date, d.updated_at) DESC, d.id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


def get_official_doc(doc_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT d.*, s.name AS source_name
            FROM official_docs d
            JOIN official_sources s ON s.id = d.source_id
            WHERE d.id = ?
            """,
            (doc_id,),
        ).fetchone()


def search_official_docs(keyword: str, limit: int = 8) -> list[sqlite3.Row]:
    if not keyword:
        return []
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT d.*, s.name AS source_name
            FROM official_docs d
            JOIN official_sources s ON s.id = d.source_id
            WHERE d.title LIKE ? OR d.content_text LIKE ?
            ORDER BY COALESCE(d.publish_date, d.updated_at) DESC, d.id DESC
            LIMIT ?
            """,
            (f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()


def count_official_docs() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM official_docs").fetchone()
        return int(row["count"])


def save_draft(
    topic: str,
    main_keyword: str,
    title: str,
    content: str,
    fact_status: str = "unchecked",
    fact_notes: str = "",
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO drafts (topic, main_keyword, title, content, fact_status, fact_notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (topic, main_keyword, title, content, fact_status, fact_notes, now_str()),
        )
        return int(cursor.lastrowid)


def update_draft(
    draft_id: int,
    title: str,
    content: str,
    fact_status: str | None = None,
    fact_notes: str | None = None,
) -> None:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT fact_status, fact_notes FROM drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if not existing:
            return
        conn.execute(
            """
            UPDATE drafts
            SET title = ?, content = ?, fact_status = ?, fact_notes = ?
            WHERE id = ?
            """,
            (
                title,
                content,
                fact_status or existing["fact_status"],
                fact_notes if fact_notes is not None else existing["fact_notes"],
                draft_id,
            ),
        )


def update_draft_fact_check(draft_id: int, fact_status: str, fact_notes: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE drafts
            SET fact_status = ?, fact_notes = ?
            WHERE id = ?
            """,
            (fact_status, fact_notes, draft_id),
        )


def list_drafts(limit: int = 100) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM drafts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_draft(draft_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
