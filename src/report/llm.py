import os

from langchain.chat_models import init_chat_model


REPORT_CONFIG = {
    "llm": {
        "model": "deepseek-chat",
        "model_provider": "deepseek",
        "api_key": os.getenv("DEEPSEEK_API_KEY", "sk-76066a769b8f48ffa0376a9a1132de29"),
        "base_url": "https://api.deepseek.com",
        "temperature": 0.1,
        "timeout": 60,
    },
    "illustrator": {
        "model": "qwen-image-2.0-pro",
        "model_provider": "openai",
        "api_key": os.getenv("DASHSCOPE_API_KEY", "sk-4fed42c6bb68432c84a4c7ce4a0292b5"),
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "temperature": 0.1,
        "timeout": 60,
    },
}

# provider label 映射（用于监控记录）
_PROVIDER_MAP = {
    "llm": ("deepseek", "deepseek-chat"),
    "illustrator": ("dashscope", "qwen-image-2.0-pro"),
}


async def create_llm(
    code: str,
    max_tokens: int = 8000,
    thread_id: str | None = None,
    user_id: str | None = None,
):
    """创建 LLM 实例并自动附加 Token 监控回调。

    thread_id / user_id 未传入时，从 LangGraph configurable 上下文自动读取。
    """
    # 尝试从 LangGraph 上下文读取，仅在 LangGraph 图节点中有效
    if thread_id is None or user_id is None:
        try:
            from langgraph.config import get_config
            cfg = get_config() or {}
            configurable = cfg.get("configurable") or {}
            thread_id = thread_id or cfg.get("thread_id") or configurable.get("thread_id")
            user_id = user_id or configurable.get("user_id")
        except Exception:
            pass

    provider, model_name_label = _PROVIDER_MAP.get(code, ("unknown", code))

    from report.utils.monitor_callback import ReportTokenCallback
    callback = ReportTokenCallback(
        model=model_name_label,
        provider=provider,
        thread_id=thread_id,
        user_id=user_id,
    )

    config = REPORT_CONFIG[code].copy()
    model_name = config.pop("model")
    config["max_tokens"] = max_tokens
    llm = init_chat_model(model_name, **config)
    return llm.with_config({"callbacks": [callback]})
