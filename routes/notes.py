from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.database import get_db
from services import notes_vault
from services.vault_md import DocumentConflictError

router = APIRouter(prefix="/api")


def _index(db, nid):
    # best-effort: a note write must never fail on an index hiccup
    try:
        from services import personal_index

        personal_index.index_record(db, "note", nid)
    except Exception:
        pass


def _unindex(db, nid):
    try:
        from services import personal_index

        personal_index.remove_record(db, "note", nid)
    except Exception:
        pass


@router.get("/notes")
def list_notes(q: str = "", tag: str = "", archived: bool = False, limit: int = 0, offset: int = 0):
    return notes_vault.list_notes(q=q, tag=tag, archived=archived, limit=limit, offset=offset)


# GET /api/notes/tags — every tag in use, for filter chips / autocomplete
@router.get("/notes/tags")
def list_tags():
    return notes_vault.tag_counts()


# title/content are Optional/None so a partial PATCH (e.g. a pin toggle that only
# sends {pinned:true}) leaves them untouched.
class NoteBody(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    pinned: Optional[bool] = None
    tags: Optional[list[str] | str] = None
    items: Optional[list[dict]] = None
    due: Optional[str] = None
    expected_hash: Optional[str] = None


@router.post("/notes")
def create_note(body: NoteBody, db: DbSession = Depends(get_db)):
    n = notes_vault.create(
        title=body.title or "",
        content=body.content or "",
        pinned=bool(body.pinned),
        tags=body.tags,
        items=body.items,
        due=body.due or "",
    )
    _index(db, n["id"])
    return n


@router.patch("/notes/{nid}")
def update_note(nid: str, body: NoteBody, db: DbSession = Depends(get_db)):
    partial = {}
    for k in ("title", "content", "pinned", "tags", "items", "due"):
        v = getattr(body, k)
        if v is not None:
            partial[k] = v
    try:
        n = notes_vault.update(nid, partial, expected_hash=body.expected_hash)
    except DocumentConflictError as exc:
        raise ApiError(409, "document_conflict", str(exc)) from exc
    if n is None:
        raise HTTPException(404)
    if n["id"] != nid:  # a retitle renamed the file → re-key the index
        _unindex(db, nid)
    _index(db, n["id"])
    return n


class ArchiveBody(BaseModel):
    archived: bool = True


@router.post("/notes/{nid}/archive")
def archive_note(nid: str, body: ArchiveBody, db: DbSession = Depends(get_db)):
    n = notes_vault.set_archived(nid, body.archived)
    if n is None:
        raise HTTPException(404)
    return n


@router.delete("/notes/{nid}")
def delete_note(nid: str, db: DbSession = Depends(get_db)):
    if notes_vault.get(nid) is None:
        raise HTTPException(404)
    notes_vault.delete(nid)
    _unindex(db, nid)
    return {"ok": True}
