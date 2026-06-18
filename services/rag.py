"""
RAG over your vault docs — chunk → embed → retrieve → answer with cited sources.
reuses memory_store's fastembed embedder (with a jaccard fallback when it's not
installed). the index is built lazily and cached; /reindex rebuilds it.
"""

import re
import logging

from services.memory_store import _embed, _cosine, _jaccard
from services.vault_md import vault_dir

log = logging.getLogger("aide.rag")

_index = None  # list[{"path","chunk","vec"}] — None means "not built yet"


def _chunk(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text:
        return []
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step)]


def _collect() -> list[tuple[str, str]]:
    """(rel-path, text) for every real markdown doc in the vault (skips _assets/
    _templates/dotfiles)."""
    base = vault_dir()
    docs = []
    for p in base.rglob("*.md"):
        if any(part.startswith((".", "_")) for part in p.relative_to(base).parts):
            continue
        try:
            docs.append(
                (
                    str(p.relative_to(base)).replace("\\", "/"),
                    p.read_text("utf-8", errors="replace"),
                )
            )
        except Exception:
            pass
    return docs


def build_index() -> int:
    global _index
    chunks = [
        {"path": path, "chunk": c} for path, text in _collect() for c in _chunk(text) if c.strip()
    ]
    if not chunks:
        _index = []
        return 0
    vecs = _embed([c["chunk"] for c in chunks])
    for i, c in enumerate(chunks):
        c["vec"] = vecs[i] if vecs else None
    _index = chunks
    log.info("rag index built: %d chunks", len(chunks))
    return len(chunks)


def _ensure():
    if _index is None:
        build_index()
    return _index


def retrieve(query: str, k: int = 5) -> list[dict]:
    idx = _ensure()
    if not idx:
        return []
    qv = _embed([query])
    if qv and idx[0].get("vec") is not None:
        q = qv[0]
        scored = [(_cosine(q, c["vec"]), c) for c in idx if c.get("vec") is not None]
    else:
        scored = [(_jaccard(query, c["chunk"]), c) for c in idx]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"path": c["path"], "chunk": c["chunk"], "score": round(s, 3)}
        for s, c in scored[:k]
        if s > 0
    ]


async def answer(query: str, base_url: str, api_key: str, model: str, k: int = 5) -> dict:
    hits = retrieve(query, k)
    if not hits:
        return {"answer": "I couldn't find anything relevant in your docs.", "sources": []}
    from services.llm import simple_complete

    ctx = "\n\n".join(f"[{i + 1}] ({h['path']})\n{h['chunk']}" for i, h in enumerate(hits))
    msgs = [
        {
            "role": "system",
            "content": (
                "Answer the question using ONLY the document excerpts provided. Cite sources "
                "inline as [1], [2] matching the excerpt numbers. If the excerpts don't contain "
                "the answer, say so plainly. Be concise and accurate."
            ),
        },
        {"role": "user", "content": f"Excerpts:\n{ctx}\n\nQuestion: {query}"},
    ]
    text = await simple_complete(msgs, base_url, api_key, model, max_tokens=900)
    seen, sources = set(), []
    for h in hits:
        if h["path"] not in seen:
            seen.add(h["path"])
            sources.append(h["path"])
    return {"answer": (text or "").strip(), "sources": sources}
