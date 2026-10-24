"""Durable call lifecycle and exactly-once finalized transcript persistence."""

import json
import threading
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
        # the event is kept, but its chat line may not be: it was held for a running turn when
        # the process stopped, or the held write failed. the client's retry puts it in, once
        session = db.get(Session, call.session_id)
        if session is not None and not _line_held_or_saved(
            db, session.id, call.id, provider_event_id
        ):
            _write_line(db, existing, session.id, call.id, role, text, provider_event_id)
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
    _write_line(db, event, session.id, call.id, role, text, provider_event_id)
    return event, True


# transcript lines waiting for a running turn to end, by (call, provider event)
_held_lines: set[tuple[str, str]] = set()
_held_lock = threading.Lock()


def _line_held_or_saved(db, session_id, call_id, provider_event_id) -> bool:
    with _held_lock:
        if (call_id, provider_event_id) in _held_lines:
            return True
    return _line_saved(db, session_id, call_id, provider_event_id)


def _line_saved(db, session_id, call_id, provider_event_id) -> bool:
    # the chat row carries the line's identity in its meta (LIKE may over-match: checked below)
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .filter(Message.meta.like(f"%{json.dumps(provider_event_id)}%"))
        .all()
    )
    return any(
        m.meta_dict().get("provider_event_id") == provider_event_id
        and m.meta_dict().get("live_call_id") == call_id
        for m in rows
    )


# a call event whose chat line waits for a running turn says so, committed with the event: if the
# process stops before the turn ends, startup puts the line in (restore_held_lines)
_HELD = "held"


def _mark(event, state: str | None) -> None:
    data = json.loads(event.data or "{}")
    if state:
        data["chat_line"] = state
    else:
        data.pop("chat_line", None)
    event.data = json.dumps(data, separators=(",", ":"), sort_keys=True)


def _write_line(db, event, session_id, call_id, role, text, provider_event_id) -> None:
    meta = json.dumps(
        {"live_call_id": call_id, "provider_event_id": provider_event_id},
        separators=(",", ":"),
        sort_keys=True,
    )
    key = (call_id, provider_event_id)

    def add(owner) -> None:
        if owner.get(Session, session_id) is None:
            return
        owner.add(Message(session_id=session_id, role=role, content=text, meta=meta))
        # counted in the database: other writers' rows count too
        owner.query(Session).filter_by(id=session_id).update(
            {
                Session.message_count: func.coalesce(Session.message_count, 0) + 1,
                Session.last_message_at: _now(),
            },
            synchronize_session=False,
        )

    def now() -> None:
        # committed while the turn registry says nobody answers, so no turn starts in between
        add(db)
        _mark(event, None)
        db.commit()

    event_id = event.id

    def later() -> None:
        # a reply was running in this task: the line goes in right after it, so it never lands
        # between that reply's question and its answer
        from core.database import SessionLocal

        owner = SessionLocal()
        try:
            if not _line_saved(owner, session_id, call_id, provider_event_id):
                add(owner)
            held = owner.get(AideCallEvent, event_id)
            if held is not None:
                _mark(held, None)
            owner.commit()
        finally:
            owner.close()
            with _held_lock:
                _held_lines.discard(key)

    from routes import chat as chat_route

    with _held_lock:
        _held_lines.add(key)
    try:
        if chat_route.write_after_turn(session_id, now, later):
            with _held_lock:
                _held_lines.discard(key)
        else:
            # the caller commits this with the event, so a restart still knows the line is owed
            _mark(event, _HELD)
    except BaseException:
        with _held_lock:
            _held_lines.discard(key)
        raise


def restore_held_lines(db) -> int:
    """At startup: put in every call line that was still waiting for a turn when alles stopped."""
    owed = (
        db.query(AideCallEvent)
        .filter(AideCallEvent.kind == "final_transcript")
        .filter(AideCallEvent.data.like(f'%"chat_line":"{_HELD}"%'))
        .all()
    )
    restored = 0
    for event in owed:
        call = db.get(AideCall, event.call_id)
        session = db.get(Session, call.session_id) if call is not None else None
        if session is not None and not _line_saved(
            db, session.id, call.id, event.provider_event_id
        ):
            meta = json.dumps(
                {"live_call_id": call.id, "provider_event_id": event.provider_event_id},
                separators=(",", ":"),
                sort_keys=True,
            )
            db.add(Message(session_id=session.id, role=event.role, content=event.text, meta=meta))
            db.query(Session).filter_by(id=session.id).update(
                {
                    Session.message_count: func.coalesce(Session.message_count, 0) + 1,
                    Session.last_message_at: _now(),
                },
                synchronize_session=False,
            )
            restored += 1
        _mark(event, None)
    db.commit()
    return restored
