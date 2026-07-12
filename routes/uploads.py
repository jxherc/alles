import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session as DbSession

from core.database import Upload, get_db
from core.settings import data_dir

router = APIRouter(prefix="/api")

UPLOAD_DIR: Path | None = None

MAX_SIZE = 20 * 1024 * 1024  # 20MB


def upload_dir() -> Path:
    d = UPLOAD_DIR or data_dir() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/uploads")
async def upload_file(
    file: UploadFile = File(...), incognito: bool = False, db: DbSession = Depends(get_db)
):
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "file too large (max 20MB)")

    mime = file.content_type or "application/octet-stream"
    if incognito:
        from services import incognito as private_store

        upload = private_store.put_upload(file.filename or "file", mime, content)
        return {"id": upload.id, "name": upload.name, "type": mime, "size": len(content)}
    ext = Path(file.filename or "file").suffix.lower()
    fname = f"{uuid.uuid4()}{ext}"
    upload_dir().joinpath(fname).write_bytes(content)

    rec = Upload(
        filename=fname, original_name=file.filename or fname, mime_type=mime, size=len(content)
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
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
def delete_upload(upload_id: str, db: DbSession = Depends(get_db)):
    from services import incognito as private_store

    if private_store.delete_upload(upload_id):
        return {"ok": True}
    rec = db.get(Upload, upload_id)
    if not rec:
        raise HTTPException(404)
    fpath = upload_dir() / rec.filename
    if fpath.exists():
        fpath.unlink()
    db.delete(rec)
    db.commit()
    return {"ok": True}
