"""the provider side of sign in: catalog, readiness, and the oauth calls.

each function talks to exactly one documented endpoint. the urls and the shape of the calls
follow the provider docs (kept next to each block) and, for the two subscription flows, the
community implementations the owner asked alles to copy.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from services import mail_oauth, signin_clients

# github device flow: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_SCOPES = ("repo", "read:user", "user:email", "offline_access")

# microsoft device code: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
# outlook imap/smtp scopes: https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth
MICROSOFT_TENANT = "common"
MICROSOFT_DEVICE_CODE_URL = (
    f"https://login.microsoftonline.com/{MICROSOFT_TENANT}/oauth2/v2.0/devicecode"
)
MICROSOFT_TOKEN_URL = f"https://login.microsoftonline.com/{MICROSOFT_TENANT}/oauth2/v2.0/token"
MICROSOFT_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
)
OUTLOOK_IMAP = ("outlook.office365.com", 993)
OUTLOOK_SMTP = ("smtp.office365.com", 587)

# google redirect rules: https://developers.google.com/identity/protocols/oauth2/web-server
GOOGLE_AUTH_URL = mail_oauth.AUTH_URL
GOOGLE_TOKEN_URL = mail_oauth.TOKEN_URL
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_MAIL_SCOPE = "https://mail.google.com/"
# google caldav: https://developers.google.com/workspace/calendar/caldav/v2/guide
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
GOOGLE_CALDAV_ROOT = "https://apidata.googleusercontent.com/caldav/v2"
GEMINI_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# anthropic subscription sign in, copied from pi-anthropic-oauth's src/auth.ts:
# https://github.com/leohenon/pi-anthropic-oauth
ANTHROPIC_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
ANTHROPIC_AUTH_URL = "https://claude.ai/oauth/authorize"
ANTHROPIC_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
ANTHROPIC_REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
ANTHROPIC_SCOPES = (
    "org:create_api_key",
    "user:profile",
    "user:inference",
    "user:sessions:claude_code",
    "user:mcp_servers",
    "user:file_upload",
)
ANTHROPIC_BASE_URL = "https://api.anthropic.com"

# openai subscription sign in, copied from openai-oauth:
# https://github.com/EvanZhouDev/openai-oauth
OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_ISSUER = "https://auth.openai.com"
OPENAI_AUTH_URL = f"{OPENAI_ISSUER}/oauth/authorize"
OPENAI_TOKEN_URL = f"{OPENAI_ISSUER}/oauth/token"
OPENAI_REDIRECT_URI = "http://localhost:1455/auth/callback"
OPENAI_SCOPE = "openid profile email offline_access"
OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"

DEVICE = "device"
REDIRECT = "redirect"
PASTE_CODE = "paste_code"


class ProviderError(Exception):
    """a provider said no; the message is safe to show and never contains a token."""

    def __init__(self, message: str, *, permanent: bool = True):
        super().__init__(message)
        self.permanent = permanent


class NotReady(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _client(*, timeout: float = 30) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return (response.text or f"HTTP {response.status_code}")[:200]
    if isinstance(body, dict):
        for key in ("error_description", "message", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
    return f"HTTP {response.status_code}"


def _raise_for(response: httpx.Response, what: str) -> None:
    if response.status_code >= 400:
        # a 4xx (except timeout/rate-limit) is the provider refusing for good; a 5xx,
        # 408 or 429 is worth another try later.
        permanent = 400 <= response.status_code < 500 and response.status_code not in (408, 429)
        raise ProviderError(f"{what} ({_detail(response)})", permanent=permanent)


def is_loopback_origin(origin: str) -> bool:
    parts = urlsplit(origin)
    host = (parts.hostname or "").lower()
    return parts.scheme in {"http", "https"} and host in {"localhost", "127.0.0.1", "::1"}


def redirect_secure(origin: str) -> bool:
    """google accepts http only on a loopback address; everything else needs https."""
    parts = urlsplit(origin)
    return parts.scheme == "https" or is_loopback_origin(origin)


def signin_redirect_uri(origin: str, provider: str) -> str:
    return f"{origin.rstrip('/')}/api/signin/callback/{provider}"


# ── catalog ──────────────────────────────────────────────────────────────────


def uses_for(provider: str) -> list[dict[str, str]]:
    return {
        "github": [{"id": "github", "name": "repos and issues"}],
        "microsoft": [{"id": "mail", "name": "outlook mail"}],
        "google": [
            {"id": "mail", "name": "gmail"},
            {"id": "calendar", "name": "google calendar"},
            {"id": "models", "name": "gemini"},
        ],
        "anthropic": [{"id": "models", "name": "claude subscription"}],
        "openai": [{"id": "models", "name": "chatgpt subscription"}],
    }.get(provider, [])


def flow_for(provider: str) -> str:
    return {
        "github": DEVICE,
        "microsoft": DEVICE,
        "google": REDIRECT,
        "anthropic": PASTE_CODE,
        "openai": PASTE_CODE,
    }.get(provider, "")


def name_for(provider: str) -> str:
    return {
        "github": "GitHub",
        "microsoft": "Microsoft",
        "google": "Google",
        "anthropic": "Claude",
        "openai": "ChatGPT",
    }.get(provider, "")


def provider_ids() -> list[str]:
    return ["github", "microsoft", "google", "anthropic", "openai"]


def known_use(provider: str, use: str) -> bool:
    return any(item["id"] == use for item in uses_for(provider))


_NOT_READY_TEXT = {
    "github": {"message": "alles's github sign in isn't set up yet"},
    "microsoft": {"message": "alles's microsoft sign in isn't set up yet"},
    "google_client": {"message": "add your own google client in mail settings first"},
    "google_https": {"message": "signing in with google needs an https address"},
}


def not_ready(provider: str, origin: str) -> dict[str, str] | None:
    """why this provider can't start from this address, or None when it can."""
    if provider == "github":
        if not signin_clients.github_client_id():
            return {
                "code": "no_client_id",
                "text": _NOT_READY_TEXT["github"]["message"],
            }
        return None
    if provider == "microsoft":
        if not signin_clients.microsoft_client_id():
            return {
                "code": "no_client_id",
                "text": _NOT_READY_TEXT["microsoft"]["message"],
            }
        return None
    if provider == "google":
        if not mail_oauth.configured():
            return {
                "code": "no_client",
                "text": _NOT_READY_TEXT["google_client"]["message"],
            }
        if not redirect_secure(origin):
            return {
                "code": "needs_https",
                "text": _NOT_READY_TEXT["google_https"]["message"],
            }
        return None
    return None


