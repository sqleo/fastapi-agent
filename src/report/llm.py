import os

from langchain.chat_models import init_chat_model


async def create_llm(
    code: str,
    max_tokens: int = 8000,
    thread_id: str | None = None,
    user_id: str | None = None,
):
    """创建 LLM 实例（统一使用全局 chat_llm 配置）并自动附加 Token 监控回调。
    
    thread_id / user_id 未传入时，从 LangGraph configurable 上下文自动读取。
    """
    if thread_id is None or user_id is None:
        try:
            from langgraph.config import get_config
            cfg = get_config() or {}
            configurable = cfg.get("configurable") or {}
            thread_id = thread_id or cfg.get("thread_id") or configurable.get("thread_id")
            user_id = user_id or configurable.get("user_id")
        except Exception:
            pass

    if not user_id:
        raise ValueError("研报模块必须提供 user_id 才能获取全局模型配置")

    from llm_completion.chat_llm import chat_llm
    from utils.sql_db import async_session

    async with async_session() as session:
        llm = await chat_llm(session, int(user_id), max_tokens=max_tokens)

    # 提取模型名称和提供商，用于监控（LiteLLM 返回的是类似 ChatLiteLLM 实例）
    model_name_label = getattr(llm, "model", "dynamic-model")
    provider = getattr(llm, "api_base", "unified-provider")

    from report.utils.monitor_callback import ReportTokenCallback
    callback = ReportTokenCallback(
        model=model_name_label,
        provider=str(provider),
        thread_id=thread_id,
        user_id=str(user_id),
    )

    return llm.with_config({"callbacks": [callback]})
