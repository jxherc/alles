import json
from collections import OrderedDict
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from core.database import Album, Photo, TrashItem, get_db
from routes.vault import _master_pw
from services import photos_store as ps
from services import trash

router = APIRouter(prefix="/api/photos")


def _kw_list(s) -> list[str]:
    return [k for k in (s or "").split(",") if k]


def _norm_kw(kws) -> str:
    """lowercase, trim, drop blanks, dedup (order-stable) → csv."""
    seen, out = set(), []
    for k in kws or []:
        k = str(k).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return ",".join(out)


def _fmt(p: Photo) -> dict:
    return {
        "id": p.id,
        "thumb": f"/api/photos/thumb/{p.id}",
        "original": f"/api/photos/original/{p.id}",
        "width": p.width,
        "height": p.height,
        "taken_at": p.taken_at.isoformat() if p.taken_at else None,
        "favorite": p.favorite,
        "album_id": p.album_id,
        "original_name": p.original_name,
        "caption": p.caption or "",
        "keywords": _kw_list(p.keywords),
        "hidden": bool(p.hidden),
        "is_video": bool(p.is_video),
        "exif": json.loads(p.exif or "{}"),
    }


def _moments(rows):
    rows.sort(key=lambda p: p.taken_at or p.created_at or datetime.min, reverse=True)
    moments = OrderedDict()
    for p in rows:
        d = p.taken_at or p.created_at or datetime.utcnow()
        moments.setdefault(d.strftime("%Y-%m-%d"), (d, []))[1].append(_fmt(p))
    out = [{"date": k, "label": _label(v[0]), "items": v[1]} for k, v in moments.items()]
    return {"moments": out, "count": len(rows)}


def _label(d: datetime) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"  # avoid %-d (not on Windows)


@router.get("/smart")
def smart_photos(
    period: str = Query("month"),
    from_date: str = Query(""),
    to_date: str = Query(""),
    keyword: str = Query(""),
    db: DbSession = Depends(get_db),
):
    """4c - smart albums: EXIF-date grouping (period=month|day) + optional date-range / keyword filter."""
    from services import smart_albums

    rows = (
        db.query(Photo)
        .filter(Photo.deleted_at == None)  # noqa: E711
        .filter((Photo.hidden == False) | (Photo.hidden == None))  # noqa: E711,E712
        .all()
    )
    photos = [
        {
            "id": p.id,
            "taken_at": p.taken_at.isoformat() if p.taken_at else "",
            "keywords": p.keywords or "",
        }
        for p in rows
    ]
    if from_date and to_date:
        photos = smart_albums.in_range(photos, from_date, to_date)
    if keyword:
        photos = smart_albums.by_keyword(photos, keyword)
    groups = smart_albums.group_by_period(photos, period=period)
    return {"groups": {k: [p["id"] for p in v] for k, v in groups.items()}, "count": len(photos)}


@router.get("/list")
def list_photos(
    album: str = Query(""), favorites: bool = Query(False), db: DbSession = Depends(get_db)
):
    q = db.query(Photo).filter(Photo.deleted_at == None)  # noqa: E711
    q = q.filter((Photo.hidden == False) | (Photo.hidden == None))  # noqa: E711,E712
    if album:
        q = q.filter(Photo.album_id == album)
    if favorites:
        q = q.filter(Photo.favorite == True)  # noqa: E712
    return _moments(q.all())


@router.get("/hidden")
def list_hidden(db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    """the hidden/locked album — only reachable with a valid vault unlock token (7a)."""
    rows = (
        db.query(Photo)
        .filter(Photo.deleted_at == None, Photo.hidden == True)  # noqa: E711,E712
        .all()
    )
    return _moments(rows)


@router.get("/search")
def search_photos(q: str = Query(...), db: DbSession = Depends(get_db)):
    """match on filename, EXIF (camera make/model), and the date ('june 2026',
    '2026-06', a year). returns the same moments shape as /list."""
    ql = (q or "").strip().lower()
    if not ql:
        return {"moments": [], "count": 0}
    hits = []
    base = db.query(Photo).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
    )
    for p in base.all():
        d = p.taken_at or p.created_at
        hay = " ".join(
            [
                (p.original_name or "").lower(),
                (p.exif or "").lower(),
                (p.caption or "").lower(),
                (p.keywords or "").lower(),
                (d.isoformat().lower() if d else ""),
                (d.strftime("%B %Y").lower() if d else ""),
            ]
        )
        if ql in hay:
            hits.append(p)
    hits.sort(key=lambda p: p.taken_at or p.created_at or datetime.min, reverse=True)
    moments = OrderedDict()
    for p in hits:
        d = p.taken_at or p.created_at or datetime.utcnow()
        moments.setdefault(d.strftime("%Y-%m-%d"), (d, []))[1].append(_fmt(p))
    out = [{"date": k, "label": _label(v[0]), "items": v[1]} for k, v in moments.items()]
    return {"moments": out, "count": len(hits)}


