import asyncio
import logging
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from report.llm import create_llm
from report.state import ReportState, SectionReview
from report.utils.emit_trace_event import emit_trace_event

logger = logging.getLogger(__name__)

MAX_REVIEW_ROUNDS = 3
PASS_SCORE = 8
SECTION_PASS_SCORE = 7


class SectionScoreOutput(BaseModel):
    score: int = Field(ge=1, le=10, description="章节质量评分 1-10")
    issues: list[str] = Field(default_factory=list, description="具体问题，精确到段落")
    suggestions: list[str] = Field(default_factory=list, description="可操作的改进建议")


_section_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是报告质量审核专家，对单个章节进行评分。\n"
        "评分维度（各2分共10分）：内容完整性、数据准确性、逻辑结构、语言质量、洞察深度。\n"
        "问题和建议必须具体，不得使用'加强分析'等空话。"
    )),
    ("human", (
        "报告主题：{topic}\n"
        "章节目标：{objective}\n"
        "关键要点：{key_points}\n\n"
        "章节内容：\n{content}\n\n"
        "调研数据摘要（用于核实）：\n{research_summary}"
    )),
])


async def _review_section(
    section: SectionReview,
    outline_section,
    research_summary: str,
    topic: str,
    llm,
) -> SectionReview:
    chain = _section_prompt | llm.with_structured_output(SectionScoreOutput)
    result: SectionScoreOutput = await chain.ainvoke({
        "topic": topic,
        "objective": outline_section.objective if outline_section else "-",
        "key_points": ", ".join(outline_section.key_points) if outline_section else "-",
        "content": section.content,
        "research_summary": research_summary,
    })

    section.score = result.score
    section.issues = result.issues
    section.suggestions = result.suggestions

    emit_trace_event("section_update", {
        "phase": "writing",
        "section_id": section.section_id,
        "status": "reviewed",
        "score": section.score,
        "issues": section.issues,
        "suggestions": section.suggestions,
        "message": f"章节 {section.section_id} 审核完成，评分 {section.score}/10",
    })
    return section


async def reviewer_node(state: ReportState) -> dict:
    """质量审核节点 — 并行审核所有章节，全部完成后计算整体分"""
    section_reviews = state.section_reviews or []
    review_count = state.review_count or 0
    current_round = review_count + 1
    topic = state.intent.topic if state.intent else state.user_query

    emit_trace_event("stage", {
        "phase": "review",
        "status": "running",
        "message": "正在执行质量审核",
        "round": current_round,
        "max_rounds": MAX_REVIEW_ROUNDS,
    })

    if not section_reviews:
        raise ValueError("section_reviews 为空，无法审核")

    # 第二轮起只审需要重写的章节
    last_review = next(
        (a for a in reversed(state.artifacts or []) if a.get("type") == "review"), None
    )
    sections_to_review = section_reviews
    if last_review:
        revise_ids = set(last_review.get("sections_to_revise", []))
        if revise_ids:
            sections_to_review = [s for s in section_reviews if s.section_id in revise_ids]

    outline_map = {s.section_id: s for s in (state.outline or [])}
    chunks = state.research_chunks or []
    research_summary = "\n".join([f"[{c.topic_key}] {c.content}" for c in chunks])[:1500]
    llm = await create_llm("llm", max_tokens=2048)

    # 并行审核
    tasks = [
        _review_section(s, outline_map.get(s.section_id), research_summary, topic, llm)
        for s in sections_to_review
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("章节 %s 审核失败: %s", sections_to_review[i].section_id, result)

    # 全部完成后计算整体分
    scored = [(s, s.score) for s in section_reviews if isinstance(s.score, int) and s.score > 0]
    overall_score = round(sum(s for _, s in scored) / len(scored), 1) if scored else 0
    passed = overall_score >= PASS_SCORE
    sections_to_revise = [s.section_id for s, score in scored if score < SECTION_PASS_SCORE]
    
    # 如果整体没通过，但没有任何单章触发重写阈值，则找出得分最低的章节进行重写
    if not passed and not sections_to_revise and scored:
        lowest_score = min(score for _, score in scored)
        sections_to_revise = [s.section_id for s, score in scored if score == lowest_score]


    logger.info("第%d轮 | 整体分: %d/10 | %s | 需重写: %s",
                current_round, overall_score, "✅通过" if passed else "❌未通过", sections_to_revise)

    emit_trace_event("review_update", {
        "phase": "writing",
        "round": current_round,
        "passed": passed,
        "overall_score": overall_score,
        "sections_to_revise": sections_to_revise,
        "message": f"整体评分 {overall_score}/10",
    })

    return {
        "review_count": current_round,
        "section_reviews": section_reviews,
        "artifacts": (state.artifacts or []) + [{
            "type": "review",
            "round": current_round,
            "overall_score": overall_score,
            "passed": passed,
            "sections_to_revise": sections_to_revise,
        }],
    }


def review_router(state: ReportState) -> Literal["writer", "end"]:
    artifacts = state.artifacts or []
    review_count = state.review_count or 0

    last_review = next(
        (a for a in reversed(artifacts) if a.get("type") == "review"), None
    )

    if last_review is None:
        return "end"
    if last_review.get("passed", False):
        return "end"
    if review_count >= MAX_REVIEW_ROUNDS:
        logger.warning("已达最大轮次 %d，强制放行", MAX_REVIEW_ROUNDS)
        return "end"
    return "writer"
