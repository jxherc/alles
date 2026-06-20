"""
memory storage + semantic search.
tries fastembed for vector search, falls back to jaccard if unavailable.
"""

import re, math, logging
from typing import Optional
from core.database import SessionLocal, Memory

log = logging.getLogger("aide.memory")

# ── vector backend (optional) ────────────────────────────────────────────────

_embed_model = None
_embed_ready = False


def _get_embedder():
    global _embed_model, _embed_ready
    if _embed_ready:
        return _embed_model
    try:
        from fastembed import TextEmbedding

        _embed_model = TextEmbedding("BAAI/bge-small-en-v1.5")
        _embed_ready = True
        log.info("fastembed loaded — vector memory search active")
    except Exception as e:
        log.warning(f"fastembed unavailable, using keyword fallback: {e}")
        _embed_model = None
        _embed_ready = True  # don't retry
    return _embed_model


def _embed(texts: list[str]) -> list[list[float]] | None:
    model = _get_embedder()
    if not model:
        return None
    try:
        # cast to py float — fastembed yields numpy float32 which json.dumps chokes on
        return [[float(x) for x in v] for v in model.embed(texts)]
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── keyword fallback ──────────────────────────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ── category boosting ─────────────────────────────────────────────────────────

_CATEGORY_PATTERNS = {
    "identity": r"\b(i am|my name|i\'m|i work|i live|i study|i go to)\b",
    "preference": r"\b(i like|i love|i prefer|i hate|i dislike|i enjoy|i use|my favorite)\b",
    "task": r"\b(remind|todo|task|need to|should|want to|going to|will)\b",
    "contact": r"\b(email|phone|address|contact|reach|number)\b",
}


def _detect_category(text: str) -> str:
    tl = text.lower()
    for cat, pat in _CATEGORY_PATTERNS.items():
        if re.search(pat, tl):
            return cat
    return "general"


_QUERY_BOOST = {
    # query category → memory categories that get boosted
    "identity": {"identity": 0.4},
    "contact": {"contact": 0.4, "identity": 0.2},
    "preference": {"preference": 0.3},
    "task": {"task": 0.3},
}


# ── public api ────────────────────────────────────────────────────────────────


def add_memory(
    text: str,
    category: str = "",
    source: str = "manual",
    session_id: str = "",
    pinned: bool = False,
) -> dict:
    db = SessionLocal()
    try:
        cat = category or _detect_category(text)
        m = Memory(
            text=text.strip(),
            category=cat,
            source=source,
            session_id=session_id or None,
            pinned=pinned,
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        return _fmt(m)
    finally:
        db.close()


def get_all_memories() -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(Memory).order_by(Memory.timestamp.desc()).all()
        return [_fmt(m) for m in rows]
    finally:
        db.close()


def delete_memory(mid: str) -> bool:
    db = SessionLocal()
    try:
        m = db.get(Memory, mid)
        if not m:
            return False
        db.delete(m)
        db.commit()
        return True
    finally:
        db.close()


def update_memory(
    mid: str, text: str = "", pinned: Optional[bool] = None, category: str = ""
) -> dict | None:
    db = SessionLocal()
    try:
        m = db.get(Memory, mid)
        if not m:
            return None
        if text:
            m.text = text.strip()
        if category:
            m.category = category
        if pinned is not None:
            m.pinned = pinned
        db.commit()
        db.refresh(m)
        return _fmt(m)
    finally:
        db.close()


def search_memories(query: str, top_k: int = 6) -> list[dict]:
    db = SessionLocal()
    try:
        all_mems = db.query(Memory).all()
        if not all_mems:
            return []

        # pinned always go in first
        pinned = [m for m in all_mems if m.pinned]
        rest = [m for m in all_mems if not m.pinned]

        q_cat = _detect_category(query)
        boosts = _QUERY_BOOST.get(q_cat, {})

        vecs = _embed([query] + [m.text for m in rest])
        if vecs:
            q_vec = vecs[0]
            scored = []
            for i, m in enumerate(rest):
                sim = _cosine(q_vec, vecs[i + 1])
                sim += boosts.get(m.category, 0.0)
                scored.append((sim, m))
        else:
            # jaccard fallback
            scored = []
            for m in rest:
                sim = _jaccard(query, m.text)
                sim += boosts.get(m.category, 0.0)
                scored.append((sim, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [m for _, m in scored[: top_k - len(pinned)]]

        return [_fmt(m) for m in pinned] + [_fmt(m) for m in top]
    finally:
        db.close()


def inject_memories(query: str, top_k: int = 6) -> str:
    """returns a system-prompt string to inject, or '' if nothing relevant"""
    parts = []

    mems = search_memories(query, top_k=top_k)
    if mems:
        lines = "\n".join(f"- {m['text']}" for m in mems)
        parts.append(f"Relevant things you know about the user:\n{lines}")

    # inject contacts if query mentions a name
    contacts_ctx = _inject_contacts(query)
    if contacts_ctx:
        parts.append(contacts_ctx)

    return "\n\n".join(parts)


def _inject_contacts(query: str) -> str:
    try:
        db = SessionLocal()
        from core.database import Contact

        contacts = db.query(Contact).all()
        db.close()
        if not contacts:
            return ""
        q_lower = query.lower()
        matched = [c for c in contacts if c.name.lower() in q_lower]
        if not matched:
            return ""
        import json

        lines = []
        for c in matched:
            parts = [c.name]
            if c.email:
                parts.append(f"email: {c.email}")
            if c.phone:
                parts.append(f"phone: {c.phone}")
            if c.notes:
                parts.append(f"notes: {c.notes}")
            lines.append(", ".join(parts))
        return "Contact info:\n" + "\n".join(f"- {l}" for l in lines)
    except Exception:
        return ""


def _fmt(m: Memory) -> dict:
    return {
        "id": m.id,
        "text": m.text,
        "category": m.category,
        "source": m.source,
        "session_id": m.session_id,
        "pinned": m.pinned,
        "timestamp": m.timestamp.isoformat(),
    }
