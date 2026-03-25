from langchain_openai import ChatOpenAI
from configs.ai_config import ai_config

def create_llm(platform_code: str, temperature: float = 0.0, max_tokens: int = 1000):
    """
    创建LLM实例
    Args:
        platform_code: 平台代码
        temperature: 温度
        max_tokens: 最大tokens
    Returns:
        LLM实例
    """
    if platform_code not in ai_config:
        raise ValueError(f"Invalid platform code: {platform_code}")
    platform_config = ai_config[platform_code]
    key = (platform_config["api_key"] or "").strip()
    return ChatOpenAI(
        model=platform_config["model"],
        api_key=key if key else None,
        base_url=platform_config["base_url"],
        temperature=temperature,
        max_tokens=max_tokens,
    )