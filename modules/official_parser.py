from __future__ import annotations

from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from modules.utils import clean_text, normalize_whitespace_inline, parse_date_text


ALLOWED_HOST = "ga.sz.gov.cn"
TITLE_HINTS = ("入户", "户政", "户籍", "迁入", "迁移", "材料", "流程", "条件", "公告", "通知")
CONTENT_SELECTORS = [
    "div.TRS_Editor",
    "div.zw",
    "div.article",
    "div.article-content",
    "div.content",
    "article",
    "main",
]


class OfficialParserError(RuntimeError):
    pass


def is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.endswith(ALLOWED_HOST)


def fetch_html(url: str, timeout: int = 20) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.text


def normalize_url(href: str, base_url: str) -> str:
    url = urljoin(base_url, href.strip())
    if url.endswith("#"):
        url = url[:-1]
    return url


def looks_relevant(title: str, url: str, source_type: str) -> bool:
    title = normalize_whitespace_inline(title)
    if any(keyword in title for keyword in TITLE_HINTS):
        return True
    if source_type == "homepage" and any(
        key in url for key in ("YWZSK/HJGL_ZS", "WSBS", "ZDYW/ZDYWRK")
    ):
        return True
    if source_type in {"migration_entry", "notice_entry"} and "/content/post_" in url:
        return True
    if source_type == "materials_entry" and any(key in url for key in ("WSBS", "bszn", "bgxz")):
        return True
    return False


def guess_category(title: str, source_type: str) -> str:
    title = title or ""
    if "材料" in title:
        return "materials"
    if "流程" in title or "办理" in title:
        return "process"
    if "条件" in title:
        return "conditions"
    if "通知" in title or "公告" in title:
        return "notice"
    return source_type


def parse_listing_page(html: str, base_url: str, source_type: str, limit: int = 20) -> list[dict[str, str | None]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        title = clean_text(link.get_text(" "))
        if len(title) < 4 or len(title) > 80:
            continue
        url = normalize_url(link["href"], base_url)
        if not is_allowed_url(url):
            continue
        if url == base_url or url in seen:
            continue
        if not looks_relevant(title, url, source_type):
            continue
        context_text = clean_text(link.parent.get_text(" "))
        results.append(
            {
                "title": title,
                "url": url,
                "publish_date": parse_date_text(context_text),
                "category": guess_category(title, source_type),
            }
        )
        seen.add(url)
        if len(results) >= limit:
            break
    return results


def parse_detail_page(html: str, url: str) -> dict[str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = ""
    title_tag = soup.select_one("h1") or soup.select_one("title")
    if title_tag:
        title = clean_text(title_tag.get_text(" "))

    publish_date = parse_date_text(clean_text(soup.get_text(" ")))

    content_text = ""
    for selector in CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if not node:
            continue
        candidate = clean_text(node.get_text("\n"))
        if len(candidate) >= 120:
            content_text = candidate
            break

    if not content_text:
        body = soup.body.get_text("\n") if soup.body else soup.get_text("\n")
        content_text = clean_text(body)

    if len(content_text) < 80:
        raise OfficialParserError(f"详情页正文过短，无法可靠解析：{url}")

    return {
        "title": title or url,
        "publish_date": publish_date,
        "content_text": content_text,
        "url": url,
    }
