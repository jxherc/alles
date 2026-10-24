"""Durable Jarvis workflow, run, prompt, delivery, and connector APIs."""

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import (
    AideGoal,
    JarvisConnector,
    JarvisDeliveryAttempt,
    JarvisInboxEvent,
    JarvisRun,
    JarvisRunEvent,
    JarvisRunPrompt,
    JarvisTrigger,
    JarvisWorkflow,
    Project,
    Session,
    get_db,
)
from services import aide_goals, jarvis_discord, jarvis_handoff
from services.jarvis_outbox import enqueue_delivery
from services.jarvis_scheduler import next_for_trigger, utc_now, validate_trigger_config
from services.jarvis_store import (
    answer_choice,
    answer_questions,
    append_event,
    create_run,
    json_value,
)
from services.jarvis_store import (
    json_text as encode_json,
)

router = APIRouter(prefix="/api/jarvis")
# a goal's webhook sits outside /api: the caller is another service, not the signed-in owner,
# and the goal's own secret token is the only key
hooks = APIRouter(prefix="/hooks")

TRIGGER_KINDS = {"manual", "once", "schedule", "interval", "heartbeat", "event", "webhook"}
SUPPORTED_AIDE_SCHEDULE_KINDS = {"once", "schedule", "interval", "heartbeat"}
AIDE_SCHEDULE_OWNER = "aide_scheduled_v1"
CONTEXT_MODES = {"fresh", "continue", "project"}
CONCURRENCY_MODES = {"one", "queue", "skip", "parallel"}
_SECRET_CONFIG_KEY = re.compile(
    r"(?:^|_)(?:access_?key|api_?key|auth(?:orization)?|client_?secret|credential|password|"
    r"private_?key|secret|token|webhook)(?:$|_)",
    re.I,
)


def _bad(code: str, detail: str):
    raise ApiError(400, code, detail)


def _json_text(value, *, expected: type, limit: int = 16_000) -> str:
    try:
        return encode_json(value, expected=expected, limit=limit)
    except ValueError as exc:
        code = str(exc)
        _bad(code, code.replace("_", " "))


def _validate_public_connector_config(value, *, key: str = ""):
    if key and _SECRET_CONFIG_KEY.search(key):
        _bad(
            "connector_secret_in_config", "put connector credentials in the encrypted secret field"
        )
    if isinstance(value, dict):
        for child_key, child in value.items():
            _validate_public_connector_config(child, key=str(child_key))
    elif isinstance(value, list):
        for child in value:
            _validate_public_connector_config(child)
    elif isinstance(value, str) and "://" in value:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            _bad("connector_secret_in_config", "connector URLs cannot contain credentials")


def _validate_trigger(kind: str, config: dict, timezone_name: str) -> None:
    try:
        validate_trigger_config(kind, config, timezone_name)
    except ValueError as exc:
        code = str(exc)
        _bad(code, code.replace("_", " "))


def _workflow(row: JarvisWorkflow) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "purpose": row.purpose or "",
        "project_id": row.project_id,
        "prompt": row.prompt or "",
        "deterministic_action": row.deterministic_action or "",
        "model_override": row.model_override or "",
        "capability_ceiling": json_value(row.capability_ceiling, list),
        "concurrency_mode": row.concurrency_mode,
        "context_mode": row.context_mode,
        "delivery_policy": json_value(row.delivery_policy, dict),
        "enabled": bool(row.enabled),
        "review_state": row.review_state,
        "legacy_automation_id": row.legacy_automation_id,
        "legacy_enabled_intent": bool(row.legacy_enabled_intent),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _is_aide_schedule_workflow(row: JarvisWorkflow) -> bool:
    return bool(
        row.deterministic_action == jarvis_handoff.HANDOFF_ACTION
        and json_value(row.delivery_policy, dict).get("aide_schedule_owner") == AIDE_SCHEDULE_OWNER
    )


def _reject_generic_aide_schedule_change(row: JarvisWorkflow) -> None:
    if _is_aide_schedule_workflow(row) or aide_goals.is_goal(row):
        raise ApiError(
            409,
            "aide_schedule_route_required",
            "use the Aide Scheduled controls to change this schedule",
        )


def _reject_reserved_aide_schedule_policy(value: dict) -> None:
    if value.get("aide_schedule_owner") is not None:
        raise ApiError(
            409,
            "aide_schedule_owner_reserved",
            "the Aide schedule ownership marker is reserved",
        )


def _trigger(row: JarvisTrigger) -> dict:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "kind": row.kind,
        "config": json_value(row.config, dict),
        "timezone": row.timezone,
        "enabled": bool(row.enabled),
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "fingerprint": row.fingerprint or "",
    }


def _event(row: JarvisRunEvent) -> dict:
    return {
        "id": row.id,
        "sequence": row.sequence,
        "kind": row.kind,
        "source": row.source or "",
        "tool_name": row.tool_name or "",
        "summary": row.summary or "",
        "data": json_value(row.data, dict),
        "created_at": row.created_at.isoformat(),
    }


def _prompt(row: JarvisRunPrompt) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "kind": row.kind,
        "state": row.state,
        "question": row.question,
        "options": json_value(row.options, list),
        "question_schema": json_value(row.question_schema, dict),
        "action": row.action or "",
        "target": row.target or "",
        "data_summary": row.data_summary or "",
        "privacy_effect": row.privacy_effect or "",
        "cost": row.cost or "",
        "capability": row.capability or "",
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "answer": row.answer or "",
        "answer_data": json_value(row.answer_data, dict),
        "responded_at": row.responded_at.isoformat() if row.responded_at else None,
        "used_at": row.used_at.isoformat() if row.used_at else None,
        "delegated_action_id": row.delegated_action_id,
    }


