from typing import Any, Optional

from pydantic import BaseModel, Field


class OutIntent(BaseModel):
    """结构化用户意图 在 intent_node 中生成并存储在 ReportState 中"""
    topic: str = Field(..., description="报告主题：简洁明了地描述报告的核心内容，例如：2025年中国新能源汽车市场分析")
    report_type: str|None = Field(default=None, description="报告类型：竞争格局分析/市场趋势报告/技术发展趋势报告/项目可行性研究报告/供应链梳理等")
    scope: str|None = Field(default=None, description="报告范围：全国/区域/企业/技术等")
    time_range: str|None = Field(default=None, description="报告时间范围：例如：2024年/2024-2025年/2025年及以后")
    # 高级参数
    depth: str|None = Field(default=None, description="报告深度: 1-2章/3-4章/5-8章/8-12章")
    style_instruction: str|None = Field(default=None, description="写作风格：专业咨询/学术研究/简洁专业/数据翔实")
    output_format: str|None = Field(default=None, description="输出格式: Markdown/PDF/PPT/Word")
    industry: str|None = Field(default=None, description="行业标签：例如：新能源汽车/半导体/医疗等")


class OutlineSection(BaseModel):
    """报告大纲章节结构，在 outliner_node 中生成并存储在 ReportState 中"""
    section_id: str = Field(..., description="章节ID：s1, s2, s3")
    title: str = Field(..., description="章节标题：背景与问题定义、现状分析、结论与建议")
    objective: str = Field(..., description="章节写作目标：例如：说明《2025年中国新能源汽车市场分析》的背景与研究问题")
    key_points: list[str] = Field(default_factory=list, description="章节要点列表：例如：背景现状、核心问题、研究边界")
    evidence_keys: Optional[list[str]] = Field(default_factory=list, description="关联的调研主题key列表，例如：market_size / policy / competition / technology")
    target_words: int = Field(default=600, ge=100, le=3000, description="章节目标字数：例如：500字，范围100-3000字")

class PlannerTask(BaseModel):
    """"任务规划结构，在 planner_node 中生成并存储在 ReportState 中"""
    task_id: str = Field(..., description="任务唯一标识: t1, t2, ...")
    topic_key: str = Field(..., description="调研主题标识，例如: market_size / policy / competition / technology")
    query: str = Field(..., description="任务描述，明确要做什么:搜索/检索 query")
    tool: str = Field(..., description="数据来源: kb_search / web_search / data_query")
    priority: int = Field(default=1, description="优先级 1-3")

class ResultTaskChunk(BaseModel):
    """调研结果片段（结构化证据对象）"""
    task_id: str = Field(..., description="来源任务ID: t1, t2, ...")
    topic_key: str = Field(..., description="所属调研主题标识")
    content: str = Field(..., description="检索到的内容摘要")
    source: Optional[str] = Field(None, description="信息来源URL或文档名")
    # 结构化证据字段
    title: Optional[str] = Field(None, description="来源标题，如网页/文档标题")
    url: Optional[str] = Field(None, description="来源URL链接")
    source_type: str = Field(default="web", description="来源类型: kb/web/api/upload")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="可信度 0-1")
    published_at: Optional[str] = Field(None, description="发布/更新时间，如 2025-Q1")
    raw_query: Optional[str] = Field(None, description="原始查询语句")

class SectionReview(BaseModel):
    """初稿片段"""
    section_id: str = Field(..., description="章节ID: s1, s2, ...")
    content: str = Field(..., description="章节内容")
    score: Optional[int] = Field(default=0, ge=0, le=10, description="章节质量评分")
    issues: Optional[list[str]] = Field(default_factory=list, description="具体问题")
    suggestions: Optional[list[str]] = Field(default_factory=list, description="可操作的改进建议")

class ReviewDecision(BaseModel):
    overall_score: float = Field(..., ge=1, le=10, description="整体评分，由各章节分数均值计算得出")
    passed: bool = Field(..., description="是否通过审核，overall_score >= 8 时为 True")
    summary: str = Field(..., description="2-3句总体评价")
    section_reviews: list[SectionReview] = Field(default_factory=list, description="每个章节的详细审核反馈")
    sections_to_revise: list[str] = Field(default_factory=list, description="需要重写的章节ID列表，score < 7 的章节")
    global_suggestions: list[str] = Field(default_factory=list, description="适用于全文的改进建议")

class ReportState(BaseModel):
    """报告生成状态，全局状态管理器（ReportStateManager）维护该状态并在各节点间传递。"""
    # 输入
    user_query: str = Field(..., description="用户输入的需求")
    # 身份与追踪
    report_id: Optional[str] = Field(default=None, description="本地任务唯一 ID")
    user_id: Optional[int] = Field(default=None, description="用户ID")
    # Phase 1 产出
    intent: Optional[OutIntent] = Field(default=None, description="结构化意图）")
    outline: Optional[list[OutlineSection]] = Field(default=None, description="大纲章节列表（outliner_node 产出）")
    final_report: Optional[str] = Field(default=None, description="最终报告内容")
    
    # Phase 2 新增：调研
    research_plan: list[PlannerTask] = Field(default_factory=list, description="调研任务列表")
    research_chunks: list[ResultTaskChunk] = Field(default_factory=list, description="调研结果片段")
    evidence_map: dict[str, list[str]] = Field(default_factory=dict, description="topic_key → 引用来源列表")

    # Phase 3 新增：审阅与修订
    section_reviews: list[SectionReview] = Field(default_factory=list, description="章节审核结果")
    human_decision: Optional[dict[str, Any]] = Field(default=None, description="人工审核决策内容")
    review_count: int = Field(default=0, description="审核轮次")
    outline_approved: bool = Field(default=False, description="大纲是否通过审核")
    # 附属
    artifacts: Optional[list[dict]] = Field(default_factory=list, description="生成过程中的中间产物列表")
    token_usage: Optional[dict[str, int]] = Field(default_factory=dict, description="Token 使用统计")