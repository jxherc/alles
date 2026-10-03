"""The saved Task status transition shared by Plan and Aide."""

from datetime import UTC, datetime

from sqlalchemy import text

from core.database import Task
from services.task_nl import advance

TASK_STAGES = {"backlog", "next", "doing", "waiting", "done"}


def normalize_stage(value: str, done: bool = False) -> str:
    if done:
        return "done"
    normalized = str(value or "backlog").strip().lower()
    if normalized not in TASK_STAGES or normalized == "done":
        return "backlog"
    return normalized


def apply_status(
    db, task: Task, *, stage: str | None = None, done: bool | None = None
) -> Task | None:
    """Change status in the caller's transaction; return the next recurring Task, if any."""
    if stage is None and done is None:
        raise ValueError("stage or done is required")

    # Reserve this transaction before reloading a possibly stale completion. Both
    # Plan and Aide use this owner; a status retry must see the saved issuance.
    db.flush()
    db.execute(text("UPDATE tasks SET id = id WHERE id = :id"), {"id": task.id})
    db.refresh(task)

    next_done = stage == "done" if stage is not None else bool(done)
    if stage is not None:
        next_stage = stage
    elif next_done:
        next_stage = "done"
    elif task.done:
        next_stage = "backlog"
    else:
        next_stage = normalize_stage(task.stage)
    if next_done != bool(task.done):
        task.completed_at = datetime.now(UTC).replace(tzinfo=None) if next_done else None

    spawned = None
    if next_done and not task.done and not task.recurrence_issued and task.repeat and task.due_date:
        anchor = task.anchor_day or (int(task.due_date[8:10]) if len(task.due_date) >= 10 else None)
        due = advance(task.due_date, task.repeat, anchor)
        if due:
            task.recurrence_issued = True
            spawned = Task(
                title=task.title,
                priority=task.priority,
                due_date=due,
                repeat=task.repeat,
                anchor_day=anchor,
                tags=task.tags,
                project=task.project,
                notes=task.notes,
                source_json=task.source_json,
                parent_id=task.parent_id,
                stage="backlog",
            )
            db.add(spawned)

    task.done = next_done
    task.stage = next_stage
    return spawned
