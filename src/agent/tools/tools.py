"""Agent tools for LangGraph graph."""

from __future__ import annotations

from langchain_core.tools import tool

from agent.memory.langmem import LANGMEM_TOOLS
from agent.tools.decorators import hidden_from_client
from agent.tools.runtime_user import langgraph_runtime_user_id


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
    return (
        "知识库向量检索尚未在服务端实现；"
        "接入 llamarag 向量存储后将恢复 Milvus 语义检索能力。"
    )


# LangMem 工具由第三方工厂创建，统一标记为不对前端暴露
ALL_AGENT_TOOLS = [
    milvus_search,
    *[hidden_from_client(t) for t in LANGMEM_TOOLS],
]


def tool_catalog() -> list[dict[str, str | None]]:
    """全部注册工具的名称与说明（含不对前端暴露的基础工具）。

    面向前端的列表请使用 ``agent.tools.registry.tool_catalog_for_client``。
    """
    rows: list[dict[str, str | None]] = []
    for t in ALL_AGENT_TOOLS:
        rows.append(
            {
                "name": t.name,
                "description": (getattr(t, "description", None) or "").strip() or None,
            }
        )
    return rows
