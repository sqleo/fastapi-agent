
from typing import Any

from pydantic import BaseModel, Field

class InterruptPayload(BaseModel):
    """通用中断消息结构"""
    message: str = Field(..., description="中断消息内容，描述中断原因或需要用户提供的信息")
    data: dict[str, Any] = Field(..., description="中断消息的附加数据，包含需要传递的详细信息")
    options: list[str] = Field(default=list, description="中断选项，例如：['修改大纲', '继续生成初稿']等）")
    metadata: dict[str, Any] = Field(default=dict, description="中断消息的元信息，例如：优先级、过期时间等")

class InterruptDecision(BaseModel):
    """用户决策解析结果"""
    action: str = Field(..., description="用户选择的操作，例如：'modify_outline', 'continue_draft'等")
    payload: dict[str, Any] = Field(..., description="完整原始决策内容，包含用户选择的操作和相关数据")
    updates: dict[str, Any] = Field(default=dict, description="用户决策的更新内容，例如修改后的大纲等")


def build_payload(message: str, data: dict[str, Any], options: list[str], metadata: dict[str, Any]) -> InterruptPayload:
    """
    构建通用中断消息
    
    Args:
        message:  展示给用户的提示文字
        data:     业务数据（大纲 / 章节 / 任何内容）
        options:  允许的 action 枚举，None 表示不限
        metadata: 额外透传字段（node_name, thread_id 等）
    """
    return InterruptPayload(
        message=message,
        data=data,
        options=options or [],
        metadata=metadata,
    )


def parse_decision(raw: Any, allowed_actions: list[str] | None = None) -> InterruptDecision:  
    """
    解析用户 resume 时传入的决策
    
    raw 支持两种格式：
        str  → 直接作为 action，如 "confirm"
        dict → {"action": "revise", "updated_outline": [...], ...}

    Args:
        raw:             Command(resume=...) 里的值
        allowed_actions: 合法 action 白名单，None 表示不验证
    
    Raises:
        ValueError: action 不在白名单时
    """
    if isinstance(raw, str):
        action, payload = raw, {"action": raw}
    elif isinstance(raw, dict):
        action = raw.get("action", "confirm")
        payload = raw
    else:
        action, payload = "confirm", {"action": "confirm"}

    if allowed_actions and action not in allowed_actions:
        raise ValueError(f"非法 action: {action!r}，允许值: {allowed_actions}")

    # 把 payload 里除 action 以外的字段收集为 updates
    updates = {k: v for k, v in payload.items() if k != "action"}
    return InterruptDecision(action=action, payload=payload, updates=updates)