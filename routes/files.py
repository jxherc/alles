from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import FileComment, FileTag, get_db
from services import files_store as fs
from services import fileversions, trash

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
    """path → {tags, color, starred} for every tagged file, to decorate listings cheaply."""
    out = {}
    for r in db.query(FileTag).all():
        out[r.path] = {
            "tags": [t for t in (r.tags or "").split(",") if t],
            "color": r.color or "",
            "starred": bool(r.starred),
        }
    return out


def _decorate(items, tmap):
    for it in items:
        meta = tmap.get(it["path"])
        it["tags"] = meta["tags"] if meta else []
        it["color"] = meta["color"] if meta else ""
        it["starred"] = meta["starred"] if meta else False
    return items


def _comment_counts(db) -> dict:
    """path → number of comments (roots + replies), to badge listings (6c)."""
    out = {}
    for (p,) in db.query(FileComment.path).all():
        out[p] = out.get(p, 0) + 1
    return out


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
    cc = _comment_counts(db)
    for it in d["items"]:
        it["comments"] = cc.get(it["path"], 0)
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


class StarBody(BaseModel):
    starred: bool = True


@router.put("/star")
def set_star(path: str = Query(...), body: StarBody = None, db: DbSession = Depends(get_db)):
    if not (path or "").strip():
        raise HTTPException(400, "path required")
    body = body or StarBody()
    r = db.query(FileTag).filter(FileTag.path == path).first()
    if not r:
        r = FileTag(path=path)
        db.add(r)
    r.starred = bool(body.starred)
    db.commit()
    return {"path": path, "starred": bool(r.starred)}


@router.get("/starred")
def list_starred(db: DbSession = Depends(get_db)):
    rows = db.query(FileTag).filter(FileTag.starred == True).all()  # noqa: E712
    items = [
        {
            "path": r.path,
            "tags": [t for t in (r.tags or "").split(",") if t],
            "color": r.color or "",
        }
        for r in rows
    ]
    items.sort(key=lambda x: x["path"].lower())
    return {"items": items}


@router.get("/quota")
def quota():
    """bytes used by the files vault + the underlying disk's total/free (6a)."""
    import shutil

    base = fs.files_dir()
    used = 0
    for p in base.rglob("*"):
        try:
            if p.is_file():
                used += p.stat().st_size
        except OSError:
            pass
    try:
        du = shutil.disk_usage(str(base))
        total, free = du.total, du.free
    except OSError:
        total = free = 0
    return {"used": used, "total": total, "free": free}


@router.get("/duplicates")
def duplicates():
    """group files with identical content (exact SHA-256) — exact dedup only (6b)."""
    import hashlib
    from collections import defaultdict

    base = fs.files_dir()
    groups = defaultdict(list)
    for p in base.rglob("*"):
        try:
            if not p.is_file() or p.stat().st_size == 0:
                continue
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            groups[h].append(
                {"path": str(p.relative_to(base)).replace("\\", "/"), "size": p.stat().st_size}
            )
        except OSError:
            pass
    out = [
        {"hash": h, "size": items[0]["size"], "paths": [i["path"] for i in items]}
        for h, items in groups.items()
        if len(items) > 1
    ]
    out.sort(key=lambda g: -len(g["paths"]))
    return {"groups": out}


