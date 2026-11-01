"""sign in with a provider: one attempt at a time, tokens in the existing encrypted columns.

the browser only ever polls alles. a device attempt is polled here in a background task; a
redirect attempt finishes in /api/signin/callback; a paste-code attempt finishes when the
owner sends back the code the provider showed. attempts are memory-only (one owner, like the
photon setup), so a restart loses a waiting attempt and the screen offers to start again.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from core.settings import data_dir, load_settings
from services import caldav_sync, mail_oauth, signin_clients
from services import signin_providers as providers
from services.signin_providers import NotReady, ProviderError

log = logging.getLogger("alles.signin")


class InvalidRequest(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AttemptGone(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


ACCOUNT_LOCK = threading.RLock()

# fixed words a screen may show. the dicts are read by scripts/server_messages.py, which
# keeps en.json and the seven translations in step with this module.
_MESSAGES = {
    "invalid_provider": {
        "code": "invalid_provider",
        "message": "that sign in provider isn't available",
    },
    "invalid_use": {"code": "invalid_use", "message": "that sign in use isn't available"},
    "attempt_gone": {
        "code": "signin_attempt_not_found",
        "message": "this sign in attempt is gone; start again",
    },
    "attempt_finished": {
        "code": "attempt_not_waiting",
        "message": "this sign in already finished",
    },
    "denied": {"code": "denied", "message": "the sign in was denied"},
    "provider_refused": {
        "code": "provider_error",
        "message": "the provider refused the sign in",
    },
    "refresh_refused": {
        "code": "needs_sign_in",
        "message": "sign in again to reconnect this account",
    },
    "bad_answer": {
        "code": "invalid_code_answer",
        "message": "that sign in answer didn't match; start again",
    },
    "calendar_busy": {
        "code": "calendar_busy",
        "message": "calendar sync is already set up for another server",
    },
}


def _reason(key: str) -> dict[str, str]:
    entry = _MESSAGES[key]
    return {"code": entry["code"], "text": entry["message"]}


def _api_message(key: str) -> tuple[str, str]:
    entry = _MESSAGES[key]
    return entry["code"], entry["message"]


# ── small helpers ────────────────────────────────────────────────────────────


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_dt(value) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value.replace(microsecond=0).isoformat() + "Z"
    return None


def _json(value, fallback):
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _new_id() -> str:
    return secrets.token_hex(4)


def effective_origin(origin: str) -> str:
    """google needs the address its client registered; the mail oauth base wins when set."""
    saved = str(load_settings().get("mail_oauth_redirect_base", "") or "").strip()
    return saved.rstrip("/") or (origin or "").rstrip("/")


# ── account metadata ─────────────────────────────────────────────────────────
#
# the tables already hold the tokens (encrypted); they don't hold the display metadata the
# accounts list needs (when it was signed in, when it last refreshed, the granted scopes).
# one small owner-private json file keeps that, so no migration is needed.


def _store_path() -> Path:
    return data_dir() / "signin-accounts.json"


def _load_store() -> dict:
    try:
        data = json.loads(_store_path().read_text("utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    accounts = data.get("accounts") if isinstance(data, dict) else None
    return accounts if isinstance(accounts, dict) else {}


def _save_store(accounts: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(f".{path.name}-{os.getpid()}")
    temp.write_text(
        json.dumps({"schema_version": 1, "accounts": accounts}, separators=(",", ":")),
        encoding="utf-8",
    )
    temp.chmod(0o600)
    os.replace(temp, path)


def _record(account_id: str, **fields) -> None:
    with ACCOUNT_LOCK:
        accounts = _load_store()
        current = accounts.get(account_id)
        entry = dict(current) if isinstance(current, dict) else {}
        entry.update({key: value for key, value in fields.items()})
        accounts[account_id] = entry
        _save_store(accounts)


def _forget(account_id: str) -> None:
    with ACCOUNT_LOCK:
        accounts = _load_store()
        if account_id in accounts:
            accounts.pop(account_id, None)
            _save_store(accounts)


def _stored(account_id: str) -> dict:
    with ACCOUNT_LOCK:
        value = _load_store().get(account_id)
        return dict(value) if isinstance(value, dict) else {}


def _needs_sign_in_error() -> dict[str, str]:
    return _reason("refresh_refused")


# ── attempts ─────────────────────────────────────────────────────────────────

_attempts: dict[str, dict] = {}
_by_use: dict[tuple[str, str], str] = {}
_tasks: dict[str, asyncio.Task] = {}
ATTEMPT_TTL = 3600


def _prune() -> None:
    now = time.time()
    for attempt_id, attempt in list(_attempts.items()):
        if attempt["state"] == "waiting" and now < (attempt.get("expires_at") or 0):
            continue
        if (
            now - float(attempt.get("finished_at") or attempt.get("created_at") or now)
            < ATTEMPT_TTL
        ):
            continue
        _attempts.pop(attempt_id, None)
        _tasks.pop(attempt_id, None)
        for key, value in list(_by_use.items()):
            if value == attempt_id:
                _by_use.pop(key, None)


def _expire_if_due(attempt: dict) -> None:
    if attempt["state"] != "waiting":
        return
    deadline = attempt.get("deadline")
    if deadline is not None and time.monotonic() >= float(deadline):
        attempt["state"] = "expired"
        attempt["finished_at"] = time.time()
        _by_use.pop((attempt["provider"], attempt["use"]), None)


def _cancel_previous(provider: str, use: str) -> None:
    attempt_id = _by_use.get((provider, use))
    if not attempt_id:
        return
    attempt = _attempts.get(attempt_id)
    if not attempt or attempt["state"] != "waiting":
        _by_use.pop((provider, use), None)
        return
    attempt["state"] = "cancelled"
    attempt["finished_at"] = time.time()
    task = _tasks.pop(attempt_id, None)
    if task is not None:
        task.cancel()
    _by_use.pop((provider, use), None)


def _new_attempt(provider: str, use: str, origin: str, flow: str, login_hint: str) -> dict:
    return {
        "id": _new_id(),
        "provider": provider,
        "use": use,
        "flow": flow,
        "state": "waiting",
        "error": None,
        "account": None,
        "origin": (origin or "").rstrip("/"),
        "login_hint": login_hint,
        "created_at": time.time(),
        "finished_at": None,
        "expires_at": None,
        "deadline": None,
        "interval": 5,
        "device_code": "",
        "user_code": "",
        "verify_url": "",
        "verify_url_complete": None,
        "state_token": "",
        "verifier": "",
        "redirect_uri": "",
    }


def _public_attempt(attempt: dict) -> dict:
    return {
        "attempt": attempt["id"],
        "provider": attempt["provider"],
        "use": attempt["use"],
        "state": attempt["state"],
        "error": attempt.get("error"),
        "account": attempt.get("account"),
    }


def _start_payload(attempt: dict, url: str = "") -> dict:
    if attempt["flow"] == providers.DEVICE:
        return {
            "attempt": attempt["id"],
            "provider": attempt["provider"],
            "use": attempt["use"],
            "flow": attempt["flow"],
            "user_code": attempt["user_code"],
            "verify_url": attempt["verify_url"],
            "verify_url_complete": attempt.get("verify_url_complete"),
            "expires_at": _iso(attempt.get("expires_at")),
            "poll_every": int(attempt["interval"]),
        }
    return {
        "attempt": attempt["id"],
        "provider": attempt["provider"],
        "use": attempt["use"],
        "flow": attempt["flow"],
        "url": url,
    }


def _finish(attempt: dict, account: dict | None) -> None:
    attempt["state"] = "done"
    attempt["error"] = None
    attempt["account"] = account
    attempt["finished_at"] = time.time()
    _by_use.pop((attempt["provider"], attempt["use"]), None)


def _fail(attempt: dict, key: str, *, state: str = "error") -> None:
    attempt["state"] = state
    attempt["error"] = _reason(key)
    attempt["finished_at"] = time.time()
    _by_use.pop((attempt["provider"], attempt["use"]), None)


def _spawn(attempt: dict) -> None:
    task = asyncio.get_running_loop().create_task(_poll_attempt(attempt))
    _tasks[attempt["id"]] = task


async def start(
    provider: str,
    use: str,
    *,
    login_hint: str = "",
    origin: str = "",
) -> dict:
    if provider not in providers.provider_ids():
        raise InvalidRequest(*_api_message("invalid_provider"))
    if not providers.known_use(provider, use):
        raise InvalidRequest(*_api_message("invalid_use"))
    redirect_origin = effective_origin(origin)
    reason = providers.not_ready(provider, redirect_origin)
    if reason:
        raise NotReady(reason["code"], reason["text"])

    _prune()
    _cancel_previous(provider, use)
    flow = providers.flow_for(provider)
    attempt = _new_attempt(provider, use, origin, flow, login_hint)
    _attempts[attempt["id"]] = attempt
    _by_use[(provider, use)] = attempt["id"]

    try:
        if provider == "github":
            body = await providers.github_start(signin_clients.github_client_id(), login_hint)
            _fill_device(attempt, body, fallback_url="https://github.com/login/device")
            _spawn(attempt)
        elif provider == "microsoft":
            body = await providers.microsoft_start(signin_clients.microsoft_client_id(), login_hint)
            _fill_device(attempt, body, fallback_url="https://microsoft.com/devicelogin")
            _spawn(attempt)
        elif provider == "google":
            state = providers._state()
            attempt["state_token"] = state
            attempt["redirect_uri"] = providers.signin_redirect_uri(redirect_origin, "google")
            attempt["expires_at"] = time.time() + 600
            attempt["deadline"] = time.monotonic() + 600
            url = providers.google_auth_url(redirect_origin, use, state, login_hint)
            return _start_payload(attempt, url)
        elif provider == "anthropic":
            verifier, challenge = providers.pkce_pair()
            state = providers._state()
            attempt.update(
                state_token=state,
                verifier=verifier,
                expires_at=time.time() + 600,
                deadline=time.monotonic() + 600,
            )
            return _start_payload(attempt, providers.anthropic_auth_url(challenge, state))
        elif provider == "openai":
            verifier, challenge = providers.pkce_pair()
            state = providers._state()
            attempt.update(
                state_token=state,
                verifier=verifier,
                expires_at=time.time() + 600,
                deadline=time.monotonic() + 600,
            )
            return _start_payload(attempt, providers.openai_auth_url(challenge, state))
    except ProviderError as exc:
        _fail(attempt, "provider_refused")
        attempt["error"] = {"code": "provider_error", "text": str(exc)[:200]}
        raise
    except Exception:
        _fail(attempt, "provider_refused")
        raise
    return _start_payload(attempt)


def _fill_device(attempt: dict, body: dict, *, fallback_url: str) -> None:
    try:
        raw_interval = body.get("interval")
        # a fake provider in a test may send 0; production providers send 5 or more
        interval = 0 if raw_interval == 0 else max(1, int(raw_interval or 5))
    except (TypeError, ValueError):
        interval = 5
    try:
        expires_in = max(30, int(body.get("expires_in") or 900))
    except (TypeError, ValueError):
        expires_in = 900
    attempt.update(
        device_code=str(body.get("device_code") or ""),
        user_code=str(body.get("user_code") or ""),
        verify_url=str(body.get("verification_uri") or fallback_url),
        verify_url_complete=body.get("verification_uri_complete") or None,
        interval=interval,
        expires_at=time.time() + expires_in,
        deadline=time.monotonic() + expires_in,
    )


async def _poll_attempt(attempt: dict) -> None:
    try:
        while attempt["state"] == "waiting":
            if time.monotonic() >= float(attempt.get("deadline") or 0):
                attempt["state"] = "expired"
                attempt["finished_at"] = time.time()
                _by_use.pop((attempt["provider"], attempt["use"]), None)
                return
            await asyncio.sleep(attempt["interval"])
            if attempt["state"] != "waiting":
                return
            if time.monotonic() >= float(attempt.get("deadline") or 0):
                attempt["state"] = "expired"
                attempt["finished_at"] = time.time()
                _by_use.pop((attempt["provider"], attempt["use"]), None)
                return
            try:
                status, body = await _poll_provider(attempt)
            except httpx.HTTPError:
                continue
            error = str(body.get("error") or "")
            if status == 200 and body.get("access_token"):
                await _finish_device(attempt, body)
                return
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                attempt["interval"] = int(attempt["interval"]) + 5
                continue
            if error in ("access_denied", "authorization_declined"):
                _fail(attempt, "denied", state="denied")
                return
            if error in ("expired_token", "token_expired"):
                attempt["state"] = "expired"
                attempt["finished_at"] = time.time()
                _by_use.pop((attempt["provider"], attempt["use"]), None)
                return
            if status >= 500 or status == 429:
                continue
            text = (
                str(body.get("error_description") or body.get("message") or error or "")
                or f"HTTP {status}"
            )
            attempt["state"] = "error"
            attempt["error"] = {"code": "provider_error", "text": text[:200]}
            attempt["finished_at"] = time.time()
            _by_use.pop((attempt["provider"], attempt["use"]), None)
            return
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # never leak a token in the message
        log.warning("sign in attempt failed: %s", type(exc).__name__)
        _fail(attempt, "provider_refused")
    finally:
        _tasks.pop(attempt["id"], None)


async def _poll_provider(attempt: dict) -> tuple[int, dict]:
    if attempt["provider"] == "github":
        return await providers.github_poll(
            signin_clients.github_client_id(), attempt["device_code"]
        )
    return await providers.microsoft_poll(
        signin_clients.microsoft_client_id(), attempt["device_code"]
    )


async def _finish_device(attempt: dict, body: dict) -> None:
    provider = attempt["provider"]
    if provider == "github":
        login, email = "", None
        info = await providers.github_user(str(body.get("access_token") or ""))
        if info:
            login = str(info.get("login") or "")
            email = str(info.get("email") or "") or None
        await _save_github(attempt, body, login=login or "github", email=email)
    elif provider == "microsoft":
        login, email = providers.microsoft_identity(body, attempt.get("login_hint", ""))
        await _save_microsoft(attempt, body, login=login, email=email)
    _finish(attempt, _account_by_id(attempt.get("account_id", "")))


# ── saving tokens ────────────────────────────────────────────────────────────


async def _save_github(
    attempt: dict, body: dict, *, login: str, email: str | None, refreshed_at: str | None = None
) -> str:
    from core.database import Connection, SessionLocal

    access = str(body.get("access_token") or "")
    refresh = str(body.get("refresh_token") or "")
    expires = providers.expires_at(body) if body.get("expires_in") else None
    scopes = providers.scopes_list(body, providers.GITHUB_SCOPES)
    signed_in_at = _iso(time.time())
    db = SessionLocal()
    try:
        row = db.query(Connection).filter(Connection.service == "github").first()
        if row is None:
            row = Connection(service="github")
            db.add(row)
        row.token = access
        meta = _json(row.meta, {})
        signin = meta.get("signin") if isinstance(meta.get("signin"), dict) else {}
        signin.update(
            {
                "provider": "github",
                "use": "github",
                "login": login,
                "email": email,
                "scopes": scopes,
                "signed_in_at": signin.get("signed_in_at") or signed_in_at,
                "refreshed_at": refreshed_at,
                "state": "ok",
                "error": None,
                "expires_at": expires,
            }
        )
        if refresh:
            signin["refresh_token"] = refresh
        meta["signin"] = signin
        row.meta = json.dumps(meta, separators=(",", ":"), sort_keys=True)
        db.flush()
        account_id = row.id
        db.commit()
    finally:
        db.close()
    attempt["account_id"] = account_id
    _record(
        account_id,
        provider="github",
        use="github",
        login=login,
        email=email,
        scopes=scopes,
        signed_in_at=signed_in_at,
        refreshed_at=refreshed_at,
        state="ok",
        error=None,
        expires_at=expires,
    )
    return account_id


async def _save_microsoft(
    attempt: dict, body: dict, *, login: str, email: str | None, refreshed_at: str | None = None
) -> str:
    from core.database import MailAccount, SessionLocal
    from services import mail as mailsvc

    access = str(body.get("access_token") or "")
    refresh = str(body.get("refresh_token") or "")
    expires = providers.expires_at(body)
    scopes = providers.scopes_list(body, providers.MICROSOFT_SCOPES)
    signed_in_at = _iso(time.time())
    address = email or (login if "@" in login else "")
    db = SessionLocal()
    try:
        row = None
        if address:
            row = db.query(MailAccount).filter(MailAccount.email == address).first()
        if row is None:
            row = (
                db.query(MailAccount)
                .filter(
                    MailAccount.auth_type == "oauth",
                    MailAccount.oauth_provider == "microsoft",
                    MailAccount.username == login,
                )
                .first()
            )
        if row is None:
            row = MailAccount(email=address or login, name=address or login)
            db.add(row)
            db.flush()
        else:
            row.revision += 1
        row.auth_type = "oauth"
        row.oauth_provider = "microsoft"
        row.username = address or login
        row.password = ""
        row.imap_host, row.imap_port = providers.OUTLOOK_IMAP
        row.smtp_host, row.smtp_port = providers.OUTLOOK_SMTP
        row.use_ssl = True
        row.oauth_access_token = access
        if refresh:
            row.oauth_refresh_token = refresh
        row.oauth_expires_at = expires
        db.flush()
        account_id = row.id
        db.commit()
    finally:
        db.close()
    attempt["account_id"] = account_id
    mailsvc.clear_cache()
    _record(
        account_id,
        provider="microsoft",
        use="mail",
        login=address or login,
        email=address or None,
        scopes=scopes,
        signed_in_at=signed_in_at,
        refreshed_at=refreshed_at,
        state="ok",
        error=None,
        expires_at=expires,
    )
    return account_id


async def _save_google(attempt: dict, body: dict, email: str, scopes: list[str]) -> str:
    from core.database import MailAccount, ModelEndpoint, SessionLocal
    from services import mail as mailsvc

    access = str(body.get("access_token") or "")
    refresh = str(body.get("refresh_token") or "")
    expires = providers.expires_at(body)
    signed_in_at = _iso(time.time())
    use = attempt["use"]
    account_id = ""

    if use == "mail":
        db = SessionLocal()
        try:
            row = db.query(MailAccount).filter(MailAccount.email == email).first()
            if row is None:
                row = MailAccount(email=email, name=email)
                db.add(row)
                db.flush()
            else:
                row.revision += 1
            row.auth_type = "oauth"
            row.oauth_provider = "google"
            row.username = email
            row.password = ""
            row.imap_host, row.imap_port = mail_oauth.GMAIL_IMAP
            row.smtp_host, row.smtp_port = mail_oauth.GMAIL_SMTP
            row.use_ssl = True
            row.oauth_access_token = access
            if refresh:
                row.oauth_refresh_token = refresh
            row.oauth_expires_at = expires
            db.flush()
            account_id = row.id
            db.commit()
        finally:
            db.close()
        mailsvc.clear_cache()
        _record(
            account_id,
            provider="google",
            use="mail",
            login=email,
            email=email,
            scopes=scopes,
            signed_in_at=signed_in_at,
            refreshed_at=None,
            state="ok",
            error=None,
            expires_at=expires,
        )
        attempt["account_id"] = account_id
        return account_id

    if use == "calendar":
        cfg = caldav_sync.load_cfg()
        current = str(cfg.get("provider") or "")
        if cfg.get("url") and not (cfg.get("auth") == "oauth" and current == "google"):
            raise ProviderError(_MESSAGES["calendar_busy"]["message"])
        if not refresh:
            # google only sends a refresh token on the first consent; keep the saved one
            refresh = str(caldav_sync.oauth_tokens(cfg).get("refresh_token") or "")
        tokens = {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": expires,
            "scopes": scopes,
        }
        caldav_sync.save_cfg(
            {
                "url": f"{providers.GOOGLE_CALDAV_ROOT}/{email}/user",
                "username": email,
                "password": "",
                "auth": "oauth",
                "provider": "google",
                "oauth_tokens": tokens,
            },
            keep_password=False,
        )
        _record(
            "caldav",
            provider="google",
            use="calendar",
            login=email,
            email=email,
            scopes=scopes,
            signed_in_at=signed_in_at,
            refreshed_at=None,
            state="ok",
            error=None,
            expires_at=expires,
        )
        attempt["account_id"] = "caldav"
        return "caldav"

    # use == "models" (gemini)
    db = SessionLocal()
    try:
        row = (
            db.query(ModelEndpoint)
            .filter(ModelEndpoint.auth_type == "oauth", ModelEndpoint.provider_id == "gemini")
            .first()
        )
        project_id = ""
        if row is not None:
            project_id = str(getattr(row, "oauth_project_id", "") or "")
        if not project_id:
            other = db.query(ModelEndpoint).filter(ModelEndpoint.provider_id == "gemini").first()
            project_id = str(getattr(other, "oauth_project_id", "") or "") if other else ""
        if row is None:
            row = ModelEndpoint(name="Gemini", base_url=providers.GEMINI_BASE_URL)
            db.add(row)
        client_id, client_secret = mail_oauth._creds()
        row.name = row.name or "Gemini"
        row.base_url = providers.GEMINI_BASE_URL
        row.provider_id = "gemini"
        row.auth_type = "oauth"
        row.auth_status = "connected"
        row.auth_error = ""
        row.account_identity = email
        row.api_key = access
        row.oauth_client_id = client_id
        row.oauth_client_secret = client_secret
        row.oauth_project_id = project_id
        if refresh:
            row.oauth_refresh_token = refresh
        row.oauth_expires_at = expires
        row.oauth_scopes = json.dumps(scopes, separators=(",", ":"))
        row.provider_adapter = "openai-compatible"
        row.enabled = True
        db.flush()
        account_id = row.id
        db.commit()
    finally:
        db.close()
    from services import model_auth

    model_auth._register_runtime_token(access, project_id)
    _record(
        account_id,
        provider="google",
        use="models",
        login=email,
        email=email,
        scopes=scopes,
        signed_in_at=signed_in_at,
        refreshed_at=None,
        state="ok",
        error=None,
        expires_at=expires,
    )
    attempt["account_id"] = account_id
    await _refresh_catalog(account_id)
    return account_id


async def _save_subscription(attempt: dict, body: dict) -> str:
    """anthropic or openai: one model endpoint with the owner's subscription tokens."""
    from core.database import ModelEndpoint, SessionLocal

    provider = attempt["provider"]
    access = str(body.get("access_token") or "")
    refresh = str(body.get("refresh_token") or "")
    expires = providers.expires_at(body)
    scopes = providers.scopes_list(
        body,
        providers.ANTHROPIC_SCOPES if provider == "anthropic" else (providers.OPENAI_SCOPE,),
    )
    signed_in_at = _iso(time.time())
    if provider == "anthropic":
        login, email = _anthropic_identity(body)
        name, base_url = "Claude", providers.ANTHROPIC_BASE_URL
    else:
        login, email = providers.openai_identity(body)
        name, base_url = "ChatGPT", providers.OPENAI_CODEX_BASE_URL
    db = SessionLocal()
    try:
        row = (
            db.query(ModelEndpoint)
            .filter(ModelEndpoint.auth_type == "oauth", ModelEndpoint.provider_id == provider)
            .first()
        )
        if row is None:
            row = ModelEndpoint(name=name, base_url=base_url)
            db.add(row)
        row.name = row.name or name
        row.base_url = base_url
        row.provider_id = provider
        row.auth_type = "oauth"
        row.auth_status = "connected"
        row.auth_error = ""
        row.account_identity = email or login
        row.api_key = access
        if refresh:
            row.oauth_refresh_token = refresh
        row.oauth_expires_at = expires
        row.oauth_scopes = json.dumps(scopes, separators=(",", ":"))
        row.provider_adapter = "anthropic" if provider == "anthropic" else "openai-compatible"
        row.enabled = True
        db.flush()
        account_id = row.id
        db.commit()
    finally:
        db.close()
    _record(
        account_id,
        provider=provider,
        use="models",
        login=login,
        email=email,
        scopes=scopes,
        signed_in_at=signed_in_at,
        refreshed_at=None,
        state="ok",
        error=None,
        expires_at=expires,
    )
    attempt["account_id"] = account_id
    await _refresh_catalog(account_id)
    return account_id


