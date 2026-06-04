import os
from fastapi import APIRouter, HTTPException, Response, Cookie
from pydantic import BaseModel
from core.settings import load_settings, save_settings
from core.auth import (hash_password, verify_password,
                       create_session_token, store_token,
                       verify_session, revoke_token)

router = APIRouter(prefix="/api/auth")


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
    response.set_cookie("aide_session", token, httponly=True,
                        max_age=30 * 86400, samesite="lax")
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, aide_session: str | None = Cookie(None)):
    if aide_session:
        revoke_token(aide_session)
    response.delete_cookie("aide_session")
    return {"ok": True}


@router.get("/me")
def me(aide_session: str | None = Cookie(None)):
    from core.settings import auth_enabled
    if not auth_enabled():
        return {"enabled": False, "authenticated": True}
    if not aide_session or not verify_session(aide_session):
        return {"enabled": True, "authenticated": False}
    return {"enabled": True, "authenticated": True}
