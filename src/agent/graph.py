"""LangGraph Agent：基于 LangChain ``create_agent``，模型来自数据库 LLM 全局设置.

运行需在 ``RunnableConfig.configurable`` 中传入 ``user_id``（与 FastAPI 当前用户一致）。
可选 ``enabled_tools: list[str]``：仅允许列出的工具名参与模型绑定与执行；不传则全部可用，``[]`` 则禁用所有工具。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware.types import wrap_model_call, wrap_tool_call
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_config

from agent.tools import ALL_AGENT_TOOLS
from utils.langgraph_sse_error_patch import apply_vendor_api_sse_patch
from utils.llm_init import create_llm
from utils.sql_db import async_session

apply_vendor_api_sse_patch()

logger = logging.getLogger("agent.graph")

tools = ALL_AGENT_TOOLS


def _tool_entry_name(entry: Any) -> str | None:
    if entry is None:
        return None
    if hasattr(entry, "name"):
        n = getattr(entry, "name", None)
        return str(n) if n is not None else None
    if isinstance(entry, dict):
        n = entry.get("name")
        return str(n) if n is not None else None
    return None


@wrap_model_call
async def _filter_tools_by_enabled_config(request, handler):
    """按 ``configurable.enabled_tools`` 限制模型可见工具；未传则全部可用."""
    config = get_config() or {}
    enabled = (config.get("configurable") or {}).get("enabled_tools")
    if enabled is None:
        return await handler(request)
    allowed = set(enabled)
    filtered = [t for t in (request.tools or []) if (n := _tool_entry_name(t)) and n in allowed]
    logger.info("tools_filtered allowed=%s bound=%s", sorted(allowed), len(filtered))
    return await handler(request.override(tools=filtered))


@wrap_tool_call
async def _block_disabled_tool_execution(request, handler):
    """防止历史线程里已生成的 tool_call 在用户关闭工具后仍被执行."""
    config = get_config() or {}
    enabled = (config.get("configurable") or {}).get("enabled_tools")
    if enabled is None:
        return await handler(request)
    allowed = set(enabled)
    call = request.tool_call or {}
    name = str(call.get("name") or "")
    if name not in allowed:
        return ToolMessage(
            content=f"工具「{name}」已被用户关闭，本次不会执行。",
            tool_call_id=str(call.get("id") or ""),
        )
    return await handler(request)

# create_agent 要求静态传入 model；真实模型在每次调用时由中间件按 user_id 从全局设置加载。
_placeholder_model = init_chat_model(
    "placeholder",
    model_provider="openai",
    base_url="https://api.openai.com/v1",
    api_key="placeholder-unused",
)


@wrap_model_call
async def _inject_llm_from_global_settings(request, handler):
    config = get_config()
    user_id = (config.get("configurable") or {}).get("user_id")
    if user_id is None:
        logger.error("model_step 缺少 configurable.user_id")
        raise ValueError("LangGraph 调用缺少 configurable.user_id，无法加载 LLM 全局设置")
    n_msg = len(request.messages or [])
    n_tools = len(request.tools or [])
    logger.info(
        "model_step start user_id=%s messages=%s tools_bound=%s",
        user_id,
        n_msg,
        n_tools,
    )
    t0 = time.perf_counter()
    try:
        async with async_session() as session:
            llm = await create_llm(session, int(user_id))
        model_label = getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"
        logger.info("model_step llm_ready model=%s", model_label)
        resp = await handler(request.override(model=llm))
    except Exception:
        logger.exception(
            "model_step failed user_id=%s after_ms=%.0f",
            user_id,
            (time.perf_counter() - t0) * 1000,
        )
        raise
    elapsed_ms = (time.perf_counter() - t0) * 1000
    tool_calls_n = 0
    if isinstance(resp, AIMessage) and resp.tool_calls:
        tool_calls_n = len(resp.tool_calls)
    else:
        res = getattr(resp, "result", None)
        if isinstance(res, list):
            for m in res:
                if isinstance(m, AIMessage) and m.tool_calls:
                    tool_calls_n += len(m.tool_calls)
    logger.info(
        "model_step end user_id=%s ms=%.0f tool_calls_in_reply=%s",
        user_id,
        elapsed_ms,
        tool_calls_n,
    )
    return resp


graph = create_agent(
    _placeholder_model,
    tools=tools,
    middleware=[
        _filter_tools_by_enabled_config,
        _inject_llm_from_global_settings,
        _block_disabled_tool_execution,
    ],
    name="Agent",
)
