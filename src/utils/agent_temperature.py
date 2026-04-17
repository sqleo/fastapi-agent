"""按 LangGraph ``assistant_id``（图 id）解析聊天温度，供各 Agent 路由写入 ``configurable``."""

from __future__ import annotations

import os

# 未设置对应环境变量时使用；``None`` 表示不覆盖，仍走厂商 ``extra_config`` / ``create_llm`` 默认
_BUILTIN_TEMPERATURE_BY_ASSISTANT: dict[str, float | None] = {
    "agent": None,
    "graph_service": None,
}


def resolve_llm_temperature_for_assistant(assistant_id: str) -> float | None:
    """返回本次运行应使用的温度；``None`` 表示不在此处覆盖（沿用厂商配置与 ``create_llm`` 默认链）。

    优先级：环境变量 ``LANGGRAPH_TEMPERATURE_<ASSISTANT>`` > 内置默认值 > 不覆盖。

    ``<ASSISTANT>`` 为 ``assistant_id`` 的大写，连字符替换为下划线，例如
    ``agent`` -> ``LANGGRAPH_TEMPERATURE_AGENT``。
    """
    key = f"LANGGRAPH_TEMPERATURE_{assistant_id.upper().replace('-', '_')}"
    raw = os.getenv(key)
    if raw is not None and str(raw).strip() != "":
        return float(raw)
    return _BUILTIN_TEMPERATURE_BY_ASSISTANT.get(assistant_id)
