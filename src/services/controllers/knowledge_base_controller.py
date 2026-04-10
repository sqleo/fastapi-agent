"""知识库业务逻辑：创建库、文件加入/移出、库内文件列表、触发布式入库."""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from configs.env import env_config
from models.FileManagementModel import FileAssetModel, FileParseStatus
from models.KnowledgeBaseModel import (
    KbFilePipelineStatus,
    KnowledgeBaseFileModel,
    KnowledgeBaseModel,
)
from rag.queue.ingest_queue import push_kb_ingest_jobs_batch
from rag.query.search import search_in_knowledge_base_formatted_async
from rag.stores.milvus_delete import delete_kb_file_vectors_sync
from schemas.knowledge_base_schema import KbFileIndexItemResult
from shared.embedding.config import FIXED_EMBEDDING_DIMENSION
from shared.embedding.exceptions import EmbeddingConfigurationError
from shared.embedding.provider import DatabaseEmbeddingSettingsProvider

logger = logging.getLogger(__name__)


async def _get_owned_kb_or_404(
    session: AsyncSession,
    *,
    owner_user_id: int,
    kb_id: int,
) -> KnowledgeBaseModel:
    row = await session.get(KnowledgeBaseModel, kb_id)
    if row is None or row.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    return row


async def create_knowledge_base_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    name: str,
    code: str | None,
    description: str | None,
    thumbnail_url: str | None,
) -> KnowledgeBaseModel:
    """创建当前用户的知识库。"""
    row = KnowledgeBaseModel(
        owner_user_id=owner_user_id,
        name=name.strip(),
        code=(code or "").strip() or None,
        description=description,
        thumbnail_url=(thumbnail_url or "").strip() or None,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="知识库名称已存在",
        ) from exc
    await session.refresh(row)
    return row


