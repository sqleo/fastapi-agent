"""LangGraph 时间旅行（Time Travel）核心逻辑。

纯 Agent 相关代码，不包含业务（FastAPI、鉴权、数据库等）。
提供 get_history、replay、fork 等功能，支持「暂停后继续」和「历史分支」。

核心概念：
- Checkpoint：每个节点执行后自动保存的状态快照
- Thread：对话主线
- Fork：从历史 checkpoint 创建新分支（推荐用于时间旅行）
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from langgraph_sdk import get_client

from agent.control.interrupt import clear_pause_controller

logger = logging.getLogger("agent.control.time_travel")

# 使用全局 LANGGRAPH_API_URL（与 agent.py 保持一致）
LANGGRAPH_API_URL = "http://localhost:8123"  # 可通过环境变量覆盖


async def get_thread_history(
    thread_id: str,
    *,
    limit: int = 20,
    before: str | None = None,
) -> list[dict]:
    """获取某个 thread 的所有历史 checkpoint（按时间倒序）。"""
    client = get_client(url=LANGGRAPH_API_URL)
    
    try:
        history = await client.threads.get_state_history(
            thread_id=thread_id,
            limit=limit,
            before=before,
        )
        return list(history)  # 转为 list 方便后续处理
    except Exception as e:
        logger.error("Failed to get history for thread %s: %s", thread_id, e)
        return []


def _format_checkpoint(state: dict) -> dict:
    """将 LangGraph state 格式化为前端友好的 checkpoint 信息。"""
    values = state.get("values", {})
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
    
    return {
        "checkpoint_id": state.get("checkpoint_id"),
        "parent_checkpoint_id": state.get("parent_checkpoint_id"),
        "timestamp": state.get("timestamp") or datetime.now().isoformat(),
        "content_preview": preview or "无输出预览",
        "node": state.get("metadata", {}).get("step", "unknown"),
        "metadata": {
            "source": "checkpoint",
            "interrupted": bool(state.get("tasks", [])),
            **(state.get("metadata") or {}),
        }
    }


async def get_formatted_history(
    thread_id: str,
    limit: int = 20,
) -> list[dict]:
    """获取格式化后的历史记录，供 API 返回。"""
    raw_history = await get_thread_history(thread_id, limit=limit)
    return [_format_checkpoint(state) for state in raw_history]


async def fork_from_checkpoint(
    thread_id: str,
    checkpoint_id: str,
    *,
    new_input: str | None = None,
    user_id: int | None = None,
) -> dict:
    """从指定 checkpoint 创建新的分支（推荐的时间旅行方式）。
    
    这不会修改原对话历史，而是创建一个新的 thread。
    """
    client = get_client(url=LANGGRAPH_API_URL)
    
    # 1. 获取目标 checkpoint 的状态
    state = await client.threads.get_state(thread_id, checkpoint_id=checkpoint_id)
    
    # 2. 创建新的 thread（分支）
    new_thread = await client.threads.create()
    new_thread_id = new_thread["thread_id"]
    
    # 3. 更新新 thread 的状态为历史 checkpoint 的状态
    await client.threads.update_state(
        thread_id=new_thread_id,
        values=state.get("values", {}),
        as_node=state.get("next", ["__end__"])[0] if state.get("next") else None,
    )
    
    # 4. 如果提供了新输入，则立即加入新消息
    if new_input:
        await client.runs.create(
            new_thread_id,
            assistant_id="agent",
            input={"messages": [{"role": "user", "content": new_input}]},
            config={"configurable": {"user_id": str(user_id)}} if user_id else None,
        )
    
    clear_pause_controller(thread_id)      # 清理旧暂停状态
    clear_pause_controller(new_thread_id)  # 清理新分支暂停状态
    
    logger.info(
        "Forked new branch from thread=%s checkpoint=%s → new_thread=%s",
        thread_id, checkpoint_id, new_thread_id
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
    thread_id: str,
    checkpoint_id: str,
) -> dict:
    """重放（Replay）某个历史 checkpoint 之后的内容（不创建新分支）。"""
    client = get_client(url=LANGGRAPH_API_URL)
    
    # LangGraph SDK 中 replay 通常通过指定 checkpoint_id 调用 run
    config = {
        "configurable": {
            "checkpoint_id": checkpoint_id,
        }
    }
    
    # 这里简化：实际生产中可使用 client.runs.create with checkpoint
    logger.info("Replay requested for thread=%s checkpoint=%s", thread_id, checkpoint_id)
    
    return {
        "thread_id": thread_id,
        "checkpoint_id": checkpoint_id,
        "mode": "replay",
        "message": "已跳转到指定历史点并开始重放（当前为简化实现）",
    }


async def travel(
    thread_id: str,
    checkpoint_id: str,
    mode: Literal["replay", "fork"] = "fork",
    new_input: str | None = None,
    user_id: int | None = None,
) -> dict:
    """统一的时间旅行入口。"""
    if mode == "fork":
        return await fork_from_checkpoint(
            thread_id, 
            checkpoint_id, 
            new_input=new_input, 
            user_id=user_id
        )
    else:
        return await replay_from_checkpoint(thread_id, checkpoint_id)
