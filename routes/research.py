import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db
from services.research import cancel_task, get_task, run_research

router = APIRouter(prefix="/api")


def _is_chat_model(mid: str) -> bool:
    from services.model_catalog import is_chat_model

    return is_chat_model(mid)


def _first_chat_model(ep) -> str:
    return next((m for m in (ep.models_list() or []) if _is_chat_model(m)), "")


def _resolve_ep():
    from core.database import SessionLocal
    from services.model_resolver import ModelResolutionError, resolve_model

    db = SessionLocal()
    try:
        try:
            selected = resolve_model(db, "andromeda")
        except ModelResolutionError:
            return None, None, None
        return selected.endpoint.base_url, selected.endpoint.api_key, selected.model
    finally:
        db.close()


def _resolve_ep_or_error():
    from core.api_errors import ApiError
    from core.database import SessionLocal
    from services.model_resolver import ModelResolutionError, resolve_model

    db = SessionLocal()
    try:
        try:
            selected = resolve_model(db, "andromeda")
        except ModelResolutionError as exc:
            raise ApiError(400, exc.code, str(exc)) from exc
        return selected.endpoint.base_url, selected.endpoint.api_key, selected.model
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
    base_url, api_key, model = _resolve_ep_or_error()

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
