import calendar as _cal
import json
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import (
    Contact,
    ContactField,
    ContactGroup,
    ContactGroupMember,
    get_db,
)

router = APIRouter(prefix="/api")


def _avatar_dir():
    from core.settings import data_dir

    d = data_dir() / "contact_avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fields_of(db, cid):
    rows = (
        db.query(ContactField)
        .filter(ContactField.contact_id == cid)
        .order_by(ContactField.sort_order, ContactField.id)
        .all()
    )
    return [{"id": f.id, "kind": f.kind, "label": f.label, "value": f.value} for f in rows]


def _days_until_birthday(bday: str, today: date):
    """days until the next occurrence of this birthday (year-agnostic). accepts
    YYYY-MM-DD / MM-DD / --MM-DD. returns None if unparseable."""
    m = re.search(r"(\d{1,2})-(\d{1,2})$", (bday or "").strip())
    if not m:
        return None
    mo, da = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12) or da < 1:
        return None

    def _mk(y):
        # clamp so a Feb-29 birthday lands on the 28th in a non-leap year instead
        # of throwing (which used to 500 the whole birthdays endpoint)
        return date(y, mo, min(da, _cal.monthrange(y, mo)[1]))

    this_year = _mk(today.year)
    nxt = this_year if this_year >= today else _mk(today.year + 1)
    return (nxt - today).days


def _fmt(c: Contact, db=None) -> dict:
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
        "avatar": c.avatar or "",
        "is_me": bool(c.is_me),
        "fields": _fields_of(db, c.id) if db is not None else [],
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
    return [_fmt(c, db) for c in rows]


@router.get("/contacts/birthdays")
def upcoming_birthdays(days: int = 30, today: str = "", db: DbSession = Depends(get_db)):
    """contacts with a birthday in the next `days` days (year-agnostic), soonest first."""
    try:
        base = date.fromisoformat(today) if today else date.today()
    except ValueError:
        base = date.today()
    out = []
    for c in db.query(Contact).filter(Contact.birthday != "").all():
        du = _days_until_birthday(c.birthday, base)
        if du is not None and du <= days:
            out.append({"id": c.id, "name": c.name, "birthday": c.birthday, "days_until": du})
    out.sort(key=lambda x: x["days_until"])
    return out


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
    try:
        from services import personal_index
        personal_index.index_record(db, "contact", c)
    except Exception:
        pass
    return _fmt(c, db)


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
    is_me: bool | None = None


