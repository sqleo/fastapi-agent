"""LlamaIndex ``MilvusVectorStore``；Milvus 连接来自环境变量，向量维度须与 ``EmbeddingConfig.dimensions`` 一致.

启用 ``enable_sparse`` 后集合 schema 含稠密向量 + Milvus BM25 稀疏字段，检索侧使用 ``hybrid``。
稠密索引用 ``HNSW``（原默认 FLAT）；

内置 BM25（``pymilvus.Function`` / BM25）时，部分 Milvus 版本在 ``hybrid_search`` 上对稀疏列与查询类型校验过严会报错
（``VECTOR_SPARSE_FLOAT`` vs ``VARCHAR``）。此处对内置 BM25 改为两次 ``search`` + 客户端 RRF/加权融合，语义与原先 ranker 配置一致。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymilvus import DataType

from shared.embedding.config import FIXED_EMBEDDING_DIMENSION

logger = logging.getLogger(__name__)

# 与 llama_index.vector_stores.milvus.base 保持一致
_MILVUS_ID_FIELD = "id"

# 与入库时写入的 node.metadata 键一致，便于 Milvus 标量过滤（检索侧）
RAG_SCALAR_FIELD_NAMES: tuple[str, ...] = (
    "kb_file_id",
    "knowledge_base_id",
    "file_id",
    "owner_user_id",
)
RAG_SCALAR_FIELD_TYPES: tuple[Any, ...] = (
    DataType.VARCHAR,
    DataType.INT64,
    DataType.INT64,
    DataType.INT64,
)


def load_milvus_collection(vector_store: Any) -> None:
    """在 ``delete`` / ``query`` 前调用；集合未 load 时 Milvus 报 ``collection not loaded``。"""
    client = vector_store.client
    name = vector_store.collection_name
    try:
        from pymilvus.client.types import LoadState

        if client.get_load_state(collection_name=name) == LoadState.Loaded:
            return
    except Exception:
        pass
    client.load_collection(collection_name=name)


def flush_milvus_collection(vector_store: Any) -> None:
    """插入后 flush，便于查询与 Attu 等控制台尽快看到条数。"""
    vector_store.client.flush(collection_name=vector_store.collection_name)


class MilvusVectorStoreSparseInsertPatch:
    """BM25 内置函数路径下为 ``sparse_embedding`` 写入空占位 ``{}``。

    部分 Milvus 要求 insert 行必须包含该字段；LlamaIndex 原实现省略该键，会触发 ``DataNotMatchException``。
    """

    def _build_insert_rows(self, nodes: list) -> tuple[list, list[str]]:
        from llama_index.core.vector_stores.utils import node_to_metadata_dict
        from llama_index.vector_stores.milvus.utils import BaseSparseEmbeddingFunction

        insert_list: list = []
        insert_ids: list[str] = []

        if self.enable_sparse is True and self.sparse_embedding_function is None:
            logger.critical(
                "语料入库时sparse_embedding_function 为空, enable_sparse 为 True.",
            )

        for node in nodes:
            entry = node_to_metadata_dict(
                node, remove_text=True, text_field=self.text_key
            )
            entry[self.text_key] = node.dict()[self.text_key]
            entry[_MILVUS_ID_FIELD] = node.node_id
            if self.enable_dense:
                entry[self.embedding_field] = node.embedding
            if self.enable_sparse:
                if isinstance(
                    self.sparse_embedding_function, BaseSparseEmbeddingFunction
                ):
                    entry[self.sparse_embedding_field] = (
                        self.sparse_embedding_function.encode_documents([node.text])[0]
                    )
                else:
                    entry[self.sparse_embedding_field] = {}

            insert_ids.append(node.node_id)
            insert_list.append(entry)

        return insert_list, insert_ids

    def add(self, nodes: list, **add_kwargs: Any) -> list[str]:
        from llama_index.core.utils import iter_batch

        insert_list, insert_ids = self._build_insert_rows(nodes)

        if self.upsert_mode:
            executor_wrapper = self.client.upsert
        else:
            executor_wrapper = self.client.insert

        for insert_batch in iter_batch(insert_list, self.batch_size):
            executor_wrapper(
                self.collection_name,
                insert_batch,
                partition_name=add_kwargs.get("milvus_partition_name"),
            )
        if add_kwargs.get("force_flush", False):
            self.client.flush(self.collection_name)
        logger.debug(
            "Successfully inserted embeddings into: %s Num Inserted: %s",
            self.collection_name,
            len(insert_list),
        )
        return insert_ids

    async def async_add(self, nodes: list, **add_kwargs: Any) -> list[str]:
        from llama_index.core.utils import iter_batch

        assert self.aclient is not None, (
            "异步客户端不能为空。请在 MilvusVectorStore 中传递 use_async_client=True。"
        )

        insert_list, insert_ids = self._build_insert_rows(nodes)

        if self.upsert_mode:
            executor_wrapper = self.aclient.upsert
        else:
            executor_wrapper = self.aclient.insert

        for insert_batch in iter_batch(insert_list, self.batch_size):
            await executor_wrapper(
                self.collection_name,
                insert_batch,
                partition_name=add_kwargs.get("milvus_partition_name"),
            )
        if add_kwargs.get("force_flush", False):
            raise NotImplementedError(" 异步模式下不支持 force_flush。")
        logger.debug(
            "Successfully inserted embeddings into: %s Num Inserted: %s",
            self.collection_name,
            len(insert_list),
        )
        return insert_ids


class MilvusBM25HybridSearchMixin:
    """对 Milvus 内置 BM25：用两次 ``search`` 替代 ``hybrid_search``，避免服务端 hybrid 计划与 BM25 文本查询不兼容。"""

    def _hybrid_search_bm25_builtin_split(
        self,
        query: Any,
        string_expr: str,
        output_fields: list[str],
        **kwargs: Any,
    ) -> tuple[list, list[float], list[str]]:
        """同步混合检索：先同步检索稠密向量，再同步检索稀疏向量，最后合并结果。"""
        dense = self._default_search(query, string_expr, output_fields, **kwargs)
        sparse = self._sparse_search(query, string_expr, output_fields, **kwargs)
        return self._merge_hybrid_dense_sparse_results(
            dense, sparse, query.similarity_top_k
        )

    async def _async_hybrid_search_bm25_builtin_split(
        self,
        query: Any,
        string_expr: str,
        output_fields: list[str],
        **kwargs: Any,
    ) -> tuple[list, list[float], list[str]]:
        """异步混合检索：先异步检索稠密向量，再异步检索稀疏向量，最后合并结果。"""
        dense_task = self._async_default_search(
            query, string_expr, output_fields, **kwargs
        )
        sparse_task = self._async_sparse_search(
            query, string_expr, output_fields, **kwargs
        )
        dense, sparse = await asyncio.gather(dense_task, sparse_task)
        return self._merge_hybrid_dense_sparse_results(
            dense, sparse, query.similarity_top_k
        )

    def _merge_hybrid_dense_sparse_results(
        self,
        dense: tuple[list, list[float], list[str]],
        sparse: tuple[list, list[float], list[str]],
        limit: int,
    ) -> tuple[list, list[float], list[str]]:
        """合并稠密和稀疏检索结果。"""
        d_nodes, d_sims, d_ids = dense
        s_nodes, s_sims, s_ids = sparse
        id_to_node: dict[str, Any] = {}
        for node, pid in zip(d_nodes, d_ids, strict=False):
            id_to_node[pid] = node
        for node, pid in zip(s_nodes, s_ids, strict=False):
            id_to_node.setdefault(pid, node)

        if not d_ids and not s_ids:
            return [], [], []

        ranker = getattr(self, "hybrid_ranker", "RRFRanker")
        raw_params = getattr(self, "hybrid_ranker_params", None) or {}
        params = dict(raw_params)

        if ranker == "RRFRanker":
            if not params:
                params = {"k": 60}
            k = int(params.get("k", 60))
            fused: dict[str, float] = {}
            for rank, pid in enumerate(d_ids, start=1):
                fused[pid] = fused.get(pid, 0.0) + 1.0 / (k + rank)
            for rank, pid in enumerate(s_ids, start=1):
                fused[pid] = fused.get(pid, 0.0) + 1.0 / (k + rank)
            ordered = sorted(fused.keys(), key=lambda x: -fused[x])[:limit]
            sims = [fused[pid] for pid in ordered]
        elif ranker == "WeightedRanker":
            if not params:
                params = {"weights": [1.0, 1.0], "norm_score": True}
            weights = params.get("weights", [1.0, 1.0])
            norm_score = params.get("norm_score", True)
            w_dense, w_sparse = float(weights[0]), float(weights[1])

            def _norm_map(
                ids: list[str], sims: list[float]
            ) -> dict[str, float]:
                if not ids:
                    return {}
                if not norm_score:
                    return dict(zip(ids, sims, strict=False))
                mn, mx = min(sims), max(sims)
                if mx == mn:
                    normed = [1.0] * len(sims)
                else:
                    normed = [(s - mn) / (mx - mn) for s in sims]
                return dict(zip(ids, normed, strict=False))

            d_map = _norm_map(d_ids, d_sims)
            s_map = _norm_map(s_ids, s_sims)
            all_ids = set(d_map) | set(s_map)
            combined = {
                pid: w_dense * d_map.get(pid, 0.0) + w_sparse * s_map.get(pid, 0.0)
                for pid in all_ids
            }
            ordered = sorted(combined.keys(), key=lambda x: -combined[x])[:limit]
            sims = [combined[pid] for pid in ordered]
        else:
            raise ValueError(f"Unsupported ranker: {ranker}")

        nodes = [id_to_node[pid] for pid in ordered]
        return nodes, sims, list(ordered)

    def _hybrid_search(self, query: Any, string_expr: str, output_fields: list[str], **kwargs: Any):  # type: ignore[override]
        try:
            from pymilvus import Function as BaseMilvusBuiltInFunction
        except ImportError:
            return super()._hybrid_search(query, string_expr, output_fields, **kwargs)
        if isinstance(self.sparse_embedding_function, BaseMilvusBuiltInFunction):
            return self._hybrid_search_bm25_builtin_split(
                query, string_expr, output_fields, **kwargs
            )
        return super()._hybrid_search(query, string_expr, output_fields, **kwargs)

    async def _async_hybrid_search(  # type: ignore[override]
        self, query: Any, string_expr: str, output_fields: list[str], **kwargs: Any
    ):
        try:
            from pymilvus import Function as BaseMilvusBuiltInFunction
        except ImportError:
            return await super()._async_hybrid_search(
                query, string_expr, output_fields, **kwargs
            )
        if isinstance(self.sparse_embedding_function, BaseMilvusBuiltInFunction):
            return await self._async_hybrid_search_bm25_builtin_split(
                query, string_expr, output_fields, **kwargs
            )
        return await super()._async_hybrid_search(
            query, string_expr, output_fields, **kwargs
        )


def build_milvus_vector_store(*, dim: int | None = None) -> Any:
    """构造 ``MilvusVectorStore``；``dim`` 默认与全局嵌入维度一致，入库/检索时应传入 ``EmbeddingConfig.dimensions``。"""
    from llama_index.core.vector_stores.utils import DEFAULT_TEXT_KEY
    from llama_index.vector_stores.milvus import MilvusVectorStore
    from llama_index.vector_stores.milvus.utils import (
        BM25BuiltInFunction,
        DEFAULT_SPARSE_EMBEDDING_KEY,
    )

    from rag.config import (
        milvus_connection_kwargs,
        milvus_token,
        milvus_uri,
        rag_milvus_collection_name,
        rag_milvus_hybrid_ranker,
        rag_milvus_hybrid_ranker_params,
    )

    d = int(dim) if dim is not None else FIXED_EMBEDDING_DIMENSION
    extra = milvus_connection_kwargs()

    class _Store(
        MilvusVectorStoreSparseInsertPatch,
        MilvusBM25HybridSearchMixin,
        MilvusVectorStore,
    ):
        pass

    # 显式指定 BM25，避免 describe_collection 未带 functions 时 LlamaIndex 误选 BGEM3（依赖 FlagEmbedding）
    bm25_sparse = BM25BuiltInFunction(
        input_field_names=DEFAULT_TEXT_KEY,
        output_field_names=DEFAULT_SPARSE_EMBEDDING_KEY,
    )

    # LlamaIndex 对 BM25 内置函数默认 sparse metric 为 BM25，但 Milvus SPARSE_INVERTED_INDEX
    # 仅支持 IP（见 milvus-io/milvus#39652）；检索侧 hybrid 仍用 BM25 查询语义。
    return _Store(
        uri=milvus_uri(),
        token=milvus_token(),
        collection_name=rag_milvus_collection_name(),
        dim=d,
        overwrite=False,
        upsert_mode=False,
        consistency_level="Strong",
        similarity_metric="IP",
        index_config={
            "index_type": "HNSW",
            "M": 16, # 稠密向量索引参数
            "efConstruction": 200, # 稠密向量索引参数
        },
        search_config={"ef": 64},
        enable_sparse=True,
        sparse_embedding_function=bm25_sparse,
        sparse_index_config={"metric_type": "IP"},
        scalar_field_names=list(RAG_SCALAR_FIELD_NAMES),
        scalar_field_types=list(RAG_SCALAR_FIELD_TYPES),
        hybrid_ranker=rag_milvus_hybrid_ranker(),
        hybrid_ranker_params=rag_milvus_hybrid_ranker_params(),
        **extra,
    )
