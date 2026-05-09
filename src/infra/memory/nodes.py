"""通用记忆节点：支持 LangMem 的检索和写入，可在任何 LangGraph 中复用。"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import convert_to_messages

from infra.langgraph import get_langgraph_store
from infra.memory.advanced_memory import AdvancedMemoryManager
from infra.memory.turns import message_text, take_last_turns

logger = logging.getLogger("infra.memory.nodes")


def _last_user_text_from_messages(messages: list[AnyMessage]) -> str:
    """从消息列表中提取最后一条用户文本。"""
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
    """提取消息内容为字符串。"""
    return message_text(msg)


def _resolve_user_id_from_config(config: RunnableConfig | None) -> int:
    """从 config 中解析 user_id。"""
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


def _normalize_messages(messages: list) -> list:
    if isinstance(messages, list) and any(isinstance(m, dict) for m in messages):
        try:
            return convert_to_messages(messages)
        except Exception:
            pass
    return messages


async def short_term_window_node(
    state: dict[str, Any],
    config: RunnableConfig,
) -> dict[str, Any]:
    """短期记忆滑动窗口节点。"""
    strategy = config.get("configurable", {}).get("memory_strategy", {})
    max_turns = strategy.get("max_turns", 3)
    messages = _normalize_messages(state.get("messages", []))
    if not messages:
        return {"messages": []}
    retained_messages = take_last_turns(messages, max_turns=max_turns)
    return {"messages": retained_messages}


async def advanced_memory_retrieve_node(
    state: dict[str, Any],
    config: RunnableConfig,
) -> dict[str, Any]:
    """高级记忆检索节点。"""
    strategy = config.get("configurable", {}).get("memory_strategy", {})
    limit = strategy.get("retrieve_limit", 3)
    messages = _normalize_messages(state.get("messages", []))
    query = _last_user_text_from_messages(messages)
    if not query:
        return {"messages": [AIMessage(content="无查询内容，跳过高级记忆检索", name="advanced_memory_retrieve")]}

    user_id = _resolve_user_id_from_config(config)
    manager = AdvancedMemoryManager(
        user_id,
        **{k: v for k, v in strategy.items() if k in ["token_limit", "categories", "classifier", "namespace_prefix"]},
    )
    try:
        memories = await manager.retrieve_memories(query, limit=limit)
    except Exception:
        logger.exception("advanced_memory_retrieve_node failed")
        memories = []

    memory_content = "\n".join(memories) if memories else "无相关高级记忆"
    return {
        "messages": [
            AIMessage(content=f"相关高级记忆：{memory_content}", name="advanced_memory_retrieve")
        ]
    }


async def advanced_memory_write_node(
    state: dict[str, Any],
    config: RunnableConfig,
) -> dict[str, Any]:
    """高级记忆写入节点。"""
    strategy = config.get("configurable", {}).get("memory_strategy", {})
    messages = _normalize_messages(state.get("messages", []))
    user_text = _last_user_text_from_messages(messages)
    logger.info("advanced_memory_write configurable=%s", (config or {}).get("configurable"))
    if not user_text:
        return {}
    ai_response = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "name", "") not in {
            "advanced_memory_retrieve", "memory_retrieve", "knowledge_base_search"
        }:
            ai_response = _message_content_str(msg)
            break

    if not ai_response:
        return {}

    user_id = _resolve_user_id_from_config(config)
    manager = AdvancedMemoryManager(
        user_id,
        **{k: v for k, v in strategy.items() if k in ["token_limit", "categories", "classifier", "namespace_prefix"]},
    )
    turn_number = len([m for m in messages if isinstance(m, HumanMessage)])
    try:
        await manager.store_memory(user_text, ai_response, turn_number)
    except Exception:
        logger.exception("advanced_memory_write_node failed")
    return {}


async def memory_retrieve_node(
    state: dict[str, Any],
    config: RunnableConfig,
    limit: int = 3,
    namespace_prefix: tuple[str, ...] = ("user_memories",),
) -> dict[str, Any]:
    """简单记忆检索节点（兼容旧版 LangMem）。"""
    messages = _normalize_messages(state.get("messages", []))
    query = _last_user_text_from_messages(messages)
    if not query:
        return {"messages": [AIMessage(content="无查询内容，跳过记忆检索", name="memory_retrieve")]}
    store = get_langgraph_store()
    user_id = _resolve_user_id_from_config(config)

    if store is None:
        logger.warning("memory_retrieve_node no custom store available, skipping memory retrieval")
        return {"messages": [AIMessage(content="无相关记忆（记忆存储未启用）", name="memory_retrieve")]}

    ns = namespace_prefix + (str(user_id),)
    memories = await store.asearch(ns, query=query, limit=limit)

    def _item_text(m: Any) -> str:
        v = m.value
        if isinstance(v, dict):
            return str(v.get("content", v))
        return str(v)

    memory_content = "\n".join(_item_text(mem) for mem in memories) if memories else "无相关记忆"
    return {
        "messages": [AIMessage(content=f"相关记忆：{memory_content}", name="memory_retrieve")]
    }


async def memory_write_node(
    state: dict[str, Any],
    config: RunnableConfig,
    namespace_prefix: tuple[str, ...] = ("user_memories",),
    exclude_names: set[str] | None = None,
) -> dict[str, Any]:
    """简单记忆写入节点（兼容旧版 LangMem）。"""
    if exclude_names is None:
        exclude_names = {"memory_retrieve", "knowledge_base_search"}

    messages = _normalize_messages(state.get("messages", []))
    user_text = _last_user_text_from_messages(messages)
    if not user_text:
        return {}

    ai_response = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "name", "") not in exclude_names:
            ai_response = _message_content_str(msg)
            break

    if not ai_response:
        return {}

    store = get_langgraph_store()
    user_id = _resolve_user_id_from_config(config)

    if store is None:
        logger.warning("memory_write_node no custom store available, skipping memory write")
        return {}

    import uuid

    key = str(uuid.uuid4())
    content = f"用户: {user_text}\nAI: {ai_response}"
    ns = namespace_prefix + (str(user_id),)
    await store.aput(ns, key, {"content": content})
    return {}
