"""Andromeda normal results, grounded overview, saved searches, and Jarvis handoff."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.build_info import afterlife_feature_flags
from core.database import (
    AndromedaSavedSearch,
    AndromedaVerificationJob,
    Project,
    Session,
    get_db,
)
from core.settings import load_settings
from services import andromeda

router = APIRouter(prefix="/api/andromeda")

_MEDIA_PLACEHOLDER = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="media unavailable"><rect width="64" height="64" fill="#171717"/><path d="M18 44 29 31l7 8 5-6 7 11H18Zm4-24h20a4 4 0 0 1 4 4v22H18V24a4 4 0 0 1 4-4Zm3 8a4 4 0 1 0 8 0 4 4 0 0 0-8 0Z" fill="none" stroke="#777" stroke-width="2" stroke-linejoin="round"/></svg>"""


def _media_placeholder() -> Response:
    return Response(
        _MEDIA_PLACEHOLDER,
        media_type="image/svg+xml",
        headers={
            "cache-control": "private, max-age=300",
            "x-andromeda-media-state": "unavailable",
            "x-content-type-options": "nosniff",
            "content-security-policy": "default-src 'none'",
        },
    )


def _require_flag() -> None:
    if not afterlife_feature_flags()["afterlife_andromeda"]:
        raise HTTPException(404, "Andromeda is not enabled")


def _event(value: dict) -> str:
    return f"data: {json.dumps(value, ensure_ascii=False)}\n\n"


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    normal_results: bool | None = None
    overview: bool | None = None
    max_results: int | None = Field(default=None, ge=1, le=600)
    category: Literal["all", "images", "news", "videos"] = "all"
    provider: Literal[
        "", "duckduckgo", "tavily", "brave", "searxng", "google_pse", "serper", "disabled"
    ] = ""


@router.get("/providers")
def providers():
    """Return usable engines without exposing credentials."""
    _require_flag()
    settings = load_settings()
    configured = {
        "brave": bool(settings.get("brave_api_key")),
        "serper": bool(settings.get("serper_api_key")),
        "tavily": bool(settings.get("tavily_api_key")),
        "searxng": bool(settings.get("searxng_url")),
        "google_pse": bool(settings.get("google_pse_api_key") and settings.get("google_pse_cx")),
        "duckduckgo": True,
    }
    labels = {
        "brave": "brave",
        "serper": "serper · google",
        "tavily": "tavily",
        "searxng": "searxng",
        "google_pse": "google",
        "duckduckgo": "duckduckgo",
    }
    order = ("searxng", "brave", "serper", "google_pse", "tavily", "duckduckgo")
    return {
        "selected": settings.get("search_provider") or "duckduckgo",
        "providers": [
            {"value": name, "label": labels[name], "available": configured[name]} for name in order
        ],
    }


@router.post("/search")
async def search(body: SearchBody):
    _require_flag()
    settings = load_settings()
    normal_enabled = (
        settings.get("andromeda_normal_results", True)
        if body.normal_results is None
        else body.normal_results
    )
    overview_default = body.category == "all" and (
        settings.get("andromeda_overview", True) if body.overview is None else body.overview
    )
    parsed = andromeda.parse_query(body.query, overview_default=overview_default)
    if not parsed.query:
        raise ApiError(400, "search_query_required", "write a search query before !ai")
    default_counts = {
        "all": int(settings.get("search_result_count") or 10),
        "images": 30,
        "news": 20,
        "videos": 20,
    }
    count = body.max_results or default_counts[body.category]
    search_needed = bool(normal_enabled or parsed.overview)
    result = await andromeda.normal_search(
        parsed.query,
        enabled=search_needed,
        max_results=count,
        category=body.category,
        provider=body.provider,
    )
    overview_seed = result.get("results", [])[:12] if parsed.overview else []
    if not normal_enabled:
        result = {**result, "status": "disabled", "results": []}
    return {
        "query": parsed.query,
        "used_no_ai": parsed.used_no_ai,
        "category": body.category,
        "normal_results_enabled": bool(normal_enabled),
        "overview_requested": parsed.overview,
        "overview_seed": overview_seed,
        **result,
    }


