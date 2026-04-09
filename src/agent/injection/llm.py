"""LLM 服务注入中间件。

强依赖 utils.llm_init 和数据库 session，用于动态根据 user_id 加载 LLM 配置。
"""

from __future__ import annotations

import logging
import time

from langchain.agents.middleware.types import wrap_model_call
from langgraph.config import get_config

from utils.llm_init import create_llm
from utils.sql_db import async_session

logger = logging.getLogger("agent.injection.llm")


@wrap_model_call
async def inject_llm_from_global_settings(request, handler):
    """根据 configurable.user_id 从数据库加载对应 LLM 并注入。

    这是一个典型的「注入型」中间件，依赖数据库和 LLM 初始化逻辑，
    因此单独放在 injection/ 目录下，而非纯技术 middleware/。
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
        last_message = resp["messages"][-1] if resp["messages"] else {}
        if isinstance(last_message, dict) and last_message.get("tool_calls"):
            tool_calls_n = len(last_message["tool_calls"])
    elif hasattr(resp, "tool_calls") and resp.tool_calls:
        tool_calls_n = len(resp.tool_calls)

    logger.info(
        "model_step end user_id=%s ms=%.0f tool_calls_in_reply=%s",
        user_id,
        elapsed_ms,
        tool_calls_n,
    )
    return resp
