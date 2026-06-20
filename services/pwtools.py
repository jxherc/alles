"""
password generator + a lightweight strength estimator (entropy-based, no deps).
not zxcvbn, but it catches the obvious stuff: tiny charsets, common passwords,
repetition, and short length, and gives an honest entropy/score.
"""

import math
import re
import secrets
import string

# ambiguous-looking chars dropped so a generated password is easy to read/type
_LOWER = "abcdefghijkmnpqrstuvwxyz"
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_DIGIT = "23456789"
_SYM = "!@#$%^&*-_=+?"

COMMON = {
    "password",
    "passw0rd",
    "123456",
    "12345678",
    "qwerty",
    "letmein",
    "admin",
    "welcome",
    "iloveyou",
    "000000",
    "abc123",
    "monkey",
    "dragon",
    "football",
    "login",
    "starwars",
    "hello",
    "freedom",
    "whatever",
    "trustno1",
}


def generate_password(
    length=20, upper=True, lower=True, digits=True, symbols=True, avoid_ambiguous=True
) -> str:
    pools = []
    if lower:
        pools.append(_LOWER if avoid_ambiguous else string.ascii_lowercase)
    if upper:
        pools.append(_UPPER if avoid_ambiguous else string.ascii_uppercase)
    if digits:
        pools.append(_DIGIT if avoid_ambiguous else string.digits)
    if symbols:
        pools.append(_SYM)
    if not pools:
        pools.append(string.ascii_letters)
    length = max(4, min(128, int(length or 20)))
    alphabet = "".join(pools)
    # guarantee at least one char from every selected pool, then fill the rest
    chars = [secrets.choice(p) for p in pools]
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars[:length])


_LABELS = ["very weak", "weak", "fair", "strong", "very strong"]


def estimate_strength(pw: str) -> dict:
    if not pw:
        return {"score": 0, "entropy": 0.0, "label": "empty", "warning": "enter a password"}
    charset = 0
    if re.search(r"[a-z]", pw):
        charset += 26
    if re.search(r"[A-Z]", pw):
        charset += 26
    if re.search(r"\d", pw):
        charset += 10
    if re.search(r"[^a-zA-Z0-9]", pw):
        charset += 32
    entropy = len(pw) * math.log2(charset or 1)

    warning = ""
    low = pw.lower()
    if low in COMMON or low.strip(string.digits) in COMMON:
        entropy, warning = min(entropy, 10.0), "this is a commonly used password"
    elif len(set(pw)) <= 2:
        entropy, warning = min(entropy, 12.0), "too repetitive"
    elif re.search(r"(.)\1\1", pw):
        warning = "avoid repeated characters"
    elif re.search(r"(0123|1234|2345|3456|4567|5678|6789|abcd|qwer)", low):
        warning = "avoid sequences"

    score = 0
    for thr, sc in ((28, 1), (40, 2), (60, 3), (80, 4)):
        if entropy >= thr:
            score = sc
    return {
        "score": score,
        "entropy": round(entropy, 1),
        "label": _LABELS[score],
        "warning": warning,
    }


# ── payment-card helpers (vault card items) ──────────────────────────────────
def _digits(number: str) -> str:
    return "".join(ch for ch in str(number or "") if ch.isdigit())


def luhn_valid(number: str) -> bool:
    d = _digits(number)
    if len(d) < 12:
        return False
    total, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def card_brand(number: str) -> str:
    d = _digits(number)
    if d.startswith("4"):
        return "Visa"
    if d[:2] in ("34", "37"):
        return "Amex"
    if (d[:2].isdigit() and 51 <= int(d[:2] or 0) <= 55) or (
        d[:4].isdigit() and 2221 <= int(d[:4] or 0) <= 2720
    ):
        return "Mastercard"
    if d[:2] in ("60", "65") or d.startswith("6011"):
        return "Discover"
    return "Card"


def card_last4(number: str) -> str:
    return _digits(number)[-4:]


def mask_card(number: str) -> str:
    d = _digits(number)
    return ("•" * max(0, len(d) - 4)) + d[-4:] if d else ""


# ── TOTP (RFC 6238) + Watchtower (9a) ─────────────────────────────────────────
def _b32key(secret: str) -> bytes:
    import base64

    s = (secret or "").strip().replace(" ", "").upper()
    s += "=" * (-len(s) % 8)  # pad to a multiple of 8 for b32decode
    return base64.b32decode(s)


def totp_now(secret: str, period: int = 30, digits: int = 6, t: float | None = None) -> str:
    """RFC 6238 TOTP code. SHA1, configurable period/digits. no third-party dep."""
    import hashlib
    import hmac
    import struct
    import time

    if t is None:
        t = time.time()
    counter = int(t // period)
    h = hmac.new(_b32key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o : o + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def totp_remaining(period: int = 30, t: float | None = None) -> int:
    import time

    if t is None:
        t = time.time()
    return period - int(t % period)


def totp_secret(length: int = 32) -> str:
    """a fresh random base32 secret for a new authenticator-app enrolment."""
    import base64

    raw = secrets.token_bytes(length * 5 // 8 + 1)
    return base64.b32encode(raw).decode().rstrip("=")[:length]


def totp_verify(secret: str, code: str, period: int = 30, window: int = 1, t: float | None = None):
    """accept a code from the current step ±window (clock-skew tolerance). constant-ish compare."""
    import time

    if not (code or "").strip().isdigit():
        return False
    if t is None:
        t = time.time()
    code = code.strip()
    for off in range(-window, window + 1):
        if secrets.compare_digest(totp_now(secret, period=period, t=t + off * period), code):
            return True
    return False


def totp_uri(secret: str, label: str = "vault", issuer: str = "alles") -> str:
    """otpauth:// provisioning URI for QR enrolment."""
    from urllib.parse import quote

    return (
        f"otpauth://totp/{quote(issuer)}:{quote(label)}"
        f"?secret={secret}&issuer={quote(issuer)}&period=30&digits=6"
    )


def is_weak(pw: str) -> bool:
    return estimate_strength(pw or "")["score"] <= 1


def find_reused(entries: list[dict]) -> list[list[str]]:
    """entries = [{id, password}] → groups of ids that share a (non-empty) password."""
    by_pw: dict[str, list[str]] = {}
    for e in entries:
        pw = (e.get("password") or "").strip()
        if pw:
            by_pw.setdefault(pw, []).append(e["id"])
    return [ids for ids in by_pw.values() if len(ids) >= 2]


def breach_count(password: str, fetch) -> int:
    """HIBP k-anonymity: SHA1 the password, send the first 5 hex chars to `fetch(prefix)`,
    match the suffix in the returned 'SUFFIX:count' lines. the full password never leaves."""
    import hashlib

    if not password:
        return 0
    sha = hashlib.sha1(password.encode()).hexdigest().upper()
    prefix, suffix = sha[:5], sha[5:]
    try:
        text = fetch(prefix) or ""
    except Exception:
        return 0
    for line in text.splitlines():
        parts = line.strip().split(":")
        if len(parts) == 2 and parts[0].strip().upper() == suffix:
            try:
                return int(parts[1])
            except ValueError:
                return 0
    return 0
