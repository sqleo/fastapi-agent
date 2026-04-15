"""入库管道入口：单文件在单知识库下的向量化写入（worker 调用）."""

from __future__ import annotations

import logging

from llama_index.core.indices.utils import embed_nodes
from llama_index.core.schema import (
    NodeRelationship,
    ObjectType,
    RelatedNodeInfo,
    TextNode,
)

from rag.chunking.splitter import split_documents
from rag.contracts import IngestContext, IngestResult
from rag.embedding.factory import build_llama_embedding_from_config
from rag.loaders.parsed_md import load_parsed_md_documents
from rag.stores.milvus_store import (
    build_milvus_vector_store,
    flush_milvus_collection,
    load_milvus_collection,
)
from shared.embedding.config import EmbeddingConfig
from shared.embedding.exceptions import EmbeddingConfigurationError
from shared.embedding.sync_resolve import sync_resolve_embedding_config

logger = logging.getLogger(__name__)


def _attach_kb_metadata(nodes: list, ctx: IngestContext) -> None:
    """为每个节点设置 metadata 和 SOURCE relationships（已较好）。"""
    kid = str(int(ctx.kb_file_link_id))
    source_ref = RelatedNodeInfo(node_id=kid, node_type=ObjectType.DOCUMENT)

    for i, node in enumerate(nodes):
        if not isinstance(node, TextNode):
            raise TypeError(f"切块须为 TextNode，实际为 {type(node).__name__}")

        meta = dict(getattr(node, "metadata", {}) or {})
        meta.pop("ref_doc_id", None)
        meta["kb_file_id"] = kid
        meta["knowledge_base_id"] = int(ctx.knowledge_base_id)
        meta["file_id"] = int(ctx.file_id)
        meta["owner_user_id"] = int(ctx.owner_user_id)

        rel = dict(getattr(node, "relationships", {}) or {})
        rel[NodeRelationship.SOURCE] = source_ref

        sep = getattr(node, "metadata_separator", None) or getattr(node, "metadata_seperator", "\n")

        # 重建节点（提前清理）
        nodes[i] = TextNode(
            id_=node.id_,
            text=node.text,
            metadata=meta,
            embedding=None,
            relationships=rel,
            excluded_embed_metadata_keys=list(getattr(node, "excluded_embed_metadata_keys", [])),
            excluded_llm_metadata_keys=list(getattr(node, "excluded_llm_metadata_keys", [])),
            metadata_separator=sep,
            metadata_template=getattr(node, "metadata_template", None),
            text_template=getattr(node, "text_template", None),
            mimetype=getattr(node, "mimetype", "text/plain"),
            start_char_idx=getattr(node, "start_char_idx", None),
            end_char_idx=getattr(node, "end_char_idx", None),
        )


def ingest_parsed_md_for_kb_file(
    ctx: IngestContext,
    *,
    embedding_config: EmbeddingConfig | None = None,
) -> IngestResult:
    """入库嵌入仅来自数据库（``llm_global_setting`` + ``llm_vendor`` 解析为 ``EmbeddingConfig``）。

    若未传入 ``embedding_config``，则按 ``ctx.owner_user_id`` 同步解析（与 worker 中异步解析二选一即可）。
    """
    if embedding_config is None:
        try:
            embedding_config = sync_resolve_embedding_config(ctx.owner_user_id)
        except EmbeddingConfigurationError as exc:
            return IngestResult(ok=False, chunk_count=0, error_message=str(exc))
    try:
        embed_model = build_llama_embedding_from_config(embedding_config)
        if embed_model is None:
            return IngestResult(
                ok=False,
                chunk_count=0,
                error_message="未安装 llama-index-core 或依赖不完整",
            )

        documents = load_parsed_md_documents(ctx.parsed_md_storage_key)
        nodes = split_documents(documents)
        if not nodes:
            return IngestResult(ok=True, chunk_count=0, error_message=None)

        _attach_kb_metadata(nodes, ctx)

        vector_store = build_milvus_vector_store(dim=embedding_config.dimensions)
        ref_doc_id = str(int(ctx.kb_file_link_id))

        # 删除旧向量（须先 load，否则 query/delete 报 collection not loaded）
        try:
            load_milvus_collection(vector_store)
            vector_store.delete(ref_doc_id=ref_doc_id)
        except Exception as exc:
            logger.warning(
                "Milvus 删除旧向量失败 (ref_doc_id=%s): %s", ref_doc_id, exc
            )

        # 嵌入（此时 nodes 已经干净）
        id_to_emb = embed_nodes(nodes, embed_model, show_progress=False)

        to_milvus: list[TextNode] = []
        source_ref = RelatedNodeInfo(
            node_id=ref_doc_id,
            node_type=ObjectType.DOCUMENT,
        )

        for node in nodes:
            emb = id_to_emb.get(node.node_id)
            if emb is None:
                logger.warning("节点 %s 嵌入为空，跳过", node.node_id)
                continue

            # 再次完全重建（最关键：不依赖 node.relationships 的原始 dict）
            rel = {NodeRelationship.SOURCE: source_ref}
            # 只保留非 SOURCE 的其他关系（如果有）
            for k, v in getattr(node, "relationships", {}).items():
                if k != NodeRelationship.SOURCE:
                    rel[k] = v

            meta = dict(getattr(node, "metadata", {}) or {})

            sep = getattr(node, "metadata_separator", None) or getattr(node, "metadata_seperator", "\n")

            new_node = TextNode(
                id_=node.id_,
                text=node.text,
                metadata=meta,
                embedding=emb,
                relationships=rel,
                excluded_embed_metadata_keys=list(getattr(node, "excluded_embed_metadata_keys", [])),
                excluded_llm_metadata_keys=list(getattr(node, "excluded_llm_metadata_keys", [])),
                metadata_separator=sep,
                metadata_template=getattr(node, "metadata_template", None),
                text_template=getattr(node, "text_template", None),
                mimetype=getattr(node, "mimetype", "text/plain"),
                start_char_idx=getattr(node, "start_char_idx", None),
                end_char_idx=getattr(node, "end_char_idx", None),
            )
            to_milvus.append(new_node)

        if not to_milvus:
            return IngestResult(
                ok=False,
                chunk_count=0,
                error_message="向量化后无有效切块（嵌入为空或全部被跳过），未写入 Milvus",
            )

        vector_store.add(to_milvus)
        try:
            flush_milvus_collection(vector_store)
        except Exception as exc:
            logger.warning("Milvus flush 失败（数据可能已写入但未落盘可见）: %s", exc)

        # 首次建集合并 insert 后服务端未必 Loaded；不 load 则后续检索会报 collection not loaded
        try:
            load_milvus_collection(vector_store)
        except Exception as exc:
            logger.warning("Milvus load_collection 失败（检索前仍会尝试 load）: %s", exc)

        return IngestResult(ok=True, chunk_count=len(to_milvus), error_message=None)

    except Exception as exc:
        logger.exception("ingest_parsed_md_for_kb_file 失败")
        return IngestResult(ok=False, chunk_count=0, error_message=str(exc))