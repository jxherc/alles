"""Owner-only, local audio calls. No speech provider fallback or implicit model switch."""

import asyncio
import json
import math
from contextlib import aclosing
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.api_errors import ApiError
from core.auth import require_auth
from core.database import Session, SessionLocal, get_db
from core.rate_limit import enforce_rate_limit
from services import aide_calls, aide_voice, jarvis_handoff, local_voice


def owner_request(request: Request):
    # CORS alone does not prevent another website posting to a local instance.
    if request.headers.get("authorization"):
        raise ApiError(
            403, "voice_owner_required", "local calls require the owner's browser session"
        )
    require_auth(request)
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise ApiError(403, "voice_origin_rejected", "use the Alles app to make a call")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != request.url.scheme
            or parsed.scheme not in {"http", "https"}
            or parsed.netloc.lower() != request.headers.get("host", "").lower()
        ):
            raise ApiError(403, "voice_origin_rejected", "use the Alles app to make a call")
    enforce_rate_limit(request, "local_voice", limit=120, window_seconds=60)


router = APIRouter(prefix="/api/aide/voice", dependencies=[Depends(owner_request)])


@router.get("/status")
def status(db=Depends(get_db)):
    return aide_voice.status(db)


class CallBody(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    confirmed_endpoint_id: str = Field(default="", max_length=100)
    confirmed_model: str = Field(default="", max_length=300)


@router.post("/calls")
def create_call(body: CallBody, db=Depends(get_db)):
    row, created = aide_voice.create_call(db, **body.model_dump())
    db.commit()
    return {**aide_voice.public_call(db, row), "created": created}


@router.get("/calls/{call_id}/turns/{turn_id}")
def get_turn(call_id: str, turn_id: str, db=Depends(get_db)):
    aide_voice.lock_call(db, call_id)
    event = aide_voice.turn_event(db, call_id, turn_id)
    values = aide_voice.data(event)
    if values["state"] not in aide_voice.TERMINAL and (call_id, turn_id) not in aide_voice._active:
        aide_voice.update(event, state="interrupted", error_code="voice_turn_interrupted")
        db.commit()
    return aide_voice.receipt(event)


def _sse(payload):
    return f"data: {json.dumps(payload)}\n\n".encode()


def _receipt(call_id, turn_id):
    with SessionLocal() as db:
        return aide_voice.receipt(aide_voice.turn_event(db, call_id, turn_id))


def _finish_unanswered(context, cancelled, code):
    """Preparation/STT failures must not lose an already accepted transcript."""
    from services.chat_turn import _save_turn

    with SessionLocal() as db:
        event = aide_voice.turn_event(db, context["call_id"], context["turn_id"])
        values = aide_voice.data(event)
        if values["state"] in {"saved", "interrupted", "handoff"} or values.get("user_message_id"):
            return
        text = event.text
        if not text:
            aide_voice.lock_call(db, context["call_id"])
            aide_voice.update(event, state="cancelled" if cancelled else "failed", error_code=code)
            db.commit()
            return
    _save_turn(
        context["session_id"],
        text,
        "",
        context["model"],
        SessionLocal,
        False,
        {"_aide_voice_turn": context},
        [],
        [],
        [],
        {},
        "",
        cancelled,
        {"status": "incomplete" if cancelled else "failed"},
    )


async def _run_turn(call_id, turn_id, audio, content_type, request):
    from routes.chat import ChatRequest, create_chat_response

    active = aide_voice._active.get((call_id, turn_id)) or aide_voice.activate(call_id, turn_id)
    active.task = asyncio.current_task()
    context = None
    error_code = "voice_turn_interrupted"
    try:
        with SessionLocal() as db:
            call = aide_voice.lock_call(db, call_id, live=True)
            event = aide_voice.turn_event(db, call_id, turn_id)
            context = {
                "call_id": call_id,
                "turn_id": turn_id,
                "session_id": call.session_id,
                "model": call.model,
            }
            if aide_voice.data(event)["state"] != "accepted":
                raise ApiError(409, "voice_turn_cancelled", "voice turn is no longer pending")
            selected = aide_voice.selected_model(db, call)
            context = {
                "call_id": call_id,
                "turn_id": turn_id,
                "session_id": call.session_id,
                "model": selected.model,
            }
            aide_voice.update(event, state="transcribing")
            db.commit()
        result = await local_voice.transcribe(
            audio, content_type, f"{call_id}:{turn_id}:stt", active.cancel
        )
        if active.cancel.is_set():
            raise asyncio.CancelledError
        text = str(result.get("text", "")).strip()
        if not text:
            raise ApiError(422, "voice_no_speech", "no speech was detected; try again")
        if len(text) > 12000:
            raise ApiError(422, "voice_transcript_too_long", "record a shorter utterance")
        with SessionLocal() as db:
            call = aide_voice.lock_call(db, call_id, live=True)
            event = aide_voice.turn_event(db, call_id, turn_id)
            event.text = text
            aide_voice.update(event, state="responding")
            db.commit()
        yield _sse({"transcript": {"turn_id": turn_id, "text": text}})

        if aide_voice.wants_background(text):
            with SessionLocal() as db:
                call = aide_voice.lock_call(db, call_id, live=True)
                selection = aide_voice.selected_model(db, call)
                event = aide_voice.turn_event(db, call_id, turn_id)
                if active.cancel.is_set():
                    raise asyncio.CancelledError
                run_id = str(uuid5(NAMESPACE_URL, f"alles-local-voice:{call_id}:{turn_id}"))
                run = jarvis_handoff.create_handoff(
                    db,
                    db.get(Session, call.session_id),
                    text,
                    request_id=run_id,
                    endpoint_override=selection.endpoint.id,
                    model_override=selection.model,
                    permission_mode="approve",
                    effort="medium",
                    reasoning_mode="automatic",
                )
                aide_calls.append_event(
                    db, call, "local_handoff", provider_event_id=f"handoff:{run.id}", data=context
                )
                aide_voice.update(event, state="handoff", run_id=run.id)
                db.commit()
                handoff = {"id": run.id, "state": run.state}
            jarvis_handoff.launch(handoff["id"])
            yield _sse({"background_run": handoff})
        else:
            with SessionLocal() as db:
                response = await create_chat_response(
                    ChatRequest(
                        session_id=context["session_id"], message=text, permission_mode="approve"
                    ),
                    request,
                    db,
                    voice_context=context,
                )
            # Keep the canonical stream's answer, tools, errors and durable receipts intact.
            async with aclosing(response.body_iterator):
                async for chunk in response.body_iterator:
                    if chunk != b"data: [DONE]\n\n":
                        yield chunk
    except asyncio.CancelledError:
        active.cancel.set()
        raise
    except (ApiError, local_voice.LocalVoiceError) as exc:
        error_code = getattr(exc, "code", "voice_unavailable")
        yield _sse(
            {
                "error": str(exc.detail)
                if isinstance(exc, ApiError)
                else "local speech could not complete this turn",
                "code": error_code,
            }
        )
    except Exception:
        error_code = "voice_turn_failed"
        yield _sse(
            {
                "error": "this voice turn could not complete; check its saved receipt before trying again",
                "code": error_code,
            }
        )
    finally:
        if context:
            _finish_unanswered(context, active.cancel.is_set(), error_code)
        if aide_voice._active.get((call_id, turn_id)) is active:
            aide_voice._active.pop((call_id, turn_id), None)
    yield _sse({"voice_turn": _receipt(call_id, turn_id)})
    yield b"data: [DONE]\n\n"


_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/mpeg"}


@router.post("/calls/{call_id}/turns")
async def start_turn(call_id: str, turn_id: str, request: Request, db=Depends(get_db)):
    aide_voice.identity(turn_id)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in _AUDIO_TYPES:
        raise ApiError(415, "voice_audio_type", "send a supported audio recording")
    try:
        size = int(request.headers.get("content-length", "0"))
        duration = float(request.headers.get("x-audio-duration-seconds", "0"))
    except ValueError as exc:
        raise ApiError(400, "voice_audio_bounds", "invalid recording size or duration") from exc
    if (
        size < 0
        or size > aide_voice.MAX_AUDIO_BYTES
        or not math.isfinite(duration)
        or duration < 0
        or duration > aide_voice.MAX_AUDIO_SECONDS
    ):
        raise ApiError(413, "voice_audio_too_large", "record at most 60 seconds and 8 MiB")
    # Raw-body streaming bounds memory before any multipart parser or decoder sees it.
    audio = bytearray()
    async for chunk in request.stream():
        if len(audio) + len(chunk) > aide_voice.MAX_AUDIO_BYTES:
            raise ApiError(413, "voice_audio_too_large", "record at most 8 MiB")
        audio.extend(chunk)
    if not audio:
        raise ApiError(422, "voice_audio_empty", "record an utterance first")
    call = aide_voice.lock_call(db, call_id)
    event, created = aide_voice.reserve_turn(db, call, turn_id, audio, content_type)
    db.commit()
    if not created:

        async def replay():
            yield _sse({"voice_turn": {**aide_voice.receipt(event), "replayed": True}})
            yield b"data: [DONE]\n\n"

        stream = replay()
    else:
        aide_voice._active[(call_id, turn_id)] = aide_voice.ActiveTurn(asyncio.Event())
        stream = _run_turn(call_id, turn_id, bytes(audio), content_type, request)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "cache-control": "no-store",
            "x-accel-buffering": "no",
        },
    )


