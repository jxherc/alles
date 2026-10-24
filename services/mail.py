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
    if acct.get("auth_type") != "oauth":
        user = _login_text(acct.get("username") or acct.get("email", ""), "username")
        password = _login_text(acct.get("password", ""), "password")
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
            M.login(_quoted(user), password)  # imaplib quotes the password itself
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
        old = None
        with _LOCK:
            key = _acct_key(acct)
            old = _POOL.pop(key, None)
            _POOL[key] = (M, time.monotonic())
        if old and old[0] is not M:
            try:
                old[0].logout()
            except Exception:
                pass
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


_UID = re.compile(r"[1-9][0-9]{0,9}")


def message_uid(uid) -> bytes:
    """a message uid the way IMAP gets it. anything but plain digits never reaches the server: a
    CRLF in it would send a second command, a comma or colon would pick other messages."""
    text = uid.decode("ascii", "replace") if isinstance(uid, bytes) else str(uid)
    if not _UID.fullmatch(text):
        raise ValueError("not a message id")
    return text.encode()


# control characters (C0, C1) and line separators can't be part of a folder name
_NOT_A_FOLDER = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def _utf7_imap(name: str) -> str:
    """RFC 3501 modified UTF-7, how a folder name beyond ascii goes on the wire ("Entwürfe" ->
    "Entw&APw-rfe")."""
    out, run = [], []

    def flush():
        if run:
            raw = base64.b64encode("".join(run).encode("utf-16-be")).decode("ascii")
            out.append("&" + raw.rstrip("=").replace("/", ",") + "-")
            run.clear()

    for char in name:
        if 0x20 <= ord(char) <= 0x7E:
            flush()
            out.append("&-" if char == "&" else char)
        else:
            run.append(char)
    flush()
    return "".join(out)


_MUTF7_RUN = re.compile(r"&([A-Za-z0-9+,]*)-")


def _utf7_imap_decode(name: str):
    """the text a modified UTF-7 name stands for, None if it isn't valid modified UTF-7"""
    out, i = [], 0
    while i < len(name):
        if name[i] == "&":
            m = _MUTF7_RUN.match(name, i)
            if not m:
                return None
            body = m.group(1)
            try:
                raw = base64.b64decode(body.replace(",", "/") + "=" * (-len(body) % 4))
                out.append(raw.decode("utf-16-be") if body else "&")
            except ValueError:
                return None
            i = m.end()
        elif 0x20 <= ord(name[i]) <= 0x7E:
            out.append(name[i])
            i += 1
        else:
            return None
    return "".join(out)


def mailbox_name(folder) -> str:
    """a folder name as it goes on the wire. the API takes wire names, as LIST hands them out:
    an ascii name that is valid modified UTF-7 (and encodes back the same way) passes as it is,
    so "Entw&APw-rfe" and "a&-b" stay. anything else is plain text and gets encoded: "Entwürfe"
    -> "Entw&APw-rfe", "R&D" -> "R&-D". (a plain name that happens to be valid modified UTF-7
    can't be told apart, so it's read as a wire name.) control and line-separator characters
    can't be part of a folder, so they're refused."""
    name = str(folder or "")
    if not name or len(name) > 512 or _NOT_A_FOLDER.search(name):
        raise ValueError("not a folder name")
    if name.isascii():
        text = _utf7_imap_decode(name)
        if text is not None and _utf7_imap(text) == name:
            return name
    return _utf7_imap(name)


def _quoted(text: str) -> str:
    """one IMAP quoted string (ascii, no line breaks: callers check that first)"""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _box(folder) -> str:
    """a folder as a command argument: always quoted, so "Sent Messages" stays one name and
    nothing in it can add parameters or a second command"""
    return _quoted(mailbox_name(folder))


def message_id_arg(message_id) -> str:
    """a Message-ID for a HEADER search, quoted. printable ascii only, which a Message-ID is."""
    mid = str(message_id or "").strip()
    if not mid or len(mid) > 998 or any(not 33 <= ord(c) <= 126 for c in mid):
        raise ValueError("not a message id")
    return _quoted(mid)


def _login_text(value, what: str) -> str:
    """a username or password for LOGIN. imaplib sends both as given (it only quotes the
    password), so a line break would end the command early"""
    text = str(value or "")
    # a quoted string may hold any ascii but NUL, CR and LF (tab included)
    if re.search(r"[\x00\r\n]", text):
        raise ValueError(f"the mail {what} has a line break or control character")
    if not text.isascii():
        raise ValueError(f"this mail login can't take characters beyond plain ascii in the {what}")
    return text


def _search_text(text) -> str:
    """search words as one quoted IMAP string, so they stay words and never become commands."""
    if re.search(r"[\x00-\x1f\x7f]", text):
        raise ValueError("search text can't hold line breaks or control characters")
    return _quoted(text)


