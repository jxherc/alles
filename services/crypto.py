"""
AES-256-GCM encryption for vault entries.

v2 (current): a random 256-bit vault key encrypts every entry and attachment. the master
password only unwraps that key, through Argon2id (64 MiB, 3 passes, 4 lanes: RFC 9106 §4,
second recommended option). the unwrapped key lives in memory while the vault is open; the
password itself is never kept. same shape as bitwarden's user key and 1password's vault keys
(threat model in the life vault: "alles vault threat model").

legacy (v1): every blob had its own salt and its own PBKDF2-SHA256 (260k) key from the master
password. kept only to read old vaults once, on the unlock that upgrades them.
"""

import base64
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_SALT_LEN = 16
_NONCE_LEN = 12
_ITER = 260_000


def derive_key(master_pw: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITER)
    return kdf.derive(master_pw.encode())


def make_verifier(master_pw: str) -> str:
    """Store this in settings.json to verify the master password later."""
    salt = os.urandom(_SALT_LEN)
    key = derive_key(master_pw, salt)
    # store salt+key as a base64 blob used for comparison
    return base64.b64encode(salt + key).decode()


def verify_master(master_pw: str, verifier: str) -> bool:
    if is_v2(verifier):
        return open_vault_key(master_pw, verifier) is not None
    try:
        blob = base64.b64decode(verifier)
        salt = blob[:_SALT_LEN]
        stored_key = blob[_SALT_LEN:]
        candidate = derive_key(master_pw, salt)
        return hmac.compare_digest(stored_key, candidate)
    except Exception:
        return False


def encrypt(master_pw, plaintext: str) -> str:
    """v2 with a VaultKey ("v2:" + nonce+ct); a plain password string still makes v1."""
    if isinstance(master_pw, VaultKey):
        nonce = os.urandom(_NONCE_LEN)
        ct = AESGCM(master_pw.key).encrypt(nonce, plaintext.encode(), _ENTRY_AAD)
        return ENTRY_PREFIX + base64.b64encode(nonce + ct).decode()
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = derive_key(master_pw, salt)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(salt + nonce + ct).decode()


def decrypt(master_pw, ciphertext_b64: str) -> str:
    if isinstance(master_pw, VaultKey):
        if not is_v2_blob(ciphertext_b64):
            raise ValueError("v1 blob needs the master password")
        raw = base64.b64decode(ciphertext_b64[len(ENTRY_PREFIX) :])
        return (
            AESGCM(master_pw.key).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], _ENTRY_AAD).decode()
        )
    if is_v2_blob(ciphertext_b64):
        raise ValueError("v2 blob needs the vault key")
    blob = base64.b64decode(ciphertext_b64)
    salt = blob[:_SALT_LEN]
    nonce = blob[_SALT_LEN : _SALT_LEN + _NONCE_LEN]
    ct = blob[_SALT_LEN + _NONCE_LEN :]
    key = derive_key(master_pw, salt)
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def encrypt_bytes(master_pw, data: bytes) -> bytes:
    """AES-GCM for binary blobs (9b attachments). VaultKey: magic+nonce+ct; password: v1."""
    if isinstance(master_pw, VaultKey):
        nonce = os.urandom(_NONCE_LEN)
        return BYTES_MAGIC + nonce + AESGCM(master_pw.key).encrypt(nonce, data, _BYTES_AAD)
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = derive_key(master_pw, salt)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return salt + nonce + ct


def decrypt_bytes(master_pw, blob: bytes) -> bytes:
    if isinstance(master_pw, VaultKey):
        if not is_v2_bytes(blob):
            raise ValueError("v1 attachment needs the master password")
        raw = blob[len(BYTES_MAGIC) :]
        return AESGCM(master_pw.key).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], _BYTES_AAD)
    if is_v2_bytes(blob):
        raise ValueError("v2 attachment needs the vault key")
    salt = blob[:_SALT_LEN]
    nonce = blob[_SALT_LEN : _SALT_LEN + _NONCE_LEN]
    ct = blob[_SALT_LEN + _NONCE_LEN :]
    key = derive_key(master_pw, salt)
    return AESGCM(key).decrypt(nonce, ct, None)


def envelope_encrypt(plaintext: str) -> tuple[str, str]:
    """encrypt with a FRESH random key (not the master pw). returns (key_b64, blob_b64),
    where blob = nonce+ct. used for per-item share links — the key travels in the URL
    fragment so the server only ever stores the ciphertext (9b)."""
    key = os.urandom(32)
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return base64.urlsafe_b64encode(key).decode(), base64.b64encode(nonce + ct).decode()


