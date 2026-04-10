"""文件管理阶段一模型：文件夹与文件元数据."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from models.BasicModel import BasicModel

# 解析中间 Markdown 固定落在磁盘 ``static/parsed_md/`` 下；库中存相对 ``static/`` 的路径，且应以此前缀开头。
# 例：``parsed_md/12/34.md`` → 实际文件 ``static/parsed_md/12/34.md``，URL ``/static/parsed_md/12/34.md``。
PARSED_MD_STORAGE_PREFIX = "parsed_md"


class FileLifecycleStatus(str, Enum):
    """文件业务状态."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    ARCHIVED = "archived"


class FileSourceType(str, Enum):
    """文件来源类型（用于追踪文件采集来源和后续处理策略）."""

    MANUAL_UPLOAD = "manual_upload"  # 用户在页面手动上传
    FIGMA_EXPORT = "figma_export"  # 由 Figma 导出或同步进入
    SYNC_DISK = "sync_disk"  # 从本地/网盘目录同步
    API_IMPORT = "api_import"  # 外部系统通过 API 推送导入


class FileParseStatus(str, Enum):
    """是否已产出中间 Markdown（解析产物）."""

    PENDING = "pending"  # 尚未解析或重新上传后待重新解析
    PARSED = "parsed"  # 已生成 parsed_md


class FileFolderModel(BasicModel, table=True):
    """文件夹模型，支持多级目录结构."""

    __tablename__ = "file_folder"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "parent_folder_id", "name", name="uq_folder_name_same_level"),
    )

    owner_user_id: int = Field(
        foreign_key="user.id",
        nullable=False,
        index=True,
        description="归属用户 id；用于多租户隔离",
        sa_column_kwargs={"comment": "归属用户 id；用于多租户隔离"},
    )
    project_code: str | None = Field(
        default=None,
        max_length=64,
        index=True,
        description="项目标识（可选）",
    )
    parent_folder_id: int | None = Field(
        default=None,
        foreign_key="file_folder.id",
        index=True,
        description="父级文件夹 id；为空表示根目录",
    )
    name: str = Field(max_length=255, description="文件夹名称")
    description: str | None = Field(default=None, max_length=500, description="文件夹说明")


class FileAssetModel(BasicModel, table=True):
    """文件元数据模型；索引进度按知识库维度放在关联表或任务侧，不在此表存单一 kb 状态."""

    __tablename__ = "file_asset"
    __table_args__ = (
        Index("idx_file_owner_status", "owner_user_id", "status"),
        Index("idx_file_parse_status", "owner_user_id", "parse_status"),
    )

    owner_user_id: int = Field(
        foreign_key="user.id",
        nullable=False,
        index=True,
        description="归属用户 id；用于多租户隔离",
        sa_column_kwargs={"comment": "归属用户 id；用于多租户隔离"},
    )
    uploader_user_id: int = Field(
        foreign_key="user.id",
        nullable=False,
        index=True,
        description="上传人用户 id",
        sa_column_kwargs={"comment": "上传人用户 id"},
    )
    folder_id: int | None = Field(
        default=None,
        foreign_key="file_folder.id",
        index=True,
        description="所属文件夹 id；为空表示根目录",
    )
    project_code: str | None = Field(default=None, max_length=64, index=True, description="项目标识（可选）")

    file_name: str = Field(max_length=255, description="文件名（含后缀）")
    display_name: str | None = Field(default=None, max_length=255, description="展示名称")
    file_ext: str | None = Field(default=None, max_length=20, description="文件后缀")
    mime_type: str | None = Field(default=None, max_length=128, description="MIME 类型")
    size_bytes: int = Field(default=0, ge=0, description="文件大小（字节）")
    storage_key: str = Field(max_length=500, unique=True, description="对象存储键（S3/OSS Key）")
    parsed_md_storage_key: str | None = Field(
        default=None,
        max_length=500,
        index=True,
        description=(
            "解析后的中间 Markdown 相对路径（相对 static/），固定落在 static/parsed_md/ 下，"
            "例如 parsed_md/{owner_user_id}/{file_id}.md；供 RAG 加载；未解析前为空"
        ),
        sa_column_kwargs={"comment": "相对 static/，位于 static/parsed_md/ 下"},
    )
    file_hash: str | None = Field(default=None, max_length=128, index=True, description="文件内容哈希（去重）")
    semver_major: int = Field(default=0, ge=0, description="内容语义版本 MAJOR（重新上传 +1）")
    semver_minor: int = Field(default=0, ge=0, description="内容语义版本 MINOR")
    semver_patch: int = Field(default=0, ge=0, description="内容语义版本 PATCH（每次解析 +1，规则见 content_semver）")
    parse_status: FileParseStatus = Field(
        default=FileParseStatus.PENDING,
        sa_column=Column(
            SAEnum(
                FileParseStatus,
                name="file_parse_status",
                native_enum=False,
                length=32,
            )
        ),
        description="pending=未解析出 md；parsed=已有中间 Markdown",
    )
    source: FileSourceType = Field(
        default=FileSourceType.MANUAL_UPLOAD,
        sa_column=Column(
            SAEnum(
                FileSourceType,
                name="file_source_type",
                native_enum=False,
                length=32,
            )
        ),
        description="文件来源",
    )

    status: FileLifecycleStatus = Field(
        default=FileLifecycleStatus.DRAFT,
        sa_column=Column(
            SAEnum(
                FileLifecycleStatus,
                name="file_lifecycle_status",
                native_enum=False,
                length=32,
            )
        ),
        description="业务状态：draft/reviewed/approved/archived",
    )
    last_indexed_at: datetime | None = Field(
        default=None,
        description="文件级最近索引时间（可选）；按知识库维度的索引进度见 knowledge_base_file",
    )
    is_deleted: bool = Field(default=False, index=True, description="软删除标记")
    extra_metadata: dict | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="扩展元数据（如解析结果、自定义标签）",
    )
