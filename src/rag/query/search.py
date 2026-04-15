"""高层检索 API：LlamaIndex + ``MilvusVectorStore``（与入库同一集合与嵌入）."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.embedding.config import EmbeddingConfig
from shared.embedding.exceptions import EmbeddingConfigurationError
from shared.embedding.sync_resolve import sync_resolve_embedding_config

logger = logging.getLogger(__name__)

_INDEX_CACHE_TTL_SECONDS = 300


@dataclass
class _CachedIndex:
    index: Any
    config_key: str
    created_at: float = field(default_factory=time.monotonic)


_vector_index_by_owner: dict[int, _CachedIndex] = {}


def _config_cache_key(cfg: EmbeddingConfig) -> str:
    return f"{cfg.base_url}|{cfg.model}|{cfg.api_key[:8]}|{cfg.dimensions}"


def invalidate_vector_index_cache(owner_user_id: int | None = None) -> None:
    """手动清除缓存；不传 owner 则清全部。"""
    if owner_user_id is None:
        _vector_index_by_owner.clear()
    else:
        _vector_index_by_owner.pop(owner_user_id, None)


def _get_vector_index_for_owner(owner_user_id: int, embedding_config: EmbeddingConfig):
    """按归属用户缓存 ``VectorStoreIndex``；TTL 5 分钟或嵌入配置变更时重建。"""
    now = time.monotonic()
    new_key = _config_cache_key(embedding_config)
    cached = _vector_index_by_owner.get(owner_user_id)
    if cached is not None:
        expired = (now - cached.created_at) > _INDEX_CACHE_TTL_SECONDS
        config_changed = cached.config_key != new_key
        if not expired and not config_changed:
            return cached.index
        _vector_index_by_owner.pop(owner_user_id, None)

    try:
        from llama_index.core import VectorStoreIndex
    except ImportError:
        return None

    from rag.embedding.factory import build_llama_embedding_from_config
    from rag.stores.milvus_store import build_milvus_vector_store, load_milvus_collection

    embed_model = build_llama_embedding_from_config(embedding_config)
    if embed_model is None:
        return None
    vs = build_milvus_vector_store(dim=embedding_config.dimensions)
    # 查询前必须 load；与入库进程分离时，仅靠 insert 不能保证 collection 处于 Loaded
    load_milvus_collection(vs)
    idx = VectorStoreIndex.from_vector_store(
        vector_store=vs,
        embed_model=embed_model,
    )
    _vector_index_by_owner[owner_user_id] = _CachedIndex(
        index=idx, config_key=new_key,
    )
    return idx


def _build_metadata_filters(
    knowledge_base_id: int | None = None,
    owner_user_id: int | None = None,
) -> Any | None:
    """构造 LlamaIndex ``MetadataFilters``，交由 Milvus 做服务端标量过滤。"""
    try:
        from llama_index.core.vector_stores import (
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
        )
    except ImportError:
        return None

    conditions: list[MetadataFilter] = []
    if knowledge_base_id is not None:
        conditions.append(MetadataFilter(
            key="knowledge_base_id", value=knowledge_base_id, operator=FilterOperator.EQ,
        ))
    if owner_user_id is not None:
        conditions.append(MetadataFilter(
            key="owner_user_id", value=owner_user_id, operator=FilterOperator.EQ,
        ))
    if not conditions:
        return None
    return MetadataFilters(filters=conditions)


def _retrieve_nodes_with_config(
    query: str,
    top_k: int,
    embedding_config: EmbeddingConfig,
    *,
    db_owner_user_id: int,
    knowledge_base_id: int | None = None,
    owner_user_id: int | None = None,
):
    """向量检索；使用 Milvus 标量过滤"""
    index = _get_vector_index_for_owner(db_owner_user_id, embedding_config)
    if index is None:
        return None

    filters = _build_metadata_filters(
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
    )
    hybrid_retriever = index.as_retriever(
        similarity_top_k=top_k,
        filters=filters,
        vector_store_query_mode="hybrid",
    )
    try:
        return hybrid_retriever.retrieve(query)
    except Exception as exc:  # pragma: no cover - 依赖 Milvus 版本与服务端行为
        message = str(exc)
        should_fallback = (
            "VECTOR_SPARSE_FLOAT" in message
            and "VARCHAR" in message
            and "sparse_embedding" in message
        )
        if not should_fallback:
            raise
        logger.warning(
            "hybrid 检索失败，自动降级为 dense-only: %s",
            message[:500],
        )
        dense_retriever = index.as_retriever(
            similarity_top_k=top_k,
            filters=filters,
            vector_store_query_mode="default",
        )
        return dense_retriever.retrieve(query)


def _format_hits(nodes: list[Any]) -> str:
    if not nodes:
        return "没有找到相关文档。"
    results: list[str] = []
    for i, nws in enumerate(nodes, 1):
        node = nws.node
        text = node.get_content() or ""
        meta = getattr(node, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        source = meta.get("source_parsed_md") or meta.get("source", "unknown")
        line = f"[{i}] (md: {source})\n{text}"
        iids = (meta.get("image_ids") or "").strip()
        iurls = (meta.get("image_static_urls") or "").strip()
        if iids or iurls:
            line += f"\n  [引用] image_ids={iids!r} static_urls={iurls!r}"
        results.append(line)
    return "\n\n---\n\n".join(results)


def milvus_similarity_search_with_config(
    query: str,
    top_k: int,
    embedding_config: EmbeddingConfig,
    *,
    db_owner_user_id: int,
    knowledge_base_id: int | None = None,
    owner_user_id: int | None = None,
) -> str:
    """已解析 ``EmbeddingConfig`` 时的检索（HTTP 异步路径优先使用）。"""
    q_preview = (query or "")[:200]
    logger.info(
        "milvus_similarity_search_with_config top_k=%s kb=%s owner=%s q=%r",
        top_k,
        knowledge_base_id,
        owner_user_id,
        q_preview,
    )

    nodes = _retrieve_nodes_with_config(
        query,
        top_k,
        embedding_config,
        db_owner_user_id=db_owner_user_id,
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
    )
    if nodes is None:
        return (
            "未安装或未启用 RAG 依赖（需 llama-index-core、llama-index-vector-stores-milvus），"
            "无法检索 Milvus。"
        )
    logger.info("milvus_similarity_search_with_config 检索到的结果数量：%s", len(nodes))
    return _format_hits(nodes)


def milvus_similarity_search_text(
    query: str,
    top_k: int = 5,
    *,
    knowledge_base_id: int | None = None,
    owner_user_id: int | None = None,
) -> str:
    """同步检索：从数据库解析嵌入配置（需 ``owner_user_id``；用于 Agent 工具等同步场景）。"""
    if owner_user_id is None:
        return "检索需要提供 owner_user_id，以加载该用户在全局设置中的嵌入厂商与模型。"
    try:
        cfg = sync_resolve_embedding_config(owner_user_id)
    except EmbeddingConfigurationError as exc:
        return str(exc)

    return milvus_similarity_search_with_config(
        query,
        top_k,
        cfg,
        db_owner_user_id=owner_user_id,
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
    )


async def milvus_similarity_search_text_async(
    query: str,
    top_k: int = 5,
    *,
    knowledge_base_id: int | None = None,
    owner_user_id: int | None = None,
) -> str:
    """异步检索：先异步解析嵌入配置；LlamaIndex + 同步嵌入 HTTP 在线程中执行，避免阻塞事件循环。"""
    if owner_user_id is None:
        return "检索需要提供 owner_user_id，以加载该用户在全局设置中的嵌入厂商与模型。"
    from shared.embedding.exceptions import EmbeddingConfigurationError
    from shared.embedding.provider import DatabaseEmbeddingSettingsProvider
    from utils.sql_db import async_session

    try:
        async with async_session() as session:
            cfg = await DatabaseEmbeddingSettingsProvider().resolve(session, owner_user_id)
    except EmbeddingConfigurationError as exc:
        return str(exc)

    return await asyncio.to_thread(
        milvus_similarity_search_with_config,
        query,
        top_k,
        cfg,
        db_owner_user_id=owner_user_id,
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
    )


def search_in_knowledge_base(
    query: str,
    *,
    knowledge_base_id: int,
    owner_user_id: int,
    top_k: int = 5,
) -> list[str]:
    """在指定知识库（且归属用户）范围内检索，返回文本片段列表."""
    nodes = _retrieve_nodes_with_config(
        query,
        top_k,
        sync_resolve_embedding_config(owner_user_id),
        db_owner_user_id=owner_user_id,
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
    )
    if nodes is None:
        raise RuntimeError("RAG 未就绪：请安装 rag optional 依赖并配置 Milvus")
    snippets: list[str] = []
    for nws in nodes:
        node = nws.node
        text = (node.get_content() or "").strip()
        if text:
            snippets.append(text)
    return snippets


async def search_in_knowledge_base_formatted_async(
    session: AsyncSession,
    query: str,
    *,
    knowledge_base_id: int,
    owner_user_id: int,
    top_k: int = 5,
) -> str:
    """在指定知识库（且归属用户）范围内检索，返回文本片段列表。"""
    from shared.embedding.provider import DatabaseEmbeddingSettingsProvider

    provider = DatabaseEmbeddingSettingsProvider()
    cfg = await provider.resolve(session, owner_user_id)

    return await asyncio.to_thread(
        milvus_similarity_search_with_config,
        query.strip(),
        top_k,
        cfg,
        db_owner_user_id=owner_user_id,
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
    )
