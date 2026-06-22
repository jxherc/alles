from fastapi import APIRouter
from pydantic import BaseModel

from core.database import SessionLocal
from services import personal_index

router = APIRouter(prefix="/api/recall")


class ReindexBody(BaseModel):
    kind: str | None = None


@router.get("/stats")
def stats():
    db = SessionLocal()
    try:
        return personal_index.stats(db)
    finally:
        db.close()


@router.post("/reindex")
def reindex(body: ReindexBody):
    db = SessionLocal()
    try:
        if body.kind:
            return {"kind": body.kind, "indexed": personal_index.reindex_source(db, body.kind)}
        return {"indexed": personal_index.reindex_all(db)}
    finally:
        db.close()


@router.post("/clear")
def clear():
    db = SessionLocal()
    try:
        return {"removed": personal_index.clear(db)}
    finally:
        db.close()