async def _refresh_catalog(account_id: str) -> None:
    """best effort: a new model endpoint should offer its models without waiting for the job."""
    from core.database import ModelEndpoint, SessionLocal
    from services import model_catalog

    db = SessionLocal()
    try:
        row = db.get(ModelEndpoint, account_id)
        if row is not None:
            await model_catalog.refresh_endpoint(row)
            db.commit()
    except Exception:
        pass
    finally:
        db.close()


def _anthropic_identity(payload: dict) -> tuple[str, str | None]:
    claims = providers.jwt_claims(str(payload.get("id_token") or ""))
    email = str(claims.get("email") or "").strip().lower()
    return (email or "claude subscription"), (email or None)


# ── finishing a redirect or a pasted code ───────────────────────────────────


async def finish_redirect(provider: str, *, code: str, state: str, error: str) -> dict | None:
    found = next(
        (
            item
            for item in _attempts.values()
            if item["provider"] == provider and item.get("state_token") == state
        ),
        None,
    )
    if found is None:
        return None
    _expire_if_due(found)
    if found["state"] != "waiting":
        return {"attempt": found["id"], "origin": found["origin"]}
    if error:
        _fail(found, "denied", state="denied")
        return {"attempt": found["id"], "origin": found["origin"]}
    if not code:
        _fail(found, "provider_refused")
        return {"attempt": found["id"], "origin": found["origin"]}
    try:
        body = await providers.google_exchange(code, found["redirect_uri"])
        email = providers.google_identity(body)[1]
        if not email:
            email = (await asyncio.to_thread(mail_oauth.fetch_email, body["access_token"])).strip()
        if not email:
            raise ProviderError(_MESSAGES["provider_refused"]["message"])
        scopes = providers.scopes_list(body, providers.google_scopes(found["use"]))
        await _save_google(found, body, email, scopes)
        _finish(found, _account_by_id(found.get("account_id", "")))
    except ProviderError as exc:
        found["state"] = "error"
        found["error"] = {"code": "provider_error", "text": str(exc)[:200]}
        found["finished_at"] = time.time()
        _by_use.pop((found["provider"], found["use"]), None)
    except Exception as exc:
        log.warning("google sign in failed: %s", type(exc).__name__)
        _fail(found, "provider_refused")
    return {"attempt": found["id"], "origin": found["origin"]}


