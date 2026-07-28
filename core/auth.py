import secrets
import time
from copy import deepcopy
from threading import RLock

import bcrypt
from fastapi import Request
from starlette.requests import HTTPConnection

# in-memory token store — survives process lifetime, not restarts
# that's fine: 30-day cookies re-login on restart
_tokens: dict[str, float] = {}  # token → expiry unix timestamp
_recent_auth: dict[str, float] = {}  # token → last password confirmation
RECENT_AUTH_SECONDS = 10 * 60
MIN_OWNER_PASSWORD_LENGTH = 12


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def store_token(token: str, ttl_days: int = 30):
    _tokens[token] = time.time() + ttl_days * 86400
    _recent_auth[token] = time.time()


def verify_session(token: str) -> bool:
    exp = _tokens.get(token)
    if not exp:
        return False
    if time.time() > exp:
        _tokens.pop(token, None)
        _recent_auth.pop(token, None)
        return False
    return True


def revoke_token(token: str):
    _tokens.pop(token, None)
    _recent_auth.pop(token, None)


def mark_session_recent(token: str) -> bool:
    if not verify_session(token):
        return False
    _recent_auth[token] = time.time()
    return True


def verify_recent_session(token: str, max_age: int = RECENT_AUTH_SECONDS) -> bool:
    if not verify_session(token):
        return False
    confirmed_at = _recent_auth.get(token)
    age = time.time() - confirmed_at if confirmed_at is not None else -1
    return confirmed_at is not None and 0 <= age <= max_age


# ── login throttle — slow down password brute-force from a single IP. matters
# the day alles sits behind a real domain; harmless on localhost. in-memory,
# resets on restart (which also clears any lockout).
_login_fails: dict[str, list[float]] = {}
_LOGIN_WINDOW = 300  # 5 minutes
_LOGIN_MAX_FAILS = 8  # failures in the window before we start blocking


def login_blocked(ip: str) -> bool:
    now = time.time()
    fails = [t for t in _login_fails.get(ip, []) if now - t < _LOGIN_WINDOW]
    if fails:
        _login_fails[ip] = fails
    else:
        _login_fails.pop(ip, None)
    return len(fails) >= _LOGIN_MAX_FAILS


def record_login_fail(ip: str):
    _login_fails.setdefault(ip, []).append(time.time())


def clear_login_fails(ip: str):
    _login_fails.pop(ip, None)


def require_auth(request: HTTPConnection):
    """FastAPI dependency for dangerous routes (shell exec etc.) — re-checks
    what TokenAuthMiddleware already enforces, so those endpoints stay locked
    even if the middleware is reordered or removed. Mirrors its semantics:
    a valid bearer token always passes; otherwise the session cookie is
    required only when AUTH_ENABLED is on."""
    from fastapi import HTTPException

    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer aide_") or auth.startswith("Bearer alles_"):
        from core.database import SessionLocal
        from routes.api_tokens import verify_token

        db = SessionLocal()
        try:
            if verify_token(auth.split(" ", 1)[1], db, required_scope="admin"):
                return
        finally:
            db.close()
        raise HTTPException(401, "invalid token")
    from core.settings import auth_enabled

    if auth_enabled() and not verify_session(request.cookies.get("aide_session", "")):
        raise HTTPException(401, "not authenticated")


def require_recent_owner(request: Request):
    """Require a recent password confirmation for high-impact owner actions."""
    from core.api_errors import ApiError
    from core.rate_limit import enforce_rate_limit
    from core.settings import auth_enabled

    if not auth_enabled():
        return
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        raise ApiError(403, "recent_auth_required", "recent owner authentication required")
    enforce_rate_limit(
        request,
        f"owner:{request.method}:{request.url.path}",
        limit=30,
        window_seconds=60,
    )
    token = request.cookies.get("aide_session", "")
    if not verify_recent_session(token):
        raise ApiError(403, "recent_auth_required", "recent owner authentication required")


# cross-subdomain SSO: a one-time short-lived code that hands a session to another
# subdomain (the Domain=localhost cookie won't share to *.localhost, so we relay).
_handoff: dict[str, tuple[float, str]] = {}  # code → (expiry, token)
_context_handoff: dict[str, tuple[float, str, dict]] = {}
_context_handoff_lock = RLock()
_CONTEXT_HANDOFF_MAX = 256


def _prune_context_handoffs(now: float | None = None, *, reserve: int = 0) -> None:
    with _context_handoff_lock:
        now = time.time() if now is None else now
        for code, value in list(_context_handoff.items()):
            if value[0] <= now:
                _context_handoff.pop(code, None)
        capacity = max(0, _CONTEXT_HANDOFF_MAX - max(0, reserve))
        overflow = len(_context_handoff) - capacity
        if overflow <= 0:
            return
        oldest = sorted(_context_handoff, key=lambda code: _context_handoff[code][0])
        for code in oldest[:overflow]:
            _context_handoff.pop(code, None)


def make_handoff(token: str, ttl: int = 30) -> str:
    code = secrets.token_urlsafe(24)
    _handoff[code] = (time.time() + ttl, token)
    return code


def redeem_handoff(code: str) -> str | None:
    v = _handoff.pop(code, None)  # single-use
    if not v:
        return None
    exp, token = v
    if time.time() > exp or not verify_session(token):
        return None
    return token


def make_context_handoff(token: str, payload: dict, ttl: int = 30) -> str:
    """Store private cross-subdomain context behind an opaque, short-lived code."""
    with _context_handoff_lock:
        now = time.time()
        _prune_context_handoffs(now, reserve=1)
        code = secrets.token_urlsafe(24)
        _context_handoff[code] = (now + ttl, token, deepcopy(payload))
        return code


def redeem_context_handoff(code: str, token: str) -> dict | None:
    with _context_handoff_lock:
        now = time.time()
        _prune_context_handoffs(now)
        value = _context_handoff.get(code)
        if not value:
            return None
        expiry, owner_token, payload = value
        if now > expiry:
            _context_handoff.pop(code, None)
            return None
        if not secrets.compare_digest(owner_token, token):
            return None
        if owner_token and not verify_session(owner_token):
            _context_handoff.pop(code, None)
            return None
        _context_handoff.pop(code, None)
        return deepcopy(payload)
