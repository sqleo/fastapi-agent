"""带 ``knowledge_base_id`` / ``owner_user_id`` metadata 过滤的检索."""

from __future__ import annotations

from typing import Any, Callable

from shared.embedding.sync_resolve import sync_resolve_embedding_config

from rag.query.search import _retrieve_nodes_with_config


def build_kb_retriever(
    *,
    knowledge_base_id: int,
    owner_user_id: int,
    top_k: int = 5,
) -> Callable[[str], list[Any]]:
    """返回 ``query -> List[NodeWithScore]``，仅包含该知识库且该用户下的向量命中。"""

    cfg = sync_resolve_embedding_config(owner_user_id)

    def _retrieve(query: str) -> list[Any]:
        return _retrieve_nodes_with_config(
            query,
            top_k,
            cfg,
            db_owner_user_id=owner_user_id,
            knowledge_base_id=knowledge_base_id,
            owner_user_id=owner_user_id,
        ) or []

    return _retrieve
