"""各平台 LLM：``model`` / ``base_url`` 在此维护；``api_key`` 来自 ``env_config``。

嵌入模型已迁至数据库 ``llm_global_setting`` + ``llm_vendor``，不再在此配置。
"""

from configs.env import env_config

ai_config = {
    "deepseek": {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": env_config.llm_deepseek_api_key,
    },
}
