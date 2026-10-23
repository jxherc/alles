"""Local voice ownership and durable receipts; canonical chat owns Message rows."""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID

from core.api_errors import ApiError
from core.database import AideCall, AideCallEvent, Session
from services import aide_calls, local_voice
from services.aide_conversation import get_or_create_primary
from services.model_resolver import ModelResolutionError, resolve_model, resolve_session_model

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 60
MAX_CLAUSE_CHARS = 500
PROVIDER = "local"
TERMINAL = {"saved", "interrupted", "failed", "cancelled", "handoff"}


def identity(value: str) -> str:
    try:
        result = str(UUID(value))
        if result != value:
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        raise ApiError(400, "invalid_voice_identity", "use a canonical UUID") from exc


def data(event) -> dict:
    return json.loads(event.data or "{}")


def update(event, **values):
    event.data = json.dumps({**data(event), **values}, separators=(",", ":"), sort_keys=True)


def lock_call(db, call_id: str, *, live=False):
    row = db.get(AideCall, call_id)
    if not row or row.provider != PROVIDER:
        raise ApiError(404, "voice_call_missing", "local call not found")
    db.query(AideCall).filter_by(id=call_id).update(
        {AideCall.id: AideCall.id}, synchronize_session=False
    )
    db.expire_all()
    row = db.get(AideCall, call_id)
    if live and row.state == "ended":
        raise ApiError(409, "voice_call_ended", "this call has ended")
    return row


def configuration(db, call):
    event = db.query(AideCallEvent).filter_by(call_id=call.id, kind="call_created").one()
    return data(event)


def _fingerprint(selection):
    value = [
        selection.endpoint.id,
        selection.endpoint.base_url,
        selection.model,
        selection.privacy_class,
    ]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def _public_model(selection):
    return {
        **selection.public(),
        "usable": True,
        "cost": "unknown",
        "confirmation_required": selection.privacy_class != "local",
    }


def status(db):
    runtime = local_voice.metadata_status()
    audio = {
        "provider": "local",
        "ready": bool(runtime.get("available")),
        "per_call_fee": 0,
        "network_required": False,
        "format": "pcm_s16le",
        "sample_rate": 24000,
        "channels": 1,
    }
    selected = None
    reason = runtime.get("reason", "local speech runtime is not installed")
    try:
        primary = db.query(Session).filter_by(aide_role="primary").one_or_none()
        selected = resolve_session_model(db, primary) if primary else resolve_model(db, "aide_chat")
    except ModelResolutionError as exc:
        reason = str(exc)
    model = (
        _public_model(selected)
        if selected
        else {
            "usable": False,
            "cost": "unknown",
            "confirmation_required": False,
            "endpoint_id": "",
            "model": "",
            "privacy_class": "unknown",
        }
    )
    if selected and selected.privacy_class != "local":
        reason = "confirm the chosen remote text model before starting; speech stays local"
    ready = audio["ready"] and bool(selected)
    return {
        "available": ready and not model["confirmation_required"],
        "can_confirm": ready and model["confirmation_required"],
        "reason": "" if ready and not model["confirmation_required"] else reason,
        "audio": audio,
        "text_model": model,
        "limits": {
            "upload_bytes": MAX_AUDIO_BYTES,
            "recording_seconds": MAX_AUDIO_SECONDS,
            "clause_chars": MAX_CLAUSE_CHARS,
        },
    }


def public_call(db, call):
    config = configuration(db, call)
    return {
        **aide_calls.public_call(call),
        "transport": "push-to-talk",
        "text_model": config["text_model"],
    }


def create_call(db, request_id, confirmed_endpoint_id="", confirmed_model=""):
    request_id = identity(request_id)
    existing = db.get(AideCall, request_id)
    if existing:
        if existing.provider != PROVIDER:
            raise ApiError(409, "call_identity_conflict", "call identity is already in use")
        return existing, False
    if not local_voice.metadata_status().get("available"):
        raise ApiError(503, "local_voice_unavailable", "install the offline speech runtime first")
    primary = get_or_create_primary(db)
    db.query(Session).filter_by(id=primary.id).update(
        {Session.id: Session.id}, synchronize_session=False
    )
    db.expire_all()
    primary = db.get(Session, primary.id)
    try:
        selected = resolve_session_model(db, primary)
    except ModelResolutionError as exc:
        raise ApiError(409, exc.code, str(exc)) from exc
    if selected.privacy_class != "local" and (
        confirmed_endpoint_id != selected.endpoint.id or confirmed_model != selected.model
    ):
        raise ApiError(
            409,
            "remote_model_confirmation_required",
            "confirm the shown text model; its cost is unknown",
        )
    existing = db.get(AideCall, request_id)
    if existing:
        if existing.provider != PROVIDER:
            raise ApiError(409, "call_identity_conflict", "call identity is already in use")
        return existing, False
    row = AideCall(
        id=request_id,
        session_id=primary.id,
        provider=PROVIDER,
        model=selected.model,
        state="connecting",
    )
    db.add(row)
    db.flush()
    aide_calls.append_event(
        db,
        row,
        "call_created",
        data={
            "transport": "push-to-talk",
            "text_model": _public_model(selected),
            "selection_fingerprint": _fingerprint(selected),
        },
    )
    aide_calls.mark_connected(db, row)
    return row, True


def selected_model(db, call):
    config = configuration(db, call)
    model = config["text_model"]
    try:
        selection = resolve_model(
            db,
            "aide_chat",
            explicit={
                "endpoint_id": model["endpoint_id"],
                "model": model["model"],
            },
        )
    except ModelResolutionError as exc:
        raise ApiError(409, exc.code, str(exc)) from exc
    if _fingerprint(selection) != config["selection_fingerprint"]:
        raise ApiError(
            409, "voice_model_changed", "the chosen model configuration changed; start a new call"
        )
    return selection


