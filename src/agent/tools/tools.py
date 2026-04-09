"""Agent tools for LangGraph graph."""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from agent.memory.langmem import LANGMEM_TOOLS
from utils.milvus_db import MilvusService

logger = logging.getLogger("agent.tools")


@tool
def milvus_search(query: str, top_k: int = 5) -> str:
    """搜索向量数据库中的文档，返回与查询相关的文档。
    Args:
        query: 搜索查询文本。
        top_k: 返回结果数量，默认为 5。
    """
    q_preview = (query or "")[:200]
    logger.info("milvus_search start top_k=%s query_preview=%r", top_k, q_preview)
    docs = MilvusService().get_vector_store().similarity_search(query, k=top_k)
    logger.info("milvus_search end hits=%s", len(docs))
    if not docs:
        return "没有找到相关文档。"
    results = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source_parsed_md") or doc.metadata.get(
            "source", "unknown"
        )
        line = f"[{i}] (md: {source})\n{doc.page_content}"
        iids = doc.metadata.get("image_ids", "").strip()
        iurls = doc.metadata.get("image_static_urls", "").strip()
        if iids or iurls:
            line += f"\n  [引用] image_ids={iids!r} static_urls={iurls!r}"
        results.append(line)
    return "\n\n---\n\n".join(results)


ALL_AGENT_TOOLS = [milvus_search, *LANGMEM_TOOLS]


def tool_catalog() -> list[dict[str, str | None]]:
    """供 API 展示：名称与说明，便于前端做开关."""
    rows: list[dict[str, str | None]] = []
    for t in ALL_AGENT_TOOLS:
        rows.append(
            {
                "name": t.name,
                "description": (getattr(t, "description", None) or "").strip() or None,
            }
        )
    return rows
