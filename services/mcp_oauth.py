"""sign in to remote MCP servers with OAuth, the way the MCP spec (2026-07-28) lays it out.

401 -> protected resource metadata -> authorization server metadata -> a client id ->
browser sign-in with PKCE + resource -> code back to alles -> tokens, sealed on disk.

client ids, in order: one the owner pasted; a client id metadata document when alles has a
public https address (the auth server has to be able to fetch it); dynamic registration.
the spec prefers metadata documents over registration, but a home alles usually isn't
reachable from the internet, so without a public address registration is the one that works.

every url here except the MCP server's own comes from the server or its auth server, so each
one goes through the same address guard as other integrations.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

PENDING_SECONDS = 600
_pending: dict[str, dict] = {}


class OAuthError(Exception):
    pass


def _file(server_id: str):
    from core.settings import data_dir

    folder = data_dir() / "mcp" / "oauth"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{re.sub(r'[^A-Za-z0-9_-]', '', server_id)}.json"


def load(server_id: str) -> dict:
    from services.secretstore import unseal

    path = _file(server_id)
    if not path.exists():
        return {}
    try:
        return json.loads(unseal(path.read_text(), f"mcp.oauth.{server_id}"))
    except Exception:
        return {}


def save(server_id: str, record: dict) -> None:
    from services.secretstore import seal

    _file(server_id).write_text(seal(json.dumps(record), f"mcp.oauth.{server_id}"))


def forget(server_id: str) -> None:
    _file(server_id).unlink(missing_ok=True)


def signed_in(server_id: str) -> bool:
    return bool((load(server_id).get("tokens") or {}).get("access_token"))


def canonical(url: str) -> str:
    """the server's resource id (RFC 8707): lowercase scheme and host, no fragment or trailing /."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") if parts.path not in ("", "/") else ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def challenge(header: str) -> dict:
    """the parameters of a Bearer WWW-Authenticate header."""
    found = {}
    for key, quoted, bare in re.findall(
        r'([A-Za-z_]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))', header or ""
    ):
        found[key.lower()] = quoted if quoted or not bare else bare
    return found


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _guard(url: str) -> None:
    from services.net_guard import is_safe_url

    parts = urlsplit(url)
    if parts.scheme != "https" and parts.hostname not in ("localhost", "127.0.0.1"):
        raise OAuthError(f"sign-in addresses must use https ({parts.netloc})")
    if not is_safe_url(url):
        raise OAuthError(f"refusing a blocked sign-in address ({parts.netloc})")


async def _json(method: str, url: str, **kwargs) -> tuple[int, dict]:
    import httpx

    _guard(url)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
        response = await http.request(
            method,
            url,
            headers={"accept": "application/json", **kwargs.pop("headers", {})},
            **kwargs,
        )
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


def _well_known(base: str, suffix: str, *, insert: bool) -> str:
    parts = urlsplit(base)
    path = parts.path.rstrip("/")
    if insert:
        return urlunsplit((parts.scheme, parts.netloc, f"/.well-known/{suffix}{path}", "", ""))
    return urlunsplit((parts.scheme, parts.netloc, f"{path}/.well-known/{suffix}", "", ""))


async def _resource_metadata(server_url: str, hint: str) -> dict:
    tries = [hint] if hint else []
    parts = urlsplit(server_url)
    if parts.path.strip("/"):
        tries.append(_well_known(server_url, "oauth-protected-resource", insert=True))
    tries.append(
        urlunsplit((parts.scheme, parts.netloc, "/.well-known/oauth-protected-resource", "", ""))
    )
    for url in tries:
        try:
            status, body = await _json("GET", url)
        except OAuthError:
            raise
        except Exception:
            continue
        if status == 200 and body.get("authorization_servers"):
            resource = body.get("resource")
            if resource and not canonical(server_url).startswith(canonical(resource)):
                raise OAuthError("the server's sign-in details are for a different address")
            return body
    raise OAuthError("this server asks for sign-in but doesn't say where to sign in")


