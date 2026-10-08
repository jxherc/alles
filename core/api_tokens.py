"""Persisted API token rules shared by middleware and route dependencies."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.database import ApiToken

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


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def token_scopes(token: ApiToken) -> tuple[str, ...]:
    try:
        values = json.loads(token.scopes or "[]")
    except (TypeError, ValueError):
        return ()
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if value in KNOWN_SCOPES)


def normalize_scopes(values: list[str]) -> tuple[str, ...]:
    if not values:
        raise ApiError(400, "invalid_token_scopes", "choose at least one token scope")
    unknown = sorted({value for value in values if value not in KNOWN_SCOPES})
    if unknown:
        raise ApiError(
            400,
            "invalid_token_scopes",
            f"unknown token scope: {', '.join(unknown)}",
        )
    return tuple(scope for scope in KNOWN_SCOPES if scope in values)


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
    token = db.query(ApiToken).filter(ApiToken.token_hash == hash_token(raw)).first()
    if not token:
        return "invalid"
    scopes = token_scopes(token)
    if scope not in scopes and "admin" not in scopes:
        return "forbidden"
    token.last_used_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return "ok"


def verify_token(raw: str, db: DbSession, required_scope: str = "read") -> bool:
    return token_access(raw, db, required_scope) == "ok"
