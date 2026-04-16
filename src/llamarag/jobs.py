"""LlamaRAG 异步任务：按知识库关联行执行解析（parsed_md）."""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llamarag.parse.pipeline import parse_file_to_parsed_md
from models.FileManagementModel import FileAssetModel
from models.KnowledgeBaseModel import KbFilePipelineStatus, KnowledgeBaseFileModel

logger = logging.getLogger(__name__)


async def run_kb_file_parse_job(
    session: AsyncSession,
    *,
    kb_file_id: int,
    expected_owner_user_id: int,
) -> None:
    """消费一条解析任务：校验归属后执行 ``parse_file_to_parsed_md``；失败则 ``FAILED``。"""
    stmt = (
        select(KnowledgeBaseFileModel, FileAssetModel)
        .join(FileAssetModel, FileAssetModel.id == KnowledgeBaseFileModel.file_id)
        .where(
            KnowledgeBaseFileModel.id == kb_file_id,
            FileAssetModel.is_deleted.is_(False),
        )
    )
    res = await session.execute(stmt)
    row = res.first()
    if row is None:
        logger.warning("kb parse job: knowledge_base_file id=%s 不存在", kb_file_id)
        return

    kb_file, _asset = row
    if int(kb_file.owner_user_id) != int(expected_owner_user_id):
        logger.warning(
            "kb parse job: owner 不匹配 kb_file_id=%s expected=%s got=%s",
            kb_file_id,
            expected_owner_user_id,
            kb_file.owner_user_id,
        )
        return

    file_id = int(kb_file.file_id)
    try:
        await parse_file_to_parsed_md(
            session,
            owner_user_id=expected_owner_user_id,
            file_id=file_id,
        )
    except HTTPException as exc:
        await session.rollback()
        kb_row = await session.get(KnowledgeBaseFileModel, kb_file_id)
        if kb_row is not None:
            kb_row.pipeline_status = KbFilePipelineStatus.FAILED
            detail = exc.detail
            kb_row.pipeline_error = (detail if isinstance(detail, str) else str(detail))[:2000]
            await session.commit()
    except Exception as exc:
        logger.exception("kb parse job 未预期异常 kb_file_id=%s", kb_file_id)
        await session.rollback()
        kb_row = await session.get(KnowledgeBaseFileModel, kb_file_id)
        if kb_row is not None:
            kb_row.pipeline_status = KbFilePipelineStatus.FAILED
            kb_row.pipeline_error = str(exc)[:2000]
            await session.commit()