@router.get("/media")
async def media(url: str = Query(min_length=8, max_length=4_000)):
    """Privacy-preserving image proxy for public search-result media."""
    _require_flag()
    from services.net_guard import safe_get_public_async

    try:
        upstream = await safe_get_public_async(
            url,
            timeout=8,
            headers={"accept": "image/avif,image/webp,image/png,image/jpeg,image/gif,image/x-icon"},
            max_redirects=4,
            max_bytes=2_000_000,
        )
        upstream.raise_for_status()
    except Exception:
        return _media_placeholder()
    media_type = upstream.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    allowed = {
        "image/avif",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/x-icon",
        "image/vnd.microsoft.icon",
    }
    if media_type not in allowed:
        return _media_placeholder()
    return Response(
        upstream.content,
        media_type=media_type,
        headers={
            "cache-control": "private, max-age=3600",
            "x-content-type-options": "nosniff",
            "content-security-policy": "default-src 'none'",
        },
    )


class OverviewBody(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    results: list[dict] = Field(default_factory=list, max_length=12)
    band: str = Field(default="", max_length=20)
    endpoint_id: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=300)
    confirmed_endpoint_id: str = Field(default="", max_length=100)
    confirmed_model: str = Field(default="", max_length=300)


@router.post("/overview")
async def overview(body: OverviewBody, db: DbSession = Depends(get_db)):
    _require_flag()
    settings = load_settings()
    if not settings.get("andromeda_overview", True):
        raise ApiError(409, "overview_disabled", "AI Overview is off in Settings")
    parsed = andromeda.parse_query(body.query, overview_default=True)
    if parsed.used_no_ai:
        raise ApiError(409, "overview_disabled_for_search", "!ai disabled this overview")
    if not parsed.query:
        raise ApiError(400, "search_query_required", "search query is required")
    exact = None
    if body.endpoint_id or body.model:
        if not body.endpoint_id or not body.model:
            raise ApiError(400, "invalid_model_choice", "choose both an endpoint and model")
        exact = {"endpoint_id": body.endpoint_id, "model": body.model}
    band = body.band or settings.get("andromeda_model_band") or "standard"
    try:
        selected = andromeda.select_overview_model(db, settings, band=band, exact=exact)
    except ValueError as exc:
        raise ApiError(
            400, str(exc), "model band must be light, standard, strong, or auto"
        ) from exc
    except Exception as exc:
        from services.model_resolver import ModelResolutionError

        if isinstance(exc, ModelResolutionError):
            raise ApiError(409, exc.code, str(exc)) from exc
        raise
    public_model = selected.public()
    if selected.privacy_class == "remote" and (
        body.confirmed_endpoint_id != selected.endpoint.id or body.confirmed_model != selected.model
    ):
        raise ApiError(
            409,
            "remote_model_confirmation_required",
            "confirm the shown model before the query and source evidence leave Alles",
        )
    rows = andromeda.normalize_results(body.results, "client", 0)
    endpoint_url = selected.endpoint.base_url
    endpoint_key = selected.endpoint.api_key
    model = selected.model

    async def stream():
        started = asyncio.get_running_loop().time()
        yield _event({"type": "model", "model": public_model, "band": band})
        try:
            evidence = await andromeda.build_evidence(parsed.query, rows)
        except asyncio.CancelledError:
            raise
        except Exception:
            evidence = []
        yield _event({"type": "evidence", "sources": evidence})
        if not evidence:
            yield _event(
                {
                    "type": "overview",
                    "overview": {
                        "status": "insufficient_evidence",
                        "summary": "",
                        "claims": [],
                        "rejected_claims": 0,
                        "freshness": andromeda.freshness_summary(parsed.query, []),
                    },
                    "elapsed_ms": round((asyncio.get_running_loop().time() - started) * 1000),
                }
            )
            yield "data: [DONE]\n\n"
            return
        from services.llm import simple_complete

        try:
            max_tokens = int(settings.get("andromeda_answer_max_tokens") or 450)
            timeout_seconds = int(settings.get("andromeda_answer_timeout_seconds") or 50)
            raw = await asyncio.wait_for(
                simple_complete(
                    andromeda.overview_prompt(
                        parsed.query, evidence, andromeda.freshness_summary(parsed.query, evidence)
                    ),
                    endpoint_url,
                    endpoint_key,
                    model,
                    max_tokens=max_tokens,
                    thinking=False,
                ),
                timeout=timeout_seconds,
            )
            checked = andromeda.verify_overview(raw, parsed.query, evidence)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            yield _event(
                {
                    "type": "error",
                    "code": "overview_timeout",
                    "detail": "AI Overview timed out; normal links are still available",
                }
            )
            yield "data: [DONE]\n\n"
            return
        except Exception:
            yield _event(
                {
                    "type": "error",
                    "code": "overview_failed",
                    "detail": "AI Overview failed; normal links are still available",
                }
            )
            yield "data: [DONE]\n\n"
            return
        for claim in checked["claims"]:
            yield _event({"type": "claim", "claim": claim})
        yield _event(
            {
                "type": "overview",
                "overview": checked,
                "elapsed_ms": round((asyncio.get_running_loop().time() - started) * 1000),
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


@router.get("/overview/preview")
def overview_preview(
    band: str = "",
    endpoint_id: str = "",
    model: str = "",
    db: DbSession = Depends(get_db),
):
    _require_flag()
    settings = load_settings()
    exact = None
    if endpoint_id or model:
        if not endpoint_id or not model:
            raise ApiError(400, "invalid_model_choice", "choose both an endpoint and model")
        exact = {"endpoint_id": endpoint_id, "model": model}
    try:
        selected = andromeda.select_overview_model(
            db,
            settings,
            band=band or settings.get("andromeda_model_band") or "standard",
            exact=exact,
        )
    except ValueError as exc:
        raise ApiError(
            400, str(exc), "model band must be light, standard, strong, or auto"
        ) from exc
    except Exception as exc:
        from services.model_resolver import ModelResolutionError

        if isinstance(exc, ModelResolutionError):
            raise ApiError(409, exc.code, str(exc)) from exc
        raise
    return selected.public()


class QualifyModelBody(BaseModel):
    endpoint_id: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=300)


@router.post("/models/qualify")
async def qualify_local_model(body: QualifyModelBody, db: DbSession = Depends(get_db)):
    _require_flag()
    settings = load_settings()
    selected = andromeda.select_overview_model(
        db,
        settings,
        band="standard",
        exact={"endpoint_id": body.endpoint_id, "model": body.model},
    )
    if selected.privacy_class != "local":
        raise ApiError(
            409, "qualification_requires_local", "only local models can qualify for Auto"
        )
    evidence = [
        {
            "id": "s1",
            "title": "fixture release notes",
            "url": "https://fixture.invalid/releases",
            "publisher": "fixture.invalid",
            "source_kind": "release notes",
            "source_quality": 2,
            "dates": ["2026-07-01"],
            "versions": ["3.2.0"],
            "passages": [
                "Version 3.2.0 was released on 2026-07-01.",
                "The release notes say offline links remain available when overview generation fails.",
            ],
        }
    ]
    from services.llm import simple_complete

    try:
        raw = await asyncio.wait_for(
            simple_complete(
                andromeda.overview_prompt(
                    "What version was released and what happens when overview generation fails?",
                    evidence,
                    andromeda.freshness_summary("latest software version", evidence),
                ),
                selected.endpoint.base_url,
                selected.endpoint.api_key,
                selected.model,
                max_tokens=500,
            ),
            timeout=35,
        )
    except TimeoutError as exc:
        raise ApiError(
            408, "qualification_timeout", "the local model did not finish the fixture"
        ) from exc
    checked = andromeda.verify_overview(raw, "latest software version", evidence)
    passed = checked["status"] == "ready" and len(checked["claims"]) >= 2
    key = f"{selected.endpoint.id}:{selected.model}"
    qualified = list(settings.get("andromeda_qualified_models") or [])
    if passed and key not in qualified:
        from core.settings import save_settings

        qualified.append(key)
        save_settings({"andromeda_qualified_models": qualified})
    return {
        "passed": passed,
        "model": selected.public(),
        "supported_claims": len(checked["claims"]),
        "required_claims": 2,
    }


class VerificationBody(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    answer: dict = Field(default_factory=dict)
    results: list[dict] = Field(default_factory=list, max_length=12)
    manual: bool = False
    confirmed_endpoint_id: str = Field(default="", max_length=100)
    confirmed_model: str = Field(default="", max_length=300)


class VerificationPreviewBody(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    manual: bool = False


@router.post("/verification/preview")
def verification_preview(
    body: VerificationPreviewBody,
    db: DbSession = Depends(get_db),
):
    """Show the independent verifier and privacy boundary before any job starts."""
    _require_flag()
    settings = load_settings()
    from services import andromeda_verifier

    if not andromeda_verifier.should_verify(settings, body.query, manual=body.manual):
        return {"status": "skipped", "reason": "verification policy did not match this query"}
    from services.model_resolver import ModelResolutionError, resolve_model

    try:
        selected = resolve_model(db, "andromeda_verifier", settings=settings)
    except ModelResolutionError as exc:
        raise ApiError(409, exc.code, str(exc)) from exc
    return {"status": "ready", "model": selected.public()}


def _verification_job(row: AndromedaVerificationJob) -> dict:
    def decoded(raw: str, expected: type):
        try:
            value = json.loads(raw or ("[]" if expected is list else "{}"))
        except (TypeError, ValueError):
            value = [] if expected is list else {}
        return value if isinstance(value, expected) else ([] if expected is list else {})

    return {
        "id": row.id,
        "status": row.status,
        "error_code": row.error_code or "",
        "checked_at": row.checked_at.isoformat() if row.checked_at else "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "model": decoded(row.model_json, dict),
        "result": decoded(row.result_json, dict),
        "evidence": decoded(row.evidence_json, list),
    }


@router.post("/verification")
def start_verification(body: VerificationBody, db: DbSession = Depends(get_db)):
    _require_flag()
    settings = load_settings()
    from services import andromeda_verifier

    if not andromeda_verifier.should_verify(settings, body.query, manual=body.manual):
        return {"status": "skipped", "reason": "verification policy did not match this query"}
    claims = body.answer.get("claims") if isinstance(body.answer, dict) else None
    if not isinstance(claims, list) or not claims:
        raise ApiError(400, "verification_answer_required", "a supported fast answer is required")
    from services.model_resolver import ModelResolutionError, resolve_model

    try:
        selected = resolve_model(db, "andromeda_verifier", settings=settings)
    except ModelResolutionError as exc:
        raise ApiError(409, exc.code, str(exc)) from exc
    if selected.privacy_class == "remote" and (
        body.confirmed_endpoint_id != selected.endpoint.id or body.confirmed_model != selected.model
    ):
        raise ApiError(
            409,
            "remote_verifier_confirmation_required",
            "confirm the shown verifier before the query, answer, and evidence leave Alles",
        )
    row = AndromedaVerificationJob(
        query=body.query.strip(),
        answer_json=_bounded_json(body.answer, dict, 100_000),
        results_json=_bounded_json(body.results, list, 100_000),
        model_json=_bounded_json(selected.public(), dict, 10_000),
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    andromeda_verifier.launch(row.id)
    return _verification_job(row)


@router.get("/verification/{job_id}")
def get_verification(job_id: str, db: DbSession = Depends(get_db)):
    _require_flag()
    row = db.get(AndromedaVerificationJob, job_id)
    if not row:
        raise HTTPException(404, "verification job not found")
    return _verification_job(row)


@router.post("/verification/{job_id}/cancel")
def cancel_verification(job_id: str, db: DbSession = Depends(get_db)):
    _require_flag()
    row = db.get(AndromedaVerificationJob, job_id)
    if not row:
        raise HTTPException(404, "verification job not found")
    if row.status in {"pending", "running"}:
        row.status = "cancelled"
        row.error_code = "cancelled_by_owner"
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(row)
    return _verification_job(row)


def _bounded_json(value, expected: type, limit: int) -> str:
    if not isinstance(value, expected):
        raise ApiError(400, "invalid_saved_search", "saved search data has the wrong shape")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode()) > limit:
        raise ApiError(413, "saved_search_too_large", "saved search data is too large")
    return encoded


def _saved(row: AndromedaSavedSearch, *, detail: bool = False) -> dict:
    result = {
        "id": row.id,
        "query": row.query,
        "checked_at": row.checked_at.isoformat() if row.checked_at else "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
    if detail:
        for target, source, expected in (
            ("request", row.request_json, dict),
            ("results", row.results_json, list),
            ("overview", row.overview_json, dict),
            ("evidence", row.evidence_json, list),
            ("model", row.model_json, dict),
            ("verification", row.verification_json, dict),
            ("verifier_model", row.verifier_model_json, dict),
        ):
            try:
                value = json.loads(source or ("[]" if expected is list else "{}"))
            except (TypeError, ValueError):
                value = [] if expected is list else {}
            result[target] = (
                value if isinstance(value, expected) else ([] if expected is list else {})
            )
    return result


class SaveBody(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    request: dict = Field(default_factory=dict)
    results: list[dict] = Field(default_factory=list, max_length=12)
    overview: dict = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list, max_length=6)
    model: dict = Field(default_factory=dict)
    verification: dict = Field(default_factory=dict)
    verifier_model: dict = Field(default_factory=dict)


@router.get("/saved")
def list_saved(db: DbSession = Depends(get_db)):
    _require_flag()
    rows = db.query(AndromedaSavedSearch).order_by(AndromedaSavedSearch.created_at.desc()).all()
    return {"searches": [_saved(row) for row in rows[:100]]}


@router.post("/saved")
def save_search(body: SaveBody, db: DbSession = Depends(get_db)):
    _require_flag()
    row = AndromedaSavedSearch(
        query=body.query.strip(),
        request_json=_bounded_json(body.request, dict, 20_000),
        results_json=_bounded_json(body.results, list, 100_000),
        overview_json=_bounded_json(body.overview, dict, 100_000),
        evidence_json=_bounded_json(body.evidence, list, 150_000),
        model_json=_bounded_json(body.model, dict, 10_000),
        verification_json=_bounded_json(body.verification, dict, 150_000),
        verifier_model_json=_bounded_json(body.verifier_model, dict, 10_000),
        checked_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _saved(row, detail=True)


@router.get("/saved/{search_id}")
def get_saved(search_id: str, db: DbSession = Depends(get_db)):
    _require_flag()
    row = db.get(AndromedaSavedSearch, search_id)
    if not row:
        raise HTTPException(404, "saved search not found")
    return _saved(row, detail=True)


@router.delete("/saved/{search_id}")
def delete_saved(search_id: str, db: DbSession = Depends(get_db)):
    _require_flag()
    row = db.get(AndromedaSavedSearch, search_id)
    if not row:
        raise HTTPException(404, "saved search not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


class DeepResearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    session_id: str = ""
    project_id: str = ""
    confirmed_endpoint_id: str = ""
    confirmed_model: str = ""


@router.post("/deep-research")
def deep_research(body: DeepResearchBody, db: DbSession = Depends(get_db)):
    _require_flag()
    from services import jarvis_handoff

    session = db.get(Session, body.session_id) if body.session_id else None
    if body.session_id and not session:
        raise HTTPException(404, "Aide conversation not found")
    if not session:
        if body.project_id and not db.get(Project, body.project_id):
            raise HTTPException(404, "Project not found")
        session = Session(name=body.query[:80], project_id=body.project_id or None, mode="jarvis")
        db.add(session)
        db.flush()
    preview = jarvis_handoff.model_preview(db)
    if preview["privacy_class"] == "remote" and (
        body.confirmed_endpoint_id != preview["endpoint_id"]
        or body.confirmed_model != preview["model"]
    ):
        raise ApiError(
            409,
            "remote_model_confirmation_required",
            "confirm the shown Jarvis model before Project context leaves Alles",
        )
    run = jarvis_handoff.create_handoff(
        db, session, f"Deep research this question and return a cited report: {body.query.strip()}"
    )
    db.commit()
    db.refresh(run)
    jarvis_handoff.launch(run.id)
    return {
        "id": run.id,
        "session_id": session.id,
        "project_id": run.project_id,
        "state": run.state,
        "model": preview,
    }


@router.get("/deep-research/preview")
def deep_research_preview(db: DbSession = Depends(get_db)):
    _require_flag()
    from services import jarvis_handoff

    try:
        return jarvis_handoff.model_preview(db)
    except Exception as exc:
        from services.model_resolver import ModelResolutionError

        if isinstance(exc, ModelResolutionError):
            raise ApiError(409, exc.code, str(exc)) from exc
        raise
