"""文件管理路由：上传文件、新建文件夹、文件夹树."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from models.FileManagementModel import FileLifecycleStatus, FileSourceType
from schemas.file_management_schema import (
    FileListResponse,
    FileParseIntermediateMdResponse,
    FileUploadItem,
    FolderCreateRequest,
    FolderItem,
    FolderTreeNode,
)
from services.controllers.file_management_controller import (
    create_folder_owned,
    list_files_owned,
    list_folder_tree_owned,
    reupload_file_owned,
    soft_delete_file_owned,
    upload_file_owned,
)
from utils.content_semver import format_semver
from services.controllers.file_parse_controller import parse_file_to_intermediate_md_owned
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/files", tags=["File Management"])


def _to_folder_item(x) -> FolderItem:
    return FolderItem(
        id=x.id,
        name=x.name,
        parent_folder_id=x.parent_folder_id,
        project_code=x.project_code,
        description=x.description,
        created_at=x.created_at,
    )


def _build_tree(rows: list) -> list[FolderTreeNode]:
    nodes = {
        x.id: FolderTreeNode(
            id=x.id,
            name=x.name,
            parent_folder_id=x.parent_folder_id,
            project_code=x.project_code,
            children=[],
        )
        for x in rows
    }
    roots: list[FolderTreeNode] = []
    for x in rows:
        node = nodes[x.id]
        if x.parent_folder_id and x.parent_folder_id in nodes:
            nodes[x.parent_folder_id].children.append(node)
        else:
            roots.append(node)
    return roots


def _to_file_upload_item(x) -> FileUploadItem:
    return FileUploadItem(
        id=x.id,
        uploader_user_id=x.uploader_user_id,
        uploader_name=x.create_by,
        folder_id=x.folder_id,
        file_name=x.file_name,
        file_ext=x.file_ext,
        mime_type=x.mime_type,
        size_bytes=x.size_bytes,
        project_code=x.project_code,
        source=x.source.value if hasattr(x.source, "value") else str(x.source),
        status=x.status.value if hasattr(x.status, "value") else str(x.status),
        content_semver=format_semver(x.semver_major, x.semver_minor, x.semver_patch),
        parse_status=x.parse_status.value if hasattr(x.parse_status, "value") else str(x.parse_status),
        storage_key=x.storage_key,
        file_url=f"/static/{x.storage_key}",
        created_at=x.created_at,
    )


@router.post(
    "/folders",
    response_model=SuccessResponse[FolderItem],
    status_code=status.HTTP_201_CREATED,
    summary="新建文件夹",
)
async def create_folder(
    body: FolderCreateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[FolderItem]:
    """新建文件夹。"""
    row = await create_folder_owned(
        session,
        owner_user_id=current_user.id,
        name=body.name,
        parent_folder_id=body.parent_folder_id,
        project_code=body.project_code,
        description=body.description,
    )
    return ok(_to_folder_item(row), message="创建成功")


@router.get(
    "/folders/tree",
    response_model=SuccessResponse[list[FolderTreeNode]],
    summary="文件夹树",
)
async def get_folder_tree(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    project_code: str | None = Query(default=None, description="按项目标识过滤（可选）"),
) -> SuccessResponse[list[FolderTreeNode]]:
    """获取当前用户的文件夹树。"""
    rows = await list_folder_tree_owned(
        session,
        owner_user_id=current_user.id,
        project_code=project_code,
    )
    return ok(_build_tree(rows), message="查询成功")


@router.post(
    "/upload",
    response_model=SuccessResponse[FileUploadItem],
    status_code=status.HTTP_201_CREATED,
    summary="上传文件",
)
async def upload_file(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    file: UploadFile = File(..., description="上传文件"),
    folder_id: int | None = Form(default=None, description="所属文件夹 id（可选）"),
    project_code: str | None = Form(default=None, description="项目标识（可选）"),
    source: FileSourceType = Form(default=FileSourceType.MANUAL_UPLOAD, description="文件来源"),
) -> SuccessResponse[FileUploadItem]:
    """上传文件并创建文件记录。"""
    row, file_url = await upload_file_owned(
        session,
        owner_user_id=current_user.id,
        uploader_user_id=current_user.id,
        uploader_username=current_user.username,
        upload=file,
        folder_id=folder_id,
        project_code=project_code,
        source=source,
    )
    payload = _to_file_upload_item(row).model_copy(update={"file_url": file_url})
    return ok(payload, message="上传成功")


@router.put(
    "/{file_id}/reupload",
    response_model=SuccessResponse[FileUploadItem],
    summary="覆盖上传（同一文件记录）",
)
async def reupload_file(
    file_id: int,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    file: UploadFile = File(..., description="新文件内容"),
) -> SuccessResponse[FileUploadItem]:
    """覆盖同一 file_id 的存储内容：MAJOR 版本 +1，清空解析产物，已关联知识库条目回到 pending_md。"""
    row, file_url = await reupload_file_owned(
        session,
        owner_user_id=current_user.id,
        uploader_user_id=current_user.id,
        uploader_username=current_user.username,
        file_id=file_id,
        upload=file,
    )
    payload = _to_file_upload_item(row).model_copy(update={"file_url": file_url})
    return ok(payload, message="重新上传成功")


@router.get(
    "",
    response_model=SuccessResponse[FileListResponse],
    summary="文件列表（分页）",
)
async def list_files(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，最大 100"),
    status: FileLifecycleStatus | None = Query(default=None, description="业务状态过滤"),
    project_code: str | None = Query(default=None, description="项目标识过滤"),
) -> SuccessResponse[FileListResponse]:
    """分页查询文件列表，支持业务状态与项目维度筛选。"""
    total, rows = await list_files_owned(
        session,
        owner_user_id=current_user.id,
        page=page,
        page_size=page_size,
        status=status,
        project_code=project_code,
    )
    payload = FileListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_file_upload_item(x) for x in rows],
    )
    return ok(payload, message="查询成功")


@router.post(
    "/{file_id}/parse-md",
    response_model=SuccessResponse[FileParseIntermediateMdResponse],
    summary="解析为中间 Markdown（当前仅支持 .md）",
)
async def parse_file_to_intermediate_md(
    file_id: int,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[FileParseIntermediateMdResponse]:
    """对已上传文件生成 ``static/parsed_md/{owner}/{id}.md``；Markdown 源经 ``aiofiles`` 异步读写。

    其他格式后续通过扩展 ``IntermediateMdGenerator`` 接入；未实现的后缀返回 415。
    """
    row = await parse_file_to_intermediate_md_owned(
        session,
        owner_user_id=current_user.id,
        file_id=file_id,
    )
    key = (row.parsed_md_storage_key or "").strip()
    url = f"/static/{key}" if key else ""
    payload = FileParseIntermediateMdResponse(
        file_id=int(row.id),
        content_semver=format_semver(row.semver_major, row.semver_minor, row.semver_patch),
        parse_status=row.parse_status.value if hasattr(row.parse_status, "value") else str(row.parse_status),
        parsed_md_storage_key=key,
        parsed_md_url=url,
    )
    return ok(payload, message="解析成功")


@router.delete(
    "/{file_id}",
    response_model=SuccessResponse[None],
    summary="删除文件",
)
async def delete_file(
    file_id: int,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[None]:
    """软删除文件；已加入任意知识库时不允许删除。"""
    await soft_delete_file_owned(
        session,
        owner_user_id=current_user.id,
        file_id=file_id,
        operator_username=current_user.username,
    )
    return ok(None, message="删除成功")

