"""
web push subscriptions — the browser registers here, the reminder loop (and
anything else) broadcasts through `broadcast()`.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, SessionLocal, PushSubscription
from services import webpush

router = APIRouter(prefix="/api")
log = logging.getLogger("aide.push")


@router.get("/push/vapid-key")
def vapid_key():
    return {"key": webpush.public_key_b64u()}


class SubscribeBody(BaseModel):
    endpoint: str
    keys: dict   # {p256dh, auth}


@router.post("/push/subscribe")
def subscribe(body: SubscribeBody, db: DbSession = Depends(get_db)):
    p256dh = body.keys.get("p256dh", "")
    auth = body.keys.get("auth", "")
    if not body.endpoint or not p256dh or not auth:
        raise HTTPException(400, "incomplete subscription")
    sub = db.query(PushSubscription).filter_by(endpoint=body.endpoint).first()
    if sub:
        sub.p256dh, sub.auth = p256dh, auth
    else:
        db.add(PushSubscription(endpoint=body.endpoint, p256dh=p256dh, auth=auth))
    db.commit()
    return {"ok": True}


class UnsubscribeBody(BaseModel):
    endpoint: str


@router.post("/push/unsubscribe")
def unsubscribe(body: UnsubscribeBody, db: DbSession = Depends(get_db)):
    db.query(PushSubscription).filter_by(endpoint=body.endpoint).delete()
    db.commit()
    return {"ok": True}


@router.get("/push/status")
def status(db: DbSession = Depends(get_db)):
    return {"subscriptions": db.query(PushSubscription).count()}


@router.post("/push/test")
async def test_push():
    n = await broadcast({"title": "alles", "body": "push notifications are working",
                         "url": "/", "tag": "push-test"})
    if n == 0:
        raise HTTPException(400, "no push subscriptions registered")
    return {"ok": True, "sent": n}


async def broadcast(payload: dict) -> int:
    """send to every registered browser, pruning dead subscriptions. returns
    how many deliveries were attempted against live subscriptions."""
    db = SessionLocal()
    try:
        subs = db.query(PushSubscription).all()
        sent = 0
        for s in subs:
            alive = await webpush.send_push(
                {"endpoint": s.endpoint, "p256dh": s.p256dh, "auth": s.auth}, payload)
            if alive:
                sent += 1
            else:
                db.delete(s)
        db.commit()
        return sent
    finally:
        db.close()
