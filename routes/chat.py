import json, asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, Session, Message, ModelEndpoint
from core.settings import load_settings
from services.llm import stream_chat, simple_complete

router = APIRouter(prefix="/api")

# active stream registry — session_id → asyncio.Event for stop
_streams: dict[str, asyncio.Event] = {}


def _resolve_endpoint(session: Session, db: DbSession) -> ModelEndpoint | None:
    if session.endpoint_id:
        return db.get(ModelEndpoint, session.endpoint_id)
    # fallback: first enabled endpoint
    return db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()


def _build_messages(session: Session, user_text: str, settings: dict) -> list[dict]:
    msgs = [{"role": "system", "content": settings.get("system_prompt", "You are aide, a helpful AI assistant.")}]
    limit = settings.get("context_limit", 40)
    history = list(session.messages)[-limit:]
    for m in history:
        msgs.append({"role": m.role, "content": m.content})
    msgs.append({"role": "user", "content": user_text})
    return msgs


async def _auto_name(session_id: str, user_text: str, ep: ModelEndpoint, model: str):
    """rename session after 3rd message — fire and forget"""
    prompt = [
        {"role": "system", "content": "You produce ultra-short chat session titles."},
        {"role": "user", "content": f"Give a 3-5 word title for a chat that starts with: {user_text[:200]}\nRespond with ONLY the title, no quotes or punctuation."},
    ]
    name = await simple_complete(prompt, ep.base_url, ep.api_key, model, max_tokens=20)
    if not name or len(name) > 80:
        return
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        s = db.get(Session, session_id)
        if s:
            s.name = name.strip().lower()
            db.commit()
    finally:
        db.close()


class ChatRequest(BaseModel):
    session_id: str
    message: str
    mode: str = "chat"   # chat | agent


async def _sse(gen):
    """wrap async generator into SSE text/event-stream"""
    async for chunk in gen:
        yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_and_save(
    session_id: str,
    user_text: str,
    messages: list[dict],
    ep: ModelEndpoint,
    model: str,
    stop_event: asyncio.Event,
    db_factory,
):
    accumulated = []
    thinking_acc = []
    usage = {}

    async for chunk in stream_chat(messages, ep.base_url, ep.api_key, model):
        if stop_event.is_set():
            break
        if "error" in chunk:
            yield chunk
            break
        if "thinking" in chunk:
            thinking_acc.append(chunk["thinking"])
            yield chunk
        elif "delta" in chunk:
            accumulated.append(chunk["delta"])
            yield chunk
        elif "done" in chunk:
            usage = chunk.get("usage", {})
            yield chunk

    # save to db
    full_text = "".join(accumulated)
    if not full_text:
        return

    db = db_factory()
    try:
        s = db.get(Session, session_id)
        if not s:
            return

        # save user message if not already there (first time)
        last = s.messages[-1] if s.messages else None
        if not last or last.role != "user" or last.content != user_text:
            um = Message(session_id=session_id, role="user", content=user_text)
            db.add(um)

        meta = {"usage": usage}
        if thinking_acc:
            meta["thinking"] = "".join(thinking_acc)
        am = Message(
            session_id=session_id,
            role="assistant",
            content=full_text,
            meta=json.dumps(meta),
        )
        db.add(am)
        s.message_count = (s.message_count or 0) + 1
        s.last_message_at = datetime.utcnow()
        db.commit()

        # auto-name after 3rd message
        if s.message_count == 3:
            asyncio.create_task(_auto_name(session_id, user_text, ep, model))
    finally:
        db.close()


# POST /api/chat
@router.post("/chat")
async def chat(body: ChatRequest, background_tasks: BackgroundTasks, db: DbSession = Depends(get_db)):
    s = db.get(Session, body.session_id)
    if not s:
        raise HTTPException(404, "session not found")

    ep = _resolve_endpoint(s, db)
    if not ep:
        raise HTTPException(400, "no model endpoint configured — add one in settings")

    model = s.model or (ep.models_list()[0] if ep.models_list() else "")
    if not model:
        raise HTTPException(400, "no model selected")

    settings = load_settings()
    messages = _build_messages(s, body.message, settings)

    stop_event = asyncio.Event()
    _streams[body.session_id] = stop_event

    from core.database import SessionLocal as _SF
    gen = _stream_and_save(body.session_id, body.message, messages, ep, model, stop_event, _SF)

    async def cleanup_gen():
        try:
            async for chunk in gen:
                yield chunk
        finally:
            _streams.pop(body.session_id, None)

    return StreamingResponse(_sse(cleanup_gen()), media_type="text/event-stream",
                             headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


# POST /api/chat/stop/{session_id}
@router.post("/chat/stop/{session_id}")
def stop_chat(session_id: str):
    ev = _streams.get(session_id)
    if ev:
        ev.set()
        return {"ok": True}
    return {"ok": False, "msg": "no active stream"}


# GET /api/chat/status/{session_id}
@router.get("/chat/status/{session_id}")
def chat_status(session_id: str):
    return {"streaming": session_id in _streams}
