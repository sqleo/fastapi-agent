"""统一应用配置：从项目根 ``.env`` 与环境变量加载，通过 ``env_config`` 访问。"""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent

# 检查系统环境变量
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

    # ---------- MinerU ==========
    mineru_token: str = Field(
        default="",
        validation_alias=AliasChoices("MINERU_TOKEN"),
        description="MinerU 令牌；用于解析富文档",
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

    # ---------- 资料库文件（本地上传）----------
    kb_upload_rel_dir: str = Field(
        default="static/kb_uploads",
        validation_alias=AliasChoices("KB_UPLOAD_REL_DIR"),
        description="相对项目根目录的上传根路径，位于 static 下便于 /static 访问",
    )
    kb_upload_max_bytes: int = Field(
        default=104_857_600,
        validation_alias=AliasChoices("KB_UPLOAD_MAX_BYTES"),
        description="单文件最大字节数，默认 100MB",
    )


env_config = ConfigSettings()
print(f"环境变量{env_config}")