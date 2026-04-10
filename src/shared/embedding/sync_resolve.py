"""在无运行中事件循环时，用 ``asyncio.run`` 从数据库解析嵌入配置（供同步工具 / LangMem 使用）."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from shared.embedding.config import EmbeddingConfig
from shared.embedding.exceptions import EmbeddingConfigurationError
from shared.embedding.provider import DatabaseEmbeddingSettingsProvider

logger = logging.getLogger(__name__)


async def _resolve_async(session: AsyncSession, owner_user_id: int) -> EmbeddingConfig:
    return await DatabaseEmbeddingSettingsProvider().resolve(session, owner_user_id)


def sync_resolve_embedding_config(owner_user_id: int) -> EmbeddingConfig:
    """同步解析 ``owner_user_id`` 的嵌入配置。

    若当前线程已有运行中的 asyncio 循环，则抛出 ``EmbeddingConfigurationError``，
    请改用 ``await DatabaseEmbeddingSettingsProvider().resolve(session, owner_user_id)``。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise EmbeddingConfigurationError(
            "同步解析嵌入失败：当前处于异步上下文，请使用 DatabaseEmbeddingSettingsProvider().resolve(session, owner_user_id)",
        )

    async def _run() -> EmbeddingConfig:
        from utils.sql_db import async_session

        async with async_session() as session:
            return await _resolve_async(session, owner_user_id)

    try:
        return asyncio.run(_run())
    except EmbeddingConfigurationError:
        raise
    except Exception as exc:
        logger.exception("sync_resolve_embedding_config failed owner_user_id=%s", owner_user_id)
        raise EmbeddingConfigurationError(str(exc)) from exc
