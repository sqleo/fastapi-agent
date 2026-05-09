"""LangMem 工具定义（可在任何图中复用）。"""

from __future__ import annotations

import logging
import os

from langmem import create_manage_memory_tool, create_search_memory_tool

logger = logging.getLogger("infra.memory.langmem_tools")

LANGMEM_ENABLED = os.getenv("LANGMEM_ENABLED", "1").lower() in ("1", "true", "yes")

_MANAGE_INSTRUCTIONS_ZH = (
    "在以下情况主动调用本工具：用户明确要求记住某事；出现稳定事实、偏好、习惯；"
    "需要跨会话保留的重要上下文。使用 create 新建、update 更新、delete 删除；"
    "更新或删除时必须提供该条记忆的 id（由创建时返回）。"
)


def build_langmem_tools():
    """构建 LangMem 提供的 manage/search 工具列表。"""
    if not LANGMEM_ENABLED:
        return []
    return [
        create_manage_memory_tool(
            namespace=("agent_memories", "{user_id}", "{thread_id}"),
            instructions=_MANAGE_INSTRUCTIONS_ZH,
        ),
        create_search_memory_tool(
            namespace=("agent_memories", "{user_id}", "{thread_id}"),
        ),
    ]


LANGMEM_TOOLS = build_langmem_tools()
