"""研报工作台 DTO 映射."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from models.ReportHistoryModel import ReportHistoryModel, ReportHistoryStatus
from schemas.report_schema import (
    FinalReportDto,
    ReportArtifactDto,
    ReportHistoryDetail,
    ReportHistoryItem,
    ReportIntentDto,
    ReportInterruptDto,
    ReportMetricsDto,
    ReportOutlineSectionDto,
    ReportReviewDto,
    ReportSectionDto,
    ReportSourceDto,
)
from utils.json import safe_serialize

_MISSING_SENTINELS = {"", "-", "未指定", "待识别", "unknown", "None"}


def _safe_dict(value: Any) -> dict[str, Any]:
    serialized = safe_serialize(value)
    return serialized if isinstance(serialized, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    serialized = safe_serialize(value)
    return serialized if isinstance(serialized, list) else []


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def infer_workspace_stage(current_node: str | None, status: str | ReportHistoryStatus | None) -> str:
    node = (current_node or "").strip()
    status_value = status.value if isinstance(status, ReportHistoryStatus) else str(status or "")
    if node == "human_review_intent" or "intent" in node:
        return "intent"
    if "planner" in node or "research" in node:
        return "research"
    if node == "human_review" or "outline" in node:
        return "outline"
    if "writer" in node or "review" in node or "illustrator" in node:
        return "writing"
    if status_value == ReportHistoryStatus.COMPLETED.value:
        return "final"
    return "intent"


def _to_ui_status(status: str | ReportHistoryStatus | None, stage: str) -> str:
    status_value = status.value if isinstance(status, ReportHistoryStatus) else str(status or "")
    if status_value == ReportHistoryStatus.COMPLETED.value:
        return "completed"
    if status_value == ReportHistoryStatus.FAILED.value:
        return "failed"
    if status_value == ReportHistoryStatus.CANCELLED.value:
        return "cancelled"
    if status_value == ReportHistoryStatus.CREATED.value:
        return "draft"
    if status_value == ReportHistoryStatus.INTERRUPTED.value:
        return "waiting_review"
    if stage in {"intent", "outline"} and status_value == ReportHistoryStatus.RUNNING.value:
        return "running"
    return "running"


def _progress_text(stage: str, status: str, row: ReportHistoryModel) -> str | None:
    if status == "waiting_review":
        return "等待人工审核"
    if status == "completed":
        return "报告已生成完成"
    if status == "failed":
        return "生成失败"
    return {
        "intent": "正在识别研究意图",
        "research": "正在调研与收集来源",
        "outline": "正在生成或审核大纲",
        "writing": "正在并行撰写报告",
        "final": "正在整理最终报告",
    }.get(stage, row.summary)


def to_history_list_item(row: ReportHistoryModel) -> ReportHistoryItem:
    stage = infer_workspace_stage(row.current_node, row.status)
    status = _to_ui_status(row.status, stage)
    return ReportHistoryItem(
        thread_id=row.thread_id,
        title=_first_nonempty(row.topic, row.user_query, "未命名研报") or "未命名研报",
        subtitle=row.report_type,
        status=status,
        stage=stage,
        updated_at=row.updated_at,
        created_at=row.created_at,
        summary=row.summary,
        can_resume=status == "waiting_review",
        progress_text=_progress_text(stage, status, row),
    )


def _intent_missing_fields(intent: dict[str, Any]) -> list[str]:
    labels = {
        "scope": "scope",
        "time_range": "time_range",
        "industry": "industry",
        "depth": "depth",
        "output_format": "output_format",
    }
    missing: list[str] = []
    for key, label in labels.items():
        value = str(intent.get(key, "") or "").strip()
        if value in _MISSING_SENTINELS:
            missing.append(label)
    return missing


def _to_source_type(tool: str | None) -> str:
    return {
        "kb_search": "kb",
        "web_search": "web",
        "data_query": "api",
    }.get(tool or "", "web")


def _build_sources(state: dict[str, Any]) -> list[ReportSourceDto]:
    plan_map = {str(item.get("task_id")): item for item in _safe_list(state.get("research_plan")) if isinstance(item, dict)}
    chunks = [item for item in _safe_list(state.get("research_chunks")) if isinstance(item, dict)]
    sources: list[ReportSourceDto] = []
    for idx, chunk in enumerate(chunks):
        task_id = str(chunk.get("task_id") or f"source-{idx}")
        plan = plan_map.get(task_id, {})
        tool = str(plan.get("tool") or "").strip() or None
        query = _first_nonempty(plan.get("query"), chunk.get("source"), f"来源 {idx + 1}") or f"来源 {idx + 1}"
        summary = _first_nonempty(chunk.get("content"), chunk.get("source"), "暂无摘要") or "暂无摘要"
        sources.append(
            ReportSourceDto(
                source_id=task_id,
                title=query,
                summary=summary,
                source_type=_to_source_type(tool),
                tool=tool,
                topic_key=_first_nonempty(chunk.get("topic_key")),
                raw_query=_first_nonempty(plan.get("query")),
            )
        )
    return sources


def _build_outline(state: dict[str, Any], interrupted: bool) -> list[ReportOutlineSectionDto]:
    items = [item for item in _safe_list(state.get("outline")) if isinstance(item, dict)]
    return [
        ReportOutlineSectionDto(
            section_id=str(item.get("section_id") or f"s{idx + 1}"),
            title=_first_nonempty(item.get("title"), f"章节 {idx + 1}") or f"章节 {idx + 1}",
            objective=_first_nonempty(item.get("objective"), "-") or "-",
            key_points=[str(x) for x in item.get("key_points", []) if str(x).strip()],
            evidence_keys=[str(x) for x in item.get("evidence_keys", []) if str(x).strip()],
            target_words=int(item.get("target_words") or 0),
            order=idx + 1,
            status="approved" if not interrupted and idx < len(items) else "ready",
        )
        for idx, item in enumerate(items)
    ]


def _build_sections(state: dict[str, Any], stage: str, review: ReportReviewDto | None) -> list[ReportSectionDto]:
    outline_map = {
        str(item.get("section_id")): item for item in _safe_list(state.get("outline")) if isinstance(item, dict)
    }
    reviews = [item for item in _safe_list(state.get("section_reviews")) if isinstance(item, dict)]
    revise_ids = set(review.sections_to_revise) if review else set()
    rows: list[ReportSectionDto] = []
    for review_item in reviews:
        section_id = str(review_item.get("section_id") or "")
        outline = outline_map.get(section_id, {})
        score = review_item.get("score")
        status = "done"
        if stage == "writing" and review and revise_ids:
            status = "revising" if section_id in revise_ids else "reviewing"
        elif stage == "writing" and not score:
            status = "writing"
        rows.append(
            ReportSectionDto(
                section_id=section_id,
                title=_first_nonempty(outline.get("title"), section_id, "未命名章节") or "未命名章节",
                content=_first_nonempty(review_item.get("content")),
                status=status,
                score=int(score) if isinstance(score, int) else None,
                issues=[str(x) for x in review_item.get("issues", []) if str(x).strip()],
                suggestions=[str(x) for x in review_item.get("suggestions", []) if str(x).strip()],
                word_count=len(str(review_item.get("content") or "")) or None,
            )
        )
    for section_id, outline in outline_map.items():
        if any(item.section_id == section_id for item in rows):
            continue
        rows.append(
            ReportSectionDto(
                section_id=section_id,
                title=_first_nonempty(outline.get("title"), section_id) or section_id,
                status="pending",
            )
        )
    return rows


def _build_review(state: dict[str, Any]) -> ReportReviewDto | None:
    reviews = [item for item in _safe_list(state.get("artifacts")) if isinstance(item, dict) and item.get("type") == "review"]
    if not reviews:
        return None
    latest = reviews[-1]
    return ReportReviewDto(
        round=int(latest.get("round") or 0),
        overall_score=float(latest.get("overall_score")) if latest.get("overall_score") is not None else None,
        passed=bool(latest.get("passed")) if latest.get("passed") is not None else None,
        sections_to_revise=[str(x) for x in latest.get("sections_to_revise", []) if str(x).strip()],
    )


def _build_final_report(state: dict[str, Any], review: ReportReviewDto | None) -> FinalReportDto | None:
    markdown = _first_nonempty(state.get("final_report"))
    if not markdown:
        return None
    chapters = len(_safe_list(state.get("outline")))
    return FinalReportDto(
        markdown=markdown,
        chapter_count=chapters,
        word_count=len(markdown),
        citation_count=markdown.count("http") + markdown.count("["),
        quality_score=review.overall_score if review else None,
    )


def _build_artifacts(state: dict[str, Any]) -> list[ReportArtifactDto]:
    rows: list[ReportArtifactDto] = []
    for idx, item in enumerate(_safe_list(state.get("artifacts"))):
        if not isinstance(item, dict):
            continue
        rows.append(
            ReportArtifactDto(
                artifact_id=str(item.get("artifact_id") or item.get("type") or f"artifact-{idx}"),
                type=str(item.get("type") or "artifact"),
                title=_first_nonempty(item.get("title"), item.get("message"), item.get("type"), f"artifact-{idx}") or f"artifact-{idx}",
                url=_first_nonempty(item.get("url")),
                meta={k: v for k, v in item.items() if k not in {"artifact_id", "type", "title", "message", "url"}},
            )
        )
    return rows


def _build_metrics(state: dict[str, Any], sources: list[ReportSourceDto], stage: str) -> ReportMetricsDto:
    total_tasks = len(_safe_list(state.get("research_plan")))
    completed_tasks = len(sources)
    progress_percent = round((completed_tasks / total_tasks) * 100, 2) if total_tasks else 0
    current_message = {
        "intent": "正在识别研究意图",
        "research": "正在汇总外部与知识库来源",
        "outline": "正在等待或处理大纲审核",
        "writing": "正在并行撰写与审阅章节",
        "final": "最终报告已准备完成",
    }.get(stage)
    return ReportMetricsDto(
        total_sources=len(sources),
        completed_tasks=completed_tasks,
        total_tasks=total_tasks,
        progress_percent=progress_percent,
        current_message=current_message,
    )


def _build_interrupt(interrupt_payload: dict[str, Any] | None) -> ReportInterruptDto | None:
    if not interrupt_payload:
        return None
    metadata = interrupt_payload.get("metadata") or {}
    node_name = str(metadata.get("node_name") or "")
    kind = "intent_review" if node_name == "human_review_intent" else "outline_review"
    return ReportInterruptDto(
        kind=kind,
        node_name=node_name or "human_review",
        message=str(interrupt_payload.get("message") or "等待人工审核"),
        payload=interrupt_payload,
    )


def to_workspace_detail(
    *,
    row: ReportHistoryModel,
    state_values: dict[str, Any] | None,
    current_node: str | None,
    interrupt_payload: dict[str, Any] | None,
) -> ReportHistoryDetail:
    state = _safe_dict(state_values)
    intent_dict = state.get("intent") if isinstance(state.get("intent"), dict) else _safe_dict(row.intent_payload)
    stage = infer_workspace_stage(current_node or row.current_node, row.status)
    status = _to_ui_status(row.status, stage)
    interrupt = _build_interrupt(interrupt_payload or _safe_dict(row.interrupt_payload))
    sources = _build_sources(state)
    review = _build_review(state)
    return ReportHistoryDetail(
        thread_id=row.thread_id,
        title=_first_nonempty(row.topic, row.user_query, "未命名研报") or "未命名研报",
        user_query=_first_nonempty(row.user_query, row.topic, "") or "",
        status=status,
        stage=stage,
        intent=ReportIntentDto(**intent_dict) if intent_dict else None,
        intent_missing_fields=_intent_missing_fields(intent_dict),
        sources=sources,
        outline=_build_outline(state, interrupt is not None),
        sections=_build_sections(state, stage, review),
        review=review,
        final_report=_build_final_report(state, review),
        artifacts=_build_artifacts(state),
        metrics=_build_metrics(state, sources, stage),
        interrupt=interrupt,
        created_at=row.created_at,
        updated_at=row.updated_at,
        finished_at=row.finished_at,
        last_error=row.last_error,
    )
