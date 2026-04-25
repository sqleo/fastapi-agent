"""通用记忆节点：支持 LangMem 的检索和写入，可在任何 LangGraph 中复用。"""

import logging
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import convert_to_messages

from .advanced_memory import AdvancedMemoryManager
from infra.langgraph import get_langgraph_store

logger = logging.getLogger("agent.memory_nodes")


def _last_user_text_from_messages(messages: list[AnyMessage]) -> str:
    """从消息列表中提取最后一条用户文本（通用辅助函数）。"""
    if not messages:
        return ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            c = m.content
            if isinstance(c, str) and c.strip():
                return c.strip()
            if isinstance(c, list):
                parts: list[str] = []
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                joined = " ".join(parts).strip()
                if joined:
                    return joined
        elif isinstance(m, dict):
            role = (str(m.get("type") or m.get("role") or "")).lower()
            if role in ("human", "user"):
                c = m.get("content")
                if isinstance(c, str) and c.strip():
                    return c.strip()
                if isinstance(c, list):
                    parts = [
                        str(b.get("text", ""))
                        for b in c
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    joined = " ".join(parts).strip()
                    if joined:
                        return joined
    return ""


def _message_content_str(msg: BaseMessage) -> str:
    """提取消息内容为字符串（通用辅助函数）。"""
    c = getattr(msg, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [
            str(b.get("text", ""))
            for b in c
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return " ".join(parts).strip()
    return str(c or "")


def _resolve_user_id_from_config(config: RunnableConfig | None) -> int:
    """从 config 中解析 user_id（通用辅助函数）。"""
    import os
    configurable = (config or {}).get("configurable") or {}
    raw = configurable.get("user_id")
    if raw is None or isinstance(raw, bool):
        uid = None
    elif isinstance(raw, int):
        uid = raw if raw > 0 else None
    else:
        s = str(raw).strip()
        if not s:
            uid = None
        else:
            try:
                uid = int(s)
            except ValueError:
                uid = None
            uid = uid if uid and uid > 0 else None

    if uid is not None:
        return uid
    fb = (os.environ.get("LANGGRAPH_DEV_USER_ID") or "").strip()
    if fb:
        try:
            uid = int(fb)
            if uid > 0:
                logger.warning(
                    "configurable.user_id 未传入，已使用 LANGGRAPH_DEV_USER_ID=%s（仅本地调试用）",
                    uid,
                )
                return uid
        except ValueError:
            pass
    raise ValueError(
        "缺少有效的 configurable.user_id（须为正整数），无法创建会话级记忆",
    )


async def short_term_window_node(
    state: dict[str, Any],
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    短期记忆滑动窗口节点。

    从 config.configurable.memory_strategy 中读取 max_turns，默认 3。
    """
    from .turns import take_last_turns

    strategy = config.get("configurable", {}).get("memory_strategy", {})
    max_turns = strategy.get("max_turns", 3)

    messages = state.get("messages", [])
    if isinstance(messages, list) and any(isinstance(m, dict) for m in messages):
        try:
            messages = convert_to_messages(messages)
        except Exception:
            pass  # 保持原样

    if not messages:
        return {"messages": []}

    # 使用现有的 turns.py 中的函数
    retained_messages = take_last_turns(messages, max_turns=max_turns)
    return {"messages": retained_messages}


async def advanced_memory_retrieve_node(
    state: dict[str, Any],
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    高级记忆检索节点。

    从 config.configurable.memory_strategy 中读取策略参数。
    """
    strategy = config.get("configurable", {}).get("memory_strategy", {})
    limit = strategy.get("retrieve_limit", 3)

    messages = state.get("messages", [])
    if isinstance(messages, list) and any(isinstance(m, dict) for m in messages):
        try:
            messages = convert_to_messages(messages)
        except Exception:
            pass  # 保持原样

    query = _last_user_text_from_messages(messages)
    if not query:
        return {"messages": [AIMessage(content="无查询内容，跳过高级记忆检索", name="advanced_memory_retrieve")]}

    user_id = _resolve_user_id_from_config(config)
    manager = AdvancedMemoryManager(user_id, **{k: v for k, v in strategy.items() if k in [
        "token_limit", "categories", "classifier", "namespace_prefix"
    ]})

    try:
        memories = await manager.retrieve_memories(query, limit=limit)
    except Exception:
        logger.exception("advanced_memory_retrieve_node failed")
        memories = []
    memory_content = "\n".join(memories) if memories else "无相关高级记忆"

    return {
        "messages": [
            AIMessage(
                content=f"相关高级记忆：{memory_content}",
                name="advanced_memory_retrieve",
            )
        ]
    }


async def advanced_memory_write_node(
    state: dict[str, Any],
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    高级记忆写入节点。

    从 config.configurable.memory_strategy 中读取策略参数。
    """
    strategy = config.get("configurable", {}).get("memory_strategy", {})

    messages = state.get("messages", [])
    if isinstance(messages, list) and any(isinstance(m, dict) for m in messages):
        try:
            messages = convert_to_messages(messages)
        except Exception:
            pass  # 保持原样

    user_text = _last_user_text_from_messages(messages)
    if not user_text:
        return {}  # 无用户输入，跳过写入

    # 获取最后一条 AI 生成的回复（排除记忆检索消息）
    ai_response = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "name", "") not in {
            "advanced_memory_retrieve", "memory_retrieve", "knowledge_base_search"
        }:
            ai_response = _message_content_str(msg)
            break

    if not ai_response:
        return {}  # 无 AI 回复，跳过写入

    user_id = _resolve_user_id_from_config(config)
    manager = AdvancedMemoryManager(user_id, **{k: v for k, v in strategy.items() if k in [
        "token_limit", "categories", "classifier", "namespace_prefix"
    ]})

    # 计算当前轮次（简单按消息对数估算）
    turn_number = len([m for m in messages if isinstance(m, HumanMessage)])

    try:
        await manager.store_memory(user_text, ai_response, turn_number)
    except Exception:
        logger.exception("advanced_memory_write_node failed")

    return {}  # 不添加新消息

    return {}  # 不添加新消息


# 兼容旧版 LangMem 的简单节点（如果需要）
async def memory_retrieve_node(
    state: dict[str, Any],
    config: RunnableConfig,
    limit: int = 3,
    namespace_prefix: tuple[str, ...] = ("user_memories",),
) -> dict[str, Any]:
    """
    简单记忆检索节点（兼容旧版 LangMem）。

    使用简单的 LangMem 搜索，不分类。
    """
    messages = state.get("messages", [])
    if isinstance(messages, list) and any(isinstance(m, dict) for m in messages):
        try:
            messages = convert_to_messages(messages)
        except Exception:
            pass  # 保持原样

    query = _last_user_text_from_messages(messages)
    if not query:
        return {"messages": [AIMessage(content="无查询内容，跳过记忆检索", name="memory_retrieve")]}

    store = get_langgraph_store()
    user_id = _resolve_user_id_from_config(config)
    namespace = namespace_prefix + (str(user_id),)

    if store is None:
        logger.warning("memory_retrieve_node no custom store available, skipping memory retrieval")
        return {
            "messages": [
                AIMessage(content="无相关记忆（记忆存储未启用）", name="memory_retrieve")
            ]
        }

    memories = await store.asearch(namespace, query, limit=limit)
    memory_content = "\n".join([mem.value for mem in memories]) if memories else "无相关记忆"

    return {
        "messages": [
            AIMessage(
                content=f"相关记忆：{memory_content}",
                name="memory_retrieve",
            )
        ]
    }


async def memory_write_node(
    state: dict[str, Any],
    config: RunnableConfig,
    namespace_prefix: tuple[str, ...] = ("user_memories",),
    exclude_names: set[str] | None = None,
) -> dict[str, Any]:
    """
    简单记忆写入节点（兼容旧版 LangMem）。

    直接存储对话，不分类。
    """
    if exclude_names is None:
        exclude_names = {"memory_retrieve", "knowledge_base_search"}

    messages = state.get("messages", [])
    if isinstance(messages, list) and any(isinstance(m, dict) for m in messages):
        try:
            messages = convert_to_messages(messages)
        except Exception:
            pass  # 保持原样

    user_text = _last_user_text_from_messages(messages)
    if not user_text:
        return {}  # 无用户输入，跳过写入

    # 获取最后一条非排除的 AI 消息
    ai_response = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "name", "") not in exclude_names:
            ai_response = _message_content_str(msg)
            break

    if not ai_response:
        return {}  # 无 AI 回复，跳过写入

    store = get_langgraph_store()
    user_id = _resolve_user_id_from_config(config)
    namespace = namespace_prefix + (str(user_id),)

