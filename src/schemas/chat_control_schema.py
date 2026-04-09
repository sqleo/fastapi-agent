"""聊天控制相关 Schema：暂停、继续、时间旅行。"""

from pydantic import BaseModel, Field
from typing import Any, Literal


class PauseRequest(BaseModel):
    """请求暂停生成。"""
    reason: str = Field(default="user_request", description="暂停原因")


class PauseResponse(BaseModel):
    """暂停成功响应。"""
    thread_id: str
    status: Literal["paused"] = "paused"
    checkpoint_id: str | None = Field(None, description="当前暂停点的 checkpoint_id（用于时间旅行）")
    message: str = "生成已暂停，可随时继续或时间旅行"


class ResumeRequest(BaseModel):
    """继续生成请求。"""
    resume_value: dict | None = Field(
        default=None,
        description="可选的 resume payload，可传递指令给中断点"
    )


class ResumeResponse(BaseModel):
    """继续生成响应。"""
    thread_id: str
    status: Literal["resumed"] = "resumed"
    message: str = "已恢复生成"


class CheckpointItem(BaseModel):
    """历史 checkpoint 信息（用于时间旅行）。"""
    checkpoint_id: str
    timestamp: str
    content_preview: str = Field(..., description="该检查点时的输出预览")
    metadata: dict[str, Any] = Field(default_factory=dict)


class HistoryResponse(BaseModel):
    """对话历史 checkpoint 列表（支持时间旅行）。"""
    thread_id: str
    checkpoints: list[CheckpointItem]
    total: int


class TimeTravelRequest(BaseModel):
    """时间旅行请求：跳转到指定历史点或创建分支。"""
    checkpoint_id: str = Field(..., description="要跳转的 checkpoint_id")
    mode: Literal["replay", "fork"] = Field(
        default="fork",
        description="replay=重放该点之后，fork=创建新分支"
    )
    new_input: str | None = Field(None, description="如果 fork，可提供新的用户输入")


class TimeTravelResponse(BaseModel):
    """时间旅行成功响应。"""
    thread_id: str
    new_thread_id: str | None = None
    checkpoint_id: str
    mode: str
    message: str
