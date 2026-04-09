"""工具策略：在模型输出进入 ToolNode 之前，去掉未启用的 tool_calls。

与 ``filter_tools_by_enabled_config`` 配合：前者限制 bind_tools，本中间件防止模型
仍产出禁用工具名（幻觉或历史干扰）时进入执行阶段，避免「先调用再拦截」的体验。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from langchain.agents.middleware.types import ExtendedModelResponse, ModelResponse, wrap_model_call
from langchain_core.messages import AIMessage
from langgraph.config import get_config

logger = logging.getLogger("agent.middleware.tool_policy")


def _tool_call_name(tc: Any) -> str:
    if isinstance(tc, dict):
        return str(tc.get("name") or "")
    return str(getattr(tc, "name", "") or "")


def _strip_ai_tool_calls(msg: Any, allowed: set[str]) -> Any:
    if not isinstance(msg, AIMessage):
        return msg
    tcs = getattr(msg, "tool_calls", None) or []
    if not tcs:
        return msg
    kept = [tc for tc in tcs if _tool_call_name(tc) in allowed]
    if len(kept) == len(tcs):
        return msg
    if not kept:
        logger.info(
            "strip_tool_calls: removed %d disallowed tool_calls (not in enabled_tools)",
            len(tcs),
        )
    else:
        logger.info(
            "strip_tool_calls: kept %d/%d tool_calls matching enabled_tools",
            len(kept),
            len(tcs),
        )
    return msg.model_copy(update={"tool_calls": kept})


def _strip_model_response(resp: Any, allowed: set[str]) -> Any:
    if isinstance(resp, ExtendedModelResponse):
        inner = _strip_model_response(resp.model_response, allowed)
        return replace(resp, model_response=inner)
    if isinstance(resp, ModelResponse):
        new_result = [_strip_ai_tool_calls(m, allowed) for m in resp.result]
        return ModelResponse(
            result=new_result,
            structured_response=resp.structured_response,
        )
    if isinstance(resp, AIMessage):
        return _strip_ai_tool_calls(resp, allowed)
    return resp


@wrap_model_call
async def strip_tool_calls_not_in_enabled_list(request, handler):
    """若 configurable.enabled_tools 为列表，则从模型输出中剔除不在列表内的 tool_calls。"""
    resp = await handler(request)
    config = get_config() or {}
    enabled = (config.get("configurable") or {}).get("enabled_tools")
    if enabled is None:
        return resp
    allowed = set(enabled)
    return _strip_model_response(resp, allowed)
