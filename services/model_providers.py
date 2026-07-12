"""Live model-catalog adapters. No shipped model-name fallback lives here."""

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.llm import detect_provider

ADAPTERS = {"auto", "openai-compatible", "anthropic", "ollama", "gemini", "manual"}


class CatalogFetchError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CatalogResult:
    model_ids: list[str]
    metadata: dict[str, dict]
    adapter: str


def adapter_name(endpoint) -> str:
    configured = (getattr(endpoint, "provider_adapter", "") or "auto").strip().lower()
    if configured not in ADAPTERS:
        raise CatalogFetchError("unsupported_adapter")
    if configured != "auto":
        return configured
    provider = detect_provider(getattr(endpoint, "base_url", "") or "")
    if provider == "anthropic":
        return "anthropic"
    if provider == "ollama":
        return "ollama"
    if provider == "gemini" and "/openai" not in (endpoint.base_url or "").lower():
        return "gemini"
    return "openai-compatible"


def validate_adapter(value: str) -> str:
    value = (value or "auto").strip().lower()
    if value not in ADAPTERS:
        raise ValueError("unsupported provider adapter")
    return value


def _url(base_url: str, path: str, *, openai_compatible: bool = False) -> str:
    parsed = urlsplit((base_url or "").rstrip("/"))
    base_path = parsed.path.rstrip("/")
    if openai_compatible and base_path.endswith(("/v1", "/v1beta/openai")):
        full_path = base_path + "/models"
    else:
        full_path = base_path + path
    return urlunsplit((parsed.scheme, parsed.netloc, full_path, "", ""))


def _clean_ids(values) -> list[str]:
    result = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        if not item or len(item) > 300 or item in seen:
            continue
        result.append(item)
        seen.add(item)
        if len(result) >= 5000:
            break
    return result


def _safe_metadata(item: dict, keys: tuple[str, ...]) -> dict:
    result = {}
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            result[key] = value[:1000]
        elif isinstance(value, (int, float, bool)) or value is None:
            result[key] = value
    return result


async def _request_json(client, url: str, headers: dict) -> dict:
    try:
        response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise CatalogFetchError("timeout") from exc
    except httpx.HTTPError as exc:
        raise CatalogFetchError("network_error") from exc
    if response.status_code in {401, 403}:
        raise CatalogFetchError("authentication_failed")
    if response.status_code == 404:
        raise CatalogFetchError("discovery_unsupported")
    if response.status_code >= 400:
        raise CatalogFetchError("provider_error")
    try:
        value = response.json()
    except (TypeError, ValueError) as exc:
        raise CatalogFetchError("invalid_response") from exc
    if not isinstance(value, dict):
        raise CatalogFetchError("invalid_response")
    return value


async def fetch_catalog(endpoint, *, client=None) -> CatalogResult:
    adapter = adapter_name(endpoint)
    if adapter == "manual":
        raise CatalogFetchError("discovery_unsupported")
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        if adapter == "anthropic":
            url = _url(endpoint.base_url, "/v1/models") + "?limit=100"
            payload = await _request_json(
                client,
                url,
                {
                    "x-api-key": endpoint.api_key or "",
                    "anthropic-version": "2023-06-01",
                },
            )
            items = payload.get("data")
            if not isinstance(items, list):
                raise CatalogFetchError("invalid_response")
            ids = _clean_ids(item.get("id") for item in items if isinstance(item, dict))
            metadata = {
                item["id"]: _safe_metadata(item, ("display_name", "created_at", "type"))
                for item in items
                if isinstance(item, dict) and item.get("id") in ids
            }
        elif adapter == "ollama":
            parsed = urlsplit(endpoint.base_url.rstrip("/"))
            base_path = parsed.path.rstrip("/")
            if base_path.endswith("/v1"):
                base_path = base_path[:-3]
            url = urlunsplit((parsed.scheme, parsed.netloc, base_path + "/api/tags", "", ""))
            payload = await _request_json(client, url, {})
            items = payload.get("models")
            if not isinstance(items, list):
                raise CatalogFetchError("invalid_response")
            ids = _clean_ids(item.get("name") for item in items if isinstance(item, dict))
            metadata = {
                item["name"]: _safe_metadata(item, ("modified_at", "size", "digest"))
                for item in items
                if isinstance(item, dict) and item.get("name") in ids
            }
        elif adapter == "gemini":
            payload = await _request_json(
                client,
                _url(endpoint.base_url, "/v1beta/models"),
                {"x-goog-api-key": endpoint.api_key or ""},
            )
            items = payload.get("models")
            if not isinstance(items, list):
                raise CatalogFetchError("invalid_response")
            supported = [
                item
                for item in items
                if isinstance(item, dict)
                and "generateContent" in (item.get("supportedGenerationMethods") or [])
            ]
            ids = _clean_ids(
                str(item.get("name") or "").removeprefix("models/") for item in supported
            )
            metadata = {
                str(item["name"]).removeprefix("models/"): _safe_metadata(
                    item, ("displayName", "version", "description")
                )
                for item in supported
                if str(item.get("name") or "").removeprefix("models/") in ids
            }
        else:
            headers = {"content-type": "application/json"}
            if endpoint.api_key:
                headers["authorization"] = f"Bearer {endpoint.api_key}"
            payload = await _request_json(
                client,
                _url(endpoint.base_url, "/v1/models", openai_compatible=True),
                headers,
            )
            items = payload.get("data")
            if not isinstance(items, list):
                raise CatalogFetchError("invalid_response")
            ids = _clean_ids(item.get("id") for item in items if isinstance(item, dict))
            metadata = {
                item["id"]: _safe_metadata(item, ("created", "owned_by", "object"))
                for item in items
                if isinstance(item, dict) and item.get("id") in ids
            }
        if not ids:
            raise CatalogFetchError("empty_catalog")
        return CatalogResult(ids, metadata, adapter)
    finally:
        if own_client:
            await client.aclose()
