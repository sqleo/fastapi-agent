"""知识库异步队列（解析 Taskiq）."""

from llamarag.queue.ingest_queue import push_kb_index_job, push_kb_parse_job

__all__ = [
    "push_kb_index_job",
    "push_kb_parse_job",
]
