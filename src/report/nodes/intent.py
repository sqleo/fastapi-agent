
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from report.llm import create_llm
from report.state import OutIntent, ReportState
from report.utils.emit_trace_event import emit_trace_event


chat_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个专业的报告需求分析专家。请从用户输入中提取以下字段：\n"
        "1. topic: 报告主题\n"
        "2. report_type: 报告类型（竞争格局分析/市场趋势报告等）\n"
        "3. scope: 报告范围（全国/区域等）\n"
        "4. time_range: 时间范围（例如：2024年-2025年）\n"
        "5. depth: 报告深度（1-2章/3-4章/5-8章/8-12章） 默认值为 4-6章\n"
        "6. style_instruction: 写作风格 默认值为 专业咨询\n"
        "7. output_format: 输出格式 默认值为 Markdown\n"
        "8. industry: 行业标签 默认值为 未指定\n"
        "如有缺失项，根据上下文合理推断或标记为'未指定'。"
    )),
    ("human", "分析以下需求：{user_query}"),
])

async def intent_node(state: ReportState) -> dict:
    """提取用户意图节点"""
    llm = await create_llm("llm")
    try:
        emit_trace_event("intent_node", {"description": "提取用户意图", "user_query": state.user_query})
        chain = chat_prompt | llm.with_structured_output(OutIntent)
        out_intent: OutIntent = await chain.ainvoke({"user_query": state.user_query})
        print(out_intent)
    except Exception as e:
        print(f"❌ 提取意图失败: {e}")
        return {
            "intent": {},
            "stage": "intent",
        }
    print(f"✅ 成功提取意图: {out_intent.topic}\n")
    return {
        "intent": out_intent.model_dump(),
        "stage": "intent",
    }

