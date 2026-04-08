"""应用日志：在 root 上附加本地文件（可轮转），与 uvicorn 共存。

``uvicorn`` 在加载 ``app`` 之后还会配置 logging，若在 ``create_app()`` 里过早
``handlers.clear()``，随后会被覆盖或导致业务 logger 无法写入文件。
因此应在 **FastAPI lifespan 启动** 时再调用 ``configure_logging()``。
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 标记由本模块挂上的文件 Handler，避免重复添加
_AGENT_FILE_HANDLER_ATTR = "_fastapi_agent_rotating_file"

_CONFIGURED = False

# 相对路径时相对项目根（含 src 的仓库根）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _already_have_agent_file_handler(root: logging.Logger) -> bool:
    return any(getattr(h, _AGENT_FILE_HANDLER_ATTR, False) for h in root.handlers)


def configure_logging() -> None:
    """
    向 root logger **追加** ``RotatingFileHandler``（默认 ``logs/app.log``），不 ``clear()``
    已有 Handler，避免冲掉 uvicorn 的控制台配置。

    应在应用 **lifespan 进入阶段** 调用一次；若已挂过同名逻辑则直接返回。
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    raw = os.getenv("LOG_FILE", "logs/app.log").strip() or "logs/app.log"
    log_path = Path(raw)
    if not log_path.is_absolute():
        log_path = _PROJECT_ROOT / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    # 与 uvicorn 共存时 root 可能被设为 WARNING，需按 LOG_LEVEL 接收业务 INFO
    root.setLevel(level)

    if _already_have_agent_file_handler(root):
        _CONFIGURED = True
        return

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=_int_env("LOG_MAX_BYTES", 10 * 1024 * 1024),
        backupCount=_int_env("LOG_BACKUP_COUNT", 5),
        encoding="utf-8",
    )
    setattr(file_handler, _AGENT_FILE_HANDLER_ATTR, True)
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # 非 uvicorn 时 root 常无 StreamHandler；RotatingFileHandler 继承自 StreamHandler，
    # 用「精确类型」判断，避免把「仅文件」当成已有控制台。
    has_plain_console = any(type(h) is logging.StreamHandler for h in root.handlers)
    if not has_plain_console:
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(fmt)
        root.addHandler(console)

    logging.getLogger(__name__).info("已附加本地日志文件: %s", log_path.resolve())
    _CONFIGURED = True
