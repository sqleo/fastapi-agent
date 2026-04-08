"""用户全局模型设置 Schema。"""

from pydantic import BaseModel, Field


class LlmGlobalSettingUpdateRequest(BaseModel):
    """更新全局模型设置请求。"""

    chat_vendor_id: int | None = Field(default=None, description="聊天模型厂商 id")
    chat_model: str | None = Field(default=None, max_length=255, description="聊天模型名称")

    embedding_vendor_id: int | None = Field(default=None, description="嵌入模型厂商 id")
    embedding_model: str | None = Field(default=None, max_length=255, description="嵌入模型名称")

    multimodal_vendor_id: int | None = Field(default=None, description="多模态模型厂商 id")
    multimodal_model: str | None = Field(default=None, max_length=255, description="多模态模型名称")

    rerank_vendor_id: int | None = Field(default=None, description="Rerank 模型厂商 id")
    rerank_model: str | None = Field(default=None, max_length=255, description="Rerank 模型名称")

    asr_vendor_id: int | None = Field(default=None, description="ASR 模型厂商 id")
    asr_model: str | None = Field(default=None, max_length=255, description="ASR 模型名称")

    tts_vendor_id: int | None = Field(default=None, description="TTS 模型厂商 id")
    tts_model: str | None = Field(default=None, max_length=255, description="TTS 模型名称")


class LlmGlobalSettingCompletion(BaseModel):
    """全局设置完成度分项。"""

    chat: bool = Field(..., description="LLM 是否已配置")
    embedding: bool = Field(..., description="Embedding 是否已配置")
    multimodal: bool = Field(..., description="VLM/多模态是否已配置")
    rerank: bool = Field(..., description="Rerank 是否已配置")
    asr: bool = Field(..., description="ASR 是否已配置")
    tts: bool = Field(..., description="TTS 是否已配置")


class LlmGlobalSettingItem(BaseModel):
    """用户全局模型设置响应。"""

    owner_user_id: int = Field(..., description="归属用户 id")
    chat_vendor_id: int | None = Field(default=None, description="聊天模型厂商 id")
    chat_model: str | None = Field(default=None, description="聊天模型名称")
    embedding_vendor_id: int | None = Field(default=None, description="嵌入模型厂商 id")
    embedding_model: str | None = Field(default=None, description="嵌入模型名称")
    multimodal_vendor_id: int | None = Field(default=None, description="多模态模型厂商 id")
    multimodal_model: str | None = Field(default=None, description="多模态模型名称")
    rerank_vendor_id: int | None = Field(default=None, description="Rerank 模型厂商 id")
    rerank_model: str | None = Field(default=None, description="Rerank 模型名称")
    asr_vendor_id: int | None = Field(default=None, description="ASR 模型厂商 id")
    asr_model: str | None = Field(default=None, description="ASR 模型名称")
    tts_vendor_id: int | None = Field(default=None, description="TTS 模型厂商 id")
    tts_model: str | None = Field(default=None, description="TTS 模型名称")
    completion: LlmGlobalSettingCompletion = Field(..., description="分项完成度")
    is_complete: bool = Field(..., description="核心项是否完成（chat + embedding）")


class AvailableModelItem(BaseModel):
    """已安装且已配置厂商下的可选模型（用于全局默认模型下拉）。"""

    vendor_id: int = Field(..., description="厂商记录 id")
    vendor_code: str = Field(..., description="厂商代码")
    vendor_name: str = Field(..., description="厂商展示名")
    model_id: str = Field(..., description="模型 id（与厂商约定）")
    label: str = Field(..., description="下拉展示文案")
    capability: str = Field(..., description="能力标签：LLM/Embedding/Rerank/VLM/ASR/TTS/Moderation")
    value: str = Field(
        ...,
        description="下拉 value，格式为 ``vendor_id|model_id``，写入全局设置时拆回 vendor_id 与 model 名",
    )

