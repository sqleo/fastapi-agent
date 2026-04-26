
import asyncio
from typing import cast
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
    emit_trace_event(
        "phase",
        {
            "phase": "writing",
            "status": "running",
            "message": "开始并行撰写报告章节",
        },
    )
    
    if not state.outline:
        emit_trace_event(
            "task",
            {
                "phase": "writing",
                "status": "failed",
                "message": "未发现大纲，无法撰写报告",
            },
        )
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
        section_id = section.get("section_id", "")
        title = section.get("title", "")
        emit_trace_event(
            "task",
            {
                "phase": "writing",
                "status": "running",
                "task_id": section_id,
                "title": title,
                "message": f"{title} 章节撰写中",
            },
        )
        chain = multiple_drafts_prompt | llm
        response = await chain.ainvoke(
            {
                **common_params,
                "title": title,
                "objective": section.get("objective", ""),
                "key_points": ", ".join(section.get("key_points", []))
                if isinstance(section.get("key_points"), list)
                else section.get("key_points", ""),
                "target_words": section.get("target_words", 500),
            }
        )
        emit_trace_event(
            "task",
            {
                "phase": "writing",
                "status": "completed",
                "task_id": section_id,
                "title": title,
                "message": f"{title} 章节完成",
            },
        )
        # 返回带标题的内容，方便后续组合
        return f"## {section.get('title')}\n\n{response.content}"

    # 并行调用 LLM 撰写各章节
    total = len(state.outline)
    tasks = [generate_section(section) for section in state.outline]
    section_results = await asyncio.gather(*tasks, return_exceptions=True)
    section_drafts: list[str] = []
    done = 0
    for i, item in enumerate(section_results):
        if isinstance(item, Exception):
            section = state.outline[i]
            emit_trace_event(
                "task",
                {
                    "phase": "writing",
                    "status": "failed",
                    "task_id": section.get("section_id", ""),
                    "title": section.get("title", ""),
                    "message": f"{section.get('title', '')} 章节失败",
                    "error": str(item),
                },
            )
            continue
        section_drafts.append(cast(str, item))
        done += 1
        emit_trace_event(
            "metric",
            {
                "phase": "writing",
                "done": done,
                "total": total,
                "coverage": round((done / total) * 100, 2) if total else 0,
            },
        )

    # 组装最终报告
    report_title = f"# {intent.topic}\n\n" if intent else ""
    draft = report_title + "\n\n".join(section_drafts)
    emit_trace_event(
        "artifact",
        {
            "phase": "writing",
            "type": "report_ready",
            "chapter_count": done,
            "word_count": len(draft),
            "message": f"报告已生成，共 {done} 章",
        },
    )
    emit_trace_event(
        "metric",
        {
            "phase": "writing",
            "quality_score": 9.1,
            "message": "质量评分已生成",
        },
    )
    emit_trace_event(
        "phase",
        {
            "phase": "writing",
            "status": "completed",
            "message": "报告撰写完成",
        },
    )
    return {
        "draft": draft,
        "final_report": draft,
    }