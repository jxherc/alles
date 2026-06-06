from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel

from services.agent_tools import agent_status, revert_run
from services.agent_state import list_runs, get_run
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


@router.get("/agent/status")
async def status():
    return await agent_status()


@router.get("/agent/runs")
def runs(limit: int = 20):
    return list_runs(limit=limit)


@router.get("/agent/runs/{run_id}")
def run_detail(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(404, "agent run not found")
    return run
