
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_core.prompts import ChatPromptTemplate
from report.llm import create_llm
from report.state import OutlineSection, ReportState
from report.utils.emit_trace_event import emit_trace_event

class OutlineResult(BaseModel):
    sections: list[OutlineSection] 

# Few-shot 示例
FEW_SHOT_EXAMPLE = """
示例输出：
{
  "sections": [
    {"section_id": "s1", "title": "行业背景与宏观环境", "objective": "梳理行业发展背景", "key_points": ["政策环境", "市场规模"], "target_words": 500},
    {"section_id": "s2", "title": "市场格局与竞争分析", "objective": "分析主要玩家与市场份额", "key_points": ["头部企业", "市场集中度"], "target_words": 700},
    {"section_id": "s3", "title": "技术趋势与创新方向", "objective": "识别关键技术路线", "key_points": ["核心技术", "专利布局"], "target_words": 600},
    {"section_id": "s4", "title": "结论与投资建议", "objective": "总结核心发现并给出建议", "key_points": ["核心结论", "风险提示", "投资建议"], "target_words": 500}
  ]
}
"""

chat_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", (
            "你是一个专业的报告大纲规划专家。\n"
            "请根据用户意图和调研摘要生成 4-6 个章节的报告大纲。\n"
            "每个章节包含：section_id, title, objective, key_points(2-3个), target_words。\n"
            "大纲章节应覆盖调研摘要中的核心主题，保持简洁， 返回示例格式，不要展开论述。\n\n"
            f"{FEW_SHOT_EXAMPLE}"
        )),
        ("human", "需求：{user_query}\n主题：{topic}\n范围：{scope}\n深度：{depth}\n行业：{industry}\n\n【调研摘要】\n{research_summary}"),
    ] ,
    template_format="jinja2"
)

def format_for_outline(state: ReportState) -> dict:
    chunks = state.research_chunks or []
    summary_lines = []
    for chunk in chunks:
        key = chunk.get("topic_key", "general")
        content = chunk.get("content", "")
        summary_lines.append(f"[{key}] {content}")
    research_summary = "\n".join(summary_lines) if summary_lines else "暂无调研数据"
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
    emit_trace_event("outliner_node", {"description": "生成报告大纲"})
    llm = await create_llm("llm")
    try:
        chains = RunnableLambda(format_for_outline) | chat_prompt | llm.with_structured_output(OutlineResult)
        results: OutlineResult = await chains.ainvoke(state)
        outline = [s.model_dump() for s in results.sections]
        print(f"✅ 大纲生成完成: {len(outline)} 个章节")
    except Exception as e:
        print(f"❌ 大纲生成失败: {e}")
        return {"outline": []}
    return {
        "outline": outline,
    }