"""Durable, content-free audit records for owner-visible state changes."""

import json
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial

from core.database import AuditRecord, SessionLocal
from services.observability import redact_value

log = logging.getLogger("alles.audit")

# one writer thread for request audits. the event loop never waits on the db, and a write burst
# holds one pooled connection instead of one per request. its queue drains at interpreter exit too
_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="alles-audit")


def _details(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {"state": "unreadable"}
    return redact_value(parsed) if isinstance(parsed, dict) else {"state": "unreadable"}


def record(
    *,
    action: str,
    outcome: str,
    actor: str,
    target: str = "",
    request_id: str = "",
    details: dict | None = None,
) -> None:
    """Best-effort audit write. Never stores request bodies or response bodies."""
    db = SessionLocal()
    try:
        clean = redact_value(details or {})
        db.add(
            AuditRecord(
                action=action[:120],
                outcome=outcome[:32],
                actor=actor[:32],
                target=target[:240],
                request_id=request_id[:64],
                details=json.dumps(clean, ensure_ascii=False, separators=(",", ":")),
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("audit write failed: %s", type(exc).__name__)
    finally:
        db.close()


def _queue(job) -> Future:
    try:
        return _writer.submit(job)
    except RuntimeError:  # interpreter is shutting down and the pool takes no new work
        done = Future()
        job()
        done.set_result(None)
        return done


def submit(**fields) -> Future:
    """Queue record(**fields) on the audit thread. The future settles once the row is stored."""
    return _queue(partial(record, **fields))


def flushed() -> Future:
    """Settles after every audit queued before this call is stored."""
    return _queue(lambda: None)


def recent(db, limit: int = 100) -> list[dict]:
    rows = db.query(AuditRecord).order_by(AuditRecord.created_at.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "action": row.action,
            "outcome": row.outcome,
            "actor": row.actor,
            "target": row.target,
            "request_id": row.request_id,
            "details": _details(row.details),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
