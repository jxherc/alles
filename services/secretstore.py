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
import os, base64
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "enc1:"
_NONCE_LEN = 12
_KEY_FILE = Path(__file__).resolve().parent.parent / "data" / "secret.key"
_key: bytes | None = None


def _load_key() -> bytes:
    global _key
    if _key is None:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _KEY_FILE.exists():
            _key = base64.b64decode(_KEY_FILE.read_text().strip())
        else:
            _key = os.urandom(32)
            _KEY_FILE.write_text(base64.b64encode(_key).decode())
            try:
                os.chmod(_KEY_FILE, 0o600)
            except OSError:
                pass   # best effort — not supported on windows
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
    blob = base64.b64decode(value[len(PREFIX):])
    return AESGCM(_load_key()).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], None).decode()
