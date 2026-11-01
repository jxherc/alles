import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import Connection, get_db
from services import signin, signin_providers
from services.redaction import redact_mapping

router = APIRouter(prefix="/api")


def _mask(t: str) -> str:
    if not t:
        return ""
    return (t[:4] + "…" + t[-4:]) if len(t) > 8 else "set"


@router.get("/connections")
def list_conns(db: DbSession = Depends(get_db)):
    rows = db.query(Connection).order_by(Connection.service).all()
    return [
        {
            "id": c.id,
            "service": c.service,
            "token_masked": _mask(c.token),
            "connected": bool(c.token),
            "meta": redact_mapping(json.loads(c.meta or "{}")),
        }
        for c in rows
    ]


class ConnBody(BaseModel):
    service: str
    token: str = ""
    meta: dict = {}


@router.post("/connections", dependencies=[Depends(require_recent_owner)])
def add_conn(body: ConnBody, db: DbSession = Depends(get_db)):
    svc = body.service.strip().lower()
    if not svc:
        raise HTTPException(400, "service required")
    c = db.query(Connection).filter(Connection.service == svc).first()
    if not c:
        c = Connection(service=svc)
        db.add(c)
    c.token = body.token.strip()
    c.meta = json.dumps(body.meta or {})
    db.commit()
    db.refresh(c)
    return {"id": c.id, "service": c.service, "connected": bool(c.token)}


@router.delete("/connections/{conn_id}", dependencies=[Depends(require_recent_owner)])
def del_conn(conn_id: str, db: DbSession = Depends(get_db)):
    c = db.get(Connection, conn_id)
    if c:
        db.delete(c)
        db.commit()
    return {"ok": True}


@router.post("/connections/rotate-key", dependencies=[Depends(require_recent_owner)])
def rotate_connection_key():
    from services.secret_rotation import rotate_all_credentials

    try:
        return rotate_all_credentials()
    except Exception as exc:
        raise HTTPException(
            500, "credential key rotation failed; the previous key was retained"
        ) from exc


@router.get("/connections/{service}/test")
async def test_conn(service: str):
    service = service.lower()
    if service == "github":
        from services.agent_tools import _github_api

        r = await _github_api("GET", "/user")
        if r.get("error"):
            return {"ok": False, "error": r.get("output", "failed")}
        try:
            login = json.loads(r["output"]).get("login", "?")
        except Exception:
            login = "?"
        return {"ok": True, "user": login}
    return {"ok": False, "error": f"no test available for {service}"}


# ── sign in with a provider ────────────────────────────────────────────────


def _origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/signin/providers")
def providers(request: Request):
    origin = signin.effective_origin(_origin(request))
    return {"providers": signin_providers.providers(origin)}


class StartBody(BaseModel):
    provider: str
    use: str
    login_hint: str = ""


@router.post("/signin/start", dependencies=[Depends(require_recent_owner)])
async def start(body: StartBody, request: Request):
    try:
        return await signin.start(
            body.provider.strip().lower(),
            body.use.strip().lower(),
            login_hint=body.login_hint.strip(),
            origin=_origin(request),
        )
    except signin.InvalidRequest as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    except signin_providers.NotReady as exc:
        raise ApiError(409, "not_ready", exc.message) from exc
    except signin_providers.ProviderError as exc:
        raise ApiError(502, "provider_error", str(exc)[:200]) from exc


@router.get("/signin/attempts/{attempt}")
def attempt(attempt: str):
    found = signin.get_attempt(attempt)
    if found is None:
        raise ApiError(404, "signin_attempt_not_found", "this sign in attempt is gone; start again")
    return found


@router.post("/signin/attempts/{attempt}/cancel")
def cancel(attempt: str):
    found = signin.cancel(attempt)
    if found is None:
        raise ApiError(404, "signin_attempt_not_found", "this sign in attempt is gone; start again")
    return found


class CodeBody(BaseModel):
    code: str


@router.post("/signin/attempts/{attempt}/code")
async def code(attempt: str, body: CodeBody):
    try:
        return await signin.finish_code(attempt, body.code)
    except signin.AttemptGone as exc:
        raise ApiError(404, "signin_attempt_not_found", exc.message) from exc


@router.get("/signin/callback/{provider}")
async def callback(provider: str, code: str = "", state: str = "", error: str = ""):
    finished = await signin.finish_redirect(provider, code=code, state=state, error=error)
    if finished is None:
        return RedirectResponse("/?signin=unknown", status_code=303)
    origin = str(finished.get("origin") or "").rstrip("/")
    target = (
        f"{origin}/?signin={quote(str(finished['attempt']))}"
        if origin
        else f"/?signin={quote(str(finished['attempt']))}"
    )
    return RedirectResponse(target, status_code=303)


@router.get("/signin/accounts")
def accounts():
    return signin.list_accounts()


@router.post("/signin/accounts/{account_id}/check")
async def check(account_id: str):
    found = await signin.refresh_account(account_id)
    if found is None:
        raise ApiError(404, "signin_account_not_found", "account not found")
    return found


@router.delete("/signin/accounts/{account_id}", dependencies=[Depends(require_recent_owner)])
async def sign_out(account_id: str):
    found = await signin.sign_out(account_id)
    if found is None:
        raise ApiError(404, "signin_account_not_found", "account not found")
    return found
