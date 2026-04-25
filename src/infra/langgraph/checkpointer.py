"""LangGraph ``checkpointer``：基于 Postgres 持久化，无库时回退内存。

使用 ``POSTGRES_URI``。可选
``LANGGRAPH_CHECKPOINT_POSTGRES_URI`` 单独指定 checkpoint 库。

说明：同步的 ``PostgresSaver`` 未实现 ``aget_tuple`` / ``aput`` / ``aput_writes``，
而 ``astream_events`` / ``AsyncPregelLoop`` 会走异步 checkpoint API，故对 Postgres
使用 ``_AsyncPostgresSaverBridge``，在 ``asyncio.to_thread`` 中调用同步实现。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from langchain_core.runnables import RunnableConfig

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres import PostgresSaver

logger = logging.getLogger("infra.langgraph.checkpointer")

_checkpointer: BaseCheckpointSaver | None = None


class _AsyncPostgresSaverBridge(BaseCheckpointSaver):
    """将同步 ``PostgresSaver`` 桥接到 LangGraph 异步 checkpoint 接口。"""

    def __init__(self, inner: PostgresSaver) -> None:
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


def _postgres_uri() -> str:
    return (
        (os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_URI") or os.getenv("POSTGRES_URI") or "")
        .strip()
    )


def get_graph_checkpointer() -> BaseCheckpointSaver:
    """单例：Postgres（桥接异步 API）或 ``MemorySaver``。"""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    uri = _postgres_uri()
    if uri:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        try:
            max_size = int(os.getenv("LANGGRAPH_CHECKPOINT_PG_POOL_MAX", "10"))
        except ValueError:
            max_size = 10

        pool = ConnectionPool(
            uri,
            min_size=1,
            max_size=max_size,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        sync_saver = PostgresSaver(pool)
        sync_saver.setup()
        _checkpointer = _AsyncPostgresSaverBridge(sync_saver)
        logger.info(
            "LangGraph checkpoint 已启用 Postgres（异步 API 桥接；与 astream_events 兼容）"
        )
    else:
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer = MemorySaver()
        logger.warning(
            "POSTGRES_URI 未设置：graph checkpoint 使用进程内内存，重启后对话状态丢失。"
            "生产环境请设置 POSTGRES_URI。"
        )

    return _checkpointer


async def delete_graph_service_conversation(thread_id: str) -> None:
    """删除该 ``thread_id`` 的会话状态数据（对齐 SDK ``threads.delete``）。"""
    cp = get_graph_checkpointer()
    await cp.adelete_thread(thread_id)
