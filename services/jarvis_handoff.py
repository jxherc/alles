"""One-off Aide-to-Jarvis handoffs backed by durable Phase 2 run records."""

import asyncio
import json
import logging

from core.database import JarvisRun, JarvisRunEvent, JarvisWorkflow, Session, SessionLocal
from core.settings import load_settings
from services.jarvis_store import append_event, create_run, json_text, transition_run
from services.memory_store import apply_memory_tool_policy, inject_memories
from services.model_resolver import ModelResolutionError, resolve_model

log = logging.getLogger("alles.jarvis.handoff")

HANDOFF_ACTION = "aide_handoff"
_tasks: dict[str, asyncio.Task] = {}
_stops: dict[str, asyncio.Event] = {}


def model_preview(db, *, endpoint_override: str = "", model_override: str = "") -> dict:
    choice = {"model": str(model_override or "").strip()} if model_override else {}
    if endpoint_override and model_override:
        choice["endpoint_id"] = str(endpoint_override).strip()
    selection = resolve_model(db, "jarvis", workflow_override=choice)
    return selection.public()


def create_handoff(
    db,
    session: Session,
    request: str,
    *,
    endpoint_override: str = "",
    model_override: str = "",
    file_ids: list[str] | None = None,
) -> JarvisRun:
    request = " ".join(str(request or "").split())
    if not request:
        raise ValueError("handoff_request_required")
    if getattr(session, "incognito", False):
        raise ValueError("incognito_handoff_forbidden")
    files = [str(value) for value in (file_ids or []) if str(value).strip()][:20]
    workflow = JarvisWorkflow(
        name=request[:80],
        purpose="one-off work handed to Jarvis from Aide",
        project_id=session.project_id,
        prompt=request,
        deterministic_action=HANDOFF_ACTION,
        model_override=str(model_override or "")[:300],
        capability_ceiling=json_text(["read", "search"], expected=list),
        concurrency_mode="one",
        context_mode="project" if session.project_id else "continue",
        enabled=False,
        review_state="ready",
    )
    db.add(workflow)
    db.flush()
    run = create_run(db, workflow, session_id=session.id)
    workflow.active_run_id = run.id
    append_event(
        db,
        run,
        "handoff_requested",
        source="aide",
        summary="request handed to Jarvis",
        data={"file_ids": files, "endpoint_override": str(endpoint_override or "")[:100]},
    )
    return run


def _handoff_input(db, run: JarvisRun) -> tuple[str, list[str], str]:
    workflow = db.get(JarvisWorkflow, run.workflow_id) if run.workflow_id else None
    if not workflow or workflow.deterministic_action != HANDOFF_ACTION:
        raise ValueError("not_aide_handoff")
    event = (
        db.query(JarvisRunEvent)
        .filter_by(run_id=run.id, kind="handoff_requested")
        .order_by(JarvisRunEvent.sequence)
        .first()
    )
    try:
        data = json.loads(event.data or "{}") if event else {}
    except (TypeError, ValueError):
        data = {}
    files = data.get("file_ids") if isinstance(data, dict) else []
    files = [str(value) for value in files] if isinstance(files, list) else []
    endpoint_override = str(data.get("endpoint_override") or "") if isinstance(data, dict) else ""
    return workflow.prompt or "", files[:20], endpoint_override[:100]


def retry_handoff(db, previous: JarvisRun) -> JarvisRun:
    if previous.state not in {"failed", "cancelled", "interrupted"}:
        raise ValueError("handoff_not_retryable")
    workflow = db.get(JarvisWorkflow, previous.workflow_id) if previous.workflow_id else None
    if not workflow or workflow.deterministic_action != HANDOFF_ACTION:
        raise ValueError("not_aide_handoff")
    request, files, endpoint_override = _handoff_input(db, previous)
    run = create_run(db, workflow, session_id=previous.session_id)
    workflow.active_run_id = run.id
    append_event(
        db,
        run,
        "handoff_requested",
        source="aide",
        summary="Jarvis retry requested",
        data={
            "file_ids": files,
            "endpoint_override": endpoint_override,
            "previous_run_id": previous.id,
        },
    )
    return run


def request_cancel(run_id: str) -> bool:
    event = _stops.get(run_id)
    if not event:
        return False
    event.set()
    return True


def launch(run_id: str) -> bool:
    current = _tasks.get(run_id)
    if current and not current.done():
        return False
    task = asyncio.create_task(_execute(run_id), name=f"jarvis-handoff-{run_id}")
    _tasks[run_id] = task
    return True


def resume_queued() -> int:
    db = SessionLocal()
    try:
        rows = (
            db.query(JarvisRun)
            .join(JarvisWorkflow, JarvisWorkflow.id == JarvisRun.workflow_id)
            .filter(
                JarvisRun.state == "queued",
                JarvisWorkflow.deterministic_action == HANDOFF_ACTION,
            )
            .all()
        )
        return sum(1 for row in rows if launch(row.id))
    finally:
        db.close()


