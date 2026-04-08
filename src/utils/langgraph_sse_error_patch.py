"""LangGraph API 流式错误全量透传。

覆盖 ``langgraph_api.serde.default``：任意 ``BaseException`` 均序列化为
``{"error": 类型名, "message": str(exception)}``，不再使用 LangGraph 默认的
``An internal error occurred``。

注意：会把图中未捕获异常的原样暴露给 SSE 消费方（含前端），生产环境请自行评估是否
需要网关层脱敏或仅对内网开放。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PATCHED = False


def apply_vendor_api_sse_patch() -> None:
    """幂等；缺 ``langgraph_api.serde`` 时直接返回。"""
    global _PATCHED
    if _PATCHED:
        return

    try:
        import langgraph_api.serde as serde_module
    except ImportError:
        logger.debug("langgraph_api 未安装，跳过 SSE 异常全量透传补丁")
        return

    _orig = serde_module.default

    def default(obj: Any) -> Any:
        if isinstance(obj, BaseException):
            return {"error": type(obj).__name__, "message": str(obj)}
        return _orig(obj)

    serde_module.default = default
    _PATCHED = True
    logger.info("LangGraph SSE：已对全部 BaseException 启用 message 透传（无白名单）")


def apply_openai_error_sse_patch() -> None:
    """兼容旧名。"""
    apply_vendor_api_sse_patch()
