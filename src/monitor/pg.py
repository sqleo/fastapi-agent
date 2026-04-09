"""PostgreSQL 异步引擎（SQLAlchemy ORM）。

复用 POSTGRES_URI，首次获取 session 时自动 ``CREATE SCHEMA`` + ``create_all``。
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger("monitor.pg")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_schema_ready: bool = False


def _pg_uri() -> str:
    raw = (os.getenv("MONITOR_POSTGRES_URI") or os.getenv("POSTGRES_URI") or "").strip()
    if not raw:
        return ""
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    return raw


async def _ensure_schema(engine: AsyncEngine) -> None:
    global _schema_ready
    if _schema_ready:
        return
    from monitor.models import MonitorBase

    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS llm_monitor"))
        await conn.run_sync(MonitorBase.metadata.create_all)
        # create_all 不会给已有表加列，显式补列（兼容旧库）
        await conn.execute(
            text(
                "ALTER TABLE llm_monitor.request_log "
                "ADD COLUMN IF NOT EXISTS input_tokens_cache_hit INTEGER NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE llm_monitor.request_log "
                "ADD COLUMN IF NOT EXISTS input_tokens_cache_miss INTEGER NOT NULL DEFAULT 0"
            )
        )
    _schema_ready = True
    logger.info("llm_monitor schema 已就绪（ORM create_all）")


async def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """返回异步 Session 工厂；首次调用时初始化引擎并建表。"""
    global _engine, _session_factory

    if _session_factory is not None:
        return _session_factory

    uri = _pg_uri()
    if not uri:
        logger.warning("未配置 POSTGRES_URI，LLM 监控已禁用")
        return None

    _engine = create_async_engine(uri, pool_size=5, max_overflow=5, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    try:
        await _ensure_schema(_engine)
    except Exception:
        logger.exception("llm_monitor schema 初始化失败，监控写入可能异常")

    return _session_factory


async def init_monitor_pool() -> None:
    """显式初始化（可选，在 lifespan 中调用）。"""
    await get_session_factory()


async def close_monitor_pool() -> None:
    """关闭引擎及连接池。"""
    global _engine, _session_factory, _schema_ready
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        _schema_ready = False
