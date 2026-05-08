"""研报流式事件映射."""

from __future__ import annotations

import time
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_stage(value: str | None) -> str | None:
    raw = (value or "").strip()
    if raw == "planning":
        return "research"
    if raw == "output":
        return "final"
    if raw == "review":
        return "writing"
    if raw.startswith("outline"):
        return "outline"
    if raw.startswith("intent"):
        return "intent"
    if raw.startswith("research"):
        return "research"
    if raw.startswith("writing"):
        return "writing"
    return raw or None


def map_report_stream_event(event_name: str, data: dict[str, Any], *, thread_id: str) -> dict[str, Any] | None:
    ts_ms = int(data.get("ts_ms") or _now_ms())
    stage = _normalize_stage(data.get("phase"))

    if event_name == "phase":
        return {
            "type": "stage",
            "thread_id": thread_id,
            "stage": stage,
            "ts_ms": ts_ms,
            "message": data.get("message"),
            "payload": {k: v for k, v in data.items() if k not in {"ts_ms", "phase", "message"}},
        }

    if event_name == "metric":
        return {
            "type": "progress",
            "thread_id": thread_id,
            "stage": stage,
            "ts_ms": ts_ms,
            "message": data.get("message") or "进度更新",
            "payload": {
                "done": data.get("done"),
                "total": data.get("total"),
                "percent": data.get("coverage"),
                "tool_counts": data.get("tool_counts"),
            },
        }

    if event_name == "source_found":
        return {
            "type": "source_found",
            "thread_id": thread_id,
            "stage": "research",
            "ts_ms": ts_ms,
            "payload": data,
        }

    if event_name == "outline_ready":
        return {
            "type": "outline_ready",
            "thread_id": thread_id,
            "stage": "outline",
            "ts_ms": ts_ms,
            "message": data.get("message") or "报告大纲已生成",
            "payload": data,
        }

    if event_name == "section_update":
        return {
            "type": "section_update",
            "thread_id": thread_id,
            "stage": "writing",
            "ts_ms": ts_ms,
            "message": data.get("message"),
            "payload": data,
        }

    if event_name == "review_update":
        return {
            "type": "review_update",
            "thread_id": thread_id,
            "stage": "writing",
            "ts_ms": ts_ms,
            "message": data.get("message"),
            "payload": data,
        }

    if event_name == "final_report_ready":
        return {
            "type": "final_report_ready",
            "thread_id": thread_id,
            "stage": "final",
            "ts_ms": ts_ms,
            "message": data.get("message"),
            "payload": data,
        }

    if event_name == "task":
        return {
            "type": "log",
            "thread_id": thread_id,
            "stage": stage,
            "ts_ms": ts_ms,
            "message": data.get("message"),
            "payload": data,
        }

    if event_name in {"web_search", "kb_search", "data_query", "artifact"}:
        return {
            "type": "log",
            "thread_id": thread_id,
            "stage": stage or "research",
            "ts_ms": ts_ms,
            "message": data.get("message") or data.get("description") or data.get("result"),
            "payload": data,
        }

    return None
