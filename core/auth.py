import secrets, time
import bcrypt

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
