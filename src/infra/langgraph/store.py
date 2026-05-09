"""LangMem + LangGraph BaseStore 入口。

每个用户独立 PostgreSQL schema + 独立嵌入模型；详见 ``tenant_store.py``。
仅当 ``LANGMEM_ENABLED`` 为 0 时返回 ``None``；其余情况一律返回 ``TenantRoutingStore``
单例（按 ``namespace[1]=user_id`` 分发到对应租户的 PostgresStore）。

历史的 ``LANGMEM_EMBEDDING_OWNER_USER_ID`` / ``LANGMEM_USE_PGVECTOR`` /
``InMemoryStore`` 回退已移除。本地无 Postgres 时请关掉 ``LANGMEM_ENABLED``。
"""

from __future__ import annotations

import logging
import os

from langgraph.store.base import BaseStore

from infra.langgraph.tenant_store import TenantRoutingStore

logger = logging.getLogger("infra.langgraph.store")

LANGMEM_ENABLED = os.getenv("LANGMEM_ENABLED", "1").lower() in ("1", "true", "yes")

_store: TenantRoutingStore | None = None


def get_langgraph_store() -> BaseStore | None:
    """返回 LangGraph Store；未启用 LangMem 时返回 ``None``。

    多租户：所有写读都通过 ``TenantRoutingStore`` 按 ``namespace[1]`` 分发到对应用户的 schema。
    """
    global _store
    if not LANGMEM_ENABLED:
        return None
    if _store is None:
        _store = TenantRoutingStore()
        logger.info("LangMem 使用 TenantRoutingStore（多租户 + 独立 schema）")
    return _store
