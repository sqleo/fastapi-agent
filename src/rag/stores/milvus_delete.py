"""按 knowledge_base_file 主键（与入库时 ref_doc_id 一致）删除 Milvus 中向量."""

from __future__ import annotations

import logging

from rag.stores.milvus_store import build_milvus_vector_store, load_milvus_collection

logger = logging.getLogger(__name__)


def delete_kb_file_vectors_sync(*, kb_file_link_id: int, dim: int) -> None:
    """删除该库-文件关联在 Milvus 中的全部节点（``ref_doc_id == str(kb_file_link_id)``）。"""
    ref_doc_id = str(int(kb_file_link_id))
    vector_store = build_milvus_vector_store(dim=dim)
    try:
        load_milvus_collection(vector_store)
        vector_store.delete(ref_doc_id=ref_doc_id)
    except Exception as exc:
        logger.warning("Milvus 删除向量失败 (kb_file_id=%s): %s", kb_file_link_id, exc)
        raise
