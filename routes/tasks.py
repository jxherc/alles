from datetime import UTC, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.database import Task, get_db
from core.settings import load_settings
from services.task_nl import advance, parse_task, reschedule_date

router = APIRouter(prefix="/api")

TASK_STAGES = {"backlog", "next", "doing", "waiting", "done"}


def _stage(value: str, done: bool = False) -> str:
    if done:
        return "done"
    normalized = str(value or "backlog").strip().lower()
    if normalized not in TASK_STAGES or normalized == "done":
        return "backlog"
    return normalized


def _validate_stage(value) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in TASK_STAGES:
        raise HTTPException(400, "stage must be backlog|next|doing|waiting|done")
    return normalized


def _fmt(t: Task) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "done": t.done,
        "stage": _stage(getattr(t, "stage", ""), bool(t.done)),
        "priority": t.priority,
        "due_date": t.due_date,
        "parent_id": t.parent_id,
        "tags": [x for x in (t.tags or "").split(",") if x],
        "repeat": t.repeat or "",
        "notes": t.notes or "",
        "project": t.project or "",
        "sort_order": t.sort_order or 0,
        "created_at": t.created_at.isoformat(),
    }


def _ordered(rows):
    return sorted(
        rows,
        key=lambda t: (
            t.sort_order or 0,
            -(t.priority or 0),
            t.due_date or "9999",
            t.created_at.isoformat(),
        ),
    )


@router.get("/tasks")
def list_tasks(project: str = "", tag: str = "", db: DbSession = Depends(get_db)):
    q = db.query(Task).filter(Task.done == False)
    if project:
        q = q.filter(Task.project == project)
    rows = _ordered(q.all())
    if tag:
        rows = [t for t in rows if tag in (t.tags or "").split(",")]
    return [_fmt(t) for t in rows]


@router.get("/tasks/search")
def search_tasks(q: str = "", db: DbSession = Depends(get_db)):
    """search active tasks by title / notes / tags (case-insensitive substring)."""
    q = (q or "").strip()
    if not q:
        return []
    rows = _ordered(db.query(Task).filter(Task.done == False).all())
    ql = q.lower()
    hits = [
        t
        for t in rows
        if ql in (t.title or "").lower()
        or ql in (t.notes or "").lower()
        or ql in (t.tags or "").lower()
    ]
    return [_fmt(t) for t in hits]


@router.get("/tasks/tree")
def task_tree(db: DbSession = Depends(get_db)):
    """active top-level tasks with their subtasks nested + done/total progress."""
    children: dict[str, list] = {}
    rows = db.query(Task).all()  # one scan; includes done subtasks so progress is accurate
    for t in rows:
        if t.parent_id:
            children.setdefault(t.parent_id, []).append(t)
    tops = _ordered([t for t in rows if not t.parent_id and not t.done])
    out = []
    for t in tops:
        subs = _ordered(children.get(t.id, []))
        node = _fmt(t)
        node["subtasks"] = [_fmt(s) for s in subs]
        node["progress"] = {"done": sum(1 for s in subs if s.done), "total": len(subs)}
        out.append(node)
    return out


@router.get("/tasks/done")
def list_done(db: DbSession = Depends(get_db)):
    rows = db.query(Task).filter(Task.done == True).order_by(Task.created_at.desc()).limit(50).all()
    return [_fmt(t) for t in rows]


@router.get("/tasks/views/{view}")
def list_view(view: str, db: DbSession = Depends(get_db)):
    """today | upcoming | someday — curated queues by due date."""
    today = date.today().isoformat()
    rows = _ordered(db.query(Task).filter(Task.done == False).all())
    if view == "today":
        rows = [t for t in rows if t.due_date and t.due_date[:10] <= today]  # due or overdue
    elif view == "upcoming":
        rows = [t for t in rows if t.due_date and t.due_date[:10] > today]
    elif view == "someday":
        rows = [t for t in rows if not t.due_date]
    else:
        raise HTTPException(400, "view must be today|upcoming|someday")
    return [_fmt(t) for t in rows]


