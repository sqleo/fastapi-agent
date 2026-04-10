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


async def _mark_failed(kb_file_id: int, error: str) -> None:
    """将 pipeline_status 标记为 FAILED（最后兜底，避免永远 queued）。"""
    try:
        from utils.sql_db import async_session
        from models.KnowledgeBaseModel import KbFilePipelineStatus, KnowledgeBaseFileModel

        async with async_session() as session:
            kb_file = await session.get(KnowledgeBaseFileModel, kb_file_id)
            if kb_file is not None and kb_file.pipeline_status.value in ("queued", "indexing"):
                kb_file.pipeline_status = KbFilePipelineStatus.FAILED
                kb_file.pipeline_error = error[:2000]
                await session.commit()
    except Exception:
        logger.exception("_mark_failed 写 DB 也失败了 kb_file_id=%s", kb_file_id)


async def _consume_loop(redis_url: str) -> None:
    import redis.asyncio as aioredis

    from utils.sql_db import async_session
    from rag.indexing.jobs import run_kb_file_ingest_job
    from rag.queue.ingest_queue import KB_INGEST_QUEUE_KEY

    client = aioredis.from_url(redis_url, decode_responses=True)
    try:
        while True:
            item = await client.brpop(KB_INGEST_QUEUE_KEY, timeout=30)
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
                if retry < MAX_RETRIES:
                    job["retry"] = retry + 1
                    await client.lpush(KB_INGEST_QUEUE_KEY, json.dumps(job))
                    logger.info("任务重新入队 kb_file_id=%s retry=%s", kb_file_id, retry + 1)
                else:
                    await client.lpush(DEAD_LETTER_KEY, raw)
                    await _mark_failed(kb_file_id, f"重试 {MAX_RETRIES} 次后仍失败: {exc}")
                    logger.error("任务进入死信队列 kb_file_id=%s", kb_file_id)
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
