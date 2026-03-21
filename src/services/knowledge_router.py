"""资料库 HTTP 路由."""

from fastapi import APIRouter, status

from services.controllers.knowledge_controller import (
    create_knowledge_base,
    list_knowledge_bases_by_owner,
)
from schemas.knowledge_schema import KnowledgeCreateRequest, KnowledgePublicResponse
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])


@router.get(
    "/bases",
    response_model=SuccessResponse[list[KnowledgePublicResponse]],
    summary="我的资料库列表",
)
async def list_knowledge_bases_route(
    session: AsyncSqlSessionDeps,
    current_user: CurrentUserDeps,
):
    """返回当前登录用户名下的全部资料库。"""
    rows = await list_knowledge_bases_by_owner(
        session, owner_user_id=current_user.id
    )
    data = [KnowledgePublicResponse.model_validate(k) for k in rows]
    return ok(data, message="success")


@router.post(
    "/bases",
    response_model=SuccessResponse[KnowledgePublicResponse],
    status_code=status.HTTP_201_CREATED,
    summary="新建资料库",
)
async def create_knowledge_base_route(
    body: KnowledgeCreateRequest,
    session: AsyncSqlSessionDeps,
    current_user: CurrentUserDeps,
):
    """创建资料库，归属当前登录用户。"""
    name = body.name.strip()
    desc = (body.description or "").strip() or None
    thumb = (body.thumbnail_key or "").strip() or None
    kb = await create_knowledge_base(
        session,
        owner_user_id=current_user.id,
        name=name,
        description=desc,
        thumbnail_key=thumb,
        audit_label=current_user.username,
    )
    data = KnowledgePublicResponse.model_validate(kb)
    return ok(data, message="创建成功")
