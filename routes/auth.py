import os
from typing import Literal

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, Field

from core.auth import (
    MIN_OWNER_PASSWORD_LENGTH,
    RECENT_AUTH_SECONDS,
    clear_login_fails,
    create_session_token,
    hash_password,
    login_blocked,
    make_context_handoff,
    make_handoff,
    mark_session_recent,
    record_login_fail,
    redeem_context_handoff,
    redeem_handoff,
    revoke_token,
    store_token,
    verify_password,
    verify_session,
)
from core.settings import auth_enabled, base_domain, load_settings, save_settings

router = APIRouter(prefix="/api/auth")


def _cookie_domain_kw() -> dict:
    # real dotted domain → set Domain so subdomains share the cookie automatically.
    # localhost (and bare hosts) → host-only per subdomain (Domain=localhost is NOT
    # sent back to *.localhost), and the /handoff relay gives each subdomain its cookie.
    bd = base_domain()
    if bd and "." in bd and bd != "localhost":
        return {"domain": bd, "secure": True}
    return {}


def _set_session_cookie(response: Response, token: str):
    response.set_cookie(
        "aide_session",
        token,
        httponly=True,
        max_age=30 * 86400,
        samesite="lax",
        **_cookie_domain_kw(),
    )


class LoginBody(BaseModel):
    password: str


class ContextDocumentScope(BaseModel):
    kind: Literal["vault_document"] = "vault_document"
    path: str = Field(min_length=1, max_length=2048)
    expected_hash: str = Field(min_length=1, max_length=256)


class ContextHandoffBody(BaseModel):
    ask: str = Field(min_length=1, max_length=20_000)
    web: bool = False
    document_scope: ContextDocumentScope | None = None


def _context_session(aide_session: str | None) -> str:
    if auth_enabled():
        if not aide_session or not verify_session(aide_session):
            raise HTTPException(401, "not authenticated")
        return aide_session
    return aide_session if aide_session and verify_session(aide_session) else ""


@router.post("/login")
def login(body: LoginBody, response: Response, request: Request):
    ip = request.client.host if request.client else "?"
    if login_blocked(ip):
        raise HTTPException(429, "too many attempts — wait a few minutes and try again")

    s = load_settings()
    hashed = s.get("auth_password_hash", "")
    if not hashed:
        env_pw = os.getenv("AUTH_PASSWORD", "")
        if not env_pw:
            raise HTTPException(400, "AUTH_PASSWORD env var not set")
        hashed = hash_password(env_pw)
        save_settings({"auth_password_hash": hashed})

    if not verify_password(body.password, hashed):
        record_login_fail(ip)
        raise HTTPException(401, "invalid password")

    clear_login_fails(ip)  # good login wipes the slate for this IP
    token = create_session_token()
    store_token(token)
    _set_session_cookie(response, token)
    return {"ok": True}


@router.post("/reauth")
def reauth(
    body: LoginBody,
    request: Request,
    aide_session: str | None = Cookie(None),
):
    if not aide_session or not verify_session(aide_session):
        raise HTTPException(401, "not authenticated")
    ip = request.client.host if request.client else "?"
    if login_blocked(ip):
        raise HTTPException(429, "too many attempts — wait a few minutes and try again")
    settings = load_settings()
    hashed = settings.get("auth_password_hash", "")
    if not hashed:
        env_password = os.getenv("AUTH_PASSWORD", "")
        hashed = hash_password(env_password) if env_password else ""
    if not hashed or not verify_password(body.password, hashed):
        record_login_fail(ip)
        raise HTTPException(401, "invalid password")
    clear_login_fails(ip)
    mark_session_recent(aide_session)
    return {"ok": True, "expires_in": RECENT_AUTH_SECONDS}


@router.post("/logout")
def logout(response: Response, aide_session: str | None = Cookie(None)):
    if aide_session:
        revoke_token(aide_session)
    response.delete_cookie("aide_session", domain=_cookie_domain_kw().get("domain"))
    return {"ok": True}


@router.get("/me")
def me(aide_session: str | None = Cookie(None)):
    from core.settings import auth_enabled

    bd = base_domain()
    username = load_settings().get("username", "")
    if not auth_enabled():
        return {"enabled": False, "authenticated": True, "base_domain": bd, "username": username}
    authed = bool(aide_session and verify_session(aide_session))
    return {"enabled": True, "authenticated": authed, "base_domain": bd, "username": username}