def _record(run_id: str, kind: str, *, tool_name: str = "", summary: str = "") -> None:
    db = SessionLocal()
    try:
        run = db.get(JarvisRun, run_id)
        if run:
            append_event(
                db,
                run,
                kind,
                source="jarvis",
                tool_name=str(tool_name or "")[:128],
                summary=str(summary or "")[:2000],
            )
            db.commit()
    finally:
        db.close()


def _finish(run_id: str, state: str, *, result: str = "", error: str = "") -> None:
    db = SessionLocal()
    try:
        run = db.get(JarvisRun, run_id)
        if run and run.state == "running":
            transition_run(
                db,
                run,
                state,
                failure_class="model_or_tool" if state == "failed" else "",
                safe_error=str(error or "")[:2000],
                result_summary=str(result or "")[:4000],
            )
            workflow = db.get(JarvisWorkflow, run.workflow_id) if run.workflow_id else None
            if workflow and workflow.active_run_id == run.id:
                workflow.active_run_id = None
            db.commit()
    finally:
        db.close()


async def _execute(run_id: str) -> None:
    stop = asyncio.Event()
    _stops[run_id] = stop
    db = SessionLocal()
    try:
        run = db.get(JarvisRun, run_id)
        if not run or run.state != "queued":
            return
        workflow = db.get(JarvisWorkflow, run.workflow_id) if run.workflow_id else None
        session = db.get(Session, run.session_id) if run.session_id else None
        if not workflow or workflow.deterministic_action != HANDOFF_ACTION or not session:
            transition_run(
                db,
                run,
                "failed",
                failure_class="missing_context",
                safe_error="the original Aide conversation is unavailable",
            )
            db.commit()
            return
        request, file_ids, endpoint_override = _handoff_input(db, run)
        transition_run(db, run, "running")
        run.attempt_count = (run.attempt_count or 0) + 1
        db.commit()

        settings = load_settings()
        apply_memory_tool_policy(settings)
        model_choice = {"model": workflow.model_override} if workflow.model_override else {}
        if endpoint_override and workflow.model_override:
            model_choice["endpoint_id"] = endpoint_override
        selection = resolve_model(
            db,
            "jarvis",
            workflow_override=model_choice,
            settings=settings,
        )
        from services.project_environment import session_environment

        environment = session_environment(session)
        settings["agent_cwd"] = environment["cwd"]
        settings["agent_environment"] = environment["kind"]
        settings["agent_project_id"] = environment["project_id"] or ""
        # Phase 4 handoffs can read and research. Phase 5 adds durable mutation approvals.
        settings["agent_permission_mode"] = "plan"
        settings["agent_effort"] = "medium"
        memory_result = (
            await asyncio.to_thread(
                inject_memories,
                request,
                project_id=session.project_id or "",
                run_id=run.id,
                return_details=True,
            )
            if settings.get("memory_policy", "ask") != "off"
            else ("", [])
        )
        mem_ctx, memory_ids = memory_result
        from routes.chat import (
            _build_messages,
            _context_provenance,
            _resolve_persona,
            _stream_and_save,
        )

        settings["context_provenance"] = _context_provenance(
            session,
            settings,
            _resolve_persona(session, db),
            memory_ids,
            db,
            selection.endpoint,
            selection.model,
        )

        messages = _build_messages(
            session,
            request,
            settings,
            db,
            file_ids,
            mem_ctx=mem_ctx,
        )
        db.close()
        db = None

        answer = []
        async for chunk in _stream_and_save(
            session.id,
            request,
            messages,
            selection.endpoint,
            selection.model,
            stop,
            SessionLocal,
            incognito=False,
            mode="agent",
            settings=settings,
            memory_ids=memory_ids,
        ):
            if chunk.get("delta"):
                answer.append(chunk["delta"])
            if chunk.get("tool_start"):
                tool = chunk["tool_start"]
                _record(
                    run_id, "tool_started", tool_name=tool.get("name", ""), summary="tool started"
                )
            if chunk.get("tool_result"):
                tool = chunk["tool_result"]
                _record(
                    run_id,
                    "tool_finished",
                    tool_name=tool.get("name", ""),
                    summary="tool failed" if tool.get("error") else "tool finished",
                )
        if stop.is_set():
            _finish(run_id, "cancelled", result="".join(answer))
        else:
            _finish(run_id, "succeeded", result="".join(answer))
    except asyncio.CancelledError:
        raise
    except ModelResolutionError as exc:
        _finish(run_id, "failed", error=str(exc))
    except Exception as exc:
        log.warning("Jarvis handoff failed: %s", type(exc).__name__)
        _finish(run_id, "failed", error="Jarvis could not finish this run")
    finally:
        if db is not None:
            db.close()
        _stops.pop(run_id, None)
        _tasks.pop(run_id, None)
