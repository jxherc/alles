import asyncio
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.database import Memory, Message, ModelEndpoint, Persona, Session, SessionLocal, get_db
from core.settings import (
    _ARTIFACT_INSTRUCTIONS,
    build_aide_system_prompt,
    load_settings,
    owner_instructions,
)
from services import incognito as incognito_service
from services.agent_runtime import merge_usage, run_agent
from services.llm import simple_complete, stream_chat
from services.memory_store import apply_memory_tool_policy, inject_memories
from services.model_resolver import ModelResolutionError, resolve_model

router = APIRouter(prefix="/api")

# active stream registry — session_id → asyncio.Event for stop
_streams: dict[str, asyncio.Event] = {}


@router.get("/aide/suggestions")
def aide_suggestions(q: str = "", session_id: str = ""):
    """1f - predicted next-step suggestions for the composer (signals + the in-progress text)."""
    if not load_settings().get("intent_suggestions", True):
        return []
    from services import intent

    db = SessionLocal()
    try:
        session = db.get(Session, session_id) if session_id else None
        return intent.predict_suggestions(db, message=q, session=session, limit=2)
    finally:
        db.close()


_ART_RE = re.compile(r"<aide-artifact([^>]*)>([\s\S]*?)</aide-artifact>")


def _extract_artifacts(text: str) -> list[dict]:
    out = []
    for m in _ART_RE.finditer(text):
        attrs, content = m.group(1), m.group(2)
        t = re.search(r'type="([^"]*)"', attrs)
        ti = re.search(r'title="([^"]*)"', attrs)
        la = re.search(r'lang="([^"]*)"', attrs)
        out.append(
            {
                "type": t.group(1) if t else "code",
                "title": ti.group(1) if ti else "artifact",
                "lang": la.group(1) if la else "",
                "content": content,
            }
        )
    return out


def _resolve_endpoint(session: Session, db: DbSession) -> ModelEndpoint | None:
    if session.endpoint_id:
        return db.get(ModelEndpoint, session.endpoint_id)
    # fallback: first enabled endpoint, or a local one if the user prefers that
    eps = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
    from core.settings import load_settings
    from services.routing import pick_endpoint

    return pick_endpoint(eps, prefer_local=bool(load_settings().get("prefer_local_models")))


def _resolve_persona(session: Session, db) -> Persona | None:
    # None is the real base assistant: only an explicit session persona adds a prompt.
    if session.persona_id:
        return db.get(Persona, session.persona_id)
    return None


def _apply_persona_model(session: Session, ep: ModelEndpoint, model: str, db):
    """if the active persona pins a model, use it — and switch to an enabled endpoint
    that actually serves it when the current one doesn't."""
    p = _resolve_persona(session, db)
    if not (p and p.model):
        return ep, model
    model = p.model
    if model not in (ep.models_list() or []):
        for e in db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all():
            if model in (e.models_list() or []):
                return e, model
        raise HTTPException(400, f"persona model unavailable: {model}")
    return ep, model


def _resolve_session_model(session: Session, db, settings: dict | None = None):
    persona = _resolve_persona(session, db)
    explicit = {
        "endpoint_id": session.endpoint_id if session.model else "",
        "model": session.model or "",
    }
    workflow = {"model": persona.model} if persona and persona.model else {}
    feature = {"endpoint_id": session.endpoint_id or ""}
    try:
        selected = resolve_model(
            db,
            "aide_chat",
            explicit=explicit,
            workflow_override=workflow,
            feature_default=feature,
            settings=settings,
        )
    except ModelResolutionError as exc:
        from core.api_errors import ApiError

        raise ApiError(400, exc.code, str(exc)) from exc
    return selected.endpoint, selected.model