def _parse_pasted_code(text: str, state: str) -> tuple[str, str]:
    """accept the provider's code#state, its full callback url, or a query string."""
    raw = (text or "").strip()
    if not raw:
        return "", ""
    try:
        parsed = urlsplit(raw)
        if parsed.query:
            query = parse_qs(parsed.query)
            code = (query.get("code") or [""])[0]
            got_state = (query.get("state") or [""])[0]
            if code:
                return code, got_state or state
    except ValueError:
        pass
    if "#" in raw:
        code, got_state = raw.split("#", 1)
        if code:
            return code.strip(), got_state.strip() or state
    for piece in raw.split("&"):
        if piece.startswith("code="):
            return piece[5:], state
    return raw, state


async def finish_code(attempt_id: str, code: str) -> dict:
    attempt = _attempts.get(attempt_id)
    if attempt is None:
        raise AttemptGone(_MESSAGES["attempt_gone"]["message"])
    _expire_if_due(attempt)
    if attempt["state"] != "waiting":
        if attempt["flow"] == providers.PASTE_CODE:
            return _public_attempt(attempt)
        raise AttemptGone(_MESSAGES["attempt_finished"]["message"])
    parsed, got_state = _parse_pasted_code(code, attempt.get("state_token", ""))
    if not parsed or (
        got_state and attempt.get("state_token") and got_state != attempt["state_token"]
    ):
        _fail(attempt, "bad_answer")
        return _public_attempt(attempt)
    try:
        if attempt["provider"] == "anthropic":
            body = await providers.anthropic_exchange(parsed, got_state, attempt["verifier"])
            await _save_subscription(attempt, body)
        elif attempt["provider"] == "openai":
            body = await providers.openai_exchange(parsed, attempt["verifier"])
            await _save_subscription(attempt, body)
        else:
            raise ProviderError(_MESSAGES["provider_refused"]["message"])
        _finish(attempt, _account_by_id(attempt.get("account_id", "")))
    except ProviderError as exc:
        attempt["state"] = "error"
        attempt["error"] = {"code": "provider_error", "text": str(exc)[:200]}
        attempt["finished_at"] = time.time()
        _by_use.pop((attempt["provider"], attempt["use"]), None)
    except Exception as exc:
        log.warning("subscription sign in failed: %s", type(exc).__name__)
        _fail(attempt, "provider_refused")
    return _public_attempt(attempt)


