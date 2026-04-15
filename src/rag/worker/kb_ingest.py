"""消费 ``kb:ingest:queue``：拉取 JSON 任务并执行 ``run_kb_file_ingest_job``。

启动示例::

    REDIS_URI=redis://localhost:6379/0 uv run python -m rag.worker.kb_ingest

需已配置 MySQL（与主应用相同环境变量）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
DEAD_LETTER_KEY = "kb:ingest:dead_letter"
# BRPOP 服务端最长阻塞秒数；客户端 socket 读等待必须大于该值，否则会先触发 TimeoutError
BRPOP_BLOCK_SEC = 30
_MIN_SOCKET_TIMEOUT = float(BRPOP_BLOCK_SEC) + 15.0


def _redis_client_for_blocking_consumer(redis_url: str):
    """构造用于长阻塞 BRPOP 的客户端（修正过短的 socket_timeout / URL 里的 timeout）。"""
    import redis.asyncio as aioredis
    from redis import RedisError
    from redis.asyncio.connection import ConnectionPool, parse_url as redis_parse_url

    try:
        opts = redis_parse_url(redis_url)
    except (ValueError, RedisError) as e:
        raise RuntimeError(f"无效的 REDIS_URI: {e}") from e
    # URL 查询参数 timeout 会进入 kwargs，但 asyncio Connection 不接受该键，需映射为 socket_timeout
    if "timeout" in opts:
        t = opts.pop("timeout")
        opts.setdefault("socket_timeout", t)
    st = opts.get("socket_timeout")
    if st is not None and st < _MIN_SOCKET_TIMEOUT:
        logger.warning(
            "REDIS_URI 的 socket_timeout=%s 小于 BRPOP(%ss) 所需等待时间，已调整为 %s",
            st,
            BRPOP_BLOCK_SEC,
            _MIN_SOCKET_TIMEOUT,
        )
        opts["socket_timeout"] = _MIN_SOCKET_TIMEOUT
    opts.setdefault("decode_responses", True)
    pool = ConnectionPool(**opts)
    return aioredis.Redis(connection_pool=pool)


async def _mark_failed(kb_file_id: int, error: str) -> None:
    """将 pipeline_status 标记为 FAILED（最后兜底，避免永远 queued）。"""
    try:
        from models.KnowledgeBaseModel import (
            KbFilePipelineStatus,
            KnowledgeBaseFileModel,
        )
        from utils.sql_db import async_session

        async with async_session() as session:
            kb_file = await session.get(KnowledgeBaseFileModel, kb_file_id)
            if kb_file is not None and kb_file.pipeline_status.value in ("queued", "indexing"):
                kb_file.pipeline_status = KbFilePipelineStatus.FAILED
                kb_file.pipeline_error = error[:2000]
                await session.commit()
    except Exception:
        logger.exception("_mark_failed 写 DB 也失败了 kb_file_id=%s", kb_file_id)


async def _consume_loop(redis_url: str) -> None:
    from redis import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

    from rag.indexing.jobs import run_kb_file_ingest_job
    from rag.queue.ingest_queue import KB_INGEST_QUEUE_KEY
    from utils.sql_db import async_session

    client = _redis_client_for_blocking_consumer(redis_url)
    try:
        while True:
            try:
                item = await client.brpop(KB_INGEST_QUEUE_KEY, timeout=BRPOP_BLOCK_SEC)
            except (RedisConnectionError, RedisTimeoutError, OSError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "Redis 阻塞读失败，10s 后重连: %s: %s",
                    type(exc).__name__,
                    exc,
                )
                await asyncio.sleep(10)
                try:
                    await client.aclose()
                except Exception:
                    logger.exception("关闭旧 Redis 连接时异常（可忽略）")
                client = _redis_client_for_blocking_consumer(redis_url)
                continue
            if item is None:
                continue
            _, raw = item
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("忽略非法任务 JSON: %s", raw[:200])
                continue

            kb_file_id = int(job.get("kb_file_id", 0))
            owner_user_id = int(job.get("owner_user_id", 0))
            if not kb_file_id or not owner_user_id:
                logger.warning("忽略缺少字段的任务: %s", job)
                continue

            retry = int(job.get("retry", 0))
            try:
                async with async_session() as session:
                    await run_kb_file_ingest_job(
                        session,
                        kb_file_id=kb_file_id,
                        expected_owner_user_id=owner_user_id,
                    )
            except Exception as exc:
                logger.exception(
                    "worker 未预期异常 kb_file_id=%s retry=%s", kb_file_id, retry,
                )
                try:
                    if retry < MAX_RETRIES:
                        job["retry"] = retry + 1
                        await client.lpush(KB_INGEST_QUEUE_KEY, json.dumps(job))
                        logger.info("任务重新入队 kb_file_id=%s retry=%s", kb_file_id, retry + 1)
                    else:
                        await client.lpush(DEAD_LETTER_KEY, raw)
                        await _mark_failed(kb_file_id, f"重试 {MAX_RETRIES} 次后仍失败: {exc}")
                        logger.error("任务进入死信队列 kb_file_id=%s", kb_file_id)
                except (RedisConnectionError, RedisTimeoutError, OSError, asyncio.TimeoutError):
                    logger.exception(
                        "Redis 写入失败 kb_file_id=%s，将重连后由重试/死信逻辑再处理",
                        kb_file_id,
                    )
                    try:
                        await client.aclose()
                    except Exception:
                        pass
                    client = _redis_client_for_blocking_consumer(redis_url)
    finally:
        await client.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    redis_url = (os.getenv("REDIS_URI") or "").strip()
    if not redis_url:
        logger.error("请设置环境变量 REDIS_URI")
        sys.exit(1)
    logger.info("kb ingest worker 启动，Redis=%s", redis_url.split("@")[-1])
    asyncio.run(_consume_loop(redis_url))


if __name__ == "__main__":
    main()
