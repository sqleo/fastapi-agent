"""用户全局模型设置业务逻辑。

嵌入字段（embedding_vendor_id / embedding_model / embedding_dim）任一变更：
- ``embedding_version`` +1
- ``embedding_status`` → ``migrating``
- 入队 reindex 任务，把旧 version 的记忆重新嵌入到新 version schema
- 清掉相关运行时缓存（store / embeddings / config）

未配置嵌入或清空配置 → ``embedding_status`` → ``deprecated``。
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.LlmGlobalSettingModel import (
    EMBEDDING_STATUS_ACTIVE,
    EMBEDDING_STATUS_DEPRECATED,
    EMBEDDING_STATUS_MIGRATING,
    LlmGlobalSettingModel,
)
from models.LlmVendorModel import LlmVendorModel

logger = logging.getLogger(__name__)


_EMBEDDING_TRIGGER_FIELDS = ("embedding_vendor_id", "embedding_model", "embedding_dim")


async def _assert_vendor_owned(session: AsyncSession, *, owner_user_id: int, vendor_id: int) -> None:
    stmt = select(LlmVendorModel.id).where(
        LlmVendorModel.id == vendor_id,
        LlmVendorModel.owner_user_id == owner_user_id,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"厂商不存在: {vendor_id}")


async def _get_or_create(session: AsyncSession, *, owner_user_id: int) -> LlmGlobalSettingModel:
    stmt = select(LlmGlobalSettingModel).where(LlmGlobalSettingModel.owner_user_id == owner_user_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = LlmGlobalSettingModel(owner_user_id=owner_user_id)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_global_setting_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
) -> LlmGlobalSettingModel:
    """获取用户全局设置；若不存在则自动创建空设置。"""
    return await _get_or_create(session, owner_user_id=owner_user_id)


def _embedding_changed(row: LlmGlobalSettingModel, patch: dict) -> bool:
    for field in _EMBEDDING_TRIGGER_FIELDS:
        if field not in patch:
            continue
        new_val = patch.get(field)
        old_val = getattr(row, field, None)
        if (new_val or None) != (old_val or None):
            return True
    return False


def _embedding_now_present(row: LlmGlobalSettingModel) -> bool:
    return bool(row.embedding_vendor_id) and bool((row.embedding_model or "").strip())


async def update_global_setting_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    patch: dict,
) -> LlmGlobalSettingModel:
    """更新用户全局设置，并校验引用厂商归属。

    嵌入相关字段变更会自动触发版本号 +1 + reindex 任务。
    """
    for field_name in (
        "chat_vendor_id",
        "embedding_vendor_id",
        "multimodal_vendor_id",
        "rerank_vendor_id",
        "asr_vendor_id",
        "tts_vendor_id",
    ):
        vid = patch.get(field_name)
        if vid is not None:
            await _assert_vendor_owned(session, owner_user_id=owner_user_id, vendor_id=int(vid))

    row = await _get_or_create(session, owner_user_id=owner_user_id)
    embedding_changed = _embedding_changed(row, patch)
    old_version = int(row.embedding_version or 1)

    for key, value in patch.items():
        # 不允许调用方手工写这三个由后端管理的字段
        if key in ("embedding_version", "embedding_status"):
            continue
        setattr(row, key, value)

    if embedding_changed:
        if _embedding_now_present(row):
            new_version = old_version + 1
            row.embedding_version = new_version
            row.embedding_status = EMBEDDING_STATUS_MIGRATING
            logger.info(
                "embedding 配置变更：user_id=%s version %s -> %s, status=migrating",
                owner_user_id,
                old_version,
                new_version,
            )
        else:
            # 用户清空了嵌入配置 → 降级为 deprecated（只 KV）
            row.embedding_status = EMBEDDING_STATUS_DEPRECATED
            logger.info("embedding 配置已清空：user_id=%s, status=deprecated", owner_user_id)

    session.add(row)
    await session.commit()
    await session.refresh(row)

    if embedding_changed:
        # 清运行时缓存：store factory + embeddings 缓存
        try:
            from infra.langgraph.tenant_store import invalidate_user_config_cache
            from llm_completion.embedding_llm import invalidate_embeddings_cache

            invalidate_user_config_cache(owner_user_id)
            invalidate_embeddings_cache(owner_user_id)
        except Exception:
            logger.warning("清理 embedding 缓存失败 user_id=%s", owner_user_id, exc_info=True)

        # 仅在切到 migrating 时入队 reindex 任务
        if row.embedding_status == EMBEDDING_STATUS_MIGRATING:
            try:
                from infra.langgraph.reindex_tasks import enqueue_reindex

                await enqueue_reindex(
                    user_id=owner_user_id,
                    old_version=old_version,
                    new_version=int(row.embedding_version),
                )
                logger.info(
                    "已入队 reindex 任务：user_id=%s old=%s new=%s",
                    owner_user_id,
                    old_version,
                    row.embedding_version,
                )
            except Exception:
                logger.exception(
                    "入队 reindex 任务失败 user_id=%s（请人工处理）",
                    owner_user_id,
                )

    return row
