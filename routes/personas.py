from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Persona

router = APIRouter(prefix="/api")

def _fmt(p: Persona) -> dict:
    return {
        "id": p.id, "name": p.name, "emoji": p.emoji,
        "system_prompt": p.system_prompt, "model": p.model,
        "is_default": p.is_default,
        "created_at": p.created_at.isoformat(),
    }

@router.get("/personas")
def list_personas(db: DbSession = Depends(get_db)):
    return [_fmt(p) for p in db.query(Persona).order_by(Persona.name).all()]

class PersonaBody(BaseModel):
    name: str
    emoji: str = ""
    system_prompt: str = ""
    model: str = ""
    is_default: bool = False

@router.post("/personas")
def create_persona(body: PersonaBody, db: DbSession = Depends(get_db)):
    if body.is_default:
        db.query(Persona).update({Persona.is_default: False})
    p = Persona(**body.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return _fmt(p)

@router.patch("/personas/{pid}")
def update_persona(pid: str, body: PersonaBody, db: DbSession = Depends(get_db)):
    p = db.get(Persona, pid)
    if not p: raise HTTPException(404)
    if body.is_default:
        db.query(Persona).filter(Persona.id != pid).update({Persona.is_default: False})
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit(); return _fmt(p)

@router.delete("/personas/{pid}")
def delete_persona(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Persona, pid)
    if not p: raise HTTPException(404)
    db.delete(p); db.commit()
    return {"ok": True}
