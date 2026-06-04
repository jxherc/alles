import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Upload

router = APIRouter(prefix="/api")

UPLOAD_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_SIZE = 20 * 1024 * 1024  # 20MB


@router.post("/uploads")
async def upload_file(file: UploadFile = File(...), db: DbSession = Depends(get_db)):
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "file too large (max 20MB)")

    mime = file.content_type or "application/octet-stream"
    ext  = Path(file.filename or "file").suffix.lower()
    fname = f"{uuid.uuid4()}{ext}"
    (UPLOAD_DIR / fname).write_bytes(content)

    rec = Upload(filename=fname, original_name=file.filename or fname,
                 mime_type=mime, size=len(content))
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, "name": rec.original_name, "type": mime, "size": rec.size}


@router.get("/uploads/{upload_id}")
def serve_upload(upload_id: str, db: DbSession = Depends(get_db)):
    rec = db.get(Upload, upload_id)
    if not rec:
        raise HTTPException(404)
    fpath = UPLOAD_DIR / rec.filename
    if not fpath.exists():
        raise HTTPException(404)
    return FileResponse(str(fpath), media_type=rec.mime_type, filename=rec.original_name)


@router.delete("/uploads/{upload_id}")
def delete_upload(upload_id: str, db: DbSession = Depends(get_db)):
    rec = db.get(Upload, upload_id)
    if not rec:
        raise HTTPException(404)
    fpath = UPLOAD_DIR / rec.filename
    if fpath.exists():
        fpath.unlink()
    db.delete(rec)
    db.commit()
    return {"ok": True}
