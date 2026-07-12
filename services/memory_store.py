"""
memory storage + semantic search.
tries fastembed for vector search, falls back to jaccard if unavailable.
"""

import json
import logging
import math
import re
from datetime import datetime
from typing import Optional

from core.database import Memory, SessionLocal
from core.settings import load_settings

log = logging.getLogger("aide.memory")


class MemoryPolicyError(RuntimeError):
    pass


MEMORY_AGENT_TOOLS = {"memory_search", "memory_add"}


def apply_memory_tool_policy(settings: dict, *, incognito: bool = False) -> dict:
    """Hide long-term-memory tools whenever the conversation cannot use memory."""
    disabled = set(settings.get("disabled_tools") or [])
    if incognito or str(settings.get("memory_policy") or "ask").lower() == "off":
        disabled.update(MEMORY_AGENT_TOOLS)
    settings["disabled_tools"] = sorted(disabled)
    return settings


def memory_policy() -> str:
    value = str(load_settings().get("memory_policy") or "ask").lower()
    return value if value in {"off", "ask", "auto"} else "ask"


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
    scope: str = "global",
    project_id: str = "",
    status: str = "",
    trust: str = "",
    provenance: str = "",
) -> dict:
    if memory_policy() == "off":
        raise MemoryPolicyError("memory is off")
    scope = (scope or "global").strip().lower()
    if scope not in {"global", "project"}:
        raise ValueError("memory scope must be global or project")
    if scope == "project" and not project_id:
        raise ValueError("project memory requires a project")
    owner_source = source in {"manual", "auto_owner"}
    if not status:
        status = "active" if owner_source else "suggested"
    if status not in {"active", "suggested"}:
        raise ValueError("memory status must be active or suggested")
    if not trust:
        trust = "owner" if owner_source else "derived"
    db = SessionLocal()
    try:
        cat = category or _detect_category(text)
        m = Memory(
            text=text.strip(),
            category=cat,
            source=source,
            session_id=session_id or None,
            pinned=pinned,
            scope=scope,
            project_id=project_id or None,
            status=status,
            trust=trust,
            provenance=provenance,
            updated_at=datetime.utcnow(),
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
    mid: str,
    text: str = "",
    pinned: Optional[bool] = None,
    category: str = "",
    scope: str = "",
    project_id: str | None = None,
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
        if scope:
            if scope not in {"global", "project"}:
                raise ValueError("memory scope must be global or project")
            if scope == "project" and not project_id:
                raise ValueError("project memory requires a project")
            m.scope = scope
            m.project_id = project_id if scope == "project" else None
        m.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(m)
        return _fmt(m)
    finally:
        db.close()


def search_memories(query: str, top_k: int = 6, project_id: str = "") -> list[dict]:
    if memory_policy() == "off":
        return []
    db = SessionLocal()
    try:
        query_set = db.query(Memory).filter(
            Memory.vetoed == False,  # noqa: E712
            Memory.status == "active",
        )
        if project_id:
            query_set = query_set.filter(
                (Memory.scope == "global")
                | ((Memory.scope == "project") & (Memory.project_id == project_id))
            )
        else:
            query_set = query_set.filter(Memory.scope == "global")
        all_mems = query_set.all()
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
        top = [m for _, m in scored[: max(0, top_k - len(pinned))]]

        return [_fmt(m) for m in pinned] + [_fmt(m) for m in top]
    finally:
        db.close()


def debug_search(query: str, top_k: int = 10) -> dict:
    """same scoring as search_memories, but exposes the scores + method so you can
    see WHY a memory does/doesn't fire for a query (relevance debugging)."""
    if memory_policy() == "off":
        return {"method": "none", "category": _detect_category(query), "results": []}
    db = SessionLocal()
    try:
        all_mems = (
            db.query(Memory).filter(Memory.status == "active", Memory.scope == "global").all()
        )
        if not all_mems:
            return {"method": "none", "category": _detect_category(query), "results": []}

        q_cat = _detect_category(query)
        boosts = _QUERY_BOOST.get(q_cat, {})

        # score every memory so pinned ones show their relevance too
        vecs = _embed([query] + [m.text for m in all_mems])
        method = "vector" if vecs else "jaccard"
        rows = []
        for i, m in enumerate(all_mems):
            base = _cosine(vecs[0], vecs[i + 1]) if vecs else _jaccard(query, m.text)
            boost = boosts.get(m.category, 0.0)
            rows.append(
                {
                    **_fmt(m),
                    "score": round(base + boost, 4),
                    "base": round(base, 4),
                    "boost": round(boost, 4),
                    "pinned": bool(m.pinned),
                }
            )
        # pinned first (they always inject), then the rest by score
        rows.sort(key=lambda r: (not r["pinned"], -r["score"]))
        return {"method": method, "category": q_cat, "results": rows[:top_k]}
    finally:
        db.close()


def inject_memories(
    query: str,
    top_k: int = 6,
    *,
    project_id: str = "",
    run_id: str = "",
    return_details: bool = False,
):
    """returns a system-prompt string to inject, or '' if nothing relevant"""
    if memory_policy() == "off":
        return ("", []) if return_details else ""
    parts = []

    mems = search_memories(query, top_k=top_k, project_id=project_id)
    if mems:
        lines = "\n".join(f"- {m['text']}" for m in mems)
        parts.append(f"Relevant things you know about the user:\n{lines}")

    # inject contacts if query mentions a name
    contacts_ctx = _inject_contacts(query)
    if contacts_ctx:
        parts.append(contacts_ctx)

    if run_id and mems:
        _mark_used([memory["id"] for memory in mems], run_id)
    text = "\n\n".join(parts)
    if return_details:
        return text, [memory["id"] for memory in mems]
    return text


def accept_memory(mid: str) -> dict | None:
    if memory_policy() == "off":
        raise MemoryPolicyError("memory is off")
    db = SessionLocal()
    try:
        memory = db.get(Memory, mid)
        if not memory:
            return None
        memory.status = "active"
        memory.trust = "reviewed"
        memory.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(memory)
        return _fmt(memory)
    finally:
        db.close()


def clear_memories() -> int:
    db = SessionLocal()
    try:
        count = db.query(Memory).delete(synchronize_session=False)
        db.commit()
        return count
    finally:
        db.close()


def _mark_used(memory_ids: list[str], run_id: str) -> None:
    db = SessionLocal()
    try:
        for memory in db.query(Memory).filter(Memory.id.in_(memory_ids)).all():
            try:
                runs = json.loads(memory.used_in_runs or "[]")
            except (TypeError, ValueError):
                runs = []
            if not isinstance(runs, list):
                runs = []
            if run_id not in runs:
                runs.append(run_id)
            memory.used_in_runs = json.dumps(runs[-100:])
            memory.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


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
    try:
        used_in_runs = json.loads(m.used_in_runs or "[]")
    except (TypeError, ValueError):
        used_in_runs = []
    return {
        "id": m.id,
        "text": m.text,
        "category": m.category,
        "source": m.source,
        "session_id": m.session_id,
        "pinned": m.pinned,
        "timestamp": m.timestamp.isoformat(),
        "created_at": m.timestamp.isoformat(),
        "updated_at": (m.updated_at or m.timestamp).isoformat(),
        "scope": m.scope or "global",
        "project_id": m.project_id,
        "status": m.status or "active",
        "trust": m.trust or "owner",
        "provenance": m.provenance or "",
        "used_in_runs": used_in_runs if isinstance(used_in_runs, list) else [],
    }
