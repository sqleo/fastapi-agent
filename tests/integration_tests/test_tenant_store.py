"""LangMem 多租户 PostgresStore 集成测试。

需要本地 Postgres + pgvector 可达（默认 ``postgresql://postgres:postgres@localhost:5432/langgraph``）。
连接失败时自动 skip 整个文件，CI 上未启动 docker-compose 不会红。

覆盖：
1. 两个用户写读隔离（不同 schema）
2. 两个用户嵌入维度不同（pgvector 列宽度独立）
3. ``TenantRoutingStore.abatch`` 混合多租户 op 正确分组
4. namespace 缺 user_id 立即 raise
5. ``DualWriteStore`` 写双 schema、读旧 schema
6. ``drop_schema`` 能彻底清理
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import struct
from typing import Iterable
from unittest.mock import patch

import pytest
from langgraph.store.base import (
    GetOp,
    InvalidNamespaceError,
    PutOp,
    SearchOp,
)

# 集成测试只跑 anyio asyncio backend
pytestmark = [pytest.mark.anyio]


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _postgres_uri_for_test() -> str:
    return (
        os.getenv("LANGMEM_TEST_POSTGRES_URI")
        or os.getenv("LANGMEM_POSTGRES_URI")
        or os.getenv("POSTGRES_URI")
        or "postgresql://postgres:postgres@localhost:5432/langgraph"
    )


def _can_connect(uri: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(uri, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                # 检查 pgvector 扩展是否能建（autocommit 不要求实际开启）
                cur.execute("SELECT 1 FROM pg_available_extensions WHERE name='vector'")
                return cur.fetchone() is not None
    except Exception:
        return False


_TEST_URI = _postgres_uri_for_test()
_PG_AVAILABLE = _can_connect(_TEST_URI)
pytestmark.append(
    pytest.mark.skipif(
        not _PG_AVAILABLE,
        reason=f"Postgres + pgvector 不可达：{_TEST_URI}",
    )
)


# 测试时把 LANGMEM_POSTGRES_URI 指到测试库
os.environ["LANGMEM_POSTGRES_URI"] = _TEST_URI


# ──────────────────────────────────────────────────────────────────────────────
# Fake embeddings：避免依赖真实 LLM 后端
# ──────────────────────────────────────────────────────────────────────────────


class FakeEmbeddings:
    """确定性的 hash → float[dim] 向量，纯 Python。"""

    def __init__(self, dim: int) -> None:
        self.dim = int(dim)

    def _vec_for(self, text: str) -> list[float]:
        # 用 sha256 + 8 字节切片 → float64，循环填满 dim
        h = hashlib.sha256(text.encode("utf-8")).digest()
        out: list[float] = []
        i = 0
        while len(out) < self.dim:
            chunk = h[(i * 8) % 24 : (i * 8) % 24 + 8]
            if len(chunk) < 8:
                chunk = (chunk + h)[:8]
            (val,) = struct.unpack("<d", chunk)
            # 归一到 [-1, 1] 量级，避免 NaN
            if val != val or val == float("inf") or val == float("-inf"):
                val = 0.1
            else:
                val = (val % 2) - 1
            out.append(val)
            i += 1
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec_for(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec_for(text)


# 强制 ``sync_embedding_for_owner`` / ``build_embeddings_for_user`` 都返回 FakeEmbeddings
# 通过 monkey-patch ``llm_completion.embedding_llm.sync_embedding_for_owner``，
# 它在 ``tenant_store._index_config_for._embed_sync`` 被调用。
@pytest.fixture(autouse=True)
def _patch_embeddings(monkeypatch):
    """根据 user_id 分配维度：user_id=1001 → 8 维；user_id=1002 → 16 维。"""

    def _fake_for_owner(owner_user_id: int):
        dim = _USER_DIMS.get(int(owner_user_id), 8)
        return FakeEmbeddings(dim)

    monkeypatch.setattr(
        "infra.langgraph.tenant_store.sync_embedding_for_owner",
        _fake_for_owner,
    )


_USER_A = 1001
_USER_B = 1002
_USER_DIMS = {_USER_A: 8, _USER_B: 16}


def _drop_all_test_schemas() -> None:
    """清理两个测试租户在所有版本号下可能残留的 schema。"""
    import psycopg

    with psycopg.connect(_TEST_URI, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name LIKE %s OR schema_name LIKE %s
            """,
            (f"mem_u{_USER_A}_v%", f"mem_u{_USER_B}_v%"),
        )
        names = [r[0] for r in cur.fetchall()]
        for name in names:
            cur.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


