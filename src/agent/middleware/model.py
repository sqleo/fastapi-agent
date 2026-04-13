"""模型调用相关的公共中间件（@wrap_model_call）。"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware.types import wrap_model_call
from langgraph.config import get_config

from agent.injection.llm import inject_llm_from_global_settings

logger = logging.getLogger("agent.middleware.model")

__all__ = ["filter_tools_by_enabled_config", "inject_llm_from_global_settings"]


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
