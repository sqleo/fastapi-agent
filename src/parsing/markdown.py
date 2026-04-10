"""Markdown 源文件：视为已是中间格式，规范化编码后异步写入 ``parsed_md`` 路径."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiofiles

from parsing.base import IntermediateMdGenerator


def _decode_markdown_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class MarkdownIntermediateMdGenerator(IntermediateMdGenerator):
    """``.md`` / ``.markdown`` / ``.mdx``：复制为规范化 UTF-8 文本。"""

    async def generate(self, *, source_path: Path, dest_path: Path) -> None:
        async with aiofiles.open(source_path, "rb") as src:
            raw = await src.read()
        text = _decode_markdown_bytes(raw)
        await asyncio.to_thread(dest_path.parent.mkdir, parents=True, exist_ok=True)
        async with aiofiles.open(dest_path, mode="w", encoding="utf-8", newline="\n") as out:
            await out.write(text)
