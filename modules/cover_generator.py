from __future__ import annotations

import mimetypes
import random
import shutil
from pathlib import Path

from modules import image_generator, met_cover_provider
from modules.utils import PROJECT_ROOT, clean_text, ensure_directories, env_or_default


class CoverGenerationError(RuntimeError):
    pass


def _resolve_provider(provider: str | None) -> str:
    resolved = clean_text(provider) or clean_text(env_or_default("COVER_PROVIDER", "local"))
    return resolved or "local"


def _resolve_cover_library_dir() -> Path:
    raw_path = clean_text(env_or_default("COVER_LIBRARY_DIR", "assets/covers"))
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _save_selected_cover(source_path: Path, draft_id: int) -> Path:
    ensure_directories()
    suffix = source_path.suffix.lower() or ".png"
    target_path = PROJECT_ROOT / "exports" / "covers" / f"draft_{draft_id}_cover{suffix}"
    shutil.copy2(source_path, target_path)
    return target_path


def _generate_local_cover(draft_id: int) -> dict[str, object]:
    library_dir = _resolve_cover_library_dir()
    candidates = [
        path for path in sorted(library_dir.glob("*"))
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]
    if not candidates:
        raise CoverGenerationError(
            f"本地封面图库为空：{library_dir}。请先放入 png/jpg/jpeg/webp 图片。"
        )

    selected_source = random.SystemRandom().choice(candidates)
    selected_path = _save_selected_cover(selected_source, draft_id)
    image_bytes = selected_path.read_bytes()
    mime_type = mimetypes.guess_type(selected_path.name)[0] or "image/png"
    return {
        "provider": "local",
        "path": selected_path,
        "bytes": image_bytes,
        "source_path": selected_source,
        "data_uri": image_generator.build_image_data_uri(image_bytes, mime_type=mime_type),
    }


def _generate_openai_cover(
    draft_id: int,
    title: str,
    article_content: str,
    main_keyword: str,
    size: str,
    quality: str,
) -> dict[str, object]:
    prompt = image_generator.build_cover_prompt(
        title=title,
        article_content=article_content,
        main_keyword=main_keyword,
    )
    image_bytes = image_generator.generate_image(
        prompt=prompt,
        size=size,
        quality=quality,
    )
    filename = image_generator.build_cover_filename(draft_id)
    path = image_generator.save_cover_image(image_bytes, filename)
    return {
        "provider": "openai",
        "path": path,
        "bytes": image_bytes,
        "data_uri": image_generator.build_image_data_uri(image_bytes),
    }


def _generate_met_cover(
    draft_id: int,
    title: str,
    article_content: str,
    main_keyword: str,
    size: str,
) -> dict[str, object]:
    result = met_cover_provider.generate_met_cover(
        draft_id=draft_id,
        title=title,
        article_content=article_content,
        main_keyword=main_keyword,
        size=size,
    )
    return {
        **result,
        "data_uri": image_generator.build_image_data_uri(result["bytes"]),
    }


def generate_cover_asset(
    draft_id: int,
    title: str,
    article_content: str,
    main_keyword: str,
    provider: str | None = None,
    size: str = "1536x1024",
    quality: str = "medium",
) -> dict[str, object]:
    resolved_provider = _resolve_provider(provider)
    errors: list[str] = []

    if resolved_provider in {"local", "auto"}:
        try:
            return _generate_local_cover(draft_id=draft_id)
        except Exception as exc:
            errors.append(f"local: {exc}")
            if resolved_provider == "local":
                raise CoverGenerationError(str(exc)) from exc

    if resolved_provider in {"met", "auto"}:
        try:
            return _generate_met_cover(
                draft_id=draft_id,
                title=title,
                article_content=article_content,
                main_keyword=main_keyword,
                size=size,
            )
        except Exception as exc:
            errors.append(f"met: {exc}")
            if resolved_provider == "met":
                raise CoverGenerationError(str(exc)) from exc

    if resolved_provider in {"auto", "openai"}:
        try:
            return _generate_openai_cover(
                draft_id=draft_id,
                title=title,
                article_content=article_content,
                main_keyword=main_keyword,
                size=size,
                quality=quality,
            )
        except Exception as exc:
            errors.append(f"openai: {exc}")
            if resolved_provider == "openai":
                raise CoverGenerationError(str(exc)) from exc

    raise CoverGenerationError("；".join(errors) if errors else f"不支持的封面生成器：{resolved_provider}")
