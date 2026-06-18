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
