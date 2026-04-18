"""metadata 抽取配置控制器。"""

from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.BasicModel import beijing_now
from models.KnowledgeBaseModel import KnowledgeBaseModel
from models.MetadataFieldModel import MetadataFieldAliasModel, MetadataFieldModel


async def _ensure_owned_kb(
    session: AsyncSession,
    *,
    owner_user_id: int,
    knowledge_base_id: int | None,
) -> None:
    if knowledge_base_id is None:
        return
    kb = await session.get(KnowledgeBaseModel, knowledge_base_id)
    if kb is None or kb.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")


def _norm_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _norm_field_key(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="field_key 不能为空",
        )
    return text


def _require_non_blank(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} 不能为空",
        )
    return text


async def _get_owned_field_or_404(
    session: AsyncSession,
    *,
    owner_user_id: int,
    field_id: int,
) -> MetadataFieldModel:
    row = await session.get(MetadataFieldModel, field_id)
    if row is None or row.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="metadata 字段配置不存在")
    return row


async def _get_owned_alias_or_404(
    session: AsyncSession,
    *,
    owner_user_id: int,
    alias_id: int,
) -> tuple[MetadataFieldAliasModel, MetadataFieldModel]:
    alias = await session.get(MetadataFieldAliasModel, alias_id)
    if alias is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="metadata 字段别名不存在")
    field = await session.get(MetadataFieldModel, alias.field_id)
    if field is None or field.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="metadata 字段别名不存在")
    return alias, field


async def list_aliases_by_field_ids_owned(
    session: AsyncSession,
    *,
    field_ids: list[int],
) -> dict[int, list[MetadataFieldAliasModel]]:
    if not field_ids:
        return {}
    stmt = (
        select(MetadataFieldAliasModel)
        .where(MetadataFieldAliasModel.field_id.in_(field_ids))
        .order_by(
            MetadataFieldAliasModel.priority.asc(),
            MetadataFieldAliasModel.id.asc(),
        )
    )
    res = await session.execute(stmt)
    mapping: dict[int, list[MetadataFieldAliasModel]] = {}
    for row in res.scalars().all():
        mapping.setdefault(int(row.field_id), []).append(row)
    return mapping


async def list_metadata_fields_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    biz_code: str | None,
    knowledge_base_id: int | None,
    status_filter: int | None,
) -> list[MetadataFieldModel]:
    biz_code = _norm_text(biz_code)
    await _ensure_owned_kb(
        session,
        owner_user_id=owner_user_id,
        knowledge_base_id=knowledge_base_id,
    )
    stmt = select(MetadataFieldModel).where(MetadataFieldModel.owner_user_id == owner_user_id)
    if biz_code is None:
        stmt = stmt.where(MetadataFieldModel.biz_code.is_(None))
    else:
        stmt = stmt.where(MetadataFieldModel.biz_code == biz_code.strip())
    if knowledge_base_id is None:
        stmt = stmt.where(MetadataFieldModel.knowledge_base_id.is_(None))
    else:
        stmt = stmt.where(MetadataFieldModel.knowledge_base_id == knowledge_base_id)
    if status_filter is not None:
        stmt = stmt.where(MetadataFieldModel.status == status_filter)
    stmt = stmt.order_by(MetadataFieldModel.priority.asc(), MetadataFieldModel.id.asc())
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def create_metadata_field_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    operator_name: str,
    biz_code: str | None,
    knowledge_base_id: int | None,
    field_key: str,
    field_name: str,
    value_type,
    extract_mode,
    status_value: int,
    priority: int,
    aliases: list[dict[str, object]],
) -> MetadataFieldModel:
    await _ensure_owned_kb(
        session,
        owner_user_id=owner_user_id,
        knowledge_base_id=knowledge_base_id,
    )
    now = beijing_now()
    row = MetadataFieldModel(
        owner_user_id=owner_user_id,
        biz_code=_norm_text(biz_code),
        knowledge_base_id=knowledge_base_id,
        field_key=_norm_field_key(field_key),
        field_name=_require_non_blank(field_name, field_name="field_name"),
        value_type=value_type,
        extract_mode=extract_mode,
        status=status_value,
        priority=priority,
        create_by=operator_name,
        update_by=operator_name,
        created_at=now,
        updated_at=now,
    )
    try:
        session.add(row)
        await session.flush()

        for alias in aliases:
            alias_text = _norm_text(str(alias["alias_text"]))
            if not alias_text:
                continue
            session.add(
                MetadataFieldAliasModel(
                    field_id=int(row.id),
                    alias_text=alias_text,
                    match_mode=alias.get("match_mode"),
                    status=int(alias.get("status", 1)),
                    priority=int(alias.get("priority", 100)),
                    create_by=operator_name,
                    update_by=operator_name,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="metadata 字段或别名已存在") from exc
    await session.refresh(row)
    return row


async def update_metadata_field_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    operator_name: str,
    field_id: int,
    patch: dict[str, object],
) -> MetadataFieldModel:
    row = await _get_owned_field_or_404(session, owner_user_id=owner_user_id, field_id=field_id)

    if "knowledge_base_id" in patch:
        await _ensure_owned_kb(
            session,
            owner_user_id=owner_user_id,
            knowledge_base_id=patch.get("knowledge_base_id"),
        )

    if "biz_code" in patch:
        row.biz_code = _norm_text(patch.get("biz_code"))
    if "knowledge_base_id" in patch:
        row.knowledge_base_id = patch.get("knowledge_base_id")
    if "field_key" in patch and patch.get("field_key") is not None:
        row.field_key = _norm_field_key(str(patch["field_key"]))
    if "field_name" in patch and patch.get("field_name") is not None:
        row.field_name = _require_non_blank(str(patch["field_name"]), field_name="field_name")
    if "value_type" in patch and patch.get("value_type") is not None:
        row.value_type = patch["value_type"]
    if "extract_mode" in patch and patch.get("extract_mode") is not None:
        row.extract_mode = patch["extract_mode"]
    if "status" in patch and patch.get("status") is not None:
        row.status = int(patch["status"])
    if "priority" in patch and patch.get("priority") is not None:
        row.priority = int(patch["priority"])
    row.update_by = operator_name
    row.updated_at = beijing_now()
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="metadata 字段配置冲突") from exc
    await session.refresh(row)
    return row


