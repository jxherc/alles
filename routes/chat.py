import re, json, asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, Session, Message, ModelEndpoint, Persona, SessionLocal
from core.settings import load_settings, _ARTIFACT_INSTRUCTIONS
from services.llm import stream_chat, simple_complete
from services.memory_store import inject_memories

router = APIRouter(prefix="/api")

# active stream registry — session_id → asyncio.Event for stop
_streams: dict[str, asyncio.Event] = {}


_ART_RE = re.compile(r'<aide-artifact([^>]*)>([\s\S]*?)</aide-artifact>')

def _extract_artifacts(text: str) -> list[dict]:
    out = []
    for m in _ART_RE.finditer(text):
        attrs, content = m.group(1), m.group(2)
        t  = re.search(r'type="([^"]*)"', attrs)
        ti = re.search(r'title="([^"]*)"', attrs)
        la = re.search(r'lang="([^"]*)"', attrs)
        out.append({
            "type":    t.group(1)  if t  else "code",
            "title":   ti.group(1) if ti else "artifact",
            "lang":    la.group(1) if la else "",
            "content": content,
        })
    return out


def _resolve_endpoint(session: Session, db: DbSession) -> ModelEndpoint | None:
    if session.endpoint_id:
        return db.get(ModelEndpoint, session.endpoint_id)
    # fallback: first enabled endpoint
    return db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()


def _resolve_persona(session: Session, db) -> Persona | None:
    # session-level persona first, then default persona
    if session.persona_id:
        return db.get(Persona, session.persona_id)
    return db.query(Persona).filter(Persona.is_default == True).first()


def _build_messages(session: Session, user_text: str, settings: dict,
                    db=None, file_ids: list[str] = None) -> list[dict]:
    sys_prompt = settings.get("system_prompt", "You are aide, a helpful AI assistant.")

    # project system prompt takes priority
    if db:
        proj = getattr(session, "project", None)
        if proj and proj.system_prompt:
            sys_prompt = proj.system_prompt + "\n\n" + sys_prompt

    # override with persona system prompt if one is set
    if db:
        persona = _resolve_persona(session, db)
        if persona and persona.system_prompt:
            sys_prompt = persona.system_prompt

    mem_ctx = inject_memories(user_text)
    if mem_ctx:
        sys_prompt = sys_prompt.rstrip() + "\n\n" + mem_ctx

    if settings.get("artifacts_enabled", True):
        sys_prompt = sys_prompt.rstrip() + "\n\n" + _ARTIFACT_INSTRUCTIONS

    msgs = [{"role": "system", "content": sys_prompt}]
    limit = settings.get("context_limit", 40)
    history = list(session.messages)[-limit:]
    for m in history:
        msgs.append({"role": m.role, "content": m.content})

    # handle file attachments
    user_content: list | str = user_text
    if file_ids and db:
        from core.database import Upload
        from pathlib import Path
        import base64
        text_blocks = []
        image_parts = []
        for fid in file_ids:
            rec = db.get(Upload, fid)
            if not rec:
                continue
            fpath = Path(__file__).parent.parent / "data" / "uploads" / rec.filename
            if not fpath.exists():
                continue
            if rec.mime_type.startswith("image/"):
                b64 = base64.b64encode(fpath.read_bytes()).decode()
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{rec.mime_type};base64,{b64}"},
                })
            else:
                try:
                    text_blocks.append(
                        f'<file name="{rec.original_name}">\n{fpath.read_text("utf-8", errors="replace")}\n</file>')
                except Exception:
                    pass
        if text_blocks:
            user_text = user_text + "\n\n" + "\n\n".join(text_blocks)
        if image_parts:
            user_content = [{"type": "text", "text": user_text}] + image_parts
        else:
            user_content = user_text

    msgs.append({"role": "user", "content": user_content})
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
    file_ids: list[str] = []


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
    incognito: bool = False,
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

    if incognito:
        return   # don't persist incognito messages

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
        artifacts = _extract_artifacts(full_text)
        if artifacts:
            meta["artifacts"] = artifacts
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

        # fire webhook
        asyncio.create_task(_fire_message_hook(session_id, user_text, full_text))
    finally:
        db.close()


async def _fire_message_hook(session_id: str, user_text: str, reply: str):
    try:
        from routes.webhooks import fire
        await fire("message", {"session_id": session_id, "user": user_text[:500], "reply": reply[:500]})
    except Exception:
        pass


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
    messages = _build_messages(s, body.message, settings, db, body.file_ids)

    # context compaction
    if settings.get("auto_compact", True):
        threshold = settings.get("compact_threshold", 30)
        chat_msgs = [m for m in messages if m["role"] != "system"]
        if len(chat_msgs) > threshold * 0.9:
            from services.llm import compact_messages
            messages = await compact_messages(messages, ep, model, target_len=threshold)

    stop_event = asyncio.Event()
    _streams[body.session_id] = stop_event

    from core.database import SessionLocal as _SF
    incognito = bool(getattr(s, "incognito", False))
    gen = _stream_and_save(body.session_id, body.message, messages, ep, model,
                           stop_event, _SF, incognito=incognito)

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


# GET /api/sessions/{session_id}/messages/{msg_id}/artifact/{idx}
@router.get("/sessions/{session_id}/messages/{msg_id}/artifact/{idx}")
def get_artifact(session_id: str, msg_id: str, idx: int, db: DbSession = Depends(get_db)):
    msg = db.get(Message, msg_id)
    if not msg or msg.session_id != session_id:
        raise HTTPException(404)
    meta = msg.meta_dict()
    arts = meta.get("artifacts", [])
    if idx >= len(arts):
        raise HTTPException(404)
    return arts[idx]
