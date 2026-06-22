"""IMAP IDLE push (5e) — best-effort. real IDLE needs a live server held open per account,
which can't be exercised offline; this exposes a capability check. when IDLE is unavailable
the app falls back to the existing 30s poll (set faster via the `mail_live` setting)."""


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


