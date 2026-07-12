"""generic read-only share/publish primitive (1a).

a Share row maps a token -> (kind, ref). sessions keep their own share_token
column for back-compat; this covers doc/file/photo and (later) album/contact/event.
helpers take an open db session so routes pass Depends(get_db) and tests pass self.db().
"""

import hashlib
import hmac
import html as _html
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import object_session

from core.auth import hash_password, verify_password
from core.database import Share

VALID_KINDS = {"doc", "file", "folder", "photo", "album", "contact", "event", "session", "persona"}


GRANT_SECONDS = 60 * 60
_LEGACY_BCRYPT_PREFIX = "legacy-bcrypt:"
_V2_BCRYPT_PREFIX = "v2-bcrypt:"
_grants: dict[str, tuple[str, str, float]] = {}
_grant_lock = threading.Lock()


def _legacy_pw_hash(pw: str) -> str:
    return hashlib.sha256(("alles-share:" + pw).encode()).hexdigest() if pw else ""


def _pw_material(pw: str) -> str:
    return hashlib.sha256(("alles-share-v2:" + pw).encode()).hexdigest()


def _legacy_wrapped_material(digest: str) -> str:
    return hashlib.sha256(("alles-share-legacy:" + digest.lower()).encode()).hexdigest()


def _pw_hash(pw: str | None) -> str:
    if not pw:
        return ""
    if len(pw) > 1024:
        raise ValueError("share password is too long")
    return _V2_BCRYPT_PREFIX + hash_password(_pw_material(pw))


