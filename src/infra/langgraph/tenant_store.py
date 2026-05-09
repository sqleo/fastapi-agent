"""LangMem 多租户 PostgresStore：每个用户独立 schema + 独立嵌入。

设计要点：
- 命名空间契约：``namespace[1] == str(user_id)``。所有调用方
  （LangMem manage/search 工具、AdvancedMemoryManager、memory_*_node）
  都已满足；路由层入口处再做防御性校验。
- schema 命名：``mem_u{user_id}_v{embedding_version}``；改任一 embedding_*
  字段 → version+1 → 新 schema → 走 reindex 任务。
- 物理隔离：``PostgresStore`` 内部 SQL 都用 unqualified 表名 ``store`` /
  ``store_vectors``。我们在每个 connection 上 ``SET search_path = <schema>,public``，
  原生支持 schema 隔离，不需要子类化它。
- 维度差异：每个用户的 ``store_vectors.embedding`` 列宽度 = 该用户
  ``embedding_dim``。不同用户互不影响。

模块导出三类 store：
- ``TenantRoutingStore``：``BaseStore`` 实现，按 namespace 分组转发；
  作为 ``get_langgraph_store()`` 的唯一返回值供 LangGraph 使用。
- ``DualWriteStore``：迁移期使用，写双 schema、读旧 schema。
- ``KVOnlyStore``：用户尚未配置嵌入时的降级（``index=None``，无向量检索）。
"""

from __future__ import annotations

import logging
import os
import threading
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from langgraph.store.base import (
    BaseStore,
    GetOp,
    InvalidNamespaceError,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchOp,
)
from langgraph.store.postgres import PostgresStore

from llm_completion.embedding_llm import sync_embedding_for_owner
from models.LlmGlobalSettingModel import (
    EMBEDDING_STATUS_ACTIVE,
    EMBEDDING_STATUS_DEPRECATED,
    EMBEDDING_STATUS_MIGRATING,
    LlmGlobalSettingModel,
)

logger = logging.getLogger("infra.langgraph.tenant_store")


# ──────────────────────────────────────────────────────────────────────────────
# 配置缓存：避免每次 batch 都查 MySQL 拿 (version, status, dim)
# 写一致性由 controller 在改配置时主动调 ``invalidate_user_config_cache`` 保证。
# ──────────────────────────────────────────────────────────────────────────────

_config_cache: dict[int, "_UserMemConfig"] = {}
_config_cache_lock = threading.Lock()


class _UserMemConfig:
    __slots__ = ("user_id", "version", "status", "dim", "previous_version")

    def __init__(
        self,
        user_id: int,
        version: int,
        status: str,
        dim: int | None,
        previous_version: int | None = None,
    ) -> None:
        self.user_id = int(user_id)
        self.version = int(version)
        self.status = str(status)
        self.dim = int(dim) if dim else None
        self.previous_version = int(previous_version) if previous_version else None


def invalidate_user_config_cache(user_id: int | None = None) -> None:
    with _config_cache_lock:
        if user_id is None:
            _config_cache.clear()
            return
        _config_cache.pop(int(user_id), None)


