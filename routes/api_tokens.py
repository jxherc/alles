import hashlib
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.auth import require_recent_owner
from core.database import ApiToken, get_db

router = APIRouter(prefix="/api")

KNOWN_SCOPES = (
    "read",
    "write",
    "models",
    "agent",
    "secrets",
    "connections",
    "admin",
)
_ADMIN_PREFIXES = (
    "/api/tokens",
    "/api/settings",
    "/api/backup",
    "/api/system",
    "/api/auth",
    "/api/macos",
)
_MODEL_PREFIXES = (
    "/v1/",
    "/api/chat",
    "/api/models",
    "/api/research",
    "/api/images",
    "/api/voice",
    "/api/local-models",
)
_AGENT_PREFIXES = ("/api/agent", "/api/mcp/rpc", "/api/mcp/call")
_SECRET_PREFIXES = ("/api/vault",)
_CONNECTION_PREFIXES = ("/api/connections", "/api/mcp", "/api/caldav", "/api/carddav")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token_scopes(token: ApiToken) -> tuple[str, ...]:
    try:
        values = json.loads(token.scopes or "[]")
    except (TypeError, ValueError):
        return ()
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if value in KNOWN_SCOPES)


def _normalize_scopes(values: list[str]) -> tuple[str, ...]:
    if not values:
        raise HTTPException(400, "choose at least one token scope")
    unknown = sorted({value for value in values if value not in KNOWN_SCOPES})
    if unknown:
        raise HTTPException(400, f"unknown token scope: {', '.join(unknown)}")
    return tuple(scope for scope in KNOWN_SCOPES if scope in values)


def _fmt(token: ApiToken, raw: str = "") -> dict:
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.prefix,
        "scopes": list(_token_scopes(token)),
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
    scopes = _normalize_scopes(body.scopes)
    raw = "alles_" + secrets.token_urlsafe(32)
    token = ApiToken(
        name=body.name,
        token_hash=_hash(raw),
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


def required_scope(method: str, path: str) -> str:
    if any(path.startswith(prefix) for prefix in _ADMIN_PREFIXES):
        return "admin"
    if any(path.startswith(prefix) for prefix in _AGENT_PREFIXES):
        return "agent"
    if any(path.startswith(prefix) for prefix in _SECRET_PREFIXES):
        return "secrets"
    if any(path.startswith(prefix) for prefix in _CONNECTION_PREFIXES):
        return "connections"
    if any(path.startswith(prefix) for prefix in _MODEL_PREFIXES):
        return "models"
    return "read" if method.upper() in {"GET", "HEAD", "OPTIONS"} else "write"


def token_access(raw: str, db: DbSession, scope: str) -> str:
    token = db.query(ApiToken).filter(ApiToken.token_hash == _hash(raw)).first()
    if not token:
        return "invalid"
    scopes = _token_scopes(token)
    if scope not in scopes and "admin" not in scopes:
        return "forbidden"
    token.last_used_at = datetime.utcnow()
    db.commit()
    return "ok"


def verify_token(raw: str, db: DbSession, required_scope: str = "read") -> bool:
    return token_access(raw, db, required_scope) == "ok"
