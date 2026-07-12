"""Durable Jarvis workflow, run, prompt, delivery, and connector APIs."""

import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import (
    JarvisConnector,
    JarvisDeliveryAttempt,
    JarvisRun,
    JarvisRunEvent,
    JarvisRunPrompt,
    JarvisTrigger,
    JarvisWorkflow,
    Project,
    get_db,
)
from services.jarvis_outbox import enqueue_delivery
from services.jarvis_scheduler import next_for_trigger, utc_now, validate_trigger_config
from services.jarvis_store import (
    answer_choice,
    create_run,
    json_value,
)
from services.jarvis_store import (
    json_text as encode_json,
)

router = APIRouter(prefix="/api/jarvis")

TRIGGER_KINDS = {"manual", "once", "schedule", "interval", "heartbeat", "event", "webhook"}
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
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


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
        "action": row.action or "",
        "target": row.target or "",
        "data_summary": row.data_summary or "",
        "privacy_effect": row.privacy_effect or "",
        "cost": row.cost or "",
        "capability": row.capability or "",
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "answer": row.answer or "",
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
    result = {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "trigger_id": row.trigger_id,
        "project_id": row.project_id,
        "session_id": row.session_id,
        "state": row.state,
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
    if body.name is not None:
        if not body.name.strip():
            _bad("workflow_name_required", "workflow name is required")
        row.name = body.name.strip()
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
        if body.context_mode == "project" and not row.project_id:
            _bad("project_context_required", "Project context needs a Project")
        row.context_mode = body.context_mode
    if body.capability_ceiling is not None:
        row.capability_ceiling = _json_text(body.capability_ceiling, expected=list, limit=8000)
    if body.delivery_policy is not None:
        row.delivery_policy = _json_text(body.delivery_policy, expected=dict, limit=8000)
    if body.enabled is not None:
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
    if not db.get(JarvisWorkflow, workflow_id):
        raise HTTPException(404)
    if body.kind not in TRIGGER_KINDS:
        _bad("invalid_trigger_kind", "unknown Jarvis trigger kind")
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
    config = body.config if body.config is not None else json_value(row.config, dict)
    timezone_name = body.timezone if body.timezone is not None else row.timezone
    _validate_trigger(row.kind, config, timezone_name or "UTC")
    if body.config is not None:
        row.config = _json_text(config, expected=dict)
    if body.timezone is not None:
        row.timezone = timezone_name or "UTC"
    if body.enabled is not None and body.enabled != bool(row.enabled):
        require_recent_owner(request)
        row.enabled = body.enabled
    if row.enabled:
        row.next_run_at = next_for_trigger(row, utc_now())
    elif body.enabled is False:
        row.next_run_at = None
    db.commit()
    db.refresh(row)
    return _trigger(row)


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
def list_runs(limit: int = 50, db: DbSession = Depends(get_db)):
    rows = (
        db.query(JarvisRun)
        .order_by(JarvisRun.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
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


class ChoiceAnswer(BaseModel):
    answer: str


@router.post("/prompts/{prompt_id}/answer")
def submit_choice(prompt_id: str, body: ChoiceAnswer, db: DbSession = Depends(get_db)):
    prompt = db.get(JarvisRunPrompt, prompt_id)
    if not prompt:
        raise HTTPException(404)
    try:
        answer_choice(db, prompt, body.answer)
    except ValueError as exc:
        code = str(exc)
        status = 409 if code in {"prompt_not_pending", "prompt_expired"} else 400
        if code == "prompt_expired":
            db.commit()
        raise ApiError(status, code, code.replace("_", " ")) from exc
    db.commit()
    db.refresh(prompt)
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
    db.delete(row)
    db.commit()
    return {"ok": True}
