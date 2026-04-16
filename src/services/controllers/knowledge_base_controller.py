"""知识库业务逻辑：创建库、文件加入/移出、库内文件列表."""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