@router.get("/map")
def photos_map(db: DbSession = Depends(get_db)):
    """located photos for the map view — only ones with GPS in EXIF, excludes hidden+deleted."""
    rows = db.query(Photo).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
    )
    points = []
    for p in rows.all():
        ex = json.loads(p.exif or "{}")
        lat, lon = ex.get("lat"), ex.get("lon")
        if lat is None or lon is None:
            continue
        points.append(
            {
                "id": p.id,
                "lat": lat,
                "lon": lon,
                "thumb": f"/api/photos/thumb/{p.id}",
                "original": f"/api/photos/original/{p.id}",
                "caption": p.caption or "",
                "taken_at": p.taken_at.isoformat() if p.taken_at else None,
            }
        )
    return {"points": points, "count": len(points)}


@router.get("/memories")
def memories(date: str = Query(""), db: DbSession = Depends(get_db)):
    """'on this day' — photos taken the same month/day in strictly earlier years,
    grouped by how many years ago. default date is today."""
    try:
        ref = datetime.fromisoformat(date) if date else datetime.utcnow()
    except ValueError:
        raise HTTPException(400, "date must be ISO (YYYY-MM-DD)")
    rows = db.query(Photo).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
        Photo.taken_at != None,  # noqa: E711
    )
    buckets = {}  # years_ago -> [photos]
    for p in rows.all():
        t = p.taken_at
        if t.month == ref.month and t.day == ref.day and t.year < ref.year:
            buckets.setdefault(ref.year - t.year, []).append(p)
    groups = []
    for ya in sorted(buckets):
        items = sorted(buckets[ya], key=lambda p: p.taken_at, reverse=True)
        groups.append(
            {
                "years_ago": ya,
                "year": ref.year - ya,
                "date": f"{ref.year - ya:04d}-{ref.month:02d}-{ref.day:02d}",
                "items": [_fmt(p) for p in items],
            }
        )
    return {"groups": groups, "count": sum(len(g["items"]) for g in groups)}


class CollageBody(BaseModel):
    ids: list[str]
    cols: int = 3


@router.post("/collage")
def collage(body: CollageBody, db: DbSession = Depends(get_db)):
    """build a PIL grid collage from the given photos and save it as a new photo."""
    if not body.ids:
        raise HTTPException(400, "no photos given")
    paths = []
    for pid in body.ids:
        p = db.get(Photo, pid)
        if not p or p.deleted_at is not None:
            continue  # skip unknown / trashed
        op = ps.original_path(p.filename)
        if op.is_file():
            paths.append(op)
    if not paths:
        raise HTTPException(400, "no usable photos")
    try:
        raw = ps.make_collage(paths, cols=body.cols)
    except ValueError as e:
        raise HTTPException(400, str(e))
    info = ps.import_image(raw, "collage.png")
    np = Photo(
        filename=info["filename"],
        thumb=info["thumb"],
        original_name=info["original_name"],
        width=info["width"],
        height=info["height"],
        taken_at=info["taken_at"],
        exif=info["exif"],
    )
    db.add(np)
    db.commit()
    db.refresh(np)
    return _fmt(np)


class EditSaveBody(BaseModel):
    data_url: str
    name: str = "edited.png"


