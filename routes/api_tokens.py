import secrets, hashlib
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, ApiToken
from datetime import datetime

router = APIRouter(prefix="/api")

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def _fmt(t: ApiToken, raw: str = "") -> dict:
    return {
        "id": t.id, "name": t.name, "prefix": t.prefix,
        "created_at": t.created_at.isoformat(),
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        **({"token": raw} if raw else {}),  # only shown once on creation
    }

@router.get("/tokens")
def list_tokens(db: DbSession = Depends(get_db)):
    return [_fmt(t) for t in db.query(ApiToken).order_by(ApiToken.created_at.desc()).all()]

class TokenBody(BaseModel):
    name: str

@router.post("/tokens")
def create_token(body: TokenBody, db: DbSession = Depends(get_db)):
    raw = "alles_" + secrets.token_urlsafe(32)
    t = ApiToken(name=body.name, token_hash=_hash(raw), prefix=raw[:12])
    db.add(t); db.commit(); db.refresh(t)
    return _fmt(t, raw)   # raw shown only here

@router.delete("/tokens/{tid}")
def delete_token(tid: str, db: DbSession = Depends(get_db)):
    t = db.get(ApiToken, tid)
    if not t: raise HTTPException(404)
    db.delete(t); db.commit()
    return {"ok": True}


def verify_token(raw: str, db) -> bool:
    h = _hash(raw)
    t = db.query(ApiToken).filter(ApiToken.token_hash == h).first()
    if not t: return False
    t.last_used_at = datetime.utcnow()
    db.commit()
    return True
