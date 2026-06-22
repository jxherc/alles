"""google oauth for mail. lets the user "sign in with google" instead of pasting an
app password - we keep the existing IMAP/SMTP engine and only swap the auth step to
XOAUTH2 (a bearer token in place of the password). all sync (httpx.Client) so it can
be called straight from the threadpooled mail routes + the connect path."""

import secrets as _secrets
import time
from urllib.parse import urlencode

import httpx

from core.settings import load_settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPES = "https://mail.google.com/ openid email"

GMAIL_IMAP = ("imap.gmail.com", 993)
GMAIL_SMTP = ("smtp.gmail.com", 587)


def _creds():
    s = load_settings()
    return s.get("mail_oauth_client_id", ""), s.get("mail_oauth_client_secret", "")


def configured() -> bool:
    cid, sec = _creds()
    return bool(cid and sec)


def redirect_uri() -> str:
    base = (load_settings().get("mail_oauth_redirect_base", "") or "http://localhost:8000").rstrip("/")
    return base + "/api/mail/oauth/google/callback"


# short-lived CSRF states (the flow takes seconds; in-memory is fine)
_pending = {}


def make_state() -> str:
    st = _secrets.token_urlsafe(24)
    now = time.time()
    _pending[st] = now
    for k, v in list(_pending.items()):
        if now - v > 600:
            _pending.pop(k, None)
    return st


def check_state(st) -> bool:
    return bool(st) and _pending.pop(st, None) is not None


def auth_url(state: str) -> str:
    cid, _ = _creds()
    q = urlencode({
        "client_id": cid,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",            # force a refresh_token back every time
        "include_granted_scopes": "true",
        "state": state,
    })
    return f"{AUTH_URL}?{q}"


def exchange_code(code: str) -> dict:
    cid, sec = _creds()
    with httpx.Client(timeout=30) as c:
        r = c.post(TOKEN_URL, data={
            "code": code, "client_id": cid, "client_secret": sec,
            "redirect_uri": redirect_uri(), "grant_type": "authorization_code",
        })
        r.raise_for_status()
        return r.json()


def refresh_access(refresh_token: str) -> dict:
    cid, sec = _creds()
    with httpx.Client(timeout=30) as c:
        r = c.post(TOKEN_URL, data={
            "refresh_token": refresh_token, "client_id": cid, "client_secret": sec,
            "grant_type": "refresh_token",
        })
        r.raise_for_status()
        return r.json()


def fetch_email(access_token: str) -> str:
    with httpx.Client(timeout=30) as c:
        r = c.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        r.raise_for_status()
        return (r.json().get("email") or "").lower()


def xoauth2(email: str, access_token: str) -> str:
    """the SASL XOAUTH2 initial response (raw - imaplib/smtplib base64 it)."""
    return f"user={email}\x01auth=Bearer {access_token}\x01\x01"


def ensure_access_token(acct: dict) -> str:
    """return a valid access token for an oauth acct dict, refreshing + persisting it
    when it's expired (or about to be). raises on refresh failure."""
    tok = acct.get("oauth_access_token", "")
    exp = float(acct.get("oauth_expires_at") or 0)
    if tok and exp - 60 > time.time():
        return tok
    data = refresh_access(acct.get("oauth_refresh_token", ""))
    new_tok = data.get("access_token", "")
    new_exp = time.time() + int(data.get("expires_in", 3600))
    aid = acct.get("id")
    if aid:  # persist so we don't refresh on every connect
        from core.database import MailAccount, SessionLocal

        db = SessionLocal()
        try:
            a = db.get(MailAccount, aid)
            if a:
                a.oauth_access_token = new_tok
                a.oauth_expires_at = new_exp
                db.commit()
        finally:
            db.close()
    acct["oauth_access_token"] = new_tok
    acct["oauth_expires_at"] = new_exp
    return new_tok