async def _load_user_mem_config(user_id: int) -> _UserMemConfig:
    cached = _config_cache.get(int(user_id))
    if cached is not None:
        return cached

    from sqlalchemy import select

    from utils.sql_db import async_session

    async with async_session() as session:
        stmt = select(LlmGlobalSettingModel).where(
            LlmGlobalSettingModel.owner_user_id == int(user_id)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

    if row is None:
        # 用户从未配置过，按 deprecated 处理
        cfg = _UserMemConfig(user_id=user_id, version=1, status=EMBEDDING_STATUS_DEPRECATED, dim=None)
        with _config_cache_lock:
            _config_cache[int(user_id)] = cfg
        return cfg

    has_embed = bool(row.embedding_vendor_id) and bool((row.embedding_model or "").strip())
    status = row.embedding_status or EMBEDDING_STATUS_ACTIVE
    if not has_embed:
        status = EMBEDDING_STATUS_DEPRECATED

    cfg = _UserMemConfig(
        user_id=user_id,
        version=int(row.embedding_version or 1),
        status=status,
        dim=row.embedding_dim,
        previous_version=int(row.embedding_version or 1) - 1 if status == EMBEDDING_STATUS_MIGRATING else None,
    )
    with _config_cache_lock:
        _config_cache[int(user_id)] = cfg
    return cfg


# ──────────────────────────────────────────────────────────────────────────────
# Postgres 资源
# ──────────────────────────────────────────────────────────────────────────────


def schema_name(user_id: int, version: int) -> str:
    """``mem_u{uid}_v{ver}``；DDL 时同步用，路由时也用。"""
    return f"mem_u{int(user_id)}_v{int(version)}"


def _postgres_uri() -> str:
    return (os.getenv("LANGMEM_POSTGRES_URI") or os.getenv("POSTGRES_URI") or "").strip()


def _ensure_schema_exists(uri: str, schema: str) -> None:
    """幂等创建 schema（PostgresStore.setup 不会管这一步）。"""
    import psycopg

    with psycopg.connect(uri, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def drop_schema(uri: str, schema: str) -> None:
    """DROP SCHEMA CASCADE；reindex 完成后清理旧版本时使用。"""
    import psycopg

    with psycopg.connect(uri, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    logger.info("tenant_store: dropped schema %s", schema)


def _make_pool(uri: str, *, schema: str, max_size: int):
    """每个 schema 一个连接池：``options=-c search_path=<schema>,public``。"""
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    options = f"-c search_path={schema},public"
    return ConnectionPool(
        uri,
        min_size=1,
        max_size=max_size,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": options,
        },
    )


def _index_config_for(user_id: int, dim: int) -> dict[str, Any]:
    def _embed_sync(texts: list[str]) -> list[list[float]]:
        emb = sync_embedding_for_owner(user_id)
        return emb.embed_documents(list(texts))

    return {"dims": int(dim), "embed": _embed_sync, "fields": ["content"]}


# ──────────────────────────────────────────────────────────────────────────────
# 单租户 PostgresStore 缓存（按 (user_id, version) key）
# ──────────────────────────────────────────────────────────────────────────────

_store_cache: dict[tuple[int, int], PostgresStore] = {}
_store_cache_lock = threading.Lock()
_pool_cache: dict[tuple[int, int], Any] = {}


def _build_postgres_store_for(user_id: int, version: int, dim: int) -> PostgresStore:
    uri = _postgres_uri()
    if not uri:
        raise RuntimeError("LANGMEM_POSTGRES_URI / POSTGRES_URI 未配置，无法构建 PostgresStore")

    schema = schema_name(user_id, version)
    _ensure_schema_exists(uri, schema)

    max_size_raw = os.getenv("LANGMEM_PG_POOL_MAX", "5")
    try:
        max_size = int(max_size_raw)
    except ValueError:
        max_size = 5

    pool = _make_pool(uri, schema=schema, max_size=max_size)
    store = PostgresStore(conn=pool, index=_index_config_for(user_id, dim))
    store.setup()
    _pool_cache[(int(user_id), int(version))] = pool
    logger.info(
        "tenant_store: PostgresStore ready user_id=%s version=%s schema=%s dim=%s",
        user_id,
        version,
        schema,
        dim,
    )
    return store


def _build_kv_only_store_for(user_id: int, version: int) -> PostgresStore:
    """``index=None``：仅 KV，无向量检索。用户未配置嵌入时降级。"""
    uri = _postgres_uri()
    if not uri:
        raise RuntimeError("LANGMEM_POSTGRES_URI / POSTGRES_URI 未配置，无法构建 PostgresStore")

    schema = schema_name(user_id, version)
    _ensure_schema_exists(uri, schema)

    max_size_raw = os.getenv("LANGMEM_PG_POOL_MAX", "5")
    try:
        max_size = int(max_size_raw)
    except ValueError:
        max_size = 5

    pool = _make_pool(uri, schema=schema, max_size=max_size)
    store = PostgresStore(conn=pool, index=None)
    store.setup()
    _pool_cache[(int(user_id), int(version))] = pool
    logger.info(
        "tenant_store: PostgresStore (KV-only) ready user_id=%s version=%s schema=%s",
        user_id,
        version,
        schema,
    )
    return store


def _get_or_build_single_store(user_id: int, version: int, dim: int | None) -> PostgresStore:
    key = (int(user_id), int(version))
    cached = _store_cache.get(key)
    if cached is not None:
        return cached
    with _store_cache_lock:
        cached = _store_cache.get(key)
        if cached is not None:
            return cached
        if dim:
            store = _build_postgres_store_for(user_id, version, int(dim))
        else:
            store = _build_kv_only_store_for(user_id, version)
        _store_cache[key] = store
        return store


def evict_store(user_id: int, version: int) -> None:
    """完全释放某个 (user_id, version) 的 PostgresStore + 连接池。"""
    key = (int(user_id), int(version))
    with _store_cache_lock:
        store = _store_cache.pop(key, None)
        pool = _pool_cache.pop(key, None)
    if pool is not None:
        try:
            pool.close()
        except Exception:
            logger.warning("tenant_store: pool close failed key=%s", key, exc_info=True)
    if store is not None:
        logger.info("tenant_store: evicted store user_id=%s version=%s", user_id, version)


# ──────────────────────────────────────────────────────────────────────────────
# 双写：迁移期 status=migrating 时，写新+旧，读仅旧
# ──────────────────────────────────────────────────────────────────────────────


class DualWriteStore(BaseStore):
    """仅在 migrating 期使用：新 store 与旧 store 共存。

    - PutOp（写）：先写旧（保持读一致性），再写新（reindex 任务结束前持续追加）
    - GetOp / SearchOp（读）：仅打到旧 store
    - 迁移完成 → controller 切回 active → 走 ``_get_or_build_single_store``，
      该 DualWriteStore 实例就不再被 factory 返回
    """

    def __init__(self, *, primary: PostgresStore, secondary: PostgresStore) -> None:
        self._primary = primary
        self._secondary = secondary

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        ops_list = list(ops)
        results = self._primary.batch(ops_list)
        self._mirror_writes(ops_list)
        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        ops_list = list(ops)
        results = await self._primary.abatch(ops_list)
        await self._amirror_writes(ops_list)
        return results

    def _mirror_writes(self, ops: list[Op]) -> None:
        write_ops = [op for op in ops if isinstance(op, PutOp)]
        if not write_ops:
            return
        try:
            self._secondary.batch(write_ops)
        except Exception:
            logger.warning(
                "DualWriteStore: secondary write failed (will be re-filled by reindex)",
                exc_info=True,
            )

    async def _amirror_writes(self, ops: list[Op]) -> None:
        write_ops = [op for op in ops if isinstance(op, PutOp)]
        if not write_ops:
            return
        try:
            await self._secondary.abatch(write_ops)
        except Exception:
            logger.warning(
                "DualWriteStore: secondary async write failed (will be re-filled by reindex)",
                exc_info=True,
            )


# ──────────────────────────────────────────────────────────────────────────────
# 工厂：根据用户当前 (version, status, dim) 决定返回哪种 store
# ──────────────────────────────────────────────────────────────────────────────


async def get_store_for_user(user_id: int) -> BaseStore:
    cfg = await _load_user_mem_config(user_id)

    # 无嵌入配置 → 该用户的 schema 仍然用 v=current_version，但 index=None
    if cfg.status == EMBEDDING_STATUS_DEPRECATED or cfg.dim is None:
        store = _get_or_build_single_store(user_id, cfg.version, dim=None)
        logger.warning(
            "tenant_store: user_id=%s 未配置嵌入，记忆功能降级为 KV-only（无语义检索）",
            user_id,
        )
        return store

    # 迁移期：双写新版（primary）+ 旧版（secondary）；读仅落新版（避免读到旧向量空间的脏数据）
    if cfg.status == EMBEDDING_STATUS_MIGRATING and cfg.previous_version:
        primary = _get_or_build_single_store(user_id, cfg.version, dim=cfg.dim)
        # 旧版本 dim 我们不知道；reindex 任务读取旧 schema 时使用同步 sql 直接读，不需要 store
        # 这里 secondary 用 KV-only（PostgresStore + index=None）保证 PutOp 仍可成功
        secondary = _get_or_build_single_store(user_id, cfg.previous_version, dim=None)
        return DualWriteStore(primary=primary, secondary=secondary)

    # active 单写
    return _get_or_build_single_store(user_id, cfg.version, dim=cfg.dim)


# ──────────────────────────────────────────────────────────────────────────────
# RoutingStore：唯一交给 LangGraph 的 BaseStore
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_user_id(namespace: tuple[str, ...]) -> int:
    """约定：namespace[1] = str(user_id)。

    ``("agent_memories", "<uid>", "<thread>")`` 或 ``("user_memories", "<uid>")``
    或任何其他 namespace[0] = prefix, namespace[1] = user_id 的形式。
    """
    if not namespace or len(namespace) < 2:
        raise InvalidNamespaceError(
            f"namespace 必须至少 2 段且 namespace[1]=user_id，实际：{namespace!r}",
        )
    raw = namespace[1]
    try:
        uid = int(str(raw).strip())
    except (TypeError, ValueError) as e:
        raise InvalidNamespaceError(
            f"namespace[1] 必须是用户 id（int 字符串），实际：{raw!r}",
        ) from e
    if uid <= 0:
        raise InvalidNamespaceError(f"namespace[1] 必须是正整数，实际：{raw!r}")
    return uid


def _op_namespace(op: Op) -> tuple[str, ...]:
    if isinstance(op, (GetOp, PutOp)):
        return op.namespace
    if isinstance(op, SearchOp):
        return op.namespace_prefix
    if isinstance(op, ListNamespacesOp):
        # ListNamespacesOp 不绑定单一 namespace，无法路由
        raise InvalidNamespaceError(
            "TenantRoutingStore 不支持 ListNamespacesOp（跨租户列举不安全）",
        )
    raise InvalidNamespaceError(f"未知 Op 类型: {type(op).__name__}")


class TenantRoutingStore(BaseStore):
    """按 namespace[1] (user_id) 把 op 分发到对应的 PostgresStore。"""

    supports_ttl = True

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        import asyncio

        ops_list = list(ops)
        return asyncio.run(self.abatch(ops_list))

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        ops_list = list(ops)
        if not ops_list:
            return []

        # 按 user_id 分组，记录原始下标以便最终按序还原
        groups: dict[int, list[tuple[int, Op]]] = defaultdict(list)
        for idx, op in enumerate(ops_list):
            uid = _resolve_user_id(_op_namespace(op))
            groups[uid].append((idx, op))

        results: list[Result | None] = [None] * len(ops_list)

        # 依次处理每个用户的子批
        for uid, items in groups.items():
            store = await get_store_for_user(uid)
            sub_ops = [op for _, op in items]
            sub_results = await store.abatch(sub_ops)
            for (orig_idx, _), r in zip(items, sub_results, strict=False):
                results[orig_idx] = r

        return results  # type: ignore[return-value]
