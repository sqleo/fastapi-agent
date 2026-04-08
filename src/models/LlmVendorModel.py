from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship

from models.BasicModel import BasicModel

if TYPE_CHECKING:
    from models.UserModel import UserModel


class LlmModelType(str, Enum):
    """模型类型枚举；后续需要时可继续扩展成员."""

    CHAT = "chat"
    MULTIMODAL = "multimodal"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    # 如需扩展，可继续添加：
    # SPEECH_TO_TEXT = "speech_to_text"
    # TEXT_TO_SPEECH = "text_to_speech"
    # IMAGE_GENERATION = "image_generation"


class LlmVendorModel(BasicModel, table=True):
    """LLM 厂商；多租户隔离：按 owner_user_id 归属."""

    __tablename__ = "llm_vendor"

    # 多租户归属：该厂商配置属于哪个用户/租户
    owner_user_id: int = Field(
        foreign_key="user.id",
        nullable=False,
        index=True,
        description="归属用户 id；用于多租户隔离",
        sa_column_kwargs={"comment": "归属用户 id；用于多租户隔离"},
    )
    owner_user: Optional["UserModel"] = Relationship(back_populates="llm_vendors")

    # 厂商基本信息
    name: str = Field(max_length=100, description="展示名称，如 OpenAI 正式")
    code: str = Field(
        max_length=50,
        index=True,
        description="厂商代码，如 openai、deepseek、aliyun；用于代码路由",
        sa_column_kwargs={"comment": "厂商代码，如 openai、deepseek、aliyun"},
    )
    description: Optional[str] = Field(default=None, description="说明/备注")

    website_url: Optional[str] = Field(default=None, max_length=255, description="官网地址")
    doc_url: Optional[str] = Field(default=None, max_length=255, description="文档地址")
    logo_url: Optional[str] = Field(default=None, max_length=255, description="Logo 地址")

    # 厂商级鉴权 & 基础调用信息
    base_url: Optional[str] = Field(
        default=None,
        max_length=255,
        description="该厂商默认 API Base URL，如 https://api.openai.com/v1",
        sa_column_kwargs={"comment": "厂商默认 API Base URL"},
    )
    api_key: Optional[str] = Field(
        default=None,
        max_length=512,
        description="该厂商通用 API Key（同一厂商下配置默认共用）",
        sa_column_kwargs={"comment": "厂商通用 API Key"},
    )
    api_secret: Optional[str] = Field(
        default=None,
        max_length=512,
        description="部分厂商需要的额外 secret/token",
    )
    organization: Optional[str] = Field(
        default=None,
        max_length=255,
        description="可选组织/tenant 信息，如 OpenAI 的 organization",
    )

    # 可选默认模型类型，方便前端展示（存枚举值字符串）
    default_model_type: Optional[str] = Field(
        default=None,
        max_length=50,
        description="默认模型类型字符串，对应 LlmModelType 的 value（如 chat/embedding）",
        sa_column_kwargs={"comment": "默认模型类型（如 chat/embedding）"},
    )

    status: int = Field(default=1, description="状态：1 启用，0 禁用")

    # 厂商私有扩展参数（按模板动态字段保存）
    extra_config: dict | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="厂商私有配置，如 endpoint_id/secret_id/max_tokens 等",
    )


