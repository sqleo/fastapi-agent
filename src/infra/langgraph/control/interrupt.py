"""统一的 LangGraph 中断控制与 Payload 模型。"""

from __future__ import annotations

import logging
from typing import Any
from pydantic import BaseModel, Field
from langchain.agents.middleware.types import wrap_model_call
logger = logging.getLogger("infra.langgraph.control.interrupt")


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


def normalize_interrupt_value(value: Any) -> dict[str, Any] | None:
    """将 LangGraph interrupt 的 value 规范化为前端可消费结构。"""
    if not isinstance(value, dict):
        return None

    # 兼容 build_payload 结构：{message, data, options, metadata}
    if "message" in value or "options" in value or "data" in value:
        return {
            "type": "interrupt",
            "message": value.get("message", "需要用户输入"),
            "data": value.get("data", {}),
            "options": value.get("options", []),
            "metadata": value.get("metadata", {}),
        }

    # 兼容 token 级暂停结构：{type: user_pause, ...}
    return {
        "type": "interrupt",
        "message": value.get("message", "流程已暂停，等待继续"),
        "data": value,
        "options": value.get("options", ["continue_generation"]),
        "metadata": {"interrupt_type": value.get("type")},
    }


def extract_interrupt_payload_from_state(state_snapshot: Any) -> dict[str, Any] | None:
    """从 LangGraph state snapshot 中提取中断 payload。"""
    if state_snapshot is None:
        return None

    # 优先从任务中的 interrupt value 提取
    tasks = list(getattr(state_snapshot, "tasks", []) or [])
    for task in tasks:
        for item in list(getattr(task, "interrupts", []) or []):
            payload = normalize_interrupt_value(getattr(item, "value", None))
            if payload:
                return payload

    # 兼容旧逻辑：业务层可能直接写入 values["interrupt_payload"]
    values = getattr(state_snapshot, "values", None) or {}
    raw_payload = values.get("interrupt_payload")
    if isinstance(raw_payload, dict):
        return normalize_interrupt_value(raw_payload)

    return None


@wrap_model_call
def token_level_pause_middleware(request, handler):
    """兼容占位中间件：仅保留节点 interrupt 模式，不做 token 级暂停。"""
    return handler(request)


# 供外部 API 使用的控制函数
async def request_pause(thread_id: str):
    """已停用：节点中断模式下不支持 token 级暂停。"""
    logger.warning("request_pause 已停用（thread_id=%s）", thread_id)
    return {"status": "not_supported", "thread_id": thread_id, "message": "仅支持节点中断"}


async def resume_from_pause(thread_id: str, resume_value: Any = None):
    """已停用：节点中断模式下不支持 token 级恢复。"""
    _ = resume_value
    logger.warning("resume_from_pause 已停用（thread_id=%s）", thread_id)
    return {"status": "not_supported", "thread_id": thread_id, "message": "仅支持节点中断"}


def clear_pause_controller(thread_id: str):
    """兼容 no-op：节点中断模式下无需清理 pause 控制器。"""
    _ = thread_id


def cleanup_all_controllers():
    """兼容 no-op：节点中断模式下无全局 pause 控制器。"""
