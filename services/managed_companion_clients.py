"""Bounded Alles-native clients for locally managed network companions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from core.settings import data_dir
from services.config_secrets import load_secret_config, save_secret_config

ADGUARD_URL = "http://127.0.0.1:3000/control"
NPM_URL = "http://127.0.0.1:8181/api"
_ADGUARD_PURPOSE = "companions.adguard.password"
_NPM_PURPOSE = "companions.npm.token"


class CompanionClientError(RuntimeError):
    pass


def _credentials_path(service_id: str) -> Path:
    if service_id not in {"adguard-home", "nginx-proxy-manager"}:
        raise CompanionClientError("unknown managed companion")
    return data_dir() / f"{service_id}.credentials.json"


def save_adguard_credentials(username: str, password: str) -> None:
    if not username.strip() or not password:
        raise CompanionClientError("AdGuard credentials are incomplete")
    save_secret_config(
        _credentials_path("adguard-home"),
        {"username": username.strip(), "password": password},
        _ADGUARD_PURPOSE,
    )


def _adguard_credentials() -> tuple[str, str]:
    value = load_secret_config(
        _credentials_path("adguard-home"), _ADGUARD_PURPOSE
    )
    username, password = str(value.get("username") or ""), str(value.get("password") or "")
    if not username or not password:
        raise CompanionClientError("AdGuard credentials are not connected")
    return username, password


def _npm_token() -> str:
    value = load_secret_config(
        _credentials_path("nginx-proxy-manager"), _NPM_PURPOSE, field="token"
    )
    token = str(value.get("token") or "")
    if not token:
        raise CompanionClientError("Nginx Proxy Manager is not connected")
    return token


def clear_credentials(service_id: str) -> None:
    path = _credentials_path(service_id)
    if path.is_symlink():
        raise CompanionClientError("companion credential file is unsafe")
    path.unlink(missing_ok=True)


def _call(
    method: str,
    url: str,
    *,
    requester: Callable[..., Any] = httpx.request,
    auth: tuple[str, str] | None = None,
    token: str = "",
    payload: dict | None = None,
    params: dict | None = None,
) -> Any:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requester(
            method,
            url,
            auth=auth,
            headers=headers,
            json=payload,
            params=params,
            timeout=8,
            follow_redirects=False,
        )
    except Exception as exc:
        raise CompanionClientError("managed companion is unavailable") from exc
    if response.status_code in {401, 403}:
        raise CompanionClientError("managed companion credentials were rejected")
    if not 200 <= response.status_code < 300:
        raise CompanionClientError(f"managed companion request failed ({response.status_code})")
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except (TypeError, ValueError) as exc:
        raise CompanionClientError("managed companion returned invalid JSON") from exc


def adguard_dashboard(*, requester: Callable[..., Any] = httpx.request) -> dict:
    auth = _adguard_credentials()
    status = _call("GET", f"{ADGUARD_URL}/status", requester=requester, auth=auth)
    stats = _call(
        "GET",
        f"{ADGUARD_URL}/stats",
        requester=requester,
        auth=auth,
        params={"recent": 86_400_000},
    )
    filtering = _call(
        "GET", f"{ADGUARD_URL}/filtering/status", requester=requester, auth=auth
    )
    rewrites = _call(
        "GET", f"{ADGUARD_URL}/rewrite/list", requester=requester, auth=auth
    )
    querylog = _call(
        "GET",
        f"{ADGUARD_URL}/querylog",
        requester=requester,
        auth=auth,
        params={"limit": 20},
    )
    return {
        "connected": True,
        "status": status if isinstance(status, dict) else {},
        "stats": stats if isinstance(stats, dict) else {},
        "filtering": filtering if isinstance(filtering, dict) else {},
        "rewrites": rewrites if isinstance(rewrites, list) else [],
        "querylog": (querylog.get("data") or [])[:20] if isinstance(querylog, dict) else [],
    }


def set_adguard_filtering(
    enabled: bool,
    interval: int,
    *,
    requester: Callable[..., Any] = httpx.request,
) -> dict:
    if interval < 0 or interval > 168:
        raise CompanionClientError("filter refresh interval must be between 0 and 168 hours")
    auth = _adguard_credentials()
    _call(
        "POST",
        f"{ADGUARD_URL}/filtering/config",
        requester=requester,
        auth=auth,
        payload={"enabled": bool(enabled), "interval": interval},
    )
    return {"ok": True, "enabled": bool(enabled), "interval": interval}


def change_adguard_rewrite(
    action: str,
    domain: str,
    answer: str,
    *,
    enabled: bool = True,
    requester: Callable[..., Any] = httpx.request,
) -> dict:
    if action not in {"add", "delete"}:
        raise CompanionClientError("rewrite action is invalid")
    clean_domain, clean_answer = domain.strip().lower(), answer.strip()
    if not clean_domain or len(clean_domain) > 253 or not clean_answer or len(clean_answer) > 253:
        raise CompanionClientError("rewrite domain and answer are required")
    payload = {"domain": clean_domain, "answer": clean_answer}
    if action == "add":
        payload["enabled"] = bool(enabled)
    _call(
        "POST",
        f"{ADGUARD_URL}/rewrite/{action}",
        requester=requester,
        auth=_adguard_credentials(),
        payload=payload,
    )
    return {"ok": True, **payload}


def connect_npm(identity: str, secret: str, *, requester: Callable[..., Any] = httpx.request) -> dict:
    clean_identity = identity.strip()
    if not clean_identity or not secret:
        raise CompanionClientError("Nginx Proxy Manager credentials are incomplete")
    result = _call(
        "POST",
        f"{NPM_URL}/tokens",
        requester=requester,
        payload={"identity": clean_identity, "secret": secret},
    )
    if not isinstance(result, dict) or not result.get("token"):
        if isinstance(result, dict) and result.get("challenge_token"):
            raise CompanionClientError("finish two-factor login in Nginx Proxy Manager first")
        raise CompanionClientError("Nginx Proxy Manager did not return a token")
    save_secret_config(
        _credentials_path("nginx-proxy-manager"),
        {
            "identity": clean_identity,
            "token": str(result["token"]),
            "expires": str(result.get("expires") or ""),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        },
        _NPM_PURPOSE,
        field="token",
    )
    return {"connected": True, "identity": clean_identity, "expires": str(result.get("expires") or "")}


def npm_dashboard(*, requester: Callable[..., Any] = httpx.request) -> dict:
    token = _npm_token()
    hosts = _call(
        "GET", f"{NPM_URL}/nginx/proxy-hosts", requester=requester, token=token
    )
    certificates = _call(
        "GET", f"{NPM_URL}/nginx/certificates", requester=requester, token=token
    )
    return {
        "connected": True,
        "proxy_hosts": hosts if isinstance(hosts, list) else [],
        "certificates": certificates if isinstance(certificates, list) else [],
    }


def create_npm_proxy_host(
    *,
    domain_names: list[str],
    forward_scheme: str,
    forward_host: str,
    forward_port: int,
    certificate_id: int = 0,
    ssl_forced: bool = False,
    requester: Callable[..., Any] = httpx.request,
) -> dict:
    domains = list(dict.fromkeys(value.strip().lower() for value in domain_names if value.strip()))
    clean_host = forward_host.strip()
    if not domains or any(len(value) > 253 for value in domains):
        raise CompanionClientError("at least one valid domain is required")
    if forward_scheme not in {"http", "https"} or not clean_host or not 1 <= forward_port <= 65535:
        raise CompanionClientError("proxy destination is invalid")
    payload = {
        "domain_names": domains,
        "forward_scheme": forward_scheme,
        "forward_host": clean_host,
        "forward_port": forward_port,
        "certificate_id": max(0, certificate_id),
        "ssl_forced": bool(ssl_forced),
        "block_exploits": True,
        "allow_websocket_upgrade": True,
        "enabled": True,
    }
    result = _call(
        "POST",
        f"{NPM_URL}/nginx/proxy-hosts",
        requester=requester,
        token=_npm_token(),
        payload=payload,
    )
    return result if isinstance(result, dict) else {"ok": True}
