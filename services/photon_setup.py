"""set Photon up without copying keys around, the way hermes-agent's photon plugin does it
(hermes-agent, MIT, Nous Research).

two halves:
- numbers: Photon's shared line only lets a text through when its sender is a registered user of
  the project. with the project id and secret alles already has, it registers each owner phone
  number (skipping ones Photon already knows) and reads back the line that number should text.
- connect: a device login (RFC 8628) against the Photon dashboard. the owner approves once in the
  browser; alles then finds or creates its project, mints the secret, saves both, and registers
  the owner's numbers. the dashboard token is sealed with the other credentials.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time

import httpx

log = logging.getLogger("alles.photon")

DASHBOARD = "https://app.photon.codes"
SPECTRUM = "https://spectrum.photon.codes"
# hosted Photon only accepts allowlisted device clients; this is Photon's own published cli client
CLIENT_ID = "photon-cli"
SCOPE = "openid profile email"
PROJECT_NAME = "alles"
E164 = re.compile(r"^\+[1-9]\d{6,14}$")

# the one sign-in in progress: {"state": waiting|done|error, "user_code", "url", "error", ...}
login: dict = {"state": "idle"}
_login_task: asyncio.Task | None = None


def e164(handle: str) -> str:
    """+digits for a phone handle; a bare ten-digit number is north american. "" for emails."""
    text = (handle or "").strip()
    if not text or "@" in text:
        return ""
    digits = re.sub(r"\D", "", text)
    if not text.startswith("+") and len(digits) == 10:
        digits = "1" + digits
    number = "+" + digits
    return number if E164.match(number) else ""


def _basic(project_id: str, secret: str) -> dict:
    token = base64.b64encode(f"{project_id}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _unwrap(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        inner = data.get("data", data)
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict):
            for key in ("users", "projects", "lines", "items"):
                if isinstance(inner.get(key), list):
                    return inner[key]
    return []


def _detail(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        for key in ("message", "error", "detail"):
            if body.get(key):
                return str(body[key])[:200]
    return f"HTTP {response.status_code}"


# ── numbers ──


async def list_users(http: httpx.AsyncClient, project_id: str, secret: str) -> list[dict]:
    response = await http.get(
        f"{SPECTRUM}/projects/{project_id}/users/", headers=_basic(project_id, secret)
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Photon wouldn't list users ({_detail(response)})")
    return [u for u in _unwrap(response.json()) if isinstance(u, dict)]


async def ensure_numbers(project_id: str, secret: str, handles: list[str]) -> dict:
    """register every owner phone number Photon doesn't know yet; returns what each one texts."""
    wanted = [n for n in dict.fromkeys(e164(h) for h in handles) if n]
    out = {"lines": {}, "added": [], "error": ""}
    if not (project_id and secret and wanted):
        return out
    async with httpx.AsyncClient(timeout=30) as http:
        users = await list_users(http, project_id, secret)
        known = {e164(u.get("phoneNumber") or ""): u for u in users}
        for number in wanted:
            user = known.get(number)
            if user is None:
                response = await http.post(
                    f"{SPECTRUM}/projects/{project_id}/users/",
                    json={"type": "shared", "phoneNumber": number},
                    headers=_basic(project_id, secret),
                )
                if response.status_code >= 400:
                    out["error"] = f"Photon wouldn't add {number[:-4]}••••: {_detail(response)}"
                    continue
                body = response.json() or {}
                user = body.get("user") or body.get("data") or body
                out["added"].append(number)
            line = user.get("assignedPhoneNumber") if isinstance(user, dict) else None
            out["lines"][number] = str(line or "")
        # a brand-new user may not have its line yet; one more look picks it up
        if any(not v for v in out["lines"].values()):
            for u in await list_users(http, project_id, secret):
                number = e164(u.get("phoneNumber") or "")
                if number in out["lines"] and not out["lines"][number]:
                    out["lines"][number] = str(u.get("assignedPhoneNumber") or "")
    return out


# ── connect (device login) ──


def _token_from(response) -> str:
    try:
        body = response.json() or {}
    except ValueError:
        body = {}
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    session = body.get("session") if isinstance(body.get("session"), dict) else {}
    for value in (
        body.get("access_token"),
        body.get("accessToken"),
        session.get("access_token"),
        data.get("access_token"),
        data.get("accessToken"),
        response.headers.get("set-auth-token"),
    ):
        if isinstance(value, str) and value.strip():
            token = value.strip()
            return token[7:].strip() if token.lower().startswith("bearer ") else token
    return ""


