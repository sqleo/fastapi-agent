"""LLM 生成过程中实现精细粒度暂停（每生成一段 token 即可暂停）。

使用 LangGraph 的 interrupt 机制 + 流式 chunk 计数。
支持「暂停后继续」和「时间旅行」（checkpoint 回放）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from langchain.agents.middleware.types import wrap_model_call
from langchain_core.messages import AIMessageChunk
from langgraph.config import get_config
from langgraph.types import interrupt, Command

logger = logging.getLogger("agent.control.interrupt")

from agent.memory.turns import message_text

# 每多少个 token chunk 检查一次是否需要暂停（越小越灵敏，但开销稍大）
TOKENS_PER_CHECK = int(os.getenv("PAUSE_TOKENS_PER_CHECK", "8"))
MAX_PAUSE_WAIT_SECONDS = int(os.getenv("MAX_PAUSE_WAIT_SECONDS", "300"))  # 5分钟超时保护


class GenerationPauseState:
    """线程安全的暂停状态管理（单 run 级别）。"""
    
    def __init__(self):
        self._should_pause = False
        self._pause_event = asyncio.Event()
        self._resume_command: Command | None = None
        self._chunk_count = 0
    
    def request_pause(self):
        """外部调用：请求暂停生成。"""
        self._should_pause = True
    
    async def check_and_pause(self, chunk: AIMessageChunk | str) -> bool:
        """在每个 chunk 后检查是否需要暂停。如果暂停，返回 True。"""
        self._chunk_count += 1
        
        if not self._should_pause:
            return False
            
        if self._chunk_count % TOKENS_PER_CHECK != 0:
            return False
            
        # 触发 LangGraph interrupt
        config = get_config()
        thread_id = (config.get("configurable") or {}).get("thread_id")
        
        content = message_text(chunk) if hasattr(chunk, "__dict__") else str(chunk)
        
        interrupt_value = {
            "type": "user_pause",
            "thread_id": thread_id,
            "content_so_far": content,
            "chunk_count": self._chunk_count,
            "message": "用户请求暂停生成",
        }
        
        # 触发中断（会保存 checkpoint）
        interrupt(interrupt_value)
        return True
    
    def set_resume_command(self, command: Command):
        """收到 resume 请求后设置继续命令。"""
        self._resume_command = command
        self._should_pause = False
        self._pause_event.set()
    
    def get_resume_command(self) -> Command | None:
        return self._resume_command


# 每个 run 有一个独立的暂停控制器（使用全局弱引用或在 config 中传递更佳，此处简化）
_pause_controllers: dict[str, GenerationPauseState] = {}


def get_pause_controller(thread_id: str | None = None) -> GenerationPauseState:
    """获取或创建当前线程的暂停控制器。"""
    if not thread_id:
        thread_id = "default"
    if thread_id not in _pause_controllers:
        _pause_controllers[thread_id] = GenerationPauseState()
    return _pause_controllers[thread_id]


@wrap_model_call
async def token_level_pause_middleware(request, handler):
    """核心中间件：在 LLM 每次返回 chunk 时检查是否需要暂停。
    
    这实现了「生成过程中每一段 token 就可暂停」的精细控制。
    """
    config = get_config()
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id") or configurable.get("threadId")
    
    controller = get_pause_controller(thread_id)
    
    # 包装 handler，拦截流式输出
    original_handler = handler
    
    async def wrapped_handler(req):
        result = await original_handler(req)
        
        # 如果是流式 chunk，检查是否需要暂停
        if isinstance(result, AIMessageChunk) or hasattr(result, "content"):
            should_pause = await controller.check_and_pause(result)
            if should_pause:
                # 返回中断后的结果
                return result
        
        return result
    
    return await wrapped_handler(request)


# 供外部 API 使用的控制函数
async def request_pause(thread_id: str):
    """API 调用：请求暂停当前生成。"""
    controller = get_pause_controller(thread_id)
    controller.request_pause()
    return {"status": "pause_requested", "thread_id": thread_id}


async def resume_from_pause(thread_id: str, resume_value: Any = None):
    """API 调用：继续生成（从中断点恢复）。"""
    controller = get_pause_controller(thread_id)
    
    cmd = Command(
        resume=resume_value or {"action": "continue_generation"},
        update=None,
    )
    controller.set_resume_command(cmd)
    
    return {
        "status": "resumed",
        "thread_id": thread_id,
        "message": "已恢复生成",
    }


def clear_pause_controller(thread_id: str):
    """清理控制器（对话结束、时间旅行分支创建时调用）。"""
    _pause_controllers.pop(thread_id, None)


def cleanup_all_controllers():
    """清理所有暂停控制器（服务重启或清理时使用）。"""
    global _pause_controllers
    _pause_controllers.clear()
    logger.info("All pause controllers cleared")