def get_attempt(attempt_id: str) -> dict | None:
    attempt = _attempts.get(attempt_id)
    if attempt is None:
        return None
    _expire_if_due(attempt)
    return _public_attempt(attempt)


def cancel(attempt_id: str) -> dict | None:
    attempt = _attempts.get(attempt_id)
    if attempt is None:
        return None
    if attempt["state"] == "waiting":
        attempt["state"] = "cancelled"
        attempt["finished_at"] = time.time()
        task = _tasks.pop(attempt_id, None)
        if task is not None:
            task.cancel()
        _by_use.pop((attempt["provider"], attempt["use"]), None)
    return {"attempt": attempt["id"], "state": attempt["state"]}


# ── accounts ────────────────────────────────────────────────────────────────


def _account_fields(provider: str, use: str) -> dict:
    return {
        "id": "",
        "provider": provider,
        "use": use,
        "login": "",
        "email": None,
        "scopes": [],
        "state": "ok",
        "error": None,
        "signed_in_at": None,
        "refreshed_at": None,
        "expires_at": None,
    }


def _account_by_id(account_id: str) -> dict | None:
    if account_id == "caldav":
        return _calendar_account()
    from core.database import Connection, MailAccount, ModelEndpoint, SessionLocal

    db = SessionLocal()
    try:
        connection = db.get(Connection, account_id)
        if connection is not None and connection.service == "github":
            return _github_account(connection)
        mail = db.get(MailAccount, account_id)
        if mail is not None and mail.auth_type == "oauth":
            return _mail_account(mail)
        endpoint = db.get(ModelEndpoint, account_id)
        if endpoint is not None and _model_signed_in(endpoint):
            return _model_account(endpoint)
    finally:
        db.close()
    return None


