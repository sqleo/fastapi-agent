"""工具调用相关的公共中间件（@wrap_tool_call）。"""

from __future__ import annotations

from langchain_core.messages import ToolMessage
from langgraph.config import get_config

from agent.middleware import wrap_tool_call


@wrap_tool_call
async def block_disabled_tool_execution(request, handler):
    """阻止已禁用工具的执行（公共版本）。"""
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
