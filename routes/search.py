from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession
from sqlalchemy import or_
from core.database import get_db, Session, Message, Note, Memory

router = APIRouter(prefix="/api")

_LIMIT = 10


@router.get("/search")
def search(q: str = Query(""), scope: str = "all", db: DbSession = Depends(get_db)):
    if not q.strip():
        return {"chats": [], "notes": [], "memories": []}

    pat = f"%{q}%"
    results = {}

    if scope in ("all", "chats"):
        # search sessions by name + message content
        sessions_by_name = (
            db.query(Session)
            .filter(Session.archived == False, Session.name.ilike(pat))
            .limit(_LIMIT).all()
        )
        msgs = (
            db.query(Message)
            .filter(Message.content.ilike(pat))
            .limit(_LIMIT * 2).all()
        )
        seen = set(s.id for s in sessions_by_name)
        chat_results = [{"session_id": s.id, "session_name": s.name,
                         "snippet": s.name} for s in sessions_by_name]
        for m in msgs:
            if m.session_id not in seen:
                seen.add(m.session_id)
                s = db.get(Session, m.session_id)
                if s and not s.archived:
                    idx = m.content.lower().find(q.lower())
                    start = max(0, idx - 40)
                    snippet = m.content[start:start + 120].strip()
                    chat_results.append({
                        "session_id": s.id,
                        "session_name": s.name,
                        "snippet": snippet,
                    })
        results["chats"] = chat_results[:_LIMIT]

    if scope in ("all", "notes"):
        notes = (
            db.query(Note)
            .filter(Note.archived == False,
                    or_(Note.title.ilike(pat), Note.content.ilike(pat)))
            .limit(_LIMIT).all()
        )
        results["notes"] = [{"id": n.id, "title": n.title or "untitled",
                              "snippet": n.content[:100]} for n in notes]

    if scope in ("all", "memories"):
        from services.memory_store import search_memories
        mems = search_memories(q, top_k=_LIMIT)
        results["memories"] = mems

    return results