class TaskBody(BaseModel):
    title: str
    priority: int = 0
    due_date: Optional[str] = None
    parent_id: Optional[str] = None
    tags: str = ""
    repeat: str = ""
    project: str = ""
    notes: str = ""
    stage: str = "backlog"
    nl: bool = False  # parse the title as natural language


@router.post("/tasks")
def create_task(body: TaskBody, db: DbSession = Depends(get_db)):
    stage = _validate_stage(body.stage)
    fields = dict(
        title=body.title,
        priority=body.priority,
        due_date=body.due_date,
        parent_id=body.parent_id,
        tags=body.tags,
        repeat=body.repeat,
        project=body.project,
        notes=body.notes,
        stage=stage,
        done=stage == "done",
    )
    if body.nl:
        p = parse_task(body.title, language=load_settings().get("language", "en"))
        fields["title"] = p["title"]
        fields["priority"] = max(body.priority, p["priority"])
        fields["due_date"] = body.due_date or p["due_date"]
        fields["repeat"] = body.repeat or p["repeat"]
        fields["tags"] = body.tags or p["tags"]
    if (
        fields.get("repeat")
        and (fields.get("due_date") or "")[:10]
        and len(fields["due_date"]) >= 10
    ):
        fields["anchor_day"] = int(
            fields["due_date"][8:10]
        )  # pin the day so monthly/yearly don't drift
    t = Task(**fields)
    db.add(t)
    db.commit()
    db.refresh(t)
    return _fmt(t)


class QuickBody(BaseModel):
    text: str
    project: str = ""


