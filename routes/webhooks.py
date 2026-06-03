import json, httpx, logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Webhook, SessionLocal

router = APIRouter(prefix="/api")
log = logging.getLogger("aide.webhooks")

_VALID_EVENTS = {"message", "research_done", "session_created", "session_renamed"}

def _fmt(w: Webhook) -> dict:
    return {
        "id": w.id, "name": w.name, "url": w.url,
        "events": w.events_list(), "enabled": w.enabled,
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
    w = Webhook(name=body.name, url=body.url, events=json.dumps(events), enabled=body.enabled)
    db.add(w); db.commit(); db.refresh(w)
    return _fmt(w)

@router.patch("/webhooks/{wid}")
def update_webhook(wid: str, body: WebhookBody, db: DbSession = Depends(get_db)):
    w = db.get(Webhook, wid)
    if not w: raise HTTPException(404)
    w.name = body.name; w.url = body.url
    w.events = json.dumps([e for e in body.events if e in _VALID_EVENTS])
    w.enabled = body.enabled
    db.commit(); return _fmt(w)

@router.delete("/webhooks/{wid}")
def delete_webhook(wid: str, db: DbSession = Depends(get_db)):
    w = db.get(Webhook, wid)
    if not w: raise HTTPException(404)
    db.delete(w); db.commit()
    return {"ok": True}

@router.get("/webhooks/events")
def valid_events():
    return sorted(_VALID_EVENTS)


async def fire(event: str, payload: dict):
    """fire all enabled webhooks for an event — call from routes, fire-and-forget"""
    db = SessionLocal()
    try:
        hooks = db.query(Webhook).filter(Webhook.enabled == True).all()
        targets = [h for h in hooks if event in h.events_list()]
    finally:
        db.close()
    if not targets:
        return
    body = {"event": event, "data": payload}
    async with httpx.AsyncClient(timeout=5) as c:
        for h in targets:
            try:
                await c.post(h.url, json=body)
            except Exception as e:
                log.warning(f"webhook {h.name} failed: {e}")
