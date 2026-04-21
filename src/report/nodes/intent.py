
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from report.llm import create_llm
from report.state import OutIntent, ReportState
from report.utils.emit_trace_event import emit_trace_event

chat_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个专业的报告需求分析专家。请从用户输入中提取以下字段：\n"
        "topic, scope, depth, output_format, industry。\n"
        "如有缺失项，根据上下文合理推断或标记为'未指定'。"
    )),
    ("human", "分析以下需求：{user_query}"),
])

async def intent_node(state: ReportState) -> dict:
    """提取用户意图节点"""
    llm = await create_llm("llm")
    emit_trace_event("intent_node", {"description": "提取用户意图", "user_query": state.user_query})
    chain = chat_prompt | llm.with_structured_output(OutIntent)
    out_intent: OutIntent = await chain.ainvoke({"user_query": state.user_query})

    print(f"✅ 成功提取意图: {out_intent.topic}\n")

    return {
        "intent": out_intent.model_dump(),
    }