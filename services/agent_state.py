"""
Persistent-ish agent run state.

Runs are stored as JSON files so active/recent agent work can be inspected even
outside the live SSE stream.
"""

import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from core.settings import data_dir

DATA_DIR: Path | None = None

_active: dict[str, dict] = {}
_private: dict[str, dict] = {}
_disk_active_by_session: dict[str, dict] | None = None
_disk_active_dir: Path | None = None


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def run_dir() -> Path:
    d = DATA_DIR or data_dir() / "agent_runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(run_id: str) -> Path:
    return run_dir() / f"{run_id}.json"


def _clear_disk_active_cache():
    global _disk_active_by_session, _disk_active_dir
    _disk_active_by_session = None
    _disk_active_dir = None


def _save(state: dict):
    if state.get("incognito"):
        from services.incognito import get_session

        if get_session(state["session_id"], touch=False) is not None:
            _private[state["id"]] = state
        else:
            _private.pop(state["id"], None)
            _active.pop(state["id"], None)
        return
    _path(state["id"]).write_text(json.dumps(state, indent=2), "utf-8")
    _clear_disk_active_cache()


def _disk_active_runs() -> dict[str, dict]:
    global _disk_active_by_session, _disk_active_dir
    d = run_dir()
    if _disk_active_by_session is not None and _disk_active_dir == d:
        return _disk_active_by_session
    rows = {}
    for st in list_runs(limit=40):
        sid = st.get("session_id")
        if sid and not st.get("incognito") and st.get("status") == "running" and sid not in rows:
            rows[sid] = st
    _disk_active_by_session = rows
    _disk_active_dir = d
    return rows


def start_run(
    session_id: str, model: str, max_turns: int, cwd: str = "", *, incognito: bool = False
) -> dict:
    state = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "model": model,
        "cwd": cwd,
        "status": "running",
        "max_turns": max_turns,
        "turn": 0,
        "text": "",  # accumulated assistant prose, persisted each turn for reconnect (10b)
        "todos": [],
        "events": [],
        "tool_steps": [],
        "source_tracking": 1,
        "checkpoints": [],
        "started_at": _now(),
        "updated_at": _now(),
        "finished_at": None,
    }
    if incognito:
        state["incognito"] = True
    _active[state["id"]] = state
    _save(state)
    return state


def record_event(run_id: str, event_type: str, data: dict | None = None, **patch):
    """log an event. pass extra state fields as kwargs (e.g. tool_steps=...) to apply them
    in the SAME write instead of a separate update_run — one file rewrite per tool, not two."""
    state = get_run(run_id)
    if not state:
        return
    payload = deepcopy(data or {})
    if event_type in ("tool_start", "tool_result"):
        payload.setdefault("completed", event_type == "tool_result")
        steps = patch.get("tool_steps", state.setdefault("tool_steps", []))
        if payload.get("call_id"):
            step = next(
                (s for s in reversed(steps) if s.get("call_id") == payload["call_id"]), None
            )
            if step is None:
                steps.append(deepcopy(payload))
            else:
                step.update(payload)
    event = {"time": _now(), "type": event_type, "data": payload}
    state.setdefault("events", []).append(event)
    state["events"] = state["events"][-300:]
    if patch:
        state.update(patch)
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
    state = _private.get(run_id)
    if state is not None:
        from services.incognito import get_session

        if get_session(state["session_id"], touch=False) is None:
            forget_private_session(state["session_id"])
            return None
        return state
    state = _active.get(run_id)
    if state is not None:
        return state
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
    _purge_private()
    for st in list(_active.values()):
        if st.get("session_id") == session_id and st.get("status") == "running":
            return st
    return _disk_active_runs().get(session_id)


