"""知识库文件索引入队：LPUSH JSON 任务，由独立 worker BRPOP 消费."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

KB_INGEST_QUEUE_KEY = "kb:ingest:queue"

_pool: aioredis.ConnectionPool | None = None
_pool_url: str = ""


def _get_pool(redis_url: str) -> aioredis.ConnectionPool:
    global _pool, _pool_url
    if _pool is not None and _pool_url == redis_url:
        return _pool
    _pool = aioredis.ConnectionPool.from_url(redis_url, decode_responses=True)
    _pool_url = redis_url
    return _pool


def get_redis_client(redis_url: str) -> aioredis.Redis:
    """获取复用连接池的 Redis 客户端。"""
    return aioredis.Redis(connection_pool=_get_pool(redis_url))


def _job_payload(*, kb_file_id: int, owner_user_id: int) -> dict[str, Any]:
    return {"v": 1, "kb_file_id": int(kb_file_id), "owner_user_id": int(owner_user_id)}


async def push_kb_ingest_job(
    redis_url: str,
    *,
    kb_file_id: int,
    owner_user_id: int,
) -> None:
    """将单条入库任务写入 Redis 列表（LPUSH）。"""
    payload = json.dumps(_job_payload(kb_file_id=kb_file_id, owner_user_id=owner_user_id))
    client = get_redis_client(redis_url)
    await client.lpush(KB_INGEST_QUEUE_KEY, payload)
    logger.info(
        "kb ingest job queued kb_file_id=%s owner_user_id=%s",
        kb_file_id,
        owner_user_id,
    )


async def push_kb_ingest_jobs_batch(
    redis_url: str,
    jobs: list[dict[str, int]],
) -> None:
    """批量入队；``jobs`` 每项含 ``kb_file_id`` 与 ``owner_user_id``。"""
    if not jobs:
        return
    client = get_redis_client(redis_url)
    pipe = client.pipeline(transaction=False)
    for j in jobs:
        payload = json.dumps(_job_payload(kb_file_id=j["kb_file_id"], owner_user_id=j["owner_user_id"]))
        pipe.lpush(KB_INGEST_QUEUE_KEY, payload)
    await pipe.execute()
    logger.info("kb ingest batch queued %s jobs", len(jobs))
