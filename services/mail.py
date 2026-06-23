"""
Mail client - IMAP fetch + SMTP send over Python stdlib.

Kept small but tuned for slow links (the usual mail complaint): reuse live IMAP
sessions, cache short-lived list/body reads, fetch the inbox by sequence range
instead of SEARCH ALL, make the background poll skip the full re-fetch when the
mailbox tip hasn't moved, and read a message by pulling ONLY its text/html body
parts (never the attachments) instead of the whole RFC822 blob.
"""

import base64
import email
import email.utils
import imaplib
import quopri
import re
import smtplib
import threading
import time
from email.header import decode_header, make_header
from email.message import EmailMessage

_IMAP_TIMEOUT = 12
_POOL_IDLE = 60.0
_LIST_TTL = 10.0
_MESSAGE_TTL = 10 * 60.0
_POOL = {}
_LIST_CACHE = {}
_MESSAGE_CACHE = {}
_LAST_LIST = {}  # (acct, folder, limit) -> last good list (no TTL, for the cheap poll)
_LAST_SIG = {}  # (acct, folder, limit) -> last mailbox tip signature
_LOCK = threading.Lock()


def _dec(s) -> str:
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:
        return s or ""


def _payload(part) -> str:
    try:
        b = part.get_payload(decode=True)
        if b is None:
            return ""
        return b.decode(part.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""


def _acct_key(acct) -> tuple:
    return (
        acct.get("imap_host", ""),
        int(acct.get("imap_port") or (993 if acct.get("use_ssl", True) else 143)),
        acct.get("username") or acct.get("email", ""),
        bool(acct.get("use_ssl", True)),
    )


def _cached(cache: dict, key):
    with _LOCK:
        hit = cache.get(key)
        if not hit:
            return None
        exp, value = hit
        if exp < time.monotonic():
            cache.pop(key, None)
            return None
        return value


def _put_cache(cache: dict, key, ttl: float, value):
    with _LOCK:
        cache[key] = (time.monotonic() + ttl, value)
        if len(cache) > 128:
            for k in list(cache.keys())[:-64]:
                cache.pop(k, None)


def _open_imap(acct) -> imaplib.IMAP4:
    host = acct.get("imap_host", "")
    if not host:
        raise ValueError("no IMAP host configured")
    port = int(acct.get("imap_port") or (993 if acct.get("use_ssl", True) else 143))
    try:
        if acct.get("use_ssl", True):
            return imaplib.IMAP4_SSL(host, port, timeout=_IMAP_TIMEOUT)
        return imaplib.IMAP4(host, port, timeout=_IMAP_TIMEOUT)
    except TypeError:
        if acct.get("use_ssl", True):
            return imaplib.IMAP4_SSL(host, port)
        return imaplib.IMAP4(host, port)


def _imap(acct) -> imaplib.IMAP4:
    key = _acct_key(acct)
    now = time.monotonic()
    with _LOCK:
        pooled = _POOL.pop(key, None)
    if pooled:
        M, last_used = pooled
        if now - last_used < _POOL_IDLE:
            try:
                M.noop()
                return M
            except Exception:
                try:
                    M.logout()
                except Exception:
                    pass
        else:
            try:
                M.logout()
            except Exception:
                pass
    M = _open_imap(acct)
    try:
        if acct.get("auth_type") == "oauth":
            from services import mail_oauth

            tok = mail_oauth.ensure_access_token(acct)
            authstr = mail_oauth.xoauth2(acct.get("email", ""), tok)
            M.authenticate("XOAUTH2", lambda _challenge: authstr.encode())
        else:
            M.login(acct.get("username") or acct.get("email", ""), acct.get("password", ""))
    except Exception:
        try:
            M.logout()
        except Exception:
            pass
        raise
    return M


def _release_imap(acct, M, ok: bool = True):
    if not M:
        return
    if ok:
        with _LOCK:
            old = _POOL.pop(_acct_key(acct), None)
            if old:
                try:
                    old[0].logout()
                except Exception:
                    pass
            _POOL[_acct_key(acct)] = (M, time.monotonic())
        return
    try:
        M.logout()
    except Exception:
        pass


def clear_cache():
    with _LOCK:
        pooled = list(_POOL.values())
        _POOL.clear()
        _LIST_CACHE.clear()
        _MESSAGE_CACHE.clear()
        _LAST_LIST.clear()
        _LAST_SIG.clear()
    for M, _ in pooled:
        try:
            M.logout()
        except Exception:
            pass


def _uid_from_meta(meta: bytes) -> str:
    m = re.search(rb"\bUID\s+(\d+)\b", meta or b"")
    return m.group(1).decode() if m else ""


def _date_ts(date: str) -> float:
    try:
        dt = email.utils.parsedate_to_datetime(date or "")
        return dt.timestamp() if dt else 0
    except Exception:
        return 0


def check(acct) -> dict:
    """Test the connection: login + select INBOX."""
    M = _imap(acct)
    ok = False
    try:
        M.select("INBOX", readonly=True)
        ok = True
        return {"ok": True}
    finally:
        _release_imap(acct, M, ok)


def list_folders(acct) -> list[str]:
    M = _imap(acct)
    ok = False
    try:
        typ, data = M.list()
        out = []
        for line in data or []:
            try:
                s = line.decode(errors="replace")
                if '"' in s:
                    out.append(
                        s.split('"')[-2]
                        if s.rstrip().endswith('"')
                        else s.split(" ")[-1].strip('"')
                    )
                else:
                    out.append(s.split(" ")[-1])
            except Exception:
                continue
        ok = True
        return [f for f in out if f]
    finally:
        _release_imap(acct, M, ok)


def _select_count(M, folder: str) -> int:
    typ, sd = M.select(folder, readonly=True)
    if typ != "OK":
        raise ValueError("could not open folder")
    try:
        return int((sd[0] or b"0").decode())
    except Exception:
        return 0


def _mailbox_sig(M, exists: int) -> tuple:
    """cheap 'has anything changed' fingerprint: message count + the UID of the
    newest message. one tiny fetch, works on every server (unlike STATUS on the
    selected mailbox). a new mail moves the count or the top UID; so does a
    delete. used to skip the full header re-fetch on the background poll."""
    if exists <= 0:
        return (0, 0)
    try:
        typ, d = M.fetch(f"{exists}:{exists}", "(UID)")
        for p in d or []:
            raw = p[0] if isinstance(p, tuple) else p
            m = re.search(rb"\bUID\s+(\d+)", raw or b"")
            if m:
                return (exists, int(m.group(1)))
    except Exception:
        pass
    return (exists, 0)


def fetch_inbox(acct, folder: str = "INBOX", limit: int = 30, quick: bool = False) -> list[dict]:
    key = _acct_key(acct)
    cache_key = (key, folder, int(limit or 30))
    if not quick:
        cached = _cached(_LIST_CACHE, cache_key)
        if cached is not None:
            return cached

    M = _imap(acct)
    ok = False
    try:
        exists = _select_count(M, folder)

        # background poll: if the tip hasn't moved, hand back the last list and
        # skip the (slow on a bad link) full header fetch entirely
        if quick:
            sig = _mailbox_sig(M, exists)
            with _LOCK:
                last_list = _LAST_LIST.get(cache_key)
                last_sig = _LAST_SIG.get(cache_key)
            if last_list is not None and last_sig == sig:
                ok = True
                return last_list

        if exists <= 0:
            ok = True
            _put_cache(_LIST_CACHE, cache_key, _LIST_TTL, [])
            with _LOCK:
                _LAST_LIST[cache_key] = []
                _LAST_SIG[cache_key] = (0, 0)
            return []

        # newest `limit` messages by sequence number — no SEARCH ALL round trip
        n = int(limit or 30)
        lo = max(1, exists - n + 1)
        typ, msgd = M.fetch(
            f"{lo}:{exists}",
            "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE LIST-UNSUBSCRIBE "
            "MESSAGE-ID IN-REPLY-TO REFERENCES)])",
        )
        rows = []
        for part in msgd or []:
            if not isinstance(part, tuple):
                continue
            meta = part[0] or b""
            uid = _uid_from_meta(meta)
            if not uid:
                continue
            msg = email.message_from_bytes(part[1] or b"")
            date = msg.get("Date", "")
            rows.append(
                {
                    "uid": uid,
                    "from": _dec(msg.get("From", "")),
                    "subject": _dec(msg.get("Subject", "(no subject)")),
                    "date": date,
                    "date_ts": _date_ts(date),
                    "seen": b"\\Seen" in meta,
                    "list_unsubscribe": msg.get("List-Unsubscribe", ""),
                    "message_id": (msg.get("Message-ID", "") or "").strip(),
                    "in_reply_to": (msg.get("In-Reply-To", "") or "").strip(),
                    "references": (msg.get("References", "") or "").strip(),
                }
            )
        rows.reverse()  # sequence order is oldest→newest; we want newest first
        out = rows[:n]
        ok = True
        _put_cache(_LIST_CACHE, cache_key, _LIST_TTL, out)
        with _LOCK:
            _LAST_LIST[cache_key] = out
            _LAST_SIG[cache_key] = _mailbox_sig(M, exists)
        return out
    finally:
        _release_imap(acct, M, ok)


# ── reading one message: pull only the text/html body parts ──────────────────


def _imap_tokenize(s: str):
    """parse an IMAP parenthesized list (a BODYSTRUCTURE) into nested python
    lists. handles quoted strings, NIL, atoms and nesting — enough for finding
    the text parts. (literals don't show up in the structures we care about.)"""
    n = len(s)
    pos = s.find("(")
    if pos < 0:
        return []
    pos += 1

    def parse():
        nonlocal pos
        out = []
        while pos < n:
            c = s[pos]
            if c == " ":
                pos += 1
            elif c == "(":
                pos += 1
                out.append(parse())
            elif c == ")":
                pos += 1
                return out
            elif c == '"':
                pos += 1
                buf = []
                while pos < n and s[pos] != '"':
                    if s[pos] == "\\" and pos + 1 < n:
                        pos += 1
                    buf.append(s[pos])
                    pos += 1
                pos += 1
                out.append("".join(buf))
            else:
                start = pos
                while pos < n and s[pos] not in " ()":
                    pos += 1
                atom = s[start:pos]
                out.append(None if atom.upper() == "NIL" else atom)
        return out

    return parse()


def _extract_bodystructure(meta: str):
    i = meta.upper().find("BODYSTRUCTURE")
    if i < 0:
        return None
    i = meta.find("(", i)
    if i < 0:
        return None
    depth = 0
    inq = False
    esc = False
    j = i
    while j < len(meta):
        c = meta[j]
        if inq:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                inq = False
        else:
            if c == '"':
                inq = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return meta[i : j + 1]
        j += 1
    return None


def _text_parts(node, prefix=""):
    """walk a parsed bodystructure, collecting text/plain + text/html leaves with
    their IMAP section number, charset and transfer-encoding."""
    out = []
    if not isinstance(node, list) or not node:
        return out
    if isinstance(node[0], list):
        # multipart: child lists then the subtype string
        i = 1
        for child in node:
            if isinstance(child, list):
                sec = f"{prefix}.{i}" if prefix else str(i)
                out += _text_parts(child, sec)
                i += 1
            else:
                break
        return out
    typ = (node[0] or "").lower() if isinstance(node[0], str) else ""
    sub = (node[1] or "").lower() if len(node) > 1 and isinstance(node[1], str) else ""
    sec = prefix or "1"
    if typ == "text" and sub in ("plain", "html"):
        charset = "utf-8"
        params = node[2] if len(node) > 2 else None
        if isinstance(params, list):
            for k, v in zip(params[0::2], params[1::2]):
                if isinstance(k, str) and k.lower() == "charset" and isinstance(v, str):
                    charset = v
        enc = node[5].lower() if len(node) > 5 and isinstance(node[5], str) else ""
        out.append({"section": sec, "subtype": sub, "charset": charset, "encoding": enc})
    return out


def _decode_part(raw: bytes, enc: str, charset: str) -> str:
    try:
        if enc == "base64":
            raw = base64.b64decode(raw)
        elif enc == "quoted-printable":
            raw = quopri.decodestring(raw)
        return raw.decode(charset or "utf-8", errors="replace")
    except Exception:
        try:
            return (raw or b"").decode("utf-8", errors="replace")
        except Exception:
            return ""


def _fetch_message_parts(M, uid_b):
    """fast path: headers + bodystructure in one round trip, then fetch only the
    text/html sections. returns None if anything looks off so the caller can fall
    back to the whole-message read."""
    typ, d = M.uid("fetch", uid_b, "(BODY.PEEK[HEADER] BODYSTRUCTURE)")
    if typ != "OK":
        return None
    meta = ""
    hdr_bytes = None
    for part in d or []:
        if isinstance(part, tuple):
            meta += (part[0] or b"").decode("latin-1", "replace")
            if hdr_bytes is None:
                hdr_bytes = part[1]
        elif isinstance(part, (bytes, bytearray)):
            meta += part.decode("latin-1", "replace")
    if hdr_bytes is None:
        return None
    bs = _extract_bodystructure(meta)
    if not bs:
        return None
    parts = _text_parts(_imap_tokenize(bs))
    if not parts:
        return None

    want = {}
    for p in parts:
        want.setdefault(p["subtype"], p)  # first plain + first html is plenty

    # fetch every wanted text section in ONE round trip (was one per part — slow on
    # a high-latency link). only sections the bodystructure flagged as text are
    # requested, so an attachment section is never downloaded.
    spec = " ".join(f"BODY.PEEK[{p['section']}]" for p in want.values())
    typ2, pd = M.uid("fetch", uid_b, f"({spec})")
    by_section = {}
    for x in pd or []:
        if isinstance(x, tuple):
            meta = (x[0] or b"").decode("latin-1", "replace")
            m = re.search(r"BODY\[([0-9.]+)\]", meta)
            if m:
                by_section[m.group(1)] = x[1]

    text, html = "", ""
    for kind, p in want.items():
        body = by_section.get(p["section"])
        if body is None:
            continue
        s = _decode_part(body, p["encoding"], p["charset"])
        if kind == "plain":
            text = s
        elif kind == "html":
            html = s

    hdr = email.message_from_bytes(hdr_bytes)
    return {
        "from": _dec(hdr.get("From", "")),
        "to": _dec(hdr.get("To", "")),
        "subject": _dec(hdr.get("Subject", "(no subject)")),
        "date": hdr.get("Date", ""),
        "message_id": (hdr.get("Message-ID", "") or "").strip(),
        "references": (hdr.get("References", "") or "").strip(),
        "text": text,
        "html": html,
    }


def _fetch_message_rfc822(M, uid_b):
    """fallback: pull the whole message and walk it (what we used to always do)."""
    typ, msgd = M.uid("fetch", uid_b, "(RFC822)")
    raw = None
    for part in msgd or []:
        if isinstance(part, tuple):
            raw = part[1]
    if not raw:
        return None
    msg = email.message_from_bytes(raw)
    text, html = "", ""
    if msg.is_multipart():
        for p in msg.walk():
            if "attachment" in str(p.get("Content-Disposition") or ""):
                continue
            ct = p.get_content_type()
            if ct == "text/plain" and not text:
                text = _payload(p)
            elif ct == "text/html" and not html:
                html = _payload(p)
    elif msg.get_content_type() == "text/html":
        html = _payload(msg)
    else:
        text = _payload(msg)
    return {
        "from": _dec(msg.get("From", "")),
        "to": _dec(msg.get("To", "")),
        "subject": _dec(msg.get("Subject", "(no subject)")),
        "date": msg.get("Date", ""),
        "message_id": (msg.get("Message-ID", "") or "").strip(),
        "references": (msg.get("References", "") or "").strip(),
        "text": text,
        "html": html,
    }


def fetch_message(acct, uid: str, folder: str = "INBOX") -> dict:
    cache_key = (_acct_key(acct), folder, str(uid))
    cached = _cached(_MESSAGE_CACHE, cache_key)
    if cached is not None:
        return cached

    M = _imap(acct)
    ok = False
    try:
        M.select(folder, readonly=True)
        uid_b = uid.encode() if isinstance(uid, str) else uid
        result = None
        try:
            result = _fetch_message_parts(M, uid_b)
        except Exception:
            result = None
        if result is None:
            result = _fetch_message_rfc822(M, uid_b)
        if result is None:
            return {"error": "message not found"}
        result["uid"] = uid
        ok = True
        _put_cache(_MESSAGE_CACHE, cache_key, _MESSAGE_TTL, result)
        return result
    finally:
        _release_imap(acct, M, ok)


def is_vip(sender: str, vips) -> bool:
    """is this message from a VIP? matches the email in 'Name <email>' against the list."""
    if not vips:
        return False
    addr = email.utils.parseaddr(sender or "")[1].lower()
    return bool(addr) and addr in {str(v).lower() for v in vips}


def set_seen(acct, uid, seen: bool, folder: str = "INBOX") -> dict:
    """add/remove the \\Seen IMAP flag (read/unread toggle, best-effort)."""
    M = _imap(acct)
    ok = False
    try:
        M.select(folder)
        op = "+FLAGS" if seen else "-FLAGS"
        M.uid("store", uid.encode() if isinstance(uid, str) else uid, op, r"(\Seen)")
        ok = True
        return {"ok": True}
    finally:
        _release_imap(acct, M, ok)


def set_flag(acct, uid, flagged: bool, folder: str = "INBOX") -> dict:
    """add/remove the \\Flagged IMAP flag (best-effort star sync)."""
    M = _imap(acct)
    ok = False
    try:
        M.select(folder)
        op = "+FLAGS" if flagged else "-FLAGS"
        M.uid("store", uid.encode() if isinstance(uid, str) else uid, op, r"(\Flagged)")
        ok = True
        return {"ok": True}
    finally:
        _release_imap(acct, M, ok)


def mark_seen(acct, uid, folder: str = "INBOX") -> dict:
    """Set the \\Seen flag so opening a mail actually marks it read on the server."""
    M = _imap(acct)
    ok = False
    try:
        M.select(folder)  # writable (not readonly)
        M.uid("store", uid.encode() if isinstance(uid, str) else uid, "+FLAGS", r"(\Seen)")
        ok = True
        # drop cached lists for this folder so a refresh reflects the read state
        akey = _acct_key(acct)
        with _LOCK:
            for k in [k for k in _LIST_CACHE if k[0] == akey and k[1] == folder]:
                _LIST_CACHE.pop(k, None)
            for k in [k for k in _LAST_LIST if k[0] == akey and k[1] == folder]:
                _LAST_LIST.pop(k, None)
                _LAST_SIG.pop(k, None)
        return {"ok": True}
    finally:
        _release_imap(acct, M, ok)


# ── threading (2i): RFC-5322 reference graph ─────────────────────────────────


def _ref_ids(s: str) -> list[str]:
    """pull <message-id> tokens out of a References / In-Reply-To header."""
    return re.findall(r"<[^>\s]+>", s or "")


def thread_messages(msgs: list[dict]) -> list[dict]:
    """assign a stable thread_id to each message via the message-id <-> references/in-reply-to
    graph (union-find). subject-independent. canonical id = smallest id in the component; a message
    with no headers gets its own uid-keyed singleton thread. returns copies with thread_id set."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        parent[find(a)] = find(b)

    keys = []
    for m in msgs:
        mid = (m.get("message_id") or "").strip()
        node = mid or ("uid:" + str(m.get("uid", "")))
        keys.append(node)
        find(node)
        for r in _ref_ids(m.get("references", "")) + _ref_ids(m.get("in_reply_to", "")):
            union(node, r)

    comps = {}
    for node in list(parent):
        comps.setdefault(find(node), []).append(node)
    canon = {root: min(members) for root, members in comps.items()}

    out = []
    for m, node in zip(msgs, keys):
        mm = dict(m)
        mm["thread_id"] = canon[find(node)]
        out.append(mm)
    return out


# ── folder ops (2h): move / copy / soft-delete ───────────────────────────────


def _has_move(M) -> bool:
    try:
        return any("MOVE" in str(c).upper() for c in (M.capabilities or ()))
    except Exception:
        return False


def _has_uidplus(M) -> bool:
    try:
        return any("UIDPLUS" in str(c).upper() for c in (M.capabilities or ()))
    except Exception:
        return False


def _do_move(M, uid, dest, src):
    """move one uid from src to dest. UID MOVE (RFC 6851) when the server has it, else the
    portable COPY + \\Deleted + EXPUNGE dance. operates on an already-open connection."""
    M.select(src)
    u = uid.encode() if isinstance(uid, str) else uid
    if _has_move(M):
        M.uid("MOVE", u, dest)
    else:
        M.uid("COPY", u, dest)
        M.uid("STORE", u, "+FLAGS", r"(\Deleted)")
        # scope the expunge to JUST this uid (UIDPLUS) — a plain EXPUNGE would purge every
        # other \Deleted message the user has flagged in this folder. fall back only if the
        # server has neither MOVE nor UIDPLUS.
        if _has_uidplus(M):
            M.uid("EXPUNGE", u)
        else:
            M.expunge()
    return True


def move_message(acct, uid, dest, src: str = "INBOX") -> dict:
    """move a message to another folder (best-effort, server-side)."""
    M = _imap(acct)
    ok = False
    try:
        _do_move(M, uid, dest, src)
        ok = True
        return {"ok": True, "uid": str(uid), "dest": dest}
    finally:
        _release_imap(acct, M, ok)


def copy_message(acct, uid, dest, src: str = "INBOX") -> dict:
    """copy a message into another folder, leaving the original in place."""
    M = _imap(acct)
    ok = False
    try:
        M.select(src)
        M.uid("COPY", uid.encode() if isinstance(uid, str) else uid, dest)
        ok = True
        return {"ok": True}
    finally:
        _release_imap(acct, M, ok)


def delete_message(acct, uid, folder: str = "INBOX") -> dict:
    """soft-delete: flag \\Deleted + expunge from the folder (best-effort)."""
    M = _imap(acct)
    ok = False
    try:
        M.select(folder)
        u = uid.encode() if isinstance(uid, str) else uid
        M.uid("STORE", u, "+FLAGS", r"(\Deleted)")
        M.expunge()
        ok = True
        return {"ok": True}
    finally:
        _release_imap(acct, M, ok)


# ── search ───────────────────────────────────────────────────────────────────


def search(acct, query: str, folder: str = "INBOX", limit: int = 40) -> list[dict]:
    """IMAP TEXT search (headers + body) → header rows, newest first. returns []
    on an empty query or a server that rejects the search."""
    q = (query or "").strip()
    if not q:
        return []
    M = _imap(acct)
    ok = False
    try:
        M.select(folder, readonly=True)
        try:
            typ, data = M.uid("search", "CHARSET", "UTF-8", "TEXT", q.encode("utf-8"))
        except Exception:
            typ, data = M.uid("search", None, "TEXT", q)
        if typ != "OK" or not data:
            ok = True
            return []
        uids = (data[0] or b"").split()[-int(limit or 40) :]  # newest matches
        if not uids:
            ok = True
            return []
        typ, msgd = M.uid(
            "fetch", b",".join(uids), "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
        )
        rows = []
        for part in msgd or []:
            if not isinstance(part, tuple):
                continue
            meta = part[0] or b""
            uid = _uid_from_meta(meta)
            if not uid:
                continue
            msg = email.message_from_bytes(part[1] or b"")
            date = msg.get("Date", "")
            rows.append(
                {
                    "uid": uid,
                    "from": _dec(msg.get("From", "")),
                    "subject": _dec(msg.get("Subject", "(no subject)")),
                    "date": date,
                    "date_ts": _date_ts(date),
                    "seen": b"\\Seen" in meta,
                }
            )
        rows.sort(key=lambda x: x["date_ts"], reverse=True)
        ok = True
        return rows
    finally:
        _release_imap(acct, M, ok)


# ── threads — group a flat message list by normalized subject ────────────────

_SUBJ_PREFIX = re.compile(r"^(?:\s*(?:re|fwd|fw|aw|wg)\s*:\s*)+", re.I)


def normalize_subject(s: str) -> str:
    s = _SUBJ_PREFIX.sub("", _dec(s or "")).strip()
    return s or "(no subject)"


_SOCIAL = (
    "facebook",
    "twitter",
    "x.com",
    "linkedin",
    "instagram",
    "tiktok",
    "reddit",
    "youtube",
    "pinterest",
)
_PROMO = (
    "sale",
    "% off",
    "deal",
    "discount",
    "coupon",
    "offer",
    "newsletter",
    "unsubscribe",
    "promo",
)


def categorize(sender: str, subject: str, list_unsubscribe: str = "") -> str:
    """Gmail-style inbox category from headers (5e): primary | social | promotions | updates."""
    s = (sender or "").lower()
    subj = (subject or "").lower()
    if any(d in s for d in _SOCIAL):
        return "social"
    if list_unsubscribe or any(w in subj for w in _PROMO) or "newsletter" in s or "marketing" in s:
        return "promotions"
    if (
        "no-reply" in s
        or "noreply" in s
        or "notification" in s
        or "notify" in s
        or "donotreply" in s
    ):
        return "updates"
    return "primary"


def parse_list_unsubscribe(header: str) -> dict:
    """pull the http(s) and mailto targets out of a List-Unsubscribe header (5a)."""
    http = mailto = ""
    for uri in re.findall(r"<([^>]+)>", header or ""):
        u = uri.strip()
        if u.lower().startswith("http") and not http:
            http = u
        elif u.lower().startswith("mailto:") and not mailto:
            mailto = u
    return {"http": http, "mailto": mailto}


def parse_search_query(q: str) -> dict:
    """parse Gmail-style operators (from:/to:/subject:/has:attachment/before:/after:) out of a
    search string; the leftover words become the free-text match (5a)."""
    spec = {
        "from": "",
        "to": "",
        "subject": "",
        "has_attachment": False,
        "before": "",
        "after": "",
        "text": "",
    }
    words = []
    for tok in (q or "").split():
        low = tok.lower()
        if low.startswith("from:"):
            spec["from"] = tok[5:]
        elif low.startswith("to:"):
            spec["to"] = tok[3:]
        elif low.startswith("subject:"):
            spec["subject"] = tok[8:]
        elif low.startswith("before:"):
            spec["before"] = tok[7:]
        elif low.startswith("after:"):
            spec["after"] = tok[6:]
        elif low in ("has:attachment", "has:attachments"):
            spec["has_attachment"] = True
        else:
            words.append(tok)
    spec["text"] = " ".join(words)
    return spec


def group_threads(messages: list[dict]) -> list[dict]:
    """collapse a flat list (from fetch_inbox) into conversations keyed on the
    re:/fwd:-stripped subject. each thread carries its messages newest-first."""
    buckets: dict[str, list] = {}
    for m in messages:
        buckets.setdefault(normalize_subject(m.get("subject", "")).lower(), []).append(m)
    out = []
    for msgs in buckets.values():
        msgs = sorted(msgs, key=lambda x: x.get("date_ts", 0), reverse=True)
        top = msgs[0]
        out.append(
            {
                "subject": normalize_subject(top.get("subject", "")),
                "count": len(msgs),
                "latest_ts": top.get("date_ts", 0),
                "unseen": sum(1 for x in msgs if not x.get("seen", True)),
                "uid": top.get("uid"),
                "from": top.get("from", ""),
                "date": top.get("date", ""),
                "messages": msgs,
            }
        )
    out.sort(key=lambda x: x["latest_ts"], reverse=True)
    return out


# ── attachments ──────────────────────────────────────────────────────────────


def attachments_of(msg) -> list[dict]:
    """list the attachment parts of a parsed email (by walk-index, so a later
    fetch can grab one). a part counts if it has a filename or is dispositioned
    as an attachment."""
    out = []
    for i, p in enumerate(msg.walk()):
        if p.is_multipart():
            continue
        fn = _dec(p.get_filename() or "")
        disp = str(p.get("Content-Disposition") or "").lower()
        if not fn and "attachment" not in disp:
            continue
        payload = p.get_payload(decode=True) or b""
        out.append(
            {
                "index": i,
                "filename": fn or f"attachment-{i}",
                "content_type": p.get_content_type(),
                "size": len(payload),
            }
        )
    return out


def _full_message(M, uid, folder):
    M.select(folder, readonly=True)
    typ, msgd = M.uid("fetch", uid.encode() if isinstance(uid, str) else uid, "(RFC822)")
    for part in msgd or []:
        if isinstance(part, tuple) and part[1]:
            return email.message_from_bytes(part[1])
    return None


def list_attachments(acct, uid, folder: str = "INBOX") -> list[dict]:
    M = _imap(acct)
    ok = False
    try:
        msg = _full_message(M, uid, folder)
        ok = True
        return attachments_of(msg) if msg else []
    finally:
        _release_imap(acct, M, ok)


def fetch_attachment(acct, uid, index: int, folder: str = "INBOX"):
    """returns (filename, content_type, bytes) for one attachment, or None."""
    M = _imap(acct)
    ok = False
    try:
        msg = _full_message(M, uid, folder)
        ok = True
        if not msg:
            return None
        for i, p in enumerate(msg.walk()):
            if i == int(index) and not p.is_multipart():
                return (
                    _dec(p.get_filename() or f"attachment-{i}"),
                    p.get_content_type(),
                    p.get_payload(decode=True) or b"",
                )
        return None
    finally:
        _release_imap(acct, M, ok)


def _build_message(
    acct, to, subject, body, cc="", bcc="", in_reply_to="", references="", html="", inline=None
):
    msg = EmailMessage()
    msg["From"] = acct.get("email") or acct.get("username", "")
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc  # send_message strips this from the wire but uses it for the envelope
    msg["Subject"] = subject
    # thread replies properly in other clients (Mail.app, Gmail, etc.)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " + in_reply_to).strip() if references else in_reply_to
    msg.set_content(body or "")
    if html:  # multipart/alternative; inline images go related off the html part (5c)
        msg.add_alternative(html, subtype="html")
        if inline:
            html_part = msg.get_payload()[-1]
            for img in inline:
                html_part.add_related(
                    img["data"],
                    maintype="image",
                    subtype=img.get("subtype", "png"),
                    cid=f"<{img['cid']}>",
                )
    return msg


def send_mail(
    acct,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    in_reply_to: str = "",
    references: str = "",
    html: str = "",
    inline=None,
) -> dict:
    host = acct.get("smtp_host", "")
    if not host:
        raise ValueError("no SMTP host configured")
    msg = _build_message(
        acct, to, subject, body, cc, bcc, in_reply_to, references, html=html, inline=inline
    )
    port = int(acct.get("smtp_port") or 587)
    user = acct.get("username") or acct.get("email", "")
    pw = acct.get("password", "")

    # a flaky proxy/link drops the SMTP socket mid-handshake every so often
    # ("connection unexpectedly closed"). that's transient — retry once before
    # giving up. auth errors are NOT retried (a wrong password won't fix itself).
    last_err = None
    for attempt in range(2):
        try:
            if port == 465:
                s = smtplib.SMTP_SSL(host, port, timeout=30)
            else:
                s = smtplib.SMTP(host, port, timeout=30)
                s.ehlo()
                try:
                    s.starttls()
                    s.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass  # server without STARTTLS (some local/self-hosted servers)
            try:
                if acct.get("auth_type") == "oauth":
                    from services import mail_oauth

                    tok = mail_oauth.ensure_access_token(acct)
                    s.auth(
                        "XOAUTH2",
                        lambda challenge=None: mail_oauth.xoauth2(acct.get("email", ""), tok),
                    )
                else:
                    s.login(user, pw)
                s.send_message(msg)
            finally:
                try:
                    s.quit()
                except Exception:
                    pass
            return {"ok": True}
        except (
            smtplib.SMTPServerDisconnected,
            smtplib.SMTPConnectError,
            ConnectionError,
            TimeoutError,
            OSError,
        ) as e:
            last_err = e
            time.sleep(0.8)
    raise last_err or RuntimeError("send failed")
