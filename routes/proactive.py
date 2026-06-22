from fastapi import APIRouter

from core.database import ProactiveItem, SessionLocal
from services import proactive

router = APIRouter(prefix="/api/proactive")


@router.get("")
def list_items():
    db = SessionLocal()
    try:
        rows = (
            db.query(ProactiveItem)
            .filter(ProactiveItem.dismissed == False)  # noqa: E712
            .order_by(ProactiveItem.score.desc(), ProactiveItem.created_at.desc())
            .limit(12)
            .all()
        )
        return [
            {"id": r.id, "category": r.category, "title": r.title, "body": r.body,
             "link": r.link, "score": r.score, "urgency": r.urgency, "status": r.status}
            for r in rows
        ]
    finally:
        db.close()


@router.post("/{item_id}/dismiss")
def dismiss(item_id: str):
    db = SessionLocal()
    try:
        it = db.get(ProactiveItem, item_id)
        if not it:
            return {"ok": False}
        it.dismissed = True
        it.status = "dismissed"
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/run")
async def run_now():
    """manual 'run now' - bypasses the toggle/interval so it can be tested."""
    return await proactive.run(force=True)