async def delete_metadata_field_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    field_id: int,
) -> None:
    row = await _get_owned_field_or_404(session, owner_user_id=owner_user_id, field_id=field_id)
    await session.execute(delete(MetadataFieldAliasModel).where(MetadataFieldAliasModel.field_id == row.id))
    await session.delete(row)
    await session.commit()


async def list_field_aliases_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    field_id: int,
) -> list[MetadataFieldAliasModel]:
    await _get_owned_field_or_404(session, owner_user_id=owner_user_id, field_id=field_id)
    stmt = (
        select(MetadataFieldAliasModel)
        .where(MetadataFieldAliasModel.field_id == field_id)
        .order_by(MetadataFieldAliasModel.priority.asc(), MetadataFieldAliasModel.id.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def create_field_alias_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    operator_name: str,
    field_id: int,
    alias_text: str,
    match_mode,
    status_value: int,
    priority: int,
) -> MetadataFieldAliasModel:
    await _get_owned_field_or_404(session, owner_user_id=owner_user_id, field_id=field_id)
    now = beijing_now()
    row = MetadataFieldAliasModel(
        field_id=field_id,
        alias_text=_norm_text(alias_text) or "",
        match_mode=match_mode,
        status=status_value,
        priority=priority,
        create_by=operator_name,
        update_by=operator_name,
        created_at=now,
        updated_at=now,
    )
    if not row.alias_text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="alias_text 不能为空")
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="metadata 字段别名已存在") from exc
    await session.refresh(row)
    return row


async def update_field_alias_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    operator_name: str,
    alias_id: int,
    patch: dict[str, object],
) -> MetadataFieldAliasModel:
    row, _field = await _get_owned_alias_or_404(session, owner_user_id=owner_user_id, alias_id=alias_id)
    if "alias_text" in patch and patch.get("alias_text") is not None:
        alias_text = _norm_text(str(patch["alias_text"]))
        if not alias_text:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="alias_text 不能为空")
        row.alias_text = alias_text
    if "match_mode" in patch and patch.get("match_mode") is not None:
        row.match_mode = patch["match_mode"]
    if "status" in patch and patch.get("status") is not None:
        row.status = int(patch["status"])
    if "priority" in patch and patch.get("priority") is not None:
        row.priority = int(patch["priority"])
    row.update_by = operator_name
    row.updated_at = beijing_now()
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="metadata 字段别名冲突") from exc
    await session.refresh(row)
    return row


async def delete_field_alias_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    alias_id: int,
) -> None:
    row, _field = await _get_owned_alias_or_404(session, owner_user_id=owner_user_id, alias_id=alias_id)
    await session.delete(row)
    await session.commit()
