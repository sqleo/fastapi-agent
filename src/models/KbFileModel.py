from datetime import datetime
from typing import Any, ClassVar, Optional

from sqlalchemy import Column, Index, JSON, Text
from sqlmodel import Field

from models.BasicModel import BasicModel


class KbFileModel(BasicModel, table=True):
    """资料库下的文件；访问权限通过所属 knowledge_base.owner_user_id 判定。"""

    __tablename__ = "kb_file"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        Index("ix_kb_file_kb_parse", "knowledge_base_id", "parse_status"),
    )

    knowledge_base_id: int = Field(
        foreign_key="knowledge_base.id",
        index=True,
        description="所属资料库",
    )
    original_name: str = Field(max_length=512, description="原始文件名")
    storage_key: str = Field(
        max_length=1024,
        description="存储路径或对象键",
        index=True,
    )
    mime_type: Optional[str] = Field(default=None, max_length=128, description="MIME")
    size_bytes: Optional[int] = Field(default=None, description="文件大小（字节）")
    content_hash: Optional[str] = Field(
        default=None,
        max_length=64,
        index=True,
        description="内容哈希，用于去重或变更检测",
    )
    parse_status: str = Field(
        max_length=32,
        default="pending",
        description="pending / parsing / parsed / failed",
        index=True,
    )
    parse_error: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="解析失败原因",
    )
    parsed_at: Optional[datetime] = Field(default=None, description="解析完成时间")
    extra_meta: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="扩展元数据（页数等）",
    )