async def _server_metadata(issuer: str) -> dict:
    has_path = bool(urlsplit(issuer).path.strip("/"))
    if has_path:
        tries = [
            _well_known(issuer, "oauth-authorization-server", insert=True),
            _well_known(issuer, "openid-configuration", insert=True),
            _well_known(issuer, "openid-configuration", insert=False),
        ]
    else:
        root = issuer.rstrip("/")
        tries = [
            f"{root}/.well-known/oauth-authorization-server",
            f"{root}/.well-known/openid-configuration",
        ]
    for url in tries:
        try:
            status, body = await _json("GET", url)
        except OAuthError:
            raise
        except Exception:
            continue
        if status == 200 and body.get("authorization_endpoint"):
            # spec: the document must name the same issuer we built the address from
            if body.get("issuer") != issuer:
                raise OAuthError("the sign-in server's details don't match its address")
            return body
    raise OAuthError("couldn't read the sign-in server's details")


def public_client(origin: str) -> dict:
    """alles's client id metadata document, for auth servers that fetch it."""
    return {
        "client_id": f"{origin}/oauth/mcp-client.json",
        "client_name": "alles",
        "client_uri": origin,
        "redirect_uris": [f"{origin}/api/mcp/oauth/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


def _public_origin() -> str:
    from core.server_config import public_origin

    try:
        return public_origin()
    except Exception:
        return ""


async def _client(meta: dict, redirect_uri: str, given: dict, scope: str) -> dict:
    if given.get("client_id"):
        return {**given, "how": "pasted"}
    public = _public_origin()
    if (
        meta.get("client_id_metadata_document_supported")
        and public
        and redirect_uri.startswith(public + "/")
    ):
        return {"client_id": public_client(public)["client_id"], "how": "metadata document"}
    endpoint = meta.get("registration_endpoint")
    if endpoint:
        host = urlsplit(redirect_uri).hostname or ""
        local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")
        body = {
            "client_name": "alles",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "application_type": "native" if local else "web",
        }
        if scope:
            body["scope"] = scope
        status, made = await _json("POST", endpoint, json=body)
        if status in (200, 201) and made.get("client_id"):
            return {
                "client_id": made["client_id"],
                "client_secret": made.get("client_secret", ""),
                "auth_method": made.get("token_endpoint_auth_method", "none"),
                "how": "registered",
            }
        raise OAuthError(
            f"the sign-in server refused to register alles ({made.get('error_description') or made.get('error') or status})"
        )
    raise OAuthError(
        "this server needs a client id; make one on the provider's site and paste it here"
    )


async def begin(
    server_id: str, server_url: str, header: str, redirect_uri: str, given: dict | None = None
) -> str:
    """start a sign-in; returns the address to open in the browser."""
    hints = challenge(header)
    resource_meta = await _resource_metadata(server_url, hints.get("resource_metadata", ""))
    issuer = str(resource_meta["authorization_servers"][0])
    meta = await _server_metadata(issuer)
    if "S256" not in (meta.get("code_challenge_methods_supported") or []):
        raise OAuthError("the sign-in server doesn't support PKCE, so alles won't use it")
    old = load(server_id)
    asked = hints.get("scope") or " ".join(resource_meta.get("scopes_supported") or [])
    # step-up: keep what was granted before and add what's asked now
    scopes = (
        list(dict.fromkeys((old.get("scope", "") + " " + asked).split()))
        if old.get("issuer") == issuer
        else asked.split()
    )
    if "offline_access" in (meta.get("scopes_supported") or []) and "offline_access" not in scopes:
        scopes.append("offline_access")
    scope = " ".join(scopes)
    given = {k: v for k, v in (given or {}).items() if v}
    client = old.get("client") if old.get("issuer") == issuer and not given else None
    if not client or client.get("redirect_uri") != redirect_uri:
        # credentials belong to one auth server and one callback; never reuse them elsewhere
        client = {**await _client(meta, redirect_uri, given, scope), "redirect_uri": redirect_uri}
    resource = canonical(resource_meta.get("resource") or server_url)
    verifier, code_challenge = _pkce()
    state = secrets.token_urlsafe(32)
    now = time.time()
    for key, value in list(_pending.items()):
        if now - value["at"] > PENDING_SECONDS:
            _pending.pop(key, None)
    _pending[state] = {
        "at": now,
        "server_id": server_id,
        "verifier": verifier,
        "issuer": issuer,
        "iss_supported": bool(meta.get("authorization_response_iss_parameter_supported")),
        "record": {
            "issuer": issuer,
            "resource": resource,
            "scope": scope,
            "client": client,
            "token_endpoint": meta.get("token_endpoint", ""),
            "auth_methods": meta.get("token_endpoint_auth_methods_supported")
            or ["client_secret_basic"],
        },
    }
    params = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "resource": resource,
    }
    if scope:
        params["scope"] = scope
    endpoint = meta["authorization_endpoint"]
    _guard(endpoint)
    return endpoint + ("&" if "?" in endpoint else "?") + urlencode(params)


def _client_auth(record: dict, form: dict) -> dict:
    client = record["client"]
    form["client_id"] = client["client_id"]
    secret = client.get("client_secret")
    if not secret:
        return {}
    if (
        "client_secret_basic" in record.get("auth_methods", [])
        and client.get("auth_method") != "client_secret_post"
    ):
        raw = f"{client['client_id']}:{secret}".encode()
        return {"authorization": "Basic " + base64.b64encode(raw).decode()}
    form["client_secret"] = secret
    return {}


def _tokens(body: dict, old: dict | None = None) -> dict:
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token") or (old or {}).get("refresh_token", ""),
        "expires_at": time.time() + float(body["expires_in"]) if body.get("expires_in") else 0,
    }


