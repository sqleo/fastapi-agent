"""仅裁剪进模型的对话轮数，不替代 LangMem 的存取逻辑."""

from __future__ import annotations

import os

from langchain.agents.middleware.types import wrap_model_call

from infra.memory.turns import take_last_turns

MEMORY_SHORT_TERM_TURNS = int(os.getenv("MEMORY_SHORT_TERM_TURNS", "10"))


@wrap_model_call
async def short_term_message_window(request, handler):
    """保留最近 N 轮再调用模型（与 checkpoint 全量历史无关）."""
    n = MEMORY_SHORT_TERM_TURNS
    if n <= 0:
        return await handler(request)
    trimmed = take_last_turns(list(request.messages or []), max_turns=n)
    return await handler(request.override(messages=trimmed))
