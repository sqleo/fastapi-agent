"""Agent tools for LangGraph graph."""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from utils.milvus_db import MilvusService

logger = logging.getLogger("agent.tools")


@tool
def milvus_search(query: str, top_k: int = 5) -> str:
    """Search the vector database for documents relevant to the query.

    Args:
        query: The search query text.
        top_k: Number of results to return, defaults to 5.
    """
    q_preview = (query or "")[:200]
    logger.info("milvus_search start top_k=%s query_preview=%r", top_k, q_preview)
    docs = MilvusService().get_vector_store().similarity_search(query, k=top_k)
    logger.info("milvus_search end hits=%s", len(docs))
    if not docs:
        return "No relevant documents found."
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


ALL_AGENT_TOOLS = [milvus_search]


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
