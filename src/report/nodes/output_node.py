from report.state import ReportState
from report.utils.emit_trace_event import emit_trace_event


async def output_node(state: ReportState) -> dict:
    """组装最终报告"""
    section_reviews = state.section_reviews or []
    intent = state.intent

    title = f"# {intent.topic}\n\n" if intent else ""
    full_report = title + "\n\n".join(s.content for s in section_reviews)

    word_count = len(full_report)
    chapter_count = len(section_reviews)

    emit_trace_event("phase", {
        "phase": "output",
        "status": "completed",
        "message": f"报告生成完成，共 {chapter_count} 章，{word_count} 字",
        "chapter_count": chapter_count,
        "word_count": word_count,
    })

    return {"final_report": full_report}