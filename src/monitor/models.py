"""LLM 监控 ORM 模型（SQLAlchemy 2.0 Declarative，独立 MetaData）。

3 张表，统一放在 PostgreSQL 的 llm_monitor schema 下：
- request_log: 每次 LLM 调用记录（Token 使用量、响应延迟、调用成功率、错误率/类型、缓存命中率）
- session:     活跃会话管理（会话数、会话级汇总）
- evaluation:  质量评估（Faithfulness / Groundedness / Answer Relevance / Hallucination Rate / 召回率）
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Float,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MonitorBase(DeclarativeBase):
    """监控表独立基类，与业务 MySQL 表完全隔离。"""


class RequestLog(MonitorBase):
    """每次 LLM 调用记录一行。

    覆盖指标:
        - Token 使用量:  input_tokens / input_tokens_cache_hit / input_tokens_cache_miss /
                          output_tokens / total_tokens（自动计算列）
        - 响应延迟:      latency_ms（总延迟）/ ttft_ms（首 Token 延迟）
        - 调用成功率:     status = 'success' | 'error' | 'timeout' | 'rate_limited'
        - 错误率与类型:   error_type + error_category 自动归类
        - 缓存命中率:     is_cache_hit / input_tokens_cache_hit / input_tokens_cache_miss
                          （cache_tokens_saved 与 input_tokens_cache_hit 同义，保留兼容）
    """

    __tablename__ = "request_log"
    __table_args__ = (
        Index("idx_req_session", "session_id"),
        Index("idx_req_model_time", "model", "created_at"),
        Index("idx_req_status", "status", "created_at"),
        Index("idx_req_user_time", "user_id", "created_at"),
        {"schema": "llm_monitor"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), default=_uuid.uuid4, unique=True, nullable=False,
    )
    session_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # 与图表「输入（命中缓存）/ 输入（未命中缓存）」一致；未命中 = input_tokens - 命中（由写入侧保证）
    input_tokens_cache_hit: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    input_tokens_cache_miss: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    total_tokens: Mapped[int | None] = mapped_column(
        Integer, Computed("input_tokens + output_tokens", persisted=True),
    )
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))

    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(20), default="success", server_default=text("'success'"))
    error_type: Mapped[str | None] = mapped_column(String(80))
    error_category: Mapped[str | None] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)

    is_cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    cache_tokens_saved: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    user_id: Mapped[str | None] = mapped_column(String(100))
    extra: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, server_default=text("now()"),
    )


class ChatSession(MonitorBase):
    """活跃会话，与 LangGraph thread 一一对应。

    覆盖指标:
        - 活跃会话数:  WHERE status = 'active'
        - 会话级汇总:  total_requests / total_tokens 按会话累加
    """

    __tablename__ = "session"
    __table_args__ = (
        Index("idx_session_status", "status", "last_active_at"),
        Index("idx_session_user", "user_id"),
        Index("idx_session_thread", "thread_id"),
        {"schema": "llm_monitor"},
    )

    id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(100))
    thread_id: Mapped[str | None] = mapped_column(String(200))

    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, server_default=text("now()"),
    )
    last_active_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, server_default=text("now()"),
    )
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    status: Mapped[str] = mapped_column(String(20), default="active", server_default=text("'active'"))
    total_requests: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    extra: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default=text("'{}'::jsonb"))


class Evaluation(MonitorBase):
    """LLM 输出质量评估（由离线评估管道写入）。

    覆盖指标:
        - Faithfulness / Groundedness: 生成内容是否忠实于上下文
        - Answer Relevance:           回答与问题的相关度
        - Hallucination Rate:         幻觉程度（0 = 无幻觉，1 = 完全幻觉）
        - 召回率 / 精确率:             RAG 检索质量（recall / precision）
    """

    __tablename__ = "evaluation"
    __table_args__ = (
        Index("idx_eval_request", "request_id"),
        Index("idx_eval_time", "evaluated_at"),
        {"schema": "llm_monitor"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    faithfulness: Mapped[float | None] = mapped_column(Float)
    groundedness: Mapped[float | None] = mapped_column(Float)
    answer_relevance: Mapped[float | None] = mapped_column(Float)
    hallucination_score: Mapped[float | None] = mapped_column(Float)

    recall: Mapped[float | None] = mapped_column(Float)
    precision: Mapped[float | None] = mapped_column(Float)
    retrieved_count: Mapped[int | None] = mapped_column(Integer)
    relevant_count: Mapped[int | None] = mapped_column(Integer)

    evaluator: Mapped[str | None] = mapped_column(String(100))
    evaluated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, server_default=text("now()"),
    )
