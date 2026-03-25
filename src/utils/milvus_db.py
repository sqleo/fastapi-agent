"""Milvus 全局访问：langchain_milvus.Milvus + 多集合缓存；兼容 pymilvus 2.6 ORM 连接。"""

from __future__ import annotations

import os
import threading
from typing import Any, Optional

from dotenv import load_dotenv
from langchain_milvus import Milvus

from utils.embedding_init import create_embeddings

load_dotenv()

MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "MILVUS_COLLECTION")
MILVUS_DROP_OLD = os.getenv("MILVUS_DROP_OLD", "").lower() in ("1", "true", "yes")

_store_lock = threading.RLock()
_vector_stores: dict[str, Milvus] = {}
_embeddings: Any = None
_embeddings_lock = threading.Lock()
_orm_primed = False


def _get_embeddings():
    global _embeddings
    with _embeddings_lock:
        if _embeddings is None:
            _embeddings = create_embeddings("Qwen-embedding-v4")
        return _embeddings


def _connection_args() -> dict[str, Any]:
    args: dict[str, Any] = {"uri": MILVUS_URI}
    token = os.getenv("MILVUS_TOKEN", "").strip()
    if token:
        args["token"] = token
    user = os.getenv("MILVUS_USER", "").strip()
    password = os.getenv("MILVUS_PASSWORD", "").strip()
    if user and password and "token" not in args:
        args["user"] = user
        args["password"] = password
    db_name = os.getenv("MILVUS_DB_NAME", "").strip()
    if db_name:
        args["db_name"] = db_name
    return args


def _prime_orm(connection_args: dict[str, Any]) -> None:
    """集合已存在时 LangChain 初始化会走 ORM ``Collection``；须先登记 ``MilvusClient`` 的 ``cm-*`` alias。"""
    from pymilvus import MilvusClient
    from pymilvus.orm.connections import connections

    probe = MilvusClient(**connection_args)
    alias = probe._using
    if not connections.has_connection(alias):
        connections.connect(alias=alias, _unbind_with_db=True, **connection_args)


def _ensure_orm_alias(vector_store: Milvus, connection_args: dict[str, Any]) -> None:
    from pymilvus.orm.connections import connections

    alias = vector_store.client._using
    if not connections.has_connection(alias):
        connections.connect(alias=alias, _unbind_with_db=True, **connection_args)


def get_vector_store(
    collection_name: str | None = None,
    *,
    drop_old: Optional[bool] = None,
) -> Milvus:
    """
    按集合名返回缓存的 ``Milvus`` 实例（每进程、每集合名一个）。

    - ``collection_name`` 默认 ``MILVUS_COLLECTION``。
    - ``drop_old`` 默认：仅当集合名为默认集合且环境 ``MILVUS_DROP_OLD`` 为真时为 True，其余集合为 False。
    """
    global _orm_primed
    name = collection_name or MILVUS_COLLECTION
    with _store_lock:
        if name in _vector_stores:
            return _vector_stores[name]

        conn = _connection_args()
        if not _orm_primed:
            _prime_orm(conn)
            _orm_primed = True

        if drop_old is None:
            drop_old = MILVUS_DROP_OLD if name == MILVUS_COLLECTION else False

        vs = Milvus(
            embedding_function=_get_embeddings(),
            connection_args=conn,
            collection_name=name,
            consistency_level="Strong",
            drop_old=drop_old,
        )
        _ensure_orm_alias(vs, conn)
        _vector_stores[name] = vs
        return vs


class MilvusService:
    """兼容旧调用：`MilvusService().get_vector_store()` / `add_documents` / `similarity_search`。"""

    _instance: Optional[MilvusService] = None
    _singleton_lock = threading.Lock()

    def __new__(cls) -> MilvusService:
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        pass

    @property
    def embeddings(self):
        return _get_embeddings()

    def get_vector_store(self, collection_name: str | None = None) -> Milvus:
        return get_vector_store(collection_name)

    def add_documents(self, docs) -> None:
        get_vector_store().add_documents(docs)

    def similarity_search(self, query: str, k: int = 5):
        return get_vector_store().similarity_search(query, k=k)


milvus_service = MilvusService()
