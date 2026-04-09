"""异步采集器：通过 SQLAlchemy ORM 将监控数据写入 PostgreSQL。

所有写操作内部捕获异常，绝不影响正常业务流程。
"""

from __future__ import annotations

import logging
import uuid as _uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from monitor.models import ChatSession, Evaluation, RequestLog
from monitor.pg import get_session_factory

logger = logging.getLogger("monitor.collector")


async def save_request_log(log: RequestLog) -> _uuid.UUID | None:
    """持久化一条 LLM 请求记录，返回 request_id。"""
    factory = await get_session_factory()
    if not factory:
        return None
    try:
        async with factory() as session:
            session.add(log)
            await session.commit()
            logger.debug("recorded request %s", log.request_id)
            return log.request_id
    except Exception:
        logger.exception("写入 request_log 失败")
        return None


async def upsert_session(
    *,
    session_id: _uuid.UUID,
    user_id: str | None = None,
    thread_id: str | None = None,
    add_tokens: int = 0,
) -> None:
    """创建或更新会话：首次 INSERT，后续累加 requests/tokens。"""
    factory = await get_session_factory()
    if not factory:
        return
    try:
        async with factory() as session:
            stmt = (
                pg_insert(ChatSession)
                .values(
                    id=session_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    total_requests=1,
                    total_tokens=add_tokens,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "last_active_at": text("now()"),
                        "total_requests": ChatSession.total_requests + 1,
                        "total_tokens": ChatSession.total_tokens + add_tokens,
                        "status": "active",
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()
            logger.debug("session %s upserted", session_id)
    except Exception:
        logger.exception("写入 session 失败")


async def save_evaluation(evaluation: Evaluation) -> None:
    """持久化一条质量评估记录。"""
    factory = await get_session_factory()
    if not factory:
        return
    try:
        async with factory() as session:
            session.add(evaluation)
            await session.commit()
            logger.debug("evaluation for %s recorded", evaluation.request_id)
    except Exception:
        logger.exception("写入 evaluation 失败")
