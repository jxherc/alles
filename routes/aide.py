"""Canonical Aide conversation, live calls, and pi coding chats."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner, verify_session
from core.database import AideCall, CodingProject, Session, get_db
from core.rate_limit import enforce_rate_limit
from core.settings import auth_enabled
from services import aide_calls, pi_agent, realtime
from services.aide_conversation import get_or_create_primary

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
        "coding": {"harness": "pi", **pi_agent.status()},
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


class CodeProjectBody(BaseModel):
    path: str = Field(min_length=1, max_length=4000)


class CodeModelBody(BaseModel):
    endpoint_id: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=300)


class CodeMessageBody(CodeModelBody):
    text: str = Field(min_length=1, max_length=50_000)


class CodeAnswerBody(BaseModel):
    question_id: str = Field(min_length=1, max_length=200)
    value: str | bool | None = None


def _public_choice(choice: dict | None) -> dict | None:
    if not choice:
        return None
    return {k: choice[k] for k in ("endpoint_id", "endpoint", "model")}


def _code_project(db: DbSession, project_id: str) -> CodingProject:
    row = db.get(CodingProject, project_id)
    if row is None:
        raise ApiError(404, "coding_project_not_found", "project not found")
    return row


def _code_choice(db: DbSession, body: CodeModelBody) -> dict:
    choice = pi_agent.resolve_choice(db, body.endpoint_id, body.model)
    if choice is None:
        raise ApiError(
            409,
            "coding_model_missing",
            "add a model with an api key in settings → models to code with pi",
        )
    return choice


def _code_ready() -> None:
    current = pi_agent.status()
    if current["state"] != "ready":
        raise ApiError(409, "pi_not_ready", current.get("error") or "pi is still installing")


@router.get("/code/status")
async def code_status(db: DbSession = Depends(get_db)):
    """pi's install state (starting the install when it is missing) and the models it can use."""
    _, _, choices = pi_agent.model_config(db)
    return {
        "pi": pi_agent.ensure_installed(),
        "models": [_public_choice(c) for c in choices],
        "default": _public_choice(pi_agent.resolve_choice(db)),
    }


@router.post("/code/install", dependencies=[Depends(require_recent_owner)])
async def code_install():
    return {"pi": pi_agent.ensure_installed()}


@router.get("/code/folders")
def code_folders(path: str = ""):
    try:
        return pi_agent.browse(path)
    except ValueError as exc:
        raise ApiError(400, "folder_unreadable", str(exc)) from exc


@router.get("/code/projects")
def code_projects(db: DbSession = Depends(get_db)):
    rows = db.query(CodingProject).order_by(CodingProject.last_used_at.desc()).all()
    return {"items": [pi_agent.public_project(row) for row in rows]}


@router.post("/code/projects", dependencies=[Depends(require_recent_owner)])
def code_add_project(body: CodeProjectBody, db: DbSession = Depends(get_db)):
    try:
        path = pi_agent.check_folder(body.path)
    except ValueError as exc:
        raise ApiError(400, "folder_not_allowed", str(exc)) from exc
    row = db.query(CodingProject).filter(CodingProject.path == str(path)).first()
    if row is None:
        row = CodingProject(path=str(path), name=path.name)
        db.add(row)
    row.last_used_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return pi_agent.public_project(row)


@router.delete("/code/projects/{project_id}", dependencies=[Depends(require_recent_owner)])
async def code_forget_project(project_id: str, db: DbSession = Depends(get_db)):
    row = _code_project(db, project_id)
    await pi_agent.forget_project(row.id)
    db.delete(row)
    db.commit()
    return {"forgotten": True}


@router.get("/code/projects/{project_id}/chats")
def code_chats(project_id: str, db: DbSession = Depends(get_db)):
    row = _code_project(db, project_id)
    return {"items": pi_agent.list_chats(row.id)}


@router.post("/code/projects/{project_id}/chats", dependencies=[Depends(require_recent_owner)])
async def code_new_chat(project_id: str, body: CodeMessageBody, db: DbSession = Depends(get_db)):
    row = _code_project(db, project_id)
    _code_ready()
    choice = _code_choice(db, body)
    try:
        chat = await pi_agent.open_chat(db, row, None, choice)
        seq = await chat.send(body.text)
    except RuntimeError as exc:
        raise ApiError(502, "pi_failed", str(exc)) from exc
    row.last_used_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return {"chat_id": chat.id, "seq": seq}


