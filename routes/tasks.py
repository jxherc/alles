from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Task

router = APIRouter(prefix="/api")


def _fmt(t: Task) -> dict:
    return {
        "id":         t.id,
        "title":      t.title,
        "done":       t.done,
        "priority":   t.priority,
        "due_date":   t.due_date,
        "created_at": t.created_at.isoformat(),
    }


@router.get("/tasks")
def list_tasks(db: DbSession = Depends(get_db)):
    rows = db.query(Task).filter(Task.done == False).order_by(
        Task.priority.desc(), Task.created_at.asc()
    ).all()
    return [_fmt(t) for t in rows]


@router.get("/tasks/done")
def list_done(db: DbSession = Depends(get_db)):
    rows = db.query(Task).filter(Task.done == True).order_by(Task.created_at.desc()).limit(50).all()
    return [_fmt(t) for t in rows]


class TaskBody(BaseModel):
    title: str
    priority: int = 0   # 0 normal, 1 high
    due_date: Optional[str] = None


@router.post("/tasks")
def create_task(body: TaskBody, db: DbSession = Depends(get_db)):
    t = Task(title=body.title, priority=body.priority, due_date=body.due_date)
    db.add(t); db.commit(); db.refresh(t)
    return _fmt(t)


@router.patch("/tasks/{tid}")
def update_task(tid: str, body: dict, db: DbSession = Depends(get_db)):
    t = db.get(Task, tid)
    if not t: raise HTTPException(404)
    if "done" in body:     t.done = body["done"]
    if "title" in body:    t.title = body["title"]
    if "priority" in body: t.priority = body["priority"]
    db.commit(); return _fmt(t)


@router.delete("/tasks/{tid}")
def delete_task(tid: str, db: DbSession = Depends(get_db)):
    t = db.get(Task, tid)
    if not t: raise HTTPException(404)
    db.delete(t); db.commit()
    return {"ok": True}
