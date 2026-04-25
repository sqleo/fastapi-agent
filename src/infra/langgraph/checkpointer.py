"""LangGraph checkpointer 统一入口。

为避免重复维护，infra 层直接复用 report 域的 checkpoint 实现。
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from report.memory.checkpoint import get_report_checkpoint_saver


def get_graph_checkpointer() -> BaseCheckpointSaver:
    """复用 report 域的全局 checkpointer。"""
    return get_report_checkpoint_saver()


async def delete_graph_service_conversation(thread_id: str) -> None:
    """删除该 ``thread_id`` 的会话状态数据（对齐 SDK ``threads.delete``）。"""
    cp = get_graph_checkpointer()
    await cp.adelete_thread(thread_id)
