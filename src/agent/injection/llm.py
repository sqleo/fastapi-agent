"""LLM 服务注入中间件。

强依赖 utils.llm_init 和数据库 session，用于动态根据 user_id 加载 LLM 配置。
同时自动采集 Token 用量、延迟、错误等监控指标写入 PostgreSQL（ORM）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid as _uuid

from langchain.agents.middleware.types import wrap_model_call
from langgraph.config import get_config

from utils.llm_init import create_llm
from utils.sql_db import async_session

logger = logging.getLogger("agent.injection.llm")


def _unwrap_message(resp):
    """从 ModelResponse / dict 中提取实际的 AIMessage。"""
    result = getattr(resp, "result", None)
    if result and isinstance(result, list) and len(result) > 0:
        return result[-1]
    if isinstance(resp, dict) and "messages" in resp:
        msgs = resp["messages"]
        if msgs:
            return msgs[-1]
    return resp


def _extract_usage(resp) -> dict:
    """从 LangChain 响应中提取 token 用量和缓存信息。

    支持 ModelResponse(result=[AIMessage(...)]) 和直接 AIMessage 两种格式。
    优先从 usage_metadata 取，兜底从 response_metadata.token_usage 取。
    """
    info: dict = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}

    msg = _unwrap_message(resp)

    # --- 优先: usage_metadata（LangChain ≥0.2 标准字段）---
    usage = getattr(msg, "usage_metadata", None)
    if usage:
        if isinstance(usage, dict):
            info["input_tokens"] = usage.get("input_tokens", 0) or 0
            info["output_tokens"] = usage.get("output_tokens", 0) or 0
            details = usage.get("input_token_details") or {}
            if isinstance(details, dict):
                info["cache_read_tokens"] = details.get("cache_read", 0) or 0
            cr_top = usage.get("cache_read_input_tokens")
            if cr_top:
                info["cache_read_tokens"] = max(
                    int(info["cache_read_tokens"]), int(cr_top)
                )
        else:
            info["input_tokens"] = getattr(usage, "input_tokens", 0) or 0
            info["output_tokens"] = getattr(usage, "output_tokens", 0) or 0
            details = getattr(usage, "input_token_details", None)
            if details:
                info["cache_read_tokens"] = getattr(details, "cache_read", 0) or 0
        if info["input_tokens"] or info["output_tokens"]:
            return info

    # --- 兜底: response_metadata.token_usage（OpenAI 兼容接口）---
    resp_meta = getattr(msg, "response_metadata", None) or {}
    if isinstance(resp_meta, dict):
        token_usage = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
        if isinstance(token_usage, dict):
            info["input_tokens"] = (
                token_usage.get("prompt_tokens", 0)
                or token_usage.get("input_tokens", 0)
                or 0
            )
            info["output_tokens"] = (
                token_usage.get("completion_tokens", 0)
                or token_usage.get("output_tokens", 0)
                or 0
            )
            # OpenAI prompt caching 等：cached 计入命中
            cr = token_usage.get("cached_tokens") or token_usage.get("cache_read_input_tokens")
            if cr:
                info["cache_read_tokens"] = max(info["cache_read_tokens"], int(cr))

    if not info["input_tokens"] and not info["output_tokens"]:
        logger.debug(
            "无法提取 token 用量 usage_metadata=%s response_metadata=%s",
            getattr(resp, "usage_metadata", None),
            resp_meta,
        )

    return info


def _classify_error(exc: Exception) -> tuple[str, str]:
    """返回 (error_type, error_category)。"""
    msg = str(exc).lower()

    if "rate" in msg and "limit" in msg:
        return "rate_limit", "provider"
    if "timeout" in msg or isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "timeout", "infra"
    if "context" in msg and ("length" in msg or "window" in msg):
        return "context_overflow", "client"
    if any(k in msg for k in ("api_key", "authentication", "unauthorized")):
        return "invalid_api_key", "client"
    if "content" in msg and "filter" in msg:
        return "content_filter", "content"
    if "overloaded" in msg or "capacity" in msg:
        return "model_overloaded", "provider"

    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int):
        if status == 429:
            return "rate_limit", "provider"
        if 400 <= status < 500:
            return "invalid_request", "client"
        if status >= 500:
            return "server_error", "provider"

    if "connection" in msg or "network" in msg:
        return "network_error", "infra"

    return type(exc).__name__, "unknown"


def _parse_uuid(val: str | None) -> _uuid.UUID | None:
    if not val:
        return None
    try:
        return _uuid.UUID(val)
    except (ValueError, AttributeError):
        return None


def _parse_config_user_id(raw: object) -> int | None:
    """解析 ``configurable.user_id``：非空且可转为正整数则返回，否则 ``None``。"""
    if raw is None:
        return None
    if isinstance(raw, bool):
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


async def _persist_monitoring(log, session_uuid, user_id, thread_id, total_tokens):
    """后台持久化监控数据，异常只记日志不影响业务。"""
    try:
        from monitor.collector import save_request_log, upsert_session

        await save_request_log(log)

        if session_uuid:
            await upsert_session(
                session_id=session_uuid,
                user_id=user_id,
                thread_id=thread_id,
                add_tokens=total_tokens,
            )
    except Exception:
        logger.warning("monitoring persist failed", exc_info=True)


@wrap_model_call
async def inject_llm_from_global_settings(request, handler):
    """根据 configurable.user_id 从数据库加载对应 LLM 并注入。
    """
    config = get_config()
    configurable = config.get("configurable") or {}
    user_id_raw = configurable.get("user_id")
    user_id = _parse_config_user_id(user_id_raw)
    thread_id = configurable.get("thread_id")

    if user_id is None:
        # LangGraph Studio / langgraph dev 有时不会把 Assistant 默认配置合并进 run.config；
        # 本地调试可在 .env 设置 LANGGRAPH_DEV_USER_ID（勿在生产环境依赖）。
        fb = (os.environ.get("LANGGRAPH_DEV_USER_ID") or "").strip()
        if fb:
            user_id = _parse_config_user_id(fb)
            if user_id is not None:
                logger.warning(
                    "configurable.user_id 未传入，已使用 LANGGRAPH_DEV_USER_ID=%s（仅本地调试用）",
                    user_id,
                )

    if user_id is None:
        logger.error(
            "model_step 缺少有效的 configurable.user_id（当前值=%r）",
            user_id_raw,
        )
        raise ValueError(
            "LangGraph 调用缺少有效的 configurable.user_id（须为正整数，不能为空字符串），"
            "无法加载 LLM 全局设置",
        )

    n_msg = len(request.messages or [])
    n_tools = len(request.tools or [])
    logger.info(
        "model_step start user_id=%s messages=%s tools_bound=%s",
        user_id, n_msg, n_tools,
    )

    model_label = "unknown"
    provider_label = "unknown"
    session_uuid = _parse_uuid(thread_id)

    t0 = time.perf_counter()
    try:
        override = configurable.get("llm_temperature")
        temperature_override = float(override) if override is not None else None
        async with async_session() as session:
            llm = await create_llm(
                session,
                user_id,
                temperature_override=temperature_override,
            )

        model_label = (
            getattr(llm, "model_name", None)
            or getattr(llm, "model", None)
            or "unknown"
        )
        provider_label = type(llm).__name__
        logger.info("model_step llm_ready model=%s", model_label)

        resp = await handler(request.override(model=llm))
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.exception(
            "model_step failed user_id=%s after_ms=%.0f",
            user_id, elapsed_ms,
        )

        error_type, error_category = _classify_error(exc)
        from monitor.models import RequestLog

        log = RequestLog(
            session_id=session_uuid,
            provider=provider_label,
            model=model_label,
            latency_ms=int(elapsed_ms),
            status="error",
            error_type=error_type,
            error_category=error_category,
            error_message=str(exc)[:1000],
            user_id=user_id,
        )
        asyncio.create_task(_persist_monitoring(log, session_uuid, user_id, thread_id, 0))
        raise

    elapsed_ms = (time.perf_counter() - t0) * 1000

    usage = _extract_usage(resp)
    input_tokens = usage["input_tokens"]
    output_tokens = usage["output_tokens"]
    cache_read = usage["cache_read_tokens"]
    input_cache_hit = int(cache_read)
    input_cache_miss = max(0, int(input_tokens) - input_cache_hit)

    msg = _unwrap_message(resp)
    tool_calls_n = 0
    if isinstance(msg, dict) and msg.get("tool_calls"):
        tool_calls_n = len(msg["tool_calls"])
    elif hasattr(msg, "tool_calls") and msg.tool_calls:
        tool_calls_n = len(msg.tool_calls)

    logger.info(
        "model_step end user_id=%s model=%s ms=%.0f "
        "in_tokens=%s out_tokens=%s in_hit=%s in_miss=%s tool_calls=%s",
        user_id, model_label, elapsed_ms,
        input_tokens, output_tokens, input_cache_hit, input_cache_miss, tool_calls_n,
    )

    from monitor.models import RequestLog

    log = RequestLog(
        session_id=session_uuid,
        provider=provider_label,
        model=model_label,
        input_tokens=input_tokens,
        input_tokens_cache_hit=input_cache_hit,
        input_tokens_cache_miss=input_cache_miss,
        output_tokens=output_tokens,
        latency_ms=int(elapsed_ms),
        status="success",
        is_cache_hit=input_cache_hit > 0,
        cache_tokens_saved=input_cache_hit,
        user_id=user_id,
        extra={"tool_calls": tool_calls_n},
    )
    asyncio.create_task(
        _persist_monitoring(log, session_uuid, user_id, thread_id, input_tokens + output_tokens)
    )

    return resp
