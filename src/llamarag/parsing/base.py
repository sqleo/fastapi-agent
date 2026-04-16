"""由原文件生成 ``static/parsed_md/`` 中间 Markdown 的抽象策略."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class IntermediateMdGenerator(ABC):
    """将磁盘上的源文件异步写入中间 Markdown 路径（UTF-8）."""

    @abstractmethod
    async def generate(self, *, source_path: Path, dest_path: Path) -> None:
        """异步读取 ``source_path``，写入 ``dest_path``；调用方保证父目录可创建."""
