from typing import Optional

from sqlmodel import Field

from models.BasicModel import BasicModel

# embedding_status 取值：active / migrating / deprecated
EMBEDDING_STATUS_ACTIVE = "active"
EMBEDDING_STATUS_MIGRATING = "migrating"
EMBEDDING_STATUS_DEPRECATED = "deprecated"


class LlmGlobalSettingModel(BasicModel, table=True):
    """用户全局模型设置（每个用户仅一条）。"""

    __tablename__ = "llm_global_setting"

    owner_user_id: int = Field(
        foreign_key="user.id",
        nullable=False,
        unique=True,
        index=True,
        description="归属用户 id；每个用户仅一条全局设置",
        sa_column_kwargs={"comment": "归属用户 id；每个用户仅一条"},
    )

    chat_vendor_id: int | None = Field(default=None, foreign_key="llm_vendor.id", description="聊天模型厂商 id")
    chat_model: str | None = Field(default=None, max_length=255, description="聊天模型名称")

    embedding_vendor_id: int | None = Field(
        default=None, foreign_key="llm_vendor.id", description="嵌入模型厂商 id"
    )
    embedding_model: str | None = Field(default=None, max_length=255, description="嵌入模型名称")
    embedding_dim: int | None = Field(
        default=None,
        description="当前嵌入维度（pgvector 列宽）。改任一 embedding_* 字段都需要重建索引",
    )
    embedding_version: int = Field(
        default=1,
        description="嵌入配置版本号；改 vendor/model/dim 任一字段 → +1，并触发 reindex",
    )
    embedding_status: str = Field(
        default=EMBEDDING_STATUS_ACTIVE,
        max_length=16,
        description="嵌入索引状态：active=单写新版；migrating=双写新旧；deprecated=用户未配置或已废弃",
    )

    multimodal_vendor_id: int | None = Field(
        default=None, foreign_key="llm_vendor.id", description="多模态模型厂商 id"
    )
    multimodal_model: str | None = Field(default=None, max_length=255, description="多模态模型名称")

    rerank_vendor_id: int | None = Field(default=None, foreign_key="llm_vendor.id", description="Rerank 模型厂商 id")
    rerank_model: str | None = Field(default=None, max_length=255, description="Rerank 模型名称")

    asr_vendor_id: int | None = Field(default=None, foreign_key="llm_vendor.id", description="ASR 模型厂商 id")
    asr_model: str | None = Field(default=None, max_length=255, description="ASR 模型名称")

    tts_vendor_id: int | None = Field(default=None, foreign_key="llm_vendor.id", description="TTS 模型厂商 id")
    tts_model: str | None = Field(default=None, max_length=255, description="TTS 模型名称")

