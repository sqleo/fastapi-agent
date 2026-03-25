"""Agent tools for LangGraph graph."""

from __future__ import annotations

from langchain_core.tools import tool

from utils.milvus_db import MilvusService


@tool
def milvus_search(query: str, top_k: int = 5) -> str:
    """Search the vector database for documents relevant to the query.

    Args:
        query: The search query text.
        top_k: Number of results to return, defaults to 5.
    """
    docs = MilvusService().get_vector_store().similarity_search(query, k=top_k)
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
