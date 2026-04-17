"""LlamaRAG 异步任务：按知识库关联行执行解析（parsed_md）或入库（向量库）."""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llamarag.parse.pipeline import parse_file_to_parsed_md
from models.FileManagementModel import FileAssetModel, FileParseStatus
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


async def run_kb_file_index_job(
    session: AsyncSession,
    *,
    kb_id: int,
    file_id: int,
    owner_user_id: int,
) -> None:
    """消费一条入库任务：状态须为 ``QUEUED``，再经 ``INDEXING`` → Milvus / Postgres。"""
    from services.controllers.knowledge_base_controller import _ingest_kb_file_persist

    stmt = select(KnowledgeBaseFileModel).where(
        KnowledgeBaseFileModel.owner_user_id == owner_user_id,
        KnowledgeBaseFileModel.knowledge_base_id == kb_id,
        KnowledgeBaseFileModel.file_id == file_id,
    )
    res = await session.execute(stmt)
    kb_file = res.scalar_one_or_none()
    if kb_file is None:
        logger.warning(
            "kb index job: 无关联行 kb_id=%s file_id=%s owner=%s",
            kb_id,
            file_id,
            owner_user_id,
        )
        return

    if kb_file.pipeline_status != KbFilePipelineStatus.QUEUED:
        logger.info(
            "kb index job skip（非 QUEUED）status=%s kb_id=%s file_id=%s",
            kb_file.pipeline_status,
            kb_id,
            file_id,
        )
        return

    asset = await session.get(FileAssetModel, file_id)
    if asset is None or int(asset.owner_user_id) != int(owner_user_id) or asset.is_deleted:
        logger.warning("kb index job: 文件无效 file_id=%s", file_id)
        kb_file.pipeline_status = KbFilePipelineStatus.FAILED
        kb_file.pipeline_error = "文件不存在或无权访问"
        await session.commit()
        return

    if asset.parse_status != FileParseStatus.PARSED or not (asset.parsed_md_storage_key or "").strip():
        kb_file.pipeline_status = KbFilePipelineStatus.FAILED
        kb_file.pipeline_error = "解析产物不可用，请重新解析"
        await session.commit()
        return

    kb_file.pipeline_status = KbFilePipelineStatus.INDEXING
    kb_file.pipeline_error = None
    await session.commit()
    await session.refresh(kb_file)

    chunk = await _ingest_kb_file_persist(
        session,
        kb_file,
        asset,
        owner_user_id=owner_user_id,
        kb_id=kb_id,
        file_id=file_id,
    )
    if chunk is None:
        logger.warning("kb index job 入库失败 kb_id=%s file_id=%s", kb_id, file_id)
