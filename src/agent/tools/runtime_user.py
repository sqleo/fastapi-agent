"""从 LangGraph 运行上下文读取当前用户 id（与 FastAPI 注入的 ``configurable.user_id`` 一致）."""

from __future__ import annotations


def langgraph_runtime_user_id() -> int | None:
    """返回当前请求的归属用户 id；不在图内或缺失时返回 ``None``。"""
    try:
        from langgraph.config import get_config

        cfg = get_config() or {}
        raw = (cfg.get("configurable") or {}).get("user_id")
        if raw is None:
            return None
        return int(str(raw).strip())
    except (ValueError, TypeError):
        return None