def envelope_decrypt(key_b64: str, blob_b64: str) -> str:
    key = base64.urlsafe_b64decode(key_b64)
    blob = base64.b64decode(blob_b64)
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


# ── v2: wrapped random vault key ─────────────────────────────────────────────
KDF_MEMORY_KIB = 64 * 1024
KDF_PASSES = 3
KDF_LANES = 4
VERIFIER_PREFIX = "v2."
ENTRY_PREFIX = "v2:"
BYTES_MAGIC = b"AV2\x00"
_KEY_AAD = b"alles-vault-key"
_ENTRY_AAD = b"alles-vault-entry"
_BYTES_AAD = b"alles-vault-attachment"


class VaultKey:
    """the open vault's key, plus the verifier it was unwrapped from (so a password change
    makes every older session stale). repr never shows the key."""

    __slots__ = ("key", "verifier")

    def __init__(self, key: bytes, verifier: str):
        if len(key) != 32:
            raise ValueError("vault key must be 32 bytes")
        self.key = key
        self.verifier = verifier

    def __repr__(self) -> str:
        return "VaultKey(<hidden>)"

    def current_for(self, verifier: str | None) -> bool:
        return bool(verifier) and hmac.compare_digest(self.verifier, verifier)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode())


def _kek(master_pw: str, salt: bytes, memory: int, passes: int, lanes: int) -> bytes:
    return Argon2id(
        salt=salt, length=32, iterations=passes, lanes=lanes, memory_cost=memory
    ).derive(master_pw.encode())


def is_v2(verifier: str | None) -> bool:
    return bool(verifier) and verifier.startswith(VERIFIER_PREFIX)


def wrap_key(master_pw: str, key: bytes) -> str:
    """wrap a vault key under the password. the result is the vault's verifier: a wrong
    password fails the GCM tag, so no separate password hash is stored."""
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    kek = _kek(master_pw, salt, KDF_MEMORY_KIB, KDF_PASSES, KDF_LANES)
    wrapped = AESGCM(kek).encrypt(nonce, key, _KEY_AAD)
    return ".".join(
        [
            "v2",
            "argon2id",
            str(KDF_MEMORY_KIB),
            str(KDF_PASSES),
            str(KDF_LANES),
            _b64e(salt),
            _b64e(nonce + wrapped),
        ]
    )


def new_vault_key(master_pw: str) -> VaultKey:
    key = os.urandom(32)
    return VaultKey(key, wrap_key(master_pw, key))


def open_vault_key(master_pw: str, verifier: str) -> VaultKey | None:
    """unwrap the vault key, or None for a wrong password or a v1 verifier."""
    if not is_v2(verifier):
        return None
    try:
        _v, kdf, memory, passes, lanes, salt, blob = verifier.split(".")
        if kdf != "argon2id":
            return None
        raw = _b64d(blob)
        kek = _kek(master_pw, _b64d(salt), int(memory), int(passes), int(lanes))
        key = AESGCM(kek).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], _KEY_AAD)
    except (InvalidTag, ValueError):
        return None
    return VaultKey(key, verifier)


def rewrap(master_pw: str, vault_key: VaultKey) -> VaultKey:
    """same key, new password: items stay as they are (1password white paper, appendix A.5)."""
    return VaultKey(vault_key.key, wrap_key(master_pw, vault_key.key))


def secret_wrap(secret: bytes, info: bytes, key: bytes) -> str:
    """wrap a vault key under some other high-entropy secret (a passkey's PRF output, a
    server-held device key). HKDF, not a password KDF: the secret is already random."""
    kek = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(secret)
    nonce = os.urandom(_NONCE_LEN)
    return _b64e(nonce + AESGCM(kek).encrypt(nonce, key, _KEY_AAD))


def secret_unwrap(secret: bytes, info: bytes, blob: str) -> bytes | None:
    try:
        raw = _b64d(blob)
        kek = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(secret)
        return AESGCM(kek).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], _KEY_AAD)
    except (InvalidTag, ValueError):
        return None


def is_v2_blob(blob: str | None) -> bool:
    return bool(blob) and blob.startswith(ENTRY_PREFIX)


def is_v2_bytes(blob: bytes) -> bool:
    return blob.startswith(BYTES_MAGIC)