@pytest.fixture()
def tenant_config_loader(monkeypatch):
    """绕过 MySQL：直接在内存里构造 ``_UserMemConfig``。"""
    from infra.langgraph import tenant_store
    from infra.langgraph.tenant_store import (
        EMBEDDING_STATUS_ACTIVE,
        EMBEDDING_STATUS_DEPRECATED,
        EMBEDDING_STATUS_MIGRATING,
        _UserMemConfig,
        _pool_cache,
        _store_cache,
        evict_store,
        invalidate_user_config_cache,
    )

    # 测试开始前：彻底清空所有相关缓存 + 残留 schema
    invalidate_user_config_cache()
    for key in list(_store_cache.keys()):
        if key[0] in (_USER_A, _USER_B):
            evict_store(*key)
    _drop_all_test_schemas()

    state: dict[int, _UserMemConfig] = {}

    def set_user(
        uid: int,
        version: int,
        *,
        status: str = EMBEDDING_STATUS_ACTIVE,
        dim: int | None = None,
        previous_version: int | None = None,
    ) -> None:
        state[int(uid)] = _UserMemConfig(
            user_id=uid,
            version=version,
            status=status,
            dim=dim if dim is not None else _USER_DIMS.get(int(uid), 8),
            previous_version=previous_version,
        )
        invalidate_user_config_cache(uid)

    async def _fake_loader(user_id: int):
        cfg = state.get(int(user_id))
        if cfg is None:
            return _UserMemConfig(
                user_id=user_id,
                version=1,
                status=EMBEDDING_STATUS_DEPRECATED,
                dim=None,
            )
        return cfg

    monkeypatch.setattr(tenant_store, "_load_user_mem_config", _fake_loader)

    yield set_user

    # 测试结束后：再次清理（防止下一个测试受影响）
    for key in list(_store_cache.keys()):
        if key[0] in (_USER_A, _USER_B):
            evict_store(*key)
    _drop_all_test_schemas()


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────


async def test_two_users_isolated(tenant_config_loader) -> None:
    """两个用户在独立 schema，写入互不可见。"""
    from infra.langgraph.tenant_store import TenantRoutingStore

    tenant_config_loader(_USER_A, version=1)
    tenant_config_loader(_USER_B, version=1)

    store = TenantRoutingStore()

    ns_a = ("user_memories", str(_USER_A))
    ns_b = ("user_memories", str(_USER_B))

    await store.abatch([
        PutOp(ns_a, "k1", {"content": "user A says hello"}),
        PutOp(ns_b, "k1", {"content": "user B says world"}),
    ])

    # 互查：A 命名空间下查不到 B 的记录
    [a_item, b_item] = await store.abatch([
        GetOp(ns_a, key="k1"),
        GetOp(ns_b, key="k1"),
    ])
    assert a_item is not None and a_item.value["content"] == "user A says hello"
    assert b_item is not None and b_item.value["content"] == "user B says world"

    # A 用 B 的 key 查空
    [missing] = await store.abatch([GetOp(ns_a, key="not_exist")])
    assert missing is None


async def test_different_dims_independent(tenant_config_loader) -> None:
    """A 用 8 维向量、B 用 16 维向量；写入互不影响维度。"""
    from infra.langgraph.tenant_store import TenantRoutingStore

    tenant_config_loader(_USER_A, version=1, dim=8)
    tenant_config_loader(_USER_B, version=1, dim=16)

    store = TenantRoutingStore()

    ns_a = ("user_memories", str(_USER_A))
    ns_b = ("user_memories", str(_USER_B))

    await store.abatch([
        PutOp(ns_a, "f1", {"content": "small dim text"}),
        PutOp(ns_b, "f1", {"content": "large dim text"}),
    ])

    # 语义检索（带 query）
    [hits_a] = await store.abatch([
        SearchOp(namespace_prefix=ns_a, filter=None, limit=5, offset=0, query="small")
    ])
    [hits_b] = await store.abatch([
        SearchOp(namespace_prefix=ns_b, filter=None, limit=5, offset=0, query="large")
    ])
    assert isinstance(hits_a, list) and len(hits_a) == 1
    assert isinstance(hits_b, list) and len(hits_b) == 1
    assert hits_a[0].key == "f1"
    assert hits_b[0].key == "f1"


async def test_mixed_batch_grouped_correctly(tenant_config_loader) -> None:
    """一个 batch 里混合两个租户的 op，要按 user_id 分组转发，结果按原 idx 还原。"""
    from infra.langgraph.tenant_store import TenantRoutingStore

    tenant_config_loader(_USER_A, version=1)
    tenant_config_loader(_USER_B, version=1)

    store = TenantRoutingStore()

    ns_a = ("user_memories", str(_USER_A))
    ns_b = ("user_memories", str(_USER_B))

    await store.abatch([
        PutOp(ns_a, "ka", {"content": "A1"}),
        PutOp(ns_b, "kb", {"content": "B1"}),
    ])

    # 顺序：A.get, B.get, A.get（同一 key），B.search
    results = await store.abatch([
        GetOp(ns_a, key="ka"),
        GetOp(ns_b, key="kb"),
        GetOp(ns_a, key="ka"),
        SearchOp(namespace_prefix=ns_b, filter=None, limit=5, offset=0, query="B1"),
    ])
    assert len(results) == 4
    assert results[0].value["content"] == "A1"
    assert results[1].value["content"] == "B1"
    assert results[2].value["content"] == "A1"
    assert isinstance(results[3], list) and len(results[3]) == 1
    assert results[3][0].key == "kb"


