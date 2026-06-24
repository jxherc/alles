"""4a - contact relationship graph: typed edges between contacts + neighbor queries + smart-invite
suggestions. links are stored both directions (with the inverse kind) so neighbors() is a cheap lookup.
"""

from core.database import Contact, ContactLink

# kind -> its inverse from the other contact's point of view. symmetric kinds map to themselves.
_INVERSE = {
    "spouse": "spouse",
    "partner": "partner",
    "sibling": "sibling",
    "friend": "friend",
    "colleague": "colleague",
    "manager": "report",
    "report": "manager",
    "parent": "child",
    "child": "parent",
    "mentor": "mentee",
    "mentee": "mentor",
}


def _inverse(kind):
    return _INVERSE.get((kind or "").lower(), kind or "")


def link(db, from_id, to_id, kind, *, reciprocal=True):
    """create a typed edge a->b (and b->a with the inverse kind unless reciprocal=False)."""
    if from_id == to_id:
        raise ValueError("cannot link a contact to itself")
    existing = db.query(ContactLink).filter_by(from_id=from_id, to_id=to_id).first()
    if existing:
        existing.kind = kind  # update the relationship type
    else:
        db.add(ContactLink(from_id=from_id, to_id=to_id, kind=kind))
    if reciprocal:
        back = db.query(ContactLink).filter_by(from_id=to_id, to_id=from_id).first()
        if back:
            back.kind = _inverse(kind)
        else:
            db.add(ContactLink(from_id=to_id, to_id=from_id, kind=_inverse(kind)))
    db.commit()


def unlink(db, a_id, b_id):
    n = (
        db.query(ContactLink)
        .filter(
            ((ContactLink.from_id == a_id) & (ContactLink.to_id == b_id))
            | ((ContactLink.from_id == b_id) & (ContactLink.to_id == a_id))
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return n


def neighbors(db, cid, kind=None):
    """contacts directly linked to `cid`, with the relationship kind (from cid's point of view)."""
    q = db.query(ContactLink).filter_by(from_id=cid)
    if kind:
        q = q.filter(ContactLink.kind == kind)
    out = []
    for link_row in q.all():
        c = db.get(Contact, link_row.to_id)
        if c:
            out.append({"id": c.id, "name": c.name, "kind": link_row.kind})
    return out


def related_for_invite(db, invitee_ids):
    """people linked to the invitees (minus the invitees themselves) - smart-invite suggestions."""
    invitees = set(invitee_ids or [])
    seen, out = set(), []
    for cid in invitees:
        for n in neighbors(db, cid):
            if n["id"] in invitees or n["id"] in seen:
                continue
            seen.add(n["id"])
            out.append(n)
    return out


def _contact_lookup(db):
    """email(lower)->cid and name(lower)->cid maps across all contacts (primary email + email
    fields). first match wins so a primary email isn't shadowed by a field."""
    from core.database import Contact, ContactField

    contacts = db.query(Contact).all()
    by_email, by_name = {}, {}
    for c in contacts:
        if c.email:
            by_email.setdefault(c.email.strip().lower(), c.id)
        if c.name:
            by_name.setdefault(c.name.strip().lower(), c.id)
    for f in db.query(ContactField).filter(ContactField.kind == "email").all():
        if f.value:
            by_email.setdefault(f.value.strip().lower(), f.contact_id)
    return contacts, by_email, by_name


def suggest_for_attendees(db, attendees):
    """given event attendees [{name,email}], match the ones we know to a contact, then suggest
    their linked contacts (skipping anyone already on the event). each suggestion carries the
    relationship kind (its tie to an invitee) so the ui can say why it's suggested."""
    contacts, by_email, by_name = _contact_lookup(db)
    cmap = {c.id: c for c in contacts}
    have_emails = {(a.get("email") or "").strip().lower() for a in attendees if a.get("email")}
    have_names = {(a.get("name") or "").strip().lower() for a in attendees if a.get("name")}
    seeds = set()
    for a in attendees:
        e = (a.get("email") or "").strip().lower()
        n = (a.get("name") or "").strip().lower()
        if e and e in by_email:
            seeds.add(by_email[e])
        elif n and n in by_name:
            seeds.add(by_name[n])
    out = []
    for r in related_for_invite(db, list(seeds)):
        c = cmap.get(r["id"])
        if not c:
            continue
        email = (c.email or "").strip()
        if email and email.lower() in have_emails:
            continue
        if not email and (c.name or "").strip().lower() in have_names:
            continue
        out.append({"id": c.id, "name": c.name, "email": email, "kind": r["kind"]})
    return out
