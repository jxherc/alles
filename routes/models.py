import json, httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, ModelEndpoint
from services.llm import detect_provider
from services.imagegen import is_image_model, image_models as _image_models

router = APIRouter(prefix="/api")

_NON_CHAT = (
    "embedding",
    "tts",
    "whisper",
    "dall-e",
    "moderation",
    "rerank",
    "clip",
    "stable-diffusion",
    "text-embedding",
)


def _is_chat_model(mid: str) -> bool:
    ml = mid.lower()
    # keep image-gen models out of the chat list too — they have their own picker
    return not any(x in ml for x in _NON_CHAT) and not is_image_model(mid)


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
        "image_models": ep.image_models_list(),
        "created_at": ep.created_at.isoformat(),
    }


# GET /api/models  — all enabled endpoints with cached model lists
@router.get("/models")
def list_models(db: DbSession = Depends(get_db)):
    eps = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
    return [_fmt_endpoint(ep) for ep in eps]


@router.get("/setup/status")
def setup_status(db: DbSession = Depends(get_db)):
    """first-run check — is there at least one usable AI provider wired up?
    drives the welcome/get-started card so a fresh install isn't a dead end."""
    eps = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
    with_models = [ep for ep in eps if ep.models_list()]
    return {
        "configured": bool(with_models),
        "endpoints": len(eps),
        "endpoints_with_models": len(with_models),
    }


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
    models: list[str] | None = None  # manually set the chat model list (no live probe needed)
    vision_models: str | None = None  # json list string
    image_models: str | None = None  # json list string


# PATCH /api/models/endpoint/{id}
@router.patch("/models/endpoint/{ep_id}")
def patch_endpoint(ep_id: str, body: PatchEndpoint, db: DbSession = Depends(get_db)):
    ep = db.get(ModelEndpoint, ep_id)
    if not ep:
        raise HTTPException(404)
    if body.name is not None:
        ep.name = body.name
    if body.base_url is not None:
        ep.base_url = body.base_url
    if body.api_key is not None:
        ep.api_key = body.api_key
    if body.enabled is not None:
        ep.enabled = body.enabled
    if body.models is not None:
        import json as _json

        ep.cached_models = _json.dumps(body.models)
    if body.vision_models is not None:
        ep.vision_models = body.vision_models
    if body.image_models is not None:
        ep.image_models = body.image_models
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
_ANTHROPIC_FALLBACK = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

# per-provider FALLBACK line-ups (current flagships + a couple of superseded ones so "newest
# only" has something to collapse). only used when the live /v1/models probe can't run — no
# api key, or it errors — so the picker + newest-only still work with no keys at all. a real
# key always wins: refresh replaces these with whatever the provider actually returns.
_PROVIDER_FALLBACK = {
    "openai": [
        "gpt-5.5", "gpt-5.5-pro", "gpt-5", "gpt-4o", "gpt-4o-mini", "o3", "o4-mini",
        "gpt-4.1", "gpt-image-2", "dall-e-3", "sora-2",
    ],
    "anthropic": _ANTHROPIC_FALLBACK,
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "moonshot": [
        "kimi-k2.7", "kimi-k2-turbo-preview", "kimi-latest",
        "moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k",
    ],
    "groq": [
        "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
        "deepseek-r1-distill-llama-70b", "qwen-2.5-32b", "gemma2-9b-it",
        "moonshotai/kimi-k2-instruct",
    ],
    "xai": [
        "grok-4", "grok-4-fast-reasoning", "grok-3", "grok-3-mini", "grok-2-image-1212",
    ],
    "gemini": [
        "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
        "gemini-2.0-flash", "imagen-4.0-generate-001",
    ],
    "mistral": [
        "mistral-large-latest", "mistral-medium-latest", "mistral-small-latest",
        "codestral-latest", "pixtral-large-latest", "magistral-medium-latest",
    ],
    "perplexity": [
        "sonar", "sonar-pro", "sonar-reasoning", "sonar-reasoning-pro", "sonar-deep-research",
    ],
    "together": [
        "meta-llama/Llama-3.3-70B-Instruct-Turbo", "deepseek-ai/DeepSeek-R1",
        "Qwen/Qwen2.5-72B-Instruct-Turbo", "black-forest-labs/FLUX.1-schnell",
    ],
    "fireworks": [
        "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "accounts/fireworks/models/deepseek-r1",
        "accounts/fireworks/models/qwen2p5-72b-instruct",
    ],
    "cohere": ["command-a-03-2025", "command-r-plus", "command-r", "command-r7b"],
    "openrouter": [
        "anthropic/claude-opus-4-8", "anthropic/claude-sonnet-4-6",
        "openai/gpt-5.5", "openai/gpt-4o", "google/gemini-2.5-pro",
        "x-ai/grok-4", "deepseek/deepseek-r1", "meta-llama/llama-3.3-70b-instruct",
    ],
}


