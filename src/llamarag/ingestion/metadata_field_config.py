"""metadata 抽取配置加载：优先读 DB，读不到走默认值。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from sqlalchemy import case, select

from models.MetadataFieldModel import MetadataFieldAliasModel, MetadataFieldModel
from utils.sql_db import async_session


def _scope_rank_case(model):
    return case(
        (model.knowledge_base_id.is_not(None), 0),
        (model.biz_code.is_not(None), 1),
        else_=2,
    )


async def _load_metadata_field_config_async(
    *,
    owner_user_id: int,
    knowledge_base_id: int | None,
    biz_code: str | None,
) -> dict[str, dict[str, Any]]:
    field_scope = [
        MetadataFieldModel.owner_user_id == owner_user_id,
        MetadataFieldModel.status == 1,
    ]
    if knowledge_base_id is not None:
        field_scope.append(
            (MetadataFieldModel.knowledge_base_id == knowledge_base_id)
            | (
                MetadataFieldModel.knowledge_base_id.is_(None)
                & (
                    (MetadataFieldModel.biz_code == biz_code)
                    | (MetadataFieldModel.biz_code.is_(None))
                )
            )
        )
    elif biz_code is not None:
        field_scope.append(
            (MetadataFieldModel.biz_code == biz_code) | (MetadataFieldModel.biz_code.is_(None))
        )

    async with async_session() as session:
        field_stmt = (
            select(MetadataFieldModel)
            .where(*field_scope)
            .order_by(_scope_rank_case(MetadataFieldModel), MetadataFieldModel.priority.asc(), MetadataFieldModel.id.asc())
        )
        field_res = await session.execute(field_stmt)
        field_rows = list(field_res.scalars().all())

        selected_fields: dict[str, MetadataFieldModel] = {}
        for row in field_rows:
            if row.field_key not in selected_fields:
                selected_fields[row.field_key] = row

        if not selected_fields:
            return {}

        alias_stmt = (
            select(MetadataFieldAliasModel)
            .where(
                MetadataFieldAliasModel.field_id.in_([int(x.id) for x in selected_fields.values()]),
                MetadataFieldAliasModel.status == 1,
            )
            .order_by(MetadataFieldAliasModel.priority.asc(), MetadataFieldAliasModel.id.asc())
        )
        alias_res = await session.execute(alias_stmt)
        alias_rows = list(alias_res.scalars().all())

    aliases_by_field_id: dict[int, list[str]] = defaultdict(list)
    for row in alias_rows:
        aliases_by_field_id[int(row.field_id)].append(row.alias_text)

    config: dict[str, dict[str, Any]] = {}
    for field_key, field in selected_fields.items():
        aliases = aliases_by_field_id.get(int(field.id), [])
        if field.field_name and field.field_name not in aliases:
            aliases = [field.field_name, *aliases]
        config[field_key] = {
            "extract_mode": str(field.extract_mode.value if hasattr(field.extract_mode, "value") else field.extract_mode),
            "aliases": aliases,
        }
    return config


async def has_metadata_field_config_async(
    *,
    owner_user_id: int,
    knowledge_base_id: int | None,
    biz_code: str | None,
) -> bool:
    """判断当前作用域下是否已配置 metadata 抽取字段。"""
    config = await _load_metadata_field_config_async(
        owner_user_id=owner_user_id,
        knowledge_base_id=knowledge_base_id,
        biz_code=biz_code,
    )
    return bool(config)


def load_metadata_field_config_sync(
    *,
    owner_user_id: int | None,
    knowledge_base_id: int | None,
    biz_code: str | None,
) -> dict[str, dict[str, Any]]:
    """同步入口：供入库线程读取动态配置。"""
    if owner_user_id is None:
        return {}
    try:
        return asyncio.run(
            _load_metadata_field_config_async(
                owner_user_id=owner_user_id,
                knowledge_base_id=knowledge_base_id,
                biz_code=biz_code,
            )
        )
    except Exception:
        return {}