class ChangePwBody(BaseModel):
    old_password: str = ""
    new_password: str


@router.post("/change-password")
def change_password(body: ChangePwBody, request: Request):
    if len(body.new_password) < MIN_OWNER_PASSWORD_LENGTH:
        raise HTTPException(
            400,
            f"new password must be at least {MIN_OWNER_PASSWORD_LENGTH} characters",
        )
    s = load_settings()
    hashed = s.get("auth_password_hash", "")
    env_pw = ""
    if not hashed:
        env_pw = os.getenv("AUTH_PASSWORD", "")
    # if a password already exists, the current one must match. throttle this
    # the same way as /login — otherwise it's an unmetered brute-force oracle
    # for the master password (this endpoint sits under the auth-exempt prefix).
    if hashed or env_pw:
        ip = request.client.host if request.client else "?"
        if login_blocked(ip):
            raise HTTPException(429, "too many attempts — wait a few minutes and try again")
        if not hashed:
            hashed = hash_password(env_pw)
        if not verify_password(body.old_password, hashed):
            record_login_fail(ip)
            raise HTTPException(401, "current password is wrong")
        clear_login_fails(ip)
    save_settings({"auth_password_hash": hash_password(body.new_password)})
    return {"ok": True}


class AuthConfigBody(BaseModel):
    enabled: bool
    password: str = ""


@router.post("/config")
def set_auth_config(body: AuthConfigBody, request: Request, response: Response):
    """turn the password lock on/off from the UI (no file editing). enabling needs a
    password to exist (or one supplied here); disabling needs the current password so a
    random visitor can't just switch it off."""
    s = load_settings()
    hashed = s.get("auth_password_hash", "")
    env_password = ""
    if not hashed:
        env_password = os.getenv("AUTH_PASSWORD", "")
    ip = request.client.host if request.client else "?"
    if (hashed or env_password) and login_blocked(ip):
        raise HTTPException(429, "too many attempts — wait a few minutes and try again")
    if not hashed and env_password:
        hashed = hash_password(env_password)
    if body.enabled:
        if hashed:
            if not verify_password(body.password, hashed):
                record_login_fail(ip)
                raise HTTPException(401, "current password required to enable the lock")
            clear_login_fails(ip)
        elif body.password:
            if len(body.password) < MIN_OWNER_PASSWORD_LENGTH:
                raise HTTPException(
                    400,
                    f"password must be at least {MIN_OWNER_PASSWORD_LENGTH} characters",
                )
            hashed = hash_password(body.password)
        if not hashed:
            raise HTTPException(400, "set a password first, then enable the lock")
        save_settings({"auth_password_hash": hashed, "auth_enabled": True})
        if body.password:
            token = create_session_token()
            store_token(token)
            _set_session_cookie(response, token)
        return {"ok": True, "enabled": True}
    # disabling
    if hashed:
        if not verify_password(body.password, hashed):
            record_login_fail(ip)
            raise HTTPException(401, "current password required to disable the lock")
        clear_login_fails(ip)
    save_settings({"auth_enabled": False})
    return {"ok": True, "enabled": False}


# cross-subdomain SSO: an authed subdomain mints a one-time code; the target
# subdomain redeems it to get its own cookie (so you only log in once).
@router.get("/handoff")
def handoff(aide_session: str | None = Cookie(None)):
    if not aide_session or not verify_session(aide_session):
        raise HTTPException(401, "not authenticated")
    return {"code": make_handoff(aide_session)}


@router.get("/redeem")
def redeem(code: str, response: Response):
    token = redeem_handoff(code)
    if not token:
        raise HTTPException(401, "bad or expired code")
    _set_session_cookie(response, token)
    return {"ok": True}


@router.post("/context-handoff")
def create_context_handoff(
    body: ContextHandoffBody,
    aide_session: str | None = Cookie(None),
):
    token = _context_session(aide_session)
    return {"code": make_context_handoff(token, body.model_dump())}


@router.post("/context-handoff/{code}")
def consume_context_handoff(code: str, aide_session: str | None = Cookie(None)):
    token = _context_session(aide_session)
    payload = redeem_context_handoff(code, token)
    if payload is None:
        raise HTTPException(404, "bad or expired context handoff")
    return payload
