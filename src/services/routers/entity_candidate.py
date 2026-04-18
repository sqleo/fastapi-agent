"""实体候选审核路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from models.EntityDictionaryModel import CandidateStatus, EntityType
from schemas.entity_candidate_schema import (
    EntityCandidateApproveRequest,
    EntityCandidateItem,
    EntityCandidateListResponse,
    EntityCandidateMergeRequest,
    EntityCandidateRejectRequest,
    EntityReviewResult,
    TargetEntityOptionItem,
    TargetEntityOptionListResponse,
)
from services.controllers.entity_candidate_controller import (
    approve_entity_candidate_owned,
    list_entity_candidates_owned,
    list_target_entities_owned,
    merge_entity_candidate_owned,
    reject_entity_candidate_owned,
)
from utils.auth_deps import CurrentUserDeps
from utils.response import SuccessResponse, ok
from utils.sql_db import AsyncSqlSessionDeps

router = APIRouter(prefix="/entity-candidates", tags=["Entity Candidate"])


def _to_candidate_item(x) -> EntityCandidateItem:
    return EntityCandidateItem(
        id=x.id,
        owner_user_id=x.owner_user_id,
        biz_code=x.biz_code,
        knowledge_base_id=x.knowledge_base_id,
        file_id=x.file_id,
        entity_type=x.entity_type.value if hasattr(x.entity_type, "value") else (str(x.entity_type) if x.entity_type else None),
        candidate_text=x.candidate_text,
        candidate_normalized=x.candidate_normalized,
        evidence=x.evidence,
        frequency=x.frequency,
        confidence=x.confidence,
        status=x.status.value if hasattr(x.status, "value") else str(x.status),
        reviewer_user_id=x.reviewer_user_id,
        reviewed_at=x.reviewed_at,
        review_comment=x.review_comment,
        approved_entity_id=x.approved_entity_id,
        created_at=x.created_at,
        updated_at=x.updated_at,
    )


@router.get(
    "",
    response_model=SuccessResponse[EntityCandidateListResponse],
    summary="候选实体分页列表",
)
async def list_entity_candidates(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，最大 100"),
    status_filter: CandidateStatus | None = Query(default=CandidateStatus.PENDING, alias="status", description="状态过滤"),
    biz_code: str | None = Query(default=None, description="业务编码；不传表示不按业务过滤"),
    knowledge_base_id: int | None = Query(default=None, description="知识库 id；不传表示不按知识库过滤"),
    file_id: int | None = Query(default=None, description="来源文件 id"),
    keyword: str | None = Query(default=None, description="按候选文本模糊搜索"),
) -> SuccessResponse[EntityCandidateListResponse]:
    total, rows = await list_entity_candidates_owned(
        session,
        owner_user_id=current_user.id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        biz_code=biz_code,
        knowledge_base_id=knowledge_base_id,
        file_id=file_id,
        keyword=keyword,
    )
    payload = EntityCandidateListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_candidate_item(x) for x in rows],
    )
    return ok(payload, message="查询成功")


@router.post(
    "/{candidate_id}/approve",
    response_model=SuccessResponse[EntityReviewResult],
    summary="候选实体审核通过",
)
async def approve_entity_candidate(
    candidate_id: int,
    body: EntityCandidateApproveRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[EntityReviewResult]:
    row = await approve_entity_candidate_owned(
        session,
        owner_user_id=current_user.id,
        reviewer_user_id=current_user.id,
        reviewer_name=current_user.username,
        candidate_id=candidate_id,
        canonical_name=body.canonical_name,
        entity_type=body.entity_type,
        aliases=body.aliases,
        review_comment=body.review_comment,
    )
    return ok(
        EntityReviewResult(
            candidate_id=int(row.id),
            status=row.status,
            approved_entity_id=row.approved_entity_id,
        ),
        message="审核通过成功",
    )


@router.post(
    "/{candidate_id}/reject",
    response_model=SuccessResponse[EntityReviewResult],
    summary="候选实体驳回",
)
async def reject_entity_candidate(
    candidate_id: int,
    body: EntityCandidateRejectRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[EntityReviewResult]:
    row = await reject_entity_candidate_owned(
        session,
        owner_user_id=current_user.id,
        reviewer_user_id=current_user.id,
        reviewer_name=current_user.username,
        candidate_id=candidate_id,
        review_comment=body.review_comment,
    )
    return ok(
        EntityReviewResult(
            candidate_id=int(row.id),
            status=row.status,
            approved_entity_id=row.approved_entity_id,
        ),
        message="驳回成功",
    )


@router.post(
    "/{candidate_id}/merge",
    response_model=SuccessResponse[EntityReviewResult],
    summary="候选实体合并到正式实体",
)
async def merge_entity_candidate(
    candidate_id: int,
    body: EntityCandidateMergeRequest,
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
) -> SuccessResponse[EntityReviewResult]:
    row = await merge_entity_candidate_owned(
        session,
        owner_user_id=current_user.id,
        reviewer_user_id=current_user.id,
        reviewer_name=current_user.username,
        candidate_id=candidate_id,
        target_entity_id=body.target_entity_id,
        review_comment=body.review_comment,
    )
    return ok(
        EntityReviewResult(
            candidate_id=int(row.id),
            status=row.status,
            approved_entity_id=row.approved_entity_id,
        ),
        message="合并成功",
    )


@router.get(
    "/target-entities",
    response_model=SuccessResponse[TargetEntityOptionListResponse],
    summary="合并目标正式实体下拉",
)
async def list_target_entities(
    current_user: CurrentUserDeps,
    session: AsyncSqlSessionDeps,
    biz_code: str | None = Query(default=None, description="业务编码；建议与候选一致"),
    knowledge_base_id: int | None = Query(default=None, description="知识库 id；建议与候选一致"),
    entity_type: EntityType | None = Query(default=None, description="实体类型过滤"),
    keyword: str | None = Query(default=None, description="标准实体名模糊搜索"),
    limit: int = Query(default=50, ge=1, le=200, description="返回条数上限"),
) -> SuccessResponse[TargetEntityOptionListResponse]:
    total, rows = await list_target_entities_owned(
        session,
        owner_user_id=current_user.id,
        biz_code=biz_code,
        knowledge_base_id=knowledge_base_id,
        entity_type=entity_type,
        keyword=keyword,
        limit=limit,
    )
    payload = TargetEntityOptionListResponse(
        total=total,
        items=[
            TargetEntityOptionItem(
                id=int(x.id),
                canonical_name=x.canonical_name,
                entity_type=x.entity_type.value if hasattr(x.entity_type, "value") else str(x.entity_type),
                biz_code=x.biz_code,
                knowledge_base_id=x.knowledge_base_id,
            )
            for x in rows
        ],
    )
    return ok(payload, message="查询成功")
