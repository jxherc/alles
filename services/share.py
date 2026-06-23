"""generic read-only share/publish primitive (1a).

a Share row maps a token -> (kind, ref). sessions keep their own share_token
column for back-compat; this covers doc/file/photo and (later) album/contact/event.
helpers take an open db session so routes pass Depends(get_db) and tests pass self.db().
"""

import hashlib
import html as _html
import re
import uuid
from datetime import datetime

from core.database import Share

VALID_KINDS = {"doc", "file", "folder", "photo", "album", "contact", "event", "session", "persona"}


def _pw_hash(pw):
    return hashlib.sha256(("alles-share:" + pw).encode()).hexdigest() if pw else ""


def _norm(kind, ref):
    return (kind or "").strip().lower(), (ref or "").strip()


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
            s.expires_at = expires_at or ""
        if password is not None:
            s.password_hash = _pw_hash(password)
        db.commit()
        return s
    s = Share(
        token=uuid.uuid4().hex,
        kind=kind,
        ref=ref,
        level=level,
        expires_at=expires_at or "",
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
    now = now or datetime.utcnow().isoformat()
    return now >= exp


def check_password(share, pw):
    h = getattr(share, "password_hash", "") or ""
    if not h:
        return True  # open share
    return _pw_hash(pw or "") == h


def resolve(db, token, password="", *, now=None):
    """the share for a token only if it's live (not expired) and the password (if any) matches."""
    s = lookup(db, token)
    if not s or is_expired(s, now) or not check_password(s, password):
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
    db.delete(s)
    db.commit()
    return True


def revoke_ref(db, kind, ref):
    kind, ref = _norm(kind, ref)
    s = db.query(Share).filter_by(kind=kind, ref=ref).first()
    if not s:
        return False
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
