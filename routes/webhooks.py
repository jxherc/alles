import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import SessionLocal, Webhook, get_db

router = APIRouter(prefix="/api")
log = logging.getLogger("aide.webhooks")

_VALID_EVENTS = {"message", "research_done", "session_created", "session_renamed"}


def _fmt(w: Webhook) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "url": w.url,
        "events": w.events_list(),
        "enabled": w.enabled,
        "secret": w.secret or "",  # shown so the receiver can verify the signature
        "last_status": w.last_status or "",
        "last_error": w.last_error or "",
        "last_triggered": w.last_triggered.isoformat() if w.last_triggered else None,
        "created_at": w.created_at.isoformat(),
    }


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


@router.get("/webhooks")
def list_webhooks(db: DbSession = Depends(get_db)):
    return [_fmt(w) for w in db.query(Webhook).all()]


class WebhookBody(BaseModel):
    name: str
    url: str
    events: list[str] = ["message"]
    enabled: bool = True


@router.post("/webhooks")
def create_webhook(body: WebhookBody, db: DbSession = Depends(get_db)):
    events = [e for e in body.events if e in _VALID_EVENTS]
    w = Webhook(
        name=body.name,
        url=body.url,
        events=json.dumps(events),
        enabled=body.enabled,
        secret=secrets.token_hex(16),
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return _fmt(w)


@router.patch("/webhooks/{wid}")
def update_webhook(wid: str, body: WebhookBody, db: DbSession = Depends(get_db)):
    w = db.get(Webhook, wid)
    if not w:
        raise HTTPException(404)
    w.name = body.name
    w.url = body.url
    w.events = json.dumps([e for e in body.events if e in _VALID_EVENTS])
    w.enabled = body.enabled
    db.commit()
    return _fmt(w)


@router.delete("/webhooks/{wid}")
def delete_webhook(wid: str, db: DbSession = Depends(get_db)):
    w = db.get(Webhook, wid)
    if not w:
        raise HTTPException(404)
    db.delete(w)
    db.commit()
    return {"ok": True}


@router.get("/webhooks/events")
def valid_events():
    return sorted(_VALID_EVENTS)


@router.post("/webhooks/{wid}/test")
async def test_webhook(wid: str):
    """send a sample payload so the user can confirm the endpoint receives + verifies it."""
    db = SessionLocal()
    try:
        w = db.get(Webhook, wid)
        if not w:
            raise HTTPException(404)
        status, err = await _deliver(w, {"event": "test", "data": {"ok": True}})
        w.last_status, w.last_error, w.last_triggered = status, err, datetime.utcnow()
        db.commit()
        return {"status": status, "error": err}
    finally:
        db.close()


async def fire(event: str, payload: dict):
    """fire all enabled webhooks for an event — call from routes, fire-and-forget"""
    db = SessionLocal()
    try:
        hooks = db.query(Webhook).filter(Webhook.enabled == True).all()
        targets = [h for h in hooks if event in h.events_list()]
        if not targets:
            return
        body = {"event": event, "data": payload}
        for h in targets:
            status, err = await _deliver(h, body)
            h.last_status, h.last_error, h.last_triggered = status, err, datetime.utcnow()
        db.commit()
    finally:
        db.close()
