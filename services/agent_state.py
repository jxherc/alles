"""
Persistent-ish agent run state.

Runs are stored as JSON files so active/recent agent work can be inspected even
outside the live SSE stream.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data" / "agent_runs"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_active: dict[str, dict] = {}


def _now() -> str:
    return datetime.utcnow().isoformat()


def _path(run_id: str) -> Path:
    return DATA_DIR / f"{run_id}.json"


def _save(state: dict):
    _path(state["id"]).write_text(json.dumps(state, indent=2), "utf-8")


def start_run(session_id: str, model: str, max_turns: int, cwd: str = "") -> dict:
    state = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "model": model,
        "cwd": cwd,
        "status": "running",
        "max_turns": max_turns,
        "turn": 0,
        "todos": [],
        "events": [],
        "tool_steps": [],
        "started_at": _now(),
        "updated_at": _now(),
        "finished_at": None,
    }
    _active[state["id"]] = state
    _save(state)
    return state


def record_event(run_id: str, event_type: str, data: dict | None = None):
    state = get_run(run_id)
    if not state:
        return
    event = {"time": _now(), "type": event_type, "data": data or {}}
    state.setdefault("events", []).append(event)
    state["events"] = state["events"][-300:]
    state["updated_at"] = event["time"]
    _active[state["id"]] = state
    _save(state)


def update_run(run_id: str, **patch):
    state = get_run(run_id)
    if not state:
        return
    state.update(patch)
    state["updated_at"] = _now()
    _active[state["id"]] = state
    _save(state)


def finish_run(run_id: str, status: str = "done"):
    state = get_run(run_id)
    if not state:
        return
    state["status"] = status
    state["finished_at"] = _now()
    state["updated_at"] = state["finished_at"]
    _active.pop(run_id, None)
    _save(state)


def get_run(run_id: str) -> dict | None:
    if run_id in _active:
        return _active[run_id]
    p = _path(run_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return None


def list_runs(limit: int = 20) -> list[dict]:
    rows = []
    for p in sorted(DATA_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            rows.append(json.loads(p.read_text("utf-8")))
        except Exception:
            continue
        if len(rows) >= limit:
            break
    return rows
