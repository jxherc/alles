from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from services.memory_store import (
    add_memory,
    get_all_memories,
    delete_memory,
    update_memory,
    search_memories,
    debug_search,
)

router = APIRouter(prefix="/api")


# GET /api/memories
@router.get("/memories")
def list_memories():
    return get_all_memories()


class AddMemory(BaseModel):
    text: str
    category: str = ""
    pinned: bool = False


# POST /api/memories
@router.post("/memories")
def create_memory(body: AddMemory):
    if not body.text.strip():
        raise HTTPException(400, "text required")
    return add_memory(body.text, category=body.category, pinned=body.pinned)


class PatchMemory(BaseModel):
    text: Optional[str] = None
    category: Optional[str] = None
    pinned: Optional[bool] = None


# PATCH /api/memories/{id}
@router.patch("/memories/{mid}")
def patch_memory(mid: str, body: PatchMemory):
    m = update_memory(mid, text=body.text or "", pinned=body.pinned, category=body.category or "")
    if not m:
        raise HTTPException(404)
    return m


# DELETE /api/memories/{id}
@router.delete("/memories/{mid}")
def remove_memory(mid: str):
    if not delete_memory(mid):
        raise HTTPException(404)
    return {"ok": True}


class SearchQuery(BaseModel):
    query: str
    top_k: int = 6


# POST /api/memories/search
@router.post("/memories/search")
def search(body: SearchQuery):
    return search_memories(body.query, top_k=body.top_k)


# POST /api/memories/debug — show which memories fire for a query + scores
@router.post("/memories/debug")
def debug(body: SearchQuery):
    """relevance debugging: every memory ranked with its score, base similarity,
    category boost, and the retrieval method (vector vs keyword fallback)."""
    return debug_search(body.query, top_k=body.top_k)


class ExtractRequest(BaseModel):
    session_id: str
    max_memories: int = 10


# POST /api/memories/extract — LLM-driven extraction from session history
@router.post("/memories/extract")
async def extract_from_session(body: ExtractRequest, bg: BackgroundTasks):
    from core.database import SessionLocal
    from services.llm import simple_complete

    db = SessionLocal()
    try:
        from core.database import Session

        s = db.get(Session, body.session_id)
        if not s:
            raise HTTPException(404, "session not found")
        msgs = list(s.messages)[-40:]  # last 40 msgs
        if not msgs:
            return {"extracted": 0}

        convo = "\n".join(f"{m.role.upper()}: {m.content[:400]}" for m in msgs)
    finally:
        db.close()

    # find a working endpoint
    from core.database import SessionLocal as SL, ModelEndpoint

    db2 = SL()
    try:
        ep = db2.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
        if not ep:
            raise HTTPException(400, "no endpoint available for extraction")
        base_url, api_key = ep.base_url, ep.api_key
        model = ep.models_list()[0] if ep.models_list() else ""
        if not model:
            raise HTTPException(400, "no model available")
    finally:
        db2.close()

    prompt = [
        {
            "role": "system",
            "content": (
                "Extract factual memories about the user from the conversation. "
                f"Return up to {body.max_memories} bullet points, one per line, starting with '- '. "
                "Only include facts explicitly stated by the user (name, preferences, habits, goals, etc). "
                "No commentary, just the bullet points."
            ),
        },
        {"role": "user", "content": convo},
    ]

    raw = await simple_complete(prompt, base_url, api_key, model, max_tokens=512)

    # parse lines starting with "- " or "1. " etc
    import re

    lines = [re.sub(r"^[-*\d.]+\s*", "", l).strip() for l in raw.splitlines()]
    lines = [l for l in lines if len(l) > 10]

    count = 0
    for line in lines[: body.max_memories]:
        add_memory(line, source="extracted", session_id=body.session_id)
        count += 1

    return {"extracted": count, "memories": lines[: body.max_memories]}
