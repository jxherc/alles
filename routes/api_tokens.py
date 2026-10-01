import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_tokens import hash_token, normalize_scopes, token_scopes
from core.auth import require_recent_owner
from core.database import ApiToken, get_db

router = APIRouter(prefix="/api")


def _fmt(token: ApiToken, raw: str = "") -> dict:
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.prefix,
        "scopes": list(token_scopes(token)),
        "created_at": token.created_at.isoformat(),
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
        **({"token": raw} if raw else {}),
    }


@router.get("/tokens")
def list_tokens(db: DbSession = Depends(get_db)):
    return [_fmt(token) for token in db.query(ApiToken).order_by(ApiToken.created_at.desc()).all()]


class TokenBody(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=lambda: ["read"])


@router.post("/tokens", dependencies=[Depends(require_recent_owner)])
def create_token(body: TokenBody, db: DbSession = Depends(get_db)):
    scopes = normalize_scopes(body.scopes)
    raw = "alles_" + secrets.token_urlsafe(32)
    token = ApiToken(
        name=body.name,
        token_hash=hash_token(raw),
        prefix=raw[:12],
        scopes=json.dumps(scopes),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return _fmt(token, raw)


@router.delete("/tokens/{tid}", dependencies=[Depends(require_recent_owner)])
def delete_token(tid: str, db: DbSession = Depends(get_db)):
    token = db.get(ApiToken, tid)
    if not token:
        raise HTTPException(404)
    db.delete(token)
    db.commit()
    return {"ok": True}
