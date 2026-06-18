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
