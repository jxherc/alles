"""Paired, exact-origin browser access to selected Passwords credentials."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from core.database import BrowserConnection, Vault, VaultEntry
from core.settings import load_settings
from services.crypto import decrypt

_EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")
_PAIR_TTL = 5 * 60
_UNLOCK_REQUEST_TTL = 3 * 60
_SESSION_TTL = 5 * 60
_MAX_PENDING = 128
_LOCK = threading.RLock()


class BrowserPasswordError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass
class _Pairing:
    id: str
    name: str
    extension_origin: str
    secret_hash: str
    code: str
    expires: float
    connection_id: str = ""
    device_secret: str = ""


@dataclass
class _UnlockRequest:
    id: str
    connection_id: str
    code: str
    expires: float
    session_token: str = ""


@dataclass
class _Session:
    connection_id: str
    vault_id: str
    password: str
    verifier_hash: str
    expires: float


_pairings: dict[str, _Pairing] = {}
_unlock_requests: dict[str, _UnlockRequest] = {}
_sessions: dict[str, _Session] = {}


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def extension_origin(value: str | None) -> str:
    origin = str(value or "").strip().lower().rstrip("/")
    if not _EXTENSION_ORIGIN.fullmatch(origin):
        raise BrowserPasswordError(
            403, "invalid_extension_origin", "a Chromium extension origin is required"
        )
    return origin


def _prune(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    for pairing_id, pairing in list(_pairings.items()):
        if pairing.expires <= now:
            _pairings.pop(pairing_id, None)
    for request_id, request in list(_unlock_requests.items()):
        if request.expires <= now:
            if request.session_token:
                _sessions.pop(request.session_token, None)
            _unlock_requests.pop(request_id, None)
    for token, session in list(_sessions.items()):
        if session.expires <= now:
            _sessions.pop(token, None)


def _bound(mapping: dict) -> None:
    if len(mapping) >= _MAX_PENDING:
        raise BrowserPasswordError(429, "too_many_pending", "too many pending browser requests")


def begin_pair(name: str, origin: str) -> dict:
    origin = extension_origin(origin)
    name = re.sub(r"\s+", " ", str(name or "").strip())[:80] or "Browser"
    with _LOCK:
        _prune()
        _bound(_pairings)
        pairing_id = secrets.token_hex(16)
        secret = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(1_000_000):06d}"
        _pairings[pairing_id] = _Pairing(
            id=pairing_id,
            name=name,
            extension_origin=origin,
            secret_hash=_hash(secret),
            code=code,
            expires=time.monotonic() + _PAIR_TTL,
        )
    return {
        "pairing_id": pairing_id,
        "pairing_secret": secret,
        "code": code,
        "expires_in": _PAIR_TTL,
    }


def poll_pair(pairing_id: str, pairing_secret: str, origin: str) -> dict:
    origin = extension_origin(origin)
    with _LOCK:
        _prune()
        pairing = _pairings.get(pairing_id)
        if (
            pairing is None
            or pairing.extension_origin != origin
            or not hmac.compare_digest(pairing.secret_hash, _hash(pairing_secret))
        ):
            raise BrowserPasswordError(404, "pairing_not_found", "pairing request was not found")
        if not pairing.connection_id:
            return {"status": "pending", "code": pairing.code}
        result = {
            "status": "approved",
            "connection_id": pairing.connection_id,
            "device_secret": pairing.device_secret,
        }
        return result


def ack_pair(pairing_id: str, pairing_secret: str, origin: str) -> None:
    origin = extension_origin(origin)
    with _LOCK:
        _prune()
        pairing = _pairings.get(pairing_id)
        if (
            pairing is None
            or not pairing.connection_id
            or pairing.extension_origin != origin
            or not hmac.compare_digest(pairing.secret_hash, _hash(pairing_secret))
        ):
            raise BrowserPasswordError(404, "pairing_not_found", "pairing request was not found")
        _pairings.pop(pairing_id, None)


def pending_pairings() -> list[dict]:
    with _LOCK:
        _prune()
        return [
            {
                "id": item.id,
                "name": item.name,
                "code": item.code,
                "extension_origin": item.extension_origin,
                "expires_in": max(0, int(item.expires - time.monotonic())),
            }
            for item in _pairings.values()
            if not item.connection_id
        ]


def approve_pair(db, pairing_id: str, vault_id: str) -> BrowserConnection:
    with _LOCK:
        _prune()
        pairing = _pairings.get(pairing_id)
        if pairing is None or pairing.connection_id:
            raise BrowserPasswordError(404, "pairing_not_found", "pairing request was not found")
        device_secret = secrets.token_urlsafe(32)
        connection = BrowserConnection(
            id=secrets.token_hex(16),
            vault_id=vault_id,
            name=pairing.name,
            secret_hash=_hash(device_secret),
            extension_origin=pairing.extension_origin,
        )
        db.add(connection)
        db.commit()
        db.refresh(connection)
        pairing.connection_id = connection.id
        pairing.device_secret = device_secret
        pairing.expires = time.monotonic() + _PAIR_TTL
        return connection


def cancel_pair(pairing_id: str) -> None:
    with _LOCK:
        _prune()
        pairing = _pairings.get(pairing_id)
        if pairing is None or pairing.connection_id:
            raise BrowserPasswordError(404, "pairing_not_found", "pairing request was not found")
        _pairings.pop(pairing_id, None)


def _connection(db, connection_id: str, device_secret: str, origin: str) -> BrowserConnection:
    origin = extension_origin(origin)
    connection = db.get(BrowserConnection, connection_id)
    if (
        connection is None
        or connection.revoked_at is not None
        or connection.extension_origin != origin
        or not hmac.compare_digest(connection.secret_hash, _hash(device_secret))
    ):
        raise BrowserPasswordError(
            403, "browser_not_connected", "browser connection is invalid or revoked"
        )
    vault = db.get(Vault, connection.vault_id)
    if vault is None:
        raise BrowserPasswordError(
            403, "browser_not_connected", "browser connection is invalid or revoked"
        )
    if bool(load_settings().get("vault_travel_mode")) and not vault.travel_safe:
        raise BrowserPasswordError(
            403,
            "vault_unavailable_in_travel_mode",
            "this vault is unavailable in Travel Mode",
        )
    connection.last_seen_at = _now_utc()
    db.commit()
    return connection


def begin_unlock(db, connection_id: str, device_secret: str, origin: str) -> dict:
    connection = _connection(db, connection_id, device_secret, origin)
    with _LOCK:
        _prune()
        _bound(_unlock_requests)
        for pending in _unlock_requests.values():
            if pending.connection_id == connection.id and not pending.session_token:
                return {
                    "request_id": pending.id,
                    "code": pending.code,
                    "expires_in": max(0, int(pending.expires - time.monotonic())),
                }
        request_id = secrets.token_hex(16)
        code = f"{secrets.randbelow(1_000_000):06d}"
        _unlock_requests[request_id] = _UnlockRequest(
            id=request_id,
            connection_id=connection.id,
            code=code,
            expires=time.monotonic() + _UNLOCK_REQUEST_TTL,
        )
        return {"request_id": request_id, "code": code, "expires_in": _UNLOCK_REQUEST_TTL}


def pending_unlocks(connection_ids: set[str]) -> list[dict]:
    with _LOCK:
        _prune()
        return [
            {
                "id": item.id,
                "connection_id": item.connection_id,
                "code": item.code,
                "expires_in": max(0, int(item.expires - time.monotonic())),
            }
            for item in _unlock_requests.values()
            if item.connection_id in connection_ids and not item.session_token
        ]


def approve_unlock(
    request_id: str,
    connection_id: str,
    vault_id: str,
    password: str,
    vault_verifier: str,
) -> None:
    with _LOCK:
        _prune()
        request = _unlock_requests.get(request_id)
        if request is None or request.connection_id != connection_id or request.session_token:
            raise BrowserPasswordError(
                404, "unlock_request_not_found", "browser unlock request was not found"
            )
        token = secrets.token_urlsafe(32)
        _sessions[token] = _Session(
            connection_id=connection_id,
            vault_id=vault_id,
            password=password,
            verifier_hash=_hash(vault_verifier),
            expires=time.monotonic() + _SESSION_TTL,
        )
        request.session_token = token
        request.expires = _sessions[token].expires


def cancel_unlock(request_id: str, connection_id: str) -> None:
    with _LOCK:
        _prune()
        request = _unlock_requests.get(request_id)
        if request is None or request.connection_id != connection_id or request.session_token:
            raise BrowserPasswordError(
                404, "unlock_request_not_found", "browser unlock request was not found"
            )
        _unlock_requests.pop(request_id, None)


def poll_unlock(db, request_id: str, connection_id: str, device_secret: str, origin: str) -> dict:
    connection = _connection(db, connection_id, device_secret, origin)
    with _LOCK:
        _prune()
        request = _unlock_requests.get(request_id)
        if request is None or request.connection_id != connection.id:
            raise BrowserPasswordError(
                404, "unlock_request_not_found", "browser unlock request was not found"
            )
        if not request.session_token:
            return {"status": "pending", "code": request.code}
        session = _sessions.get(request.session_token)
        if session is None:
            _unlock_requests.pop(request_id, None)
            raise BrowserPasswordError(
                404, "unlock_request_not_found", "browser unlock request was not found"
            )
        return {
            "status": "approved",
            "session_token": request.session_token,
            "expires_in": max(0, int(session.expires - time.monotonic())),
        }


def _session(db, connection: BrowserConnection, session_token: str) -> _Session:
    with _LOCK:
        _prune()
        session = _sessions.get(session_token)
        if (
            session is None
            or session.connection_id != connection.id
            or session.vault_id != connection.vault_id
        ):
            raise BrowserPasswordError(403, "browser_locked", "browser access is locked")
        vault = db.get(Vault, session.vault_id)
        if (
            vault is None
            or not vault.verifier
            or not hmac.compare_digest(session.verifier_hash, _hash(vault.verifier))
        ):
            _sessions.pop(session_token, None)
            raise BrowserPasswordError(403, "browser_locked", "browser access is locked")
        return session


def lock_connection(connection_id: str) -> None:
    with _LOCK:
        for pairing_id, pairing in list(_pairings.items()):
            if pairing.connection_id == connection_id:
                _pairings.pop(pairing_id, None)
        for token, session in list(_sessions.items()):
            if session.connection_id == connection_id:
                _sessions.pop(token, None)
        for request_id, request in list(_unlock_requests.items()):
            if request.connection_id == connection_id:
                _unlock_requests.pop(request_id, None)


def lock_vault(vault_id: str) -> None:
    with _LOCK:
        for token, session in list(_sessions.items()):
            if session.vault_id == vault_id:
                _sessions.pop(token, None)


def device_lock(db, connection_id: str, device_secret: str, origin: str) -> None:
    connection = _connection(db, connection_id, device_secret, origin)
    lock_connection(connection.id)


def device_disconnect(db, connection_id: str, device_secret: str, origin: str) -> None:
    connection = _connection(db, connection_id, device_secret, origin)
    revoke_connection(db, connection)


def list_connections(db, vault_id: str) -> list[dict]:
    with _LOCK:
        _prune()
        unlocked_ids = {session.connection_id for session in _sessions.values()}
    rows = (
        db.query(BrowserConnection)
        .filter(BrowserConnection.vault_id == vault_id, BrowserConnection.revoked_at.is_(None))
        .order_by(BrowserConnection.created_at.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else "",
            "locked": row.id not in unlocked_ids,
        }
        for row in rows
    ]


def revoke_connection(db, connection: BrowserConnection) -> None:
    connection.revoked_at = _now_utc()
    db.commit()
    lock_connection(connection.id)


def _normalized_origin(raw: str) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(str(raw or ""))
        port = parsed.port
    except ValueError as exc:
        raise BrowserPasswordError(400, "invalid_page_origin", "page URL is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise BrowserPasswordError(400, "invalid_page_origin", "page URL must be HTTP or HTTPS")
    try:
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise BrowserPasswordError(400, "invalid_page_origin", "page hostname is invalid") from exc
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not loopback:
        raise BrowserPasswordError(
            403, "insecure_page", "password release requires HTTPS except on localhost"
        )
    return parsed.scheme, host, port or (443 if parsed.scheme == "https" else 80)


def exact_page_origin(page_url: str, top_url: str, frame_url: str) -> tuple[str, str, int]:
    page = _normalized_origin(page_url)
    if page != _normalized_origin(top_url) or page != _normalized_origin(frame_url):
        raise BrowserPasswordError(
            403, "third_party_frame_refused", "passwords are available only to the top frame"
        )
    return page


def _entry_fields(entry: VaultEntry, password: str) -> dict:
    try:
        plaintext = decrypt(password, entry.value_encrypted)
    except Exception as exc:
        raise BrowserPasswordError(
            500, "credential_decryption_failed", "a matching credential could not be decrypted"
        ) from exc
    try:
        value = json.loads(plaintext)
    except json.JSONDecodeError:
        return {"password": plaintext}
    return value if isinstance(value, dict) else {"password": str(value)}


def matches(
    db,
    connection_id: str,
    device_secret: str,
    session_token: str,
    origin: str,
    *,
    page_url: str,
    top_url: str,
    frame_url: str,
) -> list[dict]:
    connection = _connection(db, connection_id, device_secret, origin)
    session = _session(db, connection, session_token)
    page_origin = exact_page_origin(page_url, top_url, frame_url)
    rows = (
        db.query(VaultEntry)
        .filter(VaultEntry.vault_id == session.vault_id, VaultEntry.type.in_(("login", "password")))
        .order_by(VaultEntry.name, VaultEntry.id)
        .yield_per(250)
    )
    result = []
    for entry in rows:
        fields = _entry_fields(entry, session.password)
        raw_url = fields.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            continue
        try:
            stored = _normalized_origin(raw_url)
        except BrowserPasswordError:
            continue
        if (
            stored == page_origin
            and isinstance(fields.get("password"), str)
            and fields.get("password")
        ):
            result.append(
                {
                    "id": entry.id,
                    "name": entry.name,
                    "username": str(fields.get("username") or entry.username or ""),
                }
            )
    return result


def release(
    db,
    connection_id: str,
    device_secret: str,
    session_token: str,
    origin: str,
    entry_id: str,
    *,
    page_url: str,
    top_url: str,
    frame_url: str,
) -> dict:
    connection = _connection(db, connection_id, device_secret, origin)
    session = _session(db, connection, session_token)
    page_origin = exact_page_origin(page_url, top_url, frame_url)
    entry = db.get(VaultEntry, entry_id)
    if (
        entry is None
        or entry.vault_id != session.vault_id
        or entry.type not in {"login", "password"}
    ):
        raise BrowserPasswordError(404, "credential_not_found", "credential was not found")
    fields = _entry_fields(entry, session.password)
    try:
        stored_origin = _normalized_origin(str(fields.get("url") or ""))
    except BrowserPasswordError as exc:
        raise BrowserPasswordError(
            404, "credential_not_found", "credential no longer matches this page"
        ) from exc
    password = fields.get("password")
    if stored_origin != page_origin or not isinstance(password, str) or not password:
        raise BrowserPasswordError(
            404, "credential_not_found", "credential no longer matches this page"
        )
    return {"username": str(fields.get("username") or entry.username or ""), "password": password}


def reset_ephemeral_state() -> None:
    """Tests only: production reset is the process restart boundary."""
    with _LOCK:
        _pairings.clear()
        _unlock_requests.clear()
        _sessions.clear()
