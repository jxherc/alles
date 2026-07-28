"""One model-selection path for interactive work and Jarvis background runs."""

from dataclasses import dataclass

from core.database import ModelEndpoint
from core.settings import load_settings
from services.model_catalog import is_chat_model
from services.routing import is_local_endpoint

MODEL_ROLES = ("aide_chat", "andromeda_answer", "andromeda_verifier", "jarvis")
LEGACY_MODEL_ROLE_ALIASES = {"andromeda": "andromeda_answer"}


class ModelResolutionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedModel:
    endpoint: ModelEndpoint
    model: str
    privacy_class: str
    price_metadata: dict
    reason: str

    def public(self) -> dict:
        return {
            "endpoint_id": self.endpoint.id,
            "endpoint": self.endpoint.name,
            "model": self.model,
            "privacy_class": self.privacy_class,
            "price_metadata": self.price_metadata,
            "reason": self.reason,
        }


def normalize_model_roles(value) -> dict:
    if value is None:
        return {role: {} for role in MODEL_ROLES}
    if not isinstance(value, dict):
        raise ValueError("model_roles must be an object")
    migrated = dict(value)
    for legacy, canonical in LEGACY_MODEL_ROLE_ALIASES.items():
        if legacy in migrated and canonical not in migrated:
            migrated[canonical] = migrated[legacy]
        migrated.pop(legacy, None)
    unknown = set(migrated) - set(MODEL_ROLES)
    if unknown:
        raise ValueError("unknown model role")
    result = {}
    for role in MODEL_ROLES:
        choice = migrated.get(role) or {}
        if not isinstance(choice, dict):
            raise ValueError(f"{role} must be an object")
        allowed = {"endpoint_id", "model", "cost_class", "fallbacks"}
        if set(choice) - allowed:
            raise ValueError(f"{role} has unsupported fields")
        clean = {
            "endpoint_id": _clean_text(choice.get("endpoint_id"), 100),
            "model": _clean_text(choice.get("model"), 300),
            "cost_class": _clean_text(choice.get("cost_class"), 40),
        }
        fallbacks = choice.get("fallbacks") or []
        if not isinstance(fallbacks, list) or len(fallbacks) > 5:
            raise ValueError(f"{role}.fallbacks must be a list of at most 5 choices")
        clean_fallbacks = []
        for fallback in fallbacks:
            if not isinstance(fallback, dict) or set(fallback) - {
                "endpoint_id",
                "model",
                "cost_class",
            }:
                raise ValueError(f"{role} has an invalid fallback")
            clean_fallbacks.append(
                {
                    "endpoint_id": _clean_text(fallback.get("endpoint_id"), 100),
                    "model": _clean_text(fallback.get("model"), 300),
                    "cost_class": _clean_text(fallback.get("cost_class"), 40),
                }
            )
        clean["fallbacks"] = clean_fallbacks
        result[role] = clean
    return result


def _clean_text(value, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("model role values must be strings")
    value = value.strip()
    if len(value) > limit:
        raise ValueError("model role value is too long")
    return value


def _privacy_class(endpoint: ModelEndpoint) -> str:
    return "local" if is_local_endpoint(endpoint) else "remote"


def _price_metadata(endpoint: ModelEndpoint, model: str) -> dict:
    metadata = endpoint.model_metadata_dict().get(model, {})
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if "price" in key.lower() or "cost" in key.lower()
    }


def _enabled_endpoints(db) -> list[ModelEndpoint]:
    return db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()  # noqa: E712


