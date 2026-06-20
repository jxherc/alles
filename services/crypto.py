"""
AES-256-GCM encryption for vault entries.
Key derived from master password via PBKDF2HMAC (SHA-256, 260k iterations).
"""

import os, base64, hashlib, hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


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
    try:
        blob = base64.b64decode(verifier)
        salt = blob[:_SALT_LEN]
        stored_key = blob[_SALT_LEN:]
        candidate = derive_key(master_pw, salt)
        return hmac.compare_digest(stored_key, candidate)
    except Exception:
        return False


def encrypt(master_pw: str, plaintext: str) -> str:
    """Returns base64-encoded salt+nonce+ciphertext."""
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = derive_key(master_pw, salt)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(salt + nonce + ct).decode()


def decrypt(master_pw: str, ciphertext_b64: str) -> str:
    blob = base64.b64decode(ciphertext_b64)
    salt = blob[:_SALT_LEN]
    nonce = blob[_SALT_LEN : _SALT_LEN + _NONCE_LEN]
    ct = blob[_SALT_LEN + _NONCE_LEN :]
    key = derive_key(master_pw, salt)
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def encrypt_bytes(master_pw: str, data: bytes) -> bytes:
    """master-pw AES-GCM for binary blobs (9b attachments). returns salt+nonce+ct bytes."""
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = derive_key(master_pw, salt)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return salt + nonce + ct


def decrypt_bytes(master_pw: str, blob: bytes) -> bytes:
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