def _decide_mode(
    base_mode: str,
    pmode: str,
    message: str,
    simple: bool,
    default_chat_behavior: str,
):
    """resolve the effective turn mode. returns (mode, force_approve).
    explicit Agent/Jarvis always runs tools. In chat, Answer only blocks all automatic
    promotion; otherwise a persona can prefer Agent or pure chat, and an unset persona
    falls back to intent detection. promoted mutations are gated behind approval."""
    if simple:
        return "chat", False
    if base_mode in {"agent", "jarvis"}:
        return "agent", False
    if base_mode != "chat":
        return "chat", False
    # Answer only is a conversation-level safety boundary. Persona defaults and
    # intent detection may suggest tools, but only an explicit Agent/Jarvis mode
    # may cross that boundary.
    if default_chat_behavior == "answer_only":
        return "chat", False
    if pmode == "agent":
        return "agent", True
    if pmode != "chat" and default_chat_behavior == "automatic_tools":
        from services.agent_intents import message_needs_tools

        if message_needs_tools(message):
            return "agent", True
    return "chat", False


def _resolve_working_dir(session: Session) -> str:
    from services.project_environment import session_environment

    return session_environment(session)["cwd"]


def _context_provenance(
    session: Session,
    settings: dict,
    persona: Persona | None,
    memory_ids: list[str],
    db,
    endpoint: ModelEndpoint,
    model: str,
) -> dict:
    rows = (
        db.query(Memory).filter(Memory.id.in_(memory_ids)).all()
        if memory_ids
        else []
    )
    by_id = {row.id: row for row in rows}
    memories = []
    for memory_id in memory_ids:
        row = by_id.get(memory_id)
        if not row:
            continue
        memories.append(
            {
                "id": row.id,
                "text": row.text[:160],
                "scope": row.scope or "global",
                "project_id": row.project_id or "",
            }
        )
    project = getattr(session, "project", None)
    return {
        "owner_instructions": bool(owner_instructions(settings)),
        "project_instructions": bool(project and project.system_prompt),
        "project_id": getattr(session, "project_id", "") or "",
        "persona": {"id": persona.id, "name": persona.name} if persona else None,
        "memories": memories,
        "model": model,
        "endpoint_id": endpoint.id,
        "endpoint": endpoint.name,
    }


def _resolve_mentions(text: str, cwd: str) -> str:
    """inline @path file references → append file contents for the model"""
    from pathlib import Path

    if not cwd:
        return text
    base = Path(cwd)
    blocks, seen = [], set()
    for m in re.finditer(r"(?:^|\s)@([\w./\\-]+)", text):
        rel = m.group(1).rstrip(".,;:")
        if rel in seen:
            continue
        seen.add(rel)
        try:
            p = (base / rel).resolve()
        except Exception:
            continue
        if p.is_file():
            try:
                content = p.read_text("utf-8", errors="replace")
                blocks.append(f'<file name="{rel}">\n{content[:20000]}\n</file>')
            except Exception:
                pass
    return text + "\n\n" + "\n\n".join(blocks) if blocks else text


def _is_video_upload(rec) -> bool:
    from services.video_frames import is_video

    return is_video(getattr(rec, "mime_type", "") or "", getattr(rec, "original_name", "") or "")


