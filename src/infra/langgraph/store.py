"""LangMem + LangGraph BaseStore：长期记忆工具与向量索引.

默认在设置了 ``POSTGRES_URI``（或 ``LANGMEM_POSTGRES_URI``）时使用
``PostgresStore``（``langgraph-checkpoint-postgres``）持久化；否则回退 ``InMemoryStore``。
向量维度与 RAG 一致（固定 1024）；嵌入与 RAG 共用 ``llm_global_setting`` + ``llm_vendor``，
需设置 ``LANGMEM_EMBEDDING_OWNER_USER_ID`` 指向用于解析嵌入配置的用户 id。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from shared.embedding.config import FIXED_EMBEDDING_DIMENSION
from shared.embedding.http_openai import HttpOpenAIEmbeddings
from shared.embedding.sync_resolve import sync_resolve_embedding_config

logger = logging.getLogger("infra.langgraph.store")

LANGMEM_ENABLED = os.getenv("LANGMEM_ENABLED", "1").lower() in ("1", "true", "yes")

# postgres | memory | auto（auto：有库 URL 用 postgres，否则 memory）
LANGMEM_STORE_MODE = os.getenv("LANGMEM_STORE", "auto").strip().lower()

_store: BaseStore | None = None
_http_emb: Any = None


def _postgres_uri() -> str:
    return (os.getenv("LANGMEM_POSTGRES_URI") or os.getenv("POSTGRES_URI") or "").strip()


def _langmem_embedding_owner_user_id() -> int:
    raw = os.getenv("LANGMEM_EMBEDDING_OWNER_USER_ID", "").strip()
    if not raw:
        raise RuntimeError(
            "请设置 LANGMEM_EMBEDDING_OWNER_USER_ID（与 llm_global_setting 中已配置嵌入的用户 id 一致），"
            "以便 LangMem 向量索引与全局嵌入模型对齐。",
        )
    return int(raw)


def _get_http_embeddings():
    global _http_emb
    if _http_emb is None:
        cfg = sync_resolve_embedding_config(_langmem_embedding_owner_user_id())
        _http_emb = HttpOpenAIEmbeddings.from_config(cfg)
    return _http_emb


def _embed_sync(texts: list[str]) -> list[list[float]]:
    return _get_http_embeddings().embed_documents(texts)


def _index_config() -> dict:
    return {
        "dims": FIXED_EMBEDDING_DIMENSION,
        "embed": _embed_sync,
        "fields": ["content"],
    }


def _make_pool(uri: str, *, max_size: int):
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    return ConnectionPool(
        uri,
        min_size=1,
        max_size=max_size,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    )


def _build_postgres_store() -> BaseStore | None:
    uri = _postgres_uri()
    if not uri:
        return None
    try:
        from langgraph.store.postgres import PostgresStore
    except ImportError as e:
        logger.warning("LangMem PostgresStore 不可用，回退内存：%s", e)
        return None

    max_size_raw = os.getenv("LANGMEM_PG_POOL_MAX", "10")
    try:
        max_size = int(max_size_raw)
    except ValueError:
        max_size = 10

    force_no_vec = os.getenv("LANGMEM_USE_PGVECTOR", "auto").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    )

    if force_no_vec:
        pool = _make_pool(uri, max_size=max_size)
        store = PostgresStore(conn=pool, index=None)
        store.setup()
        logger.info("LangMem PostgresStore 已初始化（无向量索引，LANGMEM_USE_PGVECTOR 已关闭）")
        return store

    pool = _make_pool(uri, max_size=max_size)
    store = PostgresStore(conn=pool, index=_index_config())
    try:
        store.setup()
        logger.info("LangMem PostgresStore 已初始化（含向量索引，依赖 pgvector）")
        return store
    except Exception as e:
        msg = str(e).lower()
        pool.close(timeout=10.0)
        if "vector" not in msg and "pgvector" not in msg and "extension" not in msg:
            logger.warning("LangMem Postgres 初始化失败，回退内存：%s", e)
            return None
        logger.warning(
            "LangMem：未检测到 pgvector 或扩展创建失败，改用无向量索引的 PostgresStore（语义检索能力受限）：%s",
            e,
        )
        pool2 = _make_pool(uri, max_size=max_size)
        store2 = PostgresStore(conn=pool2, index=None)
        store2.setup()
        logger.info("LangMem PostgresStore 已初始化（无向量索引）")
        return store2


def _build_memory_store() -> InMemoryStore:
    return InMemoryStore(index=_index_config())


def get_langgraph_store() -> BaseStore | None:
    """返回 LangGraph Store；未启用 LangMem 时返回 None。
    
    本地化部署：若设置了 POSTGRES_URI，则实际返回 PostgresStore 实例。
    """
    global _store
    if not LANGMEM_ENABLED:
        return None
    if _store is not None:
        return _store

    mode = LANGMEM_STORE_MODE
    if mode == "memory":
        _store = _build_memory_store()
        logger.info("LangMem 使用 InMemoryStore")
        return _store

    # 尝试构建 PostgresStore
    pg_store = _build_postgres_store()
    if pg_store is not None:
        _store = pg_store
        return _store

    # 回退到 MemoryStore
    logger.warning("未能构建 PostgresStore，LangMem 回退使用 InMemoryStore")
    _store = _build_memory_store()
    return _store
