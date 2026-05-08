"""研报工作台相关 Schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ReportHistoryItem(BaseModel):
    """左侧历史列表项。"""

    thread_id: str = Field(..., description="LangGraph thread_id")
    title: str = Field(..., description="报告标题")
    subtitle: str | None = Field(default=None, description="列表副标题")
    status: str = Field(..., description="UI 状态: draft/running/waiting_review/completed/failed/cancelled")
    stage: str = Field(..., description="当前阶段: intent/research/outline/writing/final")
    updated_at: datetime = Field(..., description="更新时间")
    created_at: datetime = Field(..., description="创建时间")
    summary: str | None = Field(default=None, description="摘要")
    can_resume: bool = Field(default=False, description="是否可继续执行")
    progress_text: str | None = Field(default=None, description="当前进度描述")


class ReportIntentDto(BaseModel):
    topic: str | None = None
    report_type: str | None = None
    scope: str | None = None
    time_range: str | None = None
    depth: str | None = None
    style_instruction: str | None = None
    output_format: str | None = None
    industry: str | None = None


class ReportSourceDto(BaseModel):
    source_id: str = Field(..., description="来源唯一标识")
    title: str = Field(..., description="来源标题")
    summary: str = Field(..., description="来源摘要")
    source_type: str = Field(..., description="来源类型: kb/web/api/upload")
    url: str | None = Field(default=None, description="来源链接")
    domain: str | None = Field(default=None, description="来源域名")
    tool: str | None = Field(default=None, description="采集工具")
    topic_key: str | None = Field(default=None, description="归属主题 key")
    confidence: float | None = Field(default=None, description="可信度")
    raw_query: str | None = Field(default=None, description="原始查询语句")


class ReportOutlineSectionDto(BaseModel):
    section_id: str
    title: str
    objective: str
    key_points: list[str] = Field(default_factory=list)
    evidence_keys: list[str] = Field(default_factory=list)
    target_words: int = 0
    order: int = 0
    status: str = Field(default="ready", description="pending/ready/approved/rejected")


class ReportSectionDto(BaseModel):
    section_id: str
    title: str
    content: str | None = None
    status: str = Field(..., description="pending/writing/reviewing/revising/done/failed")
    score: int | None = None
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    word_count: int | None = None
    updated_at: datetime | None = None


class ReportReviewDto(BaseModel):
    round: int = 0
    overall_score: float | None = None
    passed: bool | None = None
    sections_to_revise: list[str] = Field(default_factory=list)
    summary: str | None = None


class FinalReportDto(BaseModel):
    markdown: str
    chapter_count: int = 0
    word_count: int = 0
    citation_count: int = 0
    quality_score: float | None = None


class ReportArtifactDto(BaseModel):
    artifact_id: str
    type: str
    title: str
    url: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ReportMetricsDto(BaseModel):
    total_sources: int = 0
    completed_tasks: int = 0
    total_tasks: int = 0
    progress_percent: float = 0
    current_message: str | None = None


class ReportInterruptDto(BaseModel):
    kind: str = Field(..., description="intent_review/outline_review")
    node_name: str = Field(..., description="中断节点名")
    message: str = Field(..., description="提示信息")
    payload: dict[str, Any] = Field(default_factory=dict, description="完整中断内容")


class ReportHistoryDetail(BaseModel):
    """工作台详情。"""

    thread_id: str
    title: str
    user_query: str
    status: str
    stage: str
    intent: ReportIntentDto | None = None
    intent_missing_fields: list[str] = Field(default_factory=list)
    sources: list[ReportSourceDto] = Field(default_factory=list)
    outline: list[ReportOutlineSectionDto] = Field(default_factory=list)
    sections: list[ReportSectionDto] = Field(default_factory=list)
    review: ReportReviewDto | None = None
    final_report: FinalReportDto | None = None
    artifacts: list[ReportArtifactDto] = Field(default_factory=list)
    metrics: ReportMetricsDto = Field(default_factory=ReportMetricsDto)
    interrupt: ReportInterruptDto | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    last_error: str | None = None


class ReportHistoryListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ReportHistoryItem] = Field(default_factory=list)
