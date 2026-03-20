"""Agent tools for LangGraph graph."""

from __future__ import annotations

from langchain_core.tools import tool

from utils.milvus_db import MilvusService

_milvus_service = MilvusService()


@tool
def milvus_search(query: str, top_k: int = 5) -> str:
    """Search the vector database for documents relevant to the query.

    Args:
        query: The search query text.
        top_k: Number of results to return, defaults to 5.
    """
    vector_store = _milvus_service.get_vector_store()
    docs = vector_store.similarity_search(query, k=top_k)
    if not docs:
        return "No relevant documents found."
    results = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "unknown")
        results.append(f"[{i}] (source: {source})\n{doc.page_content}")
    return "\n\n---\n\n".join(results)
