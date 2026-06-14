import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Contact

router = APIRouter(prefix="/api")


def _fmt(c: Contact) -> dict:
    return {
        "id": c.id, "name": c.name, "email": c.email,
        "phone": c.phone, "notes": c.notes,
        "tags": json.loads(c.tags or "[]"),
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


@router.get("/contacts")
def list_contacts(q: str = Query(""), db: DbSession = Depends(get_db)):
    qs = db.query(Contact)
    if q:
        qs = qs.filter(Contact.name.ilike(f"%{q}%"))
    return [_fmt(c) for c in qs.order_by(Contact.name).all()]


@router.get("/contacts/export")
def export_contacts(db: DbSession = Depends(get_db)):
    from fastapi.responses import PlainTextResponse
    from services.vcard import to_vcard
    cards = [_fmt(c) for c in db.query(Contact).order_by(Contact.name).all()]
    return PlainTextResponse(to_vcard(cards), media_type="text/vcard",
                             headers={"content-disposition": "attachment; filename=contacts.vcf"})


class ImportBody(BaseModel):
    vcard: str


@router.post("/contacts/import")
def import_contacts(body: ImportBody, db: DbSession = Depends(get_db)):
    from services.vcard import parse_vcards
    n = 0
    for c in parse_vcards(body.vcard):
        db.add(Contact(name=c["name"], email=c.get("email", ""), phone=c.get("phone", ""),
                       notes=c.get("notes", ""), tags="[]"))
        n += 1
    db.commit()
    return {"imported": n}


class CreateContact(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    notes: str = ""
    tags: list[str] = []


@router.post("/contacts")
def create_contact(body: CreateContact, db: DbSession = Depends(get_db)):
    c = Contact(name=body.name, email=body.email, phone=body.phone,
                notes=body.notes, tags=json.dumps(body.tags))
    db.add(c); db.commit(); db.refresh(c)
    return _fmt(c)


class PatchContact(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


@router.patch("/contacts/{cid}")
def patch_contact(cid: str, body: PatchContact, db: DbSession = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c: raise HTTPException(404)
    if body.name is not None:  c.name = body.name
    if body.email is not None: c.email = body.email
    if body.phone is not None: c.phone = body.phone
    if body.notes is not None: c.notes = body.notes
    if body.tags is not None:  c.tags = json.dumps(body.tags)
    c.updated_at = datetime.utcnow()
    db.commit()
    return _fmt(c)


@router.delete("/contacts/{cid}")
def delete_contact(cid: str, db: DbSession = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c: raise HTTPException(404)
    db.delete(c); db.commit()
    return {"ok": True}
