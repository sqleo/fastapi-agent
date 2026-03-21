"""解析器抽象：本地文件 → Markdown 文本。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class DocumentToMarkdownParser(ABC):
    """将单个本地文件解析为 Markdown 字符串（异步，避免阻塞事件循环）。"""

    @abstractmethod
    async def to_markdown(self, path: Path) -> str:
        """读取 ``path`` 并返回 UTF-8 语义下的 Markdown 正文。"""
