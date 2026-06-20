"""reusable, persistent, multi-kind text index (1c).

unlike services/rag.py (vault-only, in-memory), this stores chunks + embeddings in
sqlite keyed by (kind, ref) so docs AND code (and more later) share one index.
powers workspace "ask anything" (3d) and codebase semantic search (10a).
embeddings via memory_store._embed (fastembed); falls back to jaccard keyword scoring.
"""

import json
import re

from sqlalchemy import func

from core.database import IndexChunk
from services.memory_store import _cosine, _embed, _jaccard


def _chunk(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text:
        return []
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step)]


def index(db, kind, ref, text) -> int:
    """(re)index a resource — drops any existing chunks for (kind, ref) first."""
    kind = (kind or "").strip()
    ref = (ref or "").strip()
    db.query(IndexChunk).filter_by(kind=kind, ref=ref).delete()
    chunks = [c for c in _chunk(text) if c.strip()]
    if not chunks:
        db.commit()
        return 0
    vecs = _embed(chunks)
    for i, c in enumerate(chunks):
        v = json.dumps(vecs[i]) if vecs else ""
        db.add(IndexChunk(kind=kind, ref=ref, chunk_no=i, text=c, vec=v))
    db.commit()
    return len(chunks)


def remove(db, kind, ref) -> int:
    n = db.query(IndexChunk).filter_by(kind=(kind or "").strip(), ref=(ref or "").strip()).delete()
    db.commit()
    return n


def search(db, query, kind=None, k: int = 5) -> list[dict]:
    q = db.query(IndexChunk)
    if kind:
        q = q.filter_by(kind=kind)
    rows = q.all()
    if not rows:
        return []
    qv = _embed([query]) if query else None
    scored = []
    if qv and any(r.vec for r in rows):
        qvec = qv[0]
        for r in rows:
            if not r.vec:
                continue
            try:
                v = json.loads(r.vec)
            except Exception:
                continue
            scored.append((_cosine(qvec, v), r))
    else:
        for r in rows:
            scored.append((_jaccard(query or "", r.text), r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"kind": r.kind, "ref": r.ref, "chunk": r.text, "score": round(s, 4)}
        for s, r in scored[:k]
        if s > 0
    ]


def reindex_kind(db, kind, items) -> int:
    """wipe a whole kind and rebuild from items = iterable of (ref, text)."""
    db.query(IndexChunk).filter_by(kind=kind).delete()
    db.commit()
    n = 0
    for ref, text in items:
        n += index(db, kind, ref, text)
    return n


def stats(db) -> dict:
    rows = db.query(IndexChunk.kind, func.count(IndexChunk.id)).group_by(IndexChunk.kind).all()
    return {k: c for k, c in rows}
