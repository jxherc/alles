"""daily briefing — preview the digest, or send it to your devices right now."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from core.database import SessionLocal, get_db
from services import briefing

router = APIRouter(prefix="/api")


@router.get("/briefing")
def preview(db: DbSession = Depends(get_db)):
    return briefing.compose_briefing(db)


@router.post("/briefing/send")
async def send_now():
    from routes.push import broadcast

    db = SessionLocal()
    try:
        b = briefing.compose_briefing(db)
    finally:
        db.close()
    n = await broadcast(
        {"title": b["title"], "body": b["body"], "url": "/", "tag": "daily-briefing"}
    )
    return {"ok": True, "sent": n, "briefing": b}
