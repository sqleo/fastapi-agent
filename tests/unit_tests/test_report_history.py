from models.ReportHistoryModel import ReportHistoryStatus
from report.state import OutIntent, OutlineSection
from services.controllers.report_history_controller import (
    build_report_history_changes,
    infer_report_status,
)


def test_build_report_history_changes_prefers_structured_intent_and_final_report() -> None:
    changes = build_report_history_changes(
        user_query="帮我写一份新能源汽车市场分析",
        state_values={
            "user_query": "备用 query",
            "intent": OutIntent(
                topic="2026 年中国新能源汽车市场分析",
                report_type="市场趋势报告",
            ),
            "outline": [
                OutlineSection(
                    section_id="s1",
                    title="市场规模",
                    objective="分析规模",
                    key_points=["销量", "增速"],
                    target_words=500,
                ),
            ],
            "final_report": "这是最终报告正文。",
            "token_usage": {"prompt_tokens": 12},
            "artifacts": [{"type": "image", "url": "https://example.com/a.png"}],
        },
        status=ReportHistoryStatus.COMPLETED,
        current_node=["output"],
    )

    assert changes["topic"] == "2026 年中国新能源汽车市场分析"
    assert changes["report_type"] == "市场趋势报告"
    assert changes["summary"] == "这是最终报告正文。"
    assert changes["word_count"] == len("这是最终报告正文。")
    assert changes["current_node"] == "output"
    assert changes["status"] == ReportHistoryStatus.COMPLETED
    assert changes["token_usage"] == {"prompt_tokens": 12}
    assert changes["artifacts"] == [{"type": "image", "url": "https://example.com/a.png"}]


def test_build_report_history_changes_falls_back_to_outline_titles_when_report_missing() -> None:
    changes = build_report_history_changes(
        user_query="写一份半导体竞争格局分析",
        state_values={
            "outline": [
                {"title": "行业概况"},
                {"title": "竞争格局"},
                {"title": "结论建议"},
            ],
        },
        status="interrupted",
        current_node=["human_review"],
        interrupt_payload={"reason": "need confirm"},
    )

    assert changes["summary"] == "行业概况 / 竞争格局 / 结论建议"
    assert changes["current_node"] == "human_review"
    assert changes["status"] == ReportHistoryStatus.INTERRUPTED
    assert changes["interrupt_payload"] == {"reason": "need confirm"}
    assert changes["word_count"] is None


def test_infer_report_status() -> None:
    assert infer_report_status(None) == ReportHistoryStatus.COMPLETED
    assert infer_report_status([]) == ReportHistoryStatus.COMPLETED
    assert infer_report_status(["human_review"]) == ReportHistoryStatus.INTERRUPTED
    assert infer_report_status(["writer"]) == ReportHistoryStatus.RUNNING
