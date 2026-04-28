from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

from langgraph.graph.state import logging

from utils.json import safe_serialize, sse_json

EventPayload = dict[str, Any]
EventHandler = Callable[[EventPayload], EventPayload | None]
EventHandlers = Mapping[str, EventHandler]

logger = logging.getLogger("utils.report_sse")

def normalize_report_event(event: Any) -> EventPayload | None:
    """将 LangGraph event 规范化为统一 payload。"""
    kind = event.get("event")
    event_name = event.get("name")
    metadata = event.get("metadata", {}) or {}
    node_name = metadata.get("langgraph_node")
    data = event.get("data", {}) or {}
    # if kind == "on_chain_start" and node_name and event_name == node_name:
    #     return {"type": "node", "state": "running", "node": node_name}

    # if kind == "on_chain_end" and node_name and event_name == node_name:
    #     return {
    #         "type": "node",
    #         "state": "completed",
    #         "node": node_name,
    #         "output": safe_serialize(data.get("output")) if node_name == "writer" else None,
    #     }

    # if kind == "on_chat_model_stream":
    #     chunk = data.get("chunk")
    #     content = getattr(chunk, "content", None)
    #     if content:
    #         return {
    #             "type": "message",
    #             "node": node_name,
    #             "data": {"content": content},
    #         }
    #     return None

    if kind == "on_custom_event":
        payload = event.get("data")
        print(f"🔔 捕获自定义事件 {event_name}，节点 {node_name}，数据 {payload}")
        if isinstance(payload, dict):
            return {
                "type": "custom",
                "event_name": event_name,
                "node": node_name,
                "data": payload,
            }
        return None

    if kind == "on_chain_error" and node_name and event_name == node_name:
        return {
            "type": "node_error",
            "node": node_name,
            "error": safe_serialize(data.get("error")),
        }

    return None


def dispatch_event_payload(
    payload: EventPayload,
    handlers: EventHandlers | None = None,
    default_handler: EventHandler | None = None,
) -> EventPayload | None:
    """按 payload.type 分发给处理函数。"""
    if handlers:
        event_type = payload.get("type")
        if isinstance(event_type, str) and event_type in handlers:
            return handlers[event_type](payload)
    if default_handler:
        return default_handler(payload)
    return payload


async def iter_report_sse_events(
    events: AsyncIterator[Any],
    handlers: EventHandlers | None = None,
    default_handler: EventHandler | None = None,
) -> AsyncIterator[str]:
    """遍历 LangGraph 事件并按 handler 分发后输出 SSE。"""
    async for event in events:
        payload = normalize_report_event(event)
        if payload is None:
            continue
        transformed = dispatch_event_payload(payload, handlers=handlers, default_handler=default_handler)
        if transformed is None:
            continue
        yield sse_json(transformed)
