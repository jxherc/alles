"""vault key upgrades, passkey key wraps and the unlock throttle.

the upgrade turns a v1 vault (every blob keyed straight off the master password) into v2 (a
random vault key wrapped by the password) on the next password unlock. it re-encrypts every
entry and attachment, checks each new blob opens to the same bytes, and commits the entries and
the new verifier in one transaction before the attachment files are swapped in. anything left
in v1 by a crash is picked up on the following unlock, because v1 blobs stay readable with the
password. nothing is deleted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from core.database import Vault, VaultAttachment, VaultEntry, WebAuthnCredential
from services.crypto import (
    VaultKey,
    decrypt,
    decrypt_bytes,
    encrypt,
    encrypt_bytes,
    is_v2,
    is_v2_blob,
    is_v2_bytes,
    new_vault_key,
    open_vault_key,
    secret_unwrap,
    secret_wrap,
)

log = logging.getLogger("alles.vault")

_PRF_INFO = b"alles-vault-prf"
_DEVICE_INFO = b"alles-vault-device"


class UpgradeError(RuntimeError):
    pass


def _tmp(path: Path) -> Path:
    return path.with_name(path.name + ".v2tmp")


def upgrade_vault(
    db, vault: Vault, password: str, attach_dir: Path, server_key, key: VaultKey | None = None
) -> VaultKey:
    """open the vault with its (already checked) password and finish any v1 leftovers."""
    legacy = not is_v2(vault.verifier)
    if legacy:
        key = new_vault_key(password)
    elif key is None:
        key = open_vault_key(password, vault.verifier)
    if key is None:
        raise UpgradeError("wrong password")
    changed = legacy
    staged: list[tuple[Path, Path]] = []
    try:
        entries = db.query(VaultEntry).filter(VaultEntry.vault_id == vault.id).all()
        for entry in entries:
            blob = entry.value_encrypted
            if not blob or (not legacy and is_v2_blob(blob)):
                continue
            plain = decrypt(password, blob)
            fresh = encrypt(key, plain)
            if decrypt(key, fresh) != plain:
                raise UpgradeError("re-encrypted entry did not read back")
            entry.value_encrypted = fresh
            changed = True

        ids = [e.id for e in entries]
        rows = (
            db.query(VaultAttachment).filter(VaultAttachment.entry_id.in_(ids)).all() if ids else []
        )
        for row in rows:
            path = attach_dir / f"{row.id}.enc"
            if not path.exists():
                continue
            raw = path.read_bytes()
            if not legacy and is_v2_bytes(raw):
                try:
                    decrypt_bytes(key, raw)
                    continue
                except Exception:
                    pass  # a v1 blob whose random salt happens to start like v2
            plain = decrypt_bytes(password, raw)
            fresh = encrypt_bytes(key, plain)
            if decrypt_bytes(key, fresh) != plain:
                raise UpgradeError("re-encrypted attachment did not read back")
            _tmp(path).write_bytes(fresh)
            staged.append((_tmp(path), path))
            changed = True

        blob = vault.biometric_blob or ""
        if blob and load_wraps(blob) is None:
            vault.biometric_blob = _upgrade_legacy_passkeys(db, vault, password, key, server_key)
            changed = True

        if changed:
            vault.verifier = key.verifier
            db.commit()
    except Exception:
        db.rollback()
        for tmp, _final in staged:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, final in staged:
        os.replace(tmp, final)
    if legacy:
        log.info(
            "vault %s upgraded to a wrapped key (%d entries, %d files)",
            vault.id,
            len(entries),
            len(staged),
        )
    return key


def _upgrade_legacy_passkeys(db, vault, password, key: VaultKey, server_key) -> str:
    """the old blob held the master password under a server key. keep each enrolled passkey
    working by giving it a device wrap of the vault key instead; the password copy goes."""
    try:
        held = decrypt(server_key(), vault.biometric_blob)
    except Exception:
        held = None
    if held != password:
        log.warning(
            "vault %s: old passkey unlock data didn't match, passkeys need setting up again",
            vault.id,
        )
        return ""
    creds = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.vault_id == vault.id, WebAuthnCredential.role != "2fa")
        .all()
    )
    blob = ""
    for cred in creds:
        blob = add_wrap(blob, cred.credential_id, key, None, server_key)
    return blob


# ── passkey wraps ────────────────────────────────────────────────────────────
# Vault.biometric_blob holds {"v": 2, "wraps": {credential_id: {kind, blob}}}.
# kind "prf": the vault key wrapped under the passkey's own PRF output, which the server never
# stores. kind "device": wrapped under the server's device key, for authenticators without PRF.


def load_wraps(blob: str | None) -> dict | None:
    if not blob:
        return {"v": 2, "wraps": {}}
    try:
        data = json.loads(blob)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("v") == 2 else None


def add_wrap(blob: str, credential_id: str, key: VaultKey, prf: bytes | None, server_key) -> str:
    data = load_wraps(blob) or {"v": 2, "wraps": {}}
    if prf:
        data["wraps"][credential_id] = {"kind": "prf", "blob": secret_wrap(prf, _PRF_INFO, key.key)}
    else:
        secret = server_key().encode()
        data["wraps"][credential_id] = {
            "kind": "device",
            "blob": secret_wrap(secret, _DEVICE_INFO, key.key),
        }
    return json.dumps(data, sort_keys=True)


def drop_wrap(blob: str, credential_id: str) -> str:
    data = load_wraps(blob)
    if data is None:
        return ""
    data["wraps"].pop(credential_id, None)
    return json.dumps(data, sort_keys=True) if data["wraps"] else ""


def wrap_kind(blob: str | None, credential_id: str) -> str:
    data = load_wraps(blob) or {}
    return ((data.get("wraps") or {}).get(credential_id) or {}).get("kind", "")


def open_wrap(blob: str, credential_id: str, prf: bytes | None, server_key) -> bytes | None:
    data = load_wraps(blob)
    wrap = ((data or {}).get("wraps") or {}).get(credential_id)
    if not wrap:
        return None
    if wrap.get("kind") == "prf":
        return secret_unwrap(prf, _PRF_INFO, wrap["blob"]) if prf else None
    return secret_unwrap(server_key().encode(), _DEVICE_INFO, wrap["blob"])


# ── unlock throttle ──────────────────────────────────────────────────────────
# five free tries, then 1s, 2s, 4s ... up to 5 minutes between tries. keyed by vault and
# verifier, so a new password (or a fresh test vault) starts clean. a correct unlock clears it.
FREE_TRIES = 5
MAX_WAIT = 300
_fails: dict[str, tuple[int, float]] = {}
_lock = threading.Lock()


def _slot(vault_id: str, verifier: str | None) -> str:
    return vault_id + ":" + hashlib.sha256((verifier or "").encode()).hexdigest()[:16]


def wait_left(vault_id: str, verifier: str | None) -> int:
    with _lock:
        _count, until = _fails.get(_slot(vault_id, verifier), (0, 0.0))
    return max(0, int(until - time.monotonic() + 0.999))


def failed(vault_id: str, verifier: str | None) -> int:
    slot = _slot(vault_id, verifier)
    with _lock:
        count, _until = _fails.get(slot, (0, 0.0))
        count += 1
        wait = 0 if count < FREE_TRIES else min(MAX_WAIT, 2 ** (count - FREE_TRIES))
        _fails[slot] = (count, time.monotonic() + wait)
        if len(_fails) > 256:
            _fails.pop(next(iter(_fails)))
    return wait


def succeeded(vault_id: str, verifier: str | None) -> None:
    with _lock:
        _fails.pop(_slot(vault_id, verifier), None)


def reset_throttle() -> None:
    """tests only."""
    with _lock:
        _fails.clear()