@router.get("/code/projects/{project_id}/chats/{chat_id}")
def code_chat(project_id: str, chat_id: str, db: DbSession = Depends(get_db)):
    row = _code_project(db, project_id)
    saved = pi_agent.transcript(row.id, chat_id)
    live = pi_agent.live_chat(chat_id)
    if saved is None and live is None:
        raise ApiError(404, "coding_chat_not_found", "chat not found")
    saved = saved or {"items": [], "model": {}}
    model = live.choice if live else saved["model"]
    return {
        "id": chat_id,
        "items": saved["items"],
        "model": {"model": model.get("model"), "endpoint_id": model.get("endpoint_id")},
        "live": live is not None,
        "busy": bool(live and live.busy),
        "partial": live.partial if live else "",
        "questions": list(live.questions.values()) if live else [],
        "stats": live.stats if live else {},
        "seq": live.seq if live else 0,
    }


async def _code_live_chat(db: DbSession, project_id: str, chat_id: str, body: CodeModelBody):
    row = _code_project(db, project_id)
    if chat := pi_agent.live_chat(chat_id):
        return chat
    _code_ready()
    try:
        return await pi_agent.open_chat(db, row, chat_id, _code_choice(db, body))
    except LookupError as exc:
        raise ApiError(404, "coding_chat_not_found", "chat not found") from exc
    except RuntimeError as exc:
        raise ApiError(502, "pi_failed", str(exc)) from exc


@router.post(
    "/code/projects/{project_id}/chats/{chat_id}/messages",
    dependencies=[Depends(require_recent_owner)],
)
async def code_message(
    project_id: str, chat_id: str, body: CodeMessageBody, db: DbSession = Depends(get_db)
):
    chat = await _code_live_chat(db, project_id, chat_id, body)
    try:
        seq = await chat.send(body.text)
    except RuntimeError as exc:
        raise ApiError(502, "pi_failed", str(exc)) from exc
    return {"seq": seq}


@router.post(
    "/code/projects/{project_id}/chats/{chat_id}/stop",
    dependencies=[Depends(require_recent_owner)],
)
async def code_stop(project_id: str, chat_id: str, db: DbSession = Depends(get_db)):
    _code_project(db, project_id)
    chat = pi_agent.live_chat(chat_id)
    if chat is not None:
        try:
            await chat.stop()
        except RuntimeError as exc:
            raise ApiError(502, "pi_failed", str(exc)) from exc
    return {"stopped": True}


@router.post(
    "/code/projects/{project_id}/chats/{chat_id}/model",
    dependencies=[Depends(require_recent_owner)],
)
async def code_model(
    project_id: str, chat_id: str, body: CodeModelBody, db: DbSession = Depends(get_db)
):
    choice = _code_choice(db, body)
    chat = await _code_live_chat(db, project_id, chat_id, body)
    try:
        await chat.set_model(choice)
    except RuntimeError as exc:
        raise ApiError(502, "pi_failed", str(exc)) from exc
    return {"model": _public_choice(choice)}


@router.post(
    "/code/projects/{project_id}/chats/{chat_id}/answer",
    dependencies=[Depends(require_recent_owner)],
)
async def code_answer(
    project_id: str, chat_id: str, body: CodeAnswerBody, db: DbSession = Depends(get_db)
):
    _code_project(db, project_id)
    chat = pi_agent.live_chat(chat_id)
    try:
        if chat is None:
            raise KeyError(body.question_id)
        await chat.answer(body.question_id, body.value)
    except KeyError as exc:
        raise ApiError(409, "question_gone", "pi is no longer waiting for that answer") from exc
    except ValueError as exc:
        raise ApiError(400, "bad_answer", str(exc)) from exc
    return {"answered": True}


@router.delete(
    "/code/projects/{project_id}/chats/{chat_id}",
    dependencies=[Depends(require_recent_owner)],
)
async def code_delete_chat(project_id: str, chat_id: str, db: DbSession = Depends(get_db)):
    row = _code_project(db, project_id)
    if not await pi_agent.delete_chat(row.id, chat_id):
        raise ApiError(404, "coding_chat_not_found", "chat not found")
    return {"deleted": True}


@router.get("/code/projects/{project_id}/chats/{chat_id}/live")
async def code_live(project_id: str, chat_id: str, after: int = 0, db: DbSession = Depends(get_db)):
    _code_project(db, project_id)
    db.commit()
    chat = pi_agent.live_chat(chat_id)
    if chat is None:
        raise ApiError(409, "coding_chat_idle", "pi is not running for this chat")
    queue: asyncio.Queue = asyncio.Queue()
    backlog = [event for event in chat.log if event["seq"] > after]
    chat.listeners.add(queue)

    async def frames():
        try:
            for event in backlog:
                yield "data: " + json.dumps(event, separators=(",", ":")) + "\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                except TimeoutError:
                    if not chat.alive:
                        yield "event: closed\ndata: {}\n\n"
                        return
                    yield ": still here\n\n"
                    continue
                if event["seq"] > after:
                    yield "data: " + json.dumps(event, separators=(",", ":")) + "\n\n"
        finally:
            chat.listeners.discard(queue)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
