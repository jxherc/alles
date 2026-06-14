from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel

from services.agent_tools import agent_status, revert_run
from services.agent_state import list_runs, get_run, find_active_run
from services.agent_runtime import resolve_permission

router = APIRouter(prefix="/api")


class PermDecision(BaseModel):
    allow: bool


@router.post("/agent/permission/{request_id}")
def agent_permission(request_id: str, body: PermDecision):
    ok = resolve_permission(request_id, body.allow)
    return {"ok": ok}


@router.post("/agent/runs/{run_id}/revert")
def agent_revert(run_id: str):
    return revert_run(run_id)


@router.get("/agent/files")
def agent_files(q: str = "", session_id: str = "", limit: int = 30):
    """workspace files for @-mention autocomplete"""
    from services.agent_tools import workspace_files
    from core.database import SessionLocal, Session as Sess
    cwd = ""
    if session_id:
        db = SessionLocal()
        try:
            s = db.get(Sess, session_id)
            if s:
                cwd = getattr(s, "working_dir", "") or ""
                if not cwd:
                    proj = getattr(s, "project", None)
                    if proj:
                        cwd = getattr(proj, "working_dir", "") or ""
        finally:
            db.close()
    return {"files": workspace_files(cwd, q, limit)}


@router.get("/agent/status")
async def status():
    return await agent_status()


@router.get("/agent/runs")
def runs(limit: int = 20):
    return list_runs(limit=limit)


# declared before /agent/runs/{run_id} so "active" isn't captured as a run_id
@router.get("/agent/runs/active")
def active_run(session_id: str = ""):
    """the running agent run for a session (for reconnect/replay), or {} if none."""
    return find_active_run(session_id) or {}


@router.get("/agent/runs/{run_id}")
def run_detail(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(404, "agent run not found")
    return run
