import json
from collections import OrderedDict
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, Photo, Album
from services import photos_store as ps

router = APIRouter(prefix="/api/photos")


def _fmt(p: Photo) -> dict:
    return {
        "id": p.id,
        "thumb": f"/api/photos/thumb/{p.id}",
        "original": f"/api/photos/original/{p.id}",
        "width": p.width, "height": p.height,
        "taken_at": p.taken_at.isoformat() if p.taken_at else None,
        "favorite": p.favorite, "album_id": p.album_id,
        "original_name": p.original_name,
        "exif": json.loads(p.exif or "{}"),
    }


def _label(d: datetime) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"   # avoid %-d (not on Windows)


@router.get("/list")
def list_photos(album: str = Query(""), db: DbSession = Depends(get_db)):
    q = db.query(Photo)
    if album:
        q = q.filter(Photo.album_id == album)
    rows = q.all()
    rows.sort(key=lambda p: (p.taken_at or p.created_at or datetime.min), reverse=True)  # newest first
    moments = OrderedDict()
    for p in rows:
        d = p.taken_at or p.created_at or datetime.utcnow()
        moments.setdefault(d.strftime("%Y-%m-%d"), (d, []))[1].append(_fmt(p))
    out = [{"date": k, "label": _label(v[0]), "items": v[1]} for k, v in moments.items()]
    return {"moments": out, "count": len(rows)}


@router.post("/upload")
async def upload(album_id: str = Form(""), file: UploadFile = File(...), db: DbSession = Depends(get_db)):
    data = await file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(400, "file too large (100MB max)")
    try:
        info = ps.import_image(data, file.filename or "photo.jpg")
    except ValueError as e:
        raise HTTPException(400, str(e))
    p = Photo(filename=info["filename"], thumb=info["thumb"], original_name=info["original_name"],
              width=info["width"], height=info["height"], taken_at=info["taken_at"],
              exif=info["exif"], album_id=album_id or None)
    db.add(p); db.commit(); db.refresh(p)
    return _fmt(p)


@router.get("/thumb/{pid}")
def thumb(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    tp = ps.thumb_path(p.thumb)
    if tp and tp.is_file():
        return FileResponse(str(tp))
    op = ps.original_path(p.filename)   # fall back to the original if no thumb
    if op.is_file():
        return FileResponse(str(op))
    raise HTTPException(404)


@router.get("/original/{pid}")
def original(pid: str, download: bool = False, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    op = ps.original_path(p.filename)
    if not op.is_file():
        raise HTTPException(404)
    return FileResponse(str(op), filename=p.original_name if download else None)


@router.delete("/{pid}")
def delete_photo(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    ps.delete_files(p.filename, p.thumb)
    db.delete(p); db.commit()
    return {"ok": True}


class PatchPhoto(BaseModel):
    favorite: bool | None = None
    album_id: str | None = None


@router.patch("/{pid}")
def patch_photo(pid: str, body: PatchPhoto, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    if body.favorite is not None:
        p.favorite = body.favorite
    if body.album_id is not None:
        p.album_id = body.album_id or None
    db.commit()
    return _fmt(p)


# ── albums ──
@router.get("/albums")
def albums(db: DbSession = Depends(get_db)):
    out = []
    for a in db.query(Album).order_by(Album.created_at.desc()).all():
        n = db.query(Photo).filter(Photo.album_id == a.id).count()
        out.append({"id": a.id, "name": a.name, "count": n})
    return out


class AlbumBody(BaseModel):
    name: str


@router.post("/albums")
def add_album(body: AlbumBody, db: DbSession = Depends(get_db)):
    a = Album(name=body.name)
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "name": a.name, "count": 0}


@router.delete("/albums/{aid}")
def del_album(aid: str, db: DbSession = Depends(get_db)):
    a = db.get(Album, aid)
    if not a:
        raise HTTPException(404)
    for p in db.query(Photo).filter(Photo.album_id == aid).all():
        p.album_id = None
    db.delete(a); db.commit()
    return {"ok": True}
