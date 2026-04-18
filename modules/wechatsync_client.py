from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from modules.utils import PROJECT_ROOT, clean_text, ensure_directories, env_or_default


DEFAULT_PLATFORM = "baijiahao"


class WechatSyncError(RuntimeError):
    pass


def _resolve_command() -> list[str]:
    configured_command = clean_text(env_or_default("WECHATSYNC_BIN", ""))
    if configured_command:
        return shlex.split(configured_command)

    installed_command = shutil.which("wechatsync")
    if installed_command:
        return [installed_command]

    return ["npx", "-y", "@wechatsync/cli"]


def _resolve_platform() -> str:
    return clean_text(env_or_default("WECHATSYNC_PLATFORM", DEFAULT_PLATFORM)) or DEFAULT_PLATFORM


def _resolve_timeout_seconds() -> int:
    raw_value = clean_text(env_or_default("WECHATSYNC_TIMEOUT_SECONDS", "300"))
    try:
        timeout_seconds = int(raw_value)
    except ValueError as exc:
        raise WechatSyncError("WECHATSYNC_TIMEOUT_SECONDS 必须是整数。") from exc
    return max(timeout_seconds, 30)


def build_markdown(title: str, content: str) -> str:
    cleaned_title = clean_text(title) or "未命名草稿"
    cleaned_content = clean_text(content)
    if not cleaned_content:
        raise WechatSyncError("草稿正文为空，无法同步到百家号草稿箱。")
    return f"# {cleaned_title}\n\n{cleaned_content}\n"


def _cover_markdown_image(cover: str, markdown_path: Path) -> str:
    cover_value = clean_text(cover)
    if not cover_value:
        return ""
    if cover_value.startswith("http://") or cover_value.startswith("https://"):
        return f"![封面图]({cover_value})"

    cover_path = Path(cover_value).expanduser()
    if not cover_path.exists():
        return ""
    markdown_ref = Path(
        os.path.relpath(cover_path.resolve(), start=markdown_path.parent.resolve())
    ).as_posix()
    return f"![封面图]({markdown_ref})"


def export_draft_markdown(draft_id: int, title: str, content: str, cover: str | None = None) -> Path:
    ensure_directories()
    markdown_path = PROJECT_ROOT / "exports" / "wechatsync" / f"draft_{draft_id}.md"
    markdown_content = build_markdown(title, content)
    cover_block = _cover_markdown_image(cover or "", markdown_path)
    if cover_block:
        markdown_content = markdown_content.replace("\n\n", f"\n\n{cover_block}\n\n", 1)
    markdown_path.write_text(markdown_content, encoding="utf-8")
    return markdown_path


def sync_draft_to_platform(
    draft_id: int,
    title: str,
    content: str,
    platform: str | None = None,
    cover: str | None = None,
) -> dict[str, str]:
    target_platform = clean_text(platform) or _resolve_platform()
    markdown_path = export_draft_markdown(draft_id, title, content, cover=cover)
    command = _resolve_command() + [
        "sync",
        str(markdown_path),
        "-p",
        target_platform,
        "-t",
        clean_text(title) or f"draft_{draft_id}",
    ]
    if clean_text(cover):
        command.extend(["--cover", str(cover)])

    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_resolve_timeout_seconds(),
            check=False,
        )
    except FileNotFoundError as exc:
        raise WechatSyncError(
            "没有找到 wechatsync 命令。请先全局安装 `@wechatsync/cli`，或在 .env 中配置 WECHATSYNC_BIN。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise WechatSyncError(
            "同步超时。请确认 Chrome 扩展已连接、百家号已登录，并检查本机网络。"
        ) from exc

    output = clean_text(
        "\n".join(
            part for part in [completed.stdout.strip(), completed.stderr.strip()] if part.strip()
        )
    )
    if completed.returncode != 0:
        raise WechatSyncError(output or "wechatsync 执行失败，请检查扩展连接和平台登录状态。")

    return {
        "platform": target_platform,
        "command": shlex.join(command),
        "markdown_path": str(markdown_path),
        "cover": clean_text(cover),
        "output": output or "同步完成，CLI 未返回额外日志。",
    }
