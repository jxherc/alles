import json, httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, ModelEndpoint
from services.llm import detect_provider

router = APIRouter(prefix="/api")

_NON_CHAT = ("embedding", "tts", "whisper", "dall-e", "moderation",
             "rerank", "clip", "stable-diffusion", "text-embedding")

def _is_chat_model(mid: str) -> bool:
    ml = mid.lower()
    return not any(x in ml for x in _NON_CHAT)

def _fmt_endpoint(ep: ModelEndpoint) -> dict:
    import json as _json
    try:
        vision = _json.loads(ep.vision_models or "[]")
    except Exception:
        vision = []
    return {
        "id": ep.id,
        "name": ep.name,
        "base_url": ep.base_url,
        "enabled": ep.enabled,
        "provider": detect_provider(ep.base_url),
        "models": ep.models_list(),
        "vision_models": vision,
        "created_at": ep.created_at.isoformat(),
    }


# GET /api/models  — all enabled endpoints with cached model lists
@router.get("/models")
def list_models(db: DbSession = Depends(get_db)):
    eps = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
    return [_fmt_endpoint(ep) for ep in eps]


class AddEndpoint(BaseModel):
    name: str
    base_url: str
    api_key: str = ""


# POST /api/models/endpoint
@router.post("/models/endpoint")
def add_endpoint(body: AddEndpoint, db: DbSession = Depends(get_db)):
    ep = ModelEndpoint(name=body.name, base_url=body.base_url.rstrip("/"), api_key=body.api_key)
    db.add(ep)
    db.commit()
    db.refresh(ep)
    return _fmt_endpoint(ep)


class PatchEndpoint(BaseModel):
    name: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    vision_models: str | None = None  # json list string


# PATCH /api/models/endpoint/{id}
@router.patch("/models/endpoint/{ep_id}")
def patch_endpoint(ep_id: str, body: PatchEndpoint, db: DbSession = Depends(get_db)):
    ep = db.get(ModelEndpoint, ep_id)
    if not ep:
        raise HTTPException(404)
    if body.name is not None:          ep.name = body.name
    if body.api_key is not None:       ep.api_key = body.api_key
    if body.enabled is not None:       ep.enabled = body.enabled
    if body.vision_models is not None: ep.vision_models = body.vision_models
    db.commit()
    return _fmt_endpoint(ep)


# DELETE /api/models/endpoint/{id}
@router.delete("/models/endpoint/{ep_id}")
def delete_endpoint(ep_id: str, db: DbSession = Depends(get_db)):
    ep = db.get(ModelEndpoint, ep_id)
    if not ep:
        raise HTTPException(404)
    db.delete(ep)
    db.commit()
    return {"ok": True}


# POST /api/models/endpoint/{id}/probe — fetch model list from provider
@router.post("/models/endpoint/{ep_id}/probe")
async def probe_endpoint(ep_id: str, db: DbSession = Depends(get_db)):
    ep = db.get(ModelEndpoint, ep_id)
    if not ep:
        raise HTTPException(404)

    provider = detect_provider(ep.base_url)
    url = ep.base_url.rstrip("/") + "/v1/models"
    headers = {"content-type": "application/json"}
    if ep.api_key:
        headers["authorization"] = f"Bearer {ep.api_key}"

    if provider == "anthropic":
        # anthropic doesn't have a models endpoint — just return known ones
        models = ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"]
        ep.cached_models = json.dumps(models)
        db.commit()
        return {"models": models}

    if provider == "ollama":
        url = ep.base_url.rstrip("/") + "/api/tags"

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        raise HTTPException(502, f"probe failed: {e}")

    if provider == "ollama":
        models = [m["name"] for m in data.get("models", [])]
    else:
        all_models = [m["id"] for m in data.get("data", [])]
        models = [m for m in all_models if _is_chat_model(m)]

    ep.cached_models = json.dumps(models)
    db.commit()
    return {"models": models}
