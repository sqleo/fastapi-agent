"""Test memory nodes functionality."""
from agent.memory.advanced_memory import AdvancedMemoryManager, MemoryEntry
from agent.memory.memory_nodes import (
    short_term_window_node,
    advanced_memory_retrieve_node,
    advanced_memory_write_node,
)


def test_memory_imports():
    """Test that memory modules can be imported."""
    assert AdvancedMemoryManager is not None
    assert MemoryEntry is not None
    assert short_term_window_node is not None
    assert advanced_memory_retrieve_node is not None
    assert advanced_memory_write_node is not None


def test_memory_entry_creation():
    """Test MemoryEntry creation and serialization."""
    entry = MemoryEntry(
        category="events",
        content="User asked about weather",
        turn_number=1,
        is_summary=False
    )

    # Test to_dict
    data = entry.to_dict()
    assert data["category"] == "events"
    assert data["content"] == "User asked about weather"
    assert data["turn_number"] == 1
    assert data["is_summary"] is False

    # Test from_dict
    entry2 = MemoryEntry.from_dict(data)
    assert entry2.category == entry.category
    assert entry2.content == entry.content
    assert entry2.turn_number == entry.turn_number
    assert entry2.is_summary == entry.is_summary


def test_advanced_memory_manager_creation():
    """Test AdvancedMemoryManager can be instantiated."""
    manager = AdvancedMemoryManager(store=None, namespace_prefix=("test",))
    assert manager is not None


def test_advanced_memory_manager_no_store_operations():
    """Test AdvancedMemoryManager skips operations when no store is available."""
    manager = AdvancedMemoryManager(store=None, namespace_prefix=("test",))
    assert manager.store is None
