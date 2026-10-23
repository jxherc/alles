"""Resolve the one permanent Aide conversation without merging legacy chats."""

from sqlalchemy.exc import IntegrityError

from core.database import Session

PRIMARY_ROLE = "primary"


def get_or_create_primary(db) -> Session:
    row = db.query(Session).filter(Session.aide_role == PRIMARY_ROLE).one_or_none()
    if row:
        if row.archived:
            row.archived = False
        return row

    row = Session(name="Aide", mode="chat", aide_role=PRIMARY_ROLE)
    db.add(row)
    try:
        db.flush()
        return row
    except IntegrityError:
        # A simultaneous resolver may have won the partial-unique-index race.
        db.rollback()
        row = db.query(Session).filter(Session.aide_role == PRIMARY_ROLE).one_or_none()
        if not row:
            raise
        if row.archived:
            row.archived = False
        return row