def _resolve_choice(db, choice: dict, reason: str) -> ResolvedModel | None:
    endpoint_id = (choice.get("endpoint_id") or "").strip()
    model = (choice.get("model") or "").strip()
    if not endpoint_id and not model:
        return None

    endpoints = _enabled_endpoints(db)
    endpoint = next((item for item in endpoints if item.id == endpoint_id), None)
    if endpoint_id and endpoint is None:
        raise ModelResolutionError("model_endpoint_unavailable", "selected endpoint is unavailable")
    if endpoint is None and model:
        endpoint = next((item for item in endpoints if model in _available_models(item)), None)
    if endpoint is None:
        raise ModelResolutionError("model_unavailable", "selected model is unavailable")

    available = _available_models(endpoint)
    if model and model not in available:
        raise ModelResolutionError("model_unavailable", "selected model is unavailable")
    if not model:
        model = available[0] if available else ""
    if not model:
        raise ModelResolutionError("model_catalog_empty", "selected endpoint has no models")
    return ResolvedModel(
        endpoint=endpoint,
        model=model,
        privacy_class=_privacy_class(endpoint),
        price_metadata=_price_metadata(endpoint, model),
        reason=reason,
    )


def _configured_role(settings: dict, role: str) -> dict:
    try:
        roles = normalize_model_roles(settings.get("model_roles"))
    except ValueError as exc:
        raise ModelResolutionError(
            "invalid_model_roles", "model role settings are invalid"
        ) from exc
    return roles[role]


def _available_models(endpoint: ModelEndpoint) -> list[str]:
    return [model for model in endpoint.models_list() if is_chat_model(model)]


def _fallback_for_role(
    db, role_choice: dict, primary: ResolvedModel | None
) -> ResolvedModel | None:
    if primary is None:
        return None
    primary_cost = role_choice.get("cost_class") or (
        "local" if primary.privacy_class == "local" else ""
    )
    for fallback in role_choice.get("fallbacks") or []:
        try:
            selection = _resolve_choice(db, fallback, "role_fallback")
        except ModelResolutionError:
            continue
        fallback_cost = fallback.get("cost_class") or (
            "local" if selection.privacy_class == "local" else ""
        )
        if (
            selection.privacy_class == primary.privacy_class
            and primary_cost
            and (fallback_cost == primary_cost)
        ):
            return selection
    return None


def resolve_model(
    db,
    role: str,
    *,
    explicit: dict | None = None,
    workflow_override: dict | None = None,
    feature_default: dict | None = None,
    settings: dict | None = None,
) -> ResolvedModel:
    role = LEGACY_MODEL_ROLE_ALIASES.get(role, role)
    if role not in MODEL_ROLES:
        raise ModelResolutionError("invalid_model_role", "unknown model role")
    settings = settings or load_settings()

    for choice, reason in (
        (explicit or {}, "explicit_override"),
        (workflow_override or {}, "workflow_override"),
        (feature_default or {}, "feature_default"),
    ):
        selection = _resolve_choice(db, choice, reason)
        if selection:
            return selection

    role_choice = _configured_role(settings, role)
    try:
        selection = _resolve_choice(db, role_choice, "role_default")
    except ModelResolutionError as primary_error:
        endpoint_id = role_choice.get("endpoint_id") or ""
        endpoint = db.get(ModelEndpoint, endpoint_id) if endpoint_id else None
        model = role_choice.get("model") or ""
        if endpoint and model:
            placeholder = ResolvedModel(
                endpoint=endpoint,
                model=model,
                privacy_class=_privacy_class(endpoint),
                price_metadata={},
                reason="role_default",
            )
            fallback = _fallback_for_role(db, role_choice, placeholder)
            if fallback:
                return fallback
        raise primary_error
    if selection:
        return selection

    legacy = {
        "endpoint_id": settings.get("default_endpoint_id") or "",
        "model": settings.get("default_model") or "",
    }
    selection = _resolve_choice(db, legacy, "legacy_default")
    if selection:
        return selection

    endpoints = _enabled_endpoints(db)
    if role in {"andromeda_answer", "andromeda_verifier"} or settings.get(
        "prefer_local_models"
    ):
        endpoints.sort(key=lambda item: not is_local_endpoint(item))
    for endpoint in endpoints:
        available = _available_models(endpoint)
        if available:
            model = available[0]
            return ResolvedModel(
                endpoint=endpoint,
                model=model,
                privacy_class=_privacy_class(endpoint),
                price_metadata=_price_metadata(endpoint, model),
                reason="available_fallback",
            )
    raise ModelResolutionError("model_unavailable", "no model is available")
