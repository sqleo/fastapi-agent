
import logging
from collections import defaultdict

from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from report.llm import create_llm
from report.state import OutlineSection, ReportState
from report.utils.emit_trace_event import emit_trace_event

logger = logging.getLogger(__name__)
class OutlineResult(BaseModel):
    sections: list[OutlineSection] 
    
# Few-shot 示例
FEW_SHOT_EXAMPLE = """
示例输出：
{
  "sections": [
    {"section_id": "s1", "title": "行业背景与宏观环境", "objective": "梳理行业发展背景", "key_points": ["政策环境", "市场规模"], "evidence_keys": ["market_size", "policy"], "target_words": 500},
    {"section_id": "s2", "title": "市场格局与竞争分析", "objective": "分析主要玩家与市场份额", "key_points": ["头部企业", "市场集中度"], "evidence_keys": ["competition"], "target_words": 700},
    {"section_id": "s3", "title": "技术趋势与创新方向", "objective": "识别关键技术路线", "key_points": ["核心技术", "专利布局"], "evidence_keys": ["technology"], "target_words": 600},
    {"section_id": "s4", "title": "结论与投资建议", "objective": "总结核心发现并给出建议", "key_points": ["核心结论", "风险提示", "投资建议"], "evidence_keys": ["market_size", "policy", "competition", "technology"], "target_words": 500}
  ]
}
"""

chat_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", (
            "你是一个专业的报告大纲规划专家。\n"
            "请根据用户意图和调研摘要生成 {depth} 的报告大纲。\n"
            "每个章节包含：section_id, title, objective, key_points(2-3个), evidence_keys, target_words。\n"
            "大纲章节应覆盖调研摘要中的核心主题，保持简洁， 返回示例格式，不要展开论述。\n\n"
            f"{FEW_SHOT_EXAMPLE}"
        )),
        ("human", (
            "需求：{user_query}\n"
            "主题：{topic}\n"
            "范围：{scope}\n"
            "行业：{industry}\n\n"
            "【调研摘要（按主题分组，作为大纲拟定的核心依据）】\n"
            "{research_summary}\n"
        )),
    ],
    template_format="jinja2"
)

def format_for_outline(state: ReportState) -> dict:
    chunks = state.research_chunks or []
    grouped: dict[str, list] = defaultdict(list)
    for c in chunks:
        grouped[c.topic_key].append(c)
    research_summary_parts: list[str] = []
    for key, items in grouped.items():
        summaries = "\n".join(
            f"  [{i+1}] ({c.source_type}, 可信度 {c.confidence or '-'}) {c.content}"
            for i, c in enumerate(items[:3])
        )
        research_summary_parts.append(f"▸ [{key}]\n{summaries}")
    research_summary = "\n\n".join(research_summary_parts) if research_summary_parts else "暂无调研摘要，请根据主题合理推断章节结构"

    return {
        "user_query": state.user_query,
        "topic": state.intent.topic if state.intent else "-",
        "scope": state.intent.scope if state.intent else "-",
        "depth": state.intent.depth if state.intent else "-",
        "industry": state.intent.industry if state.intent else "-",
        "research_summary": research_summary,
    }


async def outliner_node(state: ReportState) -> dict:
    """生成报告大纲"""
    emit_trace_event(
        "stage",
        {
            "phase": "outline",
            "status": "running",
            "message": "正在生成报告大纲",
        },
    )
    try:
        llm = await create_llm("llm")
        chains = RunnableLambda(format_for_outline) | chat_prompt | llm.with_structured_output(OutlineResult)
        results: OutlineResult = await chains.ainvoke(state)
        print(f"✅ 生成报告大纲{ results}")

        emit_trace_event(
            "outline_ready",
            {
                "phase": "outline",
                "chapter_count": len(results.sections),
                "outline": [section.model_dump() for section in results.sections],
                "message": "报告大纲已生成，等待审核",
            },
        )
    except Exception as e:
        raise
    return {
        "outline": results.sections,
    }