def _github_account(row) -> dict:
    meta = _json(row.meta, {})
    signin = meta.get("signin") if isinstance(meta.get("signin"), dict) else {}
    stored = _stored(row.id)
    item = _account_fields("github", "github")
    item.update(
        id=row.id,
        login=stored.get("login") or signin.get("login") or "",
        email=stored.get("email") or signin.get("email"),
        scopes=stored.get("scopes") or signin.get("scopes") or [],
        state=stored.get("state")
        or signin.get("state")
        or ("ok" if row.token else "needs_sign_in"),
        error=stored.get("error") if "error" in stored else signin.get("error"),
        signed_in_at=stored.get("signed_in_at") or signin.get("signed_in_at"),
        refreshed_at=stored.get("refreshed_at") or signin.get("refreshed_at"),
        expires_at=(
            stored.get("expires_at")
            if stored.get("expires_at") is not None
            else _iso(signin.get("expires_at"))
        ),
    )
    if not row.token:
        item["state"] = "needs_sign_in"
    if item["state"] == "needs_sign_in" and not item["error"]:
        item["error"] = _needs_sign_in_error()
    return item


def _mail_account(row) -> dict:
    provider = (row.oauth_provider or "google").strip().lower()
    stored = _stored(row.id)
    if provider == "microsoft":
        scopes = stored.get("scopes") or list(providers.MICROSOFT_SCOPES)
    else:
        scopes = stored.get("scopes") or list(providers.google_scopes("mail"))
    item = _account_fields(provider, "mail")
    item.update(
        id=row.id,
        login=stored.get("login") or row.email or row.username or "",
        email=stored.get("email") if stored.get("email") is not None else (row.email or None),
        scopes=scopes,
        state=stored.get("state")
        or ("ok" if (row.oauth_access_token or row.oauth_refresh_token) else "needs_sign_in"),
        error=stored.get("error"),
        signed_in_at=stored.get("signed_in_at") or _iso_dt(row.created_at),
        refreshed_at=stored.get("refreshed_at"),
        expires_at=_iso(row.oauth_expires_at),
    )
    if item["state"] == "needs_sign_in" and not item["error"]:
        item["error"] = _needs_sign_in_error()
    return item