def list_runs(limit: int = 20) -> list[dict]:
    _purge_private()
    rows = list(_private.values())
    public_count = 0
    for p in sorted(run_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            rows.append(json.loads(p.read_text("utf-8")))
            public_count += 1
        except Exception:
            continue
        if public_count >= limit:
            break
    rows.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    return rows[:limit]


def forget_private_session(session_id: str) -> None:
    """Drop run details with their RAM-only conversation; never remove owner files."""
    for run_id, state in list(_private.items()):
        if state.get("session_id") == session_id:
            _private.pop(run_id, None)
            _active.pop(run_id, None)


def _purge_private() -> None:
    # Reading the global run list must not keep a private conversation alive forever.
    from services.incognito import get_session

    for state in list(_private.values()):
        if get_session(state["session_id"], touch=False) is None:
            forget_private_session(state["session_id"])


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
    """Project confirmed tool outcomes; attempted reads are never source evidence."""
    run = get_run(run_id)
    if not run:
        return {}
    from services.agent_tools import TOOL_PERMISSION

    steps = deepcopy(run.get("tool_steps", []))
    by_id = {step.get("call_id"): step for step in steps if step.get("call_id")}
    for event in run.get("events", []):
        if event.get("type") not in ("tool_start", "tool_result"):
            continue
        data = deepcopy(event.get("data") or {})
        existing = by_id.get(data.get("call_id"))
        if existing is not None and "completed" in existing:
            continue
        if event["type"] == "tool_result":
            # Older stopped streams could emit a success-shaped partial result.
            if (
                run.get("source_tracking")
                or run.get("status") in ("done", "turn_limit")
                or data.get("error") is True
            ):
                data.setdefault("completed", True)
        if existing is not None:
            existing.update(data)
        else:
            steps.append(data)
            if data.get("call_id"):
                by_id[data["call_id"]] = data

    files, urls, searches, commands = set(), set(), [], []
    sources, actions = [], []
    outcomes = dict(succeeded=0, failed=0, unfinished=0, unknown=0)
    for step in steps:
        completed = step.get("completed")
        if completed is not True:
            outcomes["unfinished" if completed is False else "unknown"] += 1
            continue
        if step.get("error") is not False:
            outcomes["failed" if step.get("error") is True else "unknown"] += 1
            continue
        outcomes["succeeded"] += 1
        name, args = step.get("name", ""), step.get("args") or {}
        source = step.get("source")
        source = dict(source) if isinstance(source, dict) else None
        if not source and name in ("docs_read", "note_read"):
            try:
                snapshot = json.loads(step.get("output", ""))
                if isinstance(snapshot, dict) and snapshot.get("path") and snapshot.get("hash"):
                    source = {
                        "kind": "document",
                        "path": snapshot["path"],
                        "hash": snapshot["hash"],
                    }
            except (ValueError, TypeError):
                pass
        if not source and name == "read_file" and args.get("path"):
            source = {"kind": "file", "path": args["path"]}
        if not source and name == "web_fetch" and args.get("url"):
            source = {"kind": "url", "url": args["url"]}
        if not source and name in (
            "web_search",
            "memory_search",
            "note_search",
            "docs_search",
            "recall",
        ):
            source = {"kind": "search", "query": args.get("query", ""), "results": []}
        permission = TOOL_PERMISSION.get(name, "")
        if not source and (permission == "read" or permission.endswith("_read")):
            source = {"kind": "tool"}
        if source:
            source["tool"] = name
            if source not in sources:
                sources.append(source)
            if source.get("kind") in ("file", "document") and source.get("path"):
                files.add(source["path"])
            if source.get("kind") == "url" and source.get("url"):
                urls.add(source["url"])
        else:
            action = {"tool": name}
            for key in ("path", "command"):
                if isinstance(args.get(key), str):
                    action[key] = args[key]
            actions.append(action)
        if name in ("write_file", "edit_file", "apply_patch", "revert_file") and args.get("path"):
            files.add(args["path"])
        if name == "github_get_file" and (args.get("url") or args.get("path")):
            urls.add(args.get("url") or args["path"])
        if name == "web_search" and args.get("query"):
            searches.append(args["query"])
        if name in ("shell", "bash") and args.get("command"):
            commands.append(args["command"])
    return {
        "files": sorted(files),
        "urls": sorted(urls),
        "searches": searches,
        "commands": commands,
        "sources": sources,
        "actions": actions,
        "outcomes": outcomes,
        "history_complete": run.get("source_tracking") == 1 and not outcomes["unknown"],
    }