def _is_legacy_hash(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _is_wrapped_legacy_hash(value: str) -> bool:
    return value.startswith(_LEGACY_BCRYPT_PREFIX)


def _needs_password_upgrade(value: str) -> bool:
    return _is_legacy_hash(value) or _is_wrapped_legacy_hash(value)


def _norm(kind, ref):
    return (kind or "").strip().lower(), (ref or "").strip()


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_expiry(value) -> str:
    if value is None or not str(value).strip():
        return ""
    try:
        parsed = _parse_time(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("share expiry must be a valid ISO date and time") from exc
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def mint(db, kind, ref, level="view", *, expires_at=None, password=None):
    kind, ref = _norm(kind, ref)
    if kind not in VALID_KINDS:
        raise ValueError(f"bad kind: {kind!r}")
    if not ref:
        raise ValueError("empty ref")
    level = "download" if level == "download" else "view"
    s = db.query(Share).filter_by(kind=kind, ref=ref).first()
    if s:
        s.level = level  # idempotent, but refresh level/expiry/password
        if expires_at is not None:
            s.expires_at = normalize_expiry(expires_at)
        if password is not None:
            s.password_hash = _pw_hash(password)
            revoke_grants(s.token)
        db.commit()
        return s
    s = Share(
        token=uuid.uuid4().hex,
        kind=kind,
        ref=ref,
        level=level,
        expires_at=normalize_expiry(expires_at),
        password_hash=_pw_hash(password),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def is_expired(share, now=None):
    exp = (getattr(share, "expires_at", "") or "").strip()
    if not exp:
        return False
    try:
        expiry = _parse_time(exp)
        current = _parse_time(now) if now is not None else datetime.now(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return True
    return current >= expiry


def check_password(share, pw):
    h = getattr(share, "password_hash", "") or ""
    if not h:
        return True  # open share
    candidate = pw or ""
    if len(candidate) > 1024:
        return False
    if _is_legacy_hash(h):
        return hmac.compare_digest(_legacy_pw_hash(candidate), h)
    if _is_wrapped_legacy_hash(h):
        return verify_password(
            _legacy_wrapped_material(_legacy_pw_hash(candidate)),
            h.removeprefix(_LEGACY_BCRYPT_PREFIX),
        )
    if h.startswith(_V2_BCRYPT_PREFIX):
        return verify_password(_pw_material(candidate), h.removeprefix(_V2_BCRYPT_PREFIX))
    return verify_password(_pw_material(candidate), h)


def upgrade_password_hash(share, pw: str, db=None) -> bool:
    """Replace a verified legacy SHA-256 share password with bcrypt."""
    current = getattr(share, "password_hash", "") or ""
    if not _needs_password_upgrade(current):
        return True
    if not check_password(share, pw):
        return False
    session = db or object_session(share)
    if session is None:
        return False
    replacement = _pw_hash(pw)
    result = session.execute(
        update(Share)
        .where(Share.id == share.id, Share.password_hash == current)
        .values(password_hash=replacement)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    session.refresh(share)
    return result.rowcount == 1


def new_grant(token: str, password_hash: str, *, now: float | None = None) -> str:
    current = time.monotonic() if now is None else now
    grant = secrets.token_urlsafe(24)
    with _grant_lock:
        if len(_grants) >= 4096:
            expired = [key for key, (_, _, expiry) in _grants.items() if expiry <= current]
            for key in expired:
                _grants.pop(key, None)
            if len(_grants) >= 4096:
                oldest = min(_grants, key=lambda key: _grants[key][2])
                _grants.pop(oldest, None)
        _grants[grant] = (token, password_hash, current + GRANT_SECONDS)
    return grant


def check_grant(token: str, password_hash: str, grant: str, *, now: float | None = None) -> bool:
    if not grant:
        return False
    current = time.monotonic() if now is None else now
    with _grant_lock:
        record = _grants.get(grant)
        if not record:
            return False
        expected_token, expected_hash, expiry = record
        if expiry <= current:
            _grants.pop(grant, None)
            return False
        return hmac.compare_digest(expected_token, token) and hmac.compare_digest(
            expected_hash, password_hash
        )


def revoke_grants(token: str) -> None:
    with _grant_lock:
        stale = [grant for grant, (share_token, _, _) in _grants.items() if share_token == token]
        for grant in stale:
            _grants.pop(grant, None)


def resolve(db, token, password="", *, now=None):
    """the share for a token only if it's live (not expired) and the password (if any) matches."""
    s = lookup(db, token)
    if not s or is_expired(s, now) or not check_password(s, password):
        return None
    if not upgrade_password_hash(s, password, db):
        return None
    return s


def lookup(db, token):
    if not token:
        return None
    return db.query(Share).filter_by(token=token).first()


def token_for(db, kind, ref):
    kind, ref = _norm(kind, ref)
    s = db.query(Share).filter_by(kind=kind, ref=ref).first()
    return s.token if s else None


def revoke(db, token):
    s = db.query(Share).filter_by(token=token).first()
    if not s:
        return False
    revoke_grants(s.token)
    db.delete(s)
    db.commit()
    return True


def revoke_ref(db, kind, ref):
    kind, ref = _norm(kind, ref)
    s = db.query(Share).filter_by(kind=kind, ref=ref).first()
    if not s:
        return False
    revoke_grants(s.token)
    db.delete(s)
    db.commit()
    return True


def _inline(s):
    # s is already html-escaped; layer inline md on top
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\s][^*]*)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" rel="noopener nofollow" target="_blank">\1</a>',
        s,
    )
    return s


def md_to_html(text):
    """tiny dependency-free markdown -> html for the public read-only viewer.
    headings, bold/italic, inline + fenced code, links, ul/ol, paragraphs.
    not a full renderer — 3c (publish->site) can enrich it."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out = []
    in_ul = in_ol = False
    i = 0

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    while i < len(lines):
        ln = lines[i]
        st = ln.strip()
        if st.startswith("```"):
            close_lists()
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(_html.escape(lines[i]))
                i += 1
            i += 1  # skip closing fence
            out.append("<pre><code>" + "\n".join(code) + "</code></pre>")
            continue
        if not st:
            close_lists()
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            close_lists()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(_html.escape(m.group(2)))}</h{lvl}>")
            i += 1
            continue
        m = re.match(r"^[-*+]\s+(.*)$", st)
        if m:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(_html.escape(m.group(1)))}</li>")
            i += 1
            continue
        m = re.match(r"^\d+\.\s+(.*)$", st)
        if m:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline(_html.escape(m.group(1)))}</li>")
            i += 1
            continue
        # paragraph: gather consecutive plain lines
        close_lists()
        para = [ln]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or re.match(r"^(#{1,6}\s|[-*+]\s|\d+\.\s|```)", nxt):
                break
            para.append(lines[i])
            i += 1
        out.append("<p>" + "<br>".join(_inline(_html.escape(p)) for p in para) + "</p>")
    close_lists()
    return "\n".join(out)
