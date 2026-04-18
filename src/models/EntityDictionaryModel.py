"""实体词表：正式实体、别名、候选（人工审核）三表。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from models.BasicModel import BasicModel


class EntityType(str, Enum):
    """实体类型。"""

    OTHER = "other"
    PRODUCT = "product"
    BRAND = "brand"
    CATEGORY = "category"
    INGREDIENT = "ingredient"


class CandidateStatus(str, Enum):
    """候选审核状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"


class EntityDictionaryModel(BasicModel, table=True):
    """正式实体词表（已审核可用）。

    作用域层级：
    1) knowledge_base_id 非空：知识库级
    2) knowledge_base_id 为空且 biz_code 非空：业务级
    3) knowledge_base_id 与 biz_code 均为空：租户全局级
    """

    __tablename__ = "entity_dictionary"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "biz_code",
            "knowledge_base_id",
            "entity_type",
            "normalized_name",
            name="uq_entity_scope_type_name",
        ),
        Index(
            "idx_entity_scope_status",
            "owner_user_id",
            "biz_code",
            "knowledge_base_id",
            "entity_type",
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
        description="作用域知识库 id；为空表示租户全局词表",
        sa_column_kwargs={"comment": "作用域知识库 id；为空表示租户全局词表"},
    )
    entity_type: EntityType = Field(
        default=EntityType.OTHER,
        sa_column=Column(
            SAEnum(EntityType, name="entity_type", native_enum=False, length=32),
            nullable=False,
            comment="实体类型",
        ),
        description="实体类型",
    )
    canonical_name: str = Field(
        max_length=255,
        description="标准实体名",
        sa_column_kwargs={"comment": "标准实体名"},
    )
    normalized_name: str = Field(
        max_length=255,
        index=True,
        description="归一化实体名",
        sa_column_kwargs={"comment": "归一化实体名"},
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
    source: str = Field(
        default="manual",
        max_length=32,
        description="来源：manual/candidate_approved",
        sa_column_kwargs={"comment": "来源：manual/candidate_approved"},
    )


class EntityAliasModel(BasicModel, table=True):
    """实体别名词表（用于检索前实体归一化）。"""

    __tablename__ = "entity_alias"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "biz_code",
            "knowledge_base_id",
            "alias_normalized",
            "entity_id",
            name="uq_alias_scope_alias_entity",
        ),
        Index(
            "idx_alias_scope_status",
            "owner_user_id",
            "biz_code",
            "knowledge_base_id",
            "alias_normalized",
            "status",
        ),
        Index("idx_alias_entity_status", "entity_id", "status"),
    )

    entity_id: int = Field(
        foreign_key="entity_dictionary.id",
        nullable=False,
        index=True,
        description="所属标准实体 id",
        sa_column_kwargs={"comment": "所属标准实体 id"},
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
        description="作用域知识库 id；为空表示租户全局词表",
        sa_column_kwargs={"comment": "作用域知识库 id；为空表示租户全局词表"},
    )
    alias: str = Field(
        max_length=255,
        description="别名原文",
        sa_column_kwargs={"comment": "别名原文"},
    )
    alias_normalized: str = Field(
        max_length=255,
        index=True,
        description="别名归一化文本",
        sa_column_kwargs={"comment": "别名归一化文本"},
    )
    match_mode: str = Field(
        default="contains",
        max_length=16,
        description="匹配模式：exact/contains",
        sa_column_kwargs={"comment": "匹配模式：exact/contains"},
    )
    weight: int = Field(
        default=100,
        description="匹配权重",
        sa_column_kwargs={"comment": "匹配权重"},
    )
    status: int = Field(
        default=1,
        index=True,
        description="状态：1启用，0禁用",
        sa_column_kwargs={"comment": "状态：1启用，0禁用"},
    )


class EntityCandidateModel(BasicModel, table=True):
    """实体候选池（待人工审核）。"""

    __tablename__ = "entity_candidate"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "biz_code",
            "knowledge_base_id",
            "candidate_normalized",
            "file_id",
            name="uq_candidate_scope_text_file",
        ),
        Index(
            "idx_candidate_scope_status",
            "owner_user_id",
            "biz_code",
            "knowledge_base_id",
            "status",
            "updated_at",
        ),
        Index("idx_candidate_approved_entity", "approved_entity_id"),
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
        description="作用域知识库 id；为空表示租户全局候选",
        sa_column_kwargs={"comment": "作用域知识库 id；为空表示租户全局候选"},
    )
    file_id: int | None = Field(
        default=None,
        foreign_key="file_asset.id",
        index=True,
        description="来源文件 id（可空）",
        sa_column_kwargs={"comment": "来源文件 id（可空）"},
    )
    entity_type: EntityType | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(EntityType, name="candidate_entity_type", native_enum=False, length=32),
            nullable=True,
            comment="候选实体类型（系统猜测，可空）",
        ),
        description="候选实体类型（系统猜测，可空）",
    )
    candidate_text: str = Field(
        max_length=255,
        description="候选实体文本",
        sa_column_kwargs={"comment": "候选实体文本"},
    )
    candidate_normalized: str = Field(
        max_length=255,
        index=True,
        description="候选实体归一化文本",
        sa_column_kwargs={"comment": "候选实体归一化文本"},
    )
    evidence: dict | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="来源证据（片段、位置、命中规则）",
    )
    frequency: int = Field(
        default=1,
        ge=1,
        description="出现频次",
        sa_column_kwargs={"comment": "出现频次"},
    )
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="置信度（0~1）",
        sa_column_kwargs={"comment": "置信度（0~1）"},
    )
    status: CandidateStatus = Field(
        default=CandidateStatus.PENDING,
        sa_column=Column(
            SAEnum(CandidateStatus, name="candidate_status", native_enum=False, length=16),
            nullable=False,
            comment="审核状态：pending/approved/rejected/merged",
        ),
        description="审核状态：pending/approved/rejected/merged",
    )
    reviewer_user_id: int | None = Field(
        default=None,
        foreign_key="user.id",
        index=True,
        description="审核人 id",
        sa_column_kwargs={"comment": "审核人 id"},
    )
    reviewed_at: datetime | None = Field(
        default=None,
        description="审核时间",
        sa_column_kwargs={"comment": "审核时间"},
    )
    review_comment: str | None = Field(
        default=None,
        max_length=500,
        description="审核备注",
        sa_column_kwargs={"comment": "审核备注"},
    )
    approved_entity_id: int | None = Field(
        default=None,
        foreign_key="entity_dictionary.id",
        index=True,
        description="审核通过/合并后的正式实体 id",
        sa_column_kwargs={"comment": "审核通过/合并后的正式实体 id"},
    )
