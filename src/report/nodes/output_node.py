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
    print(f"✅ 生成最终报告，长度 {word_count}")

    emit_trace_event("final_report_ready", {
        "phase": "output",
        "chapter_count": chapter_count,
        "word_count": word_count,
        "quality_score": None,
        "markdown": full_report,
        "message": "最终报告已生成",
    })

    return {"final_report": full_report}
