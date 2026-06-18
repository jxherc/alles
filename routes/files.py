from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import FileTag, get_db
from services import files_store as fs

router = APIRouter(prefix="/api/files")


def _norm_tags(tags) -> list[str]:
    """lowercase, trim, drop blanks, dedup (order-stable)."""
    seen, out = set(), []
    for t in tags or []:
        t = str(t).strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _tag_map(db) -> dict:
    """path → {tags, color} for every tagged file, to decorate listings cheaply."""
    out = {}
    for r in db.query(FileTag).all():
        out[r.path] = {
            "tags": [t for t in (r.tags or "").split(",") if t],
            "color": r.color or "",
        }
    return out


def _decorate(items, tmap):
    for it in items:
        meta = tmap.get(it["path"])
        it["tags"] = meta["tags"] if meta else []
        it["color"] = meta["color"] if meta else ""
    return items


@router.get("/list")
def list_files(
    path: str = Query(""),
    sort: str = Query("name"),
    order: str = Query(""),
    db: DbSession = Depends(get_db),
):
    try:
        d = fs.listdir(path, sort=sort, order=order)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _decorate(d["items"], _tag_map(db))
    return d


class TagBody(BaseModel):
    tags: list[str] | None = None
    color: str | None = None


@router.get("/tags")
def get_tags(path: str = Query(...), db: DbSession = Depends(get_db)):
    r = db.query(FileTag).filter(FileTag.path == path).first()
    if not r:
        return {"path": path, "tags": [], "color": ""}
    return {
        "path": path,
        "tags": [t for t in (r.tags or "").split(",") if t],
        "color": r.color or "",
    }


@router.put("/tags")
def set_tags(path: str = Query(...), body: TagBody = None, db: DbSession = Depends(get_db)):
    body = body or TagBody()
    r = db.query(FileTag).filter(FileTag.path == path).first()
    if not r:
        r = FileTag(path=path)
        db.add(r)
    if body.tags is not None:
        r.tags = ",".join(_norm_tags(body.tags))
    if body.color is not None:
        r.color = body.color.strip()
    db.commit()
    return {
        "path": path,
        "tags": [t for t in (r.tags or "").split(",") if t],
        "color": r.color or "",
    }


@router.get("/by-tag")
def files_by_tag(tag: str = Query(...), db: DbSession = Depends(get_db)):
    t = tag.strip().lower()
    out = []
    for r in db.query(FileTag).all():
        tags = [x for x in (r.tags or "").split(",") if x]
        if t in tags:
            out.append({"path": r.path, "tags": tags, "color": r.color or ""})
    out.sort(key=lambda x: x["path"].lower())
    return {"tag": t, "items": out}


@router.get("/tags/all")
def all_tags(db: DbSession = Depends(get_db)):
    tags, colors = set(), {}
    for r in db.query(FileTag).all():
        for x in (r.tags or "").split(","):
            if x:
                tags.add(x)
        if r.color:
            colors[r.path] = r.color
    return {"tags": sorted(tags), "colors": colors}


@router.get("/search")
def search_files(q: str = Query(...), limit: int = 100):
    return fs.search(q, limit)


@router.get("/smart/{kind}")
def smart_folder(kind: str, days: int = 30, limit: int = 200):
    try:
        return fs.smart(kind, days=days, limit=limit)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/read")
def read_file(path: str = Query(...)):
    try:
        return fs.read_text(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/raw")
def raw_file(path: str = Query(...), download: bool = False):
    try:
        p = fs.abspath(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not p.is_file():
        raise HTTPException(404)
    # inline by default so images preview; download=1 forces a save dialog
    return FileResponse(str(p), filename=p.name if download else None)


class MkdirBody(BaseModel):
    path: str


@router.post("/mkdir")
def mkdir(body: MkdirBody):
    try:
        return fs.mkdir(body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class RenameBody(BaseModel):
    path: str
    to: str


@router.post("/rename")
def rename(body: RenameBody):
    try:
        return fs.rename(body.path, body.to)
    except FileNotFoundError:
        raise HTTPException(404, "not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/delete")
def delete(path: str = Query(...)):
    try:
        return fs.delete(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/upload")
async def upload(path: str = Form(""), file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(400, "file too large (100MB max)")
    try:
        return fs.save_upload(path, file.filename, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