def check(acct) -> dict:
    """Test the connection: login + select INBOX."""
    M = _imap(acct)
    ok = False
    try:
        M.select(_box("INBOX"), readonly=True)
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
            # each line is (flags) delimiter name, the name an atom, a quoted string (with \\
            # and \" escapes) or a literal, which imaplib hands over as (head, name bytes) and
            # follows with the empty rest of its line
            if isinstance(line, tuple):
                name = (line[1] or b"").decode("utf-8", "replace")
            elif line:
                parts = _imap_tokenize("(" + line.decode("utf-8", "replace") + ")")
                name = parts[2] if len(parts) > 2 and isinstance(parts[2], str) else ""
            else:
                continue
            if name:
                out.append(name)
        ok = True
        return out
    finally:
        _release_imap(acct, M, ok)


def _select_count(M, folder: str) -> int:
    typ, sd = M.select(_box(folder), readonly=True)
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
    _box(folder)  # refused before a connection opens
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
            "(UID FLAGS BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE "
            "LIST-UNSUBSCRIBE MESSAGE-ID IN-REPLY-TO REFERENCES)])",
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
            meta_s = meta.decode("latin-1", "replace")
            bs = _extract_bodystructure(meta_s)
            has_att = _bs_has_attachment(_imap_tokenize(bs or ""))
            rows.append(
                {
                    "uid": uid,
                    "from": _dec(msg.get("From", "")),
                    "to": _dec(msg.get("To", "")),
                    "subject": _dec(msg.get("Subject", "(no subject)")),
                    "date": date,
                    "date_ts": _date_ts(date),
                    "seen": b"\\Seen" in meta,
                    "has_attachment": has_att,
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


def _has_name_param(params) -> bool:
    if not isinstance(params, list):
        return False
    for k, v in zip(params[0::2], params[1::2]):
        if isinstance(k, str) and k.lower() in ("name", "filename") and v:
            return True
    return False


def _bs_has_attachment(node) -> bool:
    if not isinstance(node, list) or not node:
        return False
    if isinstance(node[0], list):
        return any(_bs_has_attachment(child) for child in node if isinstance(child, list))
    if _has_name_param(node[2] if len(node) > 2 else None):
        return True
    for part in node[8:]:
        if not isinstance(part, list) or not part:
            continue
        disp = part[0].lower() if isinstance(part[0], str) else ""
        if disp == "attachment":
            return True
        if _has_name_param(part[1] if len(part) > 1 else None):
            return True
    return False


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
        "has_attachment": _bs_has_attachment(_imap_tokenize(bs)),
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
    has_att = False
    if msg.is_multipart():
        for p in msg.walk():
            if "attachment" in str(p.get("Content-Disposition") or ""):
                has_att = True
                continue
            if p.get_filename():
                has_att = True
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
        "has_attachment": has_att,
        "text": text,
        "html": html,
    }


def fetch_message(acct, uid: str, folder: str = "INBOX", *, refresh: bool = False) -> dict:
    uid_b, box = message_uid(uid), _box(folder)
    cache_key = (_acct_key(acct), folder, str(uid))
    cached = None if refresh else _cached(_MESSAGE_CACHE, cache_key)
    if cached is not None:
        return cached

    M = _imap(acct)
    ok = False
    try:
        M.select(box, readonly=True)
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
    uid, box = message_uid(uid), _box(folder)
    M = _imap(acct)
    ok = False
    try:
        M.select(box)
        op = "+FLAGS" if seen else "-FLAGS"
        M.uid("store", uid, op, r"(\Seen)")
        ok = True
        return {"ok": True}
    finally:
        _release_imap(acct, M, ok)


def set_flag(acct, uid, flagged: bool, folder: str = "INBOX") -> dict:
    """add/remove the \\Flagged IMAP flag (best-effort star sync)."""
    uid, box = message_uid(uid), _box(folder)
    M = _imap(acct)
    ok = False
    try:
        M.select(box)
        op = "+FLAGS" if flagged else "-FLAGS"
        M.uid("store", uid, op, r"(\Flagged)")
        ok = True
        return {"ok": True}
    finally:
        _release_imap(acct, M, ok)


def mark_seen(acct, uid, folder: str = "INBOX") -> dict:
    """Set the \\Seen flag so opening a mail actually marks it read on the server."""
    uid, box = message_uid(uid), _box(folder)
    M = _imap(acct)
    ok = False
    try:
        M.select(box)  # writable (not readonly)
        M.uid("store", uid, "+FLAGS", r"(\Seen)")
        ok = True
        _forget_lists(acct, folder)
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


# ── folder ops (2h): move / soft-delete ──────────────────────────────────────


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

    def checked(response, action):
        status = response[0] if isinstance(response, (tuple, list)) and response else ""
        if isinstance(status, bytes):
            status = status.decode("ascii", errors="replace")
        if status != "OK":
            raise RuntimeError(f"mail server did not confirm {action}")

    u, src_box, dest_box = message_uid(uid), _box(src), _box(dest)
    checked(M.select(src_box), "select the source folder")
    if _has_move(M):
        checked(M.uid("MOVE", u, dest_box), "move the message")
    else:
        checked(M.uid("COPY", u, dest_box), "copy the message")
        checked(M.uid("STORE", u, "+FLAGS", r"(\Deleted)"), "mark the source message deleted")
        # scope the expunge to JUST this uid (UIDPLUS) — a plain EXPUNGE would purge every
        # other \Deleted message the user has flagged in this folder. fall back only if the
        # server has neither MOVE nor UIDPLUS.
        if _has_uidplus(M):
            checked(M.uid("EXPUNGE", u), "remove the source message")
        else:
            checked(M.expunge(), "remove deleted messages")
    return True


def _message_id(M, folder, uid) -> str:
    """the Message-ID of one message, '' when it has none or the read fails (the move still goes)."""
    try:
        M.select(_box(folder))
        typ, data = M.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
    except Exception:
        return ""
    if typ != "OK":
        return ""
    for part in data or []:
        if isinstance(part, tuple) and part[1]:
            return (email.message_from_bytes(part[1]).get("Message-ID", "") or "").strip()
    return ""


def _uid_by_message_id(M, folder, message_id) -> bytes:
    """newest uid in `folder` with this Message-ID. a move gives the message a new uid, so this is
    how an undo finds it again; the copy that just arrived is the newest one."""
    quoted = message_id_arg(message_id)
    if M.select(_box(folder))[0] != "OK":
        raise RuntimeError("mail server did not open the folder")
    typ, data = M.uid("SEARCH", None, "HEADER", "Message-ID", quoted)
    uids = (data[0] or b"").split() if typ == "OK" and data else []
    if not uids:
        raise LookupError("the message is not in that folder")
    return max(uids, key=int)


def _forget_lists(acct, *folders):
    """drop cached lists for these folders so the next read shows a move or a read change."""
    akey = _acct_key(acct)
    with _LOCK:
        for k in [k for k in _LIST_CACHE if k[0] == akey and k[1] in folders]:
            _LIST_CACHE.pop(k, None)
        for k in [k for k in _LAST_LIST if k[0] == akey and k[1] in folders]:
            _LAST_LIST.pop(k, None)
            _LAST_SIG.pop(k, None)


def move_message(acct, uid, dest, src: str = "INBOX", message_id: str = "") -> dict:
    """move a message to another folder (best-effort, server-side). with no uid, the newest message
    in src with `message_id` moves. the reply carries the Message-ID, so an undo can find it again."""
    # everything is checked before a connection opens
    _box(src)
    _box(dest)
    if uid:
        uid = message_uid(uid)
    else:
        message_id_arg(message_id)
    M = _imap(acct)
    ok = False
    try:
        if uid:
            message_id = _message_id(M, src, uid)
        else:
            uid = _uid_by_message_id(M, src, message_id)
        _do_move(M, uid, dest, src)
        ok = True
        _forget_lists(acct, src, dest)
        uid = uid.decode() if isinstance(uid, bytes) else str(uid)
        return {"ok": True, "uid": uid, "dest": dest, "message_id": message_id}
    finally:
        _release_imap(acct, M, ok)


def delete_message(acct, uid, folder: str = "INBOX") -> dict:
    """soft-delete: flag \\Deleted + expunge from the folder (best-effort)."""
    u, box = message_uid(uid), _box(folder)
    M = _imap(acct)
    ok = False
    try:
        M.select(box)
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
    box = _box(folder)
    quoted = _search_text(q)
    M = _imap(acct)
    ok = False
    try:
        M.select(box, readonly=True)
        if q.isascii():
            typ, data = M.uid("search", None, "TEXT", quoted)
        else:
            # a quoted string is ascii only: other text goes as a counted literal, which the
            # server reads as data however it looks
            try:
                M.literal = q.encode("utf-8")
                typ, data = M.uid("search", "CHARSET", "UTF-8", "TEXT")
            finally:
                M.literal = None
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
    M.select(_box(folder), readonly=True)
    typ, msgd = M.uid("fetch", message_uid(uid), "(RFC822)")
    for part in msgd or []:
        if isinstance(part, tuple) and part[1]:
            return email.message_from_bytes(part[1])
    return None


def list_attachments(acct, uid, folder: str = "INBOX") -> list[dict]:
    message_uid(uid)  # refused before a connection opens
    mailbox_name(folder)
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
    message_uid(uid)  # refused before a connection opens
    mailbox_name(folder)
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
