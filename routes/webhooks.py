import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Webhook, get_db
from services.webhook_delivery import send_test

router = APIRouter(prefix="/api")

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
    result = await send_test(wid)
    if result is None:
        raise HTTPException(404)
    status, error = result
    return {"status": status, "error": error}
