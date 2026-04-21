
from report.llm import create_llm
from report.state import ReportState
from report.utils.emit_trace_event import emit_trace_event
from langchain_core.prompts import ChatPromptTemplate

chat_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个专业的报告撰写专家。\n"
        "请根据大纲逐章撰写完整的 Markdown 格式报告。\n"
        "每章需要包含标题、正文、关键数据或观点。\n"
        "【重要】请充分利用下方提供的调研摘要，引用其中的数据和观点，不要凭空捏造。\n"
        "语言专业、逻辑清晰、数据翔实。"
    )),
    ("human", "用户需求：{user_query}\n意图：{intent}\n大纲：{outline}\n\n【调研摘要】\n{research_summary}\n\n请撰写完整报告："),
])


async def writer_node(state: ReportState) -> dict:
    """生成报告内容"""
    emit_trace_event("writer_node", {"description": "生成报告内容", "intent": state.intent, "outline": state.outline})
    llm = await create_llm("llm")

    # 直接拼接已在 researcher 摘要过的 chunks
    chunks = state.research_chunks or []
    research_summary = "\n".join(
        f"[{c.get('topic_key', '-')}] {c.get('content', '')}"
        for c in chunks
    ) if chunks else "暂无调研摘要"

    chain = chat_prompt | llm
    response = await chain.ainvoke({
        "user_query": state.user_query,
        "intent": str(state.intent),
        "outline": str(state.outline),
        "research_summary": research_summary,
    })
    draft = response.content
    print(f"✅ 报告撰写完成: {len(draft)} 字")
    return {
        "draft": draft,
        "final_report": draft,
    }