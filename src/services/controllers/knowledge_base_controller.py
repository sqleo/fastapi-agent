"""知识库业务逻辑：创建库、文件加入/移出、库内文件列表."""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from configs.env import env_config
from llamarag.ingestion.index_kb_file import index_parsed_md_for_kb_file_sync
from models.BasicModel import beijing_now
from models.FileManagementModel import FileAssetModel, FileParseStatus
from models.KnowledgeBaseModel import (
    KbFilePipelineStatus,
    KnowledgeBaseFileModel,
    KnowledgeBaseModel,
)

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


async def _validate_kb_file_for_index(
    session: AsyncSession,
    *,
    owner_user_id: int,
    kb_id: int,
    file_id: int,
) -> tuple[KnowledgeBaseFileModel, FileAssetModel]:
    """入库前校验：归属、解析产物、流水线状态（含「已在队列中」冲突）。"""
    await _get_owned_kb_or_404(session, owner_user_id=owner_user_id, kb_id=kb_id)

    kb_stmt = select(KnowledgeBaseFileModel).where(
        KnowledgeBaseFileModel.owner_user_id == owner_user_id,
        KnowledgeBaseFileModel.knowledge_base_id == kb_id,
        KnowledgeBaseFileModel.file_id == file_id,
    )
    kb_res = await session.execute(kb_stmt)
    kb_file = kb_res.scalar_one_or_none()
    if kb_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件未加入该知识库")

    asset = await session.get(FileAssetModel, file_id)
    if asset is None or asset.owner_user_id != owner_user_id or asset.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    if asset.parse_status != FileParseStatus.PARSED or not (asset.parsed_md_storage_key or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文件尚未解析为中间 Markdown，请先调用解析接口",
        )

    ps = kb_file.pipeline_status
    if ps == KbFilePipelineStatus.INDEXING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该文件正在入库中，请稍后再试",
        )
    if ps == KbFilePipelineStatus.QUEUED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已在入库队列中，请稍后查询状态",
        )
    if ps == KbFilePipelineStatus.PENDING_MD:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="流水线状态为 pending_md，请确认文件已解析并重新加入知识库",
        )
    return kb_file, asset


async def _ingest_kb_file_persist(
    session: AsyncSession,
    kb_file: KnowledgeBaseFileModel,
    asset: FileAssetModel,
    *,
    owner_user_id: int,
    kb_id: int,
    file_id: int,
) -> int | None:
    """当前行已为 ``INDEXING`` 且已 commit；执行分块入库，成功返回 chunk 数，失败写 ``FAILED`` 并返回 ``None``。"""
    try:
        chunk_count = await asyncio.to_thread(
            index_parsed_md_for_kb_file_sync,
            owner_user_id=owner_user_id,
            kb_id=kb_id,
            file_id=file_id,
            kb_file_id=int(kb_file.id),
            parsed_md_storage_key=asset.parsed_md_storage_key or "",
            semver_major=int(asset.semver_major),
            semver_minor=int(asset.semver_minor),
            semver_patch=int(asset.semver_patch),
        )
    except Exception as exc:
        logger.exception("知识库文件入库失败 kb_id=%s file_id=%s", kb_id, file_id)
        err_msg = str(exc)[:2000]
        kb_file.pipeline_status = KbFilePipelineStatus.FAILED
        kb_file.pipeline_error = err_msg
        await session.commit()
        await session.refresh(kb_file)
        return None

    now = beijing_now()
    kb_file.pipeline_status = KbFilePipelineStatus.INDEXED
    kb_file.pipeline_error = None
    kb_file.chunk_count = chunk_count
    kb_file.indexed_at = now
    kb_file.indexed_semver_major = int(asset.semver_major)
    kb_file.indexed_semver_minor = int(asset.semver_minor)
    kb_file.indexed_semver_patch = int(asset.semver_patch)

    asset.last_indexed_at = now

    await session.commit()
    await session.refresh(kb_file)
    return chunk_count


async def enqueue_kb_file_index_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    kb_id: int,
    file_id: int,
) -> KnowledgeBaseFileModel:
    """校验后将流水线置为 ``QUEUED`` 并投递 Taskiq（Redis）；需配置 ``REDIS_URI``。"""
    kb_file, _asset = await _validate_kb_file_for_index(
        session,
        owner_user_id=owner_user_id,
        kb_id=kb_id,
        file_id=file_id,
    )
    redis_url = (env_config.redis_uri or "").strip()
    if not redis_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未配置 REDIS_URI，无法入队；请配置后启动 Taskiq Worker",
        )

    kb_file.pipeline_status = KbFilePipelineStatus.QUEUED
    kb_file.pipeline_error = None
    await session.commit()
    await session.refresh(kb_file)

    from llamarag.queue.ingest_queue import push_kb_index_job

    await push_kb_index_job(
        redis_url,
        kb_id=kb_id,
        file_id=file_id,
        owner_user_id=owner_user_id,
    )
    return kb_file


async def search_knowledge_base_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    kb_id: int,
    query: str,
    top_k: int,
) -> str:
    """知识库内向量检索（待在 llamarag 中重新实现）。"""
    logger.debug(
        "search_knowledge_base_owned stub kb_id=%s top_k=%s q=%r",
        kb_id,
        top_k,
        query[:200] if query else "",
    )
    await _get_owned_kb_or_404(session, owner_user_id=owner_user_id, kb_id=kb_id)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="知识库向量检索尚未实现，请在 llamarag 接入向量存储后重试。",
    )
