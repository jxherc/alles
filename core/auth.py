import secrets, time
import bcrypt
from fastapi import Request

# in-memory token store — survives process lifetime, not restarts
# that's fine: 30-day cookies re-login on restart
_tokens: dict[str, float] = {}   # token → expiry unix timestamp


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


def verify_session(token: str) -> bool:
    exp = _tokens.get(token)
    if not exp:
        return False
    if time.time() > exp:
        _tokens.pop(token, None)
        return False
    return True


def revoke_token(token: str):
    _tokens.pop(token, None)


# ── login throttle — slow down password brute-force from a single IP. matters
# the day alles sits behind a real domain; harmless on localhost. in-memory,
# resets on restart (which also clears any lockout).
_login_fails: dict[str, list[float]] = {}
_LOGIN_WINDOW = 300        # 5 minutes
_LOGIN_MAX_FAILS = 8       # failures in the window before we start blocking


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


def require_auth(request: Request):
    """FastAPI dependency for dangerous routes (shell exec etc.) — re-checks
    what TokenAuthMiddleware already enforces, so those endpoints stay locked
    even if the middleware is reordered or removed. Mirrors its semantics:
    a valid bearer token always passes; otherwise the session cookie is
    required only when AUTH_ENABLED is on."""
    from fastapi import HTTPException
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer aide_") or auth.startswith("Bearer alles_"):
        from routes.api_tokens import verify_token
        from core.database import SessionLocal
        db = SessionLocal()
        try:
            if verify_token(auth.split(" ", 1)[1], db):
                return
        finally:
            db.close()
        raise HTTPException(401, "invalid token")
    from core.settings import auth_enabled
    if auth_enabled() and not verify_session(request.cookies.get("aide_session", "")):
        raise HTTPException(401, "not authenticated")


# cross-subdomain SSO: a one-time short-lived code that hands a session to another
# subdomain (the Domain=localhost cookie won't share to *.localhost, so we relay).
_handoff: dict[str, tuple[float, str]] = {}   # code → (expiry, token)


def make_handoff(token: str, ttl: int = 30) -> str:
    code = secrets.token_urlsafe(24)
    _handoff[code] = (time.time() + ttl, token)
    return code


def redeem_handoff(code: str) -> str | None:
    v = _handoff.pop(code, None)   # single-use
    if not v:
        return None
    exp, token = v
    if time.time() > exp or not verify_session(token):
        return None
    return token
