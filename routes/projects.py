from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Project, Session

router = APIRouter(prefix="/api")


def _fmt(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "system_prompt": p.system_prompt,
        "color": p.color,
        "created_at": p.created_at.isoformat(),
        "session_count": len(p.sessions) if p.sessions else 0,
    }


@router.get("/projects")
def list_projects(db: DbSession = Depends(get_db)):
    return [_fmt(p) for p in db.query(Project).order_by(Project.created_at).all()]


class CreateProject(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = ""
    color: str = ""


@router.post("/projects")
def create_project(body: CreateProject, db: DbSession = Depends(get_db)):
    p = Project(name=body.name, description=body.description,
                system_prompt=body.system_prompt, color=body.color)
    db.add(p); db.commit(); db.refresh(p)
    return _fmt(p)


class PatchProject(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    color: str | None = None


@router.patch("/projects/{pid}")
def patch_project(pid: str, body: PatchProject, db: DbSession = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404)
    if body.name is not None:          p.name = body.name
    if body.description is not None:   p.description = body.description
    if body.system_prompt is not None: p.system_prompt = body.system_prompt
    if body.color is not None:         p.color = body.color
    db.commit()
    return _fmt(p)


@router.delete("/projects/{pid}")
def delete_project(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404)
    for s in list(p.sessions):
        s.project_id = None
    db.delete(p); db.commit()
    return {"ok": True}


@router.post("/projects/{pid}/sessions/{sid}")
def assign_session(pid: str, sid: str, db: DbSession = Depends(get_db)):
    p = db.get(Project, pid); s = db.get(Session, sid)
    if not p or not s: raise HTTPException(404)
    s.project_id = pid; db.commit()
    return {"ok": True}


@router.delete("/projects/{pid}/sessions/{sid}")
def unassign_session(pid: str, sid: str, db: DbSession = Depends(get_db)):
    s = db.get(Session, sid)
    if not s: raise HTTPException(404)
    if s.project_id == pid:
        s.project_id = None; db.commit()
    return {"ok": True}
