"""知识库异步解析：Taskiq 投递（``llamarag:parse`` 队列）."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def push_kb_parse_job(
    redis_url: str,
    *,
    kb_file_id: int,
    owner_user_id: int,
) -> None:
    """投递 Taskiq 解析任务（Redis List ``llamarag:parse``）；worker：``taskiq worker llamarag.worker.taskiq_tasks:broker``。"""
    from llamarag.worker.taskiq_broker import make_parse_broker
    from llamarag.worker.taskiq_tasks import kb_file_parse_task

    broker = make_parse_broker(redis_url)
    await kb_file_parse_task.kicker().with_broker(broker).kiq(kb_file_id, owner_user_id)
    logger.info(
        "kb parse task kiq kb_file_id=%s owner_user_id=%s",
        kb_file_id,
        owner_user_id,
    )


async def push_kb_index_job(
    redis_url: str,
    *,
    kb_id: int,
    file_id: int,
    owner_user_id: int,
) -> None:
    """投递 Taskiq 入库任务（与解析任务共用 ``llamarag:parse`` 队列与同一 broker）。"""
    from llamarag.worker.taskiq_broker import make_parse_broker
    from llamarag.worker.taskiq_tasks import kb_file_index_task

    broker = make_parse_broker(redis_url)
    await kb_file_index_task.kicker().with_broker(broker).kiq(kb_id, file_id, owner_user_id)
    logger.info(
        "kb index task kiq kb_id=%s file_id=%s owner_user_id=%s",
        kb_id,
        file_id,
        owner_user_id,
    )
