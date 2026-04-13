"""知识库向量检索工具（与 ``milvus_search`` 能力一致，名称与「知识库搜索」语义一致）."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from agent.tools.runtime_user import langgraph_runtime_user_id
from rag.query.search import milvus_similarity_search_text_async


def _emit_custom_stream(payload: dict[str, Any]) -> None:
    """通过 LangGraph ``StreamWriter`` 推送自定义块（需 ``stream_mode`` 含 ``custom``）。

    仅在图内工具执行上下文有效；无上下文时静默跳过。
    """
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(payload)
    except Exception:
        pass


@tool
async def knowledge_base_search(
    query: str,
    top_k: int = 5,
    knowledge_base_id: int | None = None,
) -> str:
    """在已入库的知识库中做语义检索，返回与问题相关的文档片段。

    归属用户由服务端从登录会话注入，模型**不可**指定租户。
    - **不传** ``knowledge_base_id``：在**当前用户下全部知识库**中检索（合并后取最相近片段）。
    - **传入** ``knowledge_base_id``：仅在该知识库已入库的文件片段中检索。

    本工具为 **async**，在 LangGraph 异步循环内解析嵌入，避免与 ``asyncio.run`` 跨循环冲突。

    流式调试：通过 ``get_stream_writer`` 写入 ``custom`` 块，``phase`` 为 ``start`` / ``result`` / ``error``。

    Args:
        query: 检索查询（建议与用户问题语义一致，可略作改写）。
        top_k: 返回片段条数，默认 5。
        knowledge_base_id: 可选；指定则只搜该知识库，不传则搜该用户下所有知识库。
    """
    owner_user_id = langgraph_runtime_user_id()
    if owner_user_id is None:
        msg = (
            "检索失败：无法解析当前登录用户上下文。"
            "请确认通过已登录会话调用智能客服，且 LangGraph 配置中包含 user_id。"
        )
        _emit_custom_stream(
            {
                "type": "knowledge_base_search",
                "phase": "error",
                "message": msg,
            }
        )
        return msg

    _emit_custom_stream(
        {
            "type": "knowledge_base_search",
            "phase": "start",
            "query": query,
            "top_k": top_k,
            "knowledge_base_id": knowledge_base_id,
            "owner_user_id": owner_user_id,
        }
    )
    out = await milvus_similarity_search_text_async(
        query,
        top_k=top_k,
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
    )
    _emit_custom_stream(
        {
            "type": "knowledge_base_search",
            "phase": "result",
            "content": out,
        }
    )
    return out
