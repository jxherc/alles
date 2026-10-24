"""Reviewed, content-minimal event inbox for Jarvis workflows."""

import hashlib
import logging
import threading
from datetime import UTC, datetime

from sqlalchemy import event as sa_event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from core.database import (
    JarvisInboxEvent,
    JarvisRun,
    JarvisTrigger,
    JarvisWorkflow,
    SessionLocal,
)
from services.jarvis_store import create_run, json_value

log = logging.getLogger("alles.jarvis.events")

# mutation batches parked by _on_mutations until the committing session lets go of its connection
_parked = threading.local()


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _key(source_kind: str, source_id: str, event_type: str) -> str:
    return hashlib.sha256(f"{source_kind}:{source_id}:{event_type}".encode()).hexdigest()


def queue_event(
    db: DbSession,
    *,
    source_kind: str,
    source_id: str,
    event_type: str,
    entity_kind: str = "",
    entity_id: str = "",
    field_names: list[str] | None = None,
    external: bool = False,
) -> tuple[JarvisInboxEvent, bool]:
    source_kind = str(source_kind or "").strip()[:64]
    source_id = str(source_id or "").strip()[:128]
    event_type = str(event_type or "").strip()[:128]
    if not source_kind or not source_id or not event_type:
        raise ValueError("invalid_jarvis_event")
    dedupe = _key(source_kind, source_id, event_type)
    existing = db.query(JarvisInboxEvent).filter_by(dedupe_key=dedupe).first()
    if existing:
        return existing, False
    names = sorted({str(name)[:64] for name in (field_names or []) if str(name).strip()})[:40]
    summary = "external event awaiting owner review" if external else f"{entity_kind} {event_type}"
    if names and not external:
        summary += f"; fields: {', '.join(names)}"
    row = JarvisInboxEvent(
        source_kind=source_kind,
        source_id=source_id,
        event_type=event_type,
        entity_kind=str(entity_kind or "")[:64],
        entity_id=str(entity_id or "")[:128],
        safe_summary=summary[:500],
        external=bool(external),
        state="pending",
        dedupe_key=dedupe,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return db.query(JarvisInboxEvent).filter_by(dedupe_key=dedupe).one(), False
    return row, True


def _write_mutations(mutations: list[dict]) -> None:
    db = SessionLocal()
    try:
        for mutation in mutations:
            queue_event(
                db,
                source_kind="mutation",
                source_id=str(mutation.get("event_id") or ""),
                event_type=f"mutation.{mutation.get('op') or 'change'}",
                entity_kind=str(mutation.get("entity_kind") or ""),
                entity_id=str(mutation.get("entity_id") or ""),
                field_names=list((mutation.get("fields") or {}).keys()),
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Jarvis event enqueue failed: %s", type(exc).__name__)
    finally:
        db.close()


def _on_mutations(mutations: list[dict]) -> None:
    # runs in after_commit, while the committing session still holds its pooled connection. a new
    # session here wants a second one; under load every thread held one and waited on another until
    # the pool timed out. park the batch and write it once the connection is back in the pool
    batches = getattr(_parked, "batches", None)
    if batches is None:
        batches = _parked.batches = []
    batches.append(list(mutations))


def _after_transaction_end(session, transaction) -> None:
    # a savepoint ending means the outer transaction still holds the connection
    if transaction.parent is not None:
        return
    batches = getattr(_parked, "batches", None)
    if not batches:
        return
    _parked.batches = []
    _write_mutations([mutation for batch in batches for mutation in batch])


def install() -> None:
    from services import events

    if _on_mutations not in events._subscribers:
        events.subscribe(_on_mutations)
    if not sa_event.contains(SessionLocal, "after_transaction_end", _after_transaction_end):
        sa_event.listen(SessionLocal, "after_transaction_end", _after_transaction_end)


def review_event(db: DbSession, event: JarvisInboxEvent, *, allow: bool) -> JarvisInboxEvent:
    if event.state != "pending":
        raise ValueError("event_not_pending")
    event.state = "reviewed" if allow else "dismissed"
    event.reviewed_at = utc_now()
    return event


def _matches(trigger: JarvisTrigger, event: JarvisInboxEvent) -> bool:
    config = json_value(trigger.config, dict)
    return (
        (not config.get("event_type") or config["event_type"] == event.event_type)
        and (not config.get("entity_kind") or config["entity_kind"] == event.entity_kind)
        and (not config.get("source_kind") or config["source_kind"] == event.source_kind)
    )


def _event_occurrence_key(trigger_id: str, event_id: str) -> str:
    return hashlib.sha256(f"event:{trigger_id}:{event_id}".encode()).hexdigest()


def dispatch_reviewed_events(*, limit: int = 100) -> dict:
    db = SessionLocal()
    runs = 0
    dispatched = 0
    try:
        events = (
            db.query(JarvisInboxEvent)
            .filter_by(state="reviewed")
            .order_by(JarvisInboxEvent.created_at)
            .limit(max(1, min(limit, 500)))
            .all()
        )
        for event in events:
            triggers = db.query(JarvisTrigger).filter_by(kind="event", enabled=True).all()
            matched = False
            for trigger in triggers:
                workflow = db.get(JarvisWorkflow, trigger.workflow_id)
                if not workflow or not workflow.enabled or not _matches(trigger, event):
                    continue
                matched = True
                occurrence = _event_occurrence_key(trigger.id, event.id)
                exists = (
                    db.query(JarvisRun)
                    .filter_by(trigger_id=trigger.id, occurrence_key=occurrence)
                    .first()
                )
                if exists:
                    continue
                try:
                    with db.begin_nested():
                        create_run(
                            db,
                            workflow,
                            trigger_id=trigger.id,
                            scheduled_for=event.created_at,
                            occurrence_key=occurrence,
                        )
                        db.flush()
                    runs += 1
                except IntegrityError:
                    pass
            if matched:
                event.state = "dispatched"
                event.dispatched_at = utc_now()
                dispatched += 1
        db.commit()
        return {"events": dispatched, "runs": runs}
    finally:
        db.close()
