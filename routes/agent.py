from fastapi import APIRouter
from fastapi import HTTPException

from services.agent_tools import agent_status
from services.agent_state import list_runs, get_run

router = APIRouter(prefix="/api")


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
