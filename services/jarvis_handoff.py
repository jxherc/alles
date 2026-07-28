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
_stream_text: dict[str, str] = {}
_PERMISSION_MODES = {"full_access", "full_auto", "approve", "plan"}
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max", "deep_work", "custom"}
_REASONING_MODES = {"automatic", "on", "off"}


def _custom_turn_limit(custom: dict) -> int:
    value = custom.get("maxTurns", custom.get("max_turns", 24))
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("custom_max_turns_invalid")
    if not 1 <= value <= 64:
        raise ValueError("custom_max_turns_invalid")
    return value


def model_preview(db, *, endpoint_override: str = "", model_override: str = "") -> dict:
    choice = {"model": str(model_override or "").strip()} if model_override else {}
    if endpoint_override and model_override:
        choice["endpoint_id"] = str(endpoint_override).strip()
    selection = resolve_model(db, "aide_chat", workflow_override=choice)
    return selection.public()


def create_handoff(
    db,
    session: Session,
    request: str,
    *,
    endpoint_override: str = "",
    model_override: str = "",
    file_ids: list[str] | None = None,
    permission_mode: str = "approve",
    effort: str = "medium",
    reasoning_mode: str = "automatic",
    custom_effort: dict | None = None,
    origin: dict | None = None,
) -> JarvisRun:
    from services.project_environment import session_environment

    request = str(request or "").strip()
    if not request:
        raise ValueError("handoff_request_required")
    if getattr(session, "incognito", False):
        raise ValueError("incognito_handoff_forbidden")
    files = [str(value) for value in (file_ids or []) if str(value).strip()][:20]
    permission_mode = permission_mode if permission_mode in _PERMISSION_MODES else "approve"
    effort = effort if effort in _EFFORT_LEVELS else "medium"
    reasoning_mode = reasoning_mode if reasoning_mode in _REASONING_MODES else "automatic"
    custom = custom_effort if isinstance(custom_effort, dict) else {}
    custom = {
        "max_turns": _custom_turn_limit(custom),
        "verification": custom.get("verification")
        if custom.get("verification") in {"quick", "standard", "thorough"}
        else "standard",
        "delegation": custom.get("delegation")
        if custom.get("delegation") in {"off", "auto"}
        else "off",
        "workflows": custom.get("workflows")
        if custom.get("workflows") in {"off", "auto"}
        else "off",
    }
    workflow = JarvisWorkflow(
        name=" ".join(request.split())[:80],
        purpose="one-off work Aide is continuing in the background",
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
    environment = session_environment(session)
    append_event(
        db,
        run,
        "handoff_requested",
        source="aide",
        summary="background work requested",
        data={
            "file_ids": files,
            "endpoint_override": str(endpoint_override or "")[:100],
            "permission_mode": permission_mode,
            "effort": effort,
            "reasoning_mode": reasoning_mode,
            "custom_effort": custom,
            "origin_kind": str((origin or {}).get("kind") or "")[:40],
            "origin_connector_id": str((origin or {}).get("connector_id") or "")[:100],
            "origin_generation": str((origin or {}).get("generation") or "")[:64],
            "origin_channel_id": str((origin or {}).get("channel_id") or "")[:100],
            "origin_message_id": str((origin or {}).get("message_id") or "")[:100],
            "session_context_kind": environment["kind"],
            "session_working_dir": environment["cwd"]
            if environment["kind"] == "legacy_folder"
            else "",
        },
    )
    return run


def _handoff_input(
    db, run: JarvisRun
) -> tuple[str, list[str], str, str, str, str, dict, dict, dict]:
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
    permission_mode = (
        str(data.get("permission_mode") or "approve") if isinstance(data, dict) else "approve"
    )
    effort = str(data.get("effort") or "medium") if isinstance(data, dict) else "medium"
    reasoning_mode = (
        str(data.get("reasoning_mode") or "automatic") if isinstance(data, dict) else "automatic"
    )
    custom_effort = data.get("custom_effort") if isinstance(data, dict) else {}
    if permission_mode not in _PERMISSION_MODES:
        permission_mode = "approve"
    if effort not in _EFFORT_LEVELS:
        effort = "medium"
    if reasoning_mode not in _REASONING_MODES:
        reasoning_mode = "automatic"
    if not isinstance(custom_effort, dict):
        custom_effort = {}
    origin = {
        "kind": str(data.get("origin_kind") or "")[:40],
        "connector_id": str(data.get("origin_connector_id") or "")[:100],
        "generation": str(data.get("origin_generation") or "")[:64],
        "channel_id": str(data.get("origin_channel_id") or "")[:100],
        "message_id": str(data.get("origin_message_id") or "")[:100],
    }
    context_kind = str(data.get("session_context_kind") or "")[:40]
    if not event and workflow.enabled:
        context_kind = "scheduled"
    session_context = {
        "kind": context_kind,
        "working_dir": str(data.get("session_working_dir") or "")[:4096],
    }
    return (
        workflow.prompt or "",
        files[:20],
        endpoint_override[:100],
        permission_mode,
        effort,
        reasoning_mode,
        custom_effort,
        origin,
        session_context,
    )


def _has_discord_origin(db, run: JarvisRun) -> bool:
    event = (
        db.query(JarvisRunEvent)
        .filter_by(run_id=run.id, kind="handoff_requested")
        .order_by(JarvisRunEvent.sequence)
        .first()
    )
    try:
        data = json.loads(event.data or "{}") if event else {}
    except (TypeError, ValueError):
        return False
    return bool(data.get("origin_kind") == "discord" and data.get("origin_connector_id"))


def retry_handoff(db, previous: JarvisRun) -> JarvisRun:
    if previous.state not in {"failed", "cancelled", "interrupted"}:
        raise ValueError("handoff_not_retryable")
    workflow = db.get(JarvisWorkflow, previous.workflow_id) if previous.workflow_id else None
    if not workflow or workflow.deterministic_action != HANDOFF_ACTION:
        raise ValueError("not_aide_handoff")
    (
        request,
        files,
        endpoint_override,
        permission_mode,
        effort,
        reasoning_mode,
        custom_effort,
        origin,
        session_context,
    ) = _handoff_input(db, previous)
    run = create_run(db, workflow, session_id=previous.session_id)
    workflow.active_run_id = run.id
    append_event(
        db,
        run,
        "handoff_requested",
        source="aide",
        summary="background retry requested",
        data={
            "file_ids": files,
            "endpoint_override": endpoint_override,
            "permission_mode": permission_mode,
            "effort": effort,
            "reasoning_mode": reasoning_mode,
            "custom_effort": custom_effort,
            "previous_run_id": previous.id,
            "origin_kind": origin["kind"],
            "origin_connector_id": origin["connector_id"],
            "origin_generation": origin["generation"],
            "origin_channel_id": origin["channel_id"],
            "origin_message_id": origin["message_id"],
            "session_context_kind": session_context["kind"],
            "session_working_dir": session_context["working_dir"],
        },
    )
    return run


def request_cancel(run_id: str) -> bool:
    event = _stops.get(run_id)
    if not event:
        return False
    event.set()
    return True


def stream_text(run_id: str) -> str:
    """Return the live answer text for a running handoff."""
    return _stream_text.get(str(run_id), "")


def clear_stream(run_id: str) -> None:
    _stream_text.pop(str(run_id), None)


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
            .order_by(JarvisRun.created_at)
            .all()
        )
        resumed = 0
        for row in rows:
            workflow = db.get(JarvisWorkflow, row.workflow_id)
            if not workflow:
                continue
            if workflow.concurrency_mode != "parallel":
                active = (
                    db.get(JarvisRun, workflow.active_run_id) if workflow.active_run_id else None
                )
                if (
                    active
                    and active.id != row.id
                    and active.state
                    not in {
                        "succeeded",
                        "failed",
                        "cancelled",
                        "uncertain",
                    }
                ):
                    continue
                workflow.active_run_id = row.id
                db.commit()
            resumed += int(launch(row.id))
        return resumed
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
            run.lease_owner = ""
            run.lease_expires_at = None
            db.commit()
    finally:
        db.close()


