import json
from typing import Any


def sse_json(obj: dict[str, Any]) -> str:
    """将对象转换为 SSE 格式的 JSON 字符串"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

def safe_serialize(obj):
    """安全地将对象转换为可 JSON 序列化的形式，支持 Pydantic 模型和常见数据结构。"""
    if hasattr(obj, "model_dump"): # 针对 Pydantic v2
        return obj.model_dump()
    if hasattr(obj, "dict"):       # 针对 Pydantic v1
        return obj.dict()
    if isinstance(obj, list):
        return [safe_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: safe_serialize(v) for k, v in obj.items()}
    return obj