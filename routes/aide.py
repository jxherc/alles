"""Canonical Aide conversation, live-call, and optional coding capabilities."""

import json
from contextlib import aclosing
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner, verify_session
from core.database import AideCall, AideCodingRun, Session, get_db
from core.rate_limit import enforce_rate_limit
from core.settings import auth_enabled
from services import aide_calls, aide_coding, realtime
from services.aide_conversation import get_or_create_primary
from services.coding_backends.dsh import (
    DshBusinessError,
    DshConfigurationError,
    DshProtocolError,
    DshTransportError,
)

router = APIRouter(prefix="/api/aide")


def _request_id(value: str, code: str) -> str:
    try:
        canonical = str(UUID(value))
        if value.lower() != canonical:
            raise ValueError
        return canonical
    except ValueError as exc:
        raise ApiError(400, code, "use a canonical request_id") from exc


def _locked_call(db: DbSession, call_id: str) -> AideCall | None:
    """Serialize event sequence allocation and idempotency checks for one call."""
    found = db.query(AideCall.id).filter(AideCall.id == call_id).scalar()
    if not found:
        return None
    db.query(AideCall).filter(AideCall.id == call_id).update(
        {AideCall.id: AideCall.id}, synchronize_session=False
    )
    db.expire_all()
    return db.get(AideCall, call_id)


@router.get("/capabilities")
def capabilities(db: DbSession = Depends(get_db)):
    conversation = get_or_create_primary(db)
    db.commit()
    return {
        "conversation": {"session_id": conversation.id, "permanent": True},
        "voice": realtime.status(db),
        "coding": aide_coding.connection_status(db),
        "durable_tasks": {
            "available": True,
            "transport": "jarvis_run_events",
            "survives_navigation": True,
            "queued_runs_resume_after_restart": True,
        },
    }


class CreateCallBody(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)


@router.post("/calls")
def create_call(body: CreateCallBody, db: DbSession = Depends(get_db)):
    status = realtime.status(db)
    if not status["available"]:
        raise ApiError(503, "realtime_unavailable", status["reason"])
    identity = _request_id(body.request_id, "invalid_call_identity")
    primary = get_or_create_primary(db)
    db.query(Session).filter(Session.id == primary.id).update(
        {Session.id: Session.id}, synchronize_session=False
    )
    db.expire_all()
    try:
        row, created = aide_calls.create_call(
            db,
            identity,
            provider="openai-realtime",
            model=status["model"],
        )
    except ValueError as exc:
        raise ApiError(409, str(exc), str(exc).replace("_", " ")) from exc
    db.commit()
    db.refresh(row)
    return {**aide_calls.public_call(row), "created": created}


@router.get("/calls/{call_id}")
def get_call(call_id: str, db: DbSession = Depends(get_db)):
    row = db.get(AideCall, call_id)
    if not row:
        raise HTTPException(404, "call not found")
    return aide_calls.public_call(row)


@router.post("/calls/{call_id}/offer", response_class=PlainTextResponse)
async def negotiate_call(call_id: str, request: Request, db: DbSession = Depends(get_db)):
    require_recent_owner(request)
    try:
        offer = (await request.body()).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ApiError(400, "invalid_realtime_offer", "send a UTF-8 SDP offer") from exc
    try:
        row = _locked_call(db, call_id)
        if not row:
            raise HTTPException(404, "call not found")
        target = aide_calls.reserve_offer(db, row, offer)
        # A committed reservation rejects concurrent/replayed offers without keeping
        # SQLite locked while the provider establishes the WebRTC connection.
        db.commit()
        answer = await realtime.negotiate_offer(target, offer)
        row = _locked_call(db, call_id)
        if not row:
            raise HTTPException(404, "call not found")
        aide_calls.mark_connected(db, row)
    except ValueError as exc:
        raise ApiError(409, str(exc), str(exc).replace("_", " ")) from exc
    except RuntimeError as exc:
        raise ApiError(502, "realtime_provider_error", str(exc)) from exc
    db.commit()
    return PlainTextResponse(answer, media_type="application/sdp")


class TranscriptBody(BaseModel):
    provider_event_id: str = Field(min_length=1, max_length=200)
    role: str
    text: str = Field(min_length=1, max_length=50_000)


@router.post("/calls/{call_id}/transcripts")
def save_transcript(
    call_id: str,
    body: TranscriptBody,
    request: Request,
    db: DbSession = Depends(get_db),
):
    # The offer already required fresh owner approval before contacting the
    # provider. Saving that call must not expire halfway through a conversation.
    if auth_enabled():
        if request.headers.get("authorization", "").lower().startswith("bearer "):
            raise ApiError(403, "owner_session_required", "sign in as the owner to save this call")
        if not verify_session(request.cookies.get("aide_session", "")):
            raise ApiError(401, "owner_session_required", "sign in again to save this call")
        enforce_rate_limit(
            request, f"owner:{request.method}:{request.url.path}", limit=30, window_seconds=60
        )
    row = _locked_call(db, call_id)
    if not row:
        raise HTTPException(404, "call not found")
    if row.provider != "openai-realtime" or row.connected_at is None:
        raise ApiError(409, "call_not_negotiated", "this call has not been connected")
    try:
        event, created = aide_calls.append_final_transcript(
            db,
            row,
            role=body.role,
            text=body.text,
            provider_event_id=body.provider_event_id,
        )
    except ValueError as exc:
        raise ApiError(409, str(exc), str(exc).replace("_", " ")) from exc
    db.commit()
    return {
        "call_id": row.id,
        "session_id": row.session_id,
        "event_id": event.id,
        "created": created,
    }


