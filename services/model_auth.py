"""Legitimate model-provider authentication metadata and Gemini OAuth.

Alles never imports consumer-chat sessions. API-key providers stay API-key
providers; the only first-party OAuth flow here is Google's documented Gemini
desktop-client flow using owner-created credentials.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx

AUTH_TYPES = {"api_key", "oauth", "external_proxy", "none"}
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GEMINI_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


@dataclass(frozen=True)
class ProviderProfile:
    id: str
    label: str
    auth_types: tuple[str, ...]
    billing_url: str
    revoke_url: str
    revocation: str
    warning: str


PROFILES = {
    "openai": ProviderProfile(
        "openai",
        "OpenAI",
        ("api_key",),
        "https://platform.openai.com/usage",
        "https://platform.openai.com/api-keys",
        "Delete or rotate the API key in the OpenAI platform after disconnecting it here.",
        "API requests can consume paid project quota. ChatGPT subscription credentials are not used.",
    ),
    "anthropic": ProviderProfile(
        "anthropic",
        "Claude",
        ("api_key",),
        "https://console.anthropic.com/settings/usage",
        "https://console.anthropic.com/settings/keys",
        "Delete or rotate the API key in the Anthropic Console after disconnecting it here.",
        "API requests can consume paid Console quota. Claude subscription OAuth is not permitted for third-party routing.",
    ),
    "gemini": ProviderProfile(
        "gemini",
        "Gemini",
        ("api_key", "oauth"),
        "https://aistudio.google.com/usage",
        "https://myaccount.google.com/permissions",
        "Revoke the Alles Google grant, or remove the API key, in the owning Google project/account.",
        "Requests use the selected Google Cloud project quota. OAuth requires your own desktop client and project.",
    ),
    "kimi": ProviderProfile(
        "kimi",
        "Kimi",
        ("api_key",),
        "https://platform.kimi.ai/console",
        "https://platform.kimi.ai/console",
        "Delete or rotate the Kimi Open Platform API key after disconnecting it here.",
        "Kimi Open Platform API requests use API quota. Kimi web or Kimi Code sessions are not imported.",
    ),
    "deepseek": ProviderProfile(
        "deepseek",
        "DeepSeek",
        ("api_key",),
        "https://platform.deepseek.com/usage",
        "https://platform.deepseek.com/api_keys",
        "Delete or rotate the DeepSeek API key after disconnecting it here.",
        "DeepSeek's published API uses bearer API keys. The free chat website is not an OAuth source.",
    ),
    "ollama": ProviderProfile(
        "ollama",
        "Ollama",
        ("none", "api_key"),
        "",
        "",
        "Remove any reverse-proxy credential at its owner after disconnecting it here.",
        "No credential is accepted only for a loopback endpoint.",
    ),
    "external_proxy": ProviderProfile(
        "external_proxy",
        "owner-managed proxy",
        ("external_proxy",),
        "",
        "",
        "Revoke credentials in the proxy and every upstream provider it controls.",
        "Alles does not inspect or import the proxy's stored consumer tokens. You own its security and provider compliance.",
    ),
    "custom": ProviderProfile(
        "custom",
        "custom provider",
        ("api_key", "external_proxy", "none"),
        "",
        "",
        "Revoke the credential at the endpoint owner after disconnecting it here.",
        "Confirm the endpoint's authentication, billing, retention, and revocation rules before use.",
    ),
}


def provider_id_for(base_url: str, explicit: str = "") -> str:
    chosen = (explicit or "").strip().lower()
    if chosen:
        if chosen not in PROFILES:
            raise ValueError("unsupported model provider")
        return chosen
    host = (urlsplit(base_url or "").hostname or "").lower()
    if host.endswith("openai.com"):
        return "openai"
    if host.endswith("anthropic.com"):
        return "anthropic"
    if host.endswith("googleapis.com"):
        return "gemini"
    if host.endswith("deepseek.com"):
        return "deepseek"
    if host.endswith("moonshot.ai") or host.endswith("moonshot.cn") or host.endswith("kimi.ai"):
        return "kimi"
    if host in {"127.0.0.1", "localhost", "::1"} and (
        ":11434" in (base_url or "") or "ollama" in (base_url or "").lower()
    ):
        return "ollama"
    return "custom"


def is_loopback_url(value: str) -> bool:
    parsed = urlsplit(value or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (
        host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".localhost")
    )


def validate_auth(provider_id: str, auth_type: str, base_url: str) -> tuple[str, str]:
    provider_id = provider_id_for(base_url, provider_id)
    auth_type = (auth_type or "api_key").strip().lower()
    if auth_type not in AUTH_TYPES or auth_type not in PROFILES[provider_id].auth_types:
        raise ValueError(f"{PROFILES[provider_id].label} does not support that authentication type")
    if auth_type == "oauth" and provider_id != "gemini":
        raise ValueError("only the documented Gemini OAuth flow is supported")
    if auth_type == "none" and not is_loopback_url(base_url):
        raise ValueError("credential-free model endpoints must use loopback")
    return provider_id, auth_type


def public_auth(endpoint) -> dict:
    provider_id = provider_id_for(
        getattr(endpoint, "base_url", ""), getattr(endpoint, "provider_id", "") or ""
    )
    profile = PROFILES[provider_id]
    auth_type = (getattr(endpoint, "auth_type", "") or "api_key").strip().lower()
    scopes = []
    try:
        value = json.loads(getattr(endpoint, "oauth_scopes", "[]") or "[]")
        if isinstance(value, list):
            scopes = [str(item) for item in value if isinstance(item, str)]
    except (TypeError, ValueError):
        pass
    expires_at = float(getattr(endpoint, "oauth_expires_at", 0) or 0)
    return {
        "provider_id": provider_id,
        "provider_label": profile.label,
        "auth_type": auth_type,
        "auth_status": getattr(endpoint, "auth_status", "") or (
            "connected" if getattr(endpoint, "api_key", "") or auth_type == "none" else "incomplete"
        ),
        "account_identity": getattr(endpoint, "account_identity", "") or "",
        "oauth_scopes": scopes,
        "oauth_expires_at": expires_at or None,
        "oauth_refreshable": bool(getattr(endpoint, "oauth_refresh_token", "")),
        "billing_url": profile.billing_url,
        "revoke_url": profile.revoke_url,
        "revocation": profile.revocation,
        "quota_warning": profile.warning,
        "supported_auth_types": list(profile.auth_types),
    }


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


_pending: dict[str, dict] = {}
_runtime_projects: dict[str, str] = {}


def _register_runtime_token(token: str, project_id: str) -> None:
    if token and project_id:
        _runtime_projects[hashlib.sha256(token.encode("utf-8")).hexdigest()] = project_id


def runtime_headers(token: str) -> dict[str, str]:
    if not token:
        return {}
    project_id = _runtime_projects.get(hashlib.sha256(token.encode("utf-8")).hexdigest(), "")
    return {"x-goog-user-project": project_id} if project_id else {}


def begin_gemini_oauth(endpoint, redirect_uri: str) -> str:
    if not is_loopback_url(redirect_uri):
        raise ValueError("Gemini OAuth callback must use loopback")
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    now = time.time()
    _pending[state] = {
        "endpoint_id": endpoint.id,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "created_at": now,
    }
    for key, value in list(_pending.items()):
        if now - float(value.get("created_at") or 0) > 600:
            _pending.pop(key, None)
    params = {
        "client_id": endpoint.oauth_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GEMINI_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def consume_pending(state: str) -> dict | None:
    value = _pending.pop(state or "", None)
    if not value or time.time() - float(value.get("created_at") or 0) > 600:
        return None
    return value


async def exchange_gemini_code(endpoint, code: str, pending: dict, *, client=None) -> dict:
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": endpoint.oauth_client_id,
                "client_secret": endpoint.oauth_client_secret,
                "redirect_uri": pending["redirect_uri"],
                "code_verifier": pending["verifier"],
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        raise RuntimeError("gemini_oauth_exchange_failed") from exc
    finally:
        if own_client:
            await client.aclose()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError("gemini_oauth_exchange_failed")
    return payload


def apply_gemini_tokens(endpoint, payload: dict) -> None:
    endpoint.api_key = str(payload.get("access_token") or "")
    if payload.get("refresh_token"):
        endpoint.oauth_refresh_token = str(payload["refresh_token"])
    endpoint.oauth_expires_at = time.time() + max(60, int(payload.get("expires_in") or 3600))
    endpoint.oauth_scopes = json.dumps(
        str(payload.get("scope") or " ".join(GEMINI_SCOPES)).split(), separators=(",", ":")
    )
    endpoint.auth_status = "connected"
    endpoint.auth_error = ""
    endpoint.account_identity = endpoint.oauth_project_id or "google cloud project"
    _register_runtime_token(endpoint.api_key, endpoint.oauth_project_id)


async def refresh_gemini_endpoint(endpoint, *, force: bool = False, client=None) -> bool:
    if (getattr(endpoint, "auth_type", "") or "") != "oauth":
        return False
    if not force and float(getattr(endpoint, "oauth_expires_at", 0) or 0) - 300 > time.time():
        _register_runtime_token(
            getattr(endpoint, "api_key", "") or "",
            getattr(endpoint, "oauth_project_id", "") or "",
        )
        return False
    refresh_token = getattr(endpoint, "oauth_refresh_token", "") or ""
    if not refresh_token:
        endpoint.auth_status = "expired"
        endpoint.auth_error = "oauth_refresh_token_missing"
        return False
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": endpoint.oauth_client_id,
                "client_secret": endpoint.oauth_client_secret,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise ValueError("missing access token")
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        endpoint.auth_status = "expired"
        endpoint.auth_error = "oauth_refresh_failed"
        raise RuntimeError("gemini_oauth_refresh_failed") from exc
    finally:
        if own_client:
            await client.aclose()
    apply_gemini_tokens(endpoint, payload)
    return True


async def revoke_gemini_endpoint(endpoint, *, client=None) -> None:
    token = (getattr(endpoint, "oauth_refresh_token", "") or "") or (
        getattr(endpoint, "api_key", "") or ""
    )
    if not token:
        return
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(GOOGLE_REVOKE_URL, data={"token": token})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError("gemini_oauth_revoke_failed") from exc
    finally:
        if own_client:
            await client.aclose()


def clear_oauth(endpoint) -> None:
    endpoint.api_key = ""
    endpoint.oauth_refresh_token = ""
    endpoint.oauth_expires_at = 0
    endpoint.oauth_scopes = "[]"
    endpoint.auth_status = "revoked"
    endpoint.auth_error = ""
    endpoint.enabled = False


async def refresh_all_oauth_endpoints() -> int:
    from core.database import ModelEndpoint, SessionLocal

    db = SessionLocal()
    refreshed = 0
    try:
        endpoints = (
            db.query(ModelEndpoint)
            .filter(ModelEndpoint.auth_type == "oauth", ModelEndpoint.enabled == True)  # noqa: E712
            .all()
        )
        for endpoint in endpoints:
            try:
                if await refresh_gemini_endpoint(endpoint):
                    refreshed += 1
            except RuntimeError:
                pass
        db.commit()
    finally:
        db.close()
    return refreshed
