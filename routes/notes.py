from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Note

router = APIRouter(prefix="/api")


def _tags_list(s) -> list[str]:
    return [t for t in (s or "").split(",") if t]


def _norm_tags(tags) -> str:
    """accept a list or a comma string → clean, deduped, lowercase csv."""
    if isinstance(tags, str):
        tags = tags.split(",")
    seen, out = set(), []
    for t in tags or []:
        t = str(t).strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return ",".join(out)


def _fmt(n: Note) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "pinned": n.pinned,
        "archived": n.archived,
        "tags": _tags_list(getattr(n, "tags", "")),
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


@router.get("/notes")
def list_notes(q: str = "", tag: str = "", archived: bool = False,
               db: DbSession = Depends(get_db)):
    rows = (
        db.query(Note)
        .filter(Note.archived == archived)
        .order_by(Note.pinned.desc(), Note.updated_at.desc())
        .all()
    )
    if tag:
        t = tag.strip().lower()
        rows = [n for n in rows if t in _tags_list(n.tags)]
    if q:
        ql = q.lower()
        rows = [
            n for n in rows
            if ql in (n.title or "").lower()
            or ql in (n.content or "").lower()
            or ql in (n.tags or "").lower()
        ]
    return [_fmt(n) for n in rows]


# GET /api/notes/tags — every tag in use, for filter chips / autocomplete
@router.get("/notes/tags")
def list_tags(db: DbSession = Depends(get_db)):
    counts = {}
    for n in db.query(Note).filter(Note.archived == False).all():
        for t in _tags_list(n.tags):
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(counts.items())]


class NoteBody(BaseModel):
    title: str = ""
    content: str = ""
    pinned: Optional[bool] = None
    tags: Optional[list[str] | str] = None


@router.post("/notes")
def create_note(body: NoteBody, db: DbSession = Depends(get_db)):
    n = Note(title=body.title, content=body.content, tags=_norm_tags(body.tags))
    db.add(n)
    db.commit()
    db.refresh(n)
    return _fmt(n)


@router.patch("/notes/{nid}")
def update_note(nid: str, body: NoteBody, db: DbSession = Depends(get_db)):
    n = db.get(Note, nid)
    if not n:
        raise HTTPException(404)
    if body.title is not None:
        n.title = body.title
    if body.content is not None:
        n.content = body.content
    if body.pinned is not None:
        n.pinned = body.pinned
    if body.tags is not None:
        n.tags = _norm_tags(body.tags)
    n.updated_at = datetime.utcnow()
    db.commit()
    return _fmt(n)


class ArchiveBody(BaseModel):
    archived: bool = True


@router.post("/notes/{nid}/archive")
def archive_note(nid: str, body: ArchiveBody, db: DbSession = Depends(get_db)):
    n = db.get(Note, nid)
    if not n:
        raise HTTPException(404)
    n.archived = body.archived
    n.updated_at = datetime.utcnow()
    db.commit()
    return _fmt(n)


@router.delete("/notes/{nid}")
def delete_note(nid: str, db: DbSession = Depends(get_db)):
    n = db.get(Note, nid)
    if not n:
        raise HTTPException(404)
    db.delete(n)
    db.commit()
    return {"ok": True}
