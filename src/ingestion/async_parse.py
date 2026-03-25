"""异步解析入口：类型检测 → 工厂选解析器 → 落盘 Markdown。"""

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from ingestion.detection import detect_document_kind, guess_mime_type
from ingestion.factory import ParserFactory, ParserFactoryConfig
from ingestion.parsers.base import DocumentToMarkdownParser

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# src/ingestion/async_parse.py → 项目根为 parent.parent.parent
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PARSED_MD_DIR = _PROJECT_ROOT / "static" / "parsed_md"


async def parse_local_file_to_markdown_file(
    file_path: str | Path,
    *,
    output_dir: Path | None = None,
    factory: ParserFactory | None = None,
    factory_config: ParserFactoryConfig | None = None,
    kb_file_id: int | None = None,
    db_session: "AsyncSession | None" = None,
    index_to_milvus: bool = True,
    knowledge_base_id: int | None = None,
) -> Path:
    """
    异步解析本地文件为 Markdown 并写入磁盘。

    - 使用 ``detect_document_kind`` 判断类别；
    - 使用 ``ParserFactory``（可配置允许的后缀）选择具体解析器；
    - 输出目录默认 ``static/parsed_md/``，文件名 ``{stem}_{uuid8}.md``。
    - ``db_session``：在 FastAPI 路由里用 ``session: AsyncSqlSessionDeps``（见
      ``utils.sql_db``）注入，调用时传入 ``db_session=session``。
    - 若同时传入 ``kb_file_id`` 与 ``db_session``，富文档解析器会将抽取的图片写入磁盘并
      插入 ``kb_extracted_image``；配置了 LLM API Key 时，会为图片生成结合上下文的
      ``alt`` 写入正文与 ``alt_text`` 字段。解析器内仅 ``flush``，调用方需 ``commit``。
    - ``index_to_milvus=True`` 时，在写盘后对同一正文做切块并写入 Milvus，metadata 中带
      ``image_ids`` / ``image_static_urls`` 等便于图文引用；须同时传入 ``knowledge_base_id``。
    """
    path = Path(file_path).expanduser().resolve()
    if factory is None:
        factory = ParserFactory(factory_config)
    out_dir = output_dir if output_dir is not None else DEFAULT_PARSED_MD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{path.stem}_{uuid.uuid4().hex[:8]}.md"
    out_path = out_dir / out_name
    parser: DocumentToMarkdownParser = factory.get_parser_for_path(path)
    md = await parser.to_markdown(
        path,
        markdown_out_path=out_path,
        kb_file_id=kb_file_id,
        db_session=db_session,
    )
    out_path.write_text(md, encoding="utf-8")
    if index_to_milvus:
        if kb_file_id is None or db_session is None or knowledge_base_id is None:
            raise ValueError(
                "index_to_milvus=True 时必须同时传入 kb_file_id、db_session、knowledge_base_id"
            )
        from ingestion.chunk_and_embed import index_parsed_markdown_to_milvus
        await index_parsed_markdown_to_milvus(
            session=db_session,
            md_path=out_path,
            kb_file_id=kb_file_id,
            knowledge_base_id=knowledge_base_id,
            md_text=md,
        )
    return out_path


def describe_file_for_pipeline(path: str | Path) -> dict[str, str | None]:
    """调试/日志：扩展名、推断 MIME、``DocumentKind``。"""
    p = Path(path).expanduser().resolve()
    kind = detect_document_kind(p)
    return {
        "path": str(p),
        "suffix": p.suffix.lower(),
        "mime": guess_mime_type(p),
        "document_kind": kind.value,
    }