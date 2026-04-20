
from pydantic import BaseModel, Field

from report.nodes.intent import OutIntent
from report.utils.emit_trace_event import emit_trace_event


class OutIntentSection(BaseModel):
   section_id: str = Field(..., description="章节ID")
   title: str = Field(..., description="章节标题")
   objective: str = Field(..., description="章节写作目标")
   key_points: list[str] = Field(default_factory=list, description="章节要点列表")
   target_words: int = Field(default=600, ge=100, le=3000, description="章节目标字数")


class OutlinerState(BaseModel):
    """报告大纲状态"""
    intent: OutIntent = Field(..., description="结构化用户意图")
    outline: list[OutIntentSection] = Field(default_factory=list, description="报告大纲列表")

async def outliner_node(state: OutlinerState) -> OutlinerState:
    """生成报告大纲"""
    emit_trace_event("outliner_node", {"description": "生成报告大纲", "intent": state.intent})
    topic = state.intent.topic # 从用户意图中获取报告主题
    outline = [
        OutIntentSection(
            section_id="s1",
            title="背景与问题定义",
            objective=f"说明《{topic}》的背景与研究问题",
            key_points=["背景现状", "核心问题", "研究边界"],
            target_words=500,
        ),
        OutIntentSection(
            section_id="s2",
            title="现状分析",
            objective=f"分析《{topic}》的当前格局",
            key_points=["关键数据", "主要参与者", "趋势判断"],
            target_words=700,
        ),
        OutIntentSection(
            section_id="s3",
            title="结论与建议",
            objective=f"给出《{topic}》的结论与行动建议",
            key_points=["核心结论", "风险提示", "落地建议"],
            target_words=500,
        ),
    ]
    return OutlinerState(intent=state.intent, outline=outline)