def _delivery(row: JarvisDeliveryAttempt) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "event_id": row.event_id,
        "connector_id": row.connector_id,
        "channel": row.channel,
        "privacy_level": row.privacy_level,
        "state": row.state,
        "attempt_count": row.attempt_count,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "safe_error_class": row.safe_error_class or "",
        "provider_message_id": row.provider_message_id or "",
        "idempotency_supported": bool(row.idempotency_supported),
        "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
    }


def _run(db: DbSession, row: JarvisRun, *, detail: bool = False) -> dict:
    workflow = db.get(JarvisWorkflow, row.workflow_id) if row.workflow_id else None
    result = {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "trigger_id": row.trigger_id,
        "project_id": row.project_id,
        "session_id": row.session_id,
        "state": row.state,
        "title": workflow.name if workflow else "aide work",
        "scheduled_for": row.scheduled_for.isoformat() if row.scheduled_for else None,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "attempt_count": row.attempt_count,
        "failure_class": row.failure_class or "",
        "safe_error": row.safe_error or "",
        "result_summary": row.result_summary or "",
        "left_project_root": bool(row.left_project_root),
        "created_at": row.created_at.isoformat(),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if detail:
        result["title"] = workflow.name if workflow else "aide work"
        result["can_retry"] = bool(
            workflow
            and workflow.deterministic_action == jarvis_handoff.HANDOFF_ACTION
            and row.state in {"failed", "cancelled", "interrupted"}
        )
        result["events"] = [
            _event(item)
            for item in db.query(JarvisRunEvent)
            .filter_by(run_id=row.id)
            .order_by(JarvisRunEvent.sequence)
            .all()
        ]
        result["prompts"] = [
            _prompt(item)
            for item in db.query(JarvisRunPrompt)
            .filter_by(run_id=row.id)
            .order_by(JarvisRunPrompt.created_at)
            .all()
        ]
        result["deliveries"] = [
            _delivery(item)
            for item in db.query(JarvisDeliveryAttempt)
            .filter_by(run_id=row.id)
            .order_by(JarvisDeliveryAttempt.created_at)
            .all()
        ]
    return result


class WorkflowBody(BaseModel):
    name: str
    purpose: str = ""
    project_id: str = ""
    prompt: str = ""
    deterministic_action: str = ""
    model_override: str = ""
    capability_ceiling: list[str] = Field(default_factory=list)
    concurrency_mode: str = "one"
    context_mode: str = "fresh"
    delivery_policy: dict = Field(default_factory=dict)


class HandoffBody(BaseModel):
    session_id: str
    request_id: str = Field(default="", max_length=36)
    request: str = Field(min_length=1, max_length=50_000)
    endpoint_override: str = Field(default="", max_length=100)
    model_override: str = Field(default="", max_length=300)
    file_ids: list[str] = Field(default_factory=list, max_length=20)
    confirmed_endpoint_id: str = ""
    confirmed_model: str = ""
    confirmed_destination_fingerprint: str = ""
    permission_mode: Literal["full_access", "full_auto", "approve", "plan"] = "approve"
    effort: Literal["low", "medium", "high", "xhigh", "max", "deep_work", "custom"] = "medium"
    reasoning_mode: Literal["automatic", "on", "off"] = "automatic"
    custom_effort: dict | None = None


@router.get("/handoffs/preview")
def preview_handoff(
    session_id: str,
    endpoint_override: str = "",
    model_override: str = "",
    db: DbSession = Depends(get_db),
):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.incognito:
        raise ApiError(409, "incognito_handoff_forbidden", "incognito work stays in this tab")
    if endpoint_override and not model_override:
        raise ApiError(400, "invalid_model_override", "an endpoint override needs a model")
    try:
        return jarvis_handoff.model_preview(
            db,
            endpoint_override=endpoint_override,
            model_override=model_override,
        )
    except Exception as exc:
        from services.model_resolver import ModelResolutionError

        if isinstance(exc, ModelResolutionError):
            raise ApiError(409, exc.code, str(exc)) from exc
        raise


@router.post("/handoffs")
async def add_handoff(body: HandoffBody, db: DbSession = Depends(get_db)):
    session = db.get(Session, body.session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.incognito:
        raise ApiError(409, "incognito_handoff_forbidden", "incognito work stays in this tab")
    if body.endpoint_override and not body.model_override:
        raise ApiError(400, "invalid_model_override", "an endpoint override needs a model")
    identity = body.request_id
    if identity:
        try:
            canonical = str(UUID(identity))
            if identity.lower() != canonical:
                raise ValueError
            identity = canonical
        except ValueError:
            _bad("invalid_handoff_identity", "use a canonical request_id")
        # Reserve creation for this session so concurrent retries cannot both
        # create a workflow before the request-id run becomes visible.
        db.query(Session).filter_by(id=session.id).update(
            {Session.id: Session.id}, synchronize_session=False
        )
        db.expire_all()
        session = db.get(Session, body.session_id)
    replay = bool(identity and db.get(JarvisRun, identity))
    preview = None
    if not replay:
        from routes.chat import _require_idle_session

        # a reply is running in this task: work landing in its history now would split it
        _require_idle_session(session.id)
        try:
            preview = jarvis_handoff.model_preview(
                db,
                endpoint_override=body.endpoint_override,
                model_override=body.model_override,
            )
        except Exception as exc:
            from services.model_resolver import ModelResolutionError

            if isinstance(exc, ModelResolutionError):
                raise ApiError(409, exc.code, str(exc)) from exc
            raise
        if preview["privacy_class"] == "remote" and (
            body.confirmed_endpoint_id != preview["endpoint_id"]
            or body.confirmed_model != preview["model"]
            or body.confirmed_destination_fingerprint != preview["destination_fingerprint"]
        ):
            raise ApiError(
                409,
                "remote_model_confirmation_required",
                "confirm the shown background model before Project context leaves Alles",
            )
    try:
        run = jarvis_handoff.create_handoff(
            db,
            session,
            body.request,
            endpoint_override=body.endpoint_override,
            model_override=body.model_override,
            file_ids=body.file_ids,
            permission_mode=body.permission_mode,
            effort=body.effort,
            reasoning_mode=body.reasoning_mode,
            custom_effort=body.custom_effort,
            request_id=identity,
            accepted_model=preview,
        )
    except ValueError as exc:
        code = str(exc)
        raise ApiError(409, code, code.replace("_", " ")) from exc
    db.commit()
    db.refresh(run)
    if not replay:
        jarvis_handoff.launch(run.id)
    return _run(db, run, detail=True)


def _validate_workflow(body: WorkflowBody, db: DbSession):
    if not body.name.strip():
        _bad("workflow_name_required", "workflow name is required")
    if body.project_id and not db.get(Project, body.project_id):
        raise HTTPException(404, "project not found")
    if body.context_mode not in CONTEXT_MODES:
        _bad("invalid_context_mode", "context mode must be fresh, continue, or project")
    if body.context_mode == "project" and not body.project_id:
        _bad("project_context_required", "Project context needs a Project")
    if body.concurrency_mode not in CONCURRENCY_MODES:
        _bad("invalid_concurrency_mode", "invalid workflow concurrency mode")


@router.get("/workflows")
def list_workflows(db: DbSession = Depends(get_db)):
    rows = db.query(JarvisWorkflow).order_by(JarvisWorkflow.created_at).all()
    return [_workflow(row) for row in rows]


@router.post("/workflows")
def add_workflow(body: WorkflowBody, db: DbSession = Depends(get_db)):
    _validate_workflow(body, db)
    _reject_reserved_aide_schedule_policy(body.delivery_policy)
    row = JarvisWorkflow(
        name=body.name.strip(),
        purpose=body.purpose,
        project_id=body.project_id or None,
        prompt=body.prompt,
        deterministic_action=body.deterministic_action,
        model_override=body.model_override,
        capability_ceiling=_json_text(body.capability_ceiling, expected=list, limit=8000),
        concurrency_mode=body.concurrency_mode,
        context_mode=body.context_mode,
        delivery_policy=_json_text(body.delivery_policy, expected=dict, limit=8000),
        enabled=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _workflow(row)


class WorkflowPatch(BaseModel):
    name: str | None = None
    purpose: str | None = None
    project_id: str | None = None
    prompt: str | None = None
    deterministic_action: str | None = None
    model_override: str | None = None
    capability_ceiling: list[str] | None = None
    concurrency_mode: str | None = None
    context_mode: str | None = None
    delivery_policy: dict | None = None
    enabled: bool | None = None


@router.patch("/workflows/{workflow_id}")
def patch_workflow(
    workflow_id: str,
    body: WorkflowPatch,
    request: Request,
    db: DbSession = Depends(get_db),
):
    row = db.get(JarvisWorkflow, workflow_id)
    if not row:
        raise HTTPException(404)
    _reject_generic_aide_schedule_change(row)
    if body.name is not None:
        if not body.name.strip():
            _bad("workflow_name_required", "workflow name is required")
        row.name = body.name.strip()
    if "project_id" in body.model_fields_set:
        project_id = body.project_id or None
        if project_id and not db.get(Project, project_id):
            raise HTTPException(404, "project not found")
        row.project_id = project_id
    for field in ("purpose", "prompt", "deterministic_action", "model_override"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    if body.concurrency_mode is not None:
        if body.concurrency_mode not in CONCURRENCY_MODES:
            _bad("invalid_concurrency_mode", "invalid workflow concurrency mode")
        row.concurrency_mode = body.concurrency_mode
    if body.context_mode is not None:
        if body.context_mode not in CONTEXT_MODES:
            _bad("invalid_context_mode", "invalid workflow context mode")
        row.context_mode = body.context_mode
    if row.context_mode == "project" and not row.project_id:
        _bad("project_context_required", "Project context needs a Project")
    if body.capability_ceiling is not None:
        row.capability_ceiling = _json_text(body.capability_ceiling, expected=list, limit=8000)
    if body.delivery_policy is not None:
        _reject_reserved_aide_schedule_policy(body.delivery_policy)
        row.delivery_policy = _json_text(body.delivery_policy, expected=dict, limit=8000)
    if body.enabled is not None:
        if body.enabled and row.review_state == "needs_review":
            raise ApiError(
                409,
                "workflow_review_required",
                "review migrated model, permissions, delivery, and schedule first",
            )
        if body.enabled != bool(row.enabled):
            require_recent_owner(request)
        row.enabled = body.enabled
    db.commit()
    db.refresh(row)
    return _workflow(row)


class TriggerBody(BaseModel):
    kind: str
    config: dict = Field(default_factory=dict)
    timezone: str = "UTC"


class AideScheduleBody(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    prompt: str = Field(min_length=1, max_length=50_000)
    project_id: str = ""
    kind: str
    config: dict = Field(default_factory=dict)
    timezone: str = "UTC"


class AideScheduleStateBody(BaseModel):
    enabled: bool


def _validate_aide_schedule(body: AideScheduleBody, db: DbSession) -> tuple[str | None, str]:
    if not body.name.strip():
        _bad("workflow_name_required", "schedule name is required")
    if not body.prompt.strip():
        _bad("workflow_prompt_required", "tell Aide what to do")
    project_id = body.project_id or None
    if project_id and not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    if body.kind not in SUPPORTED_AIDE_SCHEDULE_KINDS:
        _bad("invalid_trigger_kind", "unknown schedule type")
    timezone_name = body.timezone or "UTC"
    _validate_trigger(body.kind, body.config, timezone_name)
    return project_id, timezone_name


def _owned_aide_schedule(db: DbSession, workflow_id: str) -> tuple[JarvisWorkflow, JarvisTrigger]:
    workflow = db.get(JarvisWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(404)
    delivery_policy = json_value(workflow.delivery_policy, dict)
    if (
        workflow.deterministic_action != jarvis_handoff.HANDOFF_ACTION
        or delivery_policy.get("aide_schedule_owner") != AIDE_SCHEDULE_OWNER
    ):
        raise ApiError(409, "not_aide_schedule", "this workflow is not owned by Aide Scheduled")
    triggers = db.query(JarvisTrigger).filter_by(workflow_id=workflow.id).all()
    if len(triggers) != 1 or triggers[0].kind not in SUPPORTED_AIDE_SCHEDULE_KINDS:
        raise ApiError(409, "invalid_aide_schedule", "this workflow has unsupported timing")
    return workflow, triggers[0]


@router.post("/aide-schedules", dependencies=[Depends(require_recent_owner)])
def add_aide_schedule(body: AideScheduleBody, db: DbSession = Depends(get_db)):
    project_id, timezone_name = _validate_aide_schedule(body, db)
    encoded_config = _json_text(body.config, expected=dict)
    workflow = JarvisWorkflow(
        name=body.name.strip(),
        purpose=body.prompt.strip(),
        project_id=project_id,
        prompt=body.prompt.strip(),
        deterministic_action=jarvis_handoff.HANDOFF_ACTION,
        capability_ceiling="[]",
        concurrency_mode="one",
        context_mode="project" if project_id else "fresh",
        delivery_policy=_json_text({"aide_schedule_owner": AIDE_SCHEDULE_OWNER}, expected=dict),
        enabled=True,
    )
    db.add(workflow)
    db.flush()
    trigger = JarvisTrigger(
        workflow_id=workflow.id,
        kind=body.kind,
        config=encoded_config,
        timezone=timezone_name,
        enabled=True,
    )
    db.add(trigger)
    db.flush()
    trigger.next_run_at = next_for_trigger(trigger, utc_now())
    db.commit()
    db.refresh(workflow)
    db.refresh(trigger)
    return {"workflow": _workflow(workflow), "trigger": _trigger(trigger)}


@router.patch("/aide-schedules/{workflow_id}", dependencies=[Depends(require_recent_owner)])
def patch_aide_schedule(
    workflow_id: str,
    body: AideScheduleBody,
    db: DbSession = Depends(get_db),
):
    workflow, trigger = _owned_aide_schedule(db, workflow_id)
    project_id, timezone_name = _validate_aide_schedule(body, db)
    encoded_config = _json_text(body.config, expected=dict)

    workflow.name = body.name.strip()
    workflow.purpose = body.prompt.strip()
    workflow.prompt = body.prompt.strip()
    workflow.project_id = project_id
    workflow.context_mode = "project" if project_id else "fresh"
    trigger.kind = body.kind
    trigger.config = encoded_config
    trigger.timezone = timezone_name
    trigger.next_run_at = next_for_trigger(trigger, utc_now()) if trigger.enabled else None
    db.commit()
    db.refresh(workflow)
    db.refresh(trigger)
    return {"workflow": _workflow(workflow), "trigger": _trigger(trigger)}


@router.patch("/aide-schedules/{workflow_id}/state", dependencies=[Depends(require_recent_owner)])
def patch_aide_schedule_state(
    workflow_id: str,
    body: AideScheduleStateBody,
    db: DbSession = Depends(get_db),
):
    workflow, trigger = _owned_aide_schedule(db, workflow_id)
    workflow.enabled = body.enabled
    trigger.enabled = body.enabled
    trigger.next_run_at = next_for_trigger(trigger, utc_now()) if body.enabled else None
    db.commit()
    db.refresh(workflow)
    db.refresh(trigger)
    return {"workflow": _workflow(workflow), "trigger": _trigger(trigger)}


class AideGoalBody(BaseModel):
    aim: str = Field(min_length=1, max_length=4000)
    name: str = Field(default="", max_length=120)
    every: Literal["hour", "six_hours", "day", "week"] = "day"
    mode: Literal["ask", "act"] = "ask"
    until: str = Field(default="", max_length=10)
    max_runs: int | None = Field(default=None, ge=1, le=1000)
    wake: Literal["rhythm", "mail", "webhook"] = "rhythm"
    mail_filter: str = Field(default="", max_length=200)


def _goal_until(raw: str):
    if not raw:
        return None
    try:
        day = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        _bad("invalid_goal_until", "use a date like 2026-12-31")
    return day.replace(hour=23, minute=59)


def _owned_goal(db: DbSession, workflow_id: str) -> tuple[JarvisWorkflow, JarvisTrigger]:
    workflow = db.get(JarvisWorkflow, workflow_id)
    if not workflow or not aide_goals.is_goal(workflow):
        raise ApiError(404, "goal_not_found", "goal not found")
    trigger = db.query(JarvisTrigger).filter_by(workflow_id=workflow.id).first()
    if trigger is None:
        raise ApiError(409, "invalid_goal", "this goal has no timing")
    return workflow, trigger


def _apply_goal(db: DbSession, workflow: JarvisWorkflow, trigger: JarvisTrigger, body):
    aim = body.aim.strip()
    if not aim:
        _bad("goal_aim_required", "say what the goal is")
    workflow.name = (body.name.strip() or aide_goals.short_name(aim))[:80]
    workflow.purpose = aim
    workflow.prompt = aim
    old = json_value(workflow.delivery_policy, dict)
    policy = {
        "aide_schedule_owner": aide_goals.GOAL_OWNER,
        "goal_every": body.every,
        "goal_mode": body.mode,
        "goal_wake": body.wake,
        "goal_mail_filter": body.mail_filter.strip(),
    }
    for kept in ("goal_hook_hash", "goal_mail_seen"):
        if kept in old:
            policy[kept] = old[kept]
    workflow.delivery_policy = _json_text(policy, expected=dict)
    trigger.kind = "interval"
    trigger.config = _json_text({"every_seconds": aide_goals.EVERY[body.every]}, expected=dict)
    trigger.timezone = "UTC"
    # mail and webhook goals wake on their event, not on a clock
    trigger.enabled = body.wake == "rhythm" and bool(workflow.enabled)
    goal = aide_goals.state_for(db, workflow)
    goal.until = _goal_until(body.until)
    goal.max_runs = body.max_runs


@router.get("/aide-goals")
def list_aide_goals(db: DbSession = Depends(get_db)):
    rows = db.query(JarvisWorkflow).order_by(JarvisWorkflow.created_at.desc()).all()
    items = []
    for workflow in rows:
        if aide_goals.is_goal(workflow):
            trigger = db.query(JarvisTrigger).filter_by(workflow_id=workflow.id).first()
            items.append(aide_goals.public(db, workflow, trigger))
    db.commit()
    return {"items": items}


@router.post("/aide-goals", dependencies=[Depends(require_recent_owner)])
def add_aide_goal(body: AideGoalBody, db: DbSession = Depends(get_db)):
    workflow = JarvisWorkflow(
        name="goal",
        deterministic_action=jarvis_handoff.HANDOFF_ACTION,
        capability_ceiling="[]",
        concurrency_mode="skip",
        context_mode="fresh",
        enabled=True,
    )
    db.add(workflow)
    db.flush()
    trigger = JarvisTrigger(workflow_id=workflow.id, kind="interval", config="{}", enabled=True)
    db.add(trigger)
    _apply_goal(db, workflow, trigger, body)
    db.flush()
    trigger.next_run_at = next_for_trigger(trigger, utc_now()) if trigger.enabled else None
    # the first check starts now instead of a whole rhythm later
    create_run(db, workflow)
    token = aide_goals.hook_token(workflow) if body.wake == "webhook" else ""
    db.commit()
    shown = aide_goals.public(db, workflow, trigger)
    # the webhook secret is shown once, here; only its hash is kept
    return {**shown, "hook_token": token} if token else shown


@router.patch("/aide-goals/{workflow_id}", dependencies=[Depends(require_recent_owner)])
def patch_aide_goal(workflow_id: str, body: AideGoalBody, db: DbSession = Depends(get_db)):
    workflow, trigger = _owned_goal(db, workflow_id)
    _apply_goal(db, workflow, trigger, body)
    trigger.next_run_at = next_for_trigger(trigger, utc_now()) if trigger.enabled else None
    db.commit()
    return aide_goals.public(db, workflow, trigger)


@router.post("/aide-goals/{workflow_id}/hook", dependencies=[Depends(require_recent_owner)])
def new_aide_goal_hook(workflow_id: str, db: DbSession = Depends(get_db)):
    """a new webhook secret for this goal; the old one stops working. shown only now."""
    workflow, _trigger = _owned_goal(db, workflow_id)
    token = aide_goals.hook_token(workflow)
    db.commit()
    return {"path": f"/hooks/goal/{workflow.id}", "token": token}


@hooks.post("/goal/{workflow_id}")
async def call_aide_goal_hook(workflow_id: str, request: Request, db: DbSession = Depends(get_db)):
    """wake a webhook goal now; the body goes into its next check as outside data."""
    workflow = db.get(JarvisWorkflow, workflow_id)
    bearer = request.headers.get("authorization", "")
    token = bearer[7:].strip() if bearer[:7].lower() == "bearer " else ""
    token = token or request.query_params.get("token", "")
    if (
        not workflow
        or not aide_goals.is_goal(workflow)
        or aide_goals.wake(workflow) != "webhook"
        or not aide_goals.hook_matches(workflow, token)
    ):
        raise ApiError(404, "hook_not_found", "no webhook here")
    raw = (await request.body())[:20_000].decode("utf-8", errors="replace").strip()
    run = aide_goals.wake_with(db, workflow, raw or "(the webhook was called with no body)")
    db.commit()
    return {"woken": run is not None}


@router.patch("/aide-goals/{workflow_id}/state", dependencies=[Depends(require_recent_owner)])
def patch_aide_goal_state(
    workflow_id: str, body: AideScheduleStateBody, db: DbSession = Depends(get_db)
):
    workflow, trigger = _owned_goal(db, workflow_id)
    workflow.enabled = body.enabled
    trigger.enabled = body.enabled and aide_goals.wake(workflow) == "rhythm"
    trigger.next_run_at = next_for_trigger(trigger, utc_now()) if trigger.enabled else None
    goal = aide_goals.state_for(db, workflow)
    if body.enabled:
        goal.status = "active"
        if goal.max_runs and goal.run_count >= goal.max_runs:
            goal.max_runs = None  # resuming a finished goal starts it again without the old cap
    else:
        goal.status = "paused" if goal.status == "active" else goal.status
    db.commit()
    return aide_goals.public(db, workflow, trigger)


@router.delete("/aide-goals/{workflow_id}", dependencies=[Depends(require_recent_owner)])
def delete_aide_goal(workflow_id: str, db: DbSession = Depends(get_db)):
    workflow, _trigger = _owned_goal(db, workflow_id)
    if aide_goals.running_run(db, workflow):
        raise ApiError(409, "goal_running", "stop the current check first")
    db.query(AideGoal).filter_by(workflow_id=workflow.id).delete()
    db.query(JarvisTrigger).filter_by(workflow_id=workflow.id).delete()
    db.query(JarvisRun).filter_by(workflow_id=workflow.id).update({JarvisRun.workflow_id: None})
    db.delete(workflow)
    db.commit()
    return {"deleted": True}


@router.get("/workflows/{workflow_id}/triggers")
def list_triggers(workflow_id: str, db: DbSession = Depends(get_db)):
    if not db.get(JarvisWorkflow, workflow_id):
        raise HTTPException(404)
    rows = (
        db.query(JarvisTrigger)
        .filter_by(workflow_id=workflow_id)
        .order_by(JarvisTrigger.created_at)
        .all()
    )
    return [_trigger(row) for row in rows]


@router.post("/workflows/{workflow_id}/triggers")
def add_trigger(workflow_id: str, body: TriggerBody, db: DbSession = Depends(get_db)):
    workflow = db.get(JarvisWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(404)
    _reject_generic_aide_schedule_change(workflow)
    if body.kind not in TRIGGER_KINDS:
        _bad("invalid_trigger_kind", "unknown schedule type")
    _validate_trigger(body.kind, body.config, body.timezone or "UTC")
    row = JarvisTrigger(
        workflow_id=workflow_id,
        kind=body.kind,
        config=_json_text(body.config, expected=dict),
        timezone=body.timezone or "UTC",
        enabled=False,
    )
    db.add(row)
    db.flush()
    row.next_run_at = next_for_trigger(row, utc_now())
    db.commit()
    db.refresh(row)
    return _trigger(row)


class TriggerPatch(BaseModel):
    kind: str | None = None
    config: dict | None = None
    timezone: str | None = None
    enabled: bool | None = None


@router.patch("/triggers/{trigger_id}")
def patch_trigger(
    trigger_id: str,
    body: TriggerPatch,
    request: Request,
    db: DbSession = Depends(get_db),
):
    row = db.get(JarvisTrigger, trigger_id)
    if not row:
        raise HTTPException(404)
    workflow = db.get(JarvisWorkflow, row.workflow_id)
    if workflow:
        _reject_generic_aide_schedule_change(workflow)
    kind = body.kind if body.kind is not None else row.kind
    if kind not in TRIGGER_KINDS:
        _bad("invalid_trigger_kind", "unknown schedule type")
    config = body.config if body.config is not None else json_value(row.config, dict)
    timezone_name = body.timezone if body.timezone is not None else row.timezone
    _validate_trigger(kind, config, timezone_name or "UTC")
    if body.kind is not None:
        row.kind = kind
    if body.config is not None:
        row.config = _json_text(config, expected=dict)
    if body.timezone is not None:
        row.timezone = timezone_name or "UTC"
    if body.enabled is not None and body.enabled != bool(row.enabled):
        if body.enabled and workflow and workflow.review_state == "needs_review":
            raise ApiError(409, "workflow_review_required", "review the migrated workflow first")
        require_recent_owner(request)
        row.enabled = body.enabled
    if row.enabled:
        row.next_run_at = next_for_trigger(row, utc_now())
    elif body.enabled is False:
        row.next_run_at = None
    db.commit()
    db.refresh(row)
    return _trigger(row)


class WorkflowReviewBody(BaseModel):
    model: bool = False
    permissions: bool = False
    delivery: bool = False
    schedule: bool = False


@router.post("/workflows/{workflow_id}/review", dependencies=[Depends(require_recent_owner)])
def review_workflow(
    workflow_id: str,
    body: WorkflowReviewBody,
    db: DbSession = Depends(get_db),
):
    workflow = db.get(JarvisWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(404)
    if not all((body.model, body.permissions, body.delivery, body.schedule)):
        raise ApiError(400, "workflow_review_incomplete", "confirm every workflow review area")
    workflow.review_state = "ready"
    workflow.enabled = False
    for trigger in db.query(JarvisTrigger).filter_by(workflow_id=workflow.id):
        trigger.enabled = False
        trigger.next_run_at = None
    db.commit()
    db.refresh(workflow)
    return _workflow(workflow)


def _inbox_event(row: JarvisInboxEvent) -> dict:
    return {
        "id": row.id,
        "source_kind": row.source_kind,
        "source_id": row.source_id,
        "event_type": row.event_type,
        "entity_kind": row.entity_kind,
        "entity_id": row.entity_id,
        "safe_summary": row.safe_summary,
        "external": bool(row.external),
        "state": row.state,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "dispatched_at": row.dispatched_at.isoformat() if row.dispatched_at else None,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/events")
def list_inbox_events(state: str = "", limit: int = 100, db: DbSession = Depends(get_db)):
    query = db.query(JarvisInboxEvent)
    if state:
        query = query.filter_by(state=state)
    rows = query.order_by(JarvisInboxEvent.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return [_inbox_event(row) for row in rows]


class EventReviewBody(BaseModel):
    allow: bool


@router.post("/events/{event_id}/review", dependencies=[Depends(require_recent_owner)])
def review_inbox_event(
    event_id: str,
    body: EventReviewBody,
    db: DbSession = Depends(get_db),
):
    from services.jarvis_events import review_event

    row = db.get(JarvisInboxEvent, event_id)
    if not row:
        raise HTTPException(404)
    try:
        review_event(db, row, allow=body.allow)
    except ValueError as exc:
        code = str(exc)
        raise ApiError(409, code, code.replace("_", " ")) from exc
    db.commit()
    db.refresh(row)
    return _inbox_event(row)


@router.post("/workflows/{workflow_id}/runs")
def queue_manual_run(workflow_id: str, db: DbSession = Depends(get_db)):
    workflow = db.get(JarvisWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(404)
    if not workflow.enabled:
        raise ApiError(409, "workflow_paused", "review and enable this workflow before running it")
    row = create_run(db, workflow)
    db.commit()
    db.refresh(row)
    return _run(db, row, detail=True)


@router.get("/runs")
def list_runs(
    limit: int = 50,
    workflow_id: str | None = None,
    db: DbSession = Depends(get_db),
):
    query = db.query(JarvisRun)
    if workflow_id:
        query = query.filter(JarvisRun.workflow_id == workflow_id)
    rows = query.order_by(JarvisRun.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return [_run(db, row) for row in rows]


class DeliveryBody(BaseModel):
    channel: str
    privacy_level: str = "title_status"
    event_id: str | None = None
    connector_id: str | None = None
    idempotency_supported: bool = False


@router.post("/runs/{run_id}/deliveries", dependencies=[Depends(require_recent_owner)])
def queue_delivery(run_id: str, body: DeliveryBody, db: DbSession = Depends(get_db)):
    run = db.get(JarvisRun, run_id)
    if not run:
        raise HTTPException(404)
    try:
        row, _created = enqueue_delivery(db, run, **body.model_dump())
    except ValueError as exc:
        code = str(exc)
        _bad(code, code.replace("_", " "))
    db.commit()
    db.refresh(row)
    return _delivery(row)


@router.get("/deliveries")
def list_deliveries(limit: int = 100, db: DbSession = Depends(get_db)):
    rows = (
        db.query(JarvisDeliveryAttempt)
        .order_by(JarvisDeliveryAttempt.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [_delivery(row) for row in rows]


@router.post("/deliveries/{delivery_id}/retry", dependencies=[Depends(require_recent_owner)])
def retry_delivery(delivery_id: str, db: DbSession = Depends(get_db)):
    row = db.get(JarvisDeliveryAttempt, delivery_id)
    if not row:
        raise HTTPException(404)
    if row.state == "uncertain":
        raise ApiError(409, "uncertain_delivery_not_retryable", "uncertain delivery is not resent")
    if row.state != "failed":
        raise ApiError(409, "delivery_not_retryable", "only a failed delivery can be retried")
    row.state = "retry"
    row.next_attempt_at = None
    row.safe_error_class = ""
    db.commit()
    db.refresh(row)
    return _delivery(row)


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: DbSession = Depends(get_db)):
    row = db.get(JarvisRun, run_id)
    if not row:
        raise HTTPException(404)
    return _run(db, row, detail=True)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: DbSession = Depends(get_db)):
    row = db.get(JarvisRun, run_id)
    if not row:
        raise HTTPException(404)
    if row.state == "queued":
        from services.jarvis_store import transition_run

        transition_run(db, row, "cancelled")
        db.commit()
    elif row.state == "running":
        if not jarvis_handoff.request_cancel(row.id):
            raise ApiError(409, "run_not_attached", "this run can be retried after restart")
        append_event(db, row, "cancel_requested", source="aide", summary="cancel requested")
        db.commit()
    else:
        raise ApiError(409, "run_not_cancellable", "this run cannot be cancelled")
    db.refresh(row)
    return _run(db, row, detail=True)


class RunRetryBody(BaseModel):
    request_id: str = ""


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str, body: RunRetryBody | None = None, db: DbSession = Depends(get_db)):
    identity = body.request_id if body else ""
    if identity:
        try:
            canonical = str(UUID(identity))
            if identity.lower() != canonical:
                raise ValueError
            identity = canonical
        except ValueError:
            _bad("invalid_retry_identity", "use a canonical request_id")
    try:
        if identity:
            # Reserve the write before checking identity, including concurrent retries.
            db.query(JarvisRun).filter_by(id=run_id).update(
                {JarvisRun.id: JarvisRun.id}, synchronize_session=False
            )
            db.expire_all()
        previous = db.get(JarvisRun, run_id)
        if not previous:
            raise HTTPException(404)
        replay = bool(identity and db.get(JarvisRun, identity))
        try:
            row = jarvis_handoff.retry_handoff(db, previous, request_id=identity)
        except ValueError as exc:
            code = str(exc)
            raise ApiError(409, code, code.replace("_", " ")) from exc
        db.commit()
        db.refresh(row)
        if not replay:
            jarvis_handoff.launch(row.id)
        return _run(db, row, detail=True)
    finally:
        db.rollback()


class ChoiceAnswer(BaseModel):
    answer: str = ""
    cancelled: bool = False
    answers: dict = Field(default_factory=dict)


@router.post("/prompts/{prompt_id}/answer")
async def submit_choice(prompt_id: str, body: ChoiceAnswer, db: DbSession = Depends(get_db)):
    prompt = db.get(JarvisRunPrompt, prompt_id)
    if not prompt:
        raise HTTPException(404)
    try:
        if json_value(prompt.question_schema, dict):
            answer_questions(
                db,
                prompt,
                {"cancelled": body.cancelled, "answers": body.answers},
            )
        else:
            answer_choice(db, prompt, body.answer)
    except ValueError as exc:
        code = str(exc)
        status = 409 if code in {"prompt_not_pending", "prompt_expired"} else 400
        if code == "prompt_expired":
            db.commit()
        raise ApiError(status, code, code.replace("_", " ")) from exc
    db.commit()
    db.refresh(prompt)
    if json_value(prompt.question_schema, dict):
        from services.agent_runtime import resolve_user_question_from_jarvis

        if not resolve_user_question_from_jarvis(prompt.id, json_value(prompt.answer_data, dict)):
            run = db.get(JarvisRun, prompt.run_id)
            workflow = db.get(JarvisWorkflow, run.workflow_id) if run and run.workflow_id else None
            if workflow and workflow.deterministic_action == jarvis_handoff.HANDOFF_ACTION:
                jarvis_handoff.launch(prompt.run_id)
    return _prompt(prompt)


def _connector(row: JarvisConnector) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "config": json_value(row.config, dict),
        "allowlist": json_value(row.allowlist, list),
        "secret_configured": bool(row.secret),
        "enabled": bool(row.enabled),
        "external": bool(row.external),
        "created_at": row.created_at.isoformat(),
    }


class ConnectorBody(BaseModel):
    name: str
    kind: str
    config: dict = Field(default_factory=dict)
    secret: str = ""
    allowlist: list[str] = Field(default_factory=list)
    external: bool = True


class DiscordConnectBody(BaseModel):
    bot_token: str = Field(min_length=1, max_length=500)


class DiscordPairBody(BaseModel):
    revoke_owner: bool = False


class DiscordPatchBody(BaseModel):
    enabled: bool | None = None
    allowed_channel_ids: list[str] | None = Field(default=None, max_length=100)
    quiet_hours: dict | None = None


@router.get("/discord")
def get_discord_connection(db: DbSession = Depends(get_db)):
    return jarvis_discord.public_connection(jarvis_discord.get_connection(db))


@router.post("/discord", dependencies=[Depends(require_recent_owner)])
async def connect_discord(body: DiscordConnectBody, db: DbSession = Depends(get_db)):
    try:
        identity = await jarvis_discord.validate_token(body.bot_token)
        row, code = jarvis_discord.configure(db, body.bot_token, identity)
    except ValueError as exc:
        code_name = str(exc)
        raise ApiError(400, code_name, code_name.replace("_", " ")) from exc
    except Exception as exc:
        raise ApiError(
            502, "discord_unavailable", "Discord could not verify this bot token"
        ) from exc
    result = jarvis_discord.public_connection(row)
    if code:
        result["pairing_code"] = code
    return result


@router.post("/discord/pairing-code", dependencies=[Depends(require_recent_owner)])
def create_discord_pairing_code(body: DiscordPairBody, db: DbSession = Depends(get_db)):
    row = jarvis_discord.get_connection(db)
    if not row:
        raise HTTPException(404, "Discord is not connected")
    code = jarvis_discord.issue_pairing_code(db, row, revoke_owner=body.revoke_owner)
    result = jarvis_discord.public_connection(row)
    result["pairing_code"] = code
    return result


@router.patch("/discord", dependencies=[Depends(require_recent_owner)])
def patch_discord_connection(body: DiscordPatchBody, db: DbSession = Depends(get_db)):
    row = jarvis_discord.get_connection(db)
    if not row:
        raise HTTPException(404, "Discord is not connected")
    try:
        row = jarvis_discord.update_connection(
            db,
            row,
            enabled=body.enabled,
            allowed_channel_ids=body.allowed_channel_ids,
            quiet_hours=body.quiet_hours,
        )
    except ValueError as exc:
        code = str(exc)
        raise ApiError(400, code, code.replace("_", " ")) from exc
    return jarvis_discord.public_connection(row)


@router.delete("/discord", dependencies=[Depends(require_recent_owner)])
def disconnect_discord(db: DbSession = Depends(get_db)):
    row = jarvis_discord.get_connection(db)
    if not row:
        return {"ok": True}
    db.delete(row)
    db.commit()
    jarvis_discord.notify_config_changed()
    return {"ok": True}


@router.get("/connectors")
def list_connectors(db: DbSession = Depends(get_db)):
    return [
        _connector(row)
        for row in db.query(JarvisConnector).order_by(JarvisConnector.created_at).all()
    ]


@router.post("/connectors", dependencies=[Depends(require_recent_owner)])
def add_connector(body: ConnectorBody, db: DbSession = Depends(get_db)):
    if not body.name.strip() or not body.kind.strip():
        _bad("connector_name_kind_required", "connector name and kind are required")
    _validate_public_connector_config(body.config)
    row = JarvisConnector(
        name=body.name.strip(),
        kind=body.kind.strip(),
        config=_json_text(body.config, expected=dict, limit=8000),
        secret=body.secret,
        allowlist=_json_text(body.allowlist, expected=list, limit=8000),
        enabled=False,
        external=body.external,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _connector(row)


@router.delete("/connectors/{connector_id}", dependencies=[Depends(require_recent_owner)])
def delete_connector(connector_id: str, db: DbSession = Depends(get_db)):
    row = db.get(JarvisConnector, connector_id)
    if not row:
        raise HTTPException(404)
    is_discord = row.kind == "discord"
    db.delete(row)
    db.commit()
    if is_discord:
        jarvis_discord.notify_config_changed()
    return {"ok": True}
