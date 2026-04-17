"""后台 worker：解析由 Taskiq 执行，见 ``llamarag.worker.taskiq_tasks``。

启动解析 + 入库共用同一 worker（队列名 ``llamarag:parse``）::

    # 须与写入任务的一端（FastAPI）使用**相同** REDIS_URI（含库号）， docker-compose.dev 中默认为 /1
    REDIS_URI=redis://localhost:6379/1 uv run taskiq worker llamarag.worker.taskiq_tasks:broker
"""
