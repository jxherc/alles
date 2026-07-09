"""minimal WebAuthn assertion verification (9c).

We don't parse CBOR attestation — registration ships the public key as SPKI DER
(the browser exposes it via `PublicKeyCredential.getPublicKey()`), so verifying an
assertion is just: rebuild `authData || sha256(clientDataJSON)` and check the
ECDSA-P256 signature. Only ES256 (the platform-authenticator default) is supported.
"""

import base64
import hashlib
import json
import os
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64d(s) -> bytes:
    if isinstance(s, (bytes, bytearray)):
        return bytes(s)
    s = s.strip().replace("-", "+").replace("_", "/")  # tolerate url-safe + standard
    return base64.b64decode(s + "=" * (-len(s) % 4))


def new_challenge() -> str:
    """a fresh random challenge, b64url without padding (matches clientData.challenge)."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")


def _rp_id(origin: str) -> str:
    return (urlsplit(origin).hostname or "").lower()


def sign_count(authenticator_data: str) -> int:
    ad = _b64d(authenticator_data)
    if len(ad) < 37:
        return 0
    return int.from_bytes(ad[33:37], "big")


def verify_assertion(
    public_key_der: str,
    authenticator_data: str,
    client_data_json: str,
    signature: str,
    expected_challenge: str,
    expected_origin: str = "",
    *,
    expected_rp_id: str = "",
    previous_sign_count: int | None = None,
    require_user_verification: bool = False,
) -> bool:
    """True iff the assertion is a valid get-assertion over `expected_challenge`.

    All blob args are base64 (url-safe or standard); expected_challenge is the
    b64url-nopad string we handed the browser.
    """
    try:
        cd_bytes = _b64d(client_data_json)
        cd = json.loads(cd_bytes)
        if cd.get("type") != "webauthn.get":
            return False
        if cd.get("challenge") != expected_challenge:
            return False
        if expected_origin and cd.get("origin") != expected_origin.rstrip("/"):
            return False
        ad = _b64d(authenticator_data)
        if len(ad) < 37:
            return False
        rp = expected_rp_id or (_rp_id(expected_origin) if expected_origin else "")
        if rp and ad[:32] != hashlib.sha256(rp.encode()).digest():
            return False
        flags = ad[32]
        if not (flags & 0x01):
            return False
        if require_user_verification and not (flags & 0x04):
            return False
        cnt = int.from_bytes(ad[33:37], "big")
        if previous_sign_count is not None and previous_sign_count and cnt and cnt <= previous_sign_count:
            return False
        pub = serialization.load_der_public_key(_b64d(public_key_der))
        signed = ad + hashlib.sha256(cd_bytes).digest()
        pub.verify(_b64d(signature), signed, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False
