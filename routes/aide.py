"""Canonical Aide conversation, live calls, and the pi bridge."""

import asyncio
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner, verify_session
from core.database import AideCall, Session, get_db
from core.rate_limit import enforce_rate_limit
from core.settings import auth_enabled
from services import aide_calls, pi_agent, realtime
from services.aide_conversation import get_or_create_primary

router = APIRouter(prefix="/api/aide")
# pi's web tools call back here from the same machine with their chat's own token; it sits
# outside /api because pi has no alles sign-in
bridge = APIRouter(prefix="/pi-bridge")


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


def _capability() -> dict:
    harness = pi_agent.settings()["harness"]
    if harness in pi_agent.NATIVE:
        return {**pi_agent.status(harness), "harness": harness}
    return {"harness": harness, "state": "ready"}


@router.get("/capabilities")
def capabilities(db: DbSession = Depends(get_db)):
    conversation = get_or_create_primary(db)
    db.commit()
    return {
        "conversation": {"session_id": conversation.id, "permanent": True},
        "voice": realtime.status(db),
        "coding": _capability(),
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


class TelegramChatBody(BaseModel):
    enabled: bool = False
    token: str = Field(default="", max_length=200)  # blank keeps the saved one


class PhotonBody(BaseModel):
    enabled: bool = False
    project_id: str = Field(default="", max_length=200)
    project_secret: str = Field(default="", max_length=500)  # blank keeps the saved one
    owner_handles: list[str] = Field(default_factory=list, max_length=10)
    read_receipts: bool | None = None  # left out keeps the saved choice (on by default)


class SignInOpenBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    width: int = Field(default=1280, ge=200, le=4000)
    height: int = Field(default=900, ge=200, le=4000)


class SignInClickBody(BaseModel):
    x: float = Field(ge=0, le=4000)
    y: float = Field(ge=0, le=4000)


class SignInTypeBody(BaseModel):
    # what the owner types for the page; never logged, echoed or kept
    text: str = Field(default="", max_length=500, repr=False)
    key: str = Field(default="", max_length=20)


class SignInScrollBody(BaseModel):
    dy: float = Field(ge=-4000, le=4000)


class BridgeSearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=400)
    count: int = Field(default=6, ge=1, le=10)