class SpeechBody(BaseModel):
    clause_id: str = Field(min_length=36, max_length=36)
    text: str = Field(min_length=1, max_length=aide_voice.MAX_CLAUSE_CHARS)


@router.post("/calls/{call_id}/turns/{turn_id}/speech")
async def speech(call_id: str, turn_id: str, body: SpeechBody, db=Depends(get_db)):
    clause_id = aide_voice.identity(body.clause_id)
    call = aide_voice.lock_call(db, call_id, live=True)
    event = aide_voice.turn_event(db, call_id, turn_id)
    values = aide_voice.data(event)
    if values.get("playback_cancelled") or values["state"] in {
        "accepted",
        "transcribing",
        "cancelled",
        "failed",
        "interrupted",
    }:
        raise ApiError(409, "voice_playback_stopped", "this turn is not accepting speech playback")
    key = f"speech:{turn_id}:{clause_id}"
    from core.database import AideCallEvent

    if db.query(AideCallEvent).filter_by(call_id=call_id, provider_event_id=key).first():
        raise ApiError(409, "voice_clause_replayed", "this speech clause was already requested")
    aide_calls.append_event(
        db, call, "local_speech", provider_event_id=key, data={"turn_id": turn_id}
    )
    db.commit()
    cancel = asyncio.Event()
    owner = (call_id, turn_id, clause_id)
    aide_voice._speech[owner] = cancel

    stream = local_voice.synthesize(body.text.strip(), ":".join(owner), cancel)
    try:
        first = await anext(stream)
    except (local_voice.LocalVoiceError, StopAsyncIteration) as exc:
        cancel.set()
        aide_voice._speech.pop(owner, None)
        await stream.aclose()
        raise ApiError(
            503, getattr(exc, "code", "voice_speech_empty"), "local speech could not start"
        ) from exc
    except BaseException:
        cancel.set()
        aide_voice._speech.pop(owner, None)
        await stream.aclose()
        raise

    async def chunks():
        try:
            async with aclosing(stream):
                if not cancel.is_set():
                    yield first
                async for chunk in stream:
                    if cancel.is_set():
                        break
                    yield chunk
        finally:
            cancel.set()
            aide_voice._speech.pop(owner, None)

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "cache-control": "no-store",
            "X-Audio-Sample-Rate": "24000",
            "X-Audio-Channels": "1",
            "X-Audio-Format": "pcm_s16le",
            "x-accel-buffering": "no",
        },
    )


@router.post("/calls/{call_id}/turns/{turn_id}/cancel")
async def cancel_turn(call_id: str, turn_id: str, db=Depends(get_db)):
    aide_voice.lock_call(db, call_id)
    event = aide_voice.turn_event(db, call_id, turn_id)
    values = aide_voice.data(event)
    aide_voice.update(
        event,
        playback_cancelled=True,
        **({"state": "cancelled"} if values["state"] not in aide_voice.TERMINAL else {}),
    )
    db.commit()
    aide_voice.cancel_owned(call_id, turn_id)
    return {**aide_voice.receipt(event), "tasks_cancelled": False}


@router.post("/calls/{call_id}/hangup")
async def hangup(call_id: str, db=Depends(get_db)):
    call = aide_voice.lock_call(db, call_id)
    aide_calls.end_call(db, call)
    db.commit()
    aide_voice.cancel_owned(call_id)
    return {**aide_voice.public_call(db, call), "tasks_cancelled": False}
