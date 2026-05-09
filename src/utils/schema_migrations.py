"""轻量级 SQLModel 启动迁移：补齐已建表上的新列。

用途：当 ``LlmGlobalSettingModel`` 这类表加新字段时，``SQLModel.metadata.create_all``
不会自动 ``ALTER TABLE``。这里做幂等的"列不存在则添加"。

仅用于开发/测试；生产环境请用 Alembic 等正式迁移工具。
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("utils.schema_migrations")


async def _column_exists(conn, *, table: str, column: str) -> bool:
    sql = text(
        """
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = :t
          AND COLUMN_NAME = :c
        """
    )
    res = await conn.execute(sql, {"t": table, "c": column})
    return int(res.scalar_one()) > 0


async def _ensure_column(conn, *, table: str, column: str, ddl: str) -> None:
    if await _column_exists(conn, table=table, column=column):
        return
    sql = text(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    await conn.execute(sql)
    logger.info("schema_migrations: 已添加列 %s.%s", table, column)


async def ensure_llm_global_setting_columns(engine: AsyncEngine) -> None:
    """补齐 ``llm_global_setting`` 表上多租户嵌入相关的 3 列。"""
    table = "llm_global_setting"
    columns = [
        ("embedding_dim", "embedding_dim INT NULL COMMENT '当前嵌入维度（pgvector 列宽）'"),
        (
            "embedding_version",
            "embedding_version INT NOT NULL DEFAULT 1 COMMENT '嵌入配置版本号'",
        ),
        (
            "embedding_status",
            "embedding_status VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT '嵌入索引状态'",
        ),
    ]
    async with engine.begin() as conn:
        for col, ddl in columns:
            await _ensure_column(conn, table=table, column=col, ddl=ddl)

        # 数据回填：未配置嵌入的用户应为 deprecated
        await conn.execute(
            text(
                f"""
                UPDATE {table}
                SET embedding_status = 'deprecated'
                WHERE (embedding_vendor_id IS NULL OR embedding_model IS NULL OR embedding_model = '')
                  AND embedding_status = 'active'
                """
            )
        )
