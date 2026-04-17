"""知识库向量检索：Milvus 混合检索（dense + BM25），按用户与可选知识库 id 过滤。"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.tools import tool
from llama_index.core.vector_stores.types import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
    VectorStoreQuery,
    VectorStoreQueryMode,
)

from agent.tools.runtime_user import langgraph_runtime_user_id

logger = logging.getLogger(__name__)

_TOP_K_MIN = 1
_TOP_K_MAX = 30
_TEXT_PREVIEW = 4000


def _clamp_top_k(top_k: int) -> int:
    if top_k < _TOP_K_MIN:
        return _TOP_K_MIN
    if top_k > _TOP_K_MAX:
        return _TOP_K_MAX
    return top_k


def search_user_knowledge_vectors_sync(
    *,
    query: str,
    owner_user_id: int,
    top_k: int = 5,
    knowledge_base_id: int | None = None,
) -> str:
    """对 Milvus 做混合检索，仅返回属于 ``owner_user_id`` 的片段（可选限定知识库）。

    延迟 import 嵌入与 Milvus，避免在仅加载 LangGraph 图时要求本机存在模型文件或拉起 SentenceTransformer。
    """
    from llamarag.local_model.embed_model import embed_model
    from llamarag.storage.vector_store import vector_store

    q = (query or "").strip()
    if not q:
        return "检索失败：查询文本为空。"

    k = _clamp_top_k(top_k)
    filters: list[MetadataFilter] = [
        MetadataFilter(
            key="owner_user_id",
            value=int(owner_user_id),
            operator=FilterOperator.EQ,
        ),
    ]
    if knowledge_base_id is not None:
        filters.append(
            MetadataFilter(
                key="knowledge_base_id",
                value=int(knowledge_base_id),
                operator=FilterOperator.EQ,
            )
        )
    meta = MetadataFilters(filters=filters)

    try:
        q_emb = embed_model.get_query_embedding(q)
    except FileNotFoundError as e:
        logger.exception("向量检索：嵌入模型路径不存在")
        return (
            "检索失败：服务端未找到嵌入模型文件。"
            "请在镜像中挂载或复制 BGE 模型目录（与 scripts/download_model.py 一致），或设置可用路径。"
            f"（{e}）"
        )
    except Exception:
        logger.exception("向量检索：查询嵌入失败")
        return "检索失败：无法为查询生成向量，请稍后重试。"

    vsq = VectorStoreQuery(
        query_embedding=q_emb,
        query_str=q,
        similarity_top_k=k,
        mode=VectorStoreQueryMode.HYBRID,
        filters=meta,
    )
    try:
        result = vector_store.query(vsq)
    except Exception:
        logger.exception("向量检索：Milvus 查询失败")
        return (
            "检索失败：向量库暂不可用或服务异常。"
            "请确认 Milvus 已启动且知识库内容已入库。"
        )

    nodes = result.nodes or []
    sims = result.similarities or []
    if not nodes:
        return (
            "未找到与查询相关的知识库片段。"
            "可尝试改写问题，或确认对应文件已解析并完成入库。"
        )

    lines: list[str] = [f"共 {len(nodes)} 条相关片段（按相关度排序）：", ""]
    for i, node in enumerate(nodes, start=1):
        meta_d = getattr(node, "metadata", None) or {}
        kb = meta_d.get("knowledge_base_id")
        fid = meta_d.get("file_id")
        score = None
        if i - 1 < len(sims) and sims[i - 1] is not None:
            try:
                score = float(sims[i - 1])
            except (TypeError, ValueError):
                score = None
        head = f"### 片段 {i}"
        if score is not None:
            head += f"（相关度 {score:.4f}）"
        head += f"\n- 知识库 ID: {kb}，文件 ID: {fid}\n\n"
        text = (getattr(node, "text", None) or "").strip()
        if len(text) > _TEXT_PREVIEW:
            text = text[:_TEXT_PREVIEW].rstrip() + "…"
        lines.append(head + text)
        lines.append("")

    return "\n".join(lines).strip()


@tool
async def milvus_search(
    query: str,
    top_k: int = 5,
    knowledge_base_id: int | None = None,
) -> str:
    """搜索向量数据库中的文档，返回与查询相关的文档。

    归属用户由服务端从登录会话注入，模型不可指定租户。
    不传 ``knowledge_base_id`` 时：检索**当前用户下全部知识库**；传入时：仅检索**该知识库 id** 下已入库片段。

    Args:
        query: 搜索查询文本。
        top_k: 返回结果数量，默认为 5。
        knowledge_base_id: 可选；指定则只搜该知识库，不传则搜该用户下所有知识库。
    """
    owner_user_id = langgraph_runtime_user_id()
    if owner_user_id is None:
        return (
            "检索失败：无法解析当前登录用户上下文。"
            "请确认通过已登录会话调用 Agent，且 LangGraph 配置中包含 user_id。"
        )
    return await asyncio.to_thread(
        search_user_knowledge_vectors_sync,
        query=query,
        owner_user_id=owner_user_id,
        top_k=top_k,
        knowledge_base_id=knowledge_base_id,
    )
