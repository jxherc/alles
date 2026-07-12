"""Persistent, provider-neutral Jarvis delivery outbox."""

import hashlib
import inspect
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from core.database import (
    JarvisConnector,
    JarvisDeliveryAttempt,
    JarvisRun,
    JarvisRunEvent,
    JarvisWorkflow,
    SessionLocal,
)

PRIVACY_LEVELS = {"status", "title_status", "summary"}
TERMINAL_STATES = {"delivered", "failed", "uncertain", "cancelled"}
_PROVIDERS: dict[str, object] = {}


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def register_provider(channel: str, provider) -> None:
    if not channel or not callable(provider):
        raise ValueError("invalid_delivery_provider")
    _PROVIDERS[channel] = provider


def unregister_provider(channel: str) -> None:
    _PROVIDERS.pop(channel, None)


def delivery_key(run_id: str, event_id: str | None, channel: str, privacy_level: str) -> str:
    raw = f"{run_id}:{event_id or ''}:{channel}:{privacy_level}"
    return hashlib.sha256(raw.encode()).hexdigest()


def enqueue_delivery(
    db: DbSession,
    run: JarvisRun,
    *,
    channel: str,
    privacy_level: str = "title_status",
    event_id: str | None = None,
    connector_id: str | None = None,
    idempotency_supported: bool = False,
) -> tuple[JarvisDeliveryAttempt, bool]:
    channel = str(channel or "").strip()[:64]
    if not channel:
        raise ValueError("delivery_channel_required")
    if privacy_level not in PRIVACY_LEVELS:
        raise ValueError("invalid_delivery_privacy")
    if event_id:
        event = db.get(JarvisRunEvent, event_id)
        if not event or event.run_id != run.id:
            raise ValueError("delivery_event_mismatch")
    if connector_id and not db.get(JarvisConnector, connector_id):
        raise ValueError("delivery_connector_missing")
    key = delivery_key(run.id, event_id, channel, privacy_level)
    existing = db.query(JarvisDeliveryAttempt).filter_by(idempotency_key=key).first()
    if existing:
        return existing, False
    row = JarvisDeliveryAttempt(
        run_id=run.id,
        event_id=event_id,
        connector_id=connector_id,
        channel=channel,
        privacy_level=privacy_level,
        state="pending",
        idempotency_key=key,
        idempotency_supported=bool(idempotency_supported),
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.query(JarvisDeliveryAttempt).filter_by(idempotency_key=key).one()
        return existing, False
    return row, True


def claim_delivery(
    db: DbSession,
    worker_id: str,
    *,
    now: datetime | None = None,
    lease_seconds: int = 60,
) -> JarvisDeliveryAttempt | None:
    if not worker_id or lease_seconds < 5 or lease_seconds > 3600:
        raise ValueError("invalid_delivery_lease")
    now = now or utc_now()
    ids = (
        db.query(JarvisDeliveryAttempt.id)
        .filter(
            JarvisDeliveryAttempt.state.in_(("pending", "retry")),
            or_(
                JarvisDeliveryAttempt.next_attempt_at.is_(None),
                JarvisDeliveryAttempt.next_attempt_at <= now,
            ),
        )
        .order_by(JarvisDeliveryAttempt.created_at)
        .limit(20)
        .all()
    )
    for (delivery_id,) in ids:
        changed = (
            db.query(JarvisDeliveryAttempt)
            .filter(
                JarvisDeliveryAttempt.id == delivery_id,
                JarvisDeliveryAttempt.state.in_(("pending", "retry")),
                or_(
                    JarvisDeliveryAttempt.next_attempt_at.is_(None),
                    JarvisDeliveryAttempt.next_attempt_at <= now,
                ),
            )
            .update(
                {
                    JarvisDeliveryAttempt.state: "delivering",
                    JarvisDeliveryAttempt.lease_owner: worker_id,
                    JarvisDeliveryAttempt.lease_expires_at: now + timedelta(seconds=lease_seconds),
                    JarvisDeliveryAttempt.attempt_count: JarvisDeliveryAttempt.attempt_count + 1,
                    JarvisDeliveryAttempt.last_attempt_at: now,
                    JarvisDeliveryAttempt.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if changed == 1:
            db.flush()
            db.expire_all()
            return db.get(JarvisDeliveryAttempt, delivery_id)
    return None


def _payload(db: DbSession, delivery: JarvisDeliveryAttempt) -> dict:
    run = db.get(JarvisRun, delivery.run_id)
    if not run:
        raise ValueError("delivery_run_missing")
    workflow = db.get(JarvisWorkflow, run.workflow_id) if run.workflow_id else None
    payload = {"run_id": run.id, "state": run.state}
    if delivery.privacy_level in {"title_status", "summary"}:
        payload["title"] = (workflow.name if workflow else "Jarvis")[:200]
    if delivery.privacy_level == "summary":
        event = db.get(JarvisRunEvent, delivery.event_id) if delivery.event_id else None
        payload["summary"] = ((event.summary if event else run.result_summary) or "")[:2000]
    return payload


def _clear_lease(delivery: JarvisDeliveryAttempt) -> None:
    delivery.lease_owner = ""
    delivery.lease_expires_at = None


def record_delivery_result(
    delivery: JarvisDeliveryAttempt,
    *,
    classification: str,
    provider_message_id: str = "",
    now: datetime | None = None,
    max_attempts: int = 4,
    base_backoff_seconds: int = 10,
) -> JarvisDeliveryAttempt:
    if delivery.state != "delivering":
        raise ValueError("delivery_not_claimed")
    now = now or utc_now()
    if classification == "delivered":
        delivery.state = "delivered"
        delivery.provider_message_id = str(provider_message_id or "")[:256]
        delivery.safe_error_class = ""
        delivery.next_attempt_at = None
    elif classification == "transient" and delivery.attempt_count < max_attempts:
        delivery.state = "retry"
        delay = min(3600, base_backoff_seconds * (2 ** max(0, delivery.attempt_count - 1)))
        delivery.next_attempt_at = now + timedelta(seconds=delay)
        delivery.safe_error_class = "transient"
    elif classification in {"transient", "permanent"}:
        delivery.state = "failed"
        delivery.safe_error_class = classification
        delivery.next_attempt_at = None
    elif classification == "uncertain":
        delivery.state = "uncertain"
        delivery.safe_error_class = "uncertain"
        delivery.next_attempt_at = None
    else:
        raise ValueError("invalid_delivery_result")
    _clear_lease(delivery)
    delivery.updated_at = now
    return delivery


def reclaim_stale_deliveries(db: DbSession, *, now: datetime | None = None) -> dict:
    now = now or utc_now()
    retried = 0
    uncertain = 0
    rows = (
        db.query(JarvisDeliveryAttempt)
        .filter(
            JarvisDeliveryAttempt.state == "delivering",
            JarvisDeliveryAttempt.lease_expires_at.is_not(None),
            JarvisDeliveryAttempt.lease_expires_at <= now,
        )
        .all()
    )
    for delivery in rows:
        if delivery.idempotency_supported:
            delivery.state = "retry"
            delivery.next_attempt_at = now
            delivery.safe_error_class = "interrupted"
            retried += 1
        else:
            delivery.state = "uncertain"
            delivery.next_attempt_at = None
            delivery.safe_error_class = "uncertain"
            uncertain += 1
        _clear_lease(delivery)
        delivery.updated_at = now
    return {"retried": retried, "uncertain": uncertain}


async def process_outbox(worker_id: str = "jarvis-outbox", *, limit: int = 20) -> dict:
    delivered = 0
    failed = 0
    db = SessionLocal()
    try:
        reclaim_stale_deliveries(db)
        db.commit()
        for _ in range(max(1, min(limit, 100))):
            delivery = claim_delivery(db, worker_id)
            if not delivery:
                break
            db.commit()
            delivery_id = delivery.id
            channel = delivery.channel
            provider = _PROVIDERS.get(channel)
            if not provider:
                delivery = db.get(JarvisDeliveryAttempt, delivery_id)
                record_delivery_result(delivery, classification="permanent")
                db.commit()
                failed += 1
                continue
            try:
                payload = _payload(db, delivery)
                connector = (
                    db.get(JarvisConnector, delivery.connector_id)
                    if delivery.connector_id
                    else None
                )
                if connector and (not connector.enabled or connector.kind != channel):
                    record_delivery_result(delivery, classification="permanent")
                    db.commit()
                    failed += 1
                    continue
                result = provider(
                    payload,
                    idempotency_key=delivery.idempotency_key,
                    connector=connector,
                )
                if inspect.isawaitable(result):
                    result = await result
                classification = str((result or {}).get("classification") or "uncertain")
                message_id = str((result or {}).get("provider_message_id") or "")
            except Exception:
                classification = "transient" if delivery.idempotency_supported else "uncertain"
                message_id = ""
            if classification not in {"delivered", "transient", "permanent", "uncertain"}:
                classification = "uncertain"
            delivery = db.get(JarvisDeliveryAttempt, delivery_id)
            record_delivery_result(
                delivery,
                classification=classification,
                provider_message_id=message_id,
            )
            db.commit()
            delivered += int(delivery.state == "delivered")
            failed += int(delivery.state in {"failed", "uncertain"})
        return {"delivered": delivered, "failed": failed}
    finally:
        db.close()
