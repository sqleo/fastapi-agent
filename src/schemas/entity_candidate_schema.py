"""实体候选审核 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from models.EntityDictionaryModel import CandidateStatus, EntityType


class EntityCandidateItem(BaseModel):
    """候选实体项。"""

    id: int = Field(..., description="候选 id")
    owner_user_id: int = Field(..., description="归属用户 id")
    biz_code: str | None = Field(default=None, description="业务线编码")
    knowledge_base_id: int | None = Field(default=None, description="知识库 id")
    file_id: int | None = Field(default=None, description="来源文件 id")
    entity_type: str | None = Field(default=None, description="候选实体类型")
    candidate_text: str = Field(..., description="候选实体文本")
    candidate_normalized: str = Field(..., description="候选归一化文本")
    evidence: dict | None = Field(default=None, description="证据信息")
    frequency: int = Field(..., description="出现频次")
    confidence: float | None = Field(default=None, description="置信度")
    status: str = Field(..., description="审核状态")
    reviewer_user_id: int | None = Field(default=None, description="审核人 id")
    reviewed_at: datetime | None = Field(default=None, description="审核时间")
    review_comment: str | None = Field(default=None, description="审核备注")
    approved_entity_id: int | None = Field(default=None, description="审核通过/合并后的正式实体 id")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class EntityCandidateListResponse(BaseModel):
    """候选实体分页列表。"""

    total: int = Field(..., description="总条数")
    page: int = Field(..., description="当前页")
    page_size: int = Field(..., description="每页条数")
    items: list[EntityCandidateItem] = Field(default_factory=list, description="候选列表")


class EntityCandidateApproveRequest(BaseModel):
    """审核通过请求。"""

    canonical_name: str | None = Field(default=None, min_length=1, max_length=255, description="标准实体名；不传默认候选文本")
    entity_type: EntityType | None = Field(default=None, description="实体类型；不传默认候选类型")
    aliases: list[str] = Field(default_factory=list, description="额外别名列表")
    review_comment: str | None = Field(default=None, max_length=500, description="审核备注")


class EntityCandidateRejectRequest(BaseModel):
    """审核拒绝请求。"""

    review_comment: str | None = Field(default=None, max_length=500, description="拒绝备注")


class EntityCandidateMergeRequest(BaseModel):
    """审核合并请求。"""

    target_entity_id: int = Field(..., description="目标正式实体 id")
    review_comment: str | None = Field(default=None, max_length=500, description="合并备注")


class EntityReviewResult(BaseModel):
    """审核动作结果。"""

    candidate_id: int = Field(..., description="候选 id")
    status: CandidateStatus = Field(..., description="审核后状态")
    approved_entity_id: int | None = Field(default=None, description="通过/合并后的正式实体 id")


class TargetEntityOptionItem(BaseModel):
    """候选合并目标实体下拉项。"""

    id: int = Field(..., description="正式实体 id")
    canonical_name: str = Field(..., description="标准实体名")
    entity_type: str = Field(..., description="实体类型")
    biz_code: str | None = Field(default=None, description="业务线编码")
    knowledge_base_id: int | None = Field(default=None, description="知识库 id")


class TargetEntityOptionListResponse(BaseModel):
    """候选合并目标实体下拉列表响应。"""

    total: int = Field(..., description="总条数")
    items: list[TargetEntityOptionItem] = Field(default_factory=list, description="下拉选项列表")
