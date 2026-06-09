"""
Mail client - IMAP fetch + SMTP send over Python stdlib.

This stays intentionally small, but borrows the useful Odysseus shape:
reuse live IMAP sessions, cache short-lived list/body reads, and fetch message
headers in one batch instead of one UID at a time.
"""
import email
import email.utils
import imaplib
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
    M.login(acct.get("username") or acct.get("email", ""), acct.get("password", ""))
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
        for line in (data or []):
            try:
                s = line.decode(errors="replace")
                if '"' in s:
                    out.append(s.split('"')[-2] if s.rstrip().endswith('"') else s.split(" ")[-1].strip('"'))
                else:
                    out.append(s.split(" ")[-1])
            except Exception:
                continue
        ok = True
        return [f for f in out if f]
    finally:
        _release_imap(acct, M, ok)


def fetch_inbox(acct, folder: str = "INBOX", limit: int = 30) -> list[dict]:
    cache_key = (_acct_key(acct), folder, int(limit or 30))
    cached = _cached(_LIST_CACHE, cache_key)
    if cached is not None:
        return cached

    M = _imap(acct)
    ok = False
    try:
        M.select(folder, readonly=True)
        typ, data = M.uid("search", None, "ALL")
        uids = data[0].split() if (data and data[0]) else []
        uids = uids[-limit:][::-1]
        if not uids:
            ok = True
            _put_cache(_LIST_CACHE, cache_key, _LIST_TTL, [])
            return []

        by_uid = {}
        typ, msgd = M.uid("fetch", b",".join(uids), "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        for part in msgd or []:
            if not isinstance(part, tuple):
                continue
            meta = part[0] or b""
            uid = _uid_from_meta(meta)
            if not uid:
                continue
            msg = email.message_from_bytes(part[1] or b"")
            date = msg.get("Date", "")
            by_uid[uid] = {
                "uid": uid,
                "from": _dec(msg.get("From", "")),
                "subject": _dec(msg.get("Subject", "(no subject)")),
                "date": date,
                "date_ts": _date_ts(date),
                "seen": b"\\Seen" in meta,
            }

        out = [by_uid[uid.decode()] for uid in uids if uid.decode() in by_uid]
        ok = True
        _put_cache(_LIST_CACHE, cache_key, _LIST_TTL, out)
        return out
    finally:
        _release_imap(acct, M, ok)


def fetch_message(acct, uid: str, folder: str = "INBOX") -> dict:
    cache_key = (_acct_key(acct), folder, str(uid))
    cached = _cached(_MESSAGE_CACHE, cache_key)
    if cached is not None:
        return cached

    M = _imap(acct)
    ok = False
    try:
        M.select(folder, readonly=True)
        typ, msgd = M.uid("fetch", uid.encode() if isinstance(uid, str) else uid, "(RFC822)")
        raw = None
        for part in (msgd or []):
            if isinstance(part, tuple):
                raw = part[1]
        if not raw:
            return {"error": "message not found"}
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
        result = {
            "uid": uid,
            "from": _dec(msg.get("From", "")),
            "to": _dec(msg.get("To", "")),
            "subject": _dec(msg.get("Subject", "(no subject)")),
            "date": msg.get("Date", ""),
            "text": text,
            "html": html,
        }
        ok = True
        _put_cache(_MESSAGE_CACHE, cache_key, _MESSAGE_TTL, result)
        return result
    finally:
        _release_imap(acct, M, ok)


def mark_seen(acct, uid, folder: str = "INBOX") -> dict:
    """Set the \\Seen flag so opening a mail actually marks it read on the server."""
    M = _imap(acct)
    ok = False
    try:
        M.select(folder)   # writable (not readonly)
        M.uid("store", uid.encode() if isinstance(uid, str) else uid, "+FLAGS", r"(\Seen)")
        ok = True
        # drop cached lists for this folder so a refresh reflects the read state
        akey = _acct_key(acct)
        with _LOCK:
            for k in [k for k in _LIST_CACHE if k[0] == akey and k[1] == folder]:
                _LIST_CACHE.pop(k, None)
        return {"ok": True}
    finally:
        _release_imap(acct, M, ok)


def send_mail(acct, to: str, subject: str, body: str, cc: str = "") -> dict:
    host = acct.get("smtp_host", "")
    if not host:
        raise ValueError("no SMTP host configured")
    msg = EmailMessage()
    msg["From"] = acct.get("email") or acct.get("username", "")
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.set_content(body or "")
    port = int(acct.get("smtp_port") or 587)
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
        try:
            s.starttls()
        except Exception:
            pass
    try:
        s.login(acct.get("username") or acct.get("email", ""), acct.get("password", ""))
        s.send_message(msg)
    finally:
        try:
            s.quit()
        except Exception:
            pass
    return {"ok": True}