def handoff_context(db, run_id):
    event = (
        db.query(AideCallEvent)
        .filter_by(provider_event_id=f"handoff:{run_id}", kind="local_handoff")
        .one_or_none()
    )
    return data(event) if event else None


def turn_event(db, call_id, turn_id):
    event = (
        db.query(AideCallEvent)
        .filter_by(
            call_id=call_id,
            provider_event_id=f"turn:{identity(turn_id)}",
        )
        .one_or_none()
    )
    if not event:
        raise ApiError(404, "voice_turn_missing", "voice turn not found")
    return event


def receipt(event):
    values = data(event)
    return {
        "turn_id": values["turn_id"],
        "state": values["state"],
        "transcript": event.text or "",
        "user_message_id": values.get("user_message_id"),
        "assistant_message_id": values.get("assistant_message_id"),
        "run_id": values.get("run_id"),
        "error_code": values.get("error_code"),
    }


def reserve_turn(db, call, turn_id, audio, content_type):
    turn_id = identity(turn_id)
    digest = hashlib.sha256(audio).hexdigest()
    existing = (
        db.query(AideCallEvent)
        .filter_by(
            call_id=call.id,
            provider_event_id=f"turn:{turn_id}",
        )
        .one_or_none()
    )
    if existing:
        previous = data(existing)
        if previous["audio_hash"] != digest or previous["content_type"] != content_type:
            raise ApiError(
                409, "voice_turn_identity_conflict", "turn identity belongs to different audio"
            )
        return existing, False
    if call.state == "ended":
        raise ApiError(409, "voice_call_ended", "this call has ended")
    for event in db.query(AideCallEvent).filter_by(call_id=call.id, kind="local_turn"):
        if data(event)["state"] not in TERMINAL:
            if (call.id, data(event)["turn_id"]) in _active:
                raise ApiError(409, "voice_turn_busy", "finish the current voice turn first")
            # A previous process/transport disappeared. Never automatically re-invoke it.
            update(event, state="interrupted", error_code="voice_turn_interrupted")
    event = aide_calls.append_event(
        db,
        call,
        "local_turn",
        provider_event_id=f"turn:{turn_id}",
        data={
            "turn_id": turn_id,
            "audio_hash": digest,
            "content_type": content_type,
            "state": "accepted",
        },
    )
    return event, True


@dataclass
class ActiveTurn:
    cancel: asyncio.Event
    task: asyncio.Task | None = None
    stop: asyncio.Event | None = None


_active: dict[tuple[str, str], ActiveTurn] = {}
_speech: dict[tuple[str, str, str], asyncio.Event] = {}


def activate(call_id, turn_id):
    active = ActiveTurn(asyncio.Event(), asyncio.current_task())
    _active[(call_id, turn_id)] = active
    return active


def claim_chat(context, stop):
    active = _active.get((context["call_id"], context["turn_id"]))
    if not active or active.cancel.is_set():
        raise ApiError(409, "voice_turn_cancelled", "voice turn was cancelled")
    active.stop = stop


def cancel_owned(call_id, turn_id=None):
    for key, active in list(_active.items()):
        if key[0] != call_id or (turn_id is not None and key[1] != turn_id):
            continue
        active.cancel.set()
        if active.stop:
            active.stop.set()
        if active.task and active.task is not asyncio.current_task():
            active.task.cancel()
    for key, cancel in list(_speech.items()):
        if key[0] == call_id and (turn_id is None or key[1] == turn_id):
            cancel.set()


def prepare_save(db, context):
    """Called by canonical _save_turn within its Message transaction."""
    call = lock_call(db, context["call_id"])
    if call.session_id != context["session_id"]:
        raise ValueError("voice_session_identity_conflict")
    return turn_event(db, call.id, context["turn_id"])


def link_saved(db, event, user, assistant, *, interrupted, recovery):
    db.flush()
    state = "interrupted" if interrupted else "failed" if recovery else "saved"
    update(
        event,
        state=state,
        user_message_id=user.id,
        assistant_message_id=assistant.id if assistant else None,
    )


_EXPLICIT_BACKGROUND = [
    re.compile(r"^\s*/background\b", re.I),
    re.compile(
        r"^\s*in the background\b[\s,:-]*(?:please\s+)?(?:run|do|handle|finish|continue|check|prepare|work)\b",
        re.I,
    ),
    re.compile(r"^\s*(?:please\s+)?keep (?:working|going)(?: on [\s\S]{1,100})? while i\b", re.I),
]
_BACKGROUND_IMPERATIVE = re.compile(
    r"^\s*(?:(?:please)\s+|(?:(?:could|can|would|will)\s+you\s+(?:please\s+)?)|(?:i\s+(?:need|want)\s+you\s+to\s+)|(?:i(?:'d| would)\s+like\s+you\s+to\s+))?(?:run|do|handle|finish|continue|check|prepare|work on|keep working on)\b\s*([\s\S]{0,100}?)\s+in the background\b",
    re.I,
)
_DESCRIPTIVE_OBJECT = re.compile(
    r"\b(?:guide|explanation|description|documentation|article|question)\b[\s\S]*\b(?:that|which)\b",
    re.I,
)


def wants_background(text):
    text = text.strip()
    if any(pattern.search(text) for pattern in _EXPLICIT_BACKGROUND):
        return True
    match = _BACKGROUND_IMPERATIVE.search(text)
    return bool(match and not _DESCRIPTIVE_OBJECT.search(match[1]))
