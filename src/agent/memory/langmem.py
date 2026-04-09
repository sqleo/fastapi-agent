"""LangMem + LangGraph BaseStore：长期记忆工具与向量索引.

默认在设置了 ``POSTGRES_URI``（或 ``LANGMEM_POSTGRES_URI``）时使用
``PostgresStore``（``langgraph-checkpoint-postgres``）持久化；否则回退 ``InMemoryStore``。
向量维度与 ``MILVUS_DIM`` 一致，嵌入函数与知识库共用 ``MilvusService`` 的 embedding。
"""

from __future__ import annotations

import logging
import os

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langmem import create_manage_memory_tool, create_search_memory_tool

from utils.milvus_db import MilvusService

logger = logging.getLogger("agent.memory.langmem")

LANGMEM_ENABLED = os.getenv("LANGMEM_ENABLED", "1").lower() in ("1", "true", "yes")

# postgres | memory | auto（auto：有库 URL 用 postgres，否则 memory）
LANGMEM_STORE_MODE = os.getenv("LANGMEM_STORE", "auto").strip().lower()

_store: BaseStore | None = None

_MANAGE_INSTRUCTIONS_ZH = (
    "在以下情况主动调用本工具：用户明确要求记住某事；出现稳定事实、偏好、习惯；"
    "需要跨会话保留的重要上下文。使用 create 新建、update 更新、delete 删除；"
    "更新或删除时必须提供该条记忆的 id（由创建时返回）。"
)


def _postgres_uri() -> str:
    return (os.getenv("LANGMEM_POSTGRES_URI") or os.getenv("POSTGRES_URI") or "").strip()


def _embed_sync(texts: list[str]) -> list[list[float]]:
    return MilvusService().embeddings.embed_documents(texts)


def _index_config() -> dict:
    dim = int(os.getenv("MILVUS_DIM", "1024"))
    return {
        "dims": dim,
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
    """返回 LangGraph Store；未启用 LangMem 时返回 None.

    注意：LangGraph Platform 会自动管理 persistence。
    这里返回 None 或 InMemoryStore 以避免 "custom store" 警告。
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

    # 对于 LangGraph API / Platform，推荐不提供自定义 PostgresStore
    # 平台会根据 POSTGRES_URI 自动管理 persistence
    logger.info("Using platform-managed persistence - returning None for custom store")
    return None



def build_langmem_tools():
    """构建 LangMem 提供的 manage/search 工具列表."""
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
