from langchain.chat_models import init_chat_model


REPORT_CONFIG = {
    "llm": {
        "model": "deepseek-chat",
        "model_provider": "deepseek",
        "api_key": "sk-76066a769b8f48ffa0376a9a1132de29",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.1,
        "timeout": 60,
    }
}

async def create_llm(code: str, max_tokens: int = 8000):
    config = REPORT_CONFIG[code].copy()
    model_name = config.pop("model")          
    config["max_tokens"] = max_tokens
    return init_chat_model(model_name,**config)