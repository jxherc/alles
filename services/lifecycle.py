"""one contract for soft-delete / archive across models.

each lifecycle model uses ONE of two mechanisms:
  - "flag":  an `archived` boolean - user-hidden, reversible, never auto-purged
  - "ts":    a `deleted_at` datetime - trashed, TTL-purged (services/trash.py)

callers used to hand-write `Model.archived == False` / `Photo.deleted_at == None` in ~20 places.
this dispatches to the right column so there's one source of truth, and later foundations
(the mutation spine's audit, the blob GC, connectors) can assume a uniform lifecycle.

NOTE: archive and trash are different semantics on purpose - this unifies the ACCESS pattern,
not the meaning. cascade-trash of owned children is a future extension point, not built here.
"""

import datetime

from core.database import Account, Habit, Note, Photo, ReadItem, Session

# model -> (column name, kind). kind: "flag" = archived bool, "ts" = deleted_at datetime.
LIFECYCLE = {
    Session: ("archived", "flag"),
    Note: ("archived", "flag"),
    Account: ("archived", "flag"),
    Habit: ("archived", "flag"),
    ReadItem: ("archived", "flag"),
    Photo: ("deleted_at", "ts"),
}


def _policy(model):
    try:
        return LIFECYCLE[model]
    except KeyError:
        raise KeyError(f"{getattr(model, '__name__', model)} is not a lifecycle model") from None


def is_active(obj) -> bool:
    col, kind = _policy(type(obj))
    v = getattr(obj, col)
    return (not v) if kind == "flag" else (v is None)


def _entity(query):
    return query.column_descriptions[0]["entity"]


def active(query):
    """filter a query down to its live rows (dispatches on the model's mechanism)."""
    model = _entity(query)
    col, kind = _policy(model)
    c = getattr(model, col)
    return query.filter(c == False) if kind == "flag" else query.filter(c.is_(None))  # noqa: E712


def inactive(query):
    """filter a query to only the archived/trashed rows."""
    model = _entity(query)
    col, kind = _policy(model)
    c = getattr(model, col)
    return query.filter(c == True) if kind == "flag" else query.filter(c.isnot(None))  # noqa: E712


def soft_delete(db, obj):
    col, kind = _policy(type(obj))
    setattr(obj, col, True if kind == "flag" else datetime.datetime.utcnow())
    db.commit()


def restore(db, obj):
    col, kind = _policy(type(obj))
    setattr(obj, col, False if kind == "flag" else None)
    db.commit()