async def test_namespace_missing_user_id_raises() -> None:
    """namespace 不含 user_id（或 user_id 不是正整数）必须立即抛错，不能静默落到错误 schema。"""
    from infra.langgraph.tenant_store import TenantRoutingStore

    store = TenantRoutingStore()

    with pytest.raises(InvalidNamespaceError):
        await store.abatch([PutOp(("user_memories",), key="k", value={"x": 1})])

    with pytest.raises(InvalidNamespaceError):
        await store.abatch([
            PutOp(("user_memories", "not-a-number"), key="k", value={"x": 1})
        ])


async def test_dual_write_during_migration(tenant_config_loader) -> None:
    """status=migrating 时双写新+旧 schema，读仍走新 schema（避免读到旧向量空间数据）。"""
    from infra.langgraph.tenant_store import (
        EMBEDDING_STATUS_ACTIVE,
        EMBEDDING_STATUS_MIGRATING,
        TenantRoutingStore,
        _get_or_build_single_store,
        schema_name,
    )

    tenant_config_loader(_USER_A, version=1, dim=8)

    # 先在 v1 写一条
    store_v1 = TenantRoutingStore()
    ns = ("user_memories", str(_USER_A))
    await store_v1.abatch([PutOp(ns, "old_key", {"content": "v1 entry"})])

    # 切到 migrating（version=2，旧 version=1）
    tenant_config_loader(
        _USER_A,
        version=2,
        status=EMBEDDING_STATUS_MIGRATING,
        dim=8,
        previous_version=1,
    )

    store_dual = TenantRoutingStore()
    await store_dual.abatch([PutOp(ns, "new_key", {"content": "v2 fresh"})])

    # 读：路由到新 schema（v2），看不到 old_key（因为还没 reindex）
    [read_old, read_new] = await store_dual.abatch([
        GetOp(ns, key="old_key"),
        GetOp(ns, key="new_key"),
    ])
    assert read_old is None  # old_key 在 v1，新 schema 还没回填
    assert read_new is not None and read_new.value["content"] == "v2 fresh"

    # 直查 v1 schema 应该同时有 old_key（原来的）和 new_key（双写镜像）
    v1_store = _get_or_build_single_store(_USER_A, 1, dim=None)  # KV-only
    raw = await v1_store.abatch([
        GetOp(ns, key="old_key"),
        GetOp(ns, key="new_key"),
    ])
    assert raw[0] is not None and raw[0].value["content"] == "v1 entry"
    assert raw[1] is not None and raw[1].value["content"] == "v2 fresh"


async def test_kv_only_for_unconfigured_user(tenant_config_loader) -> None:
    """用户未配置嵌入 → 走 index=None 的 PostgresStore，PutOp/GetOp 仍可用，SearchOp 无语义检索。"""
    from infra.langgraph.tenant_store import (
        EMBEDDING_STATUS_DEPRECATED,
        TenantRoutingStore,
    )

    tenant_config_loader(_USER_A, version=1, status=EMBEDDING_STATUS_DEPRECATED, dim=None)

    store = TenantRoutingStore()
    ns = ("user_memories", str(_USER_A))

    await store.abatch([PutOp(ns, "k", {"content": "kv only"})])
    [item] = await store.abatch([GetOp(ns, key="k")])
    assert item is not None and item.value["content"] == "kv only"

    # search 不带 query 仍可用（按 prefix 列出）
    [hits] = await store.abatch([
        SearchOp(namespace_prefix=ns, filter=None, limit=5, offset=0, query=None)
    ])
    assert isinstance(hits, list) and len(hits) == 1


async def test_drop_schema_cleans_up(tenant_config_loader) -> None:
    """drop_schema 应该清掉 store / store_vectors 表 + schema 本身。"""
    import psycopg

    from infra.langgraph.tenant_store import (
        TenantRoutingStore,
        drop_schema,
        evict_store,
        schema_name,
    )

    tenant_config_loader(_USER_A, version=1)
    store = TenantRoutingStore()
    ns = ("user_memories", str(_USER_A))
    await store.abatch([PutOp(ns, "k", {"content": "to be dropped"})])

    schema = schema_name(_USER_A, 1)
    with psycopg.connect(_TEST_URI) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
            (schema,),
        )
        before = cur.fetchone()[0]
    assert before >= 1  # 至少 store 表

    evict_store(_USER_A, 1)
    drop_schema(_TEST_URI, schema)

    with psycopg.connect(_TEST_URI) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
            (schema,),
        )
        after = cur.fetchone()[0]
    assert after == 0
