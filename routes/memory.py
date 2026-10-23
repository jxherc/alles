import json
import re
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from core.api_errors import ApiError
from core.auth import require_recent_owner
from services.memory_store import (
    MemoryPolicyError,
    accept_memory,
    add_memory,
    clear_memories,
    debug_search,
    delete_memory,
    get_all_memories,
    search_memories,
    update_memory,
)

router = APIRouter(prefix="/api")


@router.get("/memory/distilled")
def list_distilled():
    """the auto-distilled user-model facts (1c) - source=distilled, highest confidence first."""
    from core.database import Memory, SessionLocal

    db = SessionLocal()
    try:
        rows = (
            db.query(Memory)
            .filter(Memory.source == "distilled")
            .order_by(Memory.confidence.desc(), Memory.timestamp.desc())
            .all()
        )
        return [
            {
                "id": m.id,
                "text": m.text,
                "category": m.category,
                "confidence": m.confidence,
                "provenance": m.provenance,
                "vetoed": m.vetoed,
                "pinned": m.pinned,
                "scope": m.scope or "global",
                "project_id": m.project_id,
                "status": m.status or "active",
                "trust": m.trust or "derived",
            }
            for m in rows
        ]
    finally:
        db.close()


@router.post("/memory/distill/run")
async def distill_run():
    """manual 'distill now' - run the user-model distillation pass on demand (parity with the
    insights/proactive run-now buttons). returns how many new facts were learned."""
    from core.database import SessionLocal
    from services import user_model

    db = SessionLocal()
    try:
        n = await user_model.distill_async(db)
        return {"ran": True, "count": n}
    finally:
        db.close()


@router.post("/memory/{mid}/veto")
def veto_distilled(mid: str):
    """hide a distilled fact + keep it from being re-distilled."""
    from core.database import SessionLocal
    from services import user_model

    db = SessionLocal()
    try:
        return {"ok": user_model.veto(db, mid)}
    finally:
        db.close()


# GET /api/memories
@router.get("/memories")
def list_memories():
    return get_all_memories()


class AddMemory(BaseModel):
    text: str
    category: str = ""
    pinned: bool = False
    scope: str = "global"
    project_id: str = ""


# POST /api/memories
@router.post("/memories")
def create_memory(body: AddMemory):
    if not body.text.strip():
        raise HTTPException(400, "text required")
    try:
        return add_memory(
            body.text,
            category=body.category,
            pinned=body.pinned,
            scope=body.scope,
            project_id=body.project_id,
            provenance=json.dumps({"kind": "owner_request"}),
        )
    except MemoryPolicyError as exc:
        raise ApiError(409, "memory_disabled", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(400, "invalid_memory_scope", str(exc)) from exc


class PatchMemory(BaseModel):
    text: Optional[str] = None
    category: Optional[str] = None
    pinned: Optional[bool] = None
    scope: Optional[str] = None
    project_id: Optional[str] = None


# PATCH /api/memories/{id}
@router.patch("/memories/{mid}")
def patch_memory(mid: str, body: PatchMemory):
    try:
        m = update_memory(
            mid,
            text=body.text or "",
            pinned=body.pinned,
            category=body.category or "",
            scope=body.scope or "",
            project_id=body.project_id,
        )
    except ValueError as exc:
        raise ApiError(400, "invalid_memory_scope", str(exc)) from exc
    if not m:
        raise HTTPException(404)
    return m


# DELETE /api/memories/{id}
@router.delete("/memories/{mid}")
def remove_memory(mid: str):
    if not delete_memory(mid):
        raise HTTPException(404)
    return {"ok": True}


@router.post("/memories/{mid}/accept")
def approve_memory(mid: str):
    try:
        memory = accept_memory(mid)
    except MemoryPolicyError as exc:
        raise ApiError(409, "memory_disabled", str(exc)) from exc
    if not memory:
        raise ApiError(404, "memory_not_found", "memory not found")
    return memory


@router.delete("/memories", dependencies=[Depends(require_recent_owner)])
def clear_all_memories():
    return {"ok": True, "deleted": clear_memories()}


@router.get("/memories/export", dependencies=[Depends(require_recent_owner)])
def export_memories():
    payload = json.dumps(get_all_memories(), ensure_ascii=False, indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="alles-memories.json"'},
    )


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
    from services.memory_store import memory_policy

    policy = memory_policy()
    if policy == "off":
        raise ApiError(409, "memory_disabled", "memory is off")

    from services import incognito

    if incognito.get_session(body.session_id):
        raise ApiError(409, "incognito_memory_forbidden", "incognito does not use memory")

    db = SessionLocal()
    try:
        from core.database import Session

        s = db.get(Session, body.session_id)
        if not s:
            raise HTTPException(404, "session not found")
        msgs = [message for message in list(s.messages)[-40:] if message.role == "user"]
        if not msgs:
            return {"extracted": 0}

        owner_texts = [message.content[:400] for message in msgs]
        convo = "\n".join(f"USER: {text}" for text in owner_texts)
        project_id = s.project_id or ""
    finally:
        db.close()

    # find a working endpoint
    from core.database import SessionLocal as SL
    from services.model_resolver import ModelResolutionError, resolve_model

    db2 = SL()
    try:
        try:
            selected = resolve_model(db2, "aide_chat")
        except ModelResolutionError as exc:
            raise ApiError(400, exc.code, str(exc)) from exc
        ep, model = selected.endpoint, selected.model
        base_url, api_key = ep.base_url, ep.api_key
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
    lines = [re.sub(r"^[-*\d.]+\s*", "", l).strip() for l in raw.splitlines()]
    lines = [l for l in lines if len(l) > 10]

    n = max(
        0, body.max_memories
    )  # negative would slice off the newest extracted line instead of capping
    created = []
    if policy == "auto":
        for preference in _direct_preferences(owner_texts)[:n]:
            created.append(
                add_memory(
                    preference,
                    source="auto_owner",
                    session_id=body.session_id,
                    scope="project" if project_id else "global",
                    project_id=project_id,
                    provenance=json.dumps(
                        {"kind": "direct_owner_statement", "session_id": body.session_id}
                    ),
                )
            )
    for line in lines[:n]:
        created.append(
            add_memory(
                line,
                source="extracted",
                session_id=body.session_id,
                scope="project" if project_id else "global",
                project_id=project_id,
                status="suggested",
                provenance=json.dumps(
                    {"kind": "model_suggestion", "session_id": body.session_id, "roles": ["user"]}
                ),
            )
        )

    return {"extracted": len(created), "memories": created}


_LOW_RISK_PREFERENCE = re.compile(
    r"\bI\s+(?:like|love|prefer|enjoy|use)\b[^.!?\n]{1,240}[.!?]?",
    re.IGNORECASE,
)
_SENSITIVE_PREFERENCE = re.compile(
    r"\b(?:password|secret|token|api key|address|phone|email|diagnos|medical|bank|account|card)\b",
    re.IGNORECASE,
)


def _direct_preferences(owner_texts: list[str]) -> list[str]:
    result = []
    for text in owner_texts:
        for match in _LOW_RISK_PREFERENCE.finditer(text):
            value = " ".join(match.group(0).split()).strip()
            if value and not _SENSITIVE_PREFERENCE.search(value) and value not in result:
                result.append(value)
    return result
