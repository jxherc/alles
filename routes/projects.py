from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import Project, Session, get_db
from services.project_environment import canonical_folder, folder_state

router = APIRouter(prefix="/api")


def _fmt(p: Project) -> dict:
    state = folder_state(p.working_dir)
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "system_prompt": p.system_prompt,
        "working_dir": p.working_dir,
        "folder_state": state,
        "relink_required": state != "available",
        "scratchpad": p.scratchpad or "",
        "color": p.color,
        "created_at": p.created_at.isoformat(),
        "last_opened_at": p.last_opened_at.isoformat() if p.last_opened_at else None,
        "session_count": len(p.sessions) if p.sessions else 0,
    }


def _normalize_folder(value: str, *, must_exist: bool) -> str:
    try:
        return canonical_folder(value, must_exist=must_exist)
    except ValueError as exc:
        code = str(exc)
        messages = {
            "project_folder_must_be_absolute": "choose an absolute server folder path",
            "project_folder_unavailable": "the selected server folder is unavailable",
            "project_folder_is_filesystem_root": "the filesystem root cannot be a Project",
        }
        raise ApiError(400, code, messages.get(code, "invalid Project folder")) from exc


@router.get("/projects")
def list_projects(db: DbSession = Depends(get_db)):
    return [_fmt(p) for p in db.query(Project).order_by(Project.created_at).all()]


class CreateProject(BaseModel):
    name: str = ""
    description: str = ""
    system_prompt: str = ""
    working_dir: str = ""
    scratchpad: str = ""
    color: str = ""


@router.post("/projects")
def create_project(body: CreateProject, request: Request, db: DbSession = Depends(get_db)):
    working_dir = ""
    if body.working_dir.strip():
        require_recent_owner(request)
        working_dir = _normalize_folder(body.working_dir, must_exist=True)
    name = body.name.strip() or (Path(working_dir).name if working_dir else "new project")
    p = Project(
        name=name,
        description=body.description,
        system_prompt=body.system_prompt,
        working_dir=working_dir,
        scratchpad=body.scratchpad,
        color=body.color,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _fmt(p)


class PatchProject(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    working_dir: str | None = None
    scratchpad: str | None = None
    color: str | None = None


@router.get("/projects/general")
def general_environment():
    return {
        "id": "general",
        "name": "General",
        "kind": "general",
        "working_dir": "",
        "folder_state": "none",
        "relink_required": False,
    }


@router.get("/projects/{pid}")
def get_project(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404)
    return _fmt(p)


@router.patch("/projects/{pid}")
def patch_project(pid: str, body: PatchProject, request: Request, db: DbSession = Depends(get_db)):
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404)
    if body.name is not None:
        p.name = body.name
    if body.description is not None:
        p.description = body.description
    if body.system_prompt is not None:
        p.system_prompt = body.system_prompt
    if body.working_dir is not None:
        require_recent_owner(request)
        p.working_dir = (
            _normalize_folder(body.working_dir, must_exist=True) if body.working_dir.strip() else ""
        )
    if body.scratchpad is not None:
        p.scratchpad = body.scratchpad
    if body.color is not None:
        p.color = body.color
    db.commit()
    return _fmt(p)


class RelinkProject(BaseModel):
    working_dir: str


@router.post("/projects/{pid}/relink")
def relink_project(
    pid: str,
    body: RelinkProject,
    request: Request,
    db: DbSession = Depends(get_db),
):
    require_recent_owner(request)
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404)
    p.working_dir = _normalize_folder(body.working_dir, must_exist=True)
    db.commit()
    db.refresh(p)
    return _fmt(p)


@router.post("/projects/{pid}/open")
def open_project(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404)
    p.last_opened_at = datetime.now()
    db.commit()
    db.refresh(p)
    return _fmt(p)


@router.get("/projects/{pid}/files")
def project_files(pid: str, db: DbSession = Depends(get_db)):
    """the files under the project's working dir — the 'sources' for its workspace page."""
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404)
    wd = (p.working_dir or "").strip()
    state = folder_state(wd)
    if state != "available":
        return {"files": [], "working_dir": wd, "folder_state": state}
    from services.agent_tools import workspace_files

    try:
        files = workspace_files(wd, "", 200)
    except Exception:
        files = []
    return {"files": files, "working_dir": wd, "folder_state": state}


@router.delete("/projects/{pid}")
def delete_project(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404)
    for s in list(p.sessions):
        s.project_id = None
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/projects/{pid}/sessions/{sid}")
def assign_session(pid: str, sid: str, db: DbSession = Depends(get_db)):
    p = db.get(Project, pid)
    s = db.get(Session, sid)
    if not p or not s:
        raise HTTPException(404)
    s.project_id = pid
    db.commit()
    return {"ok": True}


@router.delete("/projects/{pid}/sessions/{sid}")
def unassign_session(pid: str, sid: str, db: DbSession = Depends(get_db)):
    s = db.get(Session, sid)
    if not s:
        raise HTTPException(404)
    if s.project_id == pid:
        s.project_id = None
        db.commit()
    return {"ok": True}
