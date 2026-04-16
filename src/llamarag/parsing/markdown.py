"""Markdown 源：用 ``SimpleDirectoryReader`` + ``FlatReader`` 读原文，再按 1MB 缓冲落盘."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiofiles
from llama_index.core import SimpleDirectoryReader
from llama_index.core.readers.base import BaseReader
from llama_index.readers.file import FlatReader

from llamarag.parsing.base import IntermediateMdGenerator

BUFFER_SIZE = 1024 * 1024  # 1MB


def _flat_extractors() -> dict[str, BaseReader]:
    r: BaseReader = FlatReader()
    return {".md": r, ".markdown": r, ".mdx": r}


async def _write_utf8_chunked(dest_path: Path, text: str) -> None:
    """使用 aiofiles 打开时设 1MB 缓冲，并按块写入，避免单次超大 write."""
    await asyncio.to_thread(dest_path.parent.mkdir, parents=True, exist_ok=True)
    async with aiofiles.open(
        dest_path,
        mode="w",
        encoding="utf-8",
        newline="\n",
        buffering=BUFFER_SIZE,
    ) as out:
        if not text:
            return
        for i in range(0, len(text), BUFFER_SIZE):
            await out.write(text[i : i + BUFFER_SIZE])


class MarkdownIntermediateMdGenerator(IntermediateMdGenerator):
    """``.md`` / ``.markdown`` / ``.mdx``：FlatReader 取文本，再规范化 UTF-8 落盘."""

    async def generate(self, *, source_path: Path, dest_path: Path) -> None:
        """读源文件为 Document 文本，再写入 ``dest_path``."""
        reader = SimpleDirectoryReader(
            input_files=[str(source_path.resolve())],
            file_extractor=_flat_extractors(),
        )

        documents = await asyncio.to_thread(reader.load_data)

        if not documents:
            text = ""
        else:
            text = documents[0].text or ""

        await _write_utf8_chunked(dest_path, text)