def _build_messages(
    session: Session,
    user_text: str,
    settings: dict,
    db=None,
    file_ids: list[str] = None,
    mem_ctx: str = None,
) -> list[dict]:
    contextual_instructions = ""

    # A Project supplies the contextual prompt unless a persona overrides it below.
    if db:
        proj = getattr(session, "project", None)
        if proj and proj.system_prompt:
            contextual_instructions = proj.system_prompt

    # override with persona system prompt if one is set
    if db:
        persona = _resolve_persona(session, db)
        if persona and persona.system_prompt:
            contextual_instructions = persona.system_prompt
        # 10d — let a persona answer from its attached knowledge files
        if persona:
            try:
                from services.persona_docs import knowledge_block

                kb = knowledge_block(db, persona.id, user_text)
                if kb:
                    contextual_instructions = (
                        contextual_instructions.rstrip()
                        + "\n\n### Knowledge (from attached files)\n"
                        + kb
                    )
            except Exception:
                pass

    # The code-owned base can never be replaced. A persona still replaces a Project prompt, as it
    # did before, while owner instructions remain a separate final editable layer.
    sys_prompt = build_aide_system_prompt(settings, contextual_instructions)

    memory_allowed = not settings.get("incognito") and settings.get("memory_policy", "ask") != "off"
    if memory_allowed and settings.get("memory_auto_inject", True):
        # mem_ctx may be pre-computed off the event loop by an async caller (the embed is
        # CPU-bound and used to freeze the whole server per chat turn); only embed inline
        # here as a fallback for sync callers.
        mc = mem_ctx if mem_ctx is not None else inject_memories(user_text)
        if mc:
            sys_prompt = sys_prompt.rstrip() + "\n\n" + mc

    # surface-brain - let aide weave in the cross-domain insights it found
    if db and memory_allowed and settings.get("insights_auto_inject", True):
        try:
            from services.insights import inject_active_insights

            ins_ctx = inject_active_insights(db)
            if ins_ctx:
                sys_prompt = sys_prompt.rstrip() + "\n\n" + ins_ctx
        except Exception:
            pass

    # surface-brain - feed the distilled user-model (what we learned about you) into the prompt
    if db and memory_allowed and settings.get("distilled_auto_inject", True):
        try:
            from services.user_model import inject_distilled

            dist_ctx = inject_distilled(db)
            if dist_ctx:
                sys_prompt = sys_prompt.rstrip() + "\n\n" + dist_ctx
        except Exception:
            pass

    # 1d - a compact per-session context (mode/topic/project) so aide stays coherent across turns
    if (
        not settings.get("incognito")
        and settings.get("session_context_inject", True)
        and db
        and session is not None
    ):
        try:
            from services.session_context import summarize as _session_summary

            sc_block = _session_summary(db, session)
            if sc_block:
                sys_prompt = sys_prompt.rstrip() + "\n\n" + sc_block
        except Exception:
            pass

    if settings.get("artifacts_enabled", True):
        sys_prompt = sys_prompt.rstrip() + "\n\n" + _ARTIFACT_INSTRUCTIONS

    msgs = [{"role": "system", "content": sys_prompt}]
    limit = settings.get("context_limit", 40)
    limit = max(
        1, int(limit) if isinstance(limit, (int, float)) else 40
    )  # 0/neg would dump all history
    if db is not None and not getattr(session, "incognito", False):
        # pull just the last `limit` rows in sql — loading the whole relationship dragged the
        # entire session history into memory on every turn
        history = (
            db.query(Message)
            .filter(Message.session_id == session.id)
            .order_by(Message.timestamp.desc())
            .limit(limit)
            .all()
        )[::-1]
    else:
        history = list(session.messages)[-limit:]
    for m in history:
        msgs.append({"role": m.role, "content": m.content})

    # handle file attachments
    user_content: list | str = user_text
    if file_ids and db:
        import base64

        from core.database import Upload
        from routes.uploads import upload_dir

        text_blocks = []
        image_parts = []
        for fid in file_ids:
            private = incognito_service.get_upload(fid)
            rec = db.get(Upload, fid) if not private else None
            if private:
                raw = private.content
                mime_type = private.mime_type
                original_name = private.name
                fpath = None
            elif rec:
                fpath = upload_dir() / rec.filename
                if not fpath.exists():
                    continue
                raw = fpath.read_bytes()
                mime_type = rec.mime_type
                original_name = rec.original_name
            else:
                continue
            if mime_type.startswith("image/"):
                b64 = base64.b64encode(raw).decode()
                image_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    }
                )
            elif rec and _is_video_upload(rec):
                # 10e — sample frames so a vision model can understand the clip
                from services.video_frames import extract_frames

                for url in extract_frames(str(fpath)):
                    image_parts.append({"type": "image_url", "image_url": {"url": url}})
            else:
                try:
                    text_blocks.append(
                        f'<file name="{original_name}">\n{raw.decode("utf-8", errors="replace")}\n</file>'
                    )
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


class ChatRequest(BaseModel):
    session_id: str
    message: str
    mode: str = "chat"  # chat | agent
    file_ids: list[str] = []
    incognito: bool = False
    permission_mode: str = ""  # full_auto | approve | plan
    effort: str = ""  # low | medium | high
    simple: bool = False  # pure chat — never auto-promote to tools (the home "ask aide")