async def list_knowledge_bases_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
) -> list[KnowledgeBaseModel]:
    """查询当前用户的知识库列表。"""
    stmt = (
        select(KnowledgeBaseModel)
        .where(KnowledgeBaseModel.owner_user_id == owner_user_id)
        .order_by(KnowledgeBaseModel.created_at.desc(), KnowledgeBaseModel.id.desc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def add_files_to_knowledge_base_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    kb_id: int,
    file_ids: list[int],
) -> tuple[list[int], list[int]]:
    """批量将文件加入知识库，返回（生效列表，跳过列表）。"""
    await _get_owned_kb_or_404(session, owner_user_id=owner_user_id, kb_id=kb_id)

    uniq_ids = list(dict.fromkeys(file_ids))
    files_stmt = select(FileAssetModel.id).where(
        FileAssetModel.owner_user_id == owner_user_id,
        FileAssetModel.id.in_(uniq_ids),
        FileAssetModel.is_deleted.is_(False),
    )
    files_res = await session.execute(files_stmt)
    owned_file_ids = {int(x) for x in files_res.scalars().all()}
    if not owned_file_ids:
        return [], uniq_ids

    existing_stmt = select(KnowledgeBaseFileModel.file_id).where(
        KnowledgeBaseFileModel.owner_user_id == owner_user_id,
        KnowledgeBaseFileModel.knowledge_base_id == kb_id,
        KnowledgeBaseFileModel.file_id.in_(owned_file_ids),
    )
    existing_res = await session.execute(existing_stmt)
    existing_ids = {int(x) for x in existing_res.scalars().all()}

    candidate_ids = [fid for fid in uniq_ids if fid in owned_file_ids and fid not in existing_ids]
    skipped = [fid for fid in uniq_ids if fid not in owned_file_ids or fid in existing_ids]

    assets_by_id: dict[int, FileAssetModel] = {}
    if candidate_ids:
        assets_stmt = select(FileAssetModel).where(
            FileAssetModel.id.in_(candidate_ids),
            FileAssetModel.owner_user_id == owner_user_id,
        )
        assets_res = await session.execute(assets_stmt)
        assets_by_id = {int(a.id): a for a in assets_res.scalars().all()}

    to_insert: list[int] = []
    for fid in candidate_ids:
        asset = assets_by_id.get(fid)
        parsed_ok = asset is not None and asset.parse_status == FileParseStatus.PARSED
        parsed_ok = parsed_ok and bool((asset.parsed_md_storage_key or "").strip())
        if not parsed_ok:
            skipped.append(fid)
            continue
        to_insert.append(fid)

    if to_insert:
        for fid in to_insert:
            session.add(
                KnowledgeBaseFileModel(
                    owner_user_id=owner_user_id,
                    knowledge_base_id=kb_id,
                    file_id=fid,
                    pipeline_status=KbFilePipelineStatus.READY_TO_INDEX,
                )
            )
    await session.commit()
    return to_insert, skipped


async def remove_files_from_knowledge_base_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    kb_id: int,
    file_ids: list[int],
) -> tuple[list[int], list[int]]:
    """批量将文件移出知识库，返回（生效列表，跳过列表）。"""
    await _get_owned_kb_or_404(session, owner_user_id=owner_user_id, kb_id=kb_id)

    uniq_ids = list(dict.fromkeys(file_ids))
    rows_stmt = select(KnowledgeBaseFileModel).where(
        KnowledgeBaseFileModel.owner_user_id == owner_user_id,
        KnowledgeBaseFileModel.knowledge_base_id == kb_id,
        KnowledgeBaseFileModel.file_id.in_(uniq_ids),
    )
    rows_res = await session.execute(rows_stmt)
    rows = list(rows_res.scalars().all())
    hit_ids = {int(x.file_id) for x in rows}

    if rows:
        provider = DatabaseEmbeddingSettingsProvider()
        try:
            emb_cfg = await provider.resolve(session, owner_user_id)
            embed_dim = int(emb_cfg.dimensions)
        except EmbeddingConfigurationError:
            embed_dim = FIXED_EMBEDDING_DIMENSION

        for row in rows:
            try:
                await asyncio.to_thread(
                    delete_kb_file_vectors_sync,
                    kb_file_link_id=int(row.id),
                    dim=embed_dim,
                )
            except Exception as exc:
                logger.exception(
                    "移出知识库前删除 Milvus 向量失败 kb_file_id=%s",
                    row.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"向量库删除失败，文件未从知识库移出: {exc}"[:2000],
                ) from exc

    for row in rows:
        await session.delete(row)
    await session.commit()

    affected = [fid for fid in uniq_ids if fid in hit_ids]
    skipped = [fid for fid in uniq_ids if fid not in hit_ids]
    return affected, skipped


