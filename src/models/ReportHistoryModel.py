"""智能研报业务历史主表."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, Column, Index, Text
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from models.BasicModel import BasicModel


class ReportHistoryStatus(str, Enum):
    """研报生成业务状态."""

    CREATED = "created"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReportHistoryModel(BasicModel, table=True):
    """研报历史主表.

    与 LangGraph checkpoint 的“执行态历史”分层：
    - 本表负责业务可查询历史：列表、详情、继续生成、追踪结果
    - checkpoint 负责流程中断恢复、时间旅行与完整状态快照
    """

    __tablename__ = "report_history"
    __table_args__ = (
        Index("idx_report_history_owner_updated", "owner_user_id", "updated_at"),
        Index("idx_report_history_owner_status", "owner_user_id", "status"),
        Index("idx_report_history_owner_topic", "owner_user_id", "topic"),
    )

    owner_user_id: int = Field(
        foreign_key="user.id",
        nullable=False,
        index=True,
        description="归属用户 id；用于多租户隔离",
        sa_column_kwargs={"comment": "归属用户 id；用于多租户隔离"},
    )
    thread_id: str = Field(
        max_length=128,
        unique=True,
        index=True,
        description="LangGraph thread_id；作为研报业务主键",
        sa_column_kwargs={"comment": "LangGraph thread_id；作为研报业务主键"},
    )
    user_query: str | None = Field(
        default=None,
        sa_column=Column(Text, comment="用户原始需求"),
        description="用户原始需求",
    )
    topic: str | None = Field(
        default=None,
        max_length=255,
        index=True,
        description="结构化主题或回退后的主题",
    )
    report_type: str | None = Field(
        default=None,
        max_length=128,
        description="研报类型：竞争格局/市场趋势/技术分析等",
    )
    status: ReportHistoryStatus = Field(
        default=ReportHistoryStatus.CREATED,
        sa_column=Column(
            SAEnum(
                ReportHistoryStatus,
                name="report_history_status",
                native_enum=False,
                length=32,
            )
        ),
        description="业务状态：created/running/interrupted/completed/failed/cancelled",
    )
    current_node: str | None = Field(
        default=None,
        max_length=128,
        description="最近一次同步时的当前节点",
    )
    summary: str | None = Field(
        default=None,
        max_length=1000,
        description="列表预览摘要",
    )
    final_report: str | None = Field(
        default=None,
        sa_column=Column(Text, comment="最终报告正文"),
        description="最终报告正文",
    )
    word_count: int | None = Field(
        default=None,
        ge=0,
        description="最终报告字数（按字符数近似）",
    )
    intent_payload: dict | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="结构化意图快照",
    )
    outline_payload: list[dict] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="大纲快照",
    )
    interrupt_payload: dict | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="最近一次中断信息",
    )
    token_usage: dict | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="Token 使用统计",
    )
    artifacts: list[dict] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="中间产物列表",
    )
    started_at: datetime | None = Field(default=None, description="首次开始生成时间")
    finished_at: datetime | None = Field(default=None, description="完成/失败时间")
    last_error: str | None = Field(
        default=None,
        sa_column=Column(Text, comment="最近一次错误信息"),
        description="最近一次错误信息",
    )
