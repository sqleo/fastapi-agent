"""Report Graph checkpoint 配置（Postgres 优先，失败回退内存）。"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.memory import MemorySaver


logger = logging.getLogger("report.checkpoint")


def get_postgres_uri() -> str:
    """获取 PostgreSQL 连接 URI。"""
    return (
        os.getenv("REPORT_POSTGRES_URI")
        or os.getenv("POSTGRES_URI")
        or "postgresql://postgres:postgres@localhost:5432/langgraph"
    ).strip()


class _AsyncPostgresSaverBridge(BaseCheckpointSaver):
    """将同步 PostgresSaver 桥接到 LangGraph 异步 checkpoint API。"""

    def __init__(self, inner: Any) -> None:
        super().__init__(serde=inner.serde)
        self._inner = inner

    def get_next_version(self, current: Any, channel: None) -> Any:
        return self._inner.get_next_version(current, channel)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await asyncio.to_thread(self._inner.get_tuple, config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(
            self._inner.put, config, checkpoint, metadata, new_versions
        )

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        def _run() -> None:
            self._inner.put_writes(config, writes, task_id, task_path)

        await asyncio.to_thread(_run)

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self._inner.delete_thread, thread_id)


def build_checkpoint_saver(mode: str = "auto") -> BaseCheckpointSaver:
    """构建 Checkpoint Saver 实例。"""
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
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            uri,
            min_size=1,
            max_size=10,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        sync_saver = PostgresSaver(pool)  # type: ignore[arg-type]
        sync_saver.setup()
        saver = _AsyncPostgresSaverBridge(sync_saver)
        logger.info("Report Graph 使用 PostgreSQL Checkpoint 已初始化完成")
        return saver
    except Exception as e:
        if mode == "postgres":
            raise RuntimeError(f"PostgreSQL Checkpoint 初始化失败: {e}") from e
        logger.warning("PostgreSQL Checkpoint 初始化失败，回退到内存 Checkpoint: %s", e)
        return MemorySaver()


_checkpoint_saver: Optional[BaseCheckpointSaver] = None


def get_report_checkpoint_saver() -> BaseCheckpointSaver:
    """获取全局单例 Checkpoint Saver。"""
    global _checkpoint_saver
    if _checkpoint_saver is None:
        _checkpoint_saver = build_checkpoint_saver()
    return _checkpoint_saver