def _fail_missing_context(db, run: JarvisRun, message: str) -> None:
    transition_run(db, run, "running")
    transition_run(
        db,
        run,
        "failed",
        failure_class="missing_context",
        safe_error=message,
    )
    db.commit()


async def _execute(run_id: str) -> None:
    stop = asyncio.Event()
    _stops[run_id] = stop
    _stream_text[run_id] = ""
    keep_stream = False
    db = SessionLocal()
    try:
        run = db.get(JarvisRun, run_id)
        if not run or run.state != "queued":
            return
        workflow = db.get(JarvisWorkflow, run.workflow_id) if run.workflow_id else None
        session = db.get(Session, run.session_id) if run.session_id else None
        if not workflow or workflow.deterministic_action != HANDOFF_ACTION:
            _fail_missing_context(db, run, "this Aide workflow is unavailable")
            return
        keep_stream = _has_discord_origin(db, run)
        (
            request,
            file_ids,
            endpoint_override,
            permission_mode,
            effort,
            reasoning_mode,
            custom_effort,
            _origin,
            session_context,
        ) = _handoff_input(db, run)
        if not session:
            working_dir = ""
            if workflow.project_id:
                pass
            elif session_context["kind"] == "legacy_folder":
                from services.project_environment import canonical_folder

                try:
                    working_dir = canonical_folder(session_context["working_dir"], must_exist=True)
                except ValueError:
                    _fail_missing_context(db, run, "the original working folder is unavailable")
                    return
            elif session_context["kind"] not in {"general", "scheduled"}:
                _fail_missing_context(db, run, "the original Aide working context is unavailable")
                return
            session = Session(
                name=(workflow.name or "scheduled Aide work")[:80],
                mode="chat",
                project_id=workflow.project_id,
                working_dir=working_dir,
            )
            db.add(session)
            db.flush()
            run.session_id = session.id
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
            "aide_chat",
            workflow_override=model_choice,
            settings=settings,
        )
        from services.project_environment import session_environment

        environment = session_environment(session)
        settings["agent_cwd"] = environment["cwd"]
        settings["agent_environment"] = environment["kind"]
        settings["agent_project_id"] = environment["project_id"] or ""
        settings["_jarvis_run_id"] = run.id
        # Phase 4 handoffs can read and research. Phase 5 adds durable mutation approvals.
        settings["agent_permission_mode"] = permission_mode
        settings["agent_effort"] = effort
        settings["agent_reasoning_mode"] = reasoning_mode
        settings["agent_custom_effort"] = custom_effort
        complex_request = len(request) >= 72 or len(request.split()) >= 10
        settings["agent_subagents"] = complex_request and (
            effort == "deep_work"
            or (effort == "custom" and custom_effort.get("delegation") == "auto")
        )
        settings["agent_workflows"] = effort == "deep_work" or (
            effort == "custom" and custom_effort.get("workflows") == "auto"
        )
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
                delta = str(chunk["delta"])
                answer.append(delta)
                _stream_text[run_id] = (_stream_text.get(run_id, "") + delta)[:4000]
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
        log.warning("Aide background work failed: %s", type(exc).__name__)
        _finish(run_id, "failed", error="Aide could not finish this work")
    finally:
        if db is not None:
            db.close()
        _stops.pop(run_id, None)
        if not keep_stream:
            clear_stream(run_id)
        _tasks.pop(run_id, None)