@router.post("/tasks/quick")
def quick_add(body: QuickBody, db: DbSession = Depends(get_db)):
    """natural-language quick add: 'pay rent every 1st !', 'call mom tomorrow #home'."""
    if not body.text.strip():
        raise HTTPException(400, "empty")
    p = parse_task(body.text, language=load_settings().get("language", "en"))
    _due = p["due_date"] or ""
    t = Task(
        title=p["title"],
        priority=p["priority"],
        due_date=p["due_date"],
        repeat=p["repeat"],
        anchor_day=(int(_due[8:10]) if p["repeat"] and len(_due) >= 10 else None),
        tags=p["tags"],
        project=body.project,
        stage="backlog",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _fmt(t)


class TaskOrderItem(BaseModel):
    id: str
    stage: str
    sort_order: int = Field(ge=0, le=1999)


class TaskOrderBody(BaseModel):
    items: list[TaskOrderItem] = Field(default_factory=list)
    ids: list[str] = Field(default_factory=list)


@router.post("/tasks/reorder")
def reorder_tasks(body: TaskOrderBody, db: DbSession = Depends(get_db)):
    """Atomically persist the visible active-task board order and stages."""
    if body.items and body.ids:
        raise HTTPException(400, "send items or ids, not both")
    items = body.items
    if body.ids:
        if len(body.ids) > 2000:
            raise HTTPException(400, "too many tasks")
        if len(body.ids) != len(set(body.ids)):
            raise HTTPException(400, "task ids must be unique")
        legacy_rows = db.query(Task).filter(Task.id.in_(body.ids)).all()
        legacy_by_id = {row.id: row for row in legacy_rows}
        missing = [tid for tid in body.ids if tid not in legacy_by_id]
        if missing:
            raise HTTPException(404, "task not found")
        items = [
            TaskOrderItem(
                id=tid,
                stage=_stage(getattr(legacy_by_id[tid], "stage", ""), False),
                sort_order=index,
            )
            for index, tid in enumerate(body.ids)
        ]
    if len(items) > 2000:
        raise HTTPException(400, "too many tasks")
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise HTTPException(400, "task ids must be unique")
    rows = db.query(Task).filter(Task.id.in_(ids)).all() if ids else []
    by_id = {row.id: row for row in rows}
    missing = [tid for tid in ids if tid not in by_id]
    if missing:
        raise HTTPException(404, "task not found")
    normalized_stages = {}
    for item in items:
        stage = _validate_stage(item.stage)
        if stage == "done":
            raise HTTPException(400, "complete tasks with the task update endpoint")
        row = by_id[item.id]
        if row.done:
            raise HTTPException(409, "completed task cannot be reordered")
        normalized_stages[item.id] = stage
    active_rows = db.query(Task).filter(Task.done == False).all()
    active_ids = {row.id for row in active_rows}
    if set(ids) != active_ids:
        raise HTTPException(400, "reorder requires the complete active-task board")
    requested = {item.id: item for item in items}
    positions = set()
    for row in active_rows:
        item = requested.get(row.id)
        position = (
            normalized_stages[row.id] if item else _stage(row.stage, False),
            item.sort_order if item else (row.sort_order or 0),
        )
        if position in positions:
            raise HTTPException(400, "task sort orders must be unique within each stage")
        positions.add(position)
    for item in items:
        row = by_id[item.id]
        row.stage = normalized_stages[item.id]
        row.sort_order = item.sort_order
    db.commit()
    return {"items": [_fmt(by_id[item.id]) for item in items]}


@router.patch("/tasks/{tid}")
def update_task(tid: str, body: dict, db: DbSession = Depends(get_db)):
    t = db.get(Task, tid)
    if not t:
        raise HTTPException(404)
    spawned = None
    if "stage" in body:
        body["stage"] = _validate_stage(body["stage"])
        body["done"] = body["stage"] == "done"
    elif "done" in body:
        body["done"] = bool(body["done"])
        body["stage"] = (
            "done"
            if body["done"]
            else "backlog"
            if _stage(getattr(t, "stage", ""), bool(t.done)) == "done"
            else _stage(getattr(t, "stage", ""), False)
        )
    # stamp/clear the completion time as done flips (powers the activity feed)
    if "done" in body and bool(body["done"]) != bool(t.done):
        from datetime import datetime

        t.completed_at = datetime.now(UTC).replace(tzinfo=None) if body["done"] else None
    if body.get("done") and not t.done and t.repeat and t.due_date:
        # completing a recurring task rolls it forward to the next occurrence
        anchor = t.anchor_day or (int(t.due_date[8:10]) if len(t.due_date) >= 10 else None)
        nxt = advance(t.due_date, t.repeat, anchor)
        if nxt:
            spawned = Task(
                title=t.title,
                priority=t.priority,
                due_date=nxt,
                repeat=t.repeat,
                anchor_day=anchor,
                tags=t.tags,
                project=t.project,
                notes=t.notes,
                parent_id=t.parent_id,
                stage="backlog",
            )
            db.add(spawned)
    # priority/sort_order feed an int sort key in _ordered — a non-int gets stored then 500s
    # every list/tree/search path, so coerce up front and reject junk with a 400
    for numf in ("priority", "sort_order"):
        if body.get(numf) is not None:
            try:
                body[numf] = int(body[numf])
            except (TypeError, ValueError):
                raise HTTPException(400, f"{numf} must be an integer")
    for f in (
        "done",
        "title",
        "priority",
        "due_date",
        "tags",
        "repeat",
        "notes",
        "project",
        "sort_order",
        "parent_id",
        "stage",
    ):
        if f in body:
            setattr(t, f, body[f])
    # keep the drift anchor in sync if the due date was edited on a repeating task
    if "due_date" in body or "repeat" in body:
        t.anchor_day = (
            int(t.due_date[8:10]) if (t.repeat and t.due_date and len(t.due_date) >= 10) else None
        )
    db.commit()
    db.refresh(t)
    out = _fmt(t)
    if spawned:
        db.refresh(spawned)
        out["spawned"] = _fmt(spawned)
    return out


class RescheduleBody(BaseModel):
    when: str


@router.post("/tasks/{tid}/reschedule")
def reschedule_task(tid: str, body: RescheduleBody, db: DbSession = Depends(get_db)):
    """quick reschedule: today | tomorrow | next_week | weekend | <weekday>."""
    t = db.get(Task, tid)
    if not t:
        raise HTTPException(404)
    try:
        t.due_date = reschedule_date(body.when)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    db.refresh(t)
    return _fmt(t)


@router.delete("/tasks/{tid}")
def delete_task(tid: str, db: DbSession = Depends(get_db)):
    t = db.get(Task, tid)
    if not t:
        raise HTTPException(404)
    db.query(Task).filter(Task.parent_id == tid).delete()  # cascade subtasks
    db.delete(t)
    db.commit()
    return {"ok": True}
