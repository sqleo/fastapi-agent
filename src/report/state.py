from typing import Any, Optional

from pydantic import BaseModel, Field


class ReportState(BaseModel):
    """报告生成状态，全局状态管理器（ReportStateManager）维护该状态并在各节点间传递。"""
    user_query: str = Field(..., description="用户输入的需求")

    report_id: Optional[str] = Field(None, description="本地任务唯一 ID")
    user_id: Optional[int] = Field(None, description="用户ID")

    intent: Optional[dict[str, Any]] = Field(None, description="结构化意图（intent_node 产出）")
    outline: Optional[list[dict[str, Any]]] = Field(None, description="大纲章节列表（outliner_node 产出）")
    draft: Optional[str] = Field(None, description="初稿（writer_node 产出）")
    final_report: Optional[str] = Field(None, description="最终报告内容")
    
    artifacts: Optional[list[dict]] = Field(default_factory=list, description="生成过程中的中间产物列表")
    token_usage: Optional[dict[str, int]] = Field(default_factory=dict, description="Token 使用统计")
