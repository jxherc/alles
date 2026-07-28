"""Durable Jarvis workflow/run records and restart reconciliation."""

import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from core.database import (
    JarvisRun,
    JarvisRunEvent,
    JarvisRunPrompt,
    JarvisWorkflow,
    SessionLocal,
)
from services.aide_questions import normalize_answer, normalize_request

RUN_STATES = {
    "queued",
    "running",
    "waiting_input",
    "waiting_approval",
    "paused",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
    "uncertain",
}
TERMINAL_STATES = {"succeeded", "failed", "cancelled", "uncertain"}
_TRANSITIONS = {
    "queued": {"running", "paused", "cancelled"},
    "running": {
        "queued",
        "waiting_input",
        "waiting_approval",
        "paused",
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
        "uncertain",
    },
    "waiting_input": {"queued", "running", "paused", "cancelled"},
    "waiting_approval": {"queued", "running", "paused", "cancelled"},
    "paused": {"queued", "cancelled"},
    "interrupted": {"queued", "cancelled", "uncertain"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
    "uncertain": {"cancelled"},
}


def json_text(value, *, expected: type, limit: int = 16_000) -> str:
    if value is None:
        value = expected()
    if not isinstance(value, expected):
        raise ValueError("invalid_json_shape")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError("json_value_too_large")
    return encoded


def json_value(value: str, expected: type):
    try:
        decoded = json.loads(value or ("[]" if expected is list else "{}"))
    except (TypeError, ValueError):
        return expected()
    return decoded if isinstance(decoded, expected) else expected()


def append_event(
    db: DbSession,
    run: JarvisRun,
    kind: str,
    *,
    source: str = "jarvis",
    tool_name: str = "",
    summary: str = "",
    data: dict | None = None,
) -> JarvisRunEvent:
    if not kind or len(kind) > 64:
        raise ValueError("invalid_event_kind")
    sequence = (
        db.query(func.max(JarvisRunEvent.sequence)).filter(JarvisRunEvent.run_id == run.id).scalar()
        or 0
    ) + 1
    event = JarvisRunEvent(
        run_id=run.id,
        sequence=sequence,
        kind=kind,
        source=str(source or "")[:64],
        tool_name=str(tool_name or "")[:128],
        summary=str(summary or "")[:2000],
        data=json_text(data, expected=dict),
    )
    db.add(event)
    db.flush()
    return event


def create_run(
    db: DbSession,
    workflow: JarvisWorkflow,
    *,
    trigger_id: str | None = None,
    scheduled_for: datetime | None = None,
    occurrence_key: str | None = None,
    session_id: str | None = None,
) -> JarvisRun:
    run = JarvisRun(
        workflow_id=workflow.id,
        trigger_id=trigger_id,
        project_id=workflow.project_id,
        session_id=session_id,
        state="queued",
        scheduled_for=scheduled_for,
        occurrence_key=occurrence_key,
    )
    db.add(run)
    db.flush()
    append_event(db, run, "run_queued", summary="run queued")
    return run


def transition_run(
    db: DbSession,
    run: JarvisRun,
    state: str,
    *,
    failure_class: str = "",
    safe_error: str = "",
    result_summary: str = "",
) -> JarvisRun:
    state = str(state or "")
    if state not in RUN_STATES:
        raise ValueError("invalid_run_state")
    if state == run.state:
        return run
    if state not in _TRANSITIONS.get(run.state, set()):
        raise ValueError("invalid_run_transition")
    now = datetime.now()
    old = run.state
    run.state = state
    run.updated_at = now
    if state == "running" and run.started_at is None:
        run.started_at = now
    if state in TERMINAL_STATES:
        run.finished_at = now
    run.failure_class = str(failure_class or "")[:32]
    run.safe_error = str(safe_error or "")[:2000]
    run.result_summary = str(result_summary or "")[:4000]
    append_event(
        db,
        run,
        "run_state",
        summary=f"{old} → {state}",
        data={"from": old, "to": state},
    )
    return run


def create_prompt(
    db: DbSession,
    run: JarvisRun,
    *,
    kind: str,
    question: str = "",
    options: list | None = None,
    questions: list | None = None,
    title: str = "",
    action: str = "",
    target: str = "",
    data_summary: str = "",
    privacy_effect: str = "",
    cost: str = "",
    capability: str = "",
    expires_at: datetime | None = None,
) -> JarvisRunPrompt:
    if kind not in {"choice", "approval"}:
        raise ValueError("invalid_prompt_kind")
    question_schema = {}
    if questions is not None:
        if kind != "choice":
            raise ValueError("structured_approval_forbidden")
        question_schema = normalize_request({"title": title or question, "questions": questions})
        question = question or question_schema["title"]
    if not str(question or "").strip():
        raise ValueError("prompt_question_required")
    if db.query(JarvisRunPrompt).filter_by(run_id=run.id, state="pending").first() is not None:
        raise ValueError("prompt_already_pending")
    if run.state != "running":
        raise ValueError("run_not_accepting_prompt")
    prompt = JarvisRunPrompt(
        run_id=run.id,
        kind=kind,
        question=str(question)[:4000],
        options=json_text(options, expected=list, limit=8000),
        question_schema=json_text(question_schema, expected=dict, limit=24_000),
        action=str(action or "")[:128],
        target=str(target or "")[:2000],
        data_summary=str(data_summary or "")[:2000],
        privacy_effect=str(privacy_effect or "")[:2000],
        cost=str(cost or "")[:128],
        capability=str(capability or "")[:128],
        expires_at=expires_at,
    )
    db.add(prompt)
    transition_run(db, run, "waiting_input" if kind == "choice" else "waiting_approval")
    append_event(db, run, "prompt_created", summary=f"{kind} requested")
    db.flush()
    return prompt


def _mark_choice_answered(
    db: DbSession, prompt: JarvisRunPrompt, *, answer: str, answer_data: dict
) -> JarvisRunPrompt:
    now = datetime.now()
    prompt.answer = str(answer or "")[:2000]
    prompt.answer_data = json_text(answer_data, expected=dict, limit=24_000)
    prompt.state = "answered"
    prompt.responded_at = now
    run = db.get(JarvisRun, prompt.run_id)
    if run:
        append_event(db, run, "choice_answered", summary="choice answered")
        if run.state == "waiting_input":
            transition_run(db, run, "queued")
    return prompt


def answer_choice(db: DbSession, prompt: JarvisRunPrompt, answer: str) -> JarvisRunPrompt:
    if prompt.kind != "choice":
        raise ValueError("approval_requires_exact_gate")
    if prompt.state != "pending":
        raise ValueError("prompt_not_pending")
    now = datetime.now()
    if prompt.expires_at and prompt.expires_at <= now:
        prompt.state = "expired"
        raise ValueError("prompt_expired")
    choices = json_value(prompt.options, list)
    value = str(answer or "")
    if choices and value not in choices:
        raise ValueError("invalid_prompt_answer")
    return _mark_choice_answered(db, prompt, answer=value, answer_data={})


def answer_questions(db: DbSession, prompt: JarvisRunPrompt, answer: dict) -> JarvisRunPrompt:
    if prompt.kind != "choice":
        raise ValueError("approval_requires_exact_gate")
    if prompt.state != "pending":
        raise ValueError("prompt_not_pending")
    now = datetime.now()
    if prompt.expires_at and prompt.expires_at <= now:
        prompt.state = "expired"
        raise ValueError("prompt_expired")
    schema = json_value(prompt.question_schema, dict)
    if not schema:
        raise ValueError("structured_question_unavailable")
    normalized = normalize_answer(schema, answer)
    summary = "cancelled" if normalized["cancelled"] else json.dumps(
        normalized["answers"], ensure_ascii=False, separators=(",", ":")
    )
    return _mark_choice_answered(db, prompt, answer=summary, answer_data=normalized)


def reconcile_interrupted_runs() -> dict:
    """Mark runs left active by a stopped process without guessing their outcome."""
    db = SessionLocal()
    interrupted = 0
    uncertain = 0
    try:
        runs = db.query(JarvisRun).filter(JarvisRun.state == "running").all()
        for run in runs:
            latest_effect = (
                db.query(JarvisRunEvent)
                .filter(
                    JarvisRunEvent.run_id == run.id,
                    JarvisRunEvent.kind.in_({"side_effect_started", "side_effect_confirmed"}),
                )
                .order_by(JarvisRunEvent.sequence.desc())
                .first()
            )
            if latest_effect and latest_effect.kind == "side_effect_started":
                transition_run(
                    db,
                    run,
                    "uncertain",
                    failure_class="uncertain",
                    safe_error="an external side effect could not be confirmed after restart",
                )
                uncertain += 1
            else:
                transition_run(
                    db,
                    run,
                    "interrupted",
                    failure_class="interrupted",
                    safe_error="the server stopped while this run was active",
                )
                interrupted += 1
        db.commit()
        return {"interrupted": interrupted, "uncertain": uncertain}
    finally:
        db.close()
