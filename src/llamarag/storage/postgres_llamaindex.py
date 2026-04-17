"""LlamaIndex 专用 Postgres：docstore + index_store.

与 LangGraph checkpoint、LangMem ``PostgresStore`` **完全隔离**：

- **只读** ``LLAMAINDEX_POSTGRES_URI``（或 ``env_config.llamaindex_postgres_uri``）；
- **绝不**使用 ``POSTGRES_URI`` / ``LANGMEM_POSTGRES_URI``。
- 表建在 schema ``llamaindex`` 下，避免与业务库 ``public`` 中其它表混放。

未配置 URI 时，``get_llamaindex_docstore`` / ``get_llamaindex_index_store`` 返回 ``None``，
``ingestion_pipeline`` 行为与仅使用 Milvus 时一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from configs.env import env_config

if TYPE_CHECKING:
    from llama_index.core import StorageContext
    from llama_index.storage.docstore.postgres import PostgresDocumentStore
    from llama_index.storage.index_store.postgres import PostgresIndexStore

# 与 LangGraph / LangMem 无关的专用 schema、表名
_LLAMAINDEX_SCHEMA = "llamaindex"
_DOCSTORE_TABLE = "li_docstore"
_INDEXSTORE_TABLE = "li_indexstore"

_initialized: bool = False
_docstore: PostgresDocumentStore | None = None
_index_store: PostgresIndexStore | None = None


def _postgres_uri() -> str:
    return (env_config.llamaindex_postgres_uri or "").strip()


def _ensure_stores() -> None:
    global _initialized, _docstore, _index_store
    if _initialized:
        return
    _initialized = True
    uri = _postgres_uri()
    if not uri:
        _docstore = None
        _index_store = None
        return

    from llama_index.storage.docstore.postgres import PostgresDocumentStore
    from llama_index.storage.index_store.postgres import PostgresIndexStore

    _docstore = PostgresDocumentStore.from_uri(
        uri=uri,
        namespace=None,
        table_name=_DOCSTORE_TABLE,
        schema_name=_LLAMAINDEX_SCHEMA,
        perform_setup=True,
        use_jsonb=True,
    )
    _index_store = PostgresIndexStore.from_uri(
        uri=uri,
        namespace=None,
        table_name=_INDEXSTORE_TABLE,
        schema_name=_LLAMAINDEX_SCHEMA,
        perform_setup=True,
        use_jsonb=True,
    )


def get_llamaindex_docstore() -> PostgresDocumentStore | None:
    """LlamaIndex 文档存储；未配置 ``LLAMAINDEX_POSTGRES_URI`` 时为 ``None``."""
    _ensure_stores()
    return _docstore


def get_llamaindex_index_store() -> PostgresIndexStore | None:
    """LlamaIndex 索引元数据存储；未配置 URI 时为 ``None``."""
    _ensure_stores()
    return _index_store


def get_llamaindex_storage_context() -> StorageContext | None:
    """``vector_store`` + docstore + index_store；未配置 Postgres 时为 ``None``."""
    from llama_index.core import StorageContext

    _ensure_stores()
    if _docstore is None or _index_store is None:
        return None
    from llamarag.storage.vector_store import vector_store

    return StorageContext.from_defaults(
        vector_store=vector_store,
        docstore=_docstore,
        index_store=_index_store,
    )
