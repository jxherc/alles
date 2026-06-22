import html as _html
import json as _json
import re as _re
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Message, ModelEndpoint, Session, get_db


async def _fire(event: str, data: dict):
    try:
        from routes.webhooks import fire

        await fire(event, data)
    except Exception:
        pass


router = APIRouter(prefix="/api")


def _session_or_404(session_id: str, db: DbSession):
    s = db.get(Session, session_id)
    if not s or s.archived:
        raise HTTPException(404, "session not found")
    return s


def _fmt_session(s: Session) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "model": s.model,
        "endpoint_id": s.endpoint_id,
        "mode": s.mode,
        "persona_id": s.persona_id,
        "project_id": getattr(s, "project_id", None),
        "working_dir": getattr(s, "working_dir", "") or "",
        "starred": s.starred,
        "incognito": bool(getattr(s, "incognito", False)),
        "message_count": s.message_count,
        "created_at": s.created_at.isoformat(),
        "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
    }


# GET /api/sessions
@router.get("/sessions")
def list_sessions(db: DbSession = Depends(get_db)):
    # incognito sessions never show in the sidebar — no trace
    rows = (
        db.query(Session)
        .filter(Session.archived == False, Session.incognito == False)
        .order_by(Session.last_message_at.desc())
        .all()
    )
    now = datetime.utcnow()
    today = now.date()
    yesterday = (now - timedelta(days=1)).date()

    result = {"today": [], "yesterday": [], "earlier": []}
    for s in rows:
        ts = (s.last_message_at or s.created_at).date()
        if ts == today:
            result["today"].append(_fmt_session(s))
        elif ts == yesterday:
            result["yesterday"].append(_fmt_session(s))
        else:
            result["earlier"].append(_fmt_session(s))
    return result


class CreateSession(BaseModel):
    model: str = ""
    endpoint_id: str = ""
    name: str = "new chat"
    mode: str = "chat"
    incognito: bool = False
    working_dir: str = ""
    persona_id: str = ""
    project_id: str = ""


# POST /api/sessions
@router.post("/sessions")
async def create_session(body: CreateSession, bg: BackgroundTasks, db: DbSession = Depends(get_db)):
    s = Session(
        name=body.name,
        model=body.model,
        endpoint_id=body.endpoint_id or None,
        mode=body.mode,
        incognito=body.incognito,
        working_dir=body.working_dir,
        persona_id=body.persona_id or None,
        project_id=body.project_id or None,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    if not body.incognito:
        bg.add_task(_fire, "session_created", {"session_id": s.id, "name": s.name})
    return _fmt_session(s)


# GET /api/sessions/{id}/history
@router.get("/sessions/{session_id}/history")
def get_history(session_id: str, db: DbSession = Depends(get_db)):
    s = _session_or_404(session_id, db)
    msgs = []
    for m in s.messages:
        msgs.append(
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "meta": m.meta_dict(),
                "timestamp": m.timestamp.isoformat(),
            }
        )
    return {"session": _fmt_session(s), "messages": msgs}


class PatchSession(BaseModel):
    name: str | None = None
    model: str | None = None
    endpoint_id: str | None = None
    mode: str | None = None
    starred: bool | None = None
    persona_id: str | None = None
    working_dir: str | None = None


# PATCH /api/sessions/{id}
@router.patch("/sessions/{session_id}")
async def patch_session(
    session_id: str, body: PatchSession, bg: BackgroundTasks, db: DbSession = Depends(get_db)
):
    s = _session_or_404(session_id, db)
    renamed = body.name is not None and body.name != s.name
    if body.name is not None:
        s.name = body.name
    if body.model is not None:
        s.model = body.model
    if body.endpoint_id is not None:
        s.endpoint_id = body.endpoint_id or None
    if body.mode is not None:
        s.mode = body.mode
    if body.starred is not None:
        s.starred = body.starred
    if body.persona_id is not None:
        s.persona_id = body.persona_id or None
    if body.working_dir is not None:
        s.working_dir = body.working_dir
    db.commit()
    if renamed:
        bg.add_task(_fire, "session_renamed", {"session_id": s.id, "name": s.name})
    return _fmt_session(s)


