from typing import Any, Optional

from pydantic import BaseModel, Field


class OutIntent(BaseModel):
    """结构化用户意图 在 intent_node 中生成并存储在 ReportState 中"""
    topic: str = Field(..., description="报告主题：简洁明了地描述报告的核心内容，例如：2025年中国新能源汽车市场分析")
    scope: str = Field(..., description="报告范围：全国/区域/企业/技术等")
    depth: str = Field(..., description="报告深度: 行业概览/深度研究/技术拆解/数据统计")
    output_format: str = Field(..., description="输出格式: Markdown/PDF/PPT/Word")
    industry: str = Field(..., description="行业标签：例如：新能源汽车/半导体/医疗等")


class ReportState(BaseModel):
    """报告生成状态，全局状态管理器（ReportStateManager）维护该状态并在各节点间传递。"""
    user_query: str = Field(..., description="用户输入的需求")

    report_id: Optional[str] = Field(None, description="本地任务唯一 ID")
    user_id: Optional[int] = Field(None, description="用户ID")

    intent: Optional[OutIntent] = Field(None, description="结构化意图）")
    outline: Optional[list[dict[str, Any]]] = Field(None, description="大纲章节列表（outliner_node 产出）")
    draft: Optional[str] = Field(None, description="初稿（writer_node 产出）")
    final_report: Optional[str] = Field(None, description="最终报告内容")
    
    artifacts: Optional[list[dict]] = Field(default_factory=list, description="生成过程中的中间产物列表")
    token_usage: Optional[dict[str, int]] = Field(default_factory=dict, description="Token 使用统计")



class OutlineSection(BaseModel):
    """报告大纲章节结构，在 outliner_node 中生成并存储在 ReportState 中"""
    section_id: str = Field(..., description="章节ID：s1, s2, s3")
    title: str = Field(..., description="章节标题：背景与问题定义、现状分析、结论与建议")
    objective: str = Field(..., description="章节写作目标：例如：说明《2025年中国新能源汽车市场分析》的背景与研究问题")
    key_points: list[str] = Field(default_factory=list, description="章节要点列表：例如：背景现状、核心问题、研究边界")
    target_words: int = Field(default=600, ge=100, le=3000, description="章节目标字数：例如：500字，范围100-3000字")
