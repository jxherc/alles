from datetime import date
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Task
from services.task_nl import parse_task, advance

router = APIRouter(prefix="/api")


def _fmt(t: Task) -> dict:
    return {
        "id":         t.id,
        "title":      t.title,
        "done":       t.done,
        "priority":   t.priority,
        "due_date":   t.due_date,
        "parent_id":  t.parent_id,
        "tags":       [x for x in (t.tags or "").split(",") if x],
        "repeat":     t.repeat or "",
        "notes":      t.notes or "",
        "project":    t.project or "",
        "sort_order": t.sort_order or 0,
        "created_at": t.created_at.isoformat(),
    }


def _ordered(rows):
    return sorted(rows, key=lambda t: (t.sort_order or 0, -(t.priority or 0),
                                       t.due_date or "9999", t.created_at.isoformat()))


@router.get("/tasks")
def list_tasks(project: str = "", tag: str = "", db: DbSession = Depends(get_db)):
    q = db.query(Task).filter(Task.done == False)
    if project:
        q = q.filter(Task.project == project)
    rows = _ordered(q.all())
    if tag:
        rows = [t for t in rows if tag in (t.tags or "").split(",")]
    return [_fmt(t) for t in rows]


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
        rows = [t for t in rows if t.due_date and t.due_date[:10] <= today]   # due or overdue
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
    nl: bool = False        # parse the title as natural language


@router.post("/tasks")
def create_task(body: TaskBody, db: DbSession = Depends(get_db)):
    fields = dict(title=body.title, priority=body.priority, due_date=body.due_date,
                  parent_id=body.parent_id, tags=body.tags, repeat=body.repeat,
                  project=body.project, notes=body.notes)
    if body.nl:
        p = parse_task(body.title)
        fields["title"] = p["title"]
        fields["priority"] = max(body.priority, p["priority"])
        fields["due_date"] = body.due_date or p["due_date"]
        fields["repeat"] = body.repeat or p["repeat"]
        fields["tags"] = body.tags or p["tags"]
    t = Task(**fields)
    db.add(t); db.commit(); db.refresh(t)
    return _fmt(t)


class QuickBody(BaseModel):
    text: str
    project: str = ""


@router.post("/tasks/quick")
def quick_add(body: QuickBody, db: DbSession = Depends(get_db)):
    """natural-language quick add: 'pay rent every 1st !', 'call mom tomorrow #home'."""
    if not body.text.strip():
        raise HTTPException(400, "empty")
    p = parse_task(body.text)
    t = Task(title=p["title"], priority=p["priority"], due_date=p["due_date"],
             repeat=p["repeat"], tags=p["tags"], project=body.project)
    db.add(t); db.commit(); db.refresh(t)
    return _fmt(t)


@router.patch("/tasks/{tid}")
def update_task(tid: str, body: dict, db: DbSession = Depends(get_db)):
    t = db.get(Task, tid)
    if not t:
        raise HTTPException(404)
    spawned = None
    if body.get("done") and not t.done and t.repeat and t.due_date:
        # completing a recurring task rolls it forward to the next occurrence
        nxt = advance(t.due_date, t.repeat)
        if nxt:
            spawned = Task(title=t.title, priority=t.priority, due_date=nxt,
                           repeat=t.repeat, tags=t.tags, project=t.project, notes=t.notes,
                           parent_id=t.parent_id)
            db.add(spawned)
    for f in ("done", "title", "priority", "due_date", "tags", "repeat", "notes", "project", "sort_order", "parent_id"):
        if f in body:
            setattr(t, f, body[f])
    db.commit(); db.refresh(t)
    out = _fmt(t)
    if spawned:
        db.refresh(spawned)
        out["spawned"] = _fmt(spawned)
    return out


class Reorder(BaseModel):
    ids: list[str]


@router.post("/tasks/reorder")
def reorder(body: Reorder, db: DbSession = Depends(get_db)):
    for i, tid in enumerate(body.ids):
        t = db.get(Task, tid)
        if t:
            t.sort_order = i
    db.commit()
    return {"ok": True}


@router.delete("/tasks/{tid}")
def delete_task(tid: str, db: DbSession = Depends(get_db)):
    t = db.get(Task, tid)
    if not t:
        raise HTTPException(404)
    db.query(Task).filter(Task.parent_id == tid).delete()   # cascade subtasks
    db.delete(t); db.commit()
    return {"ok": True}
