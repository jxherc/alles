"""search engines: the list every picker shows, custom engines, and a quick test."""

import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.api_errors import ApiError
from core.settings import load_settings, save_settings
from services.research import engines

router = APIRouter(prefix="/api/search")


class CustomEngineBody(BaseModel):
    name: str = ""
    url: str = ""
    method: str = "GET"
    body: str = ""
    key_header: str = ""
    key_prefix: str = ""
    # None keeps the saved key on an edit; "" clears it
    key: str | None = Field(default=None, max_length=500)
    results: str = ""
    url_field: str = "url"
    title_field: str = "title"
    snippet_field: str = "snippet"


class TestBody(BaseModel):
    engine: str = Field(min_length=1, max_length=40)
    query: str = Field(default="alles self-hosted", min_length=1, max_length=200)


@router.get("/engines")
def list_engines():
    return {"engines": engines.listing(load_settings())}


def _save_custom(body: CustomEngineBody, engine_id: str | None = None):
    settings = load_settings()
    rows = engines.custom_engines(settings)
    if engine_id and not any(row.get("id") == engine_id for row in rows):
        raise ApiError(404, "engine_not_found", "that custom engine no longer exists")
    if not engine_id and len(rows) >= engines.CUSTOM_LIMIT:
        raise ApiError(400, "too_many_engines", f"at most {engines.CUSTOM_LIMIT} custom engines")
    try:
        row = engines.clean_custom(body.model_dump(), engine_id)
    except ValueError as exc:
        raise ApiError(400, "invalid_custom_engine", str(exc)) from exc
    rows = [row if r.get("id") == row["id"] else r for r in rows]
    if not engine_id:
        rows.append(row)
    patch = {"custom_search_engines": rows}
    if body.key is not None:
        keys = dict(settings.get("custom_search_keys") or {})
        if body.key.strip():
            keys[row["id"]] = body.key.strip()
        else:
            keys.pop(row["id"], None)
        patch["custom_search_keys"] = keys
    save_settings(patch)
    return next(e for e in engines.listing(load_settings()) if e["id"] == row["id"])


@router.post("/custom")
def add_custom(body: CustomEngineBody):
    return _save_custom(body)


@router.put("/custom/{engine_id}")
def edit_custom(engine_id: str, body: CustomEngineBody):
    return _save_custom(body, engine_id)


@router.delete("/custom/{engine_id}")
def remove_custom(engine_id: str):
    settings = load_settings()
    rows = engines.custom_engines(settings)
    if not any(row.get("id") == engine_id for row in rows):
        raise ApiError(404, "engine_not_found", "that custom engine no longer exists")
    keys = dict(settings.get("custom_search_keys") or {})
    keys.pop(engine_id, None)
    patch = {
        "custom_search_engines": [row for row in rows if row.get("id") != engine_id],
        "custom_search_keys": keys,
    }
    # nothing may keep pointing at an engine that is gone
    if settings.get("search_provider") == engine_id:
        patch["search_provider"] = "duckduckgo"
    if settings.get("search_fallback") == engine_id:
        patch["search_fallback"] = "duckduckgo"
    chain = settings.get("search_fallback_chain")
    if isinstance(chain, list) and engine_id in chain:
        patch["search_fallback_chain"] = [name for name in chain if name != engine_id]
    save_settings(patch)
    return {"ok": True}


@router.post("/test")
async def test_engine(body: TestBody):
    from services.research.search import _safe_failure_type, _search_provider

    settings = load_settings()
    if not engines.known(settings, body.engine):
        raise ApiError(404, "engine_not_found", "unknown search engine")
    started = time.perf_counter()
    try:
        rows = await _search_provider(body.engine, body.query, settings, 5)
    except Exception as error:
        return {
            "ok": False,
            "failure": _safe_failure_type(error),
            "ms": round((time.perf_counter() - started) * 1000),
        }
    return {
        "ok": bool(rows),
        "count": len(rows),
        "first": (rows[0].get("title") or rows[0]["url"])[:120] if rows else "",
        "ms": round((time.perf_counter() - started) * 1000),
    }
