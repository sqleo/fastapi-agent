"""Report Graph Checkpoint 配置
基于 PostgreSQL 实现持久化 Checkpoint，支持中断恢复和 Time-travel 回滚
"""
from __future__ import annotations

import os
import logging
from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver as PostgresCheckpointSaver


logger = logging.getLogger("report.checkpoint")


def get_postgres_uri() -> str:
    """获取 PostgreSQL 连接 URI
    优先级: REPORT_POSTGRES_URI > POSTGRES_URI > 默认值
    """
    uri = (
        os.getenv("REPORT_POSTGRES_URI")
        or os.getenv("POSTGRES_URI")
        or "postgresql://postgres:postgres@localhost:5432/langgraph"
    ).strip()
    return uri


def build_checkpoint_saver(mode: str = "auto") -> BaseCheckpointSaver:
    """构建 Checkpoint Saver 实例

    Args:
        mode: 运行模式
            - "auto": 优先 PostgreSQL，不可用时回退到内存
            - "postgres": 强制使用 PostgreSQL，失败则抛出异常
            - "memory": 强制使用内存 Checkpoint

    Returns:
        BaseCheckpointSaver 实例
    """
    if mode == "memory":
        logger.info("Report Graph 使用内存 Checkpoint (mode=memory)")
        return MemorySaver()

    uri = get_postgres_uri()

    if not uri:
        if mode == "postgres":
            raise RuntimeError("POSTGRES_URI 未配置，无法初始化 PostgreSQL Checkpoint")
        logger.warning("POSTGRES_URI 未配置，回退到内存 Checkpoint")
        return MemorySaver()

    try:
        if PostgresCheckpointSaver is None:
            raise ImportError("PostgresCheckpointSaver 不可用")
            
        from psycopg_pool import AsyncConnectionPool
        pool = AsyncConnectionPool(
            conninfo=uri,
            min_size=1,
            max_size=10,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
            },
        )

        checkpoint_saver = PostgresCheckpointSaver(
            connection=pool,
        )

        # 初始化数据库表
        import asyncio
        asyncio.run(checkpoint_saver.setup())
        logger.info("Report Graph 使用 PostgreSQL Checkpoint 已初始化完成")
        return checkpoint_saver

    except Exception as e:
        if mode == "postgres":
            raise RuntimeError(f"PostgreSQL Checkpoint 初始化失败: {e}") from e
        logger.warning("PostgreSQL Checkpoint 初始化失败，回退到内存 Checkpoint: %s", e)
        return MemorySaver()


# 全局 Checkpoint 实例
_checkpoint_saver: Optional[BaseCheckpointSaver] = None


def get_report_checkpoint_saver() -> BaseCheckpointSaver:
    """获取全局单例 Checkpoint Saver"""
    global _checkpoint_saver
    if _checkpoint_saver is None:
        _checkpoint_saver = build_checkpoint_saver()
    return _checkpoint_saver
