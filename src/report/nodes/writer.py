
from pydantic import BaseModel, Field

from report.llm import create_llm
from report.state import ReportState
from report.utils.emit_trace_event import emit_trace_event
from langchain_core.prompts import ChatPromptTemplate

chat_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个专业的报告撰写专家。\n"
        "请根据大纲逐章撰写完整的 Markdown 格式报告。\n"
        "每章需要包含标题、正文、关键数据或观点。\n"
        "语言专业、逻辑清晰、数据翔实。"
    )),
    ("human", "用户需求：{user_query}\n意图：{intent}\n大纲：{outline}\n\n请撰写完整报告："),
])


async def writer_node(state: ReportState) -> dict:
    """生成报告内容"""
    emit_trace_event("writer_node", {"description": "生成报告内容", "intent": state.intent, "outline": state.outline})
    llm = await create_llm("llm")
    chain = chat_prompt | llm
    response = await chain.ainvoke({
        "user_query": state.user_query,
        "intent": str(state.intent),
        "outline": str(state.outline),
    })
    draft = response.content
    print(f"✅ 报告撰写完成: {len(draft)} 字")
    return {
        "draft": draft,
        "final_report": draft,
    }