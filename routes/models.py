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
    base_url: str | None = None
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
    if body.base_url is not None:      ep.base_url = body.base_url
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


# the static Anthropic list is only a FALLBACK for keys that can't hit the
# models API — the live probe below is what keeps lists current
_ANTHROPIC_FALLBACK = ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]


async def fetch_provider_models(ep: ModelEndpoint) -> list[str]:
    """ask the provider what models exist right now. raises on failure."""
    provider = detect_provider(ep.base_url)
    base = ep.base_url.rstrip("/")

    if provider == "anthropic":
        # Anthropic has a real models API — use it so new releases show up on
        # their own; the static list is only for keys that can't reach it
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(base + "/v1/models?limit=100", headers={
                    "x-api-key": ep.api_key or "",
                    "anthropic-version": "2023-06-01",
                })
                r.raise_for_status()
                models = [m["id"] for m in r.json().get("data", [])]
                if models:
                    return models
        except Exception:
            pass
        return list(_ANTHROPIC_FALLBACK)

    if provider == "ollama":
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(base + "/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]

    headers = {"content-type": "application/json"}
    if ep.api_key:
        headers["authorization"] = f"Bearer {ep.api_key}"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(base + "/v1/models", headers=headers)
        r.raise_for_status()
        data = r.json()
    return [m for m in (x["id"] for x in data.get("data", [])) if _is_chat_model(m)]


async def refresh_all_model_lists():
    """background re-probe of every enabled endpoint, so new provider models
    appear without anyone clicking refresh. failures keep the old cache."""
    import logging
    log = logging.getLogger("aide.models")
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        for ep in db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all():
            try:
                models = await fetch_provider_models(ep)
            except Exception as e:
                log.info(f"model refresh skipped for {ep.name}: {e}")
                continue
            if models and set(models) != set(ep.models_list()):
                added = [m for m in models if m not in ep.models_list()]
                ep.cached_models = json.dumps(models)
                db.commit()
                if added:
                    log.info(f"{ep.name}: new models available — {', '.join(added[:5])}")
    finally:
        db.close()


# POST /api/models/endpoint/{id}/probe — fetch model list from provider
@router.post("/models/endpoint/{ep_id}/probe")
async def probe_endpoint(ep_id: str, db: DbSession = Depends(get_db)):
    ep = db.get(ModelEndpoint, ep_id)
    if not ep:
        raise HTTPException(404)
    try:
        models = await fetch_provider_models(ep)
    except Exception as e:
        raise HTTPException(502, f"probe failed: {e}")
    ep.cached_models = json.dumps(models)
    db.commit()
    return {"models": models}
