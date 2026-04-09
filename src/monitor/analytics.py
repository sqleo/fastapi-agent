"""监控数据聚合查询（SQLAlchemy ORM）。

返回结构均已适配 @ant-design/charts 的数据格式：
- 折线/柱状图: [{date, value, category}]
- 饼图:        [{type, value}]
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class Period(str, Enum):
    """时间粒度。"""

    realtime = "realtime"
    day = "day"
    week = "week"
    month = "month"


_TRUNC_MAP = {
    Period.realtime: "hour",
    Period.day: "day",
    Period.week: "week",
    Period.month: "month",
}

_DEFAULT_LOOKBACK = {
    Period.realtime: timedelta(hours=24),
    Period.day: timedelta(days=30),
    Period.week: timedelta(weeks=12),
    Period.month: timedelta(days=365),
}


def _since(period: Period) -> datetime:
    return datetime.now(timezone.utc) - _DEFAULT_LOOKBACK[period]


# ── 概览卡片 ──────────────────────────────────────────────


async def get_overview(session: AsyncSession) -> dict:
    """实时概览：总请求、Token、成功率、平均延迟、活跃会话、缓存命中率、错误率。"""
    row = (
        await session.execute(
            text("""\
                SELECT
                    count(*)                                       AS total_requests,
                    coalesce(sum(input_tokens + output_tokens), 0) AS total_tokens,
                    coalesce(sum(input_tokens), 0)                 AS total_input_tokens,
                    coalesce(sum(input_tokens_cache_hit), 0)       AS total_input_tokens_cache_hit,
                    coalesce(sum(input_tokens_cache_miss), 0)      AS total_input_tokens_cache_miss,
                    coalesce(sum(output_tokens), 0)                AS total_output_tokens,
                    round(avg(latency_ms)::numeric, 1)             AS avg_latency_ms,
                    round(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric, 1) AS p95_latency_ms,
                    count(*) FILTER (WHERE status = 'success')     AS success_count,
                    count(*) FILTER (WHERE status != 'success')    AS error_count,
                    count(*) FILTER (WHERE is_cache_hit)           AS cache_hit_count,
                    coalesce(sum(estimated_cost), 0)               AS total_cost
                FROM llm_monitor.request_log
            """)
        )
    ).mappings().first()

    session_row = (
        await session.execute(
            text("""\
                SELECT count(*) AS active_sessions
                FROM llm_monitor.session
                WHERE status = 'active'
                  AND last_active_at > now() - interval '30 minutes'
            """)
        )
    ).mappings().first()

    total = row["total_requests"] or 0
    success = row["success_count"] or 0
    errors = row["error_count"] or 0
    cache_hits = row["cache_hit_count"] or 0

    return {
        "total_requests": total,
        "total_tokens": int(row["total_tokens"]),
        "total_input_tokens": int(row["total_input_tokens"]),
        "total_input_tokens_cache_hit": int(row["total_input_tokens_cache_hit"]),
        "total_input_tokens_cache_miss": int(row["total_input_tokens_cache_miss"]),
        "total_output_tokens": int(row["total_output_tokens"]),
        "avg_latency_ms": float(row["avg_latency_ms"] or 0),
        "p95_latency_ms": float(row["p95_latency_ms"] or 0),
        "success_rate": round(success / total, 4) if total else 0,
        "error_rate": round(errors / total, 4) if total else 0,
        "cache_hit_rate": round(cache_hits / total, 4) if total else 0,
        "active_sessions": session_row["active_sessions"] or 0,
        "total_cost": float(row["total_cost"]),
    }


# ── 趋势图（折线 / 柱状）─────────────────────────────────


async def get_request_trends(session: AsyncSession, period: Period) -> list[dict]:
    """请求量趋势 → [{date, value, category:"requests"}]"""
    since = _since(period)
    trunc = _TRUNC_MAP[period]
    rows = (
        await session.execute(
            text(f"""\
                SELECT date_trunc(:trunc, created_at) AS date,
                       count(*)                       AS value
                FROM llm_monitor.request_log
                WHERE created_at >= :since
                GROUP BY 1 ORDER BY 1
            """),
            {"trunc": trunc, "since": since},
        )
    ).mappings().all()
    return [{"date": str(r["date"]), "value": r["value"], "category": "requests"} for r in rows]


async def get_token_trends(session: AsyncSession, period: Period) -> list[dict]:
    """Token 用量趋势 → 三类：input_cache_hit / input_cache_miss / output_tokens（与堆叠图图例一致）。"""
    since = _since(period)
    trunc = _TRUNC_MAP[period]
    rows = (
        await session.execute(
            text(f"""\
                SELECT date_trunc(:trunc, created_at) AS date,
                       coalesce(sum(input_tokens_cache_hit), 0)  AS input_hit,
                       coalesce(sum(input_tokens_cache_miss), 0) AS input_miss,
                       coalesce(sum(output_tokens), 0) AS output_tokens
                FROM llm_monitor.request_log
                WHERE created_at >= :since
                GROUP BY 1 ORDER BY 1
            """),
            {"trunc": trunc, "since": since},
        )
    ).mappings().all()
    result = []
    for r in rows:
        d = str(r["date"])
        result.append({"date": d, "value": int(r["input_hit"]), "category": "input_cache_hit"})
        result.append({"date": d, "value": int(r["input_miss"]), "category": "input_cache_miss"})
        result.append({"date": d, "value": int(r["output_tokens"]), "category": "output_tokens"})
    return result


async def get_latency_trends(session: AsyncSession, period: Period) -> list[dict]:
    """延迟趋势 → [{date, value, category:"avg"|"p95"}]"""
    since = _since(period)
    trunc = _TRUNC_MAP[period]
    rows = (
        await session.execute(
            text(f"""\
                SELECT date_trunc(:trunc, created_at) AS date,
                       round(avg(latency_ms)::numeric, 1) AS avg_ms,
                       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric, 1) AS p95_ms
                FROM llm_monitor.request_log
                WHERE created_at >= :since
                GROUP BY 1 ORDER BY 1
            """),
            {"trunc": trunc, "since": since},
        )
    ).mappings().all()
    result = []
    for r in rows:
        d = str(r["date"])
        result.append({"date": d, "value": float(r["avg_ms"] or 0), "category": "avg"})
        result.append({"date": d, "value": float(r["p95_ms"] or 0), "category": "p95"})
    return result


async def get_success_rate_trends(session: AsyncSession, period: Period) -> list[dict]:
    """成功率趋势 → [{date, value, category:"success_rate"}]"""
    since = _since(period)
    trunc = _TRUNC_MAP[period]
    rows = (
        await session.execute(
            text(f"""\
                SELECT date_trunc(:trunc, created_at) AS date,
                       count(*)                                    AS total,
                       count(*) FILTER (WHERE status = 'success')  AS success
                FROM llm_monitor.request_log
                WHERE created_at >= :since
                GROUP BY 1 ORDER BY 1
            """),
            {"trunc": trunc, "since": since},
        )
    ).mappings().all()
    return [
        {
            "date": str(r["date"]),
            "value": round(r["success"] / r["total"], 4) if r["total"] else 0,
            "category": "success_rate",
        }
        for r in rows
    ]


# ── 错误分布（饼图 / 条形图）─────────────────────────────


async def get_error_distribution(session: AsyncSession) -> list[dict]:
    """错误类型分布 → [{type, value}]"""
    rows = (
        await session.execute(
            text("""\
                SELECT coalesce(error_type, 'unknown') AS type,
                       count(*)                        AS value
                FROM llm_monitor.request_log
                WHERE status != 'success'
                GROUP BY 1 ORDER BY 2 DESC
            """)
        )
    ).mappings().all()
    return [{"type": r["type"], "value": r["value"]} for r in rows]


# ── 模型维度统计（条形图）────────────────────────────────


async def get_model_stats(session: AsyncSession) -> list[dict]:
    """各模型使用统计 → [{model, requests, tokens, avg_latency_ms}]"""
    rows = (
        await session.execute(
            text("""\
                SELECT model,
                       count(*)                                        AS requests,
                       coalesce(sum(input_tokens + output_tokens), 0)  AS tokens,
                       round(avg(latency_ms)::numeric, 1)              AS avg_latency_ms,
                       count(*) FILTER (WHERE status = 'success')      AS success_count
                FROM llm_monitor.request_log
                GROUP BY model ORDER BY requests DESC
            """)
        )
    ).mappings().all()
    return [
        {
            "model": r["model"] or "unknown",
            "requests": r["requests"],
            "tokens": int(r["tokens"]),
            "avg_latency_ms": float(r["avg_latency_ms"] or 0),
            "success_rate": round(r["success_count"] / r["requests"], 4) if r["requests"] else 0,
        }
        for r in rows
    ]


# ── 最近请求列表 ─────────────────────────────────────────


async def get_recent_requests(session: AsyncSession, limit: int = 20) -> list[dict]:
    """最近 N 条请求明细。"""
    rows = (
        await session.execute(
            text("""\
                SELECT request_id, model, provider, input_tokens,
                       input_tokens_cache_hit, input_tokens_cache_miss,
                       output_tokens,
                       (input_tokens + output_tokens) AS total_tokens,
                       latency_ms, status, error_type, is_cache_hit,
                       user_id, created_at
                FROM llm_monitor.request_log
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )
    ).mappings().all()
    return [
        {
            "request_id": str(r["request_id"]),
            "model": r["model"],
            "provider": r["provider"],
            "input_tokens": r["input_tokens"],
            "input_tokens_cache_hit": r["input_tokens_cache_hit"],
            "input_tokens_cache_miss": r["input_tokens_cache_miss"],
            "output_tokens": r["output_tokens"],
            "total_tokens": r["total_tokens"],
            "latency_ms": r["latency_ms"],
            "status": r["status"],
            "error_type": r["error_type"],
            "is_cache_hit": r["is_cache_hit"],
            "user_id": r["user_id"],
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]
