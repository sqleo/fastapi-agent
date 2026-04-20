
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from report.llm import create_llm
from report.state import ReportState
from report.utils.emit_trace_event import emit_trace_event

class OutIntent(BaseModel):
    topic: str = Field(..., description="报告主题：简洁明了地描述报告的核心内容，例如：2025年中国新能源汽车市场分析")
    scope: str = Field(..., description="报告范围：全国/区域/企业/技术等")
    depth: str = Field(..., description="报告深度: 行业概览/深度研究/技术拆解/数据统计")
    output_format: str = Field(..., description="输出格式: Markdown/PDF/PPT/Word")
    industry: str = Field(..., description="行业标签：例如：新能源汽车/半导体/医疗等")


class IntentState(BaseModel):
    """用户意图状态"""
    user_query: str = Field(..., description="用户输入的需求")
    intent: OutIntent | None = Field(None, description="结构化用户意图")



chat_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个专业的报告需求分析专家。请从用户输入中提取以下字段：\n"
        "topic, scope, depth, output_format, industry。\n"
        "如有缺失项，根据上下文合理推断或标记为'未指定'。"
    )),
    ("human", "分析以下需求：{user_query}"),
])

async def intent_node(state: ReportState) -> dict:
    llm = await create_llm("llm")
    emit_trace_event("intent_node", {"description": "提取用户意图", "user_query": state.user_query})
    """提取用户意图"""
    # 这里可以调用 LLM 来提取用户意图，示例中直接返回输入作为输出
    chain = chat_prompt | llm.with_structured_output(OutIntent)
    out_intent: OutIntent = await chain.ainvoke({"user_query": state.user_query})

    print(f"✅ 成功提取意图: {out_intent.topic}\n")

    return {
        "intent": out_intent.model_dump(),
    }