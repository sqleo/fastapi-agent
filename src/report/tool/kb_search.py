from langchain.tools import tool
import asyncio
from report.utils.emit_trace_event import emit_trace_event

@tool("kb_search", description="使用知识库搜索工具进行查询，返回搜索结果摘要。")
async def kb_search(query: str) -> str:
    """使用知识库搜索工具进行查询，返回搜索结果摘要。"""
    emit_trace_event("kb_search", {"description": f"执行真实知识库搜索", "query": query})
    print(f"🔍 正在执行真实知识库搜索，查询: {query}")
    
    from agent.tools.runtime_user import langgraph_runtime_user_id
    from agent.tools.vector_search import search_user_knowledge_vectors_sync

    user_id = langgraph_runtime_user_id()
    if user_id is None:
        error_msg = "知识库检索失败：无法从 LangGraph 提取 user_id 上下文"
        emit_trace_event("kb_search", {"description": "知识库搜索失败", "error": error_msg})
        return error_msg

    try:
        # 调用实际的混合向量检索 (BM25 + Dense)
        result = await asyncio.to_thread(
            search_user_knowledge_vectors_sync,
            query=query,
            owner_user_id=int(user_id),
            top_k=5, # 默认取最相关的5条
        )
        emit_trace_event("kb_search", {"description": "知识库搜索完成", "result_length": len(result)})
        return result
    except Exception as e:
        error_msg = f"知识库检索报错: {str(e)}"
        emit_trace_event("kb_search", {"description": "知识库搜索异常", "error": error_msg})
        return error_msg