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
        "checkpoints": [],
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


def add_checkpoint(run_id: str, entry: dict):
    """record a file's pre-edit state so the run can be reverted"""
    state = get_run(run_id)
    if not state:
        return
    state.setdefault("checkpoints", []).append(entry)
    state["updated_at"] = _now()
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


def find_active_run(session_id: str) -> dict | None:
    """the run currently executing for a session, if any. lets a client that
    reconnected (tab reload, nav away and back) find the run to replay its
    event log and pick the live stream back up instead of losing the run."""
    if not session_id:
        return None
    for st in _active.values():
        if st.get("session_id") == session_id and st.get("status") == "running":
            return st
    # _active is memory-only — after a process restart a run can still be
    # marked running on disk; surface that too so it can be inspected/reverted.
    for st in list_runs(limit=40):
        if st.get("session_id") == session_id and st.get("status") == "running":
            return st
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


def reconcile_interrupted() -> int:
    """on boot, any run still 'running' on disk belongs to a process that's gone —
    mark it 'interrupted' so it's not a zombie and can be inspected/resumed.
    long agent runs that outlived a restart show up honestly instead of hanging."""
    n = 0
    for st in list_runs(limit=1000):
        if st.get("status") == "running" and st.get("id") not in _active:
            st["status"] = "interrupted"
            st["finished_at"] = st.get("finished_at") or _now()
            st["updated_at"] = _now()
            _save(st)
            n += 1
    return n


def list_incomplete(limit: int = 20) -> list[dict]:
    """runs that didn't finish cleanly — still running, or interrupted by a restart."""
    out = [st for st in list_runs(limit=300) if st.get("status") in ("running", "interrupted")]
    return out[:limit]


def run_sources(run_id: str) -> dict:
    """what a run actually drew on — the files it touched, urls it fetched, searches
    it ran, commands it executed. claude-code-style provenance so you can see where
    an answer came from instead of trusting it blind."""
    run = get_run(run_id)
    if not run:
        return {}
    files, urls, searches, commands = set(), set(), [], []
    for e in run.get("events", []):
        if e.get("type") != "tool_start":
            continue
        d = e.get("data", {})
        name, args = d.get("name", ""), d.get("args", {}) or {}
        if name in (
            "read_file",
            "write_file",
            "edit_file",
            "apply_patch",
            "revert_file",
        ) and args.get("path"):
            files.add(args["path"])
        elif name in ("web_fetch", "github_get_file") and (args.get("url") or args.get("path")):
            urls.add(args.get("url") or args.get("path"))
        elif name == "web_search" and args.get("query"):
            searches.append(args["query"])
        elif name == "shell" and args.get("command"):
            commands.append(args["command"])
    return {
        "files": sorted(files),
        "urls": sorted(urls),
        "searches": searches,
        "commands": commands,
    }
