"""加载 ``static/parsed_md/`` 下已解析的中间 Markdown."""

from __future__ import annotations

from pathlib import Path

from models.FileManagementModel import PARSED_MD_STORAGE_PREFIX


def resolved_parsed_md_path(parsed_md_storage_key: str) -> Path:
    """将库内 ``parsed_md_storage_key`` 解析为 ``static/`` 下绝对路径."""
    key = (parsed_md_storage_key or "").strip().lstrip("/")
    if not key.startswith(f"{PARSED_MD_STORAGE_PREFIX}/"):
        msg = f"parsed_md_storage_key 必须以 {PARSED_MD_STORAGE_PREFIX}/ 开头: {parsed_md_storage_key!r}"
        raise ValueError(msg)
    return Path("static") / key


def load_parsed_md_documents(parsed_md_storage_key: str):
    """读取中间 Markdown，返回 LlamaIndex ``Document`` 列表.

    依赖 ``llama-index-core``；未安装时请在 worker 环境安装 ``rag`` optional 依赖。
    """
    path = resolved_parsed_md_path(parsed_md_storage_key)
    if not path.is_file():
        msg = f"中间 Markdown 不存在: {path}"
        raise FileNotFoundError(msg)

    try:
        from llama_index.core import Document  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "需要安装 llama-index-core（已含在主依赖中，请确认环境安装完整）",
        ) from exc

    text = path.read_text(encoding="utf-8")
    return [
        Document(
            text=text,
            metadata={
                "source_parsed_md": str(path),
                "parsed_md_storage_key": parsed_md_storage_key,
            },
        ),
    ]
