import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session as DbSession

from core.database import Upload, get_db
from core.settings import data_dir

router = APIRouter(prefix="/api")

UPLOAD_DIR: Path | None = None

MAX_SIZE = 20 * 1024 * 1024  # 20MB
_UPLOAD_MUTATION_LOCK = threading.RLock()
CANCELLATION_TTL_SECONDS = 24 * 60 * 60
MAX_CANCELLATION_MARKERS = 4096


def upload_dir() -> Path:
    d = UPLOAD_DIR or data_dir() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upload_id(value: str | None) -> str:
    if not value:
        return str(uuid.uuid4())
    try:
        parsed = uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(400, "invalid upload id") from exc
    return str(parsed)


def _cancellation_path(upload_id: str) -> Path:
    return upload_dir() / ".cancelled" / upload_id


def _prune_cancellations(*, now: float | None = None, reserve_slot: bool = False) -> None:
    directory = upload_dir() / ".cancelled"
    if not directory.is_dir():
        return
    now = time.time() if now is None else now
    markers = []
    for marker in directory.iterdir():
        if marker.is_symlink() or not marker.is_file():
            continue
        try:
            modified = marker.stat().st_mtime
        except OSError:
            continue
        if modified > now or now - modified <= CANCELLATION_TTL_SECONDS:
            markers.append((modified, marker))
        else:
            marker.unlink(missing_ok=True)
    overflow = max(0, len(markers) - MAX_CANCELLATION_MARKERS + int(reserve_slot))
    for _modified, marker in sorted(markers)[:overflow]:
        marker.unlink(missing_ok=True)


def _mark_cancelled(upload_id: str) -> None:
    _prune_cancellations(reserve_slot=True)
    marker = _cancellation_path(upload_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)


@router.post("/uploads")
async def upload_file(
    file: UploadFile = File(...),
    upload_id: str | None = Form(None),
    incognito: bool = False,
    db: DbSession = Depends(get_db),
):
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "file too large (max 20MB)")

    public_id = _upload_id(upload_id)
    mime = file.content_type or "application/octet-stream"
    with _UPLOAD_MUTATION_LOCK:
        _prune_cancellations()
        cancellation = _cancellation_path(public_id)
        if cancellation.exists():
            raise HTTPException(409, "upload cancelled")
        if incognito:
            from services import incognito as private_store

            if db.get(Upload, public_id) is not None:
                raise HTTPException(409, "upload id already exists")
            try:
                upload = private_store.put_upload(
                    file.filename or "file",
                    mime,
                    content,
                    upload_id=public_id,
                )
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            return {"id": upload.id, "name": upload.name, "type": mime, "size": len(content)}
        from services import incognito as private_store

        if db.get(Upload, public_id) is not None or private_store.get_upload(public_id) is not None:
            raise HTTPException(409, "upload id already exists")
        ext = Path(file.filename or "file").suffix.lower()
        fname = f"{uuid.uuid4()}{ext}"
        stored = upload_dir().joinpath(fname)
        stored.write_bytes(content)
        rec = Upload(
            id=public_id,
            filename=fname,
            original_name=file.filename or fname,
            mime_type=mime,
            size=len(content),
        )
        try:
            db.add(rec)
            db.commit()
            db.refresh(rec)
        except BaseException:
            stored.unlink(missing_ok=True)
            raise
        return {"id": rec.id, "name": rec.original_name, "type": mime, "size": rec.size}


@router.get("/uploads/{upload_id}")
def serve_upload(upload_id: str, db: DbSession = Depends(get_db)):
    from services import incognito as private_store

    private = private_store.get_upload(upload_id)
    if private:
        return Response(
            content=private.content,
            media_type=_safe_mime(private.mime_type, Path(private.name).suffix),
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
        )
    rec = db.get(Upload, upload_id)
    if not rec:
        raise HTTPException(404)
    fpath = upload_dir() / rec.filename
    if not fpath.exists():
        raise HTTPException(404)
    # client-supplied mime_type: neutralize svg/html so a stored <script> can't run as a document
    mime = _safe_mime(rec.mime_type, fpath.suffix)
    return FileResponse(
        str(fpath),
        media_type=mime,
        filename=rec.original_name,
        headers={"X-Content-Type-Options": "nosniff"},
    )


def _safe_mime(mime_type: str, suffix: str) -> str:
    mime = mime_type or "application/octet-stream"
    if any(x in mime.lower() for x in ("svg", "html", "xml")) or suffix.lower() in (
        ".svg",
        ".svgz",
        ".html",
        ".htm",
        ".xml",
        ".xhtml",
    ):
        mime = "application/octet-stream"
    return mime


@router.delete("/uploads/{upload_id}")
def delete_upload(upload_id: str, pending: bool = False, db: DbSession = Depends(get_db)):
    from services import incognito as private_store

    public_id = _upload_id(upload_id) if pending else str(upload_id)
    with _UPLOAD_MUTATION_LOCK:
        private = private_store.get_upload(public_id)
        rec = db.get(Upload, public_id)
        if private is not None and rec is not None:
            raise HTTPException(409, "upload id is ambiguous")
        if pending:
            _mark_cancelled(public_id)
        deleted = private_store.delete_upload(public_id) if private is not None else False
        if rec:
            (upload_dir() / rec.filename).unlink(missing_ok=True)
            db.delete(rec)
            db.commit()
            deleted = True
        if deleted:
            if not pending:
                _cancellation_path(public_id).unlink(missing_ok=True)
            return {"ok": True}
        if pending:
            return {"ok": True}
        raise HTTPException(404)
