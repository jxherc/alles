import json
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, Connection

router = APIRouter(prefix="/api")


def _mask(t: str) -> str:
    if not t:
        return ""
    return (t[:4] + "…" + t[-4:]) if len(t) > 8 else "set"


@router.get("/connections")
def list_conns(db: DbSession = Depends(get_db)):
    rows = db.query(Connection).order_by(Connection.service).all()
    return [
        {
            "id": c.id,
            "service": c.service,
            "token_masked": _mask(c.token),
            "connected": bool(c.token),
            "meta": json.loads(c.meta or "{}"),
        }
        for c in rows
    ]


class ConnBody(BaseModel):
    service: str
    token: str = ""
    meta: dict = {}


@router.post("/connections")
def add_conn(body: ConnBody, db: DbSession = Depends(get_db)):
    svc = body.service.strip().lower()
    if not svc:
        raise HTTPException(400, "service required")
    c = db.query(Connection).filter(Connection.service == svc).first()
    if not c:
        c = Connection(service=svc)
        db.add(c)
    c.token = body.token.strip()
    c.meta = json.dumps(body.meta or {})
    db.commit()
    db.refresh(c)
    return {"id": c.id, "service": c.service, "connected": bool(c.token)}


@router.delete("/connections/{conn_id}")
def del_conn(conn_id: str, db: DbSession = Depends(get_db)):
    c = db.get(Connection, conn_id)
    if c:
        db.delete(c)
        db.commit()
    return {"ok": True}


@router.get("/connections/{service}/test")
async def test_conn(service: str):
    service = service.lower()
    if service == "github":
        from services.agent_tools import _github_api

        r = await _github_api("GET", "/user")
        if r.get("error"):
            return {"ok": False, "error": r.get("output", "failed")}
        try:
            login = json.loads(r["output"]).get("login", "?")
        except Exception:
            login = "?"
        return {"ok": True, "user": login}
    return {"ok": False, "error": f"no test available for {service}"}