async def _sse(gen):
    """wrap async generator into SSE — yield bytes so uvicorn flushes each chunk immediately"""
    async for chunk in gen:
        yield f"data: {json.dumps(chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


async def _stream_and_save(
    session_id: str,
    user_text: str,
    messages: list[dict],
    ep: ModelEndpoint,
    model: str,
    stop_event: asyncio.Event,
    db_factory,
    incognito: bool = False,
    mode: str = "chat",
    settings: dict | None = None,
    memory_ids: list[str] | None = None,
):
    accumulated = []
    thinking_acc = []
    tool_steps = []
    usage = {}
    agent_run_id = ""

    if mode == "agent":
        async for chunk in run_agent(
            messages,
            ep,
            model,
            stop_event,
            settings or {},
            accumulated,
            thinking_acc,
            tool_steps,
            session_id=session_id,
        ):
            run = chunk.get("agent_run")
            if isinstance(run, dict) and run.get("id"):
                agent_run_id = str(run["id"])
            if "usage" in chunk:
                usage = merge_usage(usage, chunk.get("usage", {}))
            yield chunk
    else:
        chat_kw = {}
        if settings and settings.get("temperature") is not None:
            chat_kw["temperature"] = settings["temperature"]
        if settings and settings.get("agent_effort"):
            chat_kw["effort"] = settings["agent_effort"]  # per-model reasoning effort
        async for chunk in stream_chat(messages, ep.base_url, ep.api_key, model, **chat_kw):
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

    if incognito:
        meta = {
            "usage": usage,
            "model": model,
            "context_provenance": (settings or {}).get("context_provenance", {}),
        }
        if thinking_acc:
            meta["thinking"] = "".join(thinking_acc)
        if tool_steps:
            meta["tool_steps"] = tool_steps
        if agent_run_id:
            meta["agent_run_id"] = agent_run_id
        incognito_service.append_turn(session_id, user_text, full_text, json.dumps(meta))
        return  # RAM only; never write an incognito turn to SQLite

    db = db_factory()
    try:
        s = db.get(Session, session_id)
        if not s:
            return

        # save user message if not already there (first time)
        # do this even if the model returned nothing, otherwise the just-sent
        # user turn vanishes on reload when a completion comes back empty/errored
        # most recent row only — loading s.messages dragged the whole history in just to dedup
        last = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.timestamp.desc())
            .first()
        )
        added = 0
        if not last or last.role != "user" or last.content != user_text:
            um = Message(session_id=session_id, role="user", content=user_text)
            db.add(um)
            added += 1

        if full_text:
            meta = {
                "usage": usage,
                "model": model,
                "context_provenance": (settings or {}).get("context_provenance", {}),
            }
            if memory_ids:
                meta["memory_ids"] = memory_ids
            if thinking_acc:
                meta["thinking"] = "".join(thinking_acc)
            if tool_steps:
                meta["tool_steps"] = tool_steps
            if agent_run_id:
                meta["agent_run_id"] = agent_run_id
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
            added += 1
            s.last_message_at = datetime.utcnow()

        # count every row we actually saved (user + assistant), not just one —
        # otherwise the sidebar count drifts a message behind every turn
        if added:
            s.message_count = (s.message_count or 0) + added

        db.commit()

        # (auto-naming is now driven by the frontend after the first reply so the
        #  sidebar updates immediately — see chat.js)

        # fire webhook
        if full_text:
            asyncio.create_task(_fire_message_hook(session_id, user_text, full_text))
    finally:
        db.close()


async def _fire_message_hook(session_id: str, user_text: str, reply: str):
    try:
        from routes.webhooks import fire

        await fire(
            "message", {"session_id": session_id, "user": user_text[:500], "reply": reply[:500]}
        )
    except Exception:
        pass


