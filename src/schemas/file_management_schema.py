"""文件管理相关 Schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FolderCreateRequest(BaseModel):
    """创建文件夹请求体."""

    name: str = Field(..., min_length=1, max_length=255, description="文件夹名称")
    parent_folder_id: int | None = Field(default=None, description="父文件夹 id；为空表示根目录")
    project_code: str | None = Field(default=None, max_length=64, description="项目标识（可选）")
    description: str | None = Field(default=None, max_length=500, description="文件夹说明")


class FolderItem(BaseModel):
    """文件夹基础信息."""

    id: int = Field(..., description="文件夹 id")
    name: str = Field(..., description="文件夹名称")
    parent_folder_id: int | None = Field(default=None, description="父文件夹 id")
    project_code: str | None = Field(default=None, description="项目标识")
    description: str | None = Field(default=None, description="说明")
    created_at: datetime = Field(..., description="创建时间")


class FolderTreeNode(BaseModel):
    """文件夹树节点."""

    id: int = Field(..., description="文件夹 id")
    name: str = Field(..., description="文件夹名称")
    parent_folder_id: int | None = Field(default=None, description="父文件夹 id")
    project_code: str | None = Field(default=None, description="项目标识")
    children: list[FolderTreeNode] = Field(default_factory=list, description="子文件夹")


class FileUploadItem(BaseModel):
    """上传文件返回数据."""

    id: int = Field(..., description="文件记录 id")
    uploader_user_id: int = Field(..., description="上传人用户 id")
    uploader_name: str | None = Field(default=None, description="上传人用户名（与 create_by 一致）")
    folder_id: int | None = Field(default=None, description="所属文件夹 id")
    file_name: str = Field(..., description="文件名")
    file_ext: str | None = Field(default=None, description="文件后缀")
    mime_type: str | None = Field(default=None, description="MIME 类型")
    size_bytes: int = Field(..., description="文件大小（字节）")
    project_code: str | None = Field(default=None, description="项目标识")
    source: str = Field(..., description="文件来源")
    status: str = Field(..., description="业务状态")
    content_semver: str = Field(..., description="内容语义版本 MAJOR.MINOR.PATCH")
    parse_status: str = Field(..., description="pending=未解析出 md；parsed=已有中间 Markdown")
    storage_key: str = Field(..., description="对象存储键")
    file_url: str = Field(..., description="可访问 URL（静态资源）")
    created_at: datetime = Field(..., description="创建时间")


class FileListResponse(BaseModel):
    """文件列表分页响应."""

    total: int = Field(..., description="总条数")
    page: int = Field(..., description="当前页，从 1 开始")
    page_size: int = Field(..., description="每页条数")
    items: list[FileUploadItem] = Field(default_factory=list, description="文件列表")


class FileParseIntermediateMdResponse(BaseModel):
    """解析为中间 Markdown 后的结果."""

    file_id: int = Field(..., description="文件记录 id")
    content_semver: str = Field(..., description="解析后的内容语义版本（PATCH 已递增）")
    parse_status: str = Field(default="parsed", description="解析后恒为 parsed")
    parsed_md_storage_key: str = Field(..., description="相对 static/ 的中间 Markdown 路径")
    parsed_md_url: str = Field(..., description="中间 Markdown 静态访问 URL")

