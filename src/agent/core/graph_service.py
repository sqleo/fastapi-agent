"""示例：按 LangGraph 文档风格的「路由 → 检索 → 生成」线性图（独立图文件，与其它 Agent 模式解耦）."""

from __future__ import annotations

import logging
import os
import re
from typing import Annotated, Any, Literal

from langchain_core.callbacks.manager import AsyncCallbackManager
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    convert_to_messages,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import patch_config
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agent.memory.graph_checkpoint import get_graph_checkpointer
from agent.memory.langmem import get_langgraph_store
from agent.memory.memory_nodes import (
    short_term_window_node,
    advanced_memory_retrieve_node,
    advanced_memory_write_node,
)
from agent.tools.knowledge_base_search import knowledge_base_search
from utils.llm_init import create_llm
from utils.sql_db import async_session

logger = logging.getLogger("agent.graph_service")

_NO_ANSWER_TEXT = "根据提供的资料，无法找到相关答案。"
_DIRECT_REPLY = "您需要了解产品与服务相关的问题吗？请告诉我具体问题～"
_NON_PRODUCT_REPLY = "抱歉，我只能回答关于产品和服务相关的问题。如果您有相关疑问，请告诉我！"

_ROUTER_SYSTEM = """你是路由分类器：判断用户这句话是否需要从知识库检索「产品、服务、规格、文档、功能」等才能回答。

规则：
- 需要检索 → 只回复一个词：rag
- 不需要（问候、闲聊、致谢或与业务无关等）→ 只回复一个词：direct
不要输出其它任何字符。"""

_ANSWER_SYSTEM = """基于下面「检索上下文」回答用户问题，简洁、可操作；不足则说明信息不足。

【检索上下文】
{retrieved_context}

【用户问题】
{user_query}"""

_NextRoute = Literal["retrieve", "end"]


def _next_route_reducer(
    left: _NextRoute | None,
    right: _NextRoute | None,
) -> _NextRoute | None:
    """分类节点单次写入覆盖路由；首帧为 ``None``。"""
    return right if right is not None else left


class ServiceState(TypedDict):
    """``messages`` 走 ``add_messages``；``next_route`` 供 ``add_conditional_edges`` 使用。"""
    messages: Annotated[list[AnyMessage], add_messages]
    next_route: Annotated[_NextRoute | None, _next_route_reducer]


def _last_user_text(state: ServiceState) -> str:
    """取最近一条用户话；兼容 LangGraph Studio 等入口里仍为 ``dict`` 的 message。"""
    raw = state.get("messages") or []
    if not raw:
        return ""
    if any(isinstance(m, dict) for m in raw):
        try:
            msgs = convert_to_messages(raw)
        except Exception:
            msgs = raw
    else:
        msgs = raw
    for m in reversed(msgs):
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


def _parse_config_user_id(raw: object) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    s = str(raw).strip()
    if not s:
        return None
    try:
        n = int(s)
    except ValueError:
        return None
    return n if n > 0 else None


def _resolve_user_id(config: RunnableConfig | None) -> int:
    configurable = (config or {}).get("configurable") or {}
    uid = _parse_config_user_id(configurable.get("user_id"))
    if uid is not None:
        return uid
    fb = (os.environ.get("LANGGRAPH_DEV_USER_ID") or "").strip()
    if fb:
        uid = _parse_config_user_id(fb)
        if uid is not None:
            logger.warning(
                "configurable.user_id 未传入，已使用 LANGGRAPH_DEV_USER_ID=%s（仅本地调试用）",
                uid,
            )
            return uid
    raise ValueError(
        "缺少有效的 configurable.user_id（须为正整数），无法创建会话级 LLM",
    )


def _needs_rag_from_text(body: str) -> bool:
    """解析路由模型输出：rag / direct。"""
    s = body.strip().lower()
    if "rag" in s and "direct" not in s:
        return True
    if "direct" in s and "rag" not in s:
        return False
    if re.match(r"^\s*rag\s*$", s, re.I):
        return True
    if re.match(r"^\s*direct\s*$", s, re.I):
        return False
    return True