# POST /api/chat
@router.post("/chat")
async def chat(body: ChatRequest, db: DbSession = Depends(get_db)):
    private_session = incognito_service.get_session(body.session_id)
    s = private_session or db.get(Session, body.session_id)
    if not s:
        raise HTTPException(404, "session not found")
    if body.incognito and not private_session and not getattr(s, "incognito", False):
        raise ApiError(
            400,
            "incognito_session_required",
            "start an incognito session before sending a private message",
        )

    settings = load_settings()
    incognito_run = bool(getattr(s, "incognito", False))
    settings["incognito"] = incognito_run
    apply_memory_tool_policy(settings, incognito=incognito_run)
    for upload_id in body.file_ids:
        private_upload = incognito_service.get_upload(upload_id)
        if incognito_run and not private_upload:
            raise ApiError(
                400,
                "incognito_upload_required",
                "attach the file again inside incognito",
            )
        if not incognito_run and private_upload:
            raise ApiError(
                400,
                "incognito_upload_forbidden",
                "private attachments can only be used inside incognito",
            )
    ep, model = _resolve_session_model(s, db, settings)
    from services.project_environment import session_environment

    environment = session_environment(s)
    settings["agent_cwd"] = environment["cwd"]
    settings["agent_environment"] = environment["kind"]
    settings["agent_project_id"] = environment["project_id"] or ""
    _p = _resolve_persona(s, db)
    if _p and _p.temperature is not None:
        settings["temperature"] = _p.temperature
    if body.permission_mode:
        settings["agent_permission_mode"] = body.permission_mode
    if body.effort:
        settings["agent_effort"] = body.effort
    # @path mentions → inline file contents for the model (saved msg stays clean)
    aug_text = _resolve_mentions(body.message, settings["agent_cwd"])
    # embed memories OFF the event loop — fastembed is CPU-bound and would otherwise freeze
    # every other request (and SSE stream) for the duration of each chat turn
    memory_result = (
        await asyncio.to_thread(
            inject_memories,
            aug_text,
            project_id=getattr(s, "project_id", "") or "",
            run_id=s.id,
            return_details=True,
        )
        if not incognito_run
        and settings.get("memory_policy", "ask") != "off"
        and settings.get("memory_auto_inject", True)
        else ("", [])
    )
    mem_ctx, memory_ids = memory_result
    settings["context_provenance"] = _context_provenance(
        s,
        settings,
        _p,
        memory_ids,
        db,
        ep,
        model,
    )
    messages = _build_messages(s, aug_text, settings, db, body.file_ids, mem_ctx=mem_ctx)
    if incognito_run:
        for upload_id in body.file_ids:
            incognito_service.delete_upload(upload_id)

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

    is_incognito = incognito_run
    base_mode = body.mode or getattr(s, "mode", "chat") or "chat"
    pmode = (_p.default_mode if _p else "") or ""
    mode, force_approve = _decide_mode(
        base_mode,
        pmode,
        body.message,
        body.simple,
        getattr(s, "chat_behavior", "")
        or settings.get("default_chat_behavior", "automatic_tools"),
    )
    if force_approve and not body.permission_mode:
        settings["agent_permission_mode"] = "approve"
    gen = _stream_and_save(
        body.session_id,
        body.message,
        messages,
        ep,
        model,
        stop_event,
        _SF,
        incognito=is_incognito,
        mode=mode,
        settings=settings,
        memory_ids=memory_ids,
    )

    async def cleanup_gen():
        try:
            yield {"context_provenance": settings["context_provenance"]}
            async for chunk in gen:
                yield chunk
        finally:
            _streams.pop(body.session_id, None)

    return StreamingResponse(
        _sse(cleanup_gen()),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-store" if incognito_run else "no-cache",
            "x-accel-buffering": "no",
        },
    )


# background agent runs — detached, survive tab close
_bg_tasks: dict[str, asyncio.Task] = {}


