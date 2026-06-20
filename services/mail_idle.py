"""IMAP IDLE push (5e) — best-effort. real IDLE needs a live server held open per account,
which can't be exercised offline; this exposes a capability check + a single IDLE wait the
caller can loop. when IDLE is unavailable the app falls back to the existing 30s poll
(set faster via the `mail_live` setting)."""

import imaplib


def idle_available(acct) -> bool:
    """does the server advertise IDLE? best-effort; False on any error."""
    from services.mail import _imap, _release_imap

    M = None
    try:
        M = _imap(acct)
        caps = getattr(M, "capabilities", ())
        return any("IDLE" in str(c).upper() for c in caps)
    except Exception:
        return False
    finally:
        if M:
            _release_imap(acct, M, ok=True)


def idle_wait(acct, folder="INBOX", timeout=29) -> bool:
    """block until the mailbox signals new mail (or timeout). returns True if something
    changed. best-effort — imaplib has no first-class IDLE, so we send it by hand."""
    from services.mail import _imap, _release_imap

    M = None
    try:
        M = _imap(acct)
        M.select(folder)
        tag = M._new_tag()
        M.send(tag + b" IDLE\r\n")
        M.readline()  # server "+ idling"
        M.sock.settimeout(timeout)
        try:
            line = M.readline()
        except Exception:
            line = b""
        M.send(b"DONE\r\n")
        M.readline()
        return b"EXISTS" in (line or b"")
    except (imaplib.IMAP4.error, OSError, AttributeError):
        return False
    finally:
        if M:
            _release_imap(acct, M, ok=False)
