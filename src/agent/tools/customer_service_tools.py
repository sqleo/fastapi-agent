"""智能客服 Agent 专用工具集：知识库检索 + LangMem（可在此扩展更多工具）."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent.memory.langmem import LANGMEM_TOOLS
from agent.tools.decorators import hidden_from_client
from agent.tools.knowledge_base_search import knowledge_base_search

# 预留：后续可 append 工单、订单查询等
ALL_CUSTOMER_SERVICE_TOOLS = [
    knowledge_base_search,
    *[hidden_from_client(t) for t in LANGMEM_TOOLS],
]


def tools_summary_markdown(tools: Sequence[Any], *, max_line_len: int = 200) -> str:
    """从 LangChain Tool 对象生成注入 system prompt 的简短 Markdown 列表。"""
    lines: list[str] = []
    for t in tools:
        name = getattr(t, "name", None) or "tool"
        desc = (getattr(t, "description", None) or "").strip()
        first = desc.split("\n", 1)[0].strip() if desc else ""
        if len(first) > max_line_len:
            first = first[: max_line_len - 1] + "…"
        lines.append(f"- **{name}**：{first}" if first else f"- **{name}**")
    if not lines:
        return "（当前无已注册工具）"
    return "\n".join(lines)


def customer_service_tool_names() -> list[str]:
    """当前图中注册的全部工具名（用于默认 enabled_tools）。"""
    return [t.name for t in ALL_CUSTOMER_SERVICE_TOOLS]


def customer_service_hidden_tool_names() -> frozenset[str]:
    """智能客服场景下不对前端展示、但必须保持启用的工具（与 LangMem 一致）。"""
    from agent.tools.decorators import is_exposed_to_client_named

    return frozenset(
        n for n in (t.name for t in ALL_CUSTOMER_SERVICE_TOOLS) if not is_exposed_to_client_named(n)
    )


def merge_customer_service_enabled_tools(selection: list[str] | None) -> list[str]:
    """合并用户选择与隐藏工具；``None`` 表示使用智能客服默认工具全集。"""
    base = customer_service_tool_names()
    if selection is None:
        return list(base)
    hidden = customer_service_hidden_tool_names()
    return sorted(set(selection) | set(hidden))
