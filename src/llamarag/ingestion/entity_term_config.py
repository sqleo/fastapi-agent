"""实体词项加载：按作用域读取正式实体及别名，供同步入库逻辑使用。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TypedDict

from sqlalchemy import case, select

from models.EntityDictionaryModel import EntityAliasModel, EntityDictionaryModel, EntityType
from utils.sql_db import async_session


class EntityTermItem(TypedDict):
    """实体词项：一个正式实体及其可匹配词。"""

    canonical_name: str
    terms: list[str]


def _scope_rank_case(model):
    return case(
        (model.knowledge_base_id.is_not(None), 0),
        (model.biz_code.is_not(None), 1),
        else_=2,
    )


async def _load_entity_terms_async(
    *,
    owner_user_id: int,
    entity_type: EntityType,
    knowledge_base_id: int | None,
    biz_code: str | None,
) -> list[EntityTermItem]:
    scope = [
        EntityDictionaryModel.owner_user_id == owner_user_id,
        EntityDictionaryModel.entity_type == entity_type,
        EntityDictionaryModel.status == 1,
    ]
    if knowledge_base_id is not None:
        scope.append(
            (EntityDictionaryModel.knowledge_base_id == knowledge_base_id)
            | (
                EntityDictionaryModel.knowledge_base_id.is_(None)
                & (
                    (EntityDictionaryModel.biz_code == biz_code)
                    | (EntityDictionaryModel.biz_code.is_(None))
                )
            )
        )
    elif biz_code is not None:
        scope.append(
            (EntityDictionaryModel.biz_code == biz_code) | (EntityDictionaryModel.biz_code.is_(None))
        )

    async with async_session() as session:
        entity_stmt = (
            select(EntityDictionaryModel)
            .where(*scope)
            .order_by(
                _scope_rank_case(EntityDictionaryModel),
                EntityDictionaryModel.priority.asc(),
                EntityDictionaryModel.id.asc(),
            )
        )
        entity_rows = list((await session.execute(entity_stmt)).scalars().all())
        if not entity_rows:
            return []

        selected: dict[str, EntityDictionaryModel] = {}
        ordered_ids: list[int] = []
        for row in entity_rows:
            normalized = str(row.normalized_name or "").strip()
            if not normalized or normalized in selected:
                continue
            selected[normalized] = row
            ordered_ids.append(int(row.id))

        alias_stmt = (
            select(EntityAliasModel)
            .where(
                EntityAliasModel.entity_id.in_(ordered_ids),
                EntityAliasModel.status == 1,
            )
            .order_by(EntityAliasModel.weight.desc(), EntityAliasModel.id.asc())
        )
        alias_rows = list((await session.execute(alias_stmt)).scalars().all())

    aliases_by_entity_id: dict[int, list[str]] = defaultdict(list)
    for row in alias_rows:
        alias = str(row.alias or "").strip()
        if alias:
            aliases_by_entity_id[int(row.entity_id)].append(alias)

    result: list[EntityTermItem] = []
    for row in selected.values():
        terms: list[str] = []
        seen: set[str] = set()
        canonical = str(row.canonical_name or "").strip()
        if canonical:
            terms.append(canonical)
            seen.add(canonical)
        for alias in aliases_by_entity_id.get(int(row.id), []):
            if alias not in seen:
                terms.append(alias)
                seen.add(alias)
        terms.sort(key=len, reverse=True)
        if terms:
            result.append(
                EntityTermItem(
                    canonical_name=canonical,
                    terms=terms,
                )
            )
    return result


def load_entity_terms_sync(
    *,
    owner_user_id: int | None,
    entity_type: EntityType,
    knowledge_base_id: int | None,
    biz_code: str | None,
) -> list[EntityTermItem]:
    """同步入口：供同步入库线程按作用域读取正式实体词项。"""
    if owner_user_id is None:
        return []
    try:
        return asyncio.run(
            _load_entity_terms_async(
                owner_user_id=owner_user_id,
                entity_type=entity_type,
                knowledge_base_id=knowledge_base_id,
                biz_code=biz_code,
            )
        )
    except Exception:
        return []
