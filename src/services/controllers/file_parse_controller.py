"""将已上传文件解析为 ``static/parsed_md/`` 中间 Markdown（当前仅 Markdown 源）."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.FileManagementModel import (
    PARSED_MD_STORAGE_PREFIX,
    FileAssetModel,
    FileParseStatus,
)
from utils.content_semver import bump_patch_after_parse
from models.KnowledgeBaseModel import KbFilePipelineStatus, KnowledgeBaseFileModel
from parsing.exceptions import UnsupportedDocumentFormatError
from parsing.registry import get_intermediate_md_generator_for_ext


def _parsed_md_key(owner_user_id: int, file_id: int) -> str:
    return f"{PARSED_MD_STORAGE_PREFIX}/{owner_user_id}/{file_id}.md"


async def parse_file_to_intermediate_md_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    file_id: int,
) -> FileAssetModel:
    """校验归属后生成中间 Markdown，并更新 ``parsed_md_storage_key``；关联知识库条目置为可入队。"""
    row = await session.get(FileAssetModel, file_id)
    if row is None or row.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    if row.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    try:
        generator = get_intermediate_md_generator_for_ext(row.file_ext)
    except UnsupportedDocumentFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    source_abs = Path("static") / (row.storage_key or "").lstrip("/")
    if not await asyncio.to_thread(source_abs.is_file):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="源文件在磁盘上不存在，请重新上传",
        )

    key = _parsed_md_key(owner_user_id, file_id)
    dest_abs = Path("static") / key

    await generator.generate(source_path=source_abs, dest_path=dest_abs)

    row.parsed_md_storage_key = key
    m, mi, p = bump_patch_after_parse(row.semver_major, row.semver_minor, row.semver_patch)
    row.semver_major = m
    row.semver_minor = mi
    row.semver_patch = p
    row.parse_status = FileParseStatus.PARSED

    kb_stmt = select(KnowledgeBaseFileModel).where(
        KnowledgeBaseFileModel.owner_user_id == owner_user_id,
        KnowledgeBaseFileModel.file_id == file_id,
    )
    kb_res = await session.execute(kb_stmt)
    for kb in kb_res.scalars().all():
        kb.pipeline_status = KbFilePipelineStatus.READY_TO_INDEX
        kb.pipeline_error = None
        kb.indexed_at = None
        kb.chunk_count = None

    await session.commit()
    await session.refresh(row)
    return row
