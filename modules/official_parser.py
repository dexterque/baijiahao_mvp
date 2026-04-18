from __future__ import annotations

from io import BytesIO
import subprocess
from zipfile import BadZipFile, ZipFile
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

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
DOCX_SUFFIXES = (".docx",)
WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


class OfficialParserError(RuntimeError):
    pass


def is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.endswith(ALLOWED_HOST)


def fetch_html(url: str, timeout: int = 20) -> str:
    response = _fetch_response(url, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.text


def fetch_binary(url: str, timeout: int = 20) -> bytes:
    response = _fetch_response(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def _fetch_response(url: str, timeout: int = 20) -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    session = requests.Session()
    # Official source sync should bypass system proxy settings so VPN/SOCKS does not break TLS to ga.sz.gov.cn.
    if is_allowed_url(url):
        session.trust_env = False
    try:
        return session.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.SSLError:
        if not is_allowed_url(url):
            raise
        # Some macOS Python/OpenSSL builds fail TLS negotiation with ga.sz.gov.cn even without a proxy.
        return _fetch_with_curl(url, headers["User-Agent"], timeout)


def _fetch_with_curl(url: str, user_agent: str, timeout: int) -> requests.Response:
    result = subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--noproxy",
            "*",
            "--max-time",
            str(timeout),
            "--user-agent",
            user_agent,
            url,
        ],
        capture_output=True,
        check=True,
    )
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response._content = result.stdout
    return response


def is_docx_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(suffix) for suffix in DOCX_SUFFIXES)


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
    if any(keyword in title for keyword in ("申请表", "表格", "样表", "模板")):
        return "materials_attachment"
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

    attachment_url = find_first_docx_attachment(soup, url)
    return {
        "title": title or url,
        "publish_date": publish_date,
        "content_text": content_text,
        "url": url,
        "attachment_url": attachment_url,
    }


def parse_remote_resource(
    url: str,
    fallback_title: str = "",
    fallback_publish_date: str | None = None,
    timeout: int = 20,
) -> dict[str, str | None]:
    if is_docx_url(url):
        return parse_docx_file(
            fetch_binary(url, timeout=timeout),
            url=url,
            fallback_title=fallback_title,
            fallback_publish_date=fallback_publish_date,
        )

    detail = parse_detail_page(fetch_html(url, timeout=timeout), url)
    attachment_url = detail.get("attachment_url")
    if attachment_url and is_docx_url(str(attachment_url)):
        attachment_detail = parse_docx_file(
            fetch_binary(str(attachment_url), timeout=timeout),
            url=str(attachment_url),
            fallback_title=detail["title"] or fallback_title,
            fallback_publish_date=detail["publish_date"] or fallback_publish_date,
        )
        attachment_detail["url"] = str(attachment_url)
        return attachment_detail
    if fallback_title and (not detail["title"] or detail["title"] == url):
        detail["title"] = fallback_title
    if fallback_publish_date and not detail["publish_date"]:
        detail["publish_date"] = fallback_publish_date
    return detail


def parse_docx_file(
    raw_bytes: bytes,
    url: str,
    fallback_title: str = "",
    fallback_publish_date: str | None = None,
) -> dict[str, str | None]:
    try:
        with ZipFile(BytesIO(raw_bytes)) as archive:
            xml_names = ["word/document.xml"] + sorted(
                name for name in archive.namelist() if name.startswith("word/") and name.endswith(".xml") and name != "word/document.xml"
            )
            paragraphs: list[str] = []
            for name in xml_names:
                try:
                    root = ElementTree.fromstring(archive.read(name))
                except ElementTree.ParseError:
                    continue
                for paragraph in root.findall(".//w:p", WORD_NAMESPACE):
                    text_parts = [node.text for node in paragraph.findall(".//w:t", WORD_NAMESPACE) if node.text]
                    if text_parts:
                        paragraphs.append("".join(text_parts))
    except BadZipFile as exc:
        raise OfficialParserError(f"附件不是可解析的 DOCX 文件：{url}") from exc

    content_text = clean_text("\n".join(paragraphs))
    if len(content_text) < 40:
        raise OfficialParserError(f"DOCX 附件可提取正文过短，无法可靠入库：{url}")

    title = clean_text(fallback_title) or urlparse(url).path.rsplit("/", 1)[-1] or url
    publish_date = fallback_publish_date or parse_date_text(content_text)
    return {
        "title": title,
        "publish_date": publish_date,
        "content_text": content_text,
        "url": url,
    }


def find_first_docx_attachment(soup: BeautifulSoup, base_url: str) -> str | None:
    for link in soup.select("a[href]"):
        href = str(link.get("href", "")).strip()
        if not href:
            continue
        url = normalize_url(href, base_url)
        if is_allowed_url(url) and is_docx_url(url):
            return url
    return None