# POST /api/sessions/{id}/archive
@router.post("/sessions/{session_id}/archive")
def archive_session(session_id: str, db: DbSession = Depends(get_db)):
    s = db.get(Session, session_id)
    if not s:
        raise HTTPException(404)
    s.archived = True
    db.commit()
    return {"ok": True}


# DELETE /api/sessions/{id}
@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: DbSession = Depends(get_db)):
    s = db.get(Session, session_id)
    if not s:
        raise HTTPException(404)
    if s.starred:
        raise HTTPException(400, "unstar before deleting")
    db.delete(s)
    db.commit()
    return {"ok": True}


class EditMessage(BaseModel):
    content: str


# POST /api/sessions/{id}/messages/{msg_id}/edit
@router.post("/sessions/{session_id}/messages/{msg_id}/edit")
def edit_message(session_id: str, msg_id: str, body: EditMessage, db: DbSession = Depends(get_db)):
    msg = db.get(Message, msg_id)
    if not msg or msg.session_id != session_id:
        raise HTTPException(404)
    msg.content = body.content
    # hard-delete everything after this message
    later = (
        db.query(Message)
        .filter(Message.session_id == session_id, Message.timestamp > msg.timestamp)
        .all()
    )
    for m in later:
        db.delete(m)
    s = db.get(Session, session_id)
    if s:
        s.message_count = max(0, (s.message_count or 0) - len(later))
    db.commit()
    return {"ok": True}


class ForkBody(BaseModel):
    msg_id: str


# POST /api/sessions/{id}/fork — non-destructive branch from a message
@router.post("/sessions/{session_id}/fork")
def fork_session(session_id: str, body: ForkBody, db: DbSession = Depends(get_db)):
    """copy this session's messages up to AND INCLUDING msg_id into a brand-new
    session (original left untouched), so you can explore an alternate path from
    any point. inherits model/endpoint/mode/persona/project."""
    s = _session_or_404(session_id, db)
    target = db.get(Message, body.msg_id)
    if not target or target.session_id != session_id:
        raise HTTPException(404, "message not found in this session")
    new = Session(
        name=f"{s.name} (branch)",
        model=s.model,
        endpoint_id=s.endpoint_id,
        mode=s.mode,
        persona_id=s.persona_id,
        project_id=getattr(s, "project_id", None),
        working_dir=getattr(s, "working_dir", "") or "",
    )
    db.add(new)
    db.flush()
    n = 0
    for m in s.messages:  # relationship is timestamp-ordered — same order the user sees
        db.add(Message(session_id=new.id, role=m.role, content=m.content, meta=m.meta))
        n += 1
        if m.id == body.msg_id:
            break  # stop after copying the chosen message
    new.message_count = n
    db.commit()
    db.refresh(new)
    return _fmt_session(new)


_TITLE_STRIP = _re.compile(
    r"^(how (do|can|to)\s+i\s+|how (do|to)\s+|what('?s| is| are)\s+|whats\s+|can you\s+|could you\s+|"
    r"please\s+|help me( with)?\s+|i (want|need|would like) to\s+|tell me about\s+|explain\s+|"
    r"write( me)?\s+|make( me)?\s+|create\s+|build\s+|fix\s+|give me\s+)",
    _re.I,
)


def _heuristic_title(text: str) -> str:
    t = " ".join((text or "").split())
    t = _TITLE_STRIP.sub("", t)
    words = t.split()[:6]
    title = " ".join(words).strip(" ?.!,:;\"'")[:48]
    return (title or " ".join((text or "").split())[:48] or "new chat").lower()


