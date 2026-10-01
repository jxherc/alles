"""Send one notification to every subscribed browser."""

from core.database import PushSubscription, SessionLocal
from services import webpush


async def broadcast_result(payload: dict) -> dict:
    """Return delivery counts and remove only confirmed dead subscriptions."""
    db = SessionLocal()
    try:
        subs = db.query(PushSubscription).all()
        sent = failed = uncertain = pruned = 0
        for sub in subs:
            state = await webpush.send_push(
                {"endpoint": sub.endpoint, "p256dh": sub.p256dh, "auth": sub.auth}, payload
            )
            if state == "sent":
                sent += 1
            elif state == "gone":
                pruned += 1
                db.delete(sub)
            elif state == "uncertain":
                uncertain += 1
            else:
                failed += 1
        db.commit()
        return {
            "sent": sent,
            "failed": failed,
            "uncertain": uncertain,
            "pruned": pruned,
            "total": len(subs),
        }
    finally:
        db.close()
