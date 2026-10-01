"""Endpoint catalog reconciliation and fail-closed health state."""

import json
from datetime import UTC, datetime

from services.imagegen import image_models, is_image_model
from services.model_providers import CatalogFetchError, fetch_catalog, validate_adapter

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


def is_chat_model(model_id: str) -> bool:
    lowered = (model_id or "").lower()
    return (
        bool(lowered)
        and not any(item in lowered for item in _NON_CHAT)
        and not is_image_model(model_id)
    )


def _chat_models(values: list[str]) -> list[str]:
    return [value for value in values if is_chat_model(value)]


def set_manual_models(endpoint, models: list[str]) -> None:
    clean = []
    seen = set()
    for value in models:
        item = str(value or "").strip()
        if item and len(item) <= 300 and item not in seen:
            clean.append(item)
            seen.add(item)
    endpoint.cached_models = json.dumps(clean)
    endpoint.unavailable_models = "[]"
    endpoint.catalog_status = "manual"
    endpoint.catalog_source = "manual"
    endpoint.catalog_error = ""
    endpoint.catalog_refreshed_at = datetime.now(UTC).replace(tzinfo=None)


def set_adapter(endpoint, adapter: str) -> None:
    endpoint.provider_adapter = validate_adapter(adapter)
    if endpoint.provider_adapter == "manual":
        endpoint.catalog_status = "manual"
        endpoint.catalog_source = "manual"
        endpoint.catalog_error = ""
    elif endpoint.catalog_status == "manual":
        endpoint.catalog_status = "unverified"
        endpoint.catalog_source = ""


async def refresh_endpoint(endpoint, *, client=None) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    old_models = endpoint.models_list()
    old_images = endpoint.image_models_list()
    if (endpoint.provider_adapter or "auto") == "manual":
        endpoint.catalog_status = "manual"
        endpoint.catalog_source = "manual"
        endpoint.catalog_error = ""
        return _result(endpoint, [], [])
    try:
        catalog = await fetch_catalog(endpoint, client=client)
    except CatalogFetchError as exc:
        endpoint.catalog_status = "stale" if old_models or old_images else "unavailable"
        endpoint.catalog_error = exc.code
        endpoint.health_status = (
            "unverified"
            if (endpoint.health_status or "unverified") == "unverified"
            else "unavailable"
        )
        endpoint.last_error_code = exc.code
        endpoint.last_tested_at = now
        return _result(endpoint, [], [])

    chat = _chat_models(catalog.model_ids)
    images = image_models(catalog.model_ids)
    added = [model for model in chat if model not in old_models]
    removed = [model for model in old_models if model not in chat]
    unavailable = set(endpoint.unavailable_models_list())
    unavailable.update((set(old_models) | set(old_images)) - set(catalog.model_ids))
    unavailable.difference_update(catalog.model_ids)
    endpoint.cached_models = json.dumps(chat)
    endpoint.image_models = json.dumps(images)
    endpoint.unavailable_models = json.dumps(sorted(unavailable))
    endpoint.model_metadata = json.dumps(catalog.metadata, ensure_ascii=False)
    endpoint.catalog_status = "live"
    endpoint.catalog_source = catalog.adapter
    endpoint.catalog_error = ""
    endpoint.catalog_refreshed_at = now
    endpoint.health_status = "healthy"
    endpoint.last_tested_at = now
    endpoint.last_error_code = ""
    return _result(endpoint, added, removed)


def _result(endpoint, added: list[str], removed: list[str]) -> dict:
    return {
        "endpoint_id": endpoint.id,
        "endpoint": endpoint.name,
        "status": endpoint.catalog_status,
        "health": endpoint.health_status,
        "error_code": endpoint.catalog_error,
        "added": added,
        "removed": removed,
        "models": endpoint.models_list(),
        "image_models": endpoint.image_models_list(),
        "unavailable_models": endpoint.unavailable_models_list(),
    }
