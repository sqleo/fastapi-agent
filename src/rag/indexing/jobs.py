"""入库任务：同步执行与 worker 消费（异步 DB + 线程内 ingest）."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.BasicModel import beijing_now
from models.FileManagementModel import FileAssetModel
from models.KnowledgeBaseModel import KbFilePipelineStatus, KnowledgeBaseFileModel
from rag.contracts import IngestContext, IngestResult
from shared.embedding.config import EmbeddingConfig
from shared.embedding.exceptions import EmbeddingConfigurationError
from shared.embedding.provider import DatabaseEmbeddingSettingsProvider

logger = logging.getLogger(__name__)


def ingest_parsed_md_sync(
    ctx: IngestContext,
    embedding_config: EmbeddingConfig | None = None,
) -> IngestResult:
    """在线程中执行；捕获导入错误与未预期异常.

    ``embedding_config`` 由 worker 异步解析后传入可避免在线程内重复查库；省略时由 pipeline 按 ``owner_user_id`` 同步解析。
    """
    try:
        from rag.indexing.pipeline import ingest_parsed_md_for_kb_file
    except ImportError as exc:
        return IngestResult(ok=False, chunk_count=0, error_message=f"RAG 依赖未安装: {exc}")
    try:
        return ingest_parsed_md_for_kb_file(ctx, embedding_config=embedding_config)
    except Exception as exc:
        logger.exception("ingest_parsed_md_for_kb_file 未捕获异常")
        return IngestResult(ok=False, chunk_count=0, error_message=str(exc))


async def run_kb_file_ingest_job(
    session: AsyncSession,
    *,
    kb_file_id: int,
    expected_owner_user_id: int,
) -> None:
    """消费一条队列任务：校验归属 → ``INDEXING`` → 入库 → ``indexed`` / ``failed``。"""
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
        logger.warning("kb ingest job: knowledge_base_file id=%s 不存在", kb_file_id)
        return

    kb_file, asset = row
    if int(kb_file.owner_user_id) != int(expected_owner_user_id):
        logger.warning(
            "kb ingest job: owner 不匹配 kb_file_id=%s expected=%s got=%s",
            kb_file_id,
            expected_owner_user_id,
            kb_file.owner_user_id,
        )
        return

    parsed_key = (asset.parsed_md_storage_key or "").strip()
    if not parsed_key:
        kb_file.pipeline_status = KbFilePipelineStatus.FAILED
        kb_file.pipeline_error = "无 parsed_md_storage_key，无法入库"
        await session.commit()
        return

    provider = DatabaseEmbeddingSettingsProvider()
    try:
        embedding_config = await provider.resolve(session, int(kb_file.owner_user_id))
    except EmbeddingConfigurationError as exc:
        kb_file.pipeline_status = KbFilePipelineStatus.FAILED
        kb_file.pipeline_error = str(exc)[:2000]
        await session.commit()
        return

    kb_file.pipeline_status = KbFilePipelineStatus.INDEXING
    kb_file.pipeline_error = None
    await session.commit()

    ctx = IngestContext(
        owner_user_id=int(kb_file.owner_user_id),
        knowledge_base_id=int(kb_file.knowledge_base_id),
        file_id=int(kb_file.file_id),
        kb_file_link_id=int(kb_file.id),
        parsed_md_storage_key=parsed_key,
    )

    ingest_result = await asyncio.to_thread(ingest_parsed_md_sync, ctx, embedding_config)

    kb_file = await session.get(KnowledgeBaseFileModel, kb_file_id)
    if kb_file is None:
        return

    if ingest_result.ok:
        kb_file.pipeline_status = KbFilePipelineStatus.INDEXED
        kb_file.chunk_count = ingest_result.chunk_count
        kb_file.indexed_at = beijing_now()
        kb_file.pipeline_error = None
        asset = await session.get(FileAssetModel, int(kb_file.file_id))
        if asset is not None:
            kb_file.indexed_semver_major = int(asset.semver_major)
            kb_file.indexed_semver_minor = int(asset.semver_minor)
            kb_file.indexed_semver_patch = int(asset.semver_patch)
    else:
        kb_file.pipeline_status = KbFilePipelineStatus.FAILED
        kb_file.pipeline_error = (ingest_result.error_message or "")[:2000]
    await session.commit()