async def _run_router(llm: Any, text: str, parent: RunnableConfig | None) -> bool:
    """内部路由 LLM：使用独立 callback，避免 token 进入 LangGraph messages 流。"""
    invoke_cfg = patch_config(parent, callbacks=AsyncCallbackManager([]))
    base = [
        SystemMessage(content=_ROUTER_SYSTEM),
        HumanMessage(content=text),
    ]
    resp = await llm.ainvoke(base, config=invoke_cfg)
    return _needs_rag_from_text(_message_content_str(resp))


async def classify_node(state: ServiceState, config: RunnableConfig) -> dict[str, Any]:
    """写出 ``next_route``，由 ``add_conditional_edges`` 决定去检索或结束。"""
    text = _last_user_text(state)

    if not text:
        return {
            "messages": [AIMessage(content=_DIRECT_REPLY)],
            "next_route": "end",
        }

    user_id = _resolve_user_id(config)
    async with async_session() as session:
        llm = await create_llm(session, user_id, temperature_override=0.0)
    if not await _run_router(llm, text, config):
        return {
            "messages": [AIMessage(content=_NON_PRODUCT_REPLY)],
            "next_route": "end",
        }
    return {"next_route": "retrieve"}


async def retrieve_node(state: ServiceState, config: RunnableConfig) -> dict[str, Any]:
    query = _last_user_text(state)
    result = await knowledge_base_search.ainvoke(
        {"query": query, "top_k": 5},
        config=config,
    )
    return {
        "messages": [
            AIMessage(
                content=str(result),
                name="knowledge_base_search",
            )
        ]
    }


async def generate_node(state: ServiceState, config: RunnableConfig) -> dict[str, Any]:
    query = _last_user_text(state)

    # 从消息历史中查找知识库检索结果
    retrieved_context = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage) and getattr(msg, "name", "") == "knowledge_base_search":
            retrieved_context = _message_content_str(msg)
            break

    # 如果没有检索结果，使用默认消息
    if not retrieved_context.strip():
        retrieved_context = "无检索到的相关知识库内容。"

    prompt = _ANSWER_SYSTEM.format(retrieved_context=retrieved_context, user_query=query)
    user_id = _resolve_user_id(config)

    async with async_session() as session:
        llm = await create_llm(session, user_id, temperature_override=0.1)
    response = await llm.ainvoke(
        [
            SystemMessage(content=prompt),
            HumanMessage(content=query),
        ],
        config=config,
    )
    return {"messages": [response]}


def route_after_classify(state: ServiceState) -> Literal["retrieve", END]:
    if state.get("next_route") == "retrieve":
        return "retrieve"
    return END


_builder = (
    StateGraph(ServiceState)
    .add_node("short_term_window", short_term_window_node)
    .add_node("classify", classify_node)
    .add_node("retrieve", retrieve_node)
    .add_node("advanced_memory_retrieve", advanced_memory_retrieve_node)
    .add_node("generate", generate_node)
    .add_node("advanced_memory_write", advanced_memory_write_node)
    .add_edge(START, "short_term_window")
    .add_edge("short_term_window", "classify")
    .add_conditional_edges("classify", route_after_classify)
    .add_edge("retrieve", "advanced_memory_retrieve")
    .add_edge("advanced_memory_retrieve", "generate")
    .add_edge("generate", "advanced_memory_write")
    .add_edge("advanced_memory_write", END)
)

graph = _builder.compile(
    name="graph_service",
)

# 用于直连调用的 graph（带 checkpointer 和 LangMem store）
graph_with_checkpoint = _builder.compile(
    checkpointer=get_graph_checkpointer(),
    store=get_langgraph_store(),
    name="graph_service_direct",
)
