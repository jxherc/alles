from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Note

router = APIRouter(prefix="/api")


def _fmt(n: Note) -> dict:
    return {
        "id":       n.id,
        "title":    n.title,
        "content":  n.content,
        "pinned":   n.pinned,
        "archived": n.archived,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


@router.get("/notes")
def list_notes(db: DbSession = Depends(get_db)):
    rows = db.query(Note).filter(Note.archived == False).order_by(
        Note.pinned.desc(), Note.updated_at.desc()
    ).all()
    return [_fmt(n) for n in rows]


class NoteBody(BaseModel):
    title: str = ""
    content: str = ""
    pinned: Optional[bool] = None


@router.post("/notes")
def create_note(body: NoteBody, db: DbSession = Depends(get_db)):
    n = Note(title=body.title, content=body.content)
    db.add(n); db.commit(); db.refresh(n)
    return _fmt(n)


@router.patch("/notes/{nid}")
def update_note(nid: str, body: NoteBody, db: DbSession = Depends(get_db)):
    n = db.get(Note, nid)
    if not n: raise HTTPException(404)
    if body.title is not None:   n.title = body.title
    if body.content is not None: n.content = body.content
    if body.pinned is not None:  n.pinned = body.pinned
    from datetime import datetime
    n.updated_at = datetime.utcnow()
    db.commit(); return _fmt(n)


@router.delete("/notes/{nid}")
def delete_note(nid: str, db: DbSession = Depends(get_db)):
    n = db.get(Note, nid)
    if not n: raise HTTPException(404)
    db.delete(n); db.commit()
    return {"ok": True}
