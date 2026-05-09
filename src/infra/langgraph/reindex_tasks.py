"""LangMem 多租户嵌入迁移任务（Taskiq）。

触发：``llm_global_setting`` 中嵌入相关字段变更 → controller +1 version、置 migrating
→ 调 ``enqueue_reindex`` 把任务入队（独立 Taskiq Redis broker，队列
``langmem:reindex``，与 LlamaRAG ``llamarag:parse`` 队列隔离）。

任务流程：
1. 创建新 schema（已由 store factory 在首次访问时建好）。
2. 分页扫旧 schema 的 ``store`` 表全部记录 → 通过 ``aput`` 写入新 schema
   （新 schema 的 PostgresStore 用新版 embedder，自动算新维度向量）。
3. 全量写入完成后：
   - controller 把 ``embedding_status`` 置为 ``active``
   - 旧 schema ``DROP SCHEMA CASCADE`` 释放空间
4. 失败 → 保持 migrating，DualWriteStore 持续双写，等下次手动重试。

Worker 启动：::

    REDIS_URI=redis://localhost:6379/1 \\
    uv run taskiq worker infra.langgraph.reindex_tasks:broker
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from infra.langgraph.tenant_store import (
    drop_schema,
    evict_store,
    invalidate_user_config_cache,
    schema_name,
)
from models.LlmGlobalSettingModel import (
    EMBEDDING_STATUS_ACTIVE,
    EMBEDDING_STATUS_MIGRATING,
    LlmGlobalSettingModel,
)

logger = logging.getLogger("infra.langgraph.reindex_tasks")

LANGMEM_REINDEX_QUEUE = "langmem:reindex"


@lru_cache(maxsize=4)
def make_reindex_broker(redis_url: str) -> ListQueueBroker:
    """按 ``redis_url`` 复用 broker（与 LlamaRAG ``llamarag:parse`` 队列隔离）。"""
    backend = RedisAsyncResultBackend(redis_url=redis_url, result_ex_time=3600)
    return ListQueueBroker(
        url=redis_url,
        queue_name=LANGMEM_REINDEX_QUEUE,
        max_connection_pool_size=8,
    ).with_result_backend(backend)


# Worker 入口：``taskiq worker infra.langgraph.reindex_tasks:broker``
_redis_url = (os.getenv("REDIS_URI") or "").strip()
broker = make_reindex_broker(_redis_url) if _redis_url else None  # type: ignore[assignment]


# ──────────────────────────────────────────────────────────────────────────────
# 实际执行：reindex_user_memory
# ──────────────────────────────────────────────────────────────────────────────


def _postgres_uri() -> str:
    return (os.getenv("LANGMEM_POSTGRES_URI") or os.getenv("POSTGRES_URI") or "").strip()


def _read_old_entries(old_schema: str) -> list[tuple[str, str, dict]]:
    """从旧 schema 的 ``store`` 表读全部记录。

    返回 ``[(prefix_text, key, value_json), ...]``；pgvector 列直接弃用——
    新 schema 重新算（可能维度都不一样）。
    """
    import psycopg
    from psycopg.rows import dict_row

    uri = _postgres_uri()
    rows: list[tuple[str, str, dict]] = []
    with psycopg.connect(uri, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = 'store'
                """,
                (old_schema,),
            )
            if cur.fetchone() is None:
                return []
            cur.execute(f'SELECT prefix, key, value FROM "{old_schema}".store')
            for r in cur.fetchall():
                rows.append((r["prefix"], r["key"], r["value"]))
    return rows


def _prefix_text_to_namespace(prefix_text: str) -> tuple[str, ...]:
    """``langgraph.store.postgres`` 内部用 '\\x1f' 作为 namespace 分隔符（见 base.py 的 ``_namespace_to_text``）。"""
    if not prefix_text:
        return ()
    sep = "\x1f"
    return tuple(prefix_text.split(sep))


