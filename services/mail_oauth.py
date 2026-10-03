"""google oauth for mail. lets the user "sign in with google" instead of pasting an
app password - we keep the existing IMAP/SMTP engine and only swap the auth step to
XOAUTH2 (a bearer token in place of the password). all sync (httpx.Client) so it can
be called straight from the threadpooled mail routes + the connect path."""

import secrets as _secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import AnyHttpUrl, TypeAdapter

from core.settings import get_port, load_settings, save_settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPES = "https://mail.google.com/ openid email"

_REDIRECT_BASE = TypeAdapter(AnyHttpUrl)

GMAIL_IMAP = ("imap.gmail.com", 993)
GMAIL_SMTP = ("smtp.gmail.com", 587)


def _creds():
    s = load_settings()
    return s.get("mail_oauth_client_id", ""), s.get("mail_oauth_client_secret", "")


def configured() -> bool:
    cid, sec = _creds()
    return bool(cid and sec)


def _redirect_uri(settings) -> str:
    base = (
        settings.get("mail_oauth_redirect_base", "") or f"http://localhost:{get_port()}"
    ).rstrip("/")
    return base + "/api/mail/oauth/google/callback"


def redirect_uri() -> str:
    return _redirect_uri(load_settings())


def _configuration(settings):
    revision = settings.get("mail_oauth_revision", 0)
    if type(revision) is not int or revision < 0:
        raise ValueError("could not read the Google configuration revision")
    return {
        "configured": bool(
            settings.get("mail_oauth_client_id") and settings.get("mail_oauth_client_secret")
        ),
        "client_id": settings.get("mail_oauth_client_id", ""),
        "client_secret_configured": bool(settings.get("mail_oauth_client_secret")),
        "redirect_base": settings.get("mail_oauth_redirect_base", ""),
        "redirect_uri": _redirect_uri(settings),
        "revision": revision,
    }


def configuration():
    from services.recovery_consistency import recovery_consistency_lock

    with recovery_consistency_lock:
        return _configuration(load_settings())


class ConfigurationConflict(ValueError):
    pass


def save_configuration(*, client_id, client_secret, redirect_base, expected_revision):
    from services.recovery_consistency import recovery_consistency_lock

    with recovery_consistency_lock:
        saved = load_settings()
        current = _configuration(saved)
        # Retention must also work for partial or invalid values saved by legacy
        # clients. It changes no configuration; only the revision fences old writes.
        if (
            client_secret is None
            and client_id == saved.get("mail_oauth_client_id", "")
            and redirect_base == saved.get("mail_oauth_redirect_base", "")
        ):
            if expected_revision != current["revision"]:
                raise ConfigurationConflict(
                    "Google configuration changed; review the saved settings before retrying"
                )
            return _configuration(
                save_settings(
                    {
                        "mail_oauth_client_id": client_id,
                        "mail_oauth_client_secret": saved.get("mail_oauth_client_secret", ""),
                        "mail_oauth_redirect_base": redirect_base,
                    }
                )
            )
        client_id = client_id.strip()
        redirect_base = redirect_base.strip()
        if redirect_base:
            try:
                if (
                    "?" in redirect_base
                    or "#" in redirect_base
                    or "\\" in redirect_base
                    or any(
                        char.isspace() or ord(char) < 32 or ord(char) == 127
                        for char in redirect_base
                    )
                ):
                    raise ValueError
                parsed = _REDIRECT_BASE.validate_python(redirect_base, strict=True)
                if (
                    parsed.username is not None
                    or parsed.password is not None
                    or "@" in urlsplit(redirect_base).netloc
                ):
                    raise ValueError
            except ValueError as exc:
                raise ValueError(
                    "redirect base must be an HTTP or HTTPS URL without credentials, query or fragment"
                ) from exc
        redirect_base = redirect_base.rstrip("/")
        desired = {
            "mail_oauth_client_id": client_id,
            "mail_oauth_client_secret": saved.get("mail_oauth_client_secret", "")
            if client_secret is None
            else client_secret,
            "mail_oauth_redirect_base": redirect_base,
        }
        if expected_revision != current["revision"]:
            if client_secret is not None and all(
                saved.get(key, "") == value for key, value in desired.items()
            ):
                return current
            raise ConfigurationConflict(
                "Google configuration changed; review the saved settings before retrying"
            )
        if bool(client_id) != bool(desired["mail_oauth_client_secret"]):
            raise ValueError(
                "enter a Google client secret" if client_id else "enter a Google client id"
            )
        # Even an unchanged claim advances the version, fencing older pending writes.
        return _configuration(save_settings(desired))


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
    q = urlencode(
        {
            "client_id": cid,
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",  # force a refresh_token back every time
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{q}"


def exchange_code(code: str) -> dict:
    cid, sec = _creds()
    with httpx.Client(timeout=30) as c:
        r = c.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": cid,
                "client_secret": sec,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        r.raise_for_status()
        return r.json()


def refresh_access(refresh_token: str) -> dict:
    cid, sec = _creds()
    with httpx.Client(timeout=30) as c:
        r = c.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": cid,
                "client_secret": sec,
                "grant_type": "refresh_token",
            },
        )
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