@router.post("/edit-save")
def edit_save(body: EditSaveBody, db: DbSession = Depends(get_db)):
    """save an edited image (a canvas data-url from the editor) as a new photo."""
    import base64

    du = body.data_url or ""
    if "," in du:
        du = du.split(",", 1)[1]
    try:
        raw = base64.b64decode(du)
    except Exception:
        raise HTTPException(400, "bad image data")
    if not raw:
        raise HTTPException(400, "empty image")
    try:
        info = ps.import_image(raw, body.name or "edited.png")
    except ValueError as e:
        raise HTTPException(400, str(e))
    p = Photo(
        filename=info["filename"],
        thumb=info["thumb"],
        original_name=info["original_name"],
        width=info["width"],
        height=info["height"],
        taken_at=info["taken_at"],
        exif=info["exif"],
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _fmt(p)


@router.post("/upload")
async def upload(
    album_id: str = Form(""), file: UploadFile = File(...), db: DbSession = Depends(get_db)
):
    data = await file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(400, "file too large (100MB max)")
    try:
        info = ps.import_media(data, file.filename or "photo.jpg")
    except ValueError as e:
        raise HTTPException(400, str(e))
    p = Photo(
        filename=info["filename"],
        thumb=info["thumb"],
        original_name=info["original_name"],
        width=info["width"],
        height=info["height"],
        taken_at=info["taken_at"],
        exif=info["exif"],
        is_video=info.get("is_video", False),
        album_id=album_id or None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _fmt(p)


class SyncBody(BaseModel):
    source: str  # a folder path (iCloud Drive / Photos export / any synced dir)


@router.post("/sync")
def sync(body: SyncBody, db: DbSession = Depends(get_db)):
    """import new images from a folder, skipping anything already pulled in."""
    from services import photo_sync

    try:
        return photo_sync.sync_folder(body.source, db)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/sync/macos")
def sync_macos():
    """pull from the macOS Photos library (Mac mini only) then import."""
    import shutil
    import tempfile

    from services import photo_sync

    dest = tempfile.mkdtemp(prefix="alles-photos-")
    try:
        photo_sync.pull_from_macos_photos(dest)
        return photo_sync.sync_folder(dest)
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        # the originals are already copied into the library by import; don't leak the GB-sized export
        shutil.rmtree(dest, ignore_errors=True)


@router.get("/thumb/{pid}")
def thumb(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    tp = ps.thumb_path(p.thumb)
    if tp and tp.is_file():
        return FileResponse(str(tp))
    op = ps.original_path(p.filename)  # fall back to the original if no thumb
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
    # soft-delete (1d): keep the files, hide it, record in the trash registry
    p.deleted_at = datetime.utcnow()
    db.commit()
    trash.record(db, "photo", pid, p.original_name or p.filename)
    return {"ok": True, "trashed": True}


@router.get("/trash")
def photo_trash(db: DbSession = Depends(get_db)):
    rows = (
        db.query(Photo)
        .filter(Photo.deleted_at != None)  # noqa: E711
        .order_by(Photo.deleted_at.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "thumb": f"/api/photos/thumb/{p.id}",
            "original_name": p.original_name,
            "deleted_at": p.deleted_at.isoformat() if p.deleted_at else None,
        }
        for p in rows
    ]


@router.post("/{pid}/restore")
def restore_photo(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p or p.deleted_at is None:
        raise HTTPException(404)
    p.deleted_at = None
    db.query(TrashItem).filter_by(kind="photo", ref=pid).delete()
    db.commit()
    return {"ok": True, "restored": pid}


class PatchPhoto(BaseModel):
    favorite: bool | None = None
    album_id: str | None = None
    caption: str | None = None
    keywords: list[str] | None = None
    hidden: bool | None = None


@router.patch("/{pid}")
def patch_photo(pid: str, body: PatchPhoto, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    if body.favorite is not None:
        p.favorite = body.favorite
    if body.album_id is not None:
        p.album_id = body.album_id or None
    if body.caption is not None:
        p.caption = body.caption.strip()
    if body.keywords is not None:
        p.keywords = _norm_kw(body.keywords)
    if body.hidden is not None:
        p.hidden = body.hidden
    db.commit()
    return _fmt(p)


# ── albums ──
@router.get("/albums")
def albums(db: DbSession = Depends(get_db)):
    # one grouped count for every album instead of a count query per album (N+1)
    counts = dict(
        db.query(Photo.album_id, func.count(Photo.id))
        .filter(
            Photo.album_id != None,  # noqa: E711
            Photo.deleted_at == None,  # noqa: E711
            (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
        )
        .group_by(Photo.album_id)
        .all()
    )
    return [
        {"id": a.id, "name": a.name, "count": counts.get(a.id, 0)}
        for a in db.query(Album).order_by(Album.created_at.desc()).all()
    ]


class AlbumBody(BaseModel):
    name: str


@router.post("/albums")
def add_album(body: AlbumBody, db: DbSession = Depends(get_db)):
    a = Album(name=body.name)
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "name": a.name, "count": 0}


@router.delete("/albums/{aid}")
def del_album(aid: str, db: DbSession = Depends(get_db)):
    a = db.get(Album, aid)
    if not a:
        raise HTTPException(404)
    for p in db.query(Photo).filter(Photo.album_id == aid).all():
        p.album_id = None
    db.delete(a)
    db.commit()
    return {"ok": True}