def providers(origin: str) -> list[dict[str, Any]]:
    out = []
    for provider in provider_ids():
        reason = not_ready(provider, origin)
        out.append(
            {
                "id": provider,
                "name": name_for(provider),
                "flow": flow_for(provider),
                "ready": reason is None,
                "not_ready": reason,
                "uses": uses_for(provider),
            }
        )
    return out


# ── github device flow ───────────────────────────────────────────────────────


async def github_start(client_id: str, login_hint: str = "") -> dict:
    data = {"client_id": client_id, "scope": " ".join(GITHUB_SCOPES)}
    if login_hint:
        data["login"] = login_hint
    async with _client() as http:
        response = await http.post(
            GITHUB_DEVICE_CODE_URL,
            data=data,
            headers={"accept": "application/json"},
        )
    _raise_for(response, "GitHub wouldn't start a sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("device_code"):
        raise ProviderError("GitHub wouldn't start a sign in (no device code)")
    return body


async def github_poll(client_id: str, device_code: str) -> tuple[int, dict]:
    async with _client() as http:
        response = await http.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"accept": "application/json"},
        )
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


async def github_user(access_token: str) -> dict:
    async with _client() as http:
        response = await http.get(
            GITHUB_USER_URL,
            headers={"accept": "application/json", "authorization": f"Bearer {access_token}"},
        )
    if response.status_code != 200:
        return {}
    body = response.json()
    return body if isinstance(body, dict) else {}


