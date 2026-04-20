from datetime import time


def emit_trace_event(event_name: str, payload: dict):
    """发送自定义事件到前端，供调试和分析使用。事件将包含在智能客服的消息流中，前端可根据事件类型和内容进行展示和处理。

    Args:
        event_name: 事件名称，建议使用短小且具有描述性的字符串，如 "knowledge_base_search"。
        payload: 事件负载，包含事件相关的详细信息，应为一个字典。建议包含以下字段：
            - phase: 事件阶段，如 "start"、"end"、"error" 等。
            - message: 可选，事件相关的文本信息，如错误描述等。
            - 其他自定义字段，根据具体事件类型而定。
    """
    from langgraph.config import get_stream_writer

    try:
        get_stream_writer()(
            {
                "type": event_name,
                "ts_ms": int(time.time() * 1000),
                **payload,
            }
        )
    except Exception:
        pass