from pathlib import Path
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
        "temperature": p.temperature, "default_mode": p.default_mode,
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
    temperature: Optional[float] = None
    default_mode: str = ""
    is_default: bool = False

@router.post("/personas")
def create_persona(body: PersonaBody, db: DbSession = Depends(get_db)):
    if body.is_default:
        db.query(Persona).update({Persona.is_default: False})
    p = Persona(**body.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return _fmt(p)

class PersonaPatch(BaseModel):
    # all optional — only fields actually sent get touched, so editing the prompt
    # doesn't silently wipe model/default
    name: Optional[str] = None
    emoji: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    default_mode: Optional[str] = None
    is_default: Optional[bool] = None

@router.patch("/personas/{pid}")
def update_persona(pid: str, body: PersonaPatch, db: DbSession = Depends(get_db)):
    p = db.get(Persona, pid)
    if not p: raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    if data.get("is_default"):
        db.query(Persona).filter(Persona.id != pid).update({Persona.is_default: False})
    for k, v in data.items():
        setattr(p, k, v)
    db.commit(); return _fmt(p)

@router.post("/personas/{pid}/duplicate")
def duplicate_persona(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Persona, pid)
    if not p: raise HTTPException(404)
    dup = Persona(name=f"{p.name} copy", emoji=p.emoji,
                  system_prompt=p.system_prompt, model=p.model,
                  temperature=p.temperature, default_mode=p.default_mode, is_default=False)
    db.add(dup); db.commit(); db.refresh(dup)
    return _fmt(dup)

@router.delete("/personas/{pid}")
def delete_persona(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Persona, pid)
    if not p: raise HTTPException(404)
    db.delete(p); db.commit()
    return {"ok": True}


# ── starter personas (seeded once on first boot so the picker isn't empty) ──────
_SEED_SENTINEL = Path(__file__).resolve().parent.parent / "data" / ".personas_seeded"

_STARTERS = [
    ("aide", "🌀", "You are aide — a sharp, friendly general assistant. Be concise, "
     "get to the point, and just do the thing instead of narrating that you'll do it.", True),
    ("coder", "🧑‍💻", "You are a senior engineer. Working code first, terse explanation after. "
     "Prefer the simplest thing that works. Flag real bugs and edge cases; skip the obvious caveats.", False),
    ("brainstorm", "💡", "You are a fast idea generator. Reply with a numbered list of distinct, "
     "concrete options — genuinely different angles, not five flavors of the same idea. Push past the obvious.", False),
    ("editor", "✏️", "You are a ruthless copy editor. Tighten prose, cut filler, keep the author's voice. "
     "Return the edited text first, then a short list of what you changed and why.", False),
    ("tutor", "📚", "You are a patient tutor. Explain from first principles, use a concrete example "
     "before the abstract rule, and end by checking understanding with one quick question.", False),
]


def seed_default_personas() -> int:
    """write the starter personas once. a sentinel file means deleting them sticks."""
    if _SEED_SENTINEL.exists():
        return 0
    from core.database import SessionLocal
    db = SessionLocal()
    n = 0
    try:
        if db.query(Persona).count() == 0:
            for name, emoji, prompt, is_def in _STARTERS:
                db.add(Persona(name=name, emoji=emoji, system_prompt=prompt, is_default=is_def))
                n += 1
            db.commit()
    finally:
        db.close()
    try:
        _SEED_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        _SEED_SENTINEL.write_text("1")
    except Exception:
        pass
    return n
