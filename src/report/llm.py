from langchain.chat_models import init_chat_model


REPORT_CONFIG = {
    "llm": {
        "model": "qwen-plus",
        "model_provider": "openai",
        "api_key": "sk-4fed42c6bb68432c84a4c7ce4a0292b5",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "max_tokens": 4096*5,
        "temperature": 0.1,
    }
}

async def create_llm(code: str):
    return init_chat_model(**REPORT_CONFIG[code])