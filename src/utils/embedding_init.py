from langchain_openai import OpenAIEmbeddings
from configs.ai_config import ai_config


def create_embeddings(platform_code: str, dimensions: int = 1024):
    """
    创建Embedding实例
    Args:
        platform_code: 平台代码
    Returns:
        Embedding实例
    """
    if platform_code not in ai_config:
        raise ValueError(f"Invalid platform code: {platform_code}")
    platform_config = ai_config[platform_code]
    return OpenAIEmbeddings(
        model=platform_config["model"],
        api_key=platform_config["api_key"],
        base_url=platform_config["base_url"],
        dimensions=dimensions,
    )