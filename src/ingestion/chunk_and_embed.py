"""解析落盘后的 Markdown：切块 → 带上图文引用字段 → 写入 Milvus。

调用顺序建议：

1. ``parse_local_file_to_markdown_file``（落盘 .md + 可选图片入库）
2. 同一事务 ``commit``（若需要别的事务可见）
3. 本模块 ``index_parsed_markdown_to_milvus``，或解析时传 ``index_to_milvus=True``

``session`` 与路由里 ``session: AsyncSqlSessionDeps`` 是同一个 ``AsyncSession`` 实例；
本函数不是 FastAPI 路由，**不会**自动注入，须由调用方把路由参数 ``session`` 原样传入。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path, PurePosixPath

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlmodel import select

from models.KbExtractedImageModel import KbExtractedImageModel
from utils.milvus_db import MilvusService
from utils.sql_db import AsyncSqlSessionDeps

# ingestion/chunk_and_embed.py → 项目根（与 async_parse 一致）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Markdown 图片：![任意文字](路径或URL)
_MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)", re.MULTILINE)


def _static_url_from_storage_key(storage_key: str) -> str:
    """数据库存的 static/parsed_md/... → 浏览器可访问的 /static/parsed_md/..."""
    k = storage_key.strip().replace("\\", "/").lstrip("/")
    return f"/{k}"


def _basename_from_markdown_url(url: str) -> str:
    """从正文里的链接取出文件名，用来对齐 ``KbExtractedImageModel.original_name``。"""
    u = url.strip().split("?", 1)[0].split("#", 1)[0]
    return PurePosixPath(u).name


async def index_parsed_markdown_to_milvus(
    session: AsyncSqlSessionDeps,
    *,
    md_path: Path | str,
    kb_file_id: int,
    knowledge_base_id: int,
    md_text: str | None = None,
    chunk_size: int = 900,
    chunk_overlap: int = 120,
) -> int:
    """
    **步骤 1** — 读入正文（若已内存里有字符串可传 ``md_text``，少一次磁盘 IO）。

    **步骤 2** — 查出该 ``kb_file_id`` 下所有 ``kb_extracted_image``，用 ``original_name``
    （如 ``abc.jpg``）建字典，后面在块里按文件名反查主键和静态 URL。

    **步骤 3** — ``RecursiveCharacterTextSplitter`` 按长度切块（可改 ``chunk_size``）。

    **步骤 4** — 对每个块用正则找 ``![](...)``，对上一步字典，写入 metadata：

    - ``kb_file_id`` / ``knowledge_base_id`` / ``chunk_index``：过滤与排序
    - ``source_parsed_md``：这份 md 相对项目根的路径，方便回源
    - ``has_images``：``0`` / ``1``
    - ``image_ids``：逗号分隔的数据库主键，文检索命中后可反查图
    - ``image_static_urls``：``|`` 分隔的 ``/static/...``，可直接给前端展示

    **步骤 5** — ``get_vector_store().add_documents``（langchain_milvus，在线程里跑避免阻塞事件循环）。

    返回写入的块数；无正文则返回 ``0``。
    """
    path = Path(md_path).expanduser().resolve()
    text = md_text if md_text is not None else path.read_text(encoding="utf-8")
    if not text.strip():
        return 0
    # 读取图片信息
    stmt = select(KbExtractedImageModel).where(
        KbExtractedImageModel.kb_file_id == kb_file_id
    )
    result = await session.execute(stmt)
    by_name: dict[str, KbExtractedImageModel] = {}
    for row in result.scalars().all():
        by_name[row.original_name] = row
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", " ", ""],
    )
    pieces = [p for p in splitter.split_text(text) if p.strip()]

    try:
        md_rel = path.resolve().relative_to(_PROJECT_ROOT.resolve())
        md_rel_str = md_rel.as_posix()
    except ValueError:
        md_rel_str = str(path)

    docs: list[Document] = []
    for idx, chunk in enumerate(pieces):
        ids_list: list[str] = []
        urls_list: list[str] = []
        for m in _MD_IMG_RE.finditer(chunk):
            bname = _basename_from_markdown_url(m.group(2))
            # 找到图片对应的数据库记录
            rec = by_name.get(bname)
            if rec is not None:
                ids_list.append(str(rec.id))
                urls_list.append(_static_url_from_storage_key(rec.storage_key))
        meta = {
            "kb_file_id": str(kb_file_id),
            "knowledge_base_id": str(knowledge_base_id),
            "chunk_index": str(idx),
            "source_parsed_md": md_rel_str,
            "has_images": "1" if ids_list else "0",
            "image_ids": ",".join(ids_list),
            "image_static_urls": "|".join(urls_list),
        }
        docs.append(Document(page_content=chunk, metadata=meta))

    def _add() -> None:
        MilvusService().add_documents(docs)

    await asyncio.to_thread(_add)
    return len(docs)
