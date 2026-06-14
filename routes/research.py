import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.research import run_research, get_task, cancel_task

router = APIRouter(prefix="/api")


def _resolve_ep():
    from core.database import SessionLocal, ModelEndpoint
    db = SessionLocal()
    try:
        ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
        if not ep:
            return None, None, None
        model = ep.models_list()[0] if ep.models_list() else ""
        return ep.base_url, ep.api_key, model
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