async def finish(state: str, code: str, iss: str, error: str) -> str:
    """the browser came back; trade the code for tokens. returns the server id."""
    flow = _pending.pop(state or "", None)
    if not flow or time.time() - flow["at"] > PENDING_SECONDS:
        raise OAuthError("this sign-in expired; start it again from settings")
    # RFC 9207: a present iss must match; a missing one is fine only if the server never sends it
    if iss and iss != flow["issuer"]:
        raise OAuthError("the answer came from a different sign-in server than expected")
    if not iss and flow["iss_supported"]:
        raise OAuthError("the sign-in answer was missing its issuer")
    if error:
        raise OAuthError(f"the sign-in was not completed ({error[:80]})")
    if not code:
        raise OAuthError("the sign-in came back without a code")
    record = flow["record"]
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": record["client"]["redirect_uri"],
        "code_verifier": flow["verifier"],
        "resource": record["resource"],
    }
    headers = _client_auth(record, form)
    status, body = await _json("POST", record["token_endpoint"], data=form, headers=headers)
    if status != 200 or not body.get("access_token"):
        raise OAuthError(f"the sign-in server didn't give a token ({body.get('error') or status})")
    record["tokens"] = _tokens(body)
    if body.get("scope"):
        record["scope"] = body["scope"]
    save(flow["server_id"], record)
    return flow["server_id"]


async def token_for(server_id: str) -> str:
    """the current access token, refreshed when it's about to run out; "" when signed out."""
    record = load(server_id)
    tokens = record.get("tokens") or {}
    if not tokens.get("access_token"):
        return ""
    if not tokens.get("expires_at") or tokens["expires_at"] - time.time() > 60:
        return tokens["access_token"]
    if not tokens.get("refresh_token"):
        return tokens["access_token"]  # let the server say 401 and start a new sign-in
    form = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "resource": record["resource"],
    }
    headers = _client_auth(record, form)
    try:
        status, body = await _json("POST", record["token_endpoint"], data=form, headers=headers)
    except Exception:
        return tokens["access_token"]
    if status != 200 or not body.get("access_token"):
        record["tokens"] = {}
        save(server_id, record)
        return ""
    record["tokens"] = _tokens(body, tokens)
    save(server_id, record)
    return record["tokens"]["access_token"]
