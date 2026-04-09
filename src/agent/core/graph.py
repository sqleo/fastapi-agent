"""LangGraph Agent：基于 LangChain ``create_agent``，模型来自数据库 LLM 全局设置.

运行需在 ``RunnableConfig.configurable`` 中传入 ``user_id``（与 FastAPI 当前用户一致）。
可选 ``enabled_tools: list[str]``：仅允许列出的工具名参与模型绑定与执行；不传则全部可用，``[]`` 则禁用所有工具。
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_config
from langgraph.store.base import BaseStore

# 中间件（已按功能拆分到 middleware/ 和 injection/）
from agent.middleware import (
    filter_tools_by_enabled_config,
    block_disabled_tool_execution,
)
from agent.injection import inject_llm_from_global_settings
from agent.memory.context_window import short_term_message_window
from agent.control.interrupt import token_level_pause_middleware
from agent.memory.langmem import get_langgraph_store
from agent.tools import ALL_AGENT_TOOLS
from utils.langgraph_sse_error_patch import apply_vendor_api_sse_patch

apply_vendor_api_sse_patch()

logger = logging.getLogger("agent.graph")

tools = ALL_AGENT_TOOLS

# 系统提示词
_AGENT_SYSTEM_PROMPT_DEFAULT = (
    "记忆类工具（manage_memory、search_memory）的返回仅供你内部使用。"
    "回复用户时不要复述、引用或翻译其中的英文句式（例如含 memory 与 UUID 的行）；"
    "用自然中文说明即可（如已记下、已更新偏好），勿向用户暴露技术细节与 id。"
)


def _load_agent_system_prompt() -> str:
    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "AGENT.md"
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            logger.info("agent system prompt: 从 %s 加载", path)
            return text
    logger.info("agent system prompt: AGENT.md 没有找到，使用默认提示词")
    return _AGENT_SYSTEM_PROMPT_DEFAULT


_AGENT_SYSTEM_PROMPT = _load_agent_system_prompt()

# 占位模型（真实 LLM 由 inject_llm_from_global_settings 中间件动态注入）
_placeholder_model = init_chat_model(
    "placeholder",
    model_provider="openai",
    base_url="https://api.openai.com/v1",
    api_key="placeholder-unused",
)


graph = create_agent(
    _placeholder_model,
    tools=tools,
    system_prompt=_AGENT_SYSTEM_PROMPT,
    store=get_langgraph_store(),           # LangGraph API 会忽略自定义 store，使用平台自带
    middleware=[
        filter_tools_by_enabled_config,
        short_term_message_window,
        token_level_pause_middleware,
        inject_llm_from_global_settings,
        block_disabled_tool_execution,
    ],
    name="Agent",
)