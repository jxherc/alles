"""Ordinary contact saves shared by Contacts and Aide."""

import json

from sqlalchemy.orm import Session

from core.database import Contact


def save_contact(
    db: Session,
    *,
    name: str,
    email: str = "",
    phone: str = "",
    notes: str = "",
    tags: list[str] | None = None,
    company: str = "",
    title: str = "",
    address: str = "",
    birthday: str = "",
    website: str = "",
) -> Contact:
    contact = Contact(
        name=name,
        email=email,
        phone=phone,
        notes=notes,
        tags=json.dumps(tags if tags is not None else []),
        company=company,
        title=title,
        address=address,
        birthday=birthday,
        website=website,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    try:
        from services import personal_index

        personal_index.index_record(db, "contact", contact)
    except Exception:
        pass
    return contact
