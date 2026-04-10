"""统一应用配置：从项目根 ``.env`` 与环境变量加载，通过 ``env_config`` 访问。"""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent

class ConfigSettings(BaseSettings):
    """全局配置（LLM、JWT 等）。"""

    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- DeepSeek----------
    llm_deepseek_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_DEEPSEEK_API_KEY"),
        description="DeepSeek API 密钥",
    )
    # ---------- Qwen-embedding-v4----------
    llm_qwen_embedding_v4_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_QWEN_EMBEDDING_V4_API_KEY"),
        description="Qwen-embedding-v4 API 密钥",
    )

    # ---------- Redis（入库队列等）----------
    redis_uri: str = Field(
        default="",
        validation_alias=AliasChoices("REDIS_URI"),
        description="Redis 连接串，如 redis://localhost:6379/0；索引入队依赖",
    )

    # ---------- JWT（登录）----------
    jwt_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("JWT_SECRET_KEY"),
        description="JWT 签名密钥；登录接口必填",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices("JWT_ALGORITHM"),
        description="JWT 签名算法",
    )
    jwt_access_token_expire_minutes: int = Field(
        default=1440,
        validation_alias=AliasChoices("JWT_ACCESS_TOKEN_EXPIRE_MINUTES"),
        description="Access Token 有效时间（分钟）",
    )
    jwt_issuer: str | None = Field(
        default=None,
        validation_alias=AliasChoices("JWT_ISSUER"),
        description="JWT iss（可选）",
    )
    jwt_audience: str | None = Field(
        default=None,
        validation_alias=AliasChoices("JWT_AUDIENCE"),
        description="JWT aud（可选）",
    )
    jwt_leeway_seconds: int = Field(
        default=0,
        validation_alias=AliasChoices("JWT_LEEWAY_SECONDS"),
        description="校验 exp/nbf 时允许的时钟偏差（秒）",
    )


env_config = ConfigSettings()