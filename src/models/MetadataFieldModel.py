"""动态 metadata 抽取配置：标准字段与字段别名。"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from models.BasicModel import BasicModel


class MetadataValueType(str, Enum):
    """metadata 字段值类型。"""

    TEXT = "text"
    NUMBER = "number"
    LIST = "list"
    DATE = "date"


class MetadataExtractMode(str, Enum):
    """抽取模式。"""

    FIELD = "field"
    SECTION = "section"


class MetadataMatchMode(str, Enum):
    """别名匹配方式。"""

    EXACT = "exact"
    CONTAINS = "contains"
    REGEX = "regex"


class MetadataFieldModel(BasicModel, table=True):
    """标准 metadata 字段定义。"""

    __tablename__ = "metadata_field"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "biz_code",
            "knowledge_base_id",
            "field_key",
            name="uq_metadata_field_scope_key",
        ),
        Index(
            "idx_metadata_field_scope_status",
            "owner_user_id",
            "biz_code",
            "knowledge_base_id",
            "status",
            "priority",
        ),
    )

    owner_user_id: int = Field(
        foreign_key="user.id",
        nullable=False,
        index=True,
        description="归属用户 id（租户隔离）",
        sa_column_kwargs={"comment": "归属用户 id（租户隔离）"},
    )
    biz_code: str | None = Field(
        default=None,
        max_length=64,
        index=True,
        description="业务线编码；为空表示全业务共享",
        sa_column_kwargs={"comment": "业务线编码；为空表示全业务共享"},
    )
    knowledge_base_id: int | None = Field(
        default=None,
        foreign_key="knowledge_base.id",
        index=True,
        description="作用域知识库 id；为空表示非知识库级配置",
        sa_column_kwargs={"comment": "作用域知识库 id；为空表示非知识库级配置"},
    )
    field_key: str = Field(
        max_length=64,
        index=True,
        description="标准字段键，如 shelf_life/storage",
        sa_column_kwargs={"comment": "标准字段键，如 shelf_life/storage"},
    )
    field_name: str = Field(
        max_length=128,
        description="字段展示名称，如 保质期",
        sa_column_kwargs={"comment": "字段展示名称，如 保质期"},
    )
    value_type: MetadataValueType = Field(
        default=MetadataValueType.TEXT,
        sa_column=Column(
            SAEnum(MetadataValueType, name="metadata_value_type", native_enum=False, length=16),
            nullable=False,
            comment="字段值类型",
        ),
        description="字段值类型",
    )
    extract_mode: MetadataExtractMode = Field(
        default=MetadataExtractMode.FIELD,
        sa_column=Column(
            SAEnum(MetadataExtractMode, name="metadata_extract_mode", native_enum=False, length=16),
            nullable=False,
            comment="抽取模式：field/section",
        ),
        description="抽取模式：field/section",
    )
    status: int = Field(
        default=1,
        index=True,
        description="状态：1启用，0禁用",
        sa_column_kwargs={"comment": "状态：1启用，0禁用"},
    )
    priority: int = Field(
        default=100,
        description="优先级（数值越小优先）",
        sa_column_kwargs={"comment": "优先级（数值越小优先）"},
    )


class MetadataFieldAliasModel(BasicModel, table=True):
    """metadata 字段别名与匹配规则。"""

    __tablename__ = "metadata_field_alias"
    __table_args__ = (
        UniqueConstraint(
            "field_id",
            "alias_text",
            name="uq_metadata_field_alias",
        ),
        Index("idx_metadata_alias_field_status", "field_id", "status", "priority"),
    )

    field_id: int = Field(
        foreign_key="metadata_field.id",
        nullable=False,
        index=True,
        description="关联标准字段 id",
        sa_column_kwargs={"comment": "关联标准字段 id"},
    )
    alias_text: str = Field(
        max_length=128,
        description="字段别名，如 保质期/有效期",
        sa_column_kwargs={"comment": "字段别名，如 保质期/有效期"},
    )
    match_mode: MetadataMatchMode = Field(
        default=MetadataMatchMode.EXACT,
        sa_column=Column(
            SAEnum(MetadataMatchMode, name="metadata_match_mode", native_enum=False, length=16),
            nullable=False,
            comment="匹配模式：exact/contains/regex",
        ),
        description="匹配模式：exact/contains/regex",
    )
    status: int = Field(
        default=1,
        index=True,
        description="状态：1启用，0禁用",
        sa_column_kwargs={"comment": "状态：1启用，0禁用"},
    )
    priority: int = Field(
        default=100,
        description="优先级（数值越小优先）",
        sa_column_kwargs={"comment": "优先级（数值越小优先）"},
    )