@router.patch("/contacts/{cid}")
def patch_contact(cid: str, body: PatchContact, db: DbSession = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c:
        raise HTTPException(404)
    if body.is_me is not None:
        if body.is_me:  # only one Me card — clear it elsewhere
            db.query(Contact).filter(Contact.id != cid).update({Contact.is_me: False})
        c.is_me = body.is_me
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
    try:
        from services import personal_index
        personal_index.index_record(db, "contact", c)
    except Exception:
        pass
    return _fmt(c, db)


@router.delete("/contacts/{cid}")
def delete_contact(cid: str, db: DbSession = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c:
        raise HTTPException(404)
    db.delete(c)
    db.commit()
    try:
        from services import personal_index
        personal_index.remove_record(db, "contact", cid)
    except Exception:
        pass
    return {"ok": True}


# ── 8c: Me card, labeled fields, avatar ───────────────────────────────────────
@router.get("/contacts/me")
def get_me(db: DbSession = Depends(get_db)):
    c = db.query(Contact).filter(Contact.is_me == True).first()  # noqa: E712
    if not c:
        raise HTTPException(404)
    return _fmt(c, db)


_FIELD_KINDS = {"email", "phone", "address", "url", "social", "custom"}


class FieldBody(BaseModel):
    kind: str = "custom"
    label: str = ""
    value: str = ""
    sort_order: int = 0


@router.get("/contacts/{cid}/fields")
def list_fields(cid: str, db: DbSession = Depends(get_db)):
    return _fields_of(db, cid)


@router.post("/contacts/{cid}/fields")
def add_field(cid: str, body: FieldBody, db: DbSession = Depends(get_db)):
    if not db.get(Contact, cid):
        raise HTTPException(404)
    kind = body.kind if body.kind in _FIELD_KINDS else "custom"
    f = ContactField(
        contact_id=cid,
        kind=kind,
        label=body.label.strip(),
        value=body.value.strip(),
        sort_order=body.sort_order,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    try:
        from services import personal_index
        personal_index.index_record(db, "contact", db.query(Contact).filter_by(id=cid).first())
    except Exception:
        pass
    return {"id": f.id, "kind": f.kind, "label": f.label, "value": f.value}


@router.delete("/contacts/{cid}/fields/{fid}")
def delete_field(cid: str, fid: str, db: DbSession = Depends(get_db)):
    f = db.get(ContactField, fid)
    if not f or f.contact_id != cid:
        raise HTTPException(404)
    db.delete(f)
    db.commit()
    try:
        from services import personal_index
        personal_index.index_record(db, "contact", db.query(Contact).filter_by(id=cid).first())
    except Exception:
        pass
    return {"ok": True}


@router.post("/contacts/{cid}/avatar")
async def set_avatar(cid: str, file: UploadFile = File(...), db: DbSession = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c:
        raise HTTPException(404)
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "avatar too large (8MB max)")
    ext = (file.filename or "a.png").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
        ext = "png"
    fname = f"{cid}.{ext}"
    (_avatar_dir() / fname).write_bytes(data)
    c.avatar = fname
    db.commit()
    return _fmt(c, db)


@router.get("/contacts/{cid}/avatar")
def get_avatar(cid: str, db: DbSession = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c or not c.avatar:
        raise HTTPException(404)
    p = _avatar_dir() / c.avatar
    if not p.is_file():
        raise HTTPException(404)
    import mimetypes

    mt = mimetypes.guess_type(p.name)[0] or "image/png"
    return FileResponse(str(p), media_type=mt)


@router.delete("/contacts/{cid}/avatar")
def delete_avatar(cid: str, db: DbSession = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c:
        raise HTTPException(404)
    if c.avatar:
        try:
            (_avatar_dir() / c.avatar).unlink(missing_ok=True)
        except Exception:
            pass
        c.avatar = ""
        db.commit()
    return {"ok": True}


# ── 8c: groups (manual + smart) + duplicate detect/merge ──────────────────────
def _group_out(g: ContactGroup) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "smart": bool(g.smart),
        "rule_tag": g.rule_tag or "",
        "rule_company": g.rule_company or "",
    }


def _group_members(db, g: ContactGroup):
    if g.smart:
        out = []
        for c in db.query(Contact).all():
            tags = [t.lower() for t in json.loads(c.tags or "[]")]
            if g.rule_tag and g.rule_tag.lower() in tags:
                out.append(c)
            elif g.rule_company and g.rule_company.lower() in (c.company or "").lower():
                out.append(c)
        return out
    ids = [
        m.contact_id
        for m in db.query(ContactGroupMember).filter(ContactGroupMember.group_id == g.id).all()
    ]
    return db.query(Contact).filter(Contact.id.in_(ids)).all() if ids else []


class GroupBody(BaseModel):
    name: str
    smart: bool = False
    rule_tag: str = ""
    rule_company: str = ""


@router.get("/contacts/groups")
def list_groups(db: DbSession = Depends(get_db)):
    return [_group_out(g) for g in db.query(ContactGroup).order_by(ContactGroup.name).all()]


@router.post("/contacts/groups")
def create_group(body: GroupBody, db: DbSession = Depends(get_db)):
    g = ContactGroup(
        name=body.name,
        smart=body.smart,
        rule_tag=body.rule_tag.strip(),
        rule_company=body.rule_company.strip(),
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return _group_out(g)


@router.delete("/contacts/groups/{gid}")
def delete_group(gid: str, db: DbSession = Depends(get_db)):
    g = db.get(ContactGroup, gid)
    if not g:
        raise HTTPException(404)
    db.query(ContactGroupMember).filter(ContactGroupMember.group_id == gid).delete()
    db.delete(g)
    db.commit()
    return {"ok": True}


@router.get("/contacts/groups/{gid}/members")
def group_members(gid: str, db: DbSession = Depends(get_db)):
    g = db.get(ContactGroup, gid)
    if not g:
        raise HTTPException(404)
    return [_fmt(c, db) for c in _group_members(db, g)]


class MemberBody(BaseModel):
    contact_id: str


@router.post("/contacts/groups/{gid}/members")
def add_member(gid: str, body: MemberBody, db: DbSession = Depends(get_db)):
    g = db.get(ContactGroup, gid)
    if not g:
        raise HTTPException(404)
    if g.smart:
        raise HTTPException(400, "smart groups compute membership automatically")
    exists = (
        db.query(ContactGroupMember)
        .filter(
            ContactGroupMember.group_id == gid, ContactGroupMember.contact_id == body.contact_id
        )
        .first()
    )
    if not exists:
        db.add(ContactGroupMember(group_id=gid, contact_id=body.contact_id))
        db.commit()
    return {"ok": True}


@router.delete("/contacts/groups/{gid}/members/{cid}")
def remove_member(gid: str, cid: str, db: DbSession = Depends(get_db)):
    db.query(ContactGroupMember).filter(
        ContactGroupMember.group_id == gid, ContactGroupMember.contact_id == cid
    ).delete()
    db.commit()
    return {"ok": True}


@router.get("/contacts/duplicates")
def duplicates(db: DbSession = Depends(get_db)):
    """cluster likely-duplicate contacts by normalized name or a shared email (union-find)."""
    contacts = db.query(Contact).all()
    parent = {c.id: c.id for c in contacts}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    by_name, by_email = {}, {}
    for c in contacts:
        nm = (c.name or "").strip().lower()
        if nm:
            by_name.setdefault(nm, []).append(c.id)
        for em in [c.email] + [
            f.value
            for f in db.query(ContactField)
            .filter(ContactField.contact_id == c.id, ContactField.kind == "email")
            .all()
        ]:
            em = (em or "").strip().lower()
            if em:
                by_email.setdefault(em, []).append(c.id)
    for ids in list(by_name.values()) + list(by_email.values()):
        for other in ids[1:]:
            union(ids[0], other)
    clusters = {}
    for c in contacts:
        clusters.setdefault(find(c.id), []).append(c)
    out = []
    cmap = {c.id: c for c in contacts}
    for root, members in clusters.items():
        if len(members) >= 2:
            out.append({"contacts": [_fmt(cmap[m.id], db) for m in members]})
    return out


class MergeBody(BaseModel):
    primary_id: str
    other_id: str


@router.post("/contacts/merge")
def merge_contacts(body: MergeBody, db: DbSession = Depends(get_db)):
    p = db.get(Contact, body.primary_id)
    o = db.get(Contact, body.other_id)
    if not p or not o:
        raise HTTPException(404)
    # fill empty scalar fields on the primary from the other
    for attr in ("email", "phone", "company", "title", "address", "birthday", "website"):
        if not (getattr(p, attr) or "").strip() and (getattr(o, attr) or "").strip():
            setattr(p, attr, getattr(o, attr))
    # union tags
    ptags = json.loads(p.tags or "[]")
    for t in json.loads(o.tags or "[]"):
        if t not in ptags:
            ptags.append(t)
    p.tags = json.dumps(ptags)
    # append notes
    if (o.notes or "").strip():
        p.notes = ((p.notes or "").strip() + "\n" + o.notes).strip()
    # move labeled fields + group memberships
    db.query(ContactField).filter(ContactField.contact_id == o.id).update(
        {ContactField.contact_id: p.id}
    )
    db.query(ContactGroupMember).filter(ContactGroupMember.contact_id == o.id).update(
        {ContactGroupMember.contact_id: p.id}
    )
    p.updated_at = datetime.utcnow()
    db.delete(o)
    db.commit()
    return _fmt(p, db)
