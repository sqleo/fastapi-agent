from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

class ConfigSettings(BaseSettings):
    llm_deepseek_api_key: str = Field(..., env="LLM_DEEPSEEK_API_KEY", description="API密钥")
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

load_dotenv(".env") 

env_config = ConfigSettings()