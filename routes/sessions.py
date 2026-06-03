import json, asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, Session, Message, ModelEndpoint


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
        "starred": s.starred,
        "message_count": s.message_count,
        "created_at": s.created_at.isoformat(),
        "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
    }


# GET /api/sessions
@router.get("/sessions")
def list_sessions(db: DbSession = Depends(get_db)):
    rows = (
        db.query(Session)
        .filter(Session.archived == False)
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


# POST /api/sessions
@router.post("/sessions")
async def create_session(body: CreateSession, bg: BackgroundTasks, db: DbSession = Depends(get_db)):
    s = Session(
        name=body.name,
        model=body.model,
        endpoint_id=body.endpoint_id or None,
        mode=body.mode,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    bg.add_task(_fire, "session_created", {"session_id": s.id, "name": s.name})
    return _fmt_session(s)


# GET /api/sessions/{id}/history
@router.get("/sessions/{session_id}/history")
def get_history(session_id: str, db: DbSession = Depends(get_db)):
    s = _session_or_404(session_id, db)
    msgs = []
    for m in s.messages:
        msgs.append({
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "meta": m.meta_dict(),
            "timestamp": m.timestamp.isoformat(),
        })
    return {"session": _fmt_session(s), "messages": msgs}


class PatchSession(BaseModel):
    name: str | None = None
    model: str | None = None
    endpoint_id: str | None = None
    mode: str | None = None
    starred: bool | None = None
    persona_id: str | None = None


# PATCH /api/sessions/{id}
@router.patch("/sessions/{session_id}")
async def patch_session(session_id: str, body: PatchSession, bg: BackgroundTasks, db: DbSession = Depends(get_db)):
    s = _session_or_404(session_id, db)
    renamed = body.name is not None and body.name != s.name
    if body.name is not None:       s.name = body.name
    if body.model is not None:      s.model = body.model
    if body.endpoint_id is not None: s.endpoint_id = body.endpoint_id or None
    if body.mode is not None:       s.mode = body.mode
    if body.starred is not None:    s.starred = body.starred
    if body.persona_id is not None: s.persona_id = body.persona_id or None
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
