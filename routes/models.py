import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import ModelEndpoint, SessionLocal, get_db
from core.settings import load_settings
from services import model_catalog
from services.imagegen import is_image_model
from services.llm import detect_provider, simple_complete
from services.model_resolver import MODEL_ROLES, ModelResolutionError, resolve_model
from services.redaction import redact_url

router = APIRouter(prefix="/api")
log = logging.getLogger("aide.models")

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


def _is_chat_model(model_id: str) -> bool:
    lowered = (model_id or "").lower()
    return (
        bool(lowered)
        and not any(item in lowered for item in _NON_CHAT)
        and not is_image_model(model_id)
    )


def _fmt_endpoint(endpoint: ModelEndpoint) -> dict:
    try:
        vision = json.loads(endpoint.vision_models or "[]")
        if not isinstance(vision, list):
            vision = []
    except (TypeError, ValueError):
        vision = []
    return {
        "id": endpoint.id,
        "name": endpoint.name,
        "base_url": redact_url(endpoint.base_url),
        "enabled": endpoint.enabled,
        "provider": detect_provider(endpoint.base_url),
        "provider_adapter": endpoint.provider_adapter or "auto",
        "models": endpoint.models_list(),
        "vision_models": vision,
        "image_models": endpoint.image_models_list(),
        "unavailable_models": endpoint.unavailable_models_list(),
        "model_metadata": endpoint.model_metadata_dict(),
        "catalog_status": endpoint.catalog_status or "unverified",
        "catalog_source": endpoint.catalog_source or "",
        "catalog_error": endpoint.catalog_error or "",
        "catalog_refreshed_at": (
            endpoint.catalog_refreshed_at.isoformat() if endpoint.catalog_refreshed_at else None
        ),
        "health_status": endpoint.health_status or "unverified",
        "last_tested_at": endpoint.last_tested_at.isoformat() if endpoint.last_tested_at else None,
        "last_error_code": endpoint.last_error_code or "",
        "created_at": endpoint.created_at.isoformat(),
    }


@router.get("/models")
def list_models(db: DbSession = Depends(get_db)):
    endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
    return [_fmt_endpoint(endpoint) for endpoint in endpoints]


@router.get("/models/roles")
def model_roles(db: DbSession = Depends(get_db)):
    settings = load_settings()
    configured = settings.get("model_roles") or {}
    result = {}
    for role in MODEL_ROLES:
        try:
            selected = resolve_model(db, role, settings=settings)
        except ModelResolutionError as exc:
            result[role] = {
                "configured": configured.get(role) or {},
                "status": "broken",
                "error_code": exc.code,
            }
        else:
            result[role] = {
                "configured": configured.get(role) or {},
                "status": "ready",
                "effective": selected.public(),
            }
    return result


@router.get("/setup/status")
def setup_status(db: DbSession = Depends(get_db)):
    endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
    with_models = [endpoint for endpoint in endpoints if endpoint.models_list()]
    return {
        "configured": bool(with_models),
        "endpoints": len(endpoints),
        "endpoints_with_models": len(with_models),
    }