@router.get("/preview")
def preview(path: str = Query(...)):
    """office / text preview (6b). docx → text (python-docx); xlsx → openpyxl if present; txt/md → raw."""
    try:
        p = fs.abspath(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not p.is_file():
        raise HTTPException(404, "not found")
    ext = p.suffix.lower()
    if ext == ".docx":
        try:
            import html as _html

            from docx import Document

            doc = Document(str(p))
            paras = [para.text for para in doc.paragraphs]
            text = "\n".join(paras)
            html = "".join(f"<p>{_html.escape(t)}</p>" if t.strip() else "<br>" for t in paras)
            return {"kind": "docx", "text": text, "html": html}
        except Exception as e:
            return {"kind": "docx", "error": f"couldn't read docx: {str(e)[:120]}"}
    if ext == ".xlsx":
        try:
            import openpyxl

            wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
            ws = wb.active
            rows = [
                [("" if c is None else str(c)) for c in row]
                for row in ws.iter_rows(values_only=True)
            ]
            return {"kind": "xlsx", "rows": rows[:200]}
        except ImportError:
            return {"kind": "xlsx", "error": "openpyxl not installed (pip install openpyxl)"}
        except Exception as e:
            return {"kind": "xlsx", "error": f"couldn't read xlsx: {str(e)[:120]}"}
    if ext in (".txt", ".md", ".markdown", ".csv", ".log", ".json"):
        try:
            return {"kind": "text", "text": p.read_text("utf-8", errors="replace")[:20000]}
        except OSError:
            return {"kind": "text", "error": "couldn't read file"}
    return {"kind": "unsupported"}


@router.get("/activity")
def activity(days: int = 30, limit: int = 100):
    """recent file changes, newest first (6b)."""
    import time

    base = fs.files_dir()
    cutoff = time.time() - days * 86400
    out = []
    for p in base.rglob("*"):
        try:
            if not p.is_file():
                continue
            st = p.stat()
            if st.st_mtime < cutoff:
                continue
            out.append(
                {
                    "path": str(p.relative_to(base)).replace("\\", "/"),
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                }
            )
        except OSError:
            pass
    out.sort(key=lambda x: -x["mtime"])
    return {"items": out[:limit]}


# ── file comments (6c) — threaded like DocComment, keyed on a files-relative path ──
class CommentBody(BaseModel):
    path: str = ""
    body: str = ""
    author: str = "me"
    parent_id: str | None = None


def _cdict(c):
    return {
        "id": c.id,
        "path": c.path,
        "body": c.body or "",
        "author": c.author or "me",
        "parent_id": c.parent_id,
        "resolved": bool(c.resolved),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("/comments")
def list_comments(path: str = Query(...), db: DbSession = Depends(get_db)):
    rows = db.query(FileComment).filter_by(path=path).order_by(FileComment.created_at.asc()).all()
    threads = []
    for root in [c for c in rows if c.parent_id is None]:
        t = _cdict(root)
        t["replies"] = [_cdict(c) for c in rows if c.parent_id == root.id]
        threads.append(t)
    return {"threads": threads}


@router.post("/comments")
def add_comment(body: CommentBody, db: DbSession = Depends(get_db)):
    """create a thread root (needs path) or a reply (needs parent_id)."""
    if not (body.body or "").strip():
        raise HTTPException(400, "comment body required")
    if body.parent_id:
        parent = db.query(FileComment).filter_by(id=body.parent_id).first()
        if not parent:
            raise HTTPException(404, "parent comment not found")
        root = (
            parent
            if parent.parent_id is None
            else db.query(FileComment).filter_by(id=parent.parent_id).first()
        )
        c = FileComment(
            path=root.path, body=body.body.strip(), author=body.author or "me", parent_id=root.id
        )
    else:
        if not (body.path or "").strip():
            raise HTTPException(400, "path required")
        c = FileComment(path=body.path.strip(), body=body.body.strip(), author=body.author or "me")
    db.add(c)
    db.commit()
    db.refresh(c)
    return _cdict(c)


@router.post("/comments/{cid}/resolve")
def resolve_comment(cid: str, db: DbSession = Depends(get_db)):
    c = db.query(FileComment).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "comment not found")
    root = c if c.parent_id is None else db.query(FileComment).filter_by(id=c.parent_id).first()
    root.resolved = not bool(root.resolved)
    db.commit()
    return {"id": root.id, "resolved": bool(root.resolved)}


@router.delete("/comments/{cid}")
def delete_comment(cid: str, db: DbSession = Depends(get_db)):
    """delete a comment; deleting a root also drops its replies."""
    c = db.query(FileComment).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "comment not found")
    if c.parent_id is None:
        db.query(FileComment).filter_by(parent_id=c.id).delete()
    db.delete(c)
    db.commit()
    return {"ok": True}


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
def delete(path: str = Query(...), db: DbSession = Depends(get_db)):
    if not (path or "").strip():
        raise HTTPException(400, "won't delete the root")
    try:
        p = fs.abspath(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not p.exists():
        raise HTTPException(404, "not found")
    trash.soft_delete_file(db, path, p)  # move to trash instead of hard-delete (1d)
    return {"ok": True, "trashed": True}


@router.get("/trash")
def list_trash(db: DbSession = Depends(get_db)):
    items = trash.list_items(db, kind="file")
    return [
        {
            "id": it.id,
            "ref": it.ref,
            "name": it.name,
            "trashed_at": it.trashed_at.isoformat() if it.trashed_at else None,
        }
        for it in items
    ]


class TrashAction(BaseModel):
    id: str


@router.post("/trash/restore")
def restore_trash(body: TrashAction, db: DbSession = Depends(get_db)):
    it = trash.get(db, body.id)
    if not it or it.kind != "file":
        raise HTTPException(404)
    trash.restore_file(db, it, fs.abspath(it.ref))
    return {"ok": True, "restored": it.ref}


@router.post("/trash/purge")
def purge_trash(db: DbSession = Depends(get_db)):
    return {"purged": trash.purge_expired(db)}


@router.post("/upload")
async def upload(
    path: str = Form(""), file: UploadFile = File(...), db: DbSession = Depends(get_db)
):
    data = await file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(400, "file too large (100MB max)")
    name = Path(file.filename).name
    rel = f"{path}/{name}" if path else name
    try:
        existing = fs.abspath(rel)
        if existing.is_file():  # overwrite → snapshot the old content first (1e)
            fileversions.snapshot(db, rel, existing)
        return fs.save_upload(path, file.filename, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/versions")
def list_versions(path: str = Query(...), db: DbSession = Depends(get_db)):
    return [
        {
            "id": v.id,
            "size": v.size,
            "sha": v.sha[:12],
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in fileversions.list_versions(db, path)
    ]


class RestoreVersion(BaseModel):
    path: str
    id: str


@router.post("/versions/restore")
def restore_version(body: RestoreVersion, db: DbSession = Depends(get_db)):
    # snapshot the current content first so a restore is itself undoable
    cur = fs.abspath(body.path)
    if cur.is_file():
        fileversions.snapshot(db, body.path, cur)
    v = fileversions.restore(db, body.id, cur)
    if not v:
        raise HTTPException(404)
    return {"ok": True, "restored": body.path}
