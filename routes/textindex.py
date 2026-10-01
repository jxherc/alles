"""generic text-index API (1c) — search + reindex over the reusable IndexChunk store."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.database import get_db
from services import textindex, vault_md

router = APIRouter(prefix="/api/index")


@router.get("/search")
def search(q: str = "", kind: str = "", k: int = 5, db: DbSession = Depends(get_db)):
    return {"hits": textindex.search(db, q, kind=kind or None, k=k)}


@router.post("/reindex")
def reindex(db: DbSession = Depends(get_db)):
    try:
        items = vault_md.indexable_documents()
    except OSError as exc:
        raise ApiError(
            503, "vault_index_unavailable", "could not read every document; search index unchanged"
        ) from exc
    n = textindex.reindex_kind(db, "doc", items)
    return {"indexed": n, "docs": len(items), "stats": textindex.stats(db)}
