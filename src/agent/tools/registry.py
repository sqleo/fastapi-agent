"""工具注册：按 ``hidden_from_client`` 装饰器登记的信息区分前后端可见性。"""

from __future__ import annotations

from agent.tools.decorators import is_exposed_to_client
from agent.tools.tools import ALL_AGENT_TOOLS


def all_registered_tool_names() -> frozenset[str]:
    """图中注册的全部工具名。"""
    return frozenset(t.name for t in ALL_AGENT_TOOLS)


def hidden_from_client_tool_names() -> frozenset[str]:
    """不返回给前端的工具名。"""
    return frozenset(t.name for t in ALL_AGENT_TOOLS if not is_exposed_to_client(t))


def exposed_tool_names() -> frozenset[str]:
    """可对用户展示开关的工具名。"""
    return frozenset(t.name for t in ALL_AGENT_TOOLS if is_exposed_to_client(t))


def tool_catalog_for_client() -> list[dict[str, str | None]]:
    """供 GET /agent/tools：仅对前端暴露的工具。"""
    rows: list[dict[str, str | None]] = []
    for t in ALL_AGENT_TOOLS:
        if not is_exposed_to_client(t):
            continue
        rows.append(
            {
                "name": t.name,
                "description": (getattr(t, "description", None) or "").strip() or None,
            }
        )
    return rows


def merge_enabled_with_hidden(selection: list[str] | None) -> list[str] | None:
    """将不向客户端暴露的工具并入启用列表，避免被误关。

    - ``None``：不限制（LangGraph 使用全部工具）。
    - 非空列表：与用户选择取并集（含隐藏工具名）。
    """
    if selection is None:
        return None
    hidden = hidden_from_client_tool_names()
    if not hidden:
        return list(selection)
    return sorted(set(selection) | set(hidden))
