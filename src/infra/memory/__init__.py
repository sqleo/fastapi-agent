"""infra.memory — 记忆基础设施层（与 agent 无关的公共函数）。

提供：
- turns          对话轮次切分与 token 估算
- advanced_memory  高级记忆管理（分类存储 + 分层摘要 + 渐进压缩）
- langmem_tools  LangMem manage/search 工具构建
- nodes          通用 LangGraph 记忆节点（检索 / 写入）
"""

from .advanced_memory import AdvancedMemoryManager, MemoryEntry
from .langmem_tools import LANGMEM_ENABLED, LANGMEM_TOOLS, build_langmem_tools
from .nodes import (
    advanced_memory_retrieve_node,
    advanced_memory_write_node,
    memory_retrieve_node,
    memory_write_node,
    short_term_window_node,
)
from .turns import (
    approx_tokens,
    estimate_messages_tokens,
    format_turns_for_summary,
    last_user_query,
    message_text,
    segment_turns,
    split_system_and_rest,
    take_last_turns,
)

__all__ = [
    # turns
    "approx_tokens",
    "message_text",
    "split_system_and_rest",
    "segment_turns",
    "estimate_messages_tokens",
    "last_user_query",
    "take_last_turns",
    "format_turns_for_summary",
    # advanced_memory
    "AdvancedMemoryManager",
    "MemoryEntry",
    # langmem_tools
    "LANGMEM_ENABLED",
    "build_langmem_tools",
    "LANGMEM_TOOLS",
    # nodes
    "short_term_window_node",
    "advanced_memory_retrieve_node",
    "advanced_memory_write_node",
    "memory_retrieve_node",
    "memory_write_node",
]
