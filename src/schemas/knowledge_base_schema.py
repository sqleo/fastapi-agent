"""知识库相关 Schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from schemas.file_management_schema import FileUploadItem


class KnowledgeBaseCreateRequest(BaseModel):
    """创建知识库请求体."""

    name: str = Field(..., min_length=1, max_length=128, description="知识库名称")
    code: str | None = Field(default=None, max_length=64, description="知识库编码（可选）")
    description: str | None = Field(default=None, max_length=500, description="知识库说明")
    thumbnail_url: str | None = Field(default=None, max_length=255, description="知识库缩略图 URL")


class KnowledgeBaseItem(BaseModel):
    """知识库信息."""

    id: int = Field(..., description="知识库 id")
    name: str = Field(..., description="知识库名称")
    code: str | None = Field(default=None, description="知识库编码")
    description: str | None = Field(default=None, description="知识库说明")
    thumbnail_url: str | None = Field(default=None, description="知识库缩略图 URL")
    status: int = Field(..., description="状态：1 启用，0 禁用")
    created_at: datetime = Field(..., description="创建时间")


class KnowledgeBaseFileOperateRequest(BaseModel):
    """知识库文件批量操作请求体."""

    file_ids: list[int] = Field(..., min_length=1, description="文件 id 列表")


class KnowledgeBaseFileOperateResult(BaseModel):
    """知识库文件批量操作结果."""

    knowledge_base_id: int = Field(..., description="知识库 id")
    affected_file_ids: list[int] = Field(default_factory=list, description="实际生效的文件 id")
    skipped_file_ids: list[int] = Field(default_factory=list, description="未生效文件 id")


class KnowledgeBaseFileListItem(FileUploadItem):
    """知识库内文件行：文件元数据 + 该库下的索引入库流水线状态."""

    kb_file_id: int = Field(..., description="knowledge_base_file 关联主键 id")
    pipeline_status: str = Field(
        ...,
        description="pending_md/ready_to_index/queued/indexing/indexed/failed",
    )
    pipeline_error: str | None = Field(default=None, description="失败原因")
    indexed_at: datetime | None = Field(default=None, description="在该库下最近一次索引成功时间")
    chunk_count: int | None = Field(default=None, description="最近一次成功写入的 chunk 数")
    parsed_md_storage_key: str | None = Field(
        default=None,
        description="解析后的中间 Markdown（相对 static/），位于 static/parsed_md/ 下，与 file_asset 一致",
    )
    indexed_content_semver: str | None = Field(
        default=None,
        description="该库内最近一次成功入库时快照的文件 content 版本；未成功入库过为 null",
    )
    has_newer_content: bool = Field(
        default=False,
        description="当前文件 content 版本是否新于已入库快照（可提示用户重新入库）",
    )


class KnowledgeBaseFileListResponse(BaseModel):
    """知识库文件分页列表."""

    knowledge_base_id: int = Field(..., description="知识库 id")
    total: int = Field(..., description="总条数")
    page: int = Field(..., description="当前页")
    page_size: int = Field(..., description="每页条数")
    items: list[KnowledgeBaseFileListItem] = Field(default_factory=list, description="文件列表")


class KnowledgeBaseSearchResponse(BaseModel):
    """知识库内向量检索结果（格式化文本）."""

    knowledge_base_id: int = Field(..., description="知识库 id")
    query: str = Field(..., description="检索 query")
    top_k: int = Field(..., description="请求条数")
    result_text: str = Field(..., description="格式化命中片段")