class AddEndpoint(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    provider_adapter: str = "auto"


@router.post("/models/endpoint", dependencies=[Depends(require_recent_owner)])
def add_endpoint(body: AddEndpoint, db: DbSession = Depends(get_db)):
    try:
        adapter = model_catalog.validate_adapter(body.provider_adapter)
    except ValueError as exc:
        raise ApiError(400, "invalid_provider_adapter", str(exc)) from exc
    endpoint = ModelEndpoint(
        name=(body.name or "").strip() or "endpoint",
        base_url=body.base_url.rstrip("/"),
        api_key=body.api_key,
        provider_adapter=adapter,
        catalog_status="manual" if adapter == "manual" else "unverified",
        catalog_source="manual" if adapter == "manual" else "",
        health_status="unverified",
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return _fmt_endpoint(endpoint)


class PatchEndpoint(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    provider_adapter: str | None = None
    models: list[str] | None = None
    vision_models: str | None = None
    image_models: str | None = None


def _json_list(value: str, field: str) -> str:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "invalid_model_list", f"{field} must be a JSON list") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ApiError(400, "invalid_model_list", f"{field} must be a JSON list of model IDs")
    return json.dumps(parsed)


@router.patch("/models/endpoint/{ep_id}", dependencies=[Depends(require_recent_owner)])
def patch_endpoint(ep_id: str, body: PatchEndpoint, db: DbSession = Depends(get_db)):
    endpoint = db.get(ModelEndpoint, ep_id)
    if not endpoint:
        raise ApiError(404, "model_endpoint_not_found", "model endpoint not found")
    if body.name is not None:
        endpoint.name = body.name
    if body.base_url is not None and body.base_url.rstrip("/") != endpoint.base_url:
        endpoint.base_url = body.base_url.rstrip("/")
        if (endpoint.provider_adapter or "auto") != "manual":
            unavailable = set(endpoint.unavailable_models_list()) | set(endpoint.models_list())
            endpoint.unavailable_models = json.dumps(sorted(unavailable))
            endpoint.cached_models = "[]"
            endpoint.image_models = "[]"
            endpoint.model_metadata = "{}"
            endpoint.catalog_status = "unverified"
            endpoint.catalog_source = ""
        endpoint.health_status = "unverified"
        endpoint.last_error_code = ""
    if body.api_key is not None:
        endpoint.api_key = body.api_key
        endpoint.health_status = "unverified"
        if endpoint.catalog_status == "live":
            endpoint.catalog_status = "stale"
    if body.enabled is not None:
        endpoint.enabled = body.enabled
    if body.provider_adapter is not None:
        try:
            model_catalog.set_adapter(endpoint, body.provider_adapter)
        except ValueError as exc:
            raise ApiError(400, "invalid_provider_adapter", str(exc)) from exc
    if body.models is not None:
        endpoint.provider_adapter = "manual"
        model_catalog.set_manual_models(endpoint, body.models)
    if body.vision_models is not None:
        endpoint.vision_models = _json_list(body.vision_models, "vision_models")
    if body.image_models is not None:
        endpoint.image_models = _json_list(body.image_models, "image_models")
    db.commit()
    return _fmt_endpoint(endpoint)


@router.delete("/models/endpoint/{ep_id}", dependencies=[Depends(require_recent_owner)])
def delete_endpoint(ep_id: str, db: DbSession = Depends(get_db)):
    endpoint = db.get(ModelEndpoint, ep_id)
    if not endpoint:
        raise ApiError(404, "model_endpoint_not_found", "model endpoint not found")
    db.delete(endpoint)
    db.commit()
    return {"ok": True}


async def refresh_all_model_lists() -> list[dict]:
    db = SessionLocal()
    results = []
    try:
        endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
        for endpoint in endpoints:
            result = await model_catalog.refresh_endpoint(endpoint)
            results.append(result)
            db.commit()
            if result["error_code"]:
                log.info(
                    "model catalog refresh failed",
                    extra={"event": "model.catalog", "status": result["error_code"]},
                )
    finally:
        db.close()
    return results


_last_refresh = 0.0


@router.post("/models/refresh")
async def refresh_models(force: bool = False):
    global _last_refresh
    now = time.time()
    if not force and now - _last_refresh < 60:
        return {"added": [], "removed": [], "endpoints": 0, "skipped": "cooldown"}
    _last_refresh = now
    results = await refresh_all_model_lists()
    return {
        "added": [model for result in results for model in result["added"]],
        "removed": [model for result in results for model in result["removed"]],
        "endpoints": len(results),
        "results": results,
    }


@router.post("/models/endpoint/{ep_id}/probe")
async def probe_endpoint(ep_id: str, db: DbSession = Depends(get_db)):
    endpoint = db.get(ModelEndpoint, ep_id)
    if not endpoint:
        raise ApiError(404, "model_endpoint_not_found", "model endpoint not found")
    result = await model_catalog.refresh_endpoint(endpoint)
    db.commit()
    if result["error_code"]:
        raise ApiError(502, "model_catalog_refresh_failed", "model catalog refresh failed")
    return result


@router.post("/models/endpoint/{ep_id}/test")
async def test_endpoint(ep_id: str, db: DbSession = Depends(get_db)):
    endpoint = db.get(ModelEndpoint, ep_id)
    if not endpoint:
        raise ApiError(404, "model_endpoint_not_found", "model endpoint not found")
    models = endpoint.models_list()
    if not models:
        raise ApiError(400, "model_catalog_empty", "no models available; refresh or add one")
    test_model = models[0]
    try:
        response = await simple_complete(
            [{"role": "user", "content": "respond with the word 'pong' and nothing else."}],
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            model=test_model,
            max_tokens=10,
        )
    except Exception as exc:
        endpoint.health_status = "unavailable"
        endpoint.last_error_code = "model_test_failed"
        endpoint.last_tested_at = datetime.utcnow()
        db.commit()
        raise ApiError(502, "model_test_failed", "model endpoint test failed") from exc
    endpoint.health_status = "healthy"
    endpoint.last_error_code = ""
    endpoint.last_tested_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "model": test_model, "response": response}
