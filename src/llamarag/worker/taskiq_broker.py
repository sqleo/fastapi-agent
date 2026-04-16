"""Taskiq broker 工厂：LlamaRAG 解析任务使用独立 Redis List 队列."""

from __future__ import annotations

from functools import lru_cache

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

TASKIQ_PARSE_QUEUE_NAME = "llamarag:parse"


@lru_cache(maxsize=16)
def make_parse_broker(redis_url: str) -> ListQueueBroker:
    """按 ``redis_url`` 复用 broker。"""
    result_backend = RedisAsyncResultBackend(redis_url=redis_url, result_ex_time=3600)
    return ListQueueBroker(
        url=redis_url,
        queue_name=TASKIQ_PARSE_QUEUE_NAME,
        max_connection_pool_size=50,
    ).with_result_backend(result_backend)