async def _dashboard(http, method: str, path: str, token: str, body: dict | None = None):
    response = await http.request(
        method, f"{DASHBOARD}{path}", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Photon {path} failed ({_detail(response)})")
    return response.json() or {}


async def _finish(http, token: str) -> None:
    """after the owner approves: project, secret, settings, numbers."""
    from core.settings import load_settings, save_settings
    from services import photon_channel

    session = await _dashboard(http, "GET", "/api/auth/get-session", token)
    user = session.get("user") if isinstance(session, dict) else None
    if not isinstance(user, dict) or not user:
        raise RuntimeError("Photon didn't recognize the sign-in")
    saved = load_settings()
    projects = _unwrap(await _dashboard(http, "GET", "/api/projects", token))
    project = next(
        (p for p in projects if str(p.get("id")) == str(saved.get("photon_project_id") or "")), None
    )
    project = project or next(
        (p for p in projects if str(p.get("name") or "").strip().lower() == PROJECT_NAME), None
    )
    if project is None:
        made = await _dashboard(
            http,
            "POST",
            "/api/projects",
            token,
            {
                "name": PROJECT_NAME,
                "location": "United States",
                "template": False,
                "observability": False,
            },
        )
        project = made.get("data") if isinstance(made.get("data"), dict) else made
    project_id = str(project.get("id") or "")
    if not project_id:
        raise RuntimeError("Photon didn't return a project")
    secret = str(saved.get("photon_project_secret") or "")
    if project_id != str(saved.get("photon_project_id") or "") or not secret:
        # the dashboard shows a secret only when it's made, so make a fresh one
        minted = await _dashboard(
            http, "POST", f"/api/projects/{project_id}/regenerate-secret", token, {}
        )
        secret = str(
            minted.get("projectSecret") or (minted.get("data") or {}).get("projectSecret") or ""
        )
        if not secret:
            raise RuntimeError("Photon didn't return a project secret")
    handles = list(saved.get("photon_owner_handles") or [])
    phone = e164(str(user.get("phoneNumber") or user.get("phone") or ""))
    if not any(e164(h) for h in handles) and phone:
        handles.append(phone)
    save_settings(
        {
            "photon_access_token": token,
            "photon_project_id": project_id,
            "photon_project_secret": secret,
            "photon_owner_handles": handles,
            "photon_enabled": True,
        }
    )
    numbers = await ensure_numbers(project_id, secret, handles)
    photon_channel.state.update(lines=numbers["lines"], register_error=numbers["error"])
    login.update(state="done", project=PROJECT_NAME, lines=numbers["lines"], error=numbers["error"])
    await photon_channel.restart()


async def _run_login() -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            response = await http.post(
                f"{DASHBOARD}/api/auth/device/code", json={"client_id": CLIENT_ID, "scope": SCOPE}
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Photon wouldn't start a sign-in ({_detail(response)})")
            code = response.json()
            login.update(
                state="waiting",
                user_code=code["user_code"],
                url=code.get("verification_uri_complete") or code["verification_uri"],
                error="",
            )
            pause = int(code["interval"]) if code.get("interval") is not None else 5
            deadline = time.monotonic() + int(code.get("expires_in") or 900)
            grant = {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": code["device_code"],
                "client_id": CLIENT_ID,
            }
            while time.monotonic() < deadline:
                await asyncio.sleep(pause)
                try:
                    reply = await http.post(f"{DASHBOARD}/api/auth/device/token", json=grant)
                except httpx.RequestError:
                    continue
                if reply.status_code == 200:
                    token = _token_from(reply)
                    if not token:
                        raise RuntimeError("Photon approved but sent no token")
                    login.update(state="finishing")
                    await _finish(http, token)
                    return
                if reply.status_code == 429:
                    pause += 10
                    continue
                error = ""
                try:
                    error = (reply.json() or {}).get("error") or ""
                except ValueError:
                    pass
                if error == "slow_down":
                    pause += 5
                elif error != "authorization_pending":
                    raise RuntimeError(
                        "the sign-in was turned down"
                        if error == "access_denied"
                        else f"Photon sign-in failed ({error or reply.status_code})"
                    )
            raise RuntimeError("the sign-in timed out; start it again")
        except Exception as exc:
            log.warning("photon connect failed: %s", type(exc).__name__)
            login.update(state="error", error=str(exc)[:300])


def start_login() -> dict:
    """begin a sign-in (or return the one already waiting)."""
    global _login_task
    if (
        _login_task is not None
        and not _login_task.done()
        and login.get("state") in ("starting", "waiting", "finishing")
    ):
        return public_login()
    login.clear()
    login.update(state="starting")
    _login_task = asyncio.get_running_loop().create_task(_run_login())
    return public_login()


def public_login() -> dict:
    return {k: login.get(k) for k in ("state", "user_code", "url", "error", "lines") if k in login}
