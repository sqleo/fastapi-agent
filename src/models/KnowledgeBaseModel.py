"""知识库与文件关联模型."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from models.BasicModel import BasicModel


class KbFilePipelineStatus(str, Enum):
    """知识库-文件 索引入库流水线状态（与 Redis 简单队列、LlamaIndex 管线对齐）."""

    PENDING_MD = "pending_md"  # 等待解析产出中间 .md（parsed_md_storage_key 未就绪）
    READY_TO_INDEX = "ready_to_index"  # 中间 .md 已就绪，可入队索引入库
    QUEUED = "queued"  # 已写入 Redis 队列，等待 worker 消费
    INDEXING = "indexing"  # worker 正在分块/嵌入/写 Milvus
    INDEXED = "indexed"  # 该文件在该知识库下已向量化完成
    FAILED = "failed"  # 失败，见 pipeline_error


class KnowledgeBaseModel(BasicModel, table=True):
    """知识库主表."""

    __tablename__ = "knowledge_base"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_kb_owner_name"),
    )

    owner_user_id: int = Field(
        foreign_key="user.id",
        nullable=False,
        index=True,
        description="归属用户 id",
        sa_column_kwargs={"comment": "归属用户 id"},
    )
    name: str = Field(max_length=128, description="知识库名称")
    code: str | None = Field(default=None, max_length=64, index=True, description="知识库编码（可选）")
    description: str | None = Field(default=None, max_length=500, description="知识库说明")
    thumbnail_url: str | None = Field(default=None, max_length=255, description="知识库缩略图 URL")
    status: int = Field(default=1, description="状态：1 启用，0 禁用")


class KnowledgeBaseFileModel(BasicModel, table=True):
    """知识库与文件多对多关联表；索引进度按 (file, knowledge_base) 记录."""

    __tablename__ = "knowledge_base_file"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "file_id", name="uq_kb_file"),
        Index("idx_kb_file_owner_kb", "owner_user_id", "knowledge_base_id"),
        Index("idx_kb_file_pipeline", "owner_user_id", "pipeline_status"),
    )

    owner_user_id: int = Field(
        foreign_key="user.id",
        nullable=False,
        index=True,
        description="归属用户 id",
        sa_column_kwargs={"comment": "归属用户 id"},
    )
    knowledge_base_id: int = Field(
        foreign_key="knowledge_base.id",
        nullable=False,
        index=True,
        description="知识库 id",
    )
    file_id: int = Field(
        foreign_key="file_asset.id",
        nullable=False,
        index=True,
        description="文件 id",
    )
    pipeline_status: KbFilePipelineStatus = Field(
        default=KbFilePipelineStatus.PENDING_MD,
        sa_column=Column(
            SAEnum(
                KbFilePipelineStatus,
                name="kb_file_pipeline_status",
                native_enum=False,
                length=32,
            )
        ),
        description="索引入库流水线状态：pending_md/ready_to_index/queued/indexing/indexed/failed",
    )
    pipeline_error: str | None = Field(
        default=None,
        max_length=2000,
        description="流水线失败原因（截断存储）",
    )
    indexed_at: datetime | None = Field(default=None, description="在该知识库下最近一次成功写入向量库的时间")
    indexed_semver_major: int | None = Field(
        default=None,
        ge=0,
        description="入库时快照的文件 content semver MAJOR（与 file_asset 对齐）",
    )
    indexed_semver_minor: int | None = Field(
        default=None,
        ge=0,
        description="入库时快照的文件 content semver MINOR",
    )
    indexed_semver_patch: int | None = Field(
        default=None,
        ge=0,
        description="入库时快照的文件 content semver PATCH",
    )
    chunk_count: int | None = Field(default=None, ge=0, description="最近一次成功索引的 chunk 数量（可选）")
