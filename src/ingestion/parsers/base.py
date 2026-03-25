"""解析器抽象：本地文件 → Markdown 文本。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class DocumentToMarkdownParser(ABC):
    """将单个本地文件解析为 Markdown 字符串（异步，避免阻塞事件循环）。"""

    @abstractmethod
    async def to_markdown(
        self,
        path: Path,
        *,
        markdown_out_path: Path | None = None,
        **kwargs: Any,
    ) -> str:
        """读取 ``path`` 并返回 UTF-8 语义下的 Markdown 正文。

        若传入 ``markdown_out_path``（即将写入的 .md 路径），富文档解析器可把配图落到
        磁盘并改写 Markdown 中的相对路径。

        可选关键字（由具体解析器识别）：例如 ``kb_file_id``、``db_session``、
        ``skip_image_alt_llm``、``image_alt_llm_platform`` — 富文档可在落盘后用 LLM
        结合上下文生成图片 ``alt`` 并写入库表字段。
        """
