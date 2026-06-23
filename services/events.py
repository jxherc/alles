"""0c - the event/mutation spine. see docs/evidence/0c-spine/findings.md.

a durable MutationEvent is written for every insert/update/delete on a TRACKED model, in the
SAME transaction as the change (via the mapper listener's connection), so it commits or rolls
back with it. after the txn commits, synchronous subscribers are fired with the committed
mutations (best-effort). listeners are bulletproof: a failure is logged + swallowed, never
breaking the host write.

event choice: after_insert (the app-set uuid PK is populated by then), before_update (the
attribute history is still intact), after_delete (the id is still on the object).
"""

import json
import logging
from datetime import datetime

from sqlalchemy import event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import object_session

from core.database import (
    CalendarEvent,
    Habit,
    JournalEntry,
    MutationEvent,
    Note,
    ProactiveItem,
    SessionLocal,
    Subscription,
    Task,
    Transaction,
    _uid,
)

log = logging.getLogger("alles.events")

TRACKED = (Task, Transaction, Subscription, CalendarEvent, Note, JournalEntry, Habit, ProactiveItem)

_subscribers = []  # sync callables: fn(list[dict])


def subscribe(fn):
    _subscribers.append(fn)


def clear_subscribers():
    _subscribers.clear()


def _jsonable(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _col_values(target):
    insp = sa_inspect(target)
    return {c.key: _jsonable(getattr(target, c.key)) for c in insp.mapper.column_attrs}


def _changed(target):
    insp = sa_inspect(target)
    out = {}
    for c in insp.mapper.column_attrs:
        h = insp.attrs[c.key].history
        if h.has_changes() and h.added:
            out[c.key] = _jsonable(h.added[0])
    return out


def record_mutation(connection, kind, eid, op, fields):
    """write one MutationEvent row on `connection` (Core insert, same txn as the caller)."""
    connection.execute(
        MutationEvent.__table__.insert().values(
            id=_uid(),
            entity_kind=kind,
            entity_id=str(eid or ""),
            op=op,
            fields=json.dumps(fields, default=str),
            actor="",
            ts=datetime.utcnow(),
        )
    )


def _emit(connection, target, op, fields):
    try:
        kind = target.__tablename__
        eid = getattr(target, "id", "")
        record_mutation(connection, kind, eid, op, fields)
        sess = object_session(target)
        if sess is not None:
            sess.info.setdefault("_mutations", []).append(
                {"entity_kind": kind, "entity_id": str(eid or ""), "op": op, "fields": fields}
            )
    except Exception as e:  # never break the host write
        log.warning(
            f"mutation-event listener failed ({op} on {getattr(target, '__tablename__', '?')}): {e}"
        )


def _on_insert(mapper, connection, target):
    _emit(connection, target, "insert", _col_values(target))


def _on_update(mapper, connection, target):
    ch = _changed(target)
    if ch:
        _emit(connection, target, "update", ch)


def _on_delete(mapper, connection, target):
    _emit(connection, target, "delete", {})


def _on_commit(session):
    muts = session.info.pop("_mutations", None)
    if not muts:
        return
    for fn in list(_subscribers):
        try:
            fn(muts)
        except Exception as e:
            log.warning(f"mutation subscriber failed: {e}")


def _on_rollback(session):
    session.info.pop("_mutations", None)


def history(db, kind, eid):
    """replay: every MutationEvent for one entity, oldest first."""
    return (
        db.query(MutationEvent)
        .filter(MutationEvent.entity_kind == kind, MutationEvent.entity_id == str(eid))
        .order_by(MutationEvent.ts)
        .all()
    )


_installed = False


def install():
    global _installed
    if _installed:
        return
    for m in TRACKED:
        event.listen(m, "after_insert", _on_insert)
        event.listen(m, "before_update", _on_update)
        event.listen(m, "after_delete", _on_delete)
    event.listen(SessionLocal, "after_commit", _on_commit)
    event.listen(SessionLocal, "after_rollback", _on_rollback)
    _installed = True


install()
