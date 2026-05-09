"""Agent tools for LangGraph graph."""

from __future__ import annotations

from infra.memory import LANGMEM_TOOLS
from agent.tools.decorators import hidden_from_client
from agent.tools.vector_search import milvus_search

# LangMem 工具由第三方工厂创建，统一标记为不对前端暴露
ALL_AGENT_TOOLS = [
    milvus_search,
    *[hidden_from_client(t) for t in LANGMEM_TOOLS],
]


def tool_catalog() -> list[dict[str, str | None]]:
    """全部注册工具的名称与说明（含不对前端暴露的基础工具）。

    面向前端的列表请使用 ``agent.tools.registry.tool_catalog_for_client``。
    """
    rows: list[dict[str, str | None]] = []
    for t in ALL_AGENT_TOOLS:
        rows.append(
            {
                "name": t.name,
                "description": (getattr(t, "description", None) or "").strip() or None,
            }
        )
    return rows
