"""模型调用相关的公共中间件（@wrap_model_call）。"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain.agents.middleware.types import wrap_model_call
from langgraph.config import get_config

from utils.llm_init import create_llm
from utils.sql_db import async_session

logger = logging.getLogger("agent.middleware.model")



@wrap_model_call
async def filter_tools_by_enabled_config(request, handler):
    """按 configurable.enabled_tools 过滤工具。"""
    config = get_config() or {}
    enabled = (config.get("configurable") or {}).get("enabled_tools")
    if enabled is None:
        return await handler(request)
    allowed = set(enabled)
    filtered = [
        t for t in (request.tools or [])
        if (n := _tool_entry_name(t)) and n in allowed
    ]
    logger.info("tools_filtered allowed=%s bound=%s", sorted(allowed), len(filtered))
    return await handler(request.override(tools=filtered))


def _tool_entry_name(entry: Any) -> str | None:
    """提取工具名称的辅助函数。"""
    if hasattr(entry, "name"):
        n = getattr(entry, "name", None)
        return str(n) if n is not None else None
    if isinstance(entry, dict):
        n = entry.get("name")
        return str(n) if n is not None else None
    return None


def _tool_entry_name(entry):
    """提取工具名称的辅助函数。"""
    if hasattr(entry, "name"):
        return getattr(entry, "name", None)
    if isinstance(entry, dict):
        return entry.get("name")
    return None


@wrap_model_call
async def inject_llm_from_global_settings(request, handler):
    """根据 configurable.user_id 从数据库加载对应 LLM 并注入。

    这是服务注入型中间件，依赖数据库 session 和 LLM 初始化。
    """
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
    if isinstance(resp, dict) and "messages" in resp:
        last = resp["messages"][-1] if resp.get("messages") else {}
        if isinstance(last, dict) and last.get("tool_calls"):
            tool_calls_n = len(last["tool_calls"])
    elif hasattr(resp, "tool_calls") and resp.tool_calls:
        tool_calls_n = len(resp.tool_calls)

    logger.info(
        "model_step end user_id=%s ms=%.0f tool_calls_in_reply=%s",
        user_id,
        elapsed_ms,
        tool_calls_n,
    )
    return resp