async def github_refresh(client_id: str, refresh_token: str) -> dict:
    async with _client() as http:
        response = await http.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"accept": "application/json"},
        )
    _raise_for(response, "GitHub wouldn't refresh the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("GitHub wouldn't refresh the sign in (no access token)")
    return body


# ── microsoft device code ───────────────────────────────────────────────────


async def microsoft_start(client_id: str, login_hint: str = "") -> dict:
    data = {"client_id": client_id, "scope": " ".join(MICROSOFT_SCOPES)}
    if login_hint:
        data["login_hint"] = login_hint
    async with _client() as http:
        response = await http.post(MICROSOFT_DEVICE_CODE_URL, data=data)
    _raise_for(response, "Microsoft wouldn't start a sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("device_code"):
        raise ProviderError("Microsoft wouldn't start a sign in (no device code)")
    return body


async def microsoft_poll(client_id: str, device_code: str) -> tuple[int, dict]:
    async with _client() as http:
        response = await http.post(
            MICROSOFT_TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            },
        )
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


_MICROSOFT_REFRESH_FORM = {
    "grant_type": "refresh_token",
    "client_id": None,
    "refresh_token": None,
}


def _microsoft_refresh_form(client_id: str, refresh_token: str) -> dict:
    form = dict(_MICROSOFT_REFRESH_FORM)
    form["client_id"] = client_id
    form["refresh_token"] = refresh_token
    form["scope"] = " ".join(MICROSOFT_SCOPES)
    return form


async def microsoft_refresh(client_id: str, refresh_token: str) -> dict:
    async with _client() as http:
        response = await http.post(
            MICROSOFT_TOKEN_URL,
            data=_microsoft_refresh_form(client_id, refresh_token),
        )
    _raise_for(response, "Microsoft wouldn't refresh the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("Microsoft wouldn't refresh the sign in (no access token)")
    return body


def microsoft_refresh_sync(client_id: str, refresh_token: str) -> dict:
    """the mail engine is synchronous; this is the same refresh without an event loop."""
    with httpx.Client(timeout=30) as http:
        response = http.post(
            MICROSOFT_TOKEN_URL,
            data=_microsoft_refresh_form(client_id, refresh_token),
        )
    _raise_for(response, "Microsoft wouldn't refresh the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("Microsoft wouldn't refresh the sign in (no access token)")
    return body


# ── google redirect ─────────────────────────────────────────────────────────


def google_scopes(use: str) -> tuple[str, ...]:
    scope = {
        "mail": GOOGLE_MAIL_SCOPE,
        "calendar": GOOGLE_CALENDAR_SCOPE,
        "models": GEMINI_SCOPE,
    }[use]
    return (scope, "openid", "email")


def google_auth_url(origin: str, use: str, state: str, login_hint: str = "") -> str:
    client_id, _secret = mail_oauth._creds()
    params = {
        "client_id": client_id,
        "redirect_uri": signin_redirect_uri(origin, "google"),
        "response_type": "code",
        "scope": " ".join(google_scopes(use)),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def google_exchange(code: str, redirect_uri: str) -> dict:
    client_id, client_secret = mail_oauth._creds()
    async with _client() as http:
        response = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    _raise_for(response, "Google wouldn't finish the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("Google wouldn't finish the sign in (no access token)")
    return body


async def google_refresh(refresh_token: str) -> dict:
    client_id, client_secret = mail_oauth._creds()
    async with _client() as http:
        response = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
    _raise_for(response, "Google wouldn't refresh the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("Google wouldn't refresh the sign in (no access token)")
    return body


def google_refresh_sync(refresh_token: str) -> dict:
    client_id, client_secret = mail_oauth._creds()
    with httpx.Client(timeout=30) as http:
        response = http.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
    _raise_for(response, "Google wouldn't refresh the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("Google wouldn't refresh the sign in (no access token)")
    return body


async def google_revoke(token: str) -> bool:
    """google's revoke endpoint takes the token alone, so no client secret is needed."""
    try:
        async with _client() as http:
            response = await http.post(GOOGLE_REVOKE_URL, data={"token": token})
        return response.status_code == 200
    except httpx.HTTPError:
        return False


# ── pkce ────────────────────────────────────────────────────────────────────


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _state() -> str:
    return secrets.token_urlsafe(24)


# ── anthropic subscription (paste code) ─────────────────────────────────────


def anthropic_auth_url(challenge: str, state: str) -> str:
    params = {
        "code": "true",
        "client_id": ANTHROPIC_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": ANTHROPIC_REDIRECT_URI,
        "scope": " ".join(ANTHROPIC_SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{ANTHROPIC_AUTH_URL}?{urlencode(params)}"


async def anthropic_exchange(code: str, state: str, verifier: str) -> dict:
    async with _client() as http:
        response = await http.post(
            ANTHROPIC_TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": ANTHROPIC_CLIENT_ID,
                "code": code,
                "state": state,
                "redirect_uri": ANTHROPIC_REDIRECT_URI,
                "code_verifier": verifier,
            },
        )
    _raise_for(response, "Claude wouldn't finish the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("Claude wouldn't finish the sign in (no access token)")
    return body


async def anthropic_refresh(refresh_token: str) -> dict:
    async with _client() as http:
        response = await http.post(
            ANTHROPIC_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": ANTHROPIC_CLIENT_ID,
                "refresh_token": refresh_token,
            },
        )
    _raise_for(response, "Claude wouldn't refresh the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("Claude wouldn't refresh the sign in (no access token)")
    return body


# ── openai subscription (paste code) ────────────────────────────────────────


def openai_auth_url(challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": OPENAI_CLIENT_ID,
        "redirect_uri": OPENAI_REDIRECT_URI,
        "scope": OPENAI_SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    return f"{OPENAI_AUTH_URL}?{urlencode(params)}"


async def openai_exchange(code: str, verifier: str) -> dict:
    async with _client() as http:
        response = await http.post(
            OPENAI_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OPENAI_REDIRECT_URI,
                "client_id": OPENAI_CLIENT_ID,
                "code_verifier": verifier,
            },
        )
    _raise_for(response, "OpenAI wouldn't finish the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("OpenAI wouldn't finish the sign in (no access token)")
    return body


async def openai_refresh(refresh_token: str) -> dict:
    async with _client() as http:
        response = await http.post(
            OPENAI_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OPENAI_CLIENT_ID,
            },
        )
    _raise_for(response, "OpenAI wouldn't refresh the sign in")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ProviderError("OpenAI wouldn't refresh the sign in (no access token)")
    return body


# ── identity from a provider token ──────────────────────────────────────────


def jwt_claims(token: str) -> dict:
    """claims of an id token we just received directly from the provider over TLS.

    this is identity display only, never a substitute for validating the API token.
    """
    parts = str(token or "").split(".")
    if len(parts) != 3:
        return {}
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, TypeError, KeyError):
        return {}
    return data if isinstance(data, dict) else {}


def microsoft_identity(payload: dict, login_hint: str = "") -> tuple[str, str]:
    claims = jwt_claims(str(payload.get("id_token") or ""))
    email = str(
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
        or login_hint
        or ""
    ).strip()
    login = email or "microsoft account"
    return login, (email if "@" in email else "")


def google_identity(payload: dict) -> tuple[str, str]:
    claims = jwt_claims(str(payload.get("id_token") or ""))
    email = str(claims.get("email") or "").strip().lower()
    return email or "google account", email


def openai_identity(payload: dict) -> tuple[str, str]:
    claims = jwt_claims(str(payload.get("id_token") or ""))
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    auth = claims.get("https://api.openai.com/auth")
    account = ""
    if isinstance(auth, dict):
        account = str(auth.get("chatgpt_account_id") or "").strip()
    account = account or str(claims.get("chatgpt_account_id") or "").strip()
    login = email or account or "chatgpt account"
    return login, (email if "@" in email else "")


def expires_at(payload: dict, *, what: str = "") -> float:
    try:
        return time.time() + max(60, int(payload.get("expires_in") or 3600))
    except (TypeError, ValueError):
        return time.time() + 3600


def scopes_list(payload: dict, fallback: tuple[str, ...] = ()) -> list[str]:
    raw = payload.get("scope")
    if isinstance(raw, str) and raw.strip():
        return [part for part in raw.replace(",", " ").split() if part]
    return list(fallback)
