"""Taskiq 任务：知识库文件解析为 parsed_md."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from llamarag.jobs import run_kb_file_parse_job
from llamarag.worker.taskiq_broker import make_parse_broker
from utils.sql_db import async_session

load_dotenv()

_redis_url = (os.getenv("REDIS_URI") or "").strip() or "redis://localhost:6379/0"
broker = make_parse_broker(_redis_url)


@broker.task
async def kb_file_parse_task(kb_file_id: int, owner_user_id: int) -> None:
    """Worker 内执行 ``run_kb_file_parse_job``。"""
    async with async_session() as session:
        await run_kb_file_parse_job(
            session,
            kb_file_id=kb_file_id,
            expected_owner_user_id=owner_user_id,
        )