async def _generate_title(first_user: str, ep, model: str) -> str:
    """LLM title with room for reasoning models, heuristic fallback. never fails."""
    if ep and model:
        try:
            from services.llm import simple_complete

            prompt = [
                {
                    "role": "system",
                    "content": "Respond with ONLY a 3-6 word lowercase title for the chat. No quotes, no punctuation, no preamble.",
                },
                {"role": "user", "content": f"Chat is about: {first_user[:400]}"},
            ]
            # generous max_tokens: reasoning models burn the budget thinking before answering
            name = (
                (await simple_complete(prompt, ep.base_url, ep.api_key, model, max_tokens=400))
                .strip()
                .strip("\"'")
                .strip()
            )
            name = (
                name.splitlines()[-1].strip() if name else ""
            )  # take last line in case of stray output
            if name and len(name) <= 60:
                return name.lower()
        except Exception:
            pass
    return _heuristic_title(first_user)


# POST /api/sessions/{id}/auto-name — name a session from its first message
@router.post("/sessions/{session_id}/auto-name")
async def auto_name_session(session_id: str, db: DbSession = Depends(get_db)):
    s = _session_or_404(session_id, db)
    if not s.messages:
        raise HTTPException(400, "no messages to name from")
    ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    model = s.model or (ep.models_list()[0] if ep and ep.models_list() else "")
    first_user = next((m.content for m in s.messages if m.role == "user"), "")
    s.name = await _generate_title(first_user, ep, model)
    db.commit()
    return {"name": s.name}


_EXPORT_MIME = {
    "md": "text/markdown",
    "json": "application/json",
    "txt": "text/plain",
    "html": "text/html",
}


def _render_export(s: Session, msgs: list, fmt: str) -> str:
    name = s.name or "chat"
    if fmt == "json":
        return _json.dumps(
            {
                "name": s.name,
                "model": s.model,
                "created_at": s.created_at.isoformat(),
                "messages": [
                    {"role": m.role, "content": m.content, "timestamp": m.timestamp.isoformat()}
                    for m in msgs
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    if fmt == "txt":
        return f"{name}\n\n" + "\n\n".join(f"{m.role.upper()}:\n{m.content}" for m in msgs)
    if fmt == "html":
        rows = "\n".join(
            f'<div class="m {_html.escape(m.role)}"><div class="r">{_html.escape(m.role)}</div>'
            f'<div class="c">{_html.escape(m.content)}</div></div>'
            for m in msgs
        )
        return (
            "<!doctype html><meta charset=utf-8>"
            f"<title>{_html.escape(name)}</title>"
            "<style>body{max-width:760px;margin:2rem auto;padding:0 1rem;"
            "font:15px/1.6 -apple-system,Segoe UI,sans-serif;color:#1a1a1a}"
            "h1{font-size:1.4rem}.m{margin:1.2rem 0;padding:.2rem 0 1.2rem;border-bottom:1px solid #eee}"
            ".r{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:#888;margin-bottom:.3rem}"
            ".c{white-space:pre-wrap}.m.user .c{color:#333}</style>"
            f"<h1>{_html.escape(name)}</h1>{rows}"
        )
    # default: markdown
    return f"# {name}\n\n" + "\n\n---\n\n".join(f"**{m.role}:**\n\n{m.content}" for m in msgs)


# GET /api/sessions/{id}/export?fmt=md|json|txt|html
@router.get("/sessions/{session_id}/export")
def export_session(session_id: str, fmt: str = "md", db: DbSession = Depends(get_db)):
    s = _session_or_404(session_id, db)
    if fmt not in _EXPORT_MIME:
        raise HTTPException(400, "unsupported format")
    text = _render_export(s, list(s.messages), fmt)
    safe = _re.sub(r"[^a-z0-9]+", "-", (s.name or "chat").lower()).strip("-") or "chat"
    return Response(
        content=text,
        media_type=_EXPORT_MIME[fmt],
        headers={"content-disposition": f'attachment; filename="{safe}.{fmt}"'},
    )


# GET /api/sessions/archived
@router.get("/sessions/archived")
def list_archived(db: DbSession = Depends(get_db)):
    rows = (
        db.query(Session)
        .filter(Session.archived == True)
        .order_by(Session.last_message_at.desc())
        .all()
    )
    return [_fmt_session(s) for s in rows]
