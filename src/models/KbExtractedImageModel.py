"""资料库文件经 MinerU 等解析后抽出的图片元数据。"""

from typing import Any, ClassVar, Optional

from sqlalchemy import Column, Index, Text
from sqlmodel import Field

from models.BasicModel import BasicModel


class KbExtractedImageModel(BasicModel, table=True):
    """解析产物中的图片：存储路径相对项目根（POSIX），关联 ``kb_file``。"""

    __tablename__ = "kb_extracted_image" 
    __table_args__: ClassVar[tuple[Any, ...]] = (
        Index("ix_kb_extracted_image_kb_file", "kb_file_id"),
    )

    kb_file_id: int = Field(
        foreign_key="kb_file.id",
        index=True,
        description="所属资料库文件（文档）",
    )
    storage_key: str = Field(
        max_length=1024,
        description="相对项目根的存储路径，如 static/parsed_md/xxx_assets/images/a.jpg",
    )
    original_name: str = Field(max_length=512, description="解析结果中的原始文件名")
    mime_type: Optional[str] = Field(default=None, max_length=128, description="MIME")
    size_bytes: Optional[int] = Field(default=None, description="字节数")
    alt_text: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="写入 Markdown 的 alt 文案（含 doc_id 等）",
    )
