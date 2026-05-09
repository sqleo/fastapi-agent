"""单元测试：记忆相关核心模块的导入与基础结构。"""

from __future__ import annotations

import pytest
from langgraph.store.base import GetOp, InvalidNamespaceError, ListNamespacesOp, PutOp, SearchOp


def test_advanced_memory_imports() -> None:
    from infra.memory.advanced_memory import AdvancedMemoryManager, MemoryEntry

    assert AdvancedMemoryManager is not None
    assert MemoryEntry is not None


def test_memory_entry_roundtrip() -> None:
    from infra.memory.advanced_memory import MemoryEntry

    entry = MemoryEntry(
        category="events",
        content="user asked about weather",
        turn_number=1,
        is_summary=False,
    )
    data = entry.to_dict()
    assert data["category"] == "events"
    assert data["content"] == "user asked about weather"
    assert data["turn_number"] == 1
    assert data["is_summary"] is False

    restored = MemoryEntry.from_dict(data)
    assert restored.category == entry.category
    assert restored.content == entry.content
    assert restored.turn_number == entry.turn_number
    assert restored.is_summary == entry.is_summary


def test_advanced_memory_manager_namespace() -> None:
    """AdvancedMemoryManager 必须把 user_id 放进 namespace[1]。

    多租户路由强依赖此约定（``TenantRoutingStore._resolve_user_id``）。
    """
    from unittest.mock import patch

    from infra.memory.advanced_memory import AdvancedMemoryManager

    sentinel = object()
    with patch("infra.memory.advanced_memory.get_langgraph_store", return_value=sentinel):
        manager = AdvancedMemoryManager(user_id=999)
    assert manager.user_id == 999
    assert manager.namespace == ("user_memories", "999")
    assert manager.store is sentinel


def test_schema_name_format() -> None:
    from infra.langgraph.tenant_store import schema_name

    assert schema_name(1, 1) == "mem_u1_v1"
    assert schema_name(42, 7) == "mem_u42_v7"


@pytest.mark.parametrize(
    "namespace",
    [
        (),
        ("user_memories",),
        ("user_memories", ""),
        ("user_memories", "abc"),
        ("user_memories", "0"),
        ("user_memories", "-1"),
    ],
)
def test_resolve_user_id_invalid_raises(namespace) -> None:
    from infra.langgraph.tenant_store import _resolve_user_id

    with pytest.raises(InvalidNamespaceError):
        _resolve_user_id(namespace)


def test_resolve_user_id_valid() -> None:
    from infra.langgraph.tenant_store import _resolve_user_id

    assert _resolve_user_id(("user_memories", "42")) == 42
    assert _resolve_user_id(("agent_memories", "7", "thread-x")) == 7
    assert _resolve_user_id(("user_memories", " 99 ")) == 99


def test_op_namespace_extraction() -> None:
    from infra.langgraph.tenant_store import _op_namespace

    assert _op_namespace(GetOp(("a", "1"), key="k")) == ("a", "1")
    assert _op_namespace(PutOp(("a", "1"), key="k", value={"x": 1})) == ("a", "1")
    assert _op_namespace(
        SearchOp(namespace_prefix=("a", "1"), filter=None, limit=10, offset=0, query="q")
    ) == ("a", "1")
    with pytest.raises(InvalidNamespaceError):
        _op_namespace(ListNamespacesOp())


def test_routing_store_rejects_listnamespaces() -> None:
    """ListNamespacesOp 跨租户列举不安全，必须直接拒绝。"""
    import asyncio

    from infra.langgraph.tenant_store import TenantRoutingStore

    store = TenantRoutingStore()
    with pytest.raises(InvalidNamespaceError):
        asyncio.run(store.abatch([ListNamespacesOp()]))
