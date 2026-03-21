"""资料库相关 Schema."""

from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeCreateRequest(BaseModel):
    """新建资料库请求体。"""

    name: str = Field(..., min_length=1, max_length=255, description="资料库名称")
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="描述",
    )
    thumbnail_key: str | None = Field(
        default=None,
        max_length=1024,
        description="缩略图存储键或相对路径，可选",
    )


class KnowledgePublicResponse(BaseModel):
    """资料库对外字段。"""

    id: int
    owner_user_id: int
    name: str
    description: str | None
    thumbnail_key: str | None
    status: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KbFileUploadResponse(BaseModel):
    """资料库文件上传结果（仅落盘，解析另接接口）。"""

    id: int
    knowledge_base_id: int
    original_name: str
    storage_key: str
    mime_type: str | None
    size_bytes: int
    parse_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
