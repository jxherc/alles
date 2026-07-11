"""
Web Push (RFC 8030/8291/8292) with no extra dependencies — VAPID signing and
aes128gcm payload encryption built on `cryptography`, delivery over httpx.

the VAPID keypair lives in data/vapid.pem (generated on first use). browsers
subscribe against its public key, so deleting the file invalidates every
existing subscription.
"""

import base64
import json
import logging
import os
import struct
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from core.settings import data_dir

log = logging.getLogger("aide.webpush")

_KEY_FILE: Path | None = None
_vapid_key: ec.EllipticCurvePrivateKey | None = None
_vapid_path: Path | None = None


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _key_file() -> Path:
    return _KEY_FILE or data_dir() / "vapid.pem"


def _load_vapid() -> ec.EllipticCurvePrivateKey:
    global _vapid_key, _vapid_path
    path = _key_file()
    if _vapid_key is None or _vapid_path != path:
        if path.exists():
            _vapid_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        else:
            _vapid_key = ec.generate_private_key(ec.SECP256R1())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                _vapid_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        _vapid_path = path
    return _vapid_key


def public_key_b64u() -> str:
    pub = (
        _load_vapid()
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    return _b64u(pub)


def _vapid_auth(endpoint: str) -> str:
    from urllib.parse import urlsplit

    u = urlsplit(endpoint)
    claims = {
        "aud": f"{u.scheme}://{u.netloc}",
        "exp": int(time.time()) + 12 * 3600,
        "sub": "mailto:admin@localhost",
    }
    header = _b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    body = _b64u(json.dumps(claims).encode())
    der = _load_vapid().sign(f"{header}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)  # JWT wants raw r||s, not DER
    sig = _b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{body}.{sig}, k={public_key_b64u()}"


def _encrypt(plaintext: bytes, p256dh: str, auth: str) -> bytes:
    """RFC 8291 aes128gcm — returns the complete encrypted body (header included)"""
    ua_pub_raw = _b64u_dec(p256dh)
    auth_secret = _b64u_dec(auth)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_raw)
    as_priv = ec.generate_private_key(ec.SECP256R1())
    as_pub_raw = as_priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = as_priv.exchange(ec.ECDH(), ua_pub)
    ikm = HKDF(
        hashes.SHA256(), 32, salt=auth_secret, info=b"WebPush: info\x00" + ua_pub_raw + as_pub_raw
    ).derive(shared)
    salt = os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    ct = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)  # 0x02 = last record
    return salt + struct.pack("!IB", 4096, len(as_pub_raw)) + as_pub_raw + ct


async def send_push(sub: dict, payload: dict, ttl: int = 86400) -> str:
    """Deliver one push: sent, gone, failed, or uncertain."""
    endpoint = sub["endpoint"]
    body = _encrypt(json.dumps(payload).encode(), sub["p256dh"], sub["auth"])
    headers = {
        "authorization": _vapid_auth(endpoint),
        "content-encoding": "aes128gcm",
        "ttl": str(ttl),
        "urgency": "normal",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(endpoint, content=body, headers=headers)
    except Exception as e:
        # The provider may have accepted the request before the connection failed.
        # Do not include endpoint-bearing exception text in logs.
        log.warning("push delivery uncertain: %s", type(e).__name__)
        return "uncertain"
    if r.status_code in (404, 410):
        return "gone"
    if r.status_code >= 500 or r.status_code in (408, 429):
        log.warning("push delivery uncertain: http %s", r.status_code)
        return "uncertain"
    if r.status_code >= 300:
        log.warning("push rejected: http %s", r.status_code)
        return "failed"
    return "sent"