async def list_knowledge_base_files_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    kb_id: int,
    page: int,
    page_size: int,
) -> tuple[int, list[tuple[FileAssetModel, KnowledgeBaseFileModel]]]:
    """查询指定知识库下的文件分页列表（含关联行上的流水线状态）。"""
    await _get_owned_kb_or_404(session, owner_user_id=owner_user_id, kb_id=kb_id)

    base_filters = (
        KnowledgeBaseFileModel.owner_user_id == owner_user_id,
        KnowledgeBaseFileModel.knowledge_base_id == kb_id,
        FileAssetModel.is_deleted.is_(False),
        FileAssetModel.parse_status == FileParseStatus.PARSED,
        and_(
            FileAssetModel.parsed_md_storage_key.isnot(None),
            FileAssetModel.parsed_md_storage_key != "",
        ),
    )

    count_stmt = (
        select(func.count(FileAssetModel.id))
        .select_from(KnowledgeBaseFileModel)
        .join(FileAssetModel, FileAssetModel.id == KnowledgeBaseFileModel.file_id)
        .where(*base_filters)
    )
    count_res = await session.execute(count_stmt)
    total = int(count_res.scalar_one() or 0)

    offset = (page - 1) * page_size
    rows_stmt = (
        select(FileAssetModel, KnowledgeBaseFileModel)
        .select_from(KnowledgeBaseFileModel)
        .join(FileAssetModel, FileAssetModel.id == KnowledgeBaseFileModel.file_id)
        .where(*base_filters)
        .order_by(KnowledgeBaseFileModel.created_at.desc(), KnowledgeBaseFileModel.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows_res = await session.execute(rows_stmt)
    rows = list(rows_res.all())
    return total, rows


async def search_knowledge_base_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    kb_id: int,
    query: str,
    top_k: int,
) -> str:
    """校验知识库归属后，在库内向量检索（见 ``rag.query.search``）。"""
    await _get_owned_kb_or_404(session, owner_user_id=owner_user_id, kb_id=kb_id)

    try:
        return await search_in_knowledge_base_formatted_async(
            session,
            query.strip(),
            knowledge_base_id=kb_id,
            owner_user_id=owner_user_id,
            top_k=top_k,
        )
    except EmbeddingConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


async def enqueue_kb_file_indexing_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    kb_id: int,
    file_ids: list[int],
) -> list[KbFileIndexItemResult]:
    """将指定知识库下文件的入库任务写入 Redis，并把 ``pipeline_status`` 置为 ``queued``。"""
    await _get_owned_kb_or_404(session, owner_user_id=owner_user_id, kb_id=kb_id)

    redis_url = (env_config.redis_uri or "").strip()
    if not redis_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未配置 REDIS_URI，无法入队索引入库",
        )

    uniq_ids = list(dict.fromkeys(file_ids))

    stmt = (
        select(KnowledgeBaseFileModel, FileAssetModel)
        .join(FileAssetModel, FileAssetModel.id == KnowledgeBaseFileModel.file_id)
        .where(
            KnowledgeBaseFileModel.owner_user_id == owner_user_id,
            KnowledgeBaseFileModel.knowledge_base_id == kb_id,
            KnowledgeBaseFileModel.file_id.in_(uniq_ids),
            FileAssetModel.is_deleted.is_(False),
        )
    )
    res = await session.execute(stmt)
    rows_by_fid: dict[int, tuple[KnowledgeBaseFileModel, FileAssetModel]] = {
        int(r[0].file_id): (r[0], r[1]) for r in res.all()
    }

    out: list[KbFileIndexItemResult] = []
    to_queue: list[dict[str, int]] = []

    for fid in uniq_ids:
        pair = rows_by_fid.get(fid)
        if pair is None:
            out.append(KbFileIndexItemResult(
                file_id=fid, kb_file_id=None, ok=False,
                pipeline_status="not_in_kb", skipped_reason="not_in_kb",
            ))
            continue

        kb_file, asset = pair
        parsed_key = (asset.parsed_md_storage_key or "").strip()
        if not parsed_key:
            ps = kb_file.pipeline_status
            out.append(KbFileIndexItemResult(
                file_id=fid, kb_file_id=int(kb_file.id), ok=False,
                pipeline_status=ps.value if hasattr(ps, "value") else str(ps),
                skipped_reason="no_parsed_md",
            ))
            continue

        kb_file.pipeline_status = KbFilePipelineStatus.QUEUED
        kb_file.pipeline_error = None
        to_queue.append({"kb_file_id": int(kb_file.id), "owner_user_id": owner_user_id})
        out.append(KbFileIndexItemResult(
            file_id=fid, kb_file_id=int(kb_file.id), ok=True,
            pipeline_status=KbFilePipelineStatus.QUEUED.value,
        ))

    if to_queue:
        await session.commit()
        try:
            await push_kb_ingest_jobs_batch(redis_url, to_queue)
        except Exception as exc:
            logger.exception("Redis 批量入队失败")
            queued_kids = {item["kb_file_id"] for item in to_queue}
            for item in to_queue:
                kid = item["kb_file_id"]
                kb_file = await session.get(KnowledgeBaseFileModel, kid)
                if kb_file is not None:
                    kb_file.pipeline_status = KbFilePipelineStatus.FAILED
                    kb_file.pipeline_error = f"入队失败: {exc}"[:2000]
            await session.commit()
            err_msg = str(exc)[:2000]
            out = [
                KbFileIndexItemResult(
                    file_id=r.file_id, kb_file_id=r.kb_file_id,
                    ok=False,
                    pipeline_status=KbFilePipelineStatus.FAILED.value,
                    error=err_msg,
                ) if r.ok and r.kb_file_id in queued_kids else r
                for r in out
            ]

    return out
