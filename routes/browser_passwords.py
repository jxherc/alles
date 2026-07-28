"""Owner and extension endpoints for paired exact-site Passwords access."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import BrowserConnection, Vault, get_db
from core.rate_limit import enforce_rate_limit
from routes.vault import _ctx, _require_current_vault_password
from services import browser_passwords

extension_router = APIRouter(prefix="/api/auth/browser")
owner_router = APIRouter(prefix="/api/vault/browsers")

_EXTENSION_FILES = ("manifest.json", "popup.html", "popup.css", "popup.js", "background.js")
_EXTENSION_ROOT = Path(__file__).resolve().parent.parent / "extension"


def _error(exc: browser_passwords.BrowserPasswordError) -> ApiError:
    return ApiError(exc.status, exc.code, exc.message)


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


class PairStartBody(BaseModel):
    name: str = Field(default="Browser", max_length=80)


class PairPollBody(BaseModel):
    pairing_id: str = Field(min_length=32, max_length=32)
    pairing_secret: str = Field(min_length=32, max_length=128)


class DeviceBody(BaseModel):
    connection_id: str = Field(min_length=32, max_length=32)
    device_secret: str = Field(min_length=32, max_length=128)


class UnlockPollBody(DeviceBody):
    request_id: str = Field(min_length=32, max_length=32)


class PageBody(DeviceBody):
    session_token: str = Field(min_length=32, max_length=128)
    page_url: str = Field(min_length=1, max_length=4096)
    top_url: str = Field(min_length=1, max_length=4096)
    frame_url: str = Field(min_length=1, max_length=4096)


class ReleaseBody(PageBody):
    entry_id: str = Field(min_length=1, max_length=128)


@extension_router.post("/pair/start")
def pair_start(
    body: PairStartBody,
    request: Request,
    response: Response,
    origin: str | None = Header(None),
):
    enforce_rate_limit(request, "browser-pair-start", limit=10, window_seconds=300)
    _private(response)
    try:
        return browser_passwords.begin_pair(body.name, origin or "")
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@extension_router.post("/pair/poll")
def pair_poll(
    body: PairPollBody,
    request: Request,
    response: Response,
    origin: str | None = Header(None),
):
    enforce_rate_limit(request, "browser-pair-poll", limit=120, window_seconds=300)
    _private(response)
    try:
        return browser_passwords.poll_pair(body.pairing_id, body.pairing_secret, origin or "")
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@extension_router.post("/pair/ack")
def pair_ack(
    body: PairPollBody,
    request: Request,
    response: Response,
    origin: str | None = Header(None),
):
    enforce_rate_limit(request, "browser-pair-ack", limit=20, window_seconds=300)
    _private(response)
    try:
        browser_passwords.ack_pair(body.pairing_id, body.pairing_secret, origin or "")
        return {"ok": True}
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@extension_router.post("/unlock/start")
def unlock_start(
    body: DeviceBody,
    request: Request,
    response: Response,
    origin: str | None = Header(None),
    db: DbSession = Depends(get_db),
):
    enforce_rate_limit(request, "browser-unlock-start", limit=20, window_seconds=300)
    _private(response)
    try:
        return browser_passwords.begin_unlock(
            db, body.connection_id, body.device_secret, origin or ""
        )
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@extension_router.post("/unlock/poll")
def unlock_poll(
    body: UnlockPollBody,
    request: Request,
    response: Response,
    origin: str | None = Header(None),
    db: DbSession = Depends(get_db),
):
    enforce_rate_limit(request, "browser-unlock-poll", limit=120, window_seconds=300)
    _private(response)
    try:
        return browser_passwords.poll_unlock(
            db, body.request_id, body.connection_id, body.device_secret, origin or ""
        )
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@extension_router.post("/lock")
def device_lock(
    body: DeviceBody,
    request: Request,
    response: Response,
    origin: str | None = Header(None),
    db: DbSession = Depends(get_db),
):
    enforce_rate_limit(request, "browser-lock", limit=60, window_seconds=300)
    _private(response)
    try:
        browser_passwords.device_lock(db, body.connection_id, body.device_secret, origin or "")
        return {"ok": True}
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@extension_router.post("/disconnect")
def device_disconnect(
    body: DeviceBody,
    request: Request,
    response: Response,
    origin: str | None = Header(None),
    db: DbSession = Depends(get_db),
):
    enforce_rate_limit(request, "browser-disconnect", limit=20, window_seconds=300)
    _private(response)
    try:
        browser_passwords.device_disconnect(
            db, body.connection_id, body.device_secret, origin or ""
        )
        return {"ok": True}
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@extension_router.post("/match")
def match(
    body: PageBody,
    request: Request,
    response: Response,
    origin: str | None = Header(None),
    db: DbSession = Depends(get_db),
):
    enforce_rate_limit(request, "browser-match", limit=120, window_seconds=60)
    _private(response)
    try:
        return {
            "matches": browser_passwords.matches(
                db,
                body.connection_id,
                body.device_secret,
                body.session_token,
                origin or "",
                page_url=body.page_url,
                top_url=body.top_url,
                frame_url=body.frame_url,
            )
        }
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@extension_router.post("/release")
def release(
    body: ReleaseBody,
    request: Request,
    response: Response,
    origin: str | None = Header(None),
    db: DbSession = Depends(get_db),
):
    enforce_rate_limit(request, "browser-release", limit=30, window_seconds=60)
    _private(response)
    try:
        return browser_passwords.release(
            db,
            body.connection_id,
            body.device_secret,
            body.session_token,
            origin or "",
            body.entry_id,
            page_url=body.page_url,
            top_url=body.top_url,
            frame_url=body.frame_url,
        )
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


def _owner(db: DbSession, ctx: tuple[str, str]) -> tuple[str, str]:
    password, vault_id = ctx
    _require_current_vault_password(db, password, vault_id)
    return password, vault_id


@owner_router.get("")
def owner_status(
    response: Response,
    db: DbSession = Depends(get_db),
    ctx: tuple[str, str] = Depends(_ctx),
):
    _private(response)
    _password, vault_id = _owner(db, ctx)
    connections = browser_passwords.list_connections(db, vault_id)
    by_id = {item["id"]: item["name"] for item in connections}
    unlocks = browser_passwords.pending_unlocks(set(by_id))
    for item in unlocks:
        item["name"] = by_id.get(item["connection_id"], "Browser")
    return {
        "connections": connections,
        "pairings": browser_passwords.pending_pairings(),
        "unlock_requests": unlocks,
    }


@owner_router.get("/extension", dependencies=[Depends(require_recent_owner)])
def download_extension(
    response: Response,
    db: DbSession = Depends(get_db),
    ctx: tuple[str, str] = Depends(_ctx),
):
    """Return only the reviewed extension files, never runtime state or secrets."""
    _private(response)
    _owner(db, ctx)
    bundle = io.BytesIO()
    try:
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in _EXTENSION_FILES:
                path = _EXTENSION_ROOT / name
                if path.is_symlink() or not path.is_file():
                    raise OSError(f"extension file is unavailable: {name}")
                archive.writestr(name, path.read_bytes())
    except OSError as exc:
        raise ApiError(
            503,
            "extension_bundle_unavailable",
            "the browser extension bundle is unavailable",
        ) from exc
    return Response(
        content=bundle.getvalue(),
        media_type="application/zip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="alles-passwords-extension.zip"',
        },
    )


@owner_router.post("/pairings/{pairing_id}/approve", dependencies=[Depends(require_recent_owner)])
def approve_pairing(
    pairing_id: str,
    response: Response,
    db: DbSession = Depends(get_db),
    ctx: tuple[str, str] = Depends(_ctx),
):
    _private(response)
    _password, vault_id = _owner(db, ctx)
    try:
        connection = browser_passwords.approve_pair(db, pairing_id, vault_id)
        return {"ok": True, "connection_id": connection.id, "name": connection.name}
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@owner_router.delete("/pairings/{pairing_id}", dependencies=[Depends(require_recent_owner)])
def cancel_pairing(
    pairing_id: str,
    response: Response,
    db: DbSession = Depends(get_db),
    ctx: tuple[str, str] = Depends(_ctx),
):
    _private(response)
    _owner(db, ctx)
    try:
        browser_passwords.cancel_pair(pairing_id)
        return {"ok": True}
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@owner_router.post(
    "/unlock-requests/{request_id}/approve", dependencies=[Depends(require_recent_owner)]
)
def approve_unlock(
    request_id: str,
    response: Response,
    db: DbSession = Depends(get_db),
    ctx: tuple[str, str] = Depends(_ctx),
):
    _private(response)
    password, vault_id = _owner(db, ctx)
    ids = {item["id"] for item in browser_passwords.list_connections(db, vault_id)}
    pending = next(
        (item for item in browser_passwords.pending_unlocks(ids) if item["id"] == request_id),
        None,
    )
    if pending is None:
        raise ApiError(404, "unlock_request_not_found", "browser unlock request was not found")
    vault = db.get(Vault, vault_id)
    if vault is None or not vault.verifier:
        raise ApiError(403, "vault_locked", "vault access is locked")
    try:
        browser_passwords.approve_unlock(
            request_id,
            pending["connection_id"],
            vault_id,
            password,
            vault.verifier,
        )
        return {"ok": True}
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


@owner_router.delete("/unlock-requests/{request_id}", dependencies=[Depends(require_recent_owner)])
def cancel_unlock(
    request_id: str,
    response: Response,
    db: DbSession = Depends(get_db),
    ctx: tuple[str, str] = Depends(_ctx),
):
    _private(response)
    _password, vault_id = _owner(db, ctx)
    ids = {item["id"] for item in browser_passwords.list_connections(db, vault_id)}
    pending = next(
        (item for item in browser_passwords.pending_unlocks(ids) if item["id"] == request_id),
        None,
    )
    if pending is None:
        raise ApiError(404, "unlock_request_not_found", "browser unlock request was not found")
    try:
        browser_passwords.cancel_unlock(request_id, pending["connection_id"])
        return {"ok": True}
    except browser_passwords.BrowserPasswordError as exc:
        raise _error(exc) from exc


def _owned_connection(db: DbSession, vault_id: str, connection_id: str) -> BrowserConnection:
    connection = db.get(BrowserConnection, connection_id)
    if connection is None or connection.vault_id != vault_id or connection.revoked_at is not None:
        raise ApiError(404, "browser_not_found", "browser connection was not found")
    return connection


@owner_router.post("/{connection_id}/lock", dependencies=[Depends(require_recent_owner)])
def owner_lock(
    connection_id: str,
    response: Response,
    db: DbSession = Depends(get_db),
    ctx: tuple[str, str] = Depends(_ctx),
):
    _private(response)
    _password, vault_id = _owner(db, ctx)
    connection = _owned_connection(db, vault_id, connection_id)
    browser_passwords.lock_connection(connection.id)
    return {"ok": True}


@owner_router.delete("/{connection_id}", dependencies=[Depends(require_recent_owner)])
def owner_revoke(
    connection_id: str,
    response: Response,
    db: DbSession = Depends(get_db),
    ctx: tuple[str, str] = Depends(_ctx),
):
    _private(response)
    _password, vault_id = _owner(db, ctx)
    connection = _owned_connection(db, vault_id, connection_id)
    browser_passwords.revoke_connection(db, connection)
    return {"ok": True}
