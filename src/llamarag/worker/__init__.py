"""后台 worker：解析由 Taskiq 执行，见 ``llamarag.worker.taskiq_tasks``。

启动解析 worker::

    REDIS_URI=redis://localhost:6379/0 uv run taskiq worker llamarag.worker.taskiq_tasks:broker
"""
