"""文件管理业务逻辑：创建文件夹、上传文件、文件夹树."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiofiles

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.BasicModel import beijing_now
from models.FileManagementModel import (
    FileAssetModel,
    FileFolderModel,
    FileLifecycleStatus,
    FileParseStatus,
    FileSourceType,
)
from models.KnowledgeBaseModel import KbFilePipelineStatus, KnowledgeBaseFileModel
from utils.content_semver import bump_major_after_reupload


def _safe_file_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文件名不能为空",
        )
    cleaned = raw.replace("/", "_").replace("\\", "_").replace("\x00", "")
    return cleaned[:255]


async def _get_owned_folder_or_404(
    session: AsyncSession,
    *,
    owner_user_id: int,
    folder_id: int,
) -> FileFolderModel:
    row = await session.get(FileFolderModel, folder_id)
    if row is None or row.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件夹不存在")
    return row


async def create_folder_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    name: str,
    parent_folder_id: int | None,
    project_code: str | None,
    description: str | None,
) -> FileFolderModel:
    """为指定用户创建文件夹。"""
    parent: FileFolderModel | None = None
    if parent_folder_id is not None:
        parent = await _get_owned_folder_or_404(
            session,
            owner_user_id=owner_user_id,
            folder_id=parent_folder_id,
        )

    effective_project_code = (project_code or "").strip() or None
    if effective_project_code is None and parent is not None:
        effective_project_code = parent.project_code

    row = FileFolderModel(
        owner_user_id=owner_user_id,
        name=name.strip(),
        parent_folder_id=parent_folder_id,
        project_code=effective_project_code,
        description=description,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同级目录下已存在同名文件夹",
        ) from exc
    await session.refresh(row)
    return row


async def list_folder_tree_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    project_code: str | None,
) -> list[FileFolderModel]:
    """获取用户文件夹列表（扁平），由路由层组装为树。"""
    stmt = select(FileFolderModel).where(FileFolderModel.owner_user_id == owner_user_id)
    if project_code and project_code.strip():
        stmt = stmt.where(FileFolderModel.project_code == project_code.strip())
    stmt = stmt.order_by(FileFolderModel.parent_folder_id.asc(), FileFolderModel.id.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def upload_file_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    uploader_user_id: int,
    uploader_username: str,
    upload: UploadFile,
    folder_id: int | None,
    project_code: str | None,
    source: FileSourceType,
) -> tuple[FileAssetModel, str]:
    """保存上传文件并写入文件元数据记录。"""
    folder: FileFolderModel | None = None
    if folder_id is not None:
        folder = await _get_owned_folder_or_404(
            session,
            owner_user_id=owner_user_id,
            folder_id=folder_id,
        )

    file_name = _safe_file_name(upload.filename or "")
    body = await upload.read()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文件内容不能为空",
        )

    normalized_project_code = (project_code or "").strip() or None
    if normalized_project_code is None and folder is not None:
        normalized_project_code = folder.project_code

    if (
        folder is not None
        and folder.project_code is not None
        and normalized_project_code is not None
        and folder.project_code != normalized_project_code
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文件项目标识与所属文件夹不一致",
        )

    if folder is not None and folder.project_code is not None:
        normalized_project_code = folder.project_code

    ext = Path(file_name).suffix.lower().lstrip(".") or None
    content_type = (upload.content_type or "").strip() or None
    file_hash = hashlib.sha256(body).hexdigest()
    now = datetime.now(UTC)
    storage_key = f"uploads/{owner_user_id}/{now:%Y/%m}/{uuid4().hex}_{file_name}"
    save_path = Path("static") / storage_key
    await asyncio.to_thread(save_path.parent.mkdir, parents=True, exist_ok=True)
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(body)

    uploader_name = (uploader_username or "").strip() or str(uploader_user_id)
    row = FileAssetModel(
        owner_user_id=owner_user_id,
        uploader_user_id=uploader_user_id,
        folder_id=folder_id,
        project_code=normalized_project_code,
        file_name=file_name,
        display_name=file_name,
        file_ext=ext,
        mime_type=content_type,
        size_bytes=len(body),
        storage_key=storage_key,
        file_hash=file_hash,
        semver_major=0,
        semver_minor=0,
        semver_patch=0,
        parse_status=FileParseStatus.PENDING,
        source=source,
        create_by=uploader_name,
        update_by=uploader_name,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文件记录冲突，请重试",
        ) from exc
    await session.refresh(row)

    file_url = f"/static/{storage_key}"
    return row, file_url


async def reupload_file_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    uploader_user_id: int,
    uploader_username: str,
    file_id: int,
    upload: UploadFile,
) -> tuple[FileAssetModel, str]:
    """同一 file_asset 覆盖上传：MAJOR+1，清空解析产物，关联知识库条目回到 pending_md。"""
    row = await session.get(FileAssetModel, file_id)
    if row is None or row.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    if row.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    new_name = _safe_file_name(upload.filename or row.file_name)
    body = await upload.read()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文件内容不能为空",
        )

    ext = Path(new_name).suffix.lower().lstrip(".") or None
    content_type = (upload.content_type or "").strip() or None
    file_hash = hashlib.sha256(body).hexdigest()
    now = datetime.now(UTC)
    storage_key = f"uploads/{owner_user_id}/{now:%Y/%m}/{uuid4().hex}_{new_name}"

    old_storage = (row.storage_key or "").strip()
    old_parsed = (row.parsed_md_storage_key or "").strip()

    save_path = Path("static") / storage_key
    await asyncio.to_thread(save_path.parent.mkdir, parents=True, exist_ok=True)
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(body)

    if old_storage:
        old_abs = Path("static") / old_storage.lstrip("/")
        try:
            if await asyncio.to_thread(old_abs.is_file):
                await asyncio.to_thread(old_abs.unlink)
        except OSError:
            pass
    if old_parsed:
        pabs = Path("static") / old_parsed.lstrip("/")
        try:
            if await asyncio.to_thread(pabs.is_file):
                await asyncio.to_thread(pabs.unlink)
        except OSError:
            pass

    major, minor, patch = bump_major_after_reupload(row.semver_major, row.semver_minor, row.semver_patch)
    uploader_name = (uploader_username or "").strip() or str(uploader_user_id)
    row.file_name = new_name
    row.display_name = new_name
    row.file_ext = ext
    row.mime_type = content_type
    row.size_bytes = len(body)
    row.storage_key = storage_key
    row.file_hash = file_hash
    row.parsed_md_storage_key = None
    row.semver_major = major
    row.semver_minor = minor
    row.semver_patch = patch
    row.parse_status = FileParseStatus.PENDING
    row.uploader_user_id = uploader_user_id
    row.updated_at = beijing_now()
    row.update_by = uploader_name

    kb_stmt = select(KnowledgeBaseFileModel).where(
        KnowledgeBaseFileModel.owner_user_id == owner_user_id,
        KnowledgeBaseFileModel.file_id == file_id,
    )
    kb_res = await session.execute(kb_stmt)
    for kb in kb_res.scalars().all():
        kb.pipeline_status = KbFilePipelineStatus.PENDING_MD
        kb.pipeline_error = None

    session.add(row)
    await session.commit()
    await session.refresh(row)

    file_url = f"/static/{storage_key}"
    return row, file_url


async def list_files_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    page: int,
    page_size: int,
    status: FileLifecycleStatus | None,
    project_code: str | None,
) -> tuple[int, list[FileAssetModel]]:
    """分页查询文件列表，支持业务状态/项目标识筛选。"""
    filters = [
        FileAssetModel.owner_user_id == owner_user_id,
        FileAssetModel.is_deleted.is_(False),
    ]
    if status is not None:
        filters.append(FileAssetModel.status == status)
    if project_code and project_code.strip():
        filters.append(FileAssetModel.project_code == project_code.strip())

    count_stmt = select(func.count(FileAssetModel.id)).where(*filters)
    count_res = await session.execute(count_stmt)
    total = int(count_res.scalar_one() or 0)

    offset = (page - 1) * page_size
    list_stmt = (
        select(FileAssetModel)
        .where(*filters)
        .order_by(FileAssetModel.created_at.desc(), FileAssetModel.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows_res = await session.execute(list_stmt)
    rows = list(rows_res.scalars().all())
    return total, rows


async def soft_delete_file_owned(
    session: AsyncSession,
    *,
    owner_user_id: int,
    file_id: int,
    operator_username: str,
) -> None:
    """软删除文件；若文件仍关联任意知识库则拒绝删除。"""
    row = await session.get(FileAssetModel, file_id)
    if row is None or row.owner_user_id != owner_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    if row.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    kb_count_stmt = select(func.count(KnowledgeBaseFileModel.id)).where(
        KnowledgeBaseFileModel.owner_user_id == owner_user_id,
        KnowledgeBaseFileModel.file_id == file_id,
    )
    kb_count_res = await session.execute(kb_count_stmt)
    if int(kb_count_res.scalar_one() or 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文件已加入知识库，请先从知识库移出后再删除",
        )

    row.is_deleted = True
    row.updated_at = beijing_now()
    row.update_by = (operator_username or "").strip() or None
    session.add(row)
    await session.commit()

