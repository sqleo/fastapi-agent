"""Agent tools for LangGraph graph."""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from agent.memory.langmem import LANGMEM_TOOLS
from agent.tools.decorators import hidden_from_client
from rag.query.search import milvus_similarity_search_text

logger = logging.getLogger("agent.tools")

@tool
def milvus_search(
    query: str,
    top_k: int = 5,
    knowledge_base_id: int | None = None,
    owner_user_id: int | None = None,
) -> str:
    """搜索向量数据库中的文档，返回与查询相关的文档。

    Args:
        query: 搜索查询文本。
        top_k: 返回结果数量，默认为 5。
        knowledge_base_id: 若提供则只检索该知识库下的片段（与入库写入的 metadata 一致）。
        owner_user_id: 可选；与 knowledge_base_id 同时提供时进一步按用户隔离。
    """
    return milvus_similarity_search_text(
        query,
        top_k=top_k,
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
    )


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
