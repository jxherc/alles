"""One-attempt webhook delivery and its persisted outcome."""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx

from core.database import SessionLocal, Webhook

log = logging.getLogger("aide.webhooks")


def _sign(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


async def _deliver(w: Webhook, body: dict) -> tuple[str, str]:
    """Post once and report whether delivery was confirmed, rejected, or uncertain."""
    from services.net_guard import is_safe_url

    if not is_safe_url(w.url):  # SSRF: a hook url can't target the app's own loopback / metadata
        return "error", "blocked: non-public url"
    raw = json.dumps(body).encode()
    headers = {"content-type": "application/json"}
    if w.secret:
        headers["x-alles-signature"] = _sign(w.secret, raw)
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(w.url, content=raw, headers=headers)
    except Exception as e:
        # A timeout or transport failure may happen after the receiver accepted the request.
        # Retrying here could deliver the same event twice. Keep only the exception
        # type because request errors can include secret-bearing webhook URLs.
        err = type(e).__name__
        log.warning("webhook %s delivery uncertain: %s", w.name, err)
        return "uncertain", err

    if r.status_code < 400:
        return "ok", ""

    err = f"http {r.status_code}"
    if r.status_code >= 500:
        # The receiver may have applied the event before returning a server error.
        log.warning("webhook %s delivery uncertain: %s", w.name, err)
        return "uncertain", err

    log.warning("webhook %s rejected: %s", w.name, err)
    return "error", err


def _record_outcome(hook: Webhook, status: str, error: str) -> None:
    hook.last_status, hook.last_error, hook.last_triggered = (
        status,
        error,
        datetime.now(UTC).replace(tzinfo=None),
    )


async def send_test(wid: str) -> tuple[str, str] | None:
    """Send a sample webhook and save its outcome, or return None if missing."""
    db = SessionLocal()
    try:
        hook = db.get(Webhook, wid)
        if hook is None:
            return None
        status, error = await _deliver(hook, {"event": "test", "data": {"ok": True}})
        _record_outcome(hook, status, error)
        db.commit()
        return status, error
    finally:
        db.close()


async def fire(event: str, payload: dict) -> None:
    """Send one event to matching enabled hooks without retrying uncertain outcomes."""
    db = SessionLocal()
    try:
        hooks = db.query(Webhook).filter(Webhook.enabled == True).all()
        targets = [hook for hook in hooks if event in hook.events_list()]
        if not targets:
            return
        body = {"event": event, "data": payload}
        for hook in targets:
            status, error = await _deliver(hook, body)
            _record_outcome(hook, status, error)
        db.commit()
    finally:
        db.close()
