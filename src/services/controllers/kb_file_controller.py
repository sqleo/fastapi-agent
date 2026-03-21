"""资料库文件：本机磁盘上传（不落解析）。"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from configs.env import env_config
from models.KbFileModel import KbFileModel
from services.controllers.knowledge_controller import get_knowledge_base_owned

# 项目根目录（与 ``configs/env.py`` 中 ``_ROOT`` 一致）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_CHUNK = 1024 * 1024


async def upload_kb_file_local(
    session: AsyncSession,
    *,
    kb_id: int,
    owner_user_id: int,
    file: UploadFile,
    audit_label: str | None,
) -> KbFileModel:
    """校验归属后写入项目根下配置目录，并插入 ``kb_file``（parse_status=pending）。"""
    kb = await get_knowledge_base_owned(
        session, kb_id=kb_id, owner_user_id=owner_user_id
    )
    if kb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="资料库不存在或无权访问",
        )
    if kb.status != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="资料库已禁用",
        )

    raw_name = (file.filename or "").strip() or "unnamed"
    safe_name = Path(raw_name).name[:500] or "unnamed"
    disk_name = f"{uuid.uuid4().hex}_{safe_name}"

    rel_root = env_config.kb_upload_rel_dir.strip().strip("/")
    abs_dir = _PROJECT_ROOT / rel_root / str(kb_id)
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / disk_name

    storage_key = f"{rel_root}/{kb_id}/{disk_name}"
    max_bytes = env_config.kb_upload_max_bytes
    total = 0

    try:
        with abs_path.open("wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    abs_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"文件超过 {max_bytes} 字节限制",
                    )
                out.write(chunk)
    except OSError as e:
        abs_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"写入文件失败：{e!s}",
        ) from e

    if total == 0:
        abs_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="空文件",
        )

    mime = file.content_type
    if mime is not None and len(mime) > 128:
        mime = mime[:128]

    row = KbFileModel(
        knowledge_base_id=kb_id,
        original_name=safe_name[:512],
        storage_key=storage_key[:1024],
        mime_type=mime,
        size_bytes=total,
        parse_status="pending",
        create_by=audit_label,
        update_by=audit_label,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row
