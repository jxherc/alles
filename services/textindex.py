"""reusable, persistent, multi-kind text index (1c).

unlike services/rag.py (vault-only, in-memory), this stores chunks + embeddings in
sqlite keyed by (kind, ref) so docs AND code (and more later) share one index.
powers workspace "ask anything" (3d) and codebase semantic search (10a).
embeddings via memory_store._embed (fastembed); falls back to jaccard keyword scoring.
"""

import json
import re

from sqlalchemy import func

from core.database import (
    DEFAULT_LOCAL_STORAGE_LOCATION_ID,
    IndexChunk,
    normalize_file_identity_path,
)
from services.memory_store import _cosine, _embed, _jaccard


def _chunk(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text:
        return []
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step)]


def _identity_filter(query, kind: str, ref: str, location_id: str | None = None):
    if kind != "file":
        return query.filter_by(kind=kind, ref=ref)
    location = location_id or DEFAULT_LOCAL_STORAGE_LOCATION_ID
    normalized = normalize_file_identity_path(ref)
    return query.filter_by(kind=kind, location_id=location, normalized_path=normalized)


def index(db, kind, ref, text, *, location_id: str | None = None) -> int:
    """(re)index a resource — drops any existing chunks for (kind, ref) first."""
    kind = (kind or "").strip()
    ref = (ref or "").strip()
    _identity_filter(db.query(IndexChunk), kind, ref, location_id).delete()
    n = _add_chunks(db, kind, ref, text, location_id=location_id)
    db.commit()
    return n


def _add_chunks(db, kind, ref, text, *, location_id: str | None = None) -> int:
    ref = (ref or "").strip()
    chunks = [c for c in _chunk(text) if c.strip()]
    if not chunks:
        return 0
    vecs = _embed(chunks)
    for i, c in enumerate(chunks):
        v = json.dumps(vecs[i]) if vecs else ""
        row = IndexChunk(kind=kind, ref=ref, chunk_no=i, text=c, vec=v)
        if kind == "file":
            row.location_id = location_id or DEFAULT_LOCAL_STORAGE_LOCATION_ID
            row.normalized_path = normalize_file_identity_path(ref)
        db.add(row)
    return len(chunks)


def remove(db, kind, ref, *, location_id: str | None = None) -> int:
    clean_kind = (kind or "").strip()
    clean_ref = (ref or "").strip()
    n = _identity_filter(db.query(IndexChunk), clean_kind, clean_ref, location_id).delete()
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
    qvec = qv[0] if qv else None
    # score each row by what it actually has: cosine for embedded chunks, keyword overlap
    # for chunks indexed before the embedder was available (vec="") — otherwise those
    # un-embedded chunks get silently dropped the moment ANY chunk has a vector.
    # cosine has a high baseline (bge ~0.5 even for unrelated text) so it needs a real
    # floor (0.6); jaccard keeps the >0 floor. each row passes its own gate.
    scored = []
    for r in rows:
        if qvec and r.vec:
            try:
                s = _cosine(qvec, json.loads(r.vec))
            except Exception:
                continue
            if s > 0.6:
                scored.append((s, r))
        else:
            s = _jaccard(query or "", r.text)
            if s > 0.0:
                scored.append((s, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"kind": r.kind, "ref": r.ref, "chunk": r.text, "score": round(s, 4)}
        for s, r in scored[: max(0, k)]  # negative k would drop the last hit instead of capping
    ]


def search_file_location(db, query: str, location_id: str, k: int = 100) -> list[dict]:
    """Search only one Files location and collapse chunk hits into file rows."""
    location = str(location_id or "").strip()
    if not location:
        raise ValueError("location_id required")
    rows = db.query(IndexChunk).filter_by(kind="file", location_id=location).all()
    query_text = str(query or "").strip()
    if not query_text or not rows:
        return []
    qv = _embed([query_text])
    qvec = qv[0] if qv else None
    best: dict[str, tuple[float, IndexChunk]] = {}
    for row in rows:
        if qvec and row.vec:
            try:
                score = _cosine(qvec, json.loads(row.vec))
            except Exception:
                continue
            if score <= 0.6:
                continue
        else:
            score = _jaccard(query_text, row.text)
            if score <= 0.0:
                continue
        path = normalize_file_identity_path(row.normalized_path or row.ref)
        current = best.get(path)
        if current is None or score > current[0]:
            best[path] = (score, row)
    ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)
    return [
        {
            "path": path,
            "name": path.rsplit("/", 1)[-1],
            "type": "file",
            "snippet": row.text[:280],
            "match": round(score, 4),
        }
        for path, (score, row) in ranked[: max(0, min(int(k), 500))]
    ]


def reindex_kind(db, kind, items) -> int:
    """Rebuild a kind; legacy file calls replace only the default Files location."""
    kind = (kind or "").strip()
    if kind == "file":
        return reindex_file_location(db, DEFAULT_LOCAL_STORAGE_LOCATION_ID, items)
    db.query(IndexChunk).filter_by(kind=kind).delete()
    n = 0
    for ref, text in items:
        n += _add_chunks(db, kind, ref, text)
    db.commit()
    return n


def reindex_file_location(db, location_id: str, items) -> int:
    """Replace only one Files location's index without disturbing other roots."""
    location = str(location_id or "").strip()
    if not location:
        raise ValueError("location_id required")
    db.query(IndexChunk).filter_by(kind="file", location_id=location).delete()
    n = 0
    for ref, text in items:
        n += _add_chunks(db, "file", ref, text, location_id=location)
    db.commit()
    return n


def stats(db) -> dict:
    rows = db.query(IndexChunk.kind, func.count(IndexChunk.id)).group_by(IndexChunk.kind).all()
    return {k: c for k, c in rows}
