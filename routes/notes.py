import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Note, get_db
from services import lifecycle

router = APIRouter(prefix="/api")


def _items_list(s) -> list[dict]:
    try:
        rows = json.loads(s or "[]")
    except Exception:
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and "text" in r:
            out.append({"text": str(r["text"]), "done": bool(r.get("done"))})
    return out


def _norm_items(items) -> str:
    clean = []
    for r in items or []:
        if isinstance(r, dict) and str(r.get("text", "")).strip():
            clean.append({"text": str(r["text"]).strip(), "done": bool(r.get("done"))})
    return json.dumps(clean)


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
        "items": _items_list(getattr(n, "items", "[]")),
        "due": getattr(n, "due", "") or "",
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


@router.get("/notes")
def list_notes(q: str = "", tag: str = "", archived: bool = False,
               db: DbSession = Depends(get_db)):
    q0 = db.query(Note)
    q0 = lifecycle.inactive(q0) if archived else lifecycle.active(q0)
    rows = q0.order_by(Note.pinned.desc(), Note.updated_at.desc()).all()
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
    for n in lifecycle.active(db.query(Note)).all():
        for t in _tags_list(n.tags):
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(counts.items())]


class NoteBody(BaseModel):
    title: str = ""
    content: str = ""
    pinned: Optional[bool] = None
    tags: Optional[list[str] | str] = None
    items: Optional[list[dict]] = None
    due: Optional[str] = None


@router.post("/notes")
def create_note(body: NoteBody, db: DbSession = Depends(get_db)):
    n = Note(
        title=body.title,
        content=body.content,
        pinned=bool(body.pinned),
        tags=_norm_tags(body.tags),
        items=_norm_items(body.items),
        due=(body.due or "").strip(),
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    try:
        from services import personal_index
        personal_index.index_record(db, "note", n)
    except Exception:
        pass
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
    if body.items is not None:
        n.items = _norm_items(body.items)
    if body.due is not None:
        n.due = body.due.strip()
    n.updated_at = datetime.utcnow()
    db.commit()
    try:
        from services import personal_index
        personal_index.index_record(db, "note", n)
    except Exception:
        pass
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
    try:
        from services import personal_index
        personal_index.remove_record(db, "note", nid)
    except Exception:
        pass
    return {"ok": True}
