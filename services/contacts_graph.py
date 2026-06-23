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