def _model_signed_in(row) -> bool:
    return bool(row.auth_type == "oauth" and (row.api_key or row.oauth_refresh_token)) and (
        (row.auth_status or "").strip().lower() != "revoked"
    )


def _model_account(row) -> dict:
    provider = (row.provider_id or "gemini").strip().lower()
    stored = _stored(row.id)
    scopes = stored.get("scopes") or _json(row.oauth_scopes, [])
    status = (row.auth_status or "").strip().lower()
    if provider == "gemini":
        signed_in_at = stored.get("signed_in_at") or _iso_dt(row.created_at)
    else:
        signed_in_at = stored.get("signed_in_at") or _iso_dt(row.created_at)
    state = stored.get("state") or (
        "needs_sign_in" if status in {"expired", "failed", "revoked"} else "ok"
    )
    if not row.api_key and not row.oauth_refresh_token:
        state = "needs_sign_in"
    item = _account_fields(provider, "models")
    item.update(
        id=row.id,
        login=stored.get("login") or row.account_identity or provider,
        email=stored.get("email"),
        scopes=scopes,
        state=state,
        error=stored.get("error"),
        signed_in_at=signed_in_at,
        refreshed_at=stored.get("refreshed_at"),
        expires_at=_iso(row.oauth_expires_at),
    )
    if item["state"] == "needs_sign_in" and not item["error"]:
        item["error"] = _needs_sign_in_error()
    return item


def _calendar_account() -> dict | None:
    cfg = caldav_sync.load_cfg()
    if cfg.get("auth") != "oauth":
        return None
    tokens = caldav_sync.oauth_tokens(cfg)
    stored = _stored("caldav")
    item = _account_fields(str(cfg.get("provider") or "google"), "calendar")
    item.update(
        id="caldav",
        login=stored.get("login") or cfg.get("username") or "",
        email=stored.get("email") or (cfg.get("username") or None),
        scopes=stored.get("scopes") or [providers.GOOGLE_CALENDAR_SCOPE],
        state=stored.get("state") or ("ok" if tokens else "needs_sign_in"),
        error=stored.get("error"),
        signed_in_at=stored.get("signed_in_at"),
        refreshed_at=stored.get("refreshed_at"),
        expires_at=_iso(tokens.get("expires_at")),
    )
    if not tokens:
        item["state"] = "needs_sign_in"
    if item["state"] == "needs_sign_in" and not item["error"]:
        item["error"] = _needs_sign_in_error()
    return item


def list_accounts() -> dict:
    items: list[dict] = []
    seen: set[str] = set()
    from core.database import Connection, MailAccount, ModelEndpoint, SessionLocal

    db = SessionLocal()
    try:
        for row in db.query(Connection).filter(Connection.service == "github").all():
            meta = _json(row.meta, {})
            if not isinstance(meta.get("signin"), dict):
                continue
            item = _github_account(row)
            if item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)
        for row in db.query(MailAccount).filter(MailAccount.auth_type == "oauth").all():
            if not (row.oauth_access_token or row.oauth_refresh_token):
                continue
            item = _mail_account(row)
            if item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)
        for row in db.query(ModelEndpoint).filter(ModelEndpoint.auth_type == "oauth").all():
            if not _model_signed_in(row):
                continue
            item = _model_account(row)
            if item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)
    finally:
        db.close()
    calendar = _calendar_account()
    if calendar is not None and calendar["id"] not in seen:
        items.append(calendar)
    return {"accounts": items}


