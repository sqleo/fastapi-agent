
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from report.llm import create_llm
from report.state import OutlineSection, ReportState
from report.utils.emit_trace_event import emit_trace_event

class OutlineResult(BaseModel):
    sections: list[OutlineSection]

chat_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个专业的报告大纲规划专家。\n"
        "请根据用户意图生成 4-6 个章节的报告大纲。\n"
        "每个章节包含：section_id, title, objective, key_points, target_words。"
    )),
    ("human", "用户需求：{user_query}\n结构化意图：{intent}"),
])

async def outliner_node(state: ReportState) -> dict:
    """生成报告大纲"""
    emit_trace_event("outliner_node", {"description": "生成报告大纲"})
    llm = await create_llm("llm")
    chain = chat_prompt | llm.with_structured_output(OutlineResult)
    result: OutlineResult = await chain.ainvoke({
        "user_query": state.user_query,
        "intent": str(state.intent),
    })
    outline = [s.model_dump() for s in result.sections]
    print(f"✅ 大纲生成完成: {len(outline)} 个章节")
    return {
        "outline": outline,
    }