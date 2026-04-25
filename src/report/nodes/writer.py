
import asyncio
from report.llm import create_llm
from report.state import ReportState
from report.utils.emit_trace_event import emit_trace_event
from langchain_core.prompts import ChatPromptTemplate

multiple_drafts_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个专业的报告撰写专家。\n"
        "原始用户问题：{user_query}\n"
        "报告主题是：{topic}\n"
        "当前正在撰写 {industry} 行业报告的特定章节。\n"
        "报告总体深度要求：{depth}\n\n"
        "报告范围是：{scope}\n"
        "**格式规范** {output_format}\n"
        "【写作准则】：\n"
        "1. 严格基于提供的【调研摘要】撰写，引用数据需标注来源，不要凭空捏造。\n"
        "2. 语言专业、逻辑清晰、数据翔实。\n"
        #"3. 写作风格要求：{style_instruction}"
    )),
    ("human", (
        "【本章节撰写任务】\n"
        "章节标题：{title}\n"
        "章节目标：{objective}\n"
        "关键要点：{key_points}\n\n"
        "目标字数：{target_words} 字\n\n"
        "【调研摘要（核心素材）】\n"
        "{content}\n\n"
        "【调研摘要（核心素材）来源】\n"
        "{source}\n\n"
        "请开始撰写该章节正文："
    )),
])


async def writer_node(state: ReportState) -> dict:
    """生成报告内容 (并行撰写)"""
    emit_trace_event("writer_node", {"description": "并行生成报告内容", "intent": state.intent, "outline": state.outline})
    
    if not state.outline:
        print("⚠️ 未发现大纲，无法撰写报告")
        return {"draft": "未发现大纲", "final_report": "未发现大纲"}

    llm = await create_llm("llm")

    # 提取调研素材
    chunks = state.research_chunks or []
    content_text = "\n".join([f"[{c.get('topic_key', '-')}] {c.get('content', '')}" for c in chunks])
    source_text = "\n".join(list(set([c.get('source', '') for c in chunks if c.get('source')])))

    intent = state.intent
    common_params = {
        "user_query": state.user_query,
        "topic": intent.topic if intent else "-",
        "industry": intent.industry if intent else "-",
        "depth": intent.depth if intent else "-",
        "scope": intent.scope if intent else "-",
        "output_format": intent.output_format if intent else "Markdown",
        "content": content_text or "暂无调研摘要",
        "source": source_text or "暂无来源数据",
    }

    async def generate_section(section: dict):
        chain = multiple_drafts_prompt | llm
        response = await chain.ainvoke({
            **common_params,
            "title": section.get("title", ""),
            "objective": section.get("objective", ""),
            "key_points": ", ".join(section.get("key_points", [])) if isinstance(section.get("key_points"), list) else section.get("key_points", ""),
            "target_words": section.get("target_words", 500),
        })
        # 返回带标题的内容，方便后续组合
        return f"## {section.get('title')}\n\n{response.content}"

    # 并行调用 LLM 撰写各章节
    tasks = [generate_section(section) for section in state.outline]
    section_drafts = await asyncio.gather(*tasks)

    # 组装最终报告
    report_title = f"# {intent.topic}\n\n" if intent else ""
    draft = report_title + "\n\n".join(section_drafts)
    
    print(f"✅ 报告并行撰写完成: {len(draft)} 字")
    return {
        "draft": draft,
        "final_report": draft,
    }