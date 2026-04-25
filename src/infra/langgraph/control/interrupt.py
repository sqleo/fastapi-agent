"""统一的 LangGraph 中断控制与 Payload 模型。"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from pydantic import BaseModel, Field
from langchain.agents.middleware.types import wrap_model_call
from langchain_core.messages import AIMessageChunk
from langgraph.config import get_config
from langgraph.types import interrupt, Command

logger = logging.getLogger("infra.langgraph.control.interrupt")

# 每多少个 token chunk 检查一次是否需要暂停（越小越灵敏，但开销稍大）
TOKENS_PER_CHECK = int(os.getenv("PAUSE_TOKENS_PER_CHECK", "8"))
MAX_PAUSE_WAIT_SECONDS = int(os.getenv("MAX_PAUSE_WAIT_SECONDS", "300"))


class InterruptPayload(BaseModel):
    """通用中断消息结构"""
    message: str = Field(..., description="中断消息内容，描述中断原因或需要用户提供的信息")
    data: dict[str, Any] = Field(..., description="中断消息的附加数据，包含需要传递的详细信息")
    options: list[str] = Field(default_factory=list, description="中断选项，例如：['修改大纲', '继续生成初稿']等）")
    metadata: dict[str, Any] = Field(default_factory=dict, description="中断消息的元信息，例如：优先级、过期时间等")


class InterruptDecision(BaseModel):
    """用户决策解析结果"""
    action: str = Field(..., description="用户选择的操作，例如：'modify_outline', 'continue_draft'等")
    payload: dict[str, Any] = Field(..., description="完整原始决策内容，包含用户选择的操作和相关数据")
    updates: dict[str, Any] = Field(default_factory=dict, description="用户决策的更新内容，例如修改后的大纲等")


def build_payload(message: str, data: dict[str, Any], options: list[str], metadata: dict[str, Any]) -> InterruptPayload:
    """构建通用中断消息"""
    return InterruptPayload(
        message=message,
        data=data,
        options=options or [],
        metadata=metadata,
    )


def parse_decision(raw: Any, allowed_actions: list[str] | None = None) -> InterruptDecision:  
    """解析用户 resume 时传入的决策"""
    if isinstance(raw, str):
        action, payload = raw, {"action": raw}
    elif isinstance(raw, dict):
        action = raw.get("action", "confirm")
        payload = raw
    else:
        action, payload = "confirm", {"action": "confirm"}

    if allowed_actions and action not in allowed_actions:
        raise ValueError(f"非法 action: {action!r}，允许值: {allowed_actions}")

    updates = {k: v for k, v in payload.items() if k != "action"}
    return InterruptDecision(action=action, payload=payload, updates=updates)


def _extract_text(chunk: Any) -> str:
    """提取内容文本，减少对业务模块的依赖。"""
    if isinstance(chunk, AIMessageChunk) or hasattr(chunk, "content"):
        c = getattr(chunk, "content", None)
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join([str(b.get("text", "")) for b in c if isinstance(b, dict) and b.get("type") == "text"])
    return str(chunk)


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
        
        content = _extract_text(chunk)
        
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


# 每个 run 有一个独立的暂停控制器
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
