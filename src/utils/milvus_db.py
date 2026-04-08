"""Milvus 全局访问：langchain_milvus.Milvus + 多集合缓存；兼容 pymilvus 2.6 ORM 连接。"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

from dotenv import load_dotenv
from langchain_milvus import Milvus
from pymilvus import MilvusException

from utils.embedding_init import create_embeddings

load_dotenv()

logger = logging.getLogger(__name__)

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


def delete_vectors_by_kb_file_id(
    kb_file_id: int,
    *,
    collection_name: str | None = None,
) -> bool:
    """
    删除集合中 ``metadata.kb_file_id`` 等于该文件 id 的全部向量，避免同一文件重复入库。

    与 ``chunk_and_embed`` 写入时使用的字段一致（字符串形式的 id）。
    """
    kid = str(int(kb_file_id))
    vs = get_vector_store(collection_name)
    expr = f'kb_file_id == "{kid}"'
    try:
        ok = vs.delete(expr=expr)
        if ok:
            logger.info("[milvus] 已删除 kb_file 旧向量 kb_file_id=%s", kb_file_id)
        else:
            logger.warning(
                "[milvus] delete(expr) 返回 False kb_file_id=%s expr=%s",
                kb_file_id,
                expr,
            )
        return bool(ok)
    except MilvusException as e:
        # 集合为空、字段尚未创建或表达式不兼容旧 schema 时可能失败；记录后继续由调用方 insert
        logger.warning(
            "[milvus] 按 kb_file_id 删除跳过（将直接写入新向量）kb_file_id=%s err=%s",
            kb_file_id,
            e,
        )
        return False


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

    def delete_vectors_by_kb_file_id(
        self, kb_file_id: int, collection_name: str | None = None
    ) -> bool:
        return delete_vectors_by_kb_file_id(
            kb_file_id, collection_name=collection_name
        )

    def similarity_search(self, query: str, k: int = 5):
        return get_vector_store().similarity_search(query, k=k)


milvus_service = MilvusService()
