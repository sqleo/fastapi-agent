"""实体候选审核控制器：分页查询 + approve/reject/merge。"""

from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.BasicModel import beijing_now
from models.EntityDictionaryModel import (
    CandidateStatus,
    EntityAliasModel,
    EntityCandidateModel,
    EntityDictionaryModel,
    EntityType,
)


def _norm_entity_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def _clean_text(text: str | None) -> str | None:
    if text is None:
        return None
    v = text.strip()
    return v or None


async def _get_owned_candidate_or_404(
    session: AsyncSession,
    *,
    owner_user_id: int,
    candidate_id: int,
) -> EntityCandidateModel:
    row = await session.get(EntityCandidateModel, candidate_id)
    if row is None or int(row.owner_user_id) != int(owner_user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选实体不存在")
    return row


async def list_entity_candidates_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    page: int,
    page_size: int,
    status_filter: CandidateStatus | None,
    biz_code: str | None,
    knowledge_base_id: int | None,
    file_id: int | None,
    keyword: str | None,
) -> tuple[int, list[EntityCandidateModel]]:
    biz_code = _clean_text(biz_code)
    kw = _clean_text(keyword)

    conditions = [EntityCandidateModel.owner_user_id == owner_user_id]
    if status_filter is not None:
        conditions.append(EntityCandidateModel.status == status_filter)
    if biz_code is not None:
        conditions.append(EntityCandidateModel.biz_code == biz_code)
    if knowledge_base_id is not None:
        conditions.append(EntityCandidateModel.knowledge_base_id == knowledge_base_id)
    if file_id is not None:
        conditions.append(EntityCandidateModel.file_id == file_id)
    if kw:
        conditions.append(EntityCandidateModel.candidate_text.ilike(f"%{kw}%"))

    total_stmt = select(func.count()).select_from(EntityCandidateModel).where(*conditions)
    total = int((await session.execute(total_stmt)).scalar_one() or 0)

    stmt = (
        select(EntityCandidateModel)
        .where(*conditions)
        .order_by(EntityCandidateModel.updated_at.desc(), EntityCandidateModel.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return total, rows


async def list_target_entities_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    biz_code: str | None,
    knowledge_base_id: int | None,
    entity_type: EntityType | None,
    keyword: str | None,
    limit: int,
) -> tuple[int, list[EntityDictionaryModel]]:
    biz_code = _clean_text(biz_code)
    kw = _clean_text(keyword)

    conditions = [
        EntityDictionaryModel.owner_user_id == owner_user_id,
        EntityDictionaryModel.status == 1,
    ]
    if biz_code is not None:
        conditions.append(EntityDictionaryModel.biz_code == biz_code)
    if knowledge_base_id is not None:
        conditions.append(EntityDictionaryModel.knowledge_base_id == knowledge_base_id)
    if entity_type is not None:
        conditions.append(EntityDictionaryModel.entity_type == entity_type)
    if kw:
        conditions.append(EntityDictionaryModel.canonical_name.ilike(f"%{kw}%"))

    total_stmt = select(func.count()).select_from(EntityDictionaryModel).where(*conditions)
    total = int((await session.execute(total_stmt)).scalar_one() or 0)

    stmt = (
        select(EntityDictionaryModel)
        .where(*conditions)
        .order_by(
            EntityDictionaryModel.priority.asc(),
            EntityDictionaryModel.updated_at.desc(),
            EntityDictionaryModel.id.desc(),
        )
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return total, rows


async def _find_or_create_entity(
    session: AsyncSession,
    *,
    owner_user_id: int,
    biz_code: str | None,
    knowledge_base_id: int | None,
    entity_type: EntityType,
    canonical_name: str,
    reviewer_name: str,
) -> EntityDictionaryModel:
    normalized = _norm_entity_text(canonical_name)
    stmt = select(EntityDictionaryModel).where(
        EntityDictionaryModel.owner_user_id == owner_user_id,
        EntityDictionaryModel.biz_code == biz_code,
        EntityDictionaryModel.knowledge_base_id == knowledge_base_id,
        EntityDictionaryModel.entity_type == entity_type,
        EntityDictionaryModel.normalized_name == normalized,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    row = EntityDictionaryModel(
        owner_user_id=owner_user_id,
        biz_code=biz_code,
        knowledge_base_id=knowledge_base_id,
        entity_type=entity_type,
        canonical_name=canonical_name,
        normalized_name=normalized,
        source="candidate_approved",
        create_by=reviewer_name,
        update_by=reviewer_name,
        created_at=beijing_now(),
        updated_at=beijing_now(),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        # 并发场景兜底重查
        retry = (await session.execute(stmt)).scalar_one_or_none()
        if retry is None:
            raise
        return retry
    return row


async def _ensure_alias(
    session: AsyncSession,
    *,
    entity_id: int,
    owner_user_id: int,
    biz_code: str | None,
    knowledge_base_id: int | None,
    alias_text: str,
    reviewer_name: str,
) -> None:
    alias_text = alias_text.strip()
    if not alias_text:
        return
    normalized = _norm_entity_text(alias_text)
    stmt = select(EntityAliasModel).where(
        EntityAliasModel.owner_user_id == owner_user_id,
        EntityAliasModel.biz_code == biz_code,
        EntityAliasModel.knowledge_base_id == knowledge_base_id,
        EntityAliasModel.entity_id == entity_id,
        EntityAliasModel.alias_normalized == normalized,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        if row.status != 1:
            row.status = 1
            row.update_by = reviewer_name
            row.updated_at = beijing_now()
        return

    session.add(
        EntityAliasModel(
            entity_id=entity_id,
            owner_user_id=owner_user_id,
            biz_code=biz_code,
            knowledge_base_id=knowledge_base_id,
            alias=alias_text,
            alias_normalized=normalized,
            match_mode="contains",
            weight=100,
            status=1,
            create_by=reviewer_name,
            update_by=reviewer_name,
            created_at=beijing_now(),
            updated_at=beijing_now(),
        )
    )


async def approve_entity_candidate_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    reviewer_user_id: int,
    reviewer_name: str,
    candidate_id: int,
    canonical_name: str | None,
    entity_type: EntityType | None,
    aliases: list[str],
    review_comment: str | None,
) -> EntityCandidateModel:
    row = await _get_owned_candidate_or_404(session, owner_user_id=owner_user_id, candidate_id=candidate_id)
    if row.status not in {CandidateStatus.PENDING, CandidateStatus.REJECTED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前状态不允许审核通过")

    final_name = _clean_text(canonical_name) or row.candidate_text.strip()
    if not final_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="canonical_name 不能为空")
    final_type = entity_type or row.entity_type or EntityType.OTHER

    entity = await _find_or_create_entity(
        session,
        owner_user_id=owner_user_id,
        biz_code=row.biz_code,
        knowledge_base_id=row.knowledge_base_id,
        entity_type=final_type,
        canonical_name=final_name,
        reviewer_name=reviewer_name,
    )
    await _ensure_alias(
        session,
        entity_id=int(entity.id),
        owner_user_id=owner_user_id,
        biz_code=row.biz_code,
        knowledge_base_id=row.knowledge_base_id,
        alias_text=row.candidate_text,
        reviewer_name=reviewer_name,
    )
    for alias in aliases:
        if _clean_text(alias):
            await _ensure_alias(
                session,
                entity_id=int(entity.id),
                owner_user_id=owner_user_id,
                biz_code=row.biz_code,
                knowledge_base_id=row.knowledge_base_id,
                alias_text=alias,
                reviewer_name=reviewer_name,
            )

    row.status = CandidateStatus.APPROVED
    row.entity_type = final_type
    row.reviewer_user_id = reviewer_user_id
    row.reviewed_at = beijing_now()
    row.review_comment = _clean_text(review_comment)
    row.approved_entity_id = int(entity.id)
    row.update_by = reviewer_name
    row.updated_at = beijing_now()

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="审核通过写入冲突") from exc
    await session.refresh(row)
    return row


async def reject_entity_candidate_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    reviewer_user_id: int,
    reviewer_name: str,
    candidate_id: int,
    review_comment: str | None,
) -> EntityCandidateModel:
    row = await _get_owned_candidate_or_404(session, owner_user_id=owner_user_id, candidate_id=candidate_id)
    if row.status not in {CandidateStatus.PENDING, CandidateStatus.APPROVED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前状态不允许驳回")

    row.status = CandidateStatus.REJECTED
    row.reviewer_user_id = reviewer_user_id
    row.reviewed_at = beijing_now()
    row.review_comment = _clean_text(review_comment)
    row.approved_entity_id = None
    row.update_by = reviewer_name
    row.updated_at = beijing_now()

    await session.commit()
    await session.refresh(row)
    return row


async def merge_entity_candidate_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    reviewer_user_id: int,
    reviewer_name: str,
    candidate_id: int,
    target_entity_id: int,
    review_comment: str | None,
) -> EntityCandidateModel:
    row = await _get_owned_candidate_or_404(session, owner_user_id=owner_user_id, candidate_id=candidate_id)
    if row.status not in {CandidateStatus.PENDING, CandidateStatus.APPROVED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前状态不允许合并")

    entity = await session.get(EntityDictionaryModel, target_entity_id)
    if entity is None or int(entity.owner_user_id) != int(owner_user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标正式实体不存在")
    if entity.biz_code != row.biz_code or entity.knowledge_base_id != row.knowledge_base_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="目标正式实体与候选作用域不一致")

    await _ensure_alias(
        session,
        entity_id=int(entity.id),
        owner_user_id=owner_user_id,
        biz_code=row.biz_code,
        knowledge_base_id=row.knowledge_base_id,
        alias_text=row.candidate_text,
        reviewer_name=reviewer_name,
    )

    row.status = CandidateStatus.MERGED
    row.reviewer_user_id = reviewer_user_id
    row.reviewed_at = beijing_now()
    row.review_comment = _clean_text(review_comment)
    row.approved_entity_id = int(entity.id)
    row.update_by = reviewer_name
    row.updated_at = beijing_now()

    await session.commit()
    await session.refresh(row)
    return row
