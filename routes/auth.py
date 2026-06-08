import os
from fastapi import APIRouter, HTTPException, Response, Cookie
from pydantic import BaseModel
from core.settings import load_settings, save_settings, base_domain
from core.auth import (hash_password, verify_password,
                       create_session_token, store_token,
                       verify_session, revoke_token,
                       make_handoff, redeem_handoff)

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
    response.set_cookie("aide_session", token, httponly=True,
                        max_age=30 * 86400, samesite="lax", **_cookie_domain_kw())


class LoginBody(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginBody, response: Response):
    s = load_settings()
    hashed = s.get("auth_password_hash", "")
    if not hashed:
        env_pw = os.getenv("AUTH_PASSWORD", "")
        if not env_pw:
            raise HTTPException(400, "AUTH_PASSWORD env var not set")
        hashed = hash_password(env_pw)
        save_settings({"auth_password_hash": hashed})

    if not verify_password(body.password, hashed):
        raise HTTPException(401, "invalid password")

    token = create_session_token()
    store_token(token)
    _set_session_cookie(response, token)
    return {"ok": True}


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
    if not auth_enabled():
        return {"enabled": False, "authenticated": True, "base_domain": bd}
    authed = bool(aide_session and verify_session(aide_session))
    return {"enabled": True, "authenticated": authed, "base_domain": bd}


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
