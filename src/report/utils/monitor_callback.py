"""LangChain 回调处理器：为研报模块的每次 LLM 调用自动写入 llm_monitor.request_log。

使用方式：通过 create_llm() 自动附加，无需在各 Node 手动添加。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger("report.monitor")


def _extract_usage_from_result(response: LLMResult) -> dict:
    """从 LLMResult 中提取 token 用量。"""
    info: dict = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}

    # LangChain ≥0.2: llm_output.token_usage (OpenAI 兼容)
    llm_output = getattr(response, "llm_output", None) or {}
    if isinstance(llm_output, dict):
        token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        if isinstance(token_usage, dict):
            info["input_tokens"] = (
                token_usage.get("prompt_tokens", 0)
                or token_usage.get("input_tokens", 0)
                or 0
            )
            info["output_tokens"] = (
                token_usage.get("completion_tokens", 0)
                or token_usage.get("output_tokens", 0)
                or 0
            )
            cr = token_usage.get("cached_tokens") or token_usage.get("cache_read_input_tokens")
            if cr:
                info["cache_read_tokens"] = int(cr)

    # 兜底：从 generations[0][0].message.usage_metadata 取
    if not info["input_tokens"] and not info["output_tokens"]:
        try:
            gen = response.generations[0][0]
            msg = getattr(gen, "message", None) or getattr(gen, "text", None)
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                if isinstance(usage, dict):
                    info["input_tokens"] = usage.get("input_tokens", 0) or 0
                    info["output_tokens"] = usage.get("output_tokens", 0) or 0
                    details = usage.get("input_token_details") or {}
                    if isinstance(details, dict):
                        info["cache_read_tokens"] = details.get("cache_read", 0) or 0
                else:
                    info["input_tokens"] = getattr(usage, "input_tokens", 0) or 0
                    info["output_tokens"] = getattr(usage, "output_tokens", 0) or 0
        except Exception:
            pass

    return info


async def _persist(
    *,
    model: str,
    provider: str,
    thread_id: str | None,
    user_id: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    latency_ms: int,
    status: str,
    error_message: str | None = None,
) -> None:
    """后台持久化，异常不影响业务。"""
    try:
        from monitor.collector import save_request_log
        from monitor.models import RequestLog

        input_cache_hit = cache_read_tokens
        input_cache_miss = max(0, input_tokens - input_cache_hit)

        log = RequestLog(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            input_tokens_cache_hit=input_cache_hit,
            input_tokens_cache_miss=input_cache_miss,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message[:1000] if error_message else None,
            is_cache_hit=input_cache_hit > 0,
            cache_tokens_saved=input_cache_hit,
            user_id=user_id,
            extra={"source": "report", "thread_id": thread_id},
        )
        await save_request_log(log)
    except Exception:
        logger.warning("report monitor persist failed", exc_info=True)


class ReportTokenCallback(AsyncCallbackHandler):
    """捕获每次 LLM 调用的 token 用量并写入监控表。"""

    def __init__(
        self,
        model: str,
        provider: str,
        thread_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self.model = model
        self.provider = provider
        self.thread_id = thread_id
        self.user_id = user_id
        self._t0: float = 0.0

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        self._t0 = time.perf_counter()

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[Any],
        **kwargs: Any,
    ) -> None:
        self._t0 = time.perf_counter()

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        elapsed_ms = int((time.perf_counter() - self._t0) * 1000)
        usage = _extract_usage_from_result(response)
        logger.debug(
            "report llm_end model=%s ms=%d in=%d out=%d thread=%s",
            self.model,
            elapsed_ms,
            usage["input_tokens"],
            usage["output_tokens"],
            self.thread_id,
        )
        asyncio.create_task(
            _persist(
                model=self.model,
                provider=self.provider,
                thread_id=self.thread_id,
                user_id=self.user_id,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cache_read_tokens=usage["cache_read_tokens"],
                latency_ms=elapsed_ms,
                status="success",
            )
        )

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        elapsed_ms = int((time.perf_counter() - self._t0) * 1000)
        asyncio.create_task(
            _persist(
                model=self.model,
                provider=self.provider,
                thread_id=self.thread_id,
                user_id=self.user_id,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                latency_ms=elapsed_ms,
                status="error",
                error_message=str(error),
            )
        )
