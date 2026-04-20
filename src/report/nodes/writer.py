
from pydantic import BaseModel, Field

from report.nodes.intent import OutIntent
from report.nodes.outliner import OutIntentSection
from report.utils.emit_trace_event import emit_trace_event


class WriterState(BaseModel):
    """写作节点状态"""
    intent: OutIntent = Field(..., description="结构化用户意图")
    outline: list[OutIntentSection] = Field(default_factory=list, description="报告大纲列表")
    draft: str | None = Field(None, description="报告初稿")
    final_report: str | None = Field(None, description="最终报告内容")


async def writer_node(state: WriterState) -> WriterState:
    """生成报告内容"""
    emit_trace_event("writer_node", {"description": "生成报告内容", "intent": state.intent, "outline": state.outline})
    # 这里可以调用 LLM 来生成报告内容，示例中直接返回输入作为输出
    return state