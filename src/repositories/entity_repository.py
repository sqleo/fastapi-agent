"""实体词典查询：查询端实体归一化（KB > Biz > Global 优先级）。"""

from __future__ import annotations

import re

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.EntityDictionaryModel import EntityAliasModel, EntityDictionaryModel, EntityType


def _normalize(text: str) -> str:
    """去空格、转小写，与入库端 normalized_name / alias_normalized 字段对齐。"""
    return re.sub(r"\s+", "", text.strip().lower())


def _priority_expr(knowledge_base_id: int | None, biz_code: str | None):
    """返回 SQLAlchemy case 表达式：KB 级=0，业务级=1，全局=2。"""
    return case(
        (
            EntityDictionaryModel.knowledge_base_id == knowledge_base_id,
            0,
        ),
        (
            (EntityDictionaryModel.biz_code == biz_code)
            & EntityDictionaryModel.knowledge_base_id.is_(None),
            1,
        ),
        else_=2,
    )


async def resolve_entity_canonical(
    text: str,
    entity_type: EntityType,
    *,
    owner_user_id: int,
    biz_code: str | None = None,
    knowledge_base_id: int | None = None,
    session: AsyncSession,
) -> str | None:
    """将模型抽到的原始文本归一化为词典 canonical_name。

    查找顺序：
    1. entity_alias 别名表（alias_normalized == normalize(text)）
    2. entity_dictionary 主表（normalized_name == normalize(text)）

    每步按作用域优先级排序：KB 级 > 业务级 > 租户全局。
    未命中返回 ``None``（调用方应退化使用模型原始文本）。
    """
    if not text or not text.strip():
        return None

    normalized = _normalize(text)
    pri = _priority_expr(knowledge_base_id, biz_code)

    # ── 1. 别名表 ──────────────────────────────────────────────────────────────
    stmt_alias = (
        select(EntityDictionaryModel.canonical_name, pri.label("pri"))
        .join(EntityAliasModel, EntityAliasModel.entity_id == EntityDictionaryModel.id)
        .where(
            EntityAliasModel.alias_normalized == normalized,
            EntityAliasModel.owner_user_id == owner_user_id,
            EntityAliasModel.status == 1,
            EntityDictionaryModel.owner_user_id == owner_user_id,
            EntityDictionaryModel.entity_type == entity_type,
            EntityDictionaryModel.status == 1,
        )
        .order_by("pri", EntityDictionaryModel.priority)
        .limit(1)
    )
    row = (await session.execute(stmt_alias)).first()
    if row:
        return str(row[0])

    # ── 2. 主表直查 ────────────────────────────────────────────────────────────
    stmt_direct = (
        select(EntityDictionaryModel.canonical_name, pri.label("pri"))
        .where(
            EntityDictionaryModel.normalized_name == normalized,
            EntityDictionaryModel.owner_user_id == owner_user_id,
            EntityDictionaryModel.entity_type == entity_type,
            EntityDictionaryModel.status == 1,
        )
        .order_by("pri", EntityDictionaryModel.priority)
        .limit(1)
    )
    row = (await session.execute(stmt_direct)).first()
    if row:
        return str(row[0])

    return None


async def resolve_entities_batch(
    brand: str | None,
    product_name: str | None,
    category: str | None,
    *,
    owner_user_id: int,
    biz_code: str | None = None,
    knowledge_base_id: int | None = None,
    session: AsyncSession,
) -> dict[str, str | None]:
    """批量归一化 brand / product_name / category，并记录是否命中词典。"""
    results: dict[str, str | None] = {}

    for raw, etype, key in [
        (brand, EntityType.BRAND, "brand"),
        (product_name, EntityType.PRODUCT, "product_name"),
        (category, EntityType.CATEGORY, "category"),
    ]:
        if raw:
            canonical = await resolve_entity_canonical(
                raw,
                etype,
                owner_user_id=owner_user_id,
                biz_code=biz_code,
                knowledge_base_id=knowledge_base_id,
                session=session,
            )
            results[key] = canonical or raw  # 未命中则保留模型原始文本
        else:
            results[key] = None

    return results
