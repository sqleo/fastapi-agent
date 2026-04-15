"""LLM 监控概览 API。

数据格式已适配 @ant-design/charts：
- Line / Column / Area: [{date, value, category}]
- Pie:                  [{type, value}]
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from monitor.analytics import (
    Period,
    get_error_distribution,
    get_latency_trends,
    get_model_stats,
    get_overview,
    get_recent_requests,
    get_request_trends,
    get_success_rate_trends,
    get_token_trends,
)
from monitor.pg import get_session_factory
from utils.response import SuccessResponse, ok

router = APIRouter(prefix="/monitor", tags=["Monitor"])
logger = logging.getLogger("services.monitor_api")


# ── Response Schemas ─────────────────────────────────────


class OverviewData(BaseModel):
    """概览卡片数据。"""

    total_requests: int = 0
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_input_tokens_cache_hit: int = 0
    total_input_tokens_cache_miss: int = 0
    total_output_tokens: int = 0
    avg_latency_ms: float = 0
    p95_latency_ms: float = 0
    success_rate: float = Field(0, description="0~1")
    error_rate: float = Field(0, description="0~1")
    cache_hit_rate: float = Field(0, description="0~1")
    active_sessions: int = 0
    total_cost: float = 0


class TrendPoint(BaseModel):
    """折线/柱状图数据点。"""

    date: str
    value: float | int
    category: str


class ErrorTypeItem(BaseModel):
    """饼图/条形图数据点。"""

    type: str
    value: int


class ModelStatItem(BaseModel):
    """模型维度统计。"""

    model: str
    requests: int
    tokens: int
    avg_latency_ms: float
    success_rate: float


class RequestItem(BaseModel):
    """请求明细。"""

    request_id: str
    model: str | None = None
    provider: str | None = None
    input_tokens: int = 0
    input_tokens_cache_hit: int = 0
    input_tokens_cache_miss: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int | None = None
    status: str = "success"
    error_type: str | None = None
    is_cache_hit: bool = False
    user_id: str | None = None
    created_at: str


# ── Helper ───────────────────────────────────────────────


async def _get_monitor_session():
    factory = await get_session_factory()
    if not factory:
        return None
    return factory


# ── Endpoints ────────────────────────────────────────────


@router.get("/overview", response_model=SuccessResponse[OverviewData], summary="概览卡片")
async def overview():
    """实时概览：总请求、Token、成功率、延迟、活跃会话、缓存命中率。"""
    factory = await _get_monitor_session()
    if not factory:
        return ok(OverviewData(), message="监控未启用")
    async with factory() as session:
        data = await get_overview(session)
    return ok(OverviewData(**data))


@router.get(
    "/trends/requests",
    response_model=SuccessResponse[list[TrendPoint]],
    summary="请求量趋势",
)
async def trends_requests(
    period: Period = Query(Period.day, description="时间粒度: realtime/day/week/month"),
):
    """请求量趋势（折线图 / 柱状图）。"""
    factory = await _get_monitor_session()
    if not factory:
        return ok([])
    async with factory() as session:
        data = await get_request_trends(session, period)
    return ok(data)


@router.get(
    "/trends/tokens",
    response_model=SuccessResponse[list[TrendPoint]],
    summary="Token 用量趋势",
)
async def trends_tokens(
    period: Period = Query(Period.day, description="时间粒度: realtime/day/week/month"),
):
    """Token 用量趋势（堆叠图：input_cache_hit / input_cache_miss / output_tokens）。"""
    factory = await _get_monitor_session()
    if not factory:
        return ok([])
    async with factory() as session:
        data = await get_token_trends(session, period)
    return ok(data)


@router.get(
    "/trends/latency",
    response_model=SuccessResponse[list[TrendPoint]],
    summary="延迟趋势",
)
async def trends_latency(
    period: Period = Query(Period.day, description="时间粒度: realtime/day/week/month"),
):
    """延迟趋势（双折线：avg / p95）。"""
    factory = await _get_monitor_session()
    if not factory:
        return ok([])
    async with factory() as session:
        data = await get_latency_trends(session, period)
    return ok(data)


@router.get(
    "/trends/success_rate",
    response_model=SuccessResponse[list[TrendPoint]],
    summary="成功率趋势",
)
async def trends_success_rate(
    period: Period = Query(Period.day, description="时间粒度: realtime/day/week/month"),
):
    """调用成功率趋势。"""
    factory = await _get_monitor_session()
    if not factory:
        return ok([])
    async with factory() as session:
        data = await get_success_rate_trends(session, period)
    return ok(data)


@router.get(
    "/errors",
    response_model=SuccessResponse[list[ErrorTypeItem]],
    summary="错误类型分布",
)
async def error_distribution():
    """错误类型分布（饼图 / 条形图）。"""
    factory = await _get_monitor_session()
    if not factory:
        return ok([])
    async with factory() as session:
        data = await get_error_distribution(session)
    return ok(data)


@router.get(
    "/models",
    response_model=SuccessResponse[list[ModelStatItem]],
    summary="模型维度统计",
)
async def model_stats():
    """各模型使用量、Token、延迟、成功率（分组柱状图）。"""
    factory = await _get_monitor_session()
    if not factory:
        return ok([])
    async with factory() as session:
        data = await get_model_stats(session)
    return ok(data)


@router.get(
    "/requests",
    response_model=SuccessResponse[list[RequestItem]],
    summary="最近请求明细",
)
async def recent_requests(
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
):
    """最近 N 条请求记录。"""
    factory = await _get_monitor_session()
    if not factory:
        return ok([])
    async with factory() as session:
        data = await get_recent_requests(session, limit)
    return ok(data)
