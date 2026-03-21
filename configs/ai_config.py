from configs.env import env_config

ai_config = {
    "deepseek": {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": env_config.llm_deepseek_api_key,
    },

}