async def _finalize_active(*, user_id: int, drop_old: bool, old_version: int) -> None:
    """把 status 切回 active，可选 DROP 旧 schema。"""
    from sqlalchemy import select

    from utils.sql_db import async_session

    async with async_session() as session:
        stmt = select(LlmGlobalSettingModel).where(
            LlmGlobalSettingModel.owner_user_id == int(user_id)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return
        if row.embedding_status == EMBEDDING_STATUS_MIGRATING:
            row.embedding_status = EMBEDDING_STATUS_ACTIVE
            session.add(row)
            await session.commit()

    invalidate_user_config_cache(user_id)

    if drop_old:
        try:
            evict_store(user_id, old_version)
            drop_schema(_postgres_uri(), schema_name(user_id, old_version))
        except Exception:
            logger.warning(
                "drop old schema 失败 user_id=%s old_version=%s",
                user_id,
                old_version,
                exc_info=True,
            )


async def _run_reindex(*, user_id: int, old_version: int, new_version: int) -> dict[str, Any]:
    from infra.langgraph.tenant_store import (
        _get_or_build_single_store,
        _load_user_mem_config,
    )

    old_schema = schema_name(user_id, old_version)
    new_schema = schema_name(user_id, new_version)

    logger.info("reindex start user_id=%s %s -> %s", user_id, old_schema, new_schema)

    rows = _read_old_entries(old_schema)
    total = len(rows)
    logger.info("reindex user_id=%s 旧数据条数=%d", user_id, total)

    invalidate_user_config_cache(user_id)
    cfg = await _load_user_mem_config(user_id)
    if cfg.dim is None:
        logger.warning("reindex user_id=%s: 嵌入已清空，跳过 reindex", user_id)
        await _finalize_active(user_id=user_id, drop_old=True, old_version=old_version)
        return {"user_id": user_id, "skipped": True, "total": 0, "done": 0}

    new_store = _get_or_build_single_store(user_id, new_version, dim=cfg.dim)

    done = 0
    failed = 0
    for prefix_text, key, value in rows:
        ns = _prefix_text_to_namespace(prefix_text)
        try:
            await new_store.aput(ns, key, value)
            done += 1
        except Exception:
            failed += 1
            logger.warning(
                "reindex put failed user_id=%s ns=%s key=%s",
                user_id,
                ns,
                key,
                exc_info=True,
            )

    if failed > 0:
        logger.error(
            "reindex user_id=%s 部分失败 done=%d failed=%d，保持 migrating，等待重试",
            user_id,
            done,
            failed,
        )
        return {"user_id": user_id, "total": total, "done": done, "failed": failed, "switched": False}

    await _finalize_active(user_id=user_id, drop_old=True, old_version=old_version)
    logger.info(
        "reindex done user_id=%s total=%d done=%d 旧 schema 已 DROP",
        user_id,
        total,
        done,
    )
    return {"user_id": user_id, "total": total, "done": done, "failed": 0, "switched": True}


# ──────────────────────────────────────────────────────────────────────────────
# Taskiq 任务定义（Worker 进程加载本模块时挂到 broker）
# ──────────────────────────────────────────────────────────────────────────────

if broker is not None:

    @broker.task
    async def reindex_user_memory(user_id: int, old_version: int, new_version: int) -> dict[str, Any]:
        return await _run_reindex(
            user_id=int(user_id),
            old_version=int(old_version),
            new_version=int(new_version),
        )

else:  # 仅声明，避免 import 时报错；未配 REDIS_URI 时无法入队
    reindex_user_memory = None  # type: ignore[assignment]


async def enqueue_reindex(*, user_id: int, old_version: int, new_version: int) -> str:
    """从 FastAPI 进程入队 reindex 任务，返回 task id。"""
    redis_url = (os.getenv("REDIS_URI") or "").strip()
    if not redis_url:
        raise RuntimeError(
            "REDIS_URI 未配置：reindex 任务需要 Taskiq Redis broker（队列 langmem:reindex）",
        )
    if reindex_user_memory is None:
        raise RuntimeError("reindex_user_memory 未注册（broker 初始化失败？）")

    sender = make_reindex_broker(redis_url)
    task = await reindex_user_memory.kicker().with_broker(sender).kiq(
        int(user_id), int(old_version), int(new_version)
    )
    return task.task_id
