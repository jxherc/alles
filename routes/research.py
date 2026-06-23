import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db
from services.research import cancel_task, get_task, run_research

router = APIRouter(prefix="/api")


def _is_chat_model(mid: str) -> bool:
    # embedding/rerank/audio models can't do research — skip them
    m = (mid or "").lower()
    return bool(m) and not any(
        b in m for b in ("embed", "rerank", "whisper", "tts", "moderation")
    )


def _first_chat_model(ep) -> str:
    return next((m for m in (ep.models_list() or []) if _is_chat_model(m)), "")


def _resolve_ep():
    from core.database import ModelEndpoint, SessionLocal
    from core.settings import load_settings

    db = SessionLocal()
    try:
        st = load_settings()
        # prefer the user's configured default endpoint+model
        dep_id = st.get("default_endpoint_id") or ""
        if dep_id:
            ep = db.get(ModelEndpoint, dep_id)
            if ep and ep.enabled:
                dmodel = st.get("default_model") or ""
                model = dmodel if _is_chat_model(dmodel) else _first_chat_model(ep)
                if model:
                    return ep.base_url, ep.api_key, model
        # fallback: first enabled endpoint that actually has a chat model
        for ep in db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all():  # noqa: E712
            model = _first_chat_model(ep)
            if model:
                return ep.base_url, ep.api_key, model
        return None, None, None
    finally:
        db.close()


class ResearchRequest(BaseModel):
    query: str
    session_id: str
    max_rounds: int = 8


async def _sse(gen):
    async for chunk in gen:
        yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


# POST /api/research  — starts research, streams progress
@router.post("/research")
async def start_research(body: ResearchRequest):
    base_url, api_key, model = _resolve_ep()
    if not base_url:
        raise HTTPException(400, "no endpoint configured")
    if not model:
        raise HTTPException(400, "no model available")

    gen = run_research(
        session_id=body.session_id,
        query=body.query,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_rounds=body.max_rounds,
    )
    return StreamingResponse(
        _sse(gen),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


# GET /api/research/{session_id}  — full task state
# 3g - declared before /research/{session_id} so "cache" isn't captured as a session id
@router.get("/research/cache")
def research_cache(q: str = "", db: DbSession = Depends(get_db)):
    """cache-first lookup over the cross-session research fact cache, + contradiction flags."""
    from services.research import fact_cache

    hits = fact_cache.cached(db, q) if q else []
    return {"findings": hits, "contradictions": fact_cache.contradictions(hits)}


@router.get("/research/{session_id}")
def get_research(session_id: str):
    t = get_task(session_id)
    if not t:
        raise HTTPException(404, "no research task found")
    return t


# GET /api/research/{session_id}/result  — just the report + sources + stats
@router.get("/research/{session_id}/result")
def get_research_result(session_id: str):
    t = get_task(session_id)
    if not t:
        raise HTTPException(404, "no research task found")
    return {
        "status": t.get("status"),
        "query": t.get("query"),
        "report": t.get("report", ""),
        "sources": t.get("sources", []),
        "stats": t.get("stats", {}),
    }


# POST /api/research/{session_id}/cancel
@router.post("/research/{session_id}/cancel")
def cancel_research(session_id: str):
    cancel_task(session_id)
    return {"ok": True}