async def _fetch_raw_model_ids(ep: ModelEndpoint) -> list[str]:
    """the full, unfiltered model-id list from the provider (chat + image + the
    rest). raises on failure. callers split it into chat/image as needed."""
    provider = detect_provider(ep.base_url)
    base = ep.base_url.rstrip("/")

    if provider == "anthropic":
        # Anthropic has a real models API — use it so new releases show up on
        # their own; the static list is only for keys that can't reach it
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    base + "/v1/models?limit=100",
                    headers={
                        "x-api-key": ep.api_key or "",
                        "anthropic-version": "2023-06-01",
                    },
                )
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
    # a real key + a reachable models API wins. on no key / error / empty, fall back to the
    # known current line-up so the picker + newest-only still work offline (no keys).
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(base + "/v1/models", headers=headers)
            r.raise_for_status()
            data = r.json()
        ids = [x["id"] for x in data.get("data", [])]
        if ids:
            return ids
    except Exception:
        pass
    fallback = _PROVIDER_FALLBACK.get(provider)
    if fallback:
        return list(fallback)
    raise RuntimeError(f"no models for {ep.name}: probe failed and no fallback for '{provider}'")


async def fetch_models_split(ep: ModelEndpoint) -> tuple[list[str], list[str]]:
    """(chat_models, image_models) for an endpoint, from one probe."""
    raw = await _fetch_raw_model_ids(ep)
    return [m for m in raw if _is_chat_model(m)], _image_models(raw)


async def fetch_provider_models(ep: ModelEndpoint) -> list[str]:
    """chat models only — kept for callers that just want the chat list."""
    chat, _ = await fetch_models_split(ep)
    return chat


async def refresh_all_model_lists() -> list[dict]:
    """re-probe every enabled endpoint so new provider models appear without anyone
    clicking refresh. failures keep the old cache. returns the per-endpoint
    additions so callers (the UI) can announce what's new."""
    import logging

    log = logging.getLogger("aide.models")
    from core.database import SessionLocal

    db = SessionLocal()
    diffs = []
    try:
        for ep in db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all():
            try:
                models, imgs = await fetch_models_split(ep)
            except Exception as e:
                log.info(f"model refresh skipped for {ep.name}: {e}")
                continue
            changed = False
            if models and set(models) != set(ep.models_list()):
                added = [m for m in models if m not in ep.models_list()]
                ep.cached_models = json.dumps(models)
                changed = True
                if added:
                    log.info(f"{ep.name}: new models available — {', '.join(added[:5])}")
                    diffs.append({"endpoint": ep.name, "added": added})
            if imgs and imgs != ep.image_models_list():
                ep.image_models = json.dumps(imgs)
                changed = True
            if changed:
                db.commit()
    finally:
        db.close()
    return diffs


_last_refresh = 0.0


# POST /api/models/refresh — re-probe all enabled endpoints (model-picker open +
# the manual "refresh all" button). cooldown so repeated opens don't hammer providers.
@router.post("/models/refresh")
async def refresh_models(force: bool = False):
    global _last_refresh
    import time as _t

    now = _t.time()
    if not force and now - _last_refresh < 60:
        return {"added": [], "endpoints": 0, "skipped": "cooldown"}
    _last_refresh = now
    diffs = await refresh_all_model_lists()
    added = []
    for d in diffs:
        added.extend(d["added"])
    return {"added": added, "endpoints": len(diffs)}


# POST /api/models/endpoint/{id}/probe — fetch model list from provider
@router.post("/models/endpoint/{ep_id}/probe")
async def probe_endpoint(ep_id: str, db: DbSession = Depends(get_db)):
    ep = db.get(ModelEndpoint, ep_id)
    if not ep:
        raise HTTPException(404)
    try:
        models, imgs = await fetch_models_split(ep)
    except Exception as e:
        raise HTTPException(502, f"probe failed: {e}")
    ep.cached_models = json.dumps(models)
    ep.image_models = json.dumps(imgs)
    db.commit()
    return {"models": models, "image_models": imgs}