class BridgeFetchBody(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


_LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost"}


@router.get("/channels/photon")
def photon_status():
    from services import photon_channel

    return photon_channel.public()


@router.put("/channels/photon", dependencies=[Depends(require_recent_owner)])
async def photon_settings(body: PhotonBody):
    """turn texting Aide over iMessage on or off; only the listed handles get answers."""
    from core.settings import save_settings
    from services import photon_channel

    handles = [h.strip()[:120] for h in body.owner_handles if h.strip()]
    if body.enabled and not handles:
        raise ApiError(400, "photon_owner_required", "add the phone number or email you text from")
    patch = {
        "photon_enabled": body.enabled,
        "photon_project_id": body.project_id.strip(),
        "photon_owner_handles": handles,
    }
    if body.read_receipts is not None:
        patch["photon_read_receipts"] = body.read_receipts
    if body.project_secret.strip():
        patch["photon_project_secret"] = body.project_secret.strip()
    save_settings(patch)
    # register the owner's numbers now so the reply can say which line to text
    if body.enabled:
        await photon_channel.register_numbers()
    await photon_channel.restart()
    return photon_channel.public()


@router.get("/channels/telegram")
def telegram_status():
    from services import telegram_channel

    return telegram_channel.public()


@router.put("/channels/telegram", dependencies=[Depends(require_recent_owner)])
async def telegram_settings(body: TelegramChatBody):
    """turn texting Aide on Telegram on or off. the bot token and chat id are the ones telegram
    notifications use; turning it on finds the chat when none is saved yet."""
    from core.settings import save_settings
    from services import telegram_channel

    patch: dict = {"telegram_chat_enabled": body.enabled}
    token = body.token.strip() or telegram_channel.settings()["token"]
    if body.token.strip():
        if not telegram_channel.TOKEN_RE.fullmatch(token):
            raise ApiError(
                400, "telegram_token_missing", "paste the bot token from BotFather first"
            )
        patch["notify_telegram_token"] = token
    if body.enabled and (body.token.strip() or not telegram_channel.settings()["chat_id"]):
        try:
            patch["notify_telegram_chat_id"] = telegram_channel.find_chat(token)["chat_id"]
        except telegram_channel.TelegramError as exc:
            raise ApiError(exc.status, exc.code, exc.message) from exc
    save_settings(patch)
    await telegram_channel.restart()
    return telegram_channel.public()


@router.post("/channels/photon/connect", dependencies=[Depends(require_recent_owner)])
# stays async: creates a task on the running loop
async def photon_connect():
    """sign in to Photon once in the browser; alles sets up the project, secret and numbers."""
    from services import photon_setup

    return photon_setup.start_login()


# ── signing in to sites in Aide's errand browser ──
# the owner drives the same headless page through screenshots; tokens can't reach any of this


def _owner_session(request: Request):
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        raise ApiError(403, "owner_session_required", "sign in to alles in the browser to do this")


async def _signin_call(fn, *args):
    try:
        return await fn(*args)
    except ImportError as exc:
        raise ApiError(
            503, "browser_missing", "Aide's browser isn't installed on this server"
        ) from exc
    except LookupError as exc:
        raise ApiError(409, "signin_closed", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(400, "signin_refused", str(exc)) from exc


@router.get("/browser/sites", dependencies=[Depends(_owner_session)])
def browser_sites():
    from services import browser_tool

    return {"sites": browser_tool.signed_in_sites(), "open": browser_tool._b.owner_active()}


@router.post(
    "/browser/signin",
    dependencies=[Depends(_owner_session), Depends(require_recent_owner)],
)
async def browser_signin_open(body: SignInOpenBody):
    """open a site in the errand browser for the owner to sign in; Aide waits meanwhile."""
    from services.browser_tool import _b

    try:
        return await _signin_call(_b.owner_open, body.url, body.width, body.height)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            502, "signin_load_failed", "that page didn't load; check the address"
        ) from exc


@router.get("/browser/signin/frame", dependencies=[Depends(_owner_session)])
async def browser_signin_frame():
    from services.browser_tool import _b

    image = await _signin_call(_b.owner_frame)
    return Response(image, media_type="image/jpeg", headers={"cache-control": "no-store"})


@router.get("/browser/signin", dependencies=[Depends(_owner_session)])
async def browser_signin_state():
    from services.browser_tool import _b

    if not _b.owner_active():
        return {"open": False}
    return await _b.owner_state()


@router.post("/browser/signin/click", dependencies=[Depends(_owner_session)])
async def browser_signin_click(body: SignInClickBody):
    from services.browser_tool import _b

    await _signin_call(_b.owner_click, body.x, body.y)
    return {"ok": True}


@router.post("/browser/signin/type", dependencies=[Depends(_owner_session)])
async def browser_signin_type(body: SignInTypeBody):
    from services.browser_tool import _b

    if body.key:
        await _signin_call(_b.owner_key, body.key)
    elif body.text:
        await _signin_call(_b.owner_type, body.text)
    return {"ok": True}


@router.post("/browser/signin/scroll", dependencies=[Depends(_owner_session)])
async def browser_signin_scroll(body: SignInScrollBody):
    from services.browser_tool import _b

    await _signin_call(_b.owner_scroll, body.dy)
    return {"ok": True}


@router.post("/browser/signin/back", dependencies=[Depends(_owner_session)])
async def browser_signin_back():
    from services.browser_tool import _b

    await _signin_call(_b.owner_back)
    return {"ok": True}


@router.post("/browser/signin/done", dependencies=[Depends(_owner_session)])
async def browser_signin_done():
    from services.browser_tool import _b

    return {"sites": await _signin_call(_b.owner_close), "open": False}


@router.delete(
    "/browser/sites/{site}",
    dependencies=[Depends(_owner_session), Depends(require_recent_owner)],
)
async def browser_sign_out(site: str):
    from services.browser_tool import _b, signed_in_sites

    if site not in {row["site"] for row in signed_in_sites()}:
        raise ApiError(404, "signin_unknown", "no saved sign-in for that site")
    return {"sites": await _signin_call(_b.sign_out, site), "open": _b.owner_active()}


@router.delete(
    "/browser/sites",
    dependencies=[Depends(_owner_session), Depends(require_recent_owner)],
)
async def browser_forget_everything():
    from services.browser_tool import _b

    await _signin_call(_b.forget_everything)
    return {"sites": [], "open": False}


def _bridge_chat(request: Request):
    client = (request.client.host if request.client else "") or ""
    if client not in _LOCAL_CLIENTS:
        raise ApiError(403, "bridge_local_only", "only pi on this machine can call this")
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    chat = pi_agent.bridge_chat(token)
    if chat is None:
        raise ApiError(401, "bridge_token", "unknown pi chat")
    return chat


@bridge.post("/search")
async def bridge_search(body: BridgeSearchBody, request: Request):
    """web_search for pi, through the owner's own search engines."""
    from services import andromeda

    chat = _bridge_chat(request)
    chat.last_active = time.monotonic()
    found = await andromeda.normal_search(body.query, max_results=body.count)
    rows = [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet", "")}
        for r in found.get("results") or []
    ]
    return {"results": rows[: body.count], "provider": found.get("provider", "")}


class BridgeToolBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    args: dict = Field(default_factory=dict)
    confirmed: bool = False


@bridge.post("/tool")
async def bridge_tool(body: BridgeToolBody, request: Request):
    """one of alles's own tools for pi: docs, tasks, calendar, memory and the like."""
    from core.settings import load_settings
    from services import agent_tools

    chat = _bridge_chat(request)
    chat.last_active = time.monotonic()
    tool = next((t for t in pi_agent.bridge_tools() if t["name"] == body.name), None)
    if tool is None:
        raise ApiError(404, "bridge_tool_unknown", "pi can't use that alles tool")
    if tool["changes"] and chat.writes != "allow" and not body.confirmed:
        raise ApiError(403, "bridge_tool_needs_ok", "the owner has to allow this change first")
    agent_tools.set_agent_ctx(settings=load_settings(), session_id="")
    try:
        result = await agent_tools.execute(tool["tool"], body.args)
    except Exception as exc:  # a bad argument comes back to pi as a failed step it can fix
        result = {
            "output": f"{tool['tool']} failed: {type(exc).__name__}: {exc}"[:500],
            "error": True,
        }
    return {"output": str(result.get("output") or "")[:40_000], "error": bool(result.get("error"))}


@bridge.post("/fetch")
async def bridge_fetch(body: BridgeFetchBody, request: Request):
    """web_fetch for pi; the same safe fetcher andromeda uses, so private addresses stay off."""
    from services.net_guard import is_safe_url
    from services.research.search import fetch_webpage_content

    _bridge_chat(request)
    if not is_safe_url(body.url):
        raise ApiError(400, "unsafe_url", "that address isn't a public web page")
    page = await asyncio.to_thread(fetch_webpage_content, body.url, 15)
    return {"title": page.get("title", ""), "content": str(page.get("content") or "")[:40_000]}
