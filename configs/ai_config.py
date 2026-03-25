"""各平台 LLM：``model`` / ``base_url`` 在此维护；``api_key`` 来自 ``env_config``。"""

from configs.env import env_config

ai_config = {
    "deepseek": {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": env_config.llm_deepseek_api_key,
    },
    "Qwen-embedding-v4":{
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": env_config.llm_qwen_embedding_v4_api_key,
        "model": "text-embedding-v4",
    }
}