@router.post("/calls/{call_id}/hangup")
def hangup(call_id: str, db: DbSession = Depends(get_db)):
    row = _locked_call(db, call_id)
    if not row:
        raise HTTPException(404, "call not found")
    aide_calls.end_call(db, row)
    db.commit()
    db.refresh(row)
    return {**aide_calls.public_call(row), "tasks_cancelled": False}


def _coding_bridge_error(exc: Exception) -> ApiError:
    if isinstance(exc, DshConfigurationError):
        return ApiError(409, str(exc), str(exc).replace("_", " "))
    if isinstance(exc, DshBusinessError):
        return ApiError(409, str(exc), "DSH rejected the request")
    if isinstance(exc, (DshTransportError, DshProtocolError)):
        return ApiError(502, "dsh_bridge_unavailable", str(exc))
    return ApiError(500, "dsh_coding_error", "the coding request could not be completed")


class PairCodingBody(BaseModel):
    base_url: str = Field(min_length=1, max_length=300)
    code: str = Field(pattern=r"^\d{8}$")


class StartCodingBody(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    aide_session_id: str | None = Field(default=None, max_length=100)
    workspace_id: str = Field(min_length=1, max_length=300)
    workspace_path: str = Field(default="", max_length=4000)
    prompt: str = Field(min_length=1, max_length=50_000)


class ContinueCodingBody(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    prompt: str = Field(min_length=1, max_length=50_000)


@router.get("/coding/status", dependencies=[Depends(require_recent_owner)])
def coding_status(db: DbSession = Depends(get_db)):
    return aide_coding.connection_status(db)


@router.post("/coding/pair", dependencies=[Depends(require_recent_owner)])
async def coding_pair(body: PairCodingBody, db: DbSession = Depends(get_db)):
    try:
        return await aide_coding.pair(db, base_url=body.base_url, code=body.code)
    except (DshConfigurationError, DshBusinessError, DshTransportError, DshProtocolError) as exc:
        raise _coding_bridge_error(exc) from exc


@router.delete("/coding/connection", dependencies=[Depends(require_recent_owner)])
def coding_disconnect(db: DbSession = Depends(get_db)):
    return {"disconnected": aide_coding.disconnect(db)}


@router.post("/coding/health", dependencies=[Depends(require_recent_owner)])
async def coding_health(db: DbSession = Depends(get_db)):
    try:
        return await aide_coding.check_health(db)
    except (DshConfigurationError, DshBusinessError, DshTransportError, DshProtocolError) as exc:
        raise _coding_bridge_error(exc) from exc


@router.get("/coding/workspaces", dependencies=[Depends(require_recent_owner)])
async def coding_workspaces(db: DbSession = Depends(get_db)):
    try:
        result = await aide_coding.backend_for(db).list_workspaces()
    except (DshConfigurationError, DshBusinessError, DshTransportError, DshProtocolError) as exc:
        raise _coding_bridge_error(exc) from exc
    items = result.get("items") if isinstance(result.get("items"), list) else []
    return {
        "items": [
            {
                "workspace_id": str(item.get("workspaceId") or ""),
                "path": str(item.get("path") or ""),
                "title": str(item.get("title") or item.get("path") or "workspace"),
            }
            for item in items
            if isinstance(item, dict) and item.get("workspaceId")
        ]
    }


@router.get("/coding/runs", dependencies=[Depends(require_recent_owner)])
def coding_runs(limit: int = 20, db: DbSession = Depends(get_db)):
    return {"items": aide_coding.list_runs(db, limit=limit)}


@router.post("/coding/runs", dependencies=[Depends(require_recent_owner)])
async def coding_start(body: StartCodingBody, db: DbSession = Depends(get_db)):
    identity = _request_id(body.request_id, "invalid_coding_run_identity")
    if body.aide_session_id and db.get(Session, body.aide_session_id) is None:
        raise ApiError(404, "aide_session_not_found", "Aide session not found")
    try:
        run, created = await aide_coding.start_run(
            db,
            run_id=identity,
            aide_session_id=body.aide_session_id,
            workspace_id=body.workspace_id.strip(),
            workspace_path=body.workspace_path.strip(),
            prompt=body.prompt.strip(),
        )
    except ValueError as exc:
        raise ApiError(409, str(exc), str(exc).replace("_", " ")) from exc
    except DshConfigurationError as exc:
        raise _coding_bridge_error(exc) from exc
    return {**aide_coding.public_run(run), "created": created}


def _coding_run(db: DbSession, run_id: str) -> AideCodingRun:
    row = db.get(AideCodingRun, run_id)
    if row is None:
        raise ApiError(404, "coding_run_not_found", "coding run not found")
    return row


@router.get("/coding/runs/{run_id}", dependencies=[Depends(require_recent_owner)])
def coding_run(run_id: str, db: DbSession = Depends(get_db)):
    return aide_coding.public_run(_coding_run(db, run_id))


@router.get("/coding/runs/{run_id}/events", dependencies=[Depends(require_recent_owner)])
def coding_events(run_id: str, db: DbSession = Depends(get_db)):
    _coding_run(db, run_id)
    return {
        "items": aide_coding.local_events(db, run_id),
        "remote_events": aide_coding.saved_remote_events(db, run_id),
    }


@router.post("/coding/runs/{run_id}/refresh", dependencies=[Depends(require_recent_owner)])
async def coding_refresh(run_id: str, db: DbSession = Depends(get_db)):
    row = _coding_run(db, run_id)
    try:
        row, remote_events = await aide_coding.refresh_run(db, row)
    except DshConfigurationError as exc:
        raise _coding_bridge_error(exc) from exc
    return {**aide_coding.public_run(row), "remote_events": remote_events}


@router.post("/coding/runs/{run_id}/resume", dependencies=[Depends(require_recent_owner)])
async def coding_resume(run_id: str, db: DbSession = Depends(get_db)):
    row = _coding_run(db, run_id)
    try:
        row = await aide_coding.resume_prompt(db, row)
    except ValueError as exc:
        raise ApiError(409, str(exc), str(exc).replace("_", " ")) from exc
    except DshConfigurationError as exc:
        raise _coding_bridge_error(exc) from exc
    return aide_coding.public_run(row)


@router.post("/coding/runs/{run_id}/continue", dependencies=[Depends(require_recent_owner)])
async def coding_continue(run_id: str, body: ContinueCodingBody, db: DbSession = Depends(get_db)):
    row = _coding_run(db, run_id)
    try:
        row = await aide_coding.continue_run(
            db,
            row,
            request_id=_request_id(body.request_id, "invalid_coding_run_identity"),
            prompt=body.prompt,
        )
    except ValueError as exc:
        raise ApiError(409, str(exc), str(exc).replace("_", " ")) from exc
    except DshConfigurationError as exc:
        raise _coding_bridge_error(exc) from exc
    return aide_coding.public_run(row)


@router.post("/coding/runs/{run_id}/cancel", dependencies=[Depends(require_recent_owner)])
async def coding_cancel(run_id: str, db: DbSession = Depends(get_db)):
    row = _coding_run(db, run_id)
    try:
        row = await aide_coding.cancel_run(db, row)
    except DshConfigurationError as exc:
        raise _coding_bridge_error(exc) from exc
    return aide_coding.public_run(row)


@router.get("/coding/runs/{run_id}/live", dependencies=[Depends(require_recent_owner)])
async def coding_live(run_id: str, db: DbSession = Depends(get_db)):
    row = _coding_run(db, run_id)
    session_id = row.provider_session_id
    backend = aide_coding.backend_for(db)
    try:
        backend._validate()
    except DshConfigurationError as exc:
        raise _coding_bridge_error(exc) from exc
    db.commit()

    async def frames():
        try:
            async with aclosing(backend.live_events(session_id)) as events:
                async for frame in events:
                    yield "data: " + json.dumps(frame, separators=(",", ":")) + "\n\n"
        except (DshTransportError, DshProtocolError) as exc:
            yield (
                "event: bridge-error\ndata: "
                + json.dumps(
                    {
                        "code": str(exc),
                        "message": "coding connection lost; reconnect and refresh the run",
                    }
                )
                + "\n\n"
            )

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


class CodingQuestionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=300)
    selected: list[str] = Field(default_factory=list, max_length=100)
    custom: str | None = Field(default=None, max_length=12_000)


class CodingResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rpc_id: str = Field(min_length=1, max_length=300)
    outcome: Literal["allowed-once", "rejected"] | None = None
    answers: list[CodingQuestionAnswer] | None = Field(default=None, max_length=100)
    cancelled: StrictBool = False


@router.post("/coding/runs/{run_id}/respond", dependencies=[Depends(require_recent_owner)])
async def coding_respond(run_id: str, body: CodingResponseBody, db: DbSession = Depends(get_db)):
    row = _coding_run(db, run_id)
    session_id = row.provider_session_id
    backend = aide_coding.backend_for(db)
    db.commit()
    try:
        return await backend.respond(
            session_id,
            body.rpc_id,
            outcome=body.outcome,
            answers=[answer.model_dump(exclude_none=True) for answer in body.answers]
            if body.answers is not None
            else None,
            cancelled=body.cancelled,
        )
    except (DshConfigurationError, DshBusinessError, DshTransportError, DshProtocolError) as exc:
        raise _coding_bridge_error(exc) from exc
    except ValueError as exc:
        raise ApiError(
            409, str(exc), "choose a valid response to the current coding request"
        ) from exc
