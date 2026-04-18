"""metadata 抽取配置 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from models.MetadataFieldModel import MetadataExtractMode, MetadataMatchMode, MetadataValueType


class MetadataFieldAliasCreateRequest(BaseModel):
    """创建字段别名请求。"""

    alias_text: str = Field(..., min_length=1, max_length=128, description="字段别名文本")
    match_mode: MetadataMatchMode = Field(default=MetadataMatchMode.EXACT, description="匹配模式")
    status: int = Field(default=1, description="状态：1启用，0禁用")
    priority: int = Field(default=100, description="优先级，数值越小优先")


class MetadataFieldAliasUpdateRequest(BaseModel):
    """更新字段别名请求。"""

    alias_text: str | None = Field(default=None, min_length=1, max_length=128, description="字段别名文本")
    match_mode: MetadataMatchMode | None = Field(default=None, description="匹配模式")
    status: int | None = Field(default=None, description="状态：1启用，0禁用")
    priority: int | None = Field(default=None, description="优先级，数值越小优先")


class MetadataFieldCreateRequest(BaseModel):
    """创建 metadata 字段请求。"""

    biz_code: str | None = Field(default=None, max_length=64, description="业务线编码；为空表示全业务共享")
    knowledge_base_id: int | None = Field(default=None, description="知识库 id；为空表示非知识库级配置")
    field_key: str = Field(..., min_length=1, max_length=64, description="标准字段键，建议 snake_case")
    field_name: str = Field(..., min_length=1, max_length=128, description="字段展示名称")
    value_type: MetadataValueType = Field(default=MetadataValueType.TEXT, description="字段值类型")
    extract_mode: MetadataExtractMode = Field(default=MetadataExtractMode.FIELD, description="抽取模式")
    status: int = Field(default=1, description="状态：1启用，0禁用")
    priority: int = Field(default=100, description="优先级，数值越小优先")
    aliases: list[MetadataFieldAliasCreateRequest] = Field(default_factory=list, description="初始化别名列表")


class MetadataFieldUpdateRequest(BaseModel):
    """更新 metadata 字段请求。"""

    biz_code: str | None = Field(default=None, max_length=64, description="业务线编码；为空表示全业务共享")
    knowledge_base_id: int | None = Field(default=None, description="知识库 id；为空表示非知识库级配置")
    field_key: str | None = Field(default=None, min_length=1, max_length=64, description="标准字段键")
    field_name: str | None = Field(default=None, min_length=1, max_length=128, description="字段展示名称")
    value_type: MetadataValueType | None = Field(default=None, description="字段值类型")
    extract_mode: MetadataExtractMode | None = Field(default=None, description="抽取模式")
    status: int | None = Field(default=None, description="状态：1启用，0禁用")
    priority: int | None = Field(default=None, description="优先级，数值越小优先")


class MetadataFieldAliasItem(BaseModel):
    """字段别名项。"""

    id: int = Field(..., description="别名 id")
    field_id: int = Field(..., description="所属字段 id")
    alias_text: str = Field(..., description="字段别名文本")
    match_mode: str = Field(..., description="匹配模式：exact/contains/regex")
    status: int = Field(..., description="状态：1启用，0禁用")
    priority: int = Field(..., description="优先级")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class MetadataFieldItem(BaseModel):
    """metadata 字段配置项。"""

    id: int = Field(..., description="字段 id")
    owner_user_id: int = Field(..., description="归属用户 id")
    biz_code: str | None = Field(default=None, description="业务线编码")
    knowledge_base_id: int | None = Field(default=None, description="知识库 id")
    field_key: str = Field(..., description="标准字段键")
    field_name: str = Field(..., description="字段展示名称")
    value_type: str = Field(..., description="字段值类型：text/number/list/date")
    extract_mode: str = Field(..., description="抽取模式：field/section")
    status: int = Field(..., description="状态：1启用，0禁用")
    priority: int = Field(..., description="优先级")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    aliases: list[MetadataFieldAliasItem] = Field(default_factory=list, description="字段别名列表")


class MetadataFieldListResponse(BaseModel):
    """metadata 字段列表响应。"""

    total: int = Field(..., description="总条数")
    items: list[MetadataFieldItem] = Field(default_factory=list, description="字段配置列表")
