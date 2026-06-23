"""1e - cross-domain causal insights API."""

import json

from fastapi import APIRouter

from core.database import Insight, SessionLocal
from services import insights as insights_svc

router = APIRouter(prefix="/api/insights")


@router.get("")
def list_insights():
    db = SessionLocal()
    try:
        rows = (
            db.query(Insight)
            .filter(Insight.dismissed == False)  # noqa: E712
            .order_by(Insight.pinned.desc(), Insight.created_at.desc())
            .limit(20)
            .all()
        )
        return [
            {
                "id": i.id,
                "kind": i.kind,
                "title": i.title,
                "body": i.body,
                "evidence": json.loads(i.evidence or "[]"),
                "pinned": i.pinned,
            }
            for i in rows
        ]
    finally:
        db.close()


@router.post("/{iid}/pin")
def pin(iid: str):
    db = SessionLocal()
    try:
        i = db.get(Insight, iid)
        if not i:
            return {"ok": False}
        i.pinned = not i.pinned
        db.commit()
        return {"ok": True, "pinned": i.pinned}
    finally:
        db.close()


@router.post("/{iid}/dismiss")
def dismiss(iid: str):
    db = SessionLocal()
    try:
        i = db.get(Insight, iid)
        if not i:
            return {"ok": False}
        i.dismissed = True
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/run")
async def run_now():
    """manual generate (run-now) - forces a pass even when the toggle is off."""
    db = SessionLocal()
    try:
        return await insights_svc.generate_async(db, force=True)
    finally:
        db.close()