# ── refresh and sign out ────────────────────────────────────────────────────


async def _mark_needs_sign_in(account_id: str, error: dict | None = None) -> None:
    from core.database import MailAccount, ModelEndpoint, SessionLocal

    error = error or _needs_sign_in_error()
    _record(account_id, state="needs_sign_in", error=error)
    db = SessionLocal()
    try:
        mail = db.get(MailAccount, account_id)
        if mail is not None:
            mail.oauth_expires_at = 0
            db.commit()
        endpoint = db.get(ModelEndpoint, account_id)
        if endpoint is not None:
            endpoint.auth_status = "expired"
            endpoint.auth_error = "oauth_refresh_failed"
            db.commit()
    finally:
        db.close()


def _update_github_meta(account_id: str, **fields) -> None:
    from core.database import Connection, SessionLocal

    db = SessionLocal()
    try:
        row = db.get(Connection, account_id)
        if row is None:
            return
        meta = _json(row.meta, {})
        signin = meta.get("signin") if isinstance(meta.get("signin"), dict) else {}
        signin.update(fields)
        meta["signin"] = signin
        row.meta = json.dumps(meta, separators=(",", ":"), sort_keys=True)
        db.commit()
    finally:
        db.close()


async def refresh_account(account_id: str) -> dict | None:
    item = _account_by_id(account_id)
    if item is None:
        return None
    provider = item["provider"]
    try:
        if item["use"] == "github":
            await _refresh_github(account_id, item)
        elif item["use"] == "mail":
            await _refresh_mail(account_id, provider)
        elif item["use"] == "models":
            await _refresh_model(account_id, provider)
        elif item["use"] == "calendar":
            await _refresh_calendar()
    except ProviderError as exc:
        if not exc.permanent:
            log.info("sign in refresh deferred: %s", type(exc).__name__)
            return _account_by_id(account_id)
        await _mark_needs_sign_in(
            account_id,
            {
                "code": "needs_sign_in",
                "text": str(exc)[:200] or _needs_sign_in_error()["text"],
            },
        )
    except RuntimeError as exc:
        await _mark_needs_sign_in(
            account_id,
            {
                "code": "needs_sign_in",
                "text": str(exc)[:200] or _needs_sign_in_error()["text"],
            },
        )
    except httpx.HTTPError:
        log.info("sign in refresh deferred: network error")
        return _account_by_id(account_id)
    except Exception as exc:
        log.warning("sign in refresh failed: %s", type(exc).__name__)
        await _mark_needs_sign_in(account_id)
    return _account_by_id(account_id)


async def _refresh_github(account_id: str, item: dict) -> None:
    from core.database import Connection, SessionLocal

    db = SessionLocal()
    try:
        row = db.get(Connection, account_id)
        if row is None:
            raise ProviderError(_MESSAGES["provider_refused"]["message"])
        meta = _json(row.meta, {})
        signin = meta.get("signin") if isinstance(meta.get("signin"), dict) else {}
        refresh_token = str(signin.get("refresh_token") or "")
        if not refresh_token:
            info = await providers.github_user(row.token or "")
            if not info:
                raise ProviderError(_MESSAGES["refresh_refused"]["message"])
            signin["login"] = info.get("login") or signin.get("login") or ""
            signin["email"] = info.get("email") or signin.get("email")
            meta["signin"] = signin
            row.meta = json.dumps(meta, separators=(",", ":"), sort_keys=True)
            db.commit()
            return
        body = await providers.github_refresh(signin_clients.github_client_id(), refresh_token)
        row.token = str(body.get("access_token") or "")
        if body.get("refresh_token"):
            signin["refresh_token"] = str(body["refresh_token"])
        signin["expires_at"] = providers.expires_at(body) if body.get("expires_in") else None
        signin["refreshed_at"] = _iso(time.time())
        signin["state"] = "ok"
        signin["error"] = None
        meta["signin"] = signin
        row.meta = json.dumps(meta, separators=(",", ":"), sort_keys=True)
        db.commit()
    finally:
        db.close()
    _record(account_id, state="ok", error=None, refreshed_at=_iso(time.time()))


async def _refresh_mail(account_id: str, provider: str) -> None:
    from core.database import MailAccount, SessionLocal

    db = SessionLocal()
    try:
        row = db.get(MailAccount, account_id)
        if row is None:
            raise ProviderError(_MESSAGES["provider_refused"]["message"])
        refresh_token = str(row.oauth_refresh_token or "")
        if not refresh_token:
            if row.oauth_access_token and float(row.oauth_expires_at or 0) - 60 > time.time():
                return
            raise ProviderError(_MESSAGES["refresh_refused"]["message"])
        if provider == "microsoft":
            body = await providers.microsoft_refresh(
                signin_clients.microsoft_client_id(), refresh_token
            )
        else:
            body = await providers.google_refresh(refresh_token)
        row.oauth_access_token = str(body.get("access_token") or "")
        if body.get("refresh_token"):
            row.oauth_refresh_token = str(body["refresh_token"])
        row.oauth_expires_at = providers.expires_at(body)
        db.commit()
    finally:
        db.close()
    _record(account_id, state="ok", error=None, refreshed_at=_iso(time.time()))


async def _refresh_model(account_id: str, provider: str) -> None:
    from core.database import ModelEndpoint, SessionLocal
    from services import model_auth

    db = SessionLocal()
    try:
        row = db.get(ModelEndpoint, account_id)
        if row is None:
            raise ProviderError(_MESSAGES["provider_refused"]["message"])
        refresh_token = str(row.oauth_refresh_token or "")
        if not refresh_token and provider in {"anthropic", "openai"}:
            if row.api_key and float(row.oauth_expires_at or 0) - 60 > time.time():
                return
            raise ProviderError(_MESSAGES["refresh_refused"]["message"])
        if provider == "gemini":
            if not await model_auth.refresh_gemini_endpoint(row, force=True):
                raise ProviderError(_MESSAGES["refresh_refused"]["message"])
        elif provider == "anthropic":
            body = await providers.anthropic_refresh(refresh_token)
            row.api_key = str(body.get("access_token") or "")
            if body.get("refresh_token"):
                row.oauth_refresh_token = str(body["refresh_token"])
            row.oauth_expires_at = providers.expires_at(body)
            row.auth_status = "connected"
            row.auth_error = ""
        elif provider == "openai":
            body = await providers.openai_refresh(refresh_token)
            row.api_key = str(body.get("access_token") or "")
            if body.get("refresh_token"):
                row.oauth_refresh_token = str(body["refresh_token"])
            row.oauth_expires_at = providers.expires_at(body)
            row.auth_status = "connected"
            row.auth_error = ""
        else:
            raise ProviderError(_MESSAGES["refresh_refused"]["message"])
        db.commit()
    finally:
        db.close()
    _record(account_id, state="ok", error=None, refreshed_at=_iso(time.time()))


