"""研报历史业务逻辑。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.BasicModel import beijing_now
from models.ReportHistoryModel import ReportHistoryModel, ReportHistoryStatus
from utils.json import safe_serialize


def _truncate_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        text = _truncate_text(value, 10_000)
        if text:
            return text
    return None


def _normalize_status(value: str | ReportHistoryStatus | None) -> ReportHistoryStatus | None:
    if value is None:
        return None
    if isinstance(value, ReportHistoryStatus):
        return value
    return ReportHistoryStatus(str(value))


def infer_report_status(next_nodes: list[str] | None) -> ReportHistoryStatus:
    """从图状态推断业务状态。"""
    nodes = list(next_nodes or [])
    if not nodes:
        return ReportHistoryStatus.COMPLETED
    if "human_review" in nodes or "human_review_intent" in nodes:
        return ReportHistoryStatus.INTERRUPTED
    return ReportHistoryStatus.RUNNING


def _normalize_current_node(current_node: str | list[str] | tuple[str, ...] | None) -> str | None:
    if isinstance(current_node, str):
        return _truncate_text(current_node, 128)
    if isinstance(current_node, (list, tuple)):
        for node in current_node:
            text = _truncate_text(node, 128)
            if text:
                return text
    return None


def _build_summary(
    *,
    final_report: Any,
    outline_payload: Any,
    fallback_query: Any,
) -> str | None:
    final_text = _truncate_text(final_report, 300)
    if final_text:
        return final_text

    if isinstance(outline_payload, list):
        titles: list[str] = []
        for item in outline_payload:
            if not isinstance(item, dict):
                continue
            title = _truncate_text(item.get("title"), 120)
            if title:
                titles.append(title)
            if len(titles) >= 3:
                break
        if titles:
            return " / ".join(titles)

    return _truncate_text(fallback_query, 300)


def build_report_history_changes(
    *,
    user_query: str | None = None,
    state_values: dict[str, Any] | None = None,
    status: str | ReportHistoryStatus | None = None,
    current_node: str | list[str] | tuple[str, ...] | None = None,
    interrupt_payload: dict[str, Any] | None = None,
    last_error: str | None = None,
) -> dict[str, Any]:
    """把图状态与显式覆盖项转换为业务表字段。"""
    serialized = safe_serialize(state_values) if state_values else {}
    if not isinstance(serialized, dict):
        serialized = {}

    normalized_status = _normalize_status(status)
    intent_payload = serialized.get("intent")
    outline_payload = serialized.get("outline")
    final_report = _truncate_text(serialized.get("final_report"), 200_000)
    effective_query = _first_nonempty(user_query, serialized.get("user_query"))
    topic = _first_nonempty(
        intent_payload.get("topic") if isinstance(intent_payload, dict) else None,
        effective_query,
    )
    report_type = _first_nonempty(
        intent_payload.get("report_type") if isinstance(intent_payload, dict) else None,
    )
    summary = _build_summary(
        final_report=final_report,
        outline_payload=outline_payload,
        fallback_query=effective_query,
    )
    changes: dict[str, Any] = {
        "user_query": effective_query,
        "topic": _truncate_text(topic, 255),
        "report_type": _truncate_text(report_type, 128),
        "current_node": _normalize_current_node(current_node),
        "summary": _truncate_text(summary, 1000),
        "final_report": final_report,
        "word_count": len(final_report) if final_report else None,
        "intent_payload": intent_payload if isinstance(intent_payload, dict) else None,
        "outline_payload": outline_payload if isinstance(outline_payload, list) else None,
        "token_usage": serialized.get("token_usage") if isinstance(serialized.get("token_usage"), dict) else None,
        "artifacts": serialized.get("artifacts") if isinstance(serialized.get("artifacts"), list) else None,
    }

    if interrupt_payload is not None:
        safe_interrupt = safe_serialize(interrupt_payload)
        changes["interrupt_payload"] = safe_interrupt if isinstance(safe_interrupt, dict) else None
    if last_error is not None:
        changes["last_error"] = _truncate_text(last_error, 20_000)
    if normalized_status is not None:
        changes["status"] = normalized_status
    return changes


async def _get_report_history_by_thread_id(
    session: AsyncSession,
    *,
    thread_id: str,
) -> ReportHistoryModel | None:
    stmt = select(ReportHistoryModel).where(ReportHistoryModel.thread_id == thread_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def get_report_history_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    thread_id: str,
) -> ReportHistoryModel | None:
    """查询当前用户的单条研报历史。"""
    stmt = select(ReportHistoryModel).where(
        ReportHistoryModel.owner_user_id == owner_user_id,
        ReportHistoryModel.thread_id == thread_id,
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_report_histories_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    page: int = 1,
    page_size: int = 20,
    status: str | ReportHistoryStatus | None = None,
    keyword: str | None = None,
) -> tuple[int, list[ReportHistoryModel]]:
    """分页查询当前用户的研报历史。"""
    filters = [ReportHistoryModel.owner_user_id == owner_user_id]
    normalized_status = _normalize_status(status)
    if normalized_status is not None:
        filters.append(ReportHistoryModel.status == normalized_status)

    keyword_text = _truncate_text(keyword, 255)
    if keyword_text:
        like_value = f"%{keyword_text}%"
        filters.append(
            or_(
                ReportHistoryModel.topic.like(like_value),
                ReportHistoryModel.user_query.like(like_value),
            )
        )

    total_stmt = select(func.count()).select_from(ReportHistoryModel).where(*filters)
    total_res = await session.execute(total_stmt)
    total = int(total_res.scalar_one() or 0)

    stmt = (
        select(ReportHistoryModel)
        .where(*filters)
        .order_by(ReportHistoryModel.updated_at.desc(), ReportHistoryModel.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    res = await session.execute(stmt)
    return total, list(res.scalars().all())


async def upsert_report_history_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    thread_id: str,
    operator_name: str | None = None,
    user_query: str | None = None,
    state_values: dict[str, Any] | None = None,
    status: str | ReportHistoryStatus | None = None,
    current_node: str | list[str] | tuple[str, ...] | None = None,
    interrupt_payload: dict[str, Any] | None = None,
    last_error: str | None = None,
) -> ReportHistoryModel:
    """按 thread_id 幂等写入或更新研报历史。"""
    row = await _get_report_history_by_thread_id(session, thread_id=thread_id)
    if row is None:
        row = ReportHistoryModel(
            owner_user_id=owner_user_id,
            thread_id=_truncate_text(thread_id, 128) or thread_id,
        )
        row.started_at = beijing_now()
        row.create_by = _truncate_text(operator_name, 64)
        session.add(row)
    elif row.owner_user_id != owner_user_id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="研报不存在")

    changes = build_report_history_changes(
        user_query=user_query,
        state_values=state_values,
        status=status,
        current_node=current_node,
        interrupt_payload=interrupt_payload,
        last_error=last_error,
    )
    now = beijing_now()

    for key, value in changes.items():
        if key == "user_query" and value is None and row.user_query:
            continue
        setattr(row, key, value)

    normalized_status = changes.get("status")
    if normalized_status in {
        ReportHistoryStatus.CREATED,
        ReportHistoryStatus.RUNNING,
        ReportHistoryStatus.INTERRUPTED,
    }:
        row.finished_at = None
    if normalized_status == ReportHistoryStatus.COMPLETED:
        row.finished_at = now
        row.last_error = None
        row.interrupt_payload = None
    elif normalized_status in {ReportHistoryStatus.FAILED, ReportHistoryStatus.CANCELLED}:
        row.finished_at = now
    elif normalized_status == ReportHistoryStatus.RUNNING:
        row.last_error = None
        row.interrupt_payload = None

    if row.started_at is None and normalized_status in {
        ReportHistoryStatus.CREATED,
        ReportHistoryStatus.RUNNING,
        ReportHistoryStatus.INTERRUPTED,
        ReportHistoryStatus.COMPLETED,
    }:
        row.started_at = now

    row.updated_at = now
    row.update_by = _truncate_text(operator_name, 64)
    await session.commit()
    await session.refresh(row)
    return row


async def delete_report_history_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    thread_id: str,
) -> None:
    """删除指定用户的研报历史记录。不存在则抛 404。"""
    row = await _get_report_history_by_thread_id(session, thread_id=thread_id)
    if row is None or row.owner_user_id != owner_user_id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="研报历史不存在")
    await session.delete(row)
    await session.commit()
