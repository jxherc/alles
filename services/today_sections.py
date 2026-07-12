"""Deterministic Afterlife Today sections built from local records only."""

from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session as DbSession

from core.database import (
    JarvisDeliveryAttempt,
    JarvisRun,
    JarvisRunPrompt,
    JarvisWorkflow,
    Project,
)

_LIMIT = 12
_ATTENTION_RUN_STATES = {"waiting_input", "waiting_approval", "failed", "interrupted", "uncertain"}
_ACTIVE_RUN_STATES = {"queued", "running", "paused"}


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _context(db: DbSession, runs: list[JarvisRun]) -> tuple[dict[str, str], dict[str, str]]:
    workflow_ids = {row.workflow_id for row in runs if row.workflow_id}
    project_ids = {row.project_id for row in runs if row.project_id}
    workflows = (
        {
            row.id: row.name
            for row in db.query(JarvisWorkflow).filter(JarvisWorkflow.id.in_(workflow_ids)).all()
        }
        if workflow_ids
        else {}
    )
    projects = (
        {row.id: row.name for row in db.query(Project).filter(Project.id.in_(project_ids)).all()}
        if project_ids
        else {}
    )
    return workflows, projects


def _run_card(row: JarvisRun, workflows: dict[str, str], projects: dict[str, str]) -> dict:
    return {
        "kind": "run",
        "id": row.id,
        "run_id": row.id,
        "title": workflows.get(row.workflow_id, "jarvis task"),
        "project": projects.get(row.project_id, "general"),
        "state": row.state,
        "summary": row.safe_error or row.result_summary or "",
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _prompt_cards(db: DbSession) -> tuple[list[dict], set[str]]:
    now = datetime.now(UTC).replace(tzinfo=None)
    pairs = (
        db.query(JarvisRunPrompt, JarvisRun)
        .join(JarvisRun, JarvisRun.id == JarvisRunPrompt.run_id)
        .filter(
            JarvisRunPrompt.state == "pending",
            or_(JarvisRunPrompt.expires_at.is_(None), JarvisRunPrompt.expires_at > now),
        )
        .order_by(JarvisRunPrompt.created_at.desc())
        .limit(_LIMIT)
        .all()
    )
    runs = [run for _prompt, run in pairs]
    workflows, projects = _context(db, runs)
    cards = [
        {
            "kind": prompt.kind,
            "id": prompt.id,
            "run_id": run.id,
            "title": prompt.question,
            "workflow": workflows.get(run.workflow_id, "jarvis task"),
            "project": projects.get(run.project_id, "general"),
            "state": prompt.state,
            "created_at": _iso(prompt.created_at),
            "expires_at": _iso(prompt.expires_at),
        }
        for prompt, run in pairs
    ]
    return cards, {run.id for run in runs}


def _attention_runs(db: DbSession, prompted_run_ids: set[str]) -> list[dict]:
    rows = (
        db.query(JarvisRun)
        .filter(JarvisRun.state.in_(_ATTENTION_RUN_STATES))
        .order_by(JarvisRun.updated_at.desc())
        .limit(_LIMIT * 2)
        .all()
    )
    rows = [row for row in rows if row.id not in prompted_run_ids][:_LIMIT]
    workflows, projects = _context(db, rows)
    return [_run_card(row, workflows, projects) for row in rows]


def _delivery_cards(db: DbSession) -> list[dict]:
    rows = (
        db.query(JarvisDeliveryAttempt)
        .filter(JarvisDeliveryAttempt.state.in_(("failed", "uncertain")))
        .order_by(JarvisDeliveryAttempt.updated_at.desc())
        .limit(_LIMIT)
        .all()
    )
    return [
        {
            "kind": "delivery",
            "id": row.id,
            "run_id": row.run_id,
            "title": f"{row.channel} delivery",
            "state": row.state,
            "summary": row.safe_error_class or "",
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
        for row in rows
    ]


def _active_runs(db: DbSession) -> list[dict]:
    rows = (
        db.query(JarvisRun)
        .filter(JarvisRun.state.in_(_ACTIVE_RUN_STATES))
        .order_by(JarvisRun.updated_at.desc())
        .limit(_LIMIT)
        .all()
    )
    workflows, projects = _context(db, rows)
    return [_run_card(row, workflows, projects) for row in rows]


def _briefs(db: DbSession) -> list[dict]:
    rows = (
        db.query(JarvisRun)
        .filter(JarvisRun.state == "succeeded", JarvisRun.result_summary != "")
        .order_by(JarvisRun.finished_at.desc(), JarvisRun.updated_at.desc())
        .limit(_LIMIT)
        .all()
    )
    workflows, projects = _context(db, rows)
    return [
        {
            **_run_card(row, workflows, projects),
            "kind": "brief",
            "finished_at": _iso(row.finished_at),
        }
        for row in rows
    ]


def build(db: DbSession, daily: dict) -> dict:
    prompts, prompted_run_ids = _prompt_cards(db)
    return {
        "needs_you": [*prompts, *_attention_runs(db, prompted_run_ids), *_delivery_cards(db)],
        "today": daily,
        "in_progress": _active_runs(db),
        "briefs": _briefs(db),
        "shortcuts": [],
    }
