"""3c - tool chain (macro) CRUD + run."""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import ToolChain, get_db

router = APIRouter(prefix="/api/chains")


def _fmt(c: ToolChain) -> dict:
    try:
        steps = json.loads(c.steps or "[]")
    except ValueError:
        steps = []
    return {"id": c.id, "name": c.name, "steps": steps, "created_at": c.created_at.isoformat()}


@router.get("")
def list_chains(db: DbSession = Depends(get_db)):
    rows = db.query(ToolChain).order_by(ToolChain.created_at.asc()).all()
    return {"chains": [_fmt(c) for c in rows]}


class ChainBody(BaseModel):
    name: str
    steps: list = []


@router.post("")
def create_chain(body: ChainBody, db: DbSession = Depends(get_db)):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    c = ToolChain(name=name, steps=json.dumps(body.steps or []))
    db.add(c)
    db.commit()
    db.refresh(c)
    return _fmt(c)


@router.delete("/{cid}")
def delete_chain(cid: str, db: DbSession = Depends(get_db)):
    c = db.get(ToolChain, cid)
    if not c:
        raise HTTPException(404)
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/{cid}/run")
async def run_chain(cid: str, db: DbSession = Depends(get_db)):
    from services import capabilities, chains

    c = db.get(ToolChain, cid)
    if not c:
        raise HTTPException(404)
    steps = json.loads(c.steps or "[]")
    return await chains.run_chain(steps, invoke=capabilities.invoke)
