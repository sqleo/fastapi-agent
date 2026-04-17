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

    # ---------- Milvus（向量库；LlamaIndex MilvusVectorStore）----------
    # 本机直连默认 localhost；Docker / K8s 中应设为服务名，如 http://milvus:19530（与 docker-compose 中 MILVUS_URI 一致）
    milvus_uri: str = Field(
        default="http://localhost:19530",
        validation_alias=AliasChoices("MILVUS_URI"),
        description="Milvus gRPC 代理地址，如 http://host:19530",
    )

    # ---------- Redis（入库队列等）----------
    redis_uri: str = Field(
        default="",
        validation_alias=AliasChoices("REDIS_URI"),
        description="Redis 连接串，如 redis://localhost:6379/0；索引入队依赖",
    )

    # ---------- LlamaIndex（docstore / index_store；与 LangGraph 隔离）----------
    llamaindex_postgres_uri: str = Field(
        default="",
        validation_alias=AliasChoices("LLAMAINDEX_POSTGRES_URI"),
        description=(
            "仅用于 LlamaIndex PostgresDocumentStore / PostgresIndexStore；"
            "勿与 LangGraph checkpoint / LangMem 共用同一库（应另建库或使用独立 schema）"
        ),
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