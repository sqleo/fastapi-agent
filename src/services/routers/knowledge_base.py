"""知识库路由：新建知识库、文件加入/移出、知识库文件列表."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from schemas.file_management_schema import FileUploadItem
from schemas.knowledge_base_schema import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseFileIndexTriggerResponse,
    KnowledgeBaseFileListItem,
    KnowledgeBaseFileListResponse,
    KnowledgeBaseFileOperateRequest,
    KnowledgeBaseFileOperateResult,
    KnowledgeBaseItem,
    KnowledgeBaseSearchResponse,
)
from services.controllers.knowledge_base_controller import (
    add_files_to_knowledge_base_owned,
    create_knowledge_base_owned,
    enqueue_kb_file_indexing_owned,
    list_knowledge_base_files_owned,
    list_knowledge_bases_owned,
    remove_files_from_knowledge_base_owned,
    search_knowledge_base_owned,
)
from utils.auth_deps import CurrentUserDeps
from utils.content_semver import compare_semver, format_semver
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Base"])


def _to_kb_item(x) -> KnowledgeBaseItem:
    return KnowledgeBaseItem(
        id=x.id,
        name=x.name,
        code=x.code,
        description=x.description,
        thumbnail_url=x.thumbnail_url,
        status=x.status,
        created_at=x.created_at,
    )


def _to_file_item(x) -> FileUploadItem:
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


def _to_kb_file_list_item(f, kb) -> KnowledgeBaseFileListItem:
    base = _to_file_item(f)
    ps = kb.pipeline_status
    pipeline_status = ps.value if hasattr(ps, "value") else str(ps)
    indexed_content_semver = None
    if kb.indexed_semver_major is not None:
        indexed_content_semver = format_semver(
            int(kb.indexed_semver_major),
            int(kb.indexed_semver_minor or 0),
            int(kb.indexed_semver_patch or 0),
        )
    has_newer = False
    if kb.indexed_semver_major is not None:
        cur = (int(f.semver_major), int(f.semver_minor), int(f.semver_patch))
        idx = (
            int(kb.indexed_semver_major),
            int(kb.indexed_semver_minor or 0),
            int(kb.indexed_semver_patch or 0),
        )
        has_newer = compare_semver(cur, idx) > 0
    return KnowledgeBaseFileListItem(
        **base.model_dump(),
        kb_file_id=kb.id,
        pipeline_status=pipeline_status,
        pipeline_error=kb.pipeline_error,
        indexed_at=kb.indexed_at,
        chunk_count=kb.chunk_count,
        parsed_md_storage_key=f.parsed_md_storage_key,
        indexed_content_semver=indexed_content_semver,
        has_newer_content=has_newer,
    )


@router.post(
    "",
    response_model=SuccessResponse[KnowledgeBaseItem],
    status_code=status.HTTP_201_CREATED,
    summary="新建知识库",
)
async def create_knowledge_base(
    body: KnowledgeBaseCreateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[KnowledgeBaseItem]:
    """创建当前登录用户的知识库。"""
    row = await create_knowledge_base_owned(
        session,
        owner_user_id=current_user.id,
        name=body.name,
        code=body.code,
        description=body.description,
        thumbnail_url=body.thumbnail_url,
    )
    return ok(_to_kb_item(row), message="创建成功")


@router.get(
    "",
    response_model=SuccessResponse[list[KnowledgeBaseItem]],
    summary="知识库列表",
)
async def list_knowledge_bases(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[list[KnowledgeBaseItem]]:
    """查询当前登录用户的知识库列表。"""
    rows = await list_knowledge_bases_owned(
        session,
        owner_user_id=current_user.id,
    )
    return ok([_to_kb_item(x) for x in rows], message="查询成功")


@router.post(
    "/{kb_id}/files/add",
    response_model=SuccessResponse[KnowledgeBaseFileOperateResult],
    summary="文件加入知识库",
)
async def add_files_to_knowledge_base(
    kb_id: int,
    body: KnowledgeBaseFileOperateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[KnowledgeBaseFileOperateResult]:
    """批量将文件加入指定知识库。"""
    affected, skipped = await add_files_to_knowledge_base_owned(
        session,
        owner_user_id=current_user.id,
        kb_id=kb_id,
        file_ids=body.file_ids,
    )
    payload = KnowledgeBaseFileOperateResult(
        knowledge_base_id=kb_id,
        affected_file_ids=affected,
        skipped_file_ids=skipped,
    )
    return ok(payload, message="操作成功")


@router.post(
    "/{kb_id}/files/index",
    status_code=status.HTTP_202_ACCEPTED,
    summary="索引入队（Redis 异步执行）",
)
async def enqueue_kb_file_indexing(
    kb_id: int,
    body: KnowledgeBaseFileOperateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> JSONResponse:
    """将入库任务写入 Redis，由独立 worker 消费；成功项 ``pipeline_status`` 为 ``queued``。

    需配置 ``REDIS_URI``；文件需已有 ``parsed_md_storage_key``。worker 见 ``python -m rag.worker.kb_ingest``。
    """
    results = await enqueue_kb_file_indexing_owned(
        session,
        owner_user_id=current_user.id,
        kb_id=kb_id,
        file_ids=body.file_ids,
    )
    payload = KnowledgeBaseFileIndexTriggerResponse(
        knowledge_base_id=kb_id,
        results=results,
    )
    body_ok = ok(payload, message="已入队")
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=jsonable_encoder(body_ok.model_dump()),
    )


@router.get(
    "/{kb_id}/search",
    response_model=SuccessResponse[KnowledgeBaseSearchResponse],
    summary="知识库内向量检索",
)
async def search_knowledge_base(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    kb_id: int,
    q: str = Query(..., min_length=1, description="检索文本"),
    top_k: int = Query(default=5, ge=1, le=50, description="返回条数上限"),
) -> SuccessResponse[KnowledgeBaseSearchResponse]:
    """仅检索当前用户该知识库下已入库向量（按 metadata 过滤）。"""
    text = await search_knowledge_base_owned(
        session,
        owner_user_id=current_user.id,
        kb_id=kb_id,
        query=q.strip(),
        top_k=top_k,
    )
    payload = KnowledgeBaseSearchResponse(
        knowledge_base_id=kb_id,
        query=q.strip(),
        top_k=top_k,
        result_text=text,
    )
    return ok(payload, message="查询成功")


@router.post(
    "/{kb_id}/files/remove",
    response_model=SuccessResponse[KnowledgeBaseFileOperateResult],
    summary="文件移出知识库",
)
async def remove_files_from_knowledge_base(
    kb_id: int,
    body: KnowledgeBaseFileOperateRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[KnowledgeBaseFileOperateResult]:
    """批量将文件从指定知识库移出。"""
    affected, skipped = await remove_files_from_knowledge_base_owned(
        session,
        owner_user_id=current_user.id,
        kb_id=kb_id,
        file_ids=body.file_ids,
    )
    payload = KnowledgeBaseFileOperateResult(
        knowledge_base_id=kb_id,
        affected_file_ids=affected,
        skipped_file_ids=skipped,
    )
    return ok(payload, message="操作成功")


@router.get(
    "/{kb_id}/files",
    response_model=SuccessResponse[KnowledgeBaseFileListResponse],
    summary="查询知识库文件列表",
)
async def list_knowledge_base_files(
    kb_id: int,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，最大 100"),
) -> SuccessResponse[KnowledgeBaseFileListResponse]:
    """分页查询指定知识库下的文件列表。"""
    total, rows = await list_knowledge_base_files_owned(
        session,
        owner_user_id=current_user.id,
        kb_id=kb_id,
        page=page,
        page_size=page_size,
    )
    payload = KnowledgeBaseFileListResponse(
        knowledge_base_id=kb_id,
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_kb_file_list_item(f, kb) for f, kb in rows],
    )
    return ok(payload, message="查询成功")