@router.post("/agent/background")
async def chat_background(body: ChatRequest, db: DbSession = Depends(get_db)):
    s = incognito_service.get_session(body.session_id) or db.get(Session, body.session_id)
    if not s:
        raise HTTPException(404, "session not found")
    if getattr(s, "incognito", False) or body.incognito:
        from core.api_errors import ApiError

        raise ApiError(400, "incognito_background_forbidden", "incognito work stays in this tab")
    settings = load_settings()
    ep, model = _resolve_session_model(s, db, settings)
    from services.project_environment import session_environment

    environment = session_environment(s)
    settings["agent_cwd"] = environment["cwd"]
    settings["agent_environment"] = environment["kind"]
    settings["agent_project_id"] = environment["project_id"] or ""
    settings["agent_permission_mode"] = "full_auto"  # nothing is watching to approve
    _p = _resolve_persona(s, db)
    if _p and _p.temperature is not None:
        settings["temperature"] = _p.temperature
    aug_text = _resolve_mentions(body.message, settings["agent_cwd"])
    memory_result = (
        await asyncio.to_thread(
            inject_memories,
            aug_text,
            project_id=getattr(s, "project_id", "") or "",
            run_id=s.id,
            return_details=True,
        )
        if settings.get("memory_policy", "ask") != "off"
        and settings.get("memory_auto_inject", True)
        else ("", [])
    )
    mem_ctx, memory_ids = memory_result
    messages = _build_messages(s, aug_text, settings, db, body.file_ids, mem_ctx=mem_ctx)

    stop_event = asyncio.Event()
    _streams[body.session_id] = stop_event
    from core.database import SessionLocal as _SF

    async def runner():
        try:
            async for _ in _stream_and_save(
                body.session_id,
                body.message,
                messages,
                ep,
                model,
                stop_event,
                _SF,
                incognito=False,
                mode="agent",
                settings=settings,
                memory_ids=memory_ids,
            ):
                pass
            # ping Discord/Telegram when a long background run wraps up
            try:
                from services import notify

                if settings.get("notify_on_agent_done") and notify.configured():
                    await notify.send(f"✓ aide finished a background run: {body.message[:140]}")
            except Exception:
                pass
        finally:
            _streams.pop(body.session_id, None)
            _bg_tasks.pop(body.session_id, None)

    _bg_tasks[body.session_id] = asyncio.create_task(runner())
    return {"ok": True, "session_id": body.session_id}


# POST /api/chat/stop/{session_id}
@router.post("/chat/stop/{session_id}")
def stop_chat(session_id: str):
    ev = _streams.get(session_id)
    if ev:
        ev.set()
        return {"ok": True}
    return {"ok": False, "msg": "no active stream"}


_REWRITE_STYLES = {
    "shorter": "Rewrite the assistant reply below to be significantly shorter and tighter — keep every load-bearing point, cut filler. Same format.",
    "simpler": "Rewrite the assistant reply below in plainer, simpler language anyone can follow. Keep the meaning, drop jargon.",
    "formal": "Rewrite the assistant reply below in a more formal, professional tone. Keep the content.",
    "casual": "Rewrite the assistant reply below in a warmer, more casual tone. Keep the content.",
}


class RewriteBody(BaseModel):
    session_id: str
    style: str = "shorter"
    msg_id: str = ""  # which assistant message to rewrite; default = the last one


# POST /api/chat/rewrite — rewrite an assistant message in place (no agent loop)
@router.post("/chat/rewrite")
async def rewrite_last(body: RewriteBody, db: DbSession = Depends(get_db)):
    instr = _REWRITE_STYLES.get(body.style)
    if not instr:
        raise HTTPException(400, "unknown style")
    s = db.get(Session, body.session_id)
    if not s:
        raise HTTPException(404, "session not found")
    if body.msg_id:
        last = db.get(Message, body.msg_id)
        if not last or last.session_id != body.session_id or last.role != "assistant":
            raise HTTPException(404, "assistant message not found")
    else:
        last = (
            db.query(Message)
            .filter(Message.session_id == body.session_id, Message.role == "assistant")
            .order_by(Message.timestamp.desc())
            .first()
        )
    if not last or not last.content.strip():
        raise HTTPException(400, "no assistant reply to rewrite")

    ep, model = _resolve_session_model(s, db, load_settings())

    prompt = [
        {"role": "system", "content": instr + " Output ONLY the rewritten reply, nothing else."},
        {"role": "user", "content": last.content},
    ]
    out = (await simple_complete(prompt, ep.base_url, ep.api_key, model, max_tokens=2000)).strip()
    if not out:
        raise HTTPException(502, "rewrite produced nothing")
    last.content = out
    db.commit()
    return {"content": out, "msg_id": last.id}
