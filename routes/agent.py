from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.agent_runtime import resolve_permission
from services.agent_state import find_active_run, get_run, list_runs
from services.agent_tools import agent_status, revert_run

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
    from core.database import Session as Sess
    from core.database import SessionLocal
    from services.agent_tools import workspace_files

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


_RUN_LITE = (
    "id",
    "session_id",
    "model",
    "cwd",
    "status",
    "turn",
    "max_turns",
    "started_at",
    "finished_at",
    "updated_at",
)


@router.get("/agent/runs")
def runs(limit: int = 20, summary: bool = False):
    rows = list_runs(limit=limit)
    if not summary:
        return rows
    # strip the heavy events/checkpoints for the drawer list; keep a few signals
    out = []
    for r in rows:
        lite = {k: r.get(k) for k in _RUN_LITE}
        lite["steps"] = len(r.get("tool_steps", []) or [])
        lite["edits"] = len(r.get("checkpoints", []) or [])
        todos = r.get("todos", []) or []
        lite["todo"] = next(
            (t.get("text") or t.get("title") for t in todos if isinstance(t, dict)), ""
        )
        lite["todos_total"] = len(todos)
        lite["todos_done"] = sum(
            1 for t in todos if isinstance(t, dict) and t.get("status") == "done"
        )
        out.append(lite)
    return out


# declared before /agent/runs/{run_id} so "active"/"incomplete" aren't captured as run_ids
@router.get("/agent/runs/active")
def active_run(session_id: str = ""):
    """the running agent run for a session (for reconnect/replay), or {} if none."""
    return find_active_run(session_id) or {}


@router.get("/agent/runs/incomplete")
def incomplete_runs(limit: int = 20):
    """runs that didn't finish cleanly (still running, or interrupted by a restart)."""
    from services.agent_state import list_incomplete

    return list_incomplete(limit)


# 3e - declared before /agent/runs/{run_id} so "analysis" isn't captured as a run_id
@router.get("/agent/runs/analysis")
def runs_analysis(limit: int = 50):
    """summaries + intent clusters over recent agent runs."""
    from services import run_analysis

    runs = run_analysis.load_runs(limit=limit)
    clusters = run_analysis.cluster_by_intent(runs)
    return {
        "summaries": [run_analysis.summarize(r) for r in runs],
        "clusters": [
            {"intent": k, "count": len(v), "runs": v} for k, v in sorted(clusters.items())
        ],
    }


@router.get("/agent/runs/{run_id}")
def run_detail(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(404, "agent run not found")
    return run


@router.get("/agent/runs/{run_id}/replay-plan")
def run_replay_plan(run_id: str, model: str = "", effort: str = ""):
    """3e - rebuild a past run's input to re-submit (optionally on a different model/effort)."""
    from services import run_analysis

    run = get_run(run_id)
    if not run:
        raise HTTPException(404, "agent run not found")
    return run_analysis.replay_plan(run, model=model or None, effort=effort or None)


@router.get("/agent/runs/{run_id}/events")
def run_events(run_id: str, since: int = 0):
    """durable tail of a run's events for reconnect — events after `since`, plus the
    accumulated prose + live status so a client that reloaded can resume showing progress (10b)."""
    run = get_run(run_id)
    if not run:
        raise HTTPException(404, "agent run not found")
    events = run.get("events", []) or []
    since = max(0, since)
    return {
        "events": events[since:],
        "next": len(events),
        "status": run.get("status"),
        "text": run.get("text", ""),
        "turn": run.get("turn", 0),
        "done": run.get("status") not in ("running",),
    }


@router.get("/agent/runs/{run_id}/sources")
def run_sources(run_id: str):
    """provenance for a run — files touched, urls fetched, searches, commands."""
    from services.agent_state import run_sources as _sources

    if not get_run(run_id):
        raise HTTPException(404, "agent run not found")
    return _sources(run_id)
