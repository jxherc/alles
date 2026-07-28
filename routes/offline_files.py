"""Offline-cache controls for Files."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import OfflineFile, get_db
from services import offline_files, storage_locations

router = APIRouter(prefix="/api/files/offline")

_ACTIVE_MEDIA_TYPES = frozenset(
    {
        "application/javascript",
        "application/xhtml+xml",
        "application/xml",
        "image/svg+xml",
        "text/html",
        "text/javascript",
        "text/xml",
    }
)


def _is_active_media_type(media_type: str) -> bool:
    value = media_type.lower()
    return value in _ACTIVE_MEDIA_TYPES or value.endswith("+xml")


class OfflineBody(BaseModel):
    location_id: str
    path: str


def _error(call):
    try:
        return call()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (RuntimeError, ValueError, offline_files.OfflineFileError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("")
def list_offline(location_id: str = Query(""), db: DbSession = Depends(get_db)):
    rows = offline_files.list_items(db, location_id=location_id or None)
    return {
        "items": [offline_files.public_dict(row) for row in rows],
        "cache_only": True,
        "is_backup": False,
    }


@router.post("")
def enable_offline(body: OfflineBody, db: DbSession = Depends(get_db)):
    row = _error(lambda: offline_files.enable(db, location_id=body.location_id, path=body.path))
    return offline_files.public_dict(row)


@router.post("/{offline_id}/cancel")
def cancel_offline(offline_id: str, db: DbSession = Depends(get_db)):
    row = db.get(OfflineFile, offline_id)
    if not row:
        raise HTTPException(404, "offline copy not found")
    _error(lambda: offline_files.cancel(db, row))
    return offline_files.public_dict(row)


@router.delete("")
def disable_offline(body: OfflineBody, db: DbSession = Depends(get_db)):
    normalized = _error(lambda: storage_locations.normalize_path(body.path))
    row = (
        db.query(OfflineFile)
        .filter(
            OfflineFile.location_id == body.location_id,
            OfflineFile.normalized_path == normalized,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "offline copy not found")
    _error(lambda: offline_files.disable(db, row))
    return {"ok": True, "cache_only": True, "is_backup": False}


@router.get("/raw")
def read_offline(
    location_id: str = Query(...), path: str = Query(...), db: DbSession = Depends(get_db)
):
    normalized = _error(lambda: storage_locations.normalize_path(path))
    resolved = _error(
        lambda: offline_files.resolve_cached(db, location_id=location_id, path=normalized)
    )
    if resolved is None or not resolved.is_file():
        raise HTTPException(404, "offline copy not found")
    media_type = mimetypes.guess_type(normalized)[0] or "application/octet-stream"
    headers = {"X-Content-Type-Options": "nosniff"}
    options = {}
    if _is_active_media_type(media_type):
        media_type = "application/octet-stream"
        options = {
            "filename": Path(normalized).name or "offline-file",
            "content_disposition_type": "attachment",
        }
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return FileResponse(str(resolved), media_type=media_type, headers=headers, **options)


@router.get("/list")
def list_cached_folder(
    location_id: str = Query(...), path: str = Query(...), db: DbSession = Depends(get_db)
):
    normalized = _error(lambda: storage_locations.normalize_path(path))
    resolved = _error(
        lambda: offline_files.resolve_cached(db, location_id=location_id, path=normalized)
    )
    if resolved is None or not resolved.is_dir():
        raise HTTPException(404, "offline folder not found")
    items = []
    children = [child for child in resolved.iterdir() if not child.is_symlink()]
    for child in sorted(children, key=lambda item: (not item.is_dir(), item.name.lower())):
        info = child.stat()
        child_path = f"{normalized}/{child.name}" if normalized else child.name
        items.append(
            {
                "path": child_path,
                "normalized_path": child_path,
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": info.st_size if child.is_file() else 0,
                "mtime": info.st_mtime,
                "cache_only": True,
                "offline_state": "ready",
            }
        )
    return {"path": normalized, "items": items, "cache_only": True, "is_backup": False}


@router.get("/read")
def read_cached_file(
    location_id: str = Query(...),
    path: str = Query(...),
    limit: int = Query(200_000, ge=1, le=2_000_000),
    db: DbSession = Depends(get_db),
):
    normalized = _error(lambda: storage_locations.normalize_path(path))
    resolved = _error(
        lambda: offline_files.resolve_cached(db, location_id=location_id, path=normalized)
    )
    if resolved is None or not resolved.is_file():
        raise HTTPException(404, "offline copy not found")
    with resolved.open("rb") as handle:
        raw = handle.read(limit + 1)
    truncated = len(raw) > limit
    preview = raw[:limit]
    try:
        content = preview.decode("utf-8")
        is_text = True
    except UnicodeError:
        content = ""
        is_text = False
    return {
        "path": normalized,
        "mime": mimetypes.guess_type(normalized)[0] or "application/octet-stream",
        "is_text": is_text,
        "content": content,
        "size": resolved.stat().st_size,
        "truncated": truncated,
        "cache_only": True,
    }
