from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from core.database import get_db
from core.settings import load_settings
from services import codeindex

router = APIRouter(prefix="/api/code")


def _root() -> str:
    # index the agent's working dir if set, else the repo root
    cwd = (load_settings().get("agent_cwd") or "").strip()
    return cwd or str(Path(__file__).resolve().parent.parent)


@router.get("/search")
def code_search(q: str = "", k: int = 8, db: DbSession = Depends(get_db)):
    return {"query": q, "hits": codeindex.search(db, q, k)}


@router.post("/reindex")
def code_reindex(db: DbSession = Depends(get_db)):
    root = _root()
    return {"indexed": codeindex.reindex(db, root), "root": root}
