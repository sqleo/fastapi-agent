"""LangGraph 时间旅行（Time Travel）核心逻辑。

纯基础设施代码，不依赖特定的 Agent 实例或外部 LangGraph SDK，
统一接受 graph: CompiledGraph 对象执行本地状态操作。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from .interrupt import clear_pause_controller

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger("infra.langgraph.control.time_travel")

async def rollback_to(
    config: RunnableConfig,
    target_node: str,
    extra_updates: dict[str, Any] | None = None,
) -> Command:
    """
    从 Checkpointer 历史里找到 target_node 执行前的快照，
    用那个快照的 state 覆盖当前 state，再跳回去重跑（业务节点内使用）。

    依赖 config["configurable"]["graph"] 中传入了图实例。
    """
    configurable = config.get("configurable")
    if not configurable:
        raise ValueError("config.configurable 不能为空")

    graph = cast("CompiledStateGraph", configurable.get("graph"))
    thread_id = cast(str | None, configurable.get("thread_id"))
    if graph is None or not thread_id:
        raise ValueError("config.configurable 必须包含 graph 和 thread_id")

    cfg: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    target_snapshot = None

    # 从历史快照里找到目标节点执行前的状态
    async for snapshot in graph.aget_state_history(cfg):
        if snapshot.next and target_node in snapshot.next:
            target_snapshot = snapshot
            break

    if target_snapshot is None:
        raise ValueError(f"找不到节点 {target_node!r} 执行前的快照")

    update = {**target_snapshot.values, **(extra_updates or {})}
    return Command(goto=target_node, update=update)


async def get_thread_history(
    graph: CompiledStateGraph,
    thread_id: str,
    *,
    limit: int = 20,
    before: RunnableConfig | None = None,
) -> list[Any]:
    """获取某个 thread 的所有历史 checkpoint（按时间倒序）。"""
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    history = []

    try:
        async for state in graph.aget_state_history(config, limit=limit, before=before):
            history.append(state)
        return history
    except Exception as e:
        logger.error("Failed to get history for thread %s: %s", thread_id, e)
        return []


def _format_checkpoint(state: Any) -> dict:
    """将 LangGraph state 格式化为前端友好的 checkpoint 信息。"""
    values = state.values or {}
    messages = values.get("messages", [])

    # 提取最后一条 AI 消息作为预览
    preview = ""
    if messages and len(messages) > 0:
        last_msg = messages[-1]
        if isinstance(last_msg, dict):
            content = last_msg.get("content", "")
            if isinstance(content, str):
                preview = content[:120] + "..." if len(content) > 120 else content
            else:
                preview = str(content)[:120]
        else:
            preview = str(last_msg)[:120]

    # 解析 StateSnapshot 对象
    checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")
    # LangGraph 最新版本可能没有显式的 timestamp，从 checkpoint_id 提取或使用当前时间

    return {
        "checkpoint_id": checkpoint_id,
        "parent_checkpoint_id": (
            state.parent_config.get("configurable", {}).get("checkpoint_id")
            if state.parent_config
            else None
        ),
        "timestamp": datetime.now().isoformat(),  # 简化：如果需要精准时间可以解析 uuid
        "content_preview": preview or "无输出预览",
        "node": state.metadata.get("step", "unknown") if state.metadata else "unknown",
        "metadata": {
            "source": "checkpoint",
            "interrupted": bool(state.tasks),
            **(state.metadata or {}),
        },
    }


async def get_formatted_history(
    graph: CompiledStateGraph,
    thread_id: str,
    limit: int = 20,
) -> list[dict]:
    """获取格式化后的历史记录，供 API 返回。"""
    raw_history = await get_thread_history(graph, thread_id, limit=limit)
    return [_format_checkpoint(state) for state in raw_history]


async def fork_from_checkpoint(
    graph: CompiledStateGraph,
    thread_id: str,
    checkpoint_id: str,
    *,
    new_input: str | None = None,
    user_id: int | None = None,
) -> dict:
    """从指定 checkpoint 创建新的分支（推荐的时间旅行方式）。

    不修改原对话历史，而是创建一个新的 thread。
    """
    # 1. 获取目标 checkpoint 的状态
    config: RunnableConfig = {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}
    state = await graph.aget_state(config)

    # 2. 创建新的 thread（分支）
    new_thread_id = str(uuid.uuid4())
    new_config: RunnableConfig = {"configurable": {"thread_id": new_thread_id}}

    # 3. 更新新 thread 的状态为历史 checkpoint 的状态
    await graph.aupdate_state(
        new_config,
        state.values,
        as_node=state.next[0] if state.next else None,
    )

    # 4. 如果提供了新输入，则立即加入新消息 (在后台图调用中处理，或由调用方决定，此处可以选择直接抛给调用方或在此 invoke)
    # 本地直接 invoke 是非阻塞或阻塞的，建议通过异步方式触发，或将新输入加入 state
    if new_input:
        invoke_config: RunnableConfig = {"configurable": {"thread_id": new_thread_id}}
        if user_id:
            invoke_config["configurable"]["user_id"] = str(user_id)

        # 注意：这里会产生一次完整的生成调用，可以根据需求改为仅挂起任务，此处简单起见直接 ainvoke
        await graph.ainvoke(
            {"messages": [{"role": "user", "content": new_input}]},
            config=invoke_config,
        )

    clear_pause_controller(thread_id)  # 清理旧暂停状态
    clear_pause_controller(new_thread_id)  # 清理新分支暂停状态

    logger.info(
        "Forked new branch from thread=%s checkpoint=%s → new_thread=%s",
        thread_id,
        checkpoint_id,
        new_thread_id,
    )

    return {
        "original_thread_id": thread_id,
        "new_thread_id": new_thread_id,
        "checkpoint_id": checkpoint_id,
        "mode": "fork",
        "message": "已成功创建时间旅行分支",
        "action": "new_branch_created",
    }


async def replay_from_checkpoint(
    graph: CompiledStateGraph,
    thread_id: str,
    checkpoint_id: str,
) -> dict:
    """重放（Replay）某个历史 checkpoint 之后的内容（不创建新分支）。"""

    logger.info("Replay requested for thread=%s checkpoint=%s", thread_id, checkpoint_id)

    # 通常重放直接使用带有 checkpoint_id 的 config 去 astream/ainvoke
    # 路由层会处理
    return {
        "thread_id": thread_id,
        "checkpoint_id": checkpoint_id,
        "mode": "replay",
        "message": "已跳转到指定历史点（调用方可使用该 checkpoint_id 继续图的执行）",
    }


async def travel(
    graph: CompiledStateGraph,
    thread_id: str,
    checkpoint_id: str,
    mode: Literal["replay", "fork"] = "fork",
    new_input: str | None = None,
    user_id: int | None = None,
) -> dict:
    """统一的时间旅行入口。"""
    if mode == "fork":
        return await fork_from_checkpoint(
            graph,
            thread_id,
            checkpoint_id,
            new_input=new_input,
            user_id=user_id,
        )
    else:
        return await replay_from_checkpoint(graph, thread_id, checkpoint_id)
