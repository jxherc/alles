"""generic text-index API (1c) — search + reindex over the reusable IndexChunk store."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from core.database import get_db
from services import textindex, vault_md

router = APIRouter(prefix="/api/index")


@router.get("/search")
def search(q: str = "", kind: str = "", k: int = 5, db: DbSession = Depends(get_db)):
    return {"hits": textindex.search(db, q, kind=kind or None, k=k)}


def _collect_docs():
    from services import journal_vault

    base = vault_md.vault_dir()  # dynamic so a patched vault dir is honored
    items = []
    for p in base.rglob("*.md"):
        rel = str(p.relative_to(base)).replace("\\", "/")
        rel_parts = p.relative_to(base).parts
        if any(part.startswith((".", "_")) for part in rel_parts):
            continue
        if rel_parts and rel_parts[0] == "Notes":  # notes are the "note" kind, not "doc"
            continue
        if journal_vault.is_daily(rel):  # diary daily notes are the "journal" kind — never "doc"
            continue
        try:
            items.append((rel, p.read_text("utf-8", errors="replace")))
        except Exception:
            pass
    return items


@router.post("/reindex")
def reindex(db: DbSession = Depends(get_db)):
    items = _collect_docs()
    n = textindex.reindex_kind(db, "doc", items)
    return {"indexed": n, "docs": len(items), "stats": textindex.stats(db)}