async def _refresh_calendar() -> None:
    cfg = caldav_sync.load_cfg()
    tokens = caldav_sync.oauth_tokens(cfg)
    refresh_token = str(tokens.get("refresh_token") or "")
    if not refresh_token:
        if tokens.get("access_token") and float(tokens.get("expires_at") or 0) - 60 > time.time():
            return
        raise ProviderError(_MESSAGES["refresh_refused"]["message"])
    body = await providers.google_refresh(refresh_token)
    tokens["access_token"] = str(body.get("access_token") or "")
    if body.get("refresh_token"):
        tokens["refresh_token"] = str(body["refresh_token"])
    tokens["expires_at"] = providers.expires_at(body)
    caldav_sync.save_cfg({**cfg, "oauth_tokens": tokens}, keep_password=False)
    _record("caldav", state="ok", error=None, refreshed_at=_iso(time.time()))


async def sign_out(account_id: str) -> dict | None:
    item = _account_by_id(account_id)
    if item is None:
        return None
    revoked = False
    use = item["use"]
    provider = item["provider"]
    if use == "github":
        from core.database import Connection, SessionLocal

        db = SessionLocal()
        try:
            row = db.get(Connection, account_id)
            if row is not None:
                db.delete(row)
                db.commit()
        finally:
            db.close()
        # github only revokes an oauth token with the app's client secret, which this
        # public device-flow app does not have. deleting the row forgets it here.
    elif use == "mail":
        from core.database import MailAccount, SessionLocal
        from services import mail as mailsvc

        db = SessionLocal()
        try:
            row = db.get(MailAccount, account_id)
            if row is not None:
                if provider == "google":
                    revoked = await providers.google_revoke(
                        row.oauth_refresh_token or row.oauth_access_token
                    )
                # microsoft has no public revocation endpoint for a consumer refresh token.
                db.delete(row)
                db.commit()
        finally:
            db.close()
        mailsvc.clear_cache()
    elif use == "models":
        from core.database import ModelEndpoint, SessionLocal
        from services import model_auth

        db = SessionLocal()
        try:
            row = db.get(ModelEndpoint, account_id)
            if row is not None:
                if provider == "gemini":
                    try:
                        await model_auth.revoke_gemini_endpoint(row)
                        revoked = True
                    except RuntimeError:
                        revoked = False
                elif provider in {"anthropic", "openai"}:
                    # neither subscription provider exposes a public revoke endpoint for this
                    # public client, so only alles forgets the tokens.
                    revoked = False
                model_auth.clear_oauth(row)
                db.commit()
        finally:
            db.close()
    elif use == "calendar":
        cfg = caldav_sync.load_cfg()
        tokens = caldav_sync.oauth_tokens(cfg)
        revoked = await providers.google_revoke(
            str(tokens.get("refresh_token") or tokens.get("access_token") or "")
        )
        caldav_sync.save_cfg(
            {"url": "", "username": "", "password": "", "auth": "", "provider": ""},
            keep_password=False,
        )
    _forget(account_id)
    return {"id": account_id, "signed_out": True, "revoked": bool(revoked)}


async def refresh_due_accounts() -> int:
    """refresh accounts close to expiry. a failure marks just that account needs_sign_in."""
    refreshed = 0
    now = time.time()
    for item in list_accounts()["accounts"]:
        if item["state"] != "ok" or not item["expires_at"]:
            continue
        try:
            expires = (
                datetime.strptime(item["expires_at"], "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=UTC)
                .timestamp()
            )
        except (TypeError, ValueError):
            continue
        if expires - now > 300:
            continue
        await refresh_account(item["id"])
        refreshed += 1
    return refreshed


# ── the mail engine's synchronous microsoft refresh ─────────────────────────


def ensure_microsoft_mail_token(acct: dict) -> str:
    """a valid access token for a microsoft mail account, refreshing and saving when due."""
    token = acct.get("oauth_access_token", "")
    expires = float(acct.get("oauth_expires_at") or 0)
    if token and expires - 60 > time.time():
        return token
    refresh_token = str(acct.get("oauth_refresh_token") or "")
    if not refresh_token:
        raise ProviderError(_MESSAGES["refresh_refused"]["message"])
    try:
        body = providers.microsoft_refresh_sync(signin_clients.microsoft_client_id(), refresh_token)
    except ProviderError as exc:
        if exc.permanent and acct.get("id"):
            _record(acct["id"], state="needs_sign_in", error=_needs_sign_in_error())
        raise
    new_token = str(body.get("access_token") or "")
    new_expires = providers.expires_at(body)
    account_id = acct.get("id")
    if account_id:
        from core.database import MailAccount, SessionLocal

        db = SessionLocal()
        try:
            row = db.get(MailAccount, account_id)
            if row is not None:
                row.oauth_access_token = new_token
                if body.get("refresh_token"):
                    row.oauth_refresh_token = str(body["refresh_token"])
                row.oauth_expires_at = new_expires
                db.commit()
        finally:
            db.close()
        _record(account_id, state="ok", error=None, refreshed_at=_iso(time.time()))
    acct["oauth_access_token"] = new_token
    if body.get("refresh_token"):
        acct["oauth_refresh_token"] = str(body["refresh_token"])
    acct["oauth_expires_at"] = new_expires
    return new_token
