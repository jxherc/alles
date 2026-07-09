"""
at-rest encryption for server-side secrets (model API keys, mail passwords).

unlike the vault (locked behind the master password), these have to be usable
without user interaction — the server needs them to talk to providers. so
they're sealed with AES-256-GCM under a machine-local key in data/secret.key
(generated on first use, chmod 600). the database file alone no longer
contains readable credentials; keep the key file with it when moving data/.

values are prefixed "enc1:"; anything without the prefix is treated as legacy
plaintext and passed through, so existing rows keep working until re-saved.
"""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.settings import data_dir

PREFIX = "enc1:"
_NONCE_LEN = 12
_KEY_FILE: Path | None = None
_key: bytes | None = None
_key_path: Path | None = None


def _key_file() -> Path:
    return _KEY_FILE or data_dir() / "secret.key"


def _load_key() -> bytes:
    global _key, _key_path
    path = _key_file()
    if _key is None or _key_path != path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            _key = base64.b64decode(path.read_text().strip())
        else:
            _key = os.urandom(32)
            path.write_text(base64.b64encode(_key).decode())
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass  # best effort — not supported on windows
        _key_path = path
    return _key


def seal(plaintext: str) -> str:
    if not plaintext or plaintext.startswith(PREFIX):
        return plaintext
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(_load_key()).encrypt(nonce, plaintext.encode(), None)
    return PREFIX + base64.b64encode(nonce + ct).decode()


def unseal(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value or ""
    blob = base64.b64decode(value[len(PREFIX) :])
    return AESGCM(_load_key()).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], None).decode()
