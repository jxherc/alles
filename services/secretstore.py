"""Machine-local authenticated encryption for unattended server credentials."""

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.settings import settings_secret_key_path

LEGACY_PREFIX = "enc1:"
PREFIX = "enc2:"
_NONCE_LEN = 12
_KEY_FILE: Path | None = None
_key: bytes | None = None
_key_path: Path | None = None
_keys: dict[str, bytes] = {}
_active_id = ""


class SecretStoreError(RuntimeError):
    pass


def _key_file() -> Path:
    return _KEY_FILE or settings_secret_key_path()


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def _decode_key(value: str) -> bytes:
    try:
        key = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise SecretStoreError("secret key file is invalid") from exc
    if len(key) != 32:
        raise SecretStoreError("secret key file is invalid")
    return key


def _write_keyring(path: Path, keys: dict[str, bytes], active: str) -> None:
    if active not in keys or not keys:
        raise SecretStoreError("secret keyring has no active key")
    document = {
        "version": 2,
        "active": active,
        "keys": {key_id: base64.b64encode(key).decode("ascii") for key_id, key in keys.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=".secret-key-", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _parse_keyring(raw: str) -> tuple[dict[str, bytes], str, bool]:
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        key = _decode_key(raw.strip())
        key_id = _key_id(key)
        return {key_id: key}, key_id, True
    if not isinstance(document, dict) or document.get("version") != 2:
        raise SecretStoreError("secret key file is invalid")
    active = document.get("active")
    encoded = document.get("keys")
    if not isinstance(active, str) or not isinstance(encoded, dict) or not encoded:
        raise SecretStoreError("secret key file is invalid")
    keys: dict[str, bytes] = {}
    for key_id, value in encoded.items():
        if not isinstance(key_id, str) or len(key_id) != 16 or not isinstance(value, str):
            raise SecretStoreError("secret key file is invalid")
        key = _decode_key(value)
        if _key_id(key) != key_id:
            raise SecretStoreError("secret key file is invalid")
        keys[key_id] = key
    if active not in keys:
        raise SecretStoreError("secret key file is invalid")
    return keys, active, False


def _load_keyring() -> tuple[dict[str, bytes], str]:
    global _key, _key_path, _keys, _active_id
    path = _key_file()
    if _key is not None and _key_path == path and _active_id in _keys:
        return dict(_keys), _active_id
    if path.exists():
        try:
            raw = path.read_text("utf-8")
        except OSError as exc:
            raise SecretStoreError("secret key file could not be read") from exc
        keys, active, legacy = _parse_keyring(raw)
        if legacy:
            _write_keyring(path, keys, active)
    else:
        key = os.urandom(32)
        active = _key_id(key)
        keys = {active: key}
        _write_keyring(path, keys, active)
    _keys = dict(keys)
    _active_id = active
    _key = keys[active]
    _key_path = path
    return dict(keys), active


def _load_key() -> bytes:
    keys, active = _load_keyring()
    return keys[active]


def is_sealed(value: str) -> bool:
    return bool(value) and value.startswith((LEGACY_PREFIX, PREFIX))


def active_key_id() -> str:
    return _load_keyring()[1]


def key_ids() -> set[str]:
    return set(_load_keyring()[0])


def cipher_key_id(value: str) -> str | None:
    if not value.startswith(PREFIX):
        return None
    parts = value.split(":", 2)
    return parts[1] if len(parts) == 3 else None


def seal(plaintext: str, purpose: str = "") -> str:
    if not plaintext or is_sealed(plaintext):
        return plaintext
    keys, active = _load_keyring()
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(keys[active]).encrypt(nonce, plaintext.encode(), purpose.encode())
    blob = base64.b64encode(nonce + ciphertext).decode("ascii")
    return f"{PREFIX}{active}:{blob}"


def _decode_blob(value: str) -> bytes:
    try:
        blob = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise SecretStoreError("encrypted secret is invalid") from exc
    if len(blob) <= _NONCE_LEN + 15:
        raise SecretStoreError("encrypted secret is invalid")
    return blob


def unseal(value: str, purpose: str = "") -> str:
    if not value:
        return ""
    if not is_sealed(value):
        return value
    keys, _active = _load_keyring()
    try:
        if value.startswith(PREFIX):
            parts = value.split(":", 2)
            if len(parts) != 3 or parts[1] not in keys:
                raise SecretStoreError("encrypted secret uses an unavailable key")
            blob = _decode_blob(parts[2])
            plaintext = AESGCM(keys[parts[1]]).decrypt(
                blob[:_NONCE_LEN], blob[_NONCE_LEN:], purpose.encode()
            )
            return plaintext.decode()

        blob = _decode_blob(value[len(LEGACY_PREFIX) :])
        for key in keys.values():
            try:
                return AESGCM(key).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], None).decode()
            except InvalidTag:
                continue
        raise SecretStoreError("encrypted secret could not be decrypted")
    except (InvalidTag, UnicodeDecodeError) as exc:
        raise SecretStoreError("encrypted secret could not be decrypted") from exc


def needs_reseal(value: str) -> bool:
    if not value:
        return False
    if not value.startswith(PREFIX):
        return True
    return cipher_key_id(value) != active_key_id()


def reseal(value: str, purpose: str = "") -> str:
    plaintext = unseal(value, purpose)
    if not plaintext:
        return ""
    keys, active = _load_keyring()
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(keys[active]).encrypt(nonce, plaintext.encode(), purpose.encode())
    return f"{PREFIX}{active}:{base64.b64encode(nonce + ciphertext).decode('ascii')}"


def rotate_key() -> str:
    global _key, _keys, _active_id, _key_path
    keys, _active = _load_keyring()
    key = os.urandom(32)
    key_id = _key_id(key)
    while key_id in keys:
        key = os.urandom(32)
        key_id = _key_id(key)
    keys[key_id] = key
    _write_keyring(_key_file(), keys, key_id)
    _keys = dict(keys)
    _active_id = key_id
    _key = key
    _key_path = _key_file()
    return key_id


def prune_keys(keep: set[str]) -> None:
    global _key, _keys, _active_id, _key_path
    keys, active = _load_keyring()
    retained = {key_id: key for key_id, key in keys.items() if key_id in keep or key_id == active}
    _write_keyring(_key_file(), retained, active)
    _keys = retained
    _active_id = active
    _key = retained[active]
    _key_path = _key_file()
