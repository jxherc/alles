"""
Mail client — IMAP fetch + SMTP send over Python stdlib (no extra deps).

Functions take a plain `acct` dict (imap_host/imap_port/smtp_host/smtp_port/
username/password/email/use_ssl) so this stays decoupled from the DB. Real use
needs the user's own server creds; everything is wrapped so a bad connection
raises a clean error the route turns into JSON.
"""
import imaplib
import smtplib
import email
from email.header import decode_header, make_header
from email.message import EmailMessage


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


def _imap(acct) -> imaplib.IMAP4:
    host = acct.get("imap_host", "")
    if not host:
        raise ValueError("no IMAP host configured")
    if acct.get("use_ssl", True):
        M = imaplib.IMAP4_SSL(host, int(acct.get("imap_port") or 993))
    else:
        M = imaplib.IMAP4(host, int(acct.get("imap_port") or 143))
    M.login(acct.get("username") or acct.get("email", ""), acct.get("password", ""))
    return M


def check(acct) -> dict:
    """test the connection — login + select INBOX."""
    M = _imap(acct)
    try:
        M.select("INBOX", readonly=True)
        return {"ok": True}
    finally:
        try: M.logout()
        except Exception: pass


def list_folders(acct) -> list[str]:
    M = _imap(acct)
    try:
        typ, data = M.list()
        out = []
        for line in (data or []):
            try:
                s = line.decode(errors="replace")
                # folder name is the last token, usually quoted after the delimiter
                if '"' in s:
                    out.append(s.split('"')[-2] if s.rstrip().endswith('"') else s.split(' ')[-1].strip('"'))
                else:
                    out.append(s.split(" ")[-1])
            except Exception:
                continue
        return [f for f in out if f]
    finally:
        try: M.logout()
        except Exception: pass


def fetch_inbox(acct, folder: str = "INBOX", limit: int = 30) -> list[dict]:
    M = _imap(acct)
    try:
        M.select(folder, readonly=True)
        typ, data = M.uid("search", None, "ALL")
        uids = data[0].split() if (data and data[0]) else []
        uids = uids[-limit:][::-1]   # newest first
        out = []
        for uid in uids:
            typ, msgd = M.uid("fetch", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not msgd:
                continue
            flags, hdr = b"", b""
            for part in msgd:
                if isinstance(part, tuple):
                    flags += part[0] or b""
                    hdr += part[1] or b""
                elif isinstance(part, bytes):
                    flags += part
            msg = email.message_from_bytes(hdr)
            out.append({
                "uid": uid.decode(),
                "from": _dec(msg.get("From", "")),
                "subject": _dec(msg.get("Subject", "(no subject)")),
                "date": msg.get("Date", ""),
                "seen": b"\\Seen" in flags,
            })
        return out
    finally:
        try: M.logout()
        except Exception: pass


def fetch_message(acct, uid: str, folder: str = "INBOX") -> dict:
    M = _imap(acct)
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
        return {
            "uid": uid, "from": _dec(msg.get("From", "")), "to": _dec(msg.get("To", "")),
            "subject": _dec(msg.get("Subject", "(no subject)")), "date": msg.get("Date", ""),
            "text": text, "html": html,
        }
    finally:
        try: M.logout()
        except Exception: pass


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
            pass  # some servers are plain
    try:
        s.login(acct.get("username") or acct.get("email", ""), acct.get("password", ""))
        s.send_message(msg)
    finally:
        try: s.quit()
        except Exception: pass
    return {"ok": True}
