from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, SessionTemplate

router = APIRouter(prefix="/api")


def _fmt(t: SessionTemplate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "system_prompt": t.system_prompt,
        "initial_message": t.initial_message,
        "created_at": t.created_at.isoformat(),
    }


class TemplateCreate(BaseModel):
    name: str
    system_prompt: str = ""
    initial_message: str = ""


@router.get("/templates")
def list_templates(db: DbSession = Depends(get_db)):
    return [_fmt(t) for t in db.query(SessionTemplate).order_by(SessionTemplate.created_at.desc()).all()]


@router.post("/templates")
def create_template(body: TemplateCreate, db: DbSession = Depends(get_db)):
    t = SessionTemplate(name=body.name, system_prompt=body.system_prompt, initial_message=body.initial_message)
    db.add(t); db.commit(); db.refresh(t)
    return _fmt(t)


@router.delete("/templates/{tid}")
def delete_template(tid: str, db: DbSession = Depends(get_db)):
    t = db.get(SessionTemplate, tid)
    if not t:
        raise HTTPException(404, "not found")
    db.delete(t); db.commit()
    return {"ok": True}
