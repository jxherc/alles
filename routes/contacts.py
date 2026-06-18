import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Contact, get_db

router = APIRouter(prefix="/api")


def _fmt(c: Contact) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "notes": c.notes,
        "tags": json.loads(c.tags or "[]"),
        "company": c.company or "",
        "title": c.title or "",
        "address": c.address or "",
        "birthday": c.birthday or "",
        "website": c.website or "",
        "favorite": bool(c.favorite),
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


_RICH = ("company", "title", "address", "birthday", "website")


@router.get("/contacts")
def list_contacts(
    q: str = Query(""), favorites: bool = Query(False), db: DbSession = Depends(get_db)
):
    qs = db.query(Contact)
    if favorites:
        qs = qs.filter(Contact.favorite == True)  # noqa: E712
    rows = qs.order_by(Contact.name).all()
    if q:
        ql = q.lower()
        rows = [
            c
            for c in rows
            if ql in (c.name or "").lower()
            or ql in (c.email or "").lower()
            or ql in (c.phone or "").lower()
            or ql in (c.company or "").lower()
        ]
    return [_fmt(c) for c in rows]


@router.get("/contacts/export")
def export_contacts(db: DbSession = Depends(get_db)):
    from fastapi.responses import PlainTextResponse

    from services.vcard import to_vcard

    cards = [_fmt(c) for c in db.query(Contact).order_by(Contact.name).all()]
    return PlainTextResponse(
        to_vcard(cards),
        media_type="text/vcard",
        headers={"content-disposition": "attachment; filename=contacts.vcf"},
    )


class ImportBody(BaseModel):
    vcard: str


@router.post("/contacts/import")
def import_contacts(body: ImportBody, db: DbSession = Depends(get_db)):
    from services.vcard import parse_vcards

    n = 0
    for c in parse_vcards(body.vcard):
        db.add(
            Contact(
                name=c["name"],
                email=c.get("email", ""),
                phone=c.get("phone", ""),
                notes=c.get("notes", ""),
                tags="[]",
                company=c.get("company", ""),
                title=c.get("title", ""),
                address=c.get("address", ""),
                birthday=c.get("birthday", ""),
                website=c.get("website", ""),
            )
        )
        n += 1
    db.commit()
    return {"imported": n}


class CreateContact(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    notes: str = ""
    tags: list[str] = []
    company: str = ""
    title: str = ""
    address: str = ""
    birthday: str = ""
    website: str = ""


@router.post("/contacts")
def create_contact(body: CreateContact, db: DbSession = Depends(get_db)):
    c = Contact(
        name=body.name,
        email=body.email,
        phone=body.phone,
        notes=body.notes,
        tags=json.dumps(body.tags),
        company=body.company,
        title=body.title,
        address=body.address,
        birthday=body.birthday,
        website=body.website,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _fmt(c)


class PatchContact(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    company: str | None = None
    title: str | None = None
    address: str | None = None
    birthday: str | None = None
    website: str | None = None
    favorite: bool | None = None


@router.patch("/contacts/{cid}")
def patch_contact(cid: str, body: PatchContact, db: DbSession = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c:
        raise HTTPException(404)
    if body.name is not None:
        c.name = body.name
    if body.email is not None:
        c.email = body.email
    if body.phone is not None:
        c.phone = body.phone
    if body.notes is not None:
        c.notes = body.notes
    if body.tags is not None:
        c.tags = json.dumps(body.tags)
    for f in _RICH:
        v = getattr(body, f)
        if v is not None:
            setattr(c, f, v)
    if body.favorite is not None:
        c.favorite = body.favorite
    c.updated_at = datetime.utcnow()
    db.commit()
    return _fmt(c)


@router.delete("/contacts/{cid}")
def delete_contact(cid: str, db: DbSession = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c:
        raise HTTPException(404)
    db.delete(c)
    db.commit()
    return {"ok": True}
