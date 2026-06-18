from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, CookbookEntry

router = APIRouter(prefix="/api")


def _fmt(e: CookbookEntry) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "description": e.description,
        "prompt": e.prompt,
        "created_at": e.created_at.isoformat(),
    }


@router.get("/cookbook")
def list_entries(db: DbSession = Depends(get_db)):
    return [_fmt(e) for e in db.query(CookbookEntry).order_by(CookbookEntry.name).all()]


class EntryBody(BaseModel):
    name: str  # slash-command style, e.g. "summarize"
    description: str = ""
    prompt: str


@router.post("/cookbook")
def create_entry(body: EntryBody, db: DbSession = Depends(get_db)):
    # sanitize name — lowercase, no spaces
    name = body.name.lower().replace(" ", "-")
    e = CookbookEntry(name=name, description=body.description, prompt=body.prompt)
    db.add(e)
    db.commit()
    db.refresh(e)
    return _fmt(e)


@router.patch("/cookbook/{eid}")
def update_entry(eid: str, body: EntryBody, db: DbSession = Depends(get_db)):
    e = db.get(CookbookEntry, eid)
    if not e:
        raise HTTPException(404)
    e.name = body.name.lower().replace(" ", "-")
    e.description = body.description
    e.prompt = body.prompt
    db.commit()
    return _fmt(e)


@router.delete("/cookbook/{eid}")
def delete_entry(eid: str, db: DbSession = Depends(get_db)):
    e = db.get(CookbookEntry, eid)
    if not e:
        raise HTTPException(404)
    db.delete(e)
    db.commit()
    return {"ok": True}
