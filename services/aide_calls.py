"""Durable call lifecycle and exactly-once finalized transcript persistence."""

import json
from datetime import UTC, datetime

from sqlalchemy import func

from core.database import AideCall, AideCallEvent, Message, Session
from services import realtime
from services.aide_conversation import get_or_create_primary


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def public_call(row: AideCall) -> dict:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "provider": row.provider,
        "model": row.model,
        "state": row.state,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "connected_at": row.connected_at.isoformat() if row.connected_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
    }


def create_call(db, request_id: str, *, provider: str, model: str) -> tuple[AideCall, bool]:
    primary = get_or_create_primary(db)
    existing = db.get(AideCall, request_id)
    if existing:
        if (
            existing.session_id != primary.id
            or existing.provider != provider
            or existing.model != model
        ):
            raise ValueError("call_identity_conflict")
        return existing, False
    configuration = {"transport": "webrtc"}
    if provider == "openai-realtime":
        endpoint, _ = realtime.find_webrtc_endpoint(db, model=model)
        if not endpoint:
            raise ValueError("realtime_unavailable")
        configuration["endpoint_id"] = endpoint.id
    row = AideCall(
        id=request_id,
        session_id=primary.id,
        provider=provider,
        model=model,
        state="connecting",
    )
    db.add(row)
    db.flush()
    append_event(db, row, "call_created", data=configuration)
    return row, True


def append_event(
    db,
    call: AideCall,
    kind: str,
    *,
    role: str = "",
    text: str = "",
    provider_event_id: str | None = None,
    data: dict | None = None,
) -> AideCallEvent:
    if provider_event_id:
        existing = (
            db.query(AideCallEvent)
            .filter_by(call_id=call.id, provider_event_id=provider_event_id)
            .one_or_none()
        )
        if existing:
            return existing
    sequence = (
        db.query(func.max(AideCallEvent.sequence)).filter(AideCallEvent.call_id == call.id).scalar()
        or 0
    ) + 1
    event = AideCallEvent(
        call_id=call.id,
        sequence=sequence,
        kind=kind,
        role=role,
        text=text,
        provider_event_id=provider_event_id or None,
        data=json.dumps(data or {}, separators=(",", ":"), sort_keys=True),
    )
    db.add(event)
    db.flush()
    return event


def reserve_offer(db, call: AideCall, offer: str) -> realtime.RealtimeTarget:
    """The caller holds the call write lock and commits before contacting the provider."""
    if call.provider != "openai-realtime":
        raise ValueError("call_provider_mismatch")
    if call.state == "ended":
        raise ValueError("call_already_ended")
    if (
        call.state != "connecting"
        or db.query(AideCallEvent).filter_by(call_id=call.id, kind="offer_reserved").first()
    ):
        raise ValueError("call_offer_already_submitted")
    created = db.query(AideCallEvent).filter_by(call_id=call.id, kind="call_created").one_or_none()
    configuration = json.loads(created.data or "{}") if created else {}
    target = realtime.prepare_offer(
        db, offer, endpoint_id=configuration.get("endpoint_id", ""), model=call.model
    )
    append_event(db, call, "offer_reserved")
    return target


def mark_connected(db, call: AideCall) -> AideCall:
    if call.state == "ended":
        raise ValueError("call_already_ended")
    if call.state != "connected":
        call.state = "connected"
        call.connected_at = _now()
        append_event(db, call, "call_connected")
    return call


def end_call(db, call: AideCall) -> AideCall:
    if call.state != "ended":
        call.state = "ended"
        call.ended_at = _now()
        append_event(db, call, "call_ended")
    return call


def append_final_transcript(
    db,
    call: AideCall,
    *,
    role: str,
    text: str,
    provider_event_id: str,
) -> tuple[AideCallEvent, bool]:
    if role not in {"user", "assistant"}:
        raise ValueError("invalid_transcript_role")
    text = str(text or "").strip()
    if not text:
        raise ValueError("empty_transcript")
    provider_event_id = str(provider_event_id or "").strip()[:200]
    if not provider_event_id:
        raise ValueError("provider_event_id_required")
    existing = (
        db.query(AideCallEvent)
        .filter_by(call_id=call.id, provider_event_id=provider_event_id)
        .one_or_none()
    )
    if existing:
        if existing.role != role or existing.text != text:
            raise ValueError("call_event_identity_conflict")
        return existing, False
    event = append_event(
        db,
        call,
        "final_transcript",
        role=role,
        text=text,
        provider_event_id=provider_event_id,
    )
    session = db.get(Session, call.session_id)
    if not session:
        raise ValueError("call_session_missing")
    db.add(
        Message(
            session_id=session.id,
            role=role,
            content=text,
            meta=json.dumps(
                {"live_call_id": call.id, "provider_event_id": provider_event_id},
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    )
    session.message_count = (session.message_count or 0) + 1
    session.last_message_at = _now()
    db.flush()
    return event, True
