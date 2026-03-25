"""富文档：MinerU 提取 Markdown + 图片落盘；可用 LLM 结合上下文生成 ``![描述](…)`` 并入库。"""

from __future__ import annotations

import asyncio
import mimetypes
import re
from pathlib import Path, PurePosixPath
from typing import Any

from mineru import MinerU
from sqlalchemy.ext.asyncio import AsyncSession

from configs.env import env_config
from ingestion.image_alt_llm import enrich_markdown_image_alts_with_llm
from ingestion.parsers.base import DocumentToMarkdownParser
from models.KbExtractedImageModel import KbExtractedImageModel

# src/ingestion/parsers/rich_document_parser.py → 项目根
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# MinerU 默认正文里为 ![](images/xxx.jpg) 或 ![](images/sub/xxx.jpg)
_MINERU_IMAGE_MD_RE = re.compile(
    r"!\[([^\]]*)\]\(\s*(?:\./)?images/([^)\s]+)\s*\)",
    re.MULTILINE,
)


def _clean_parsed_markdown(text: str) -> str:
    """规范化 MinerU 输出：去 BOM、统一换行、去行尾空白、压缩多余空行。"""
    if not text:
        return ""
    t = text.replace("\ufeff", "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in t.split("\n")]
    t = "\n".join(lines)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _guess_mime(filename: str) -> str | None:
    mime, _ = mimetypes.guess_type(filename)
    return mime


def _mineru_extract_write_images_rewrite_md(
    path: Path,
    markdown_out_path: Path | None,
) -> tuple[str, list[dict[str, Any]]]:
    """同步：调用 MinerU、落盘图片、改写 Markdown；返回 (正文, 待入库行 dict 列表)。"""
    client = MinerU(token=env_config.mineru_token)
    client.set_source("fastapi-agent")
    result = client.extract(
        str(path),
        language="ch",
        timeout=1200,
        ocr=True,
        formula=True,
        table=True,
    )
    state = getattr(result, "state", None)
    if state != "done":
        err = getattr(result, "error", None)
        raise ValueError(f"MinerU 解析未完成: state={state}, error={err}")

    md = result.markdown or ""
    pending: list[dict[str, Any]] = []
    images = getattr(result, "images", None) or []

    if not images:
        return _clean_parsed_markdown(md), pending

    if markdown_out_path is None:
        raise ValueError("解析结果包含图片时必须提供 markdown_out_path，用于落盘与链接改写")

    md_out = markdown_out_path.expanduser().resolve()
    asset_stem = f"{md_out.stem}_assets"
    images_dir = md_out.parent / asset_stem / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    url_prefix = f"{asset_stem}/images"

    seen_names: set[str] = set()
    for img in images:
        name = PurePosixPath(getattr(img, "path", "") or getattr(img, "name", "")).name
        if not name:
            name = str(getattr(img, "name", "") or "image.bin")
        target = images_dir / name
        data = getattr(img, "data", b"") or b""
        target.write_bytes(data)
        if name not in seen_names:
            seen_names.add(name)
            rel_storage = target.resolve().relative_to(_PROJECT_ROOT.resolve())
            pending.append(
                {
                    "storage_key": rel_storage.as_posix(),
                    "original_name": name,
                    "size_bytes": len(data),
                    "mime_type": _guess_mime(name),
                }
            )

    def _repl(m: re.Match[str]) -> str:
        fname = m.group(2).strip()
        new_url = f"{url_prefix}/{fname}"
        return f"![]({new_url})"

    md = _MINERU_IMAGE_MD_RE.sub(_repl, md)
    return _clean_parsed_markdown(md), pending


class UnstructuredRichDocumentParser(DocumentToMarkdownParser):
    async def to_markdown(
        self,
        path: Path,
        *,
        markdown_out_path: Path | None = None,
        **kwargs: Any,
    ) -> str:
        kb_file_id = kwargs.get("kb_file_id")
        if kb_file_id is not None and not isinstance(kb_file_id, int):
            raise TypeError("kb_file_id 须为 int 或 None")

        db_session = kwargs.get("db_session")
        if db_session is not None and not isinstance(db_session, AsyncSession):
            raise TypeError("db_session 须为 sqlalchemy.ext.asyncio.AsyncSession 或 None")

        md, pending = await asyncio.to_thread(
            _mineru_extract_write_images_rewrite_md,
            path,
            markdown_out_path,
        )

        fname_to_alt: dict[str, str] = {}
        if pending and not kwargs.get("skip_image_alt_llm", False):
            md, fname_to_alt = await enrich_markdown_image_alts_with_llm(
                md,
                platform_code="deepseek",
            )

        if pending and db_session is not None and kb_file_id is not None:
            for row in pending:
                db_session.add(
                    KbExtractedImageModel(
                        kb_file_id=kb_file_id,
                        storage_key=row["storage_key"][:1024],
                        original_name=row["original_name"][:512],
                        size_bytes=row.get("size_bytes"),
                        mime_type=(row.get("mime_type") or "")[:128] or None,
                        alt_text=fname_to_alt.get(row["original_name"]),
                    )
                )
            await db_session.flush()

        return md
