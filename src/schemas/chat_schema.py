"""聊天相关 Pydantic Schema（新增删除对话接口使用）。"""

from pydantic import BaseModel, Field


class DeleteChatRequest(BaseModel):
    """删除对话请求体（如果使用 POST 也可使用此模型）。"""

    thread_id: str = Field(..., description="要删除的对话 Thread ID")


class DeleteChatResponse(BaseModel):
    """删除对话成功响应。"""

    thread_id: str = Field(..., description="已删除的 Thread ID")
    message: str = Field(..., description="操作结果提示")
