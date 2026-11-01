"""password-protected vault export files.

a json wrapper that names its own kdf, so a later alles (or a short script with any argon2id
and aes-gcm library) can open it:
{"format": "alles-vault-export", "version": 1,
 "kdf": {"name": "argon2id", "memory_kib", "passes", "lanes", "salt"},
 "nonce", "data"}   (base64; data is AES-256-GCM over the entries json)
"""

from __future__ import annotations

import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from services.crypto import KDF_LANES, KDF_MEMORY_KIB, KDF_PASSES

FORMAT = "alles-vault-export"
_AAD = b"alles-vault-export-v1"
_MAX_MEMORY_KIB = 1024 * 1024  # a file can't make the server spend more than 1 GiB


class ExportError(ValueError):
    pass


def _key(password: str, salt: bytes, memory: int, passes: int, lanes: int) -> bytes:
    return Argon2id(
        salt=salt, length=32, iterations=passes, lanes=lanes, memory_cost=memory
    ).derive(password.encode())


def seal(password: str, payload: dict) -> str:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _key(password, salt, KDF_MEMORY_KIB, KDF_PASSES, KDF_LANES)
    data = AESGCM(key).encrypt(nonce, json.dumps(payload).encode(), _AAD)
    return json.dumps(
        {
            "format": FORMAT,
            "version": 1,
            "kdf": {
                "name": "argon2id",
                "memory_kib": KDF_MEMORY_KIB,
                "passes": KDF_PASSES,
                "lanes": KDF_LANES,
                "salt": base64.b64encode(salt).decode(),
            },
            "nonce": base64.b64encode(nonce).decode(),
            "data": base64.b64encode(data).decode(),
        },
        indent=1,
    )


def open_sealed(password: str, text: str) -> dict:
    try:
        wrapper = json.loads(text)
        kdf = wrapper["kdf"]
        if wrapper.get("format") != FORMAT or kdf.get("name") != "argon2id":
            raise ExportError("not an alles vault export")
        memory, passes, lanes = int(kdf["memory_kib"]), int(kdf["passes"]), int(kdf["lanes"])
        if not (8 * lanes <= memory <= _MAX_MEMORY_KIB and 1 <= passes <= 20 and 1 <= lanes <= 16):
            raise ExportError("export uses settings alles won't run")
        salt = base64.b64decode(kdf["salt"])
        nonce = base64.b64decode(wrapper["nonce"])
        data = base64.b64decode(wrapper["data"])
    except ExportError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise ExportError("not an alles vault export") from exc
    try:
        plain = AESGCM(_key(password, salt, memory, passes, lanes)).decrypt(nonce, data, _AAD)
    except InvalidTag as exc:
        raise ExportError("wrong export password") from exc
    payload = json.loads(plain)
    if not isinstance(payload, dict):
        raise ExportError("not an alles vault export")
    return payload
