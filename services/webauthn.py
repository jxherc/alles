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


def verify_assertion(
    public_key_der: str,
    authenticator_data: str,
    client_data_json: str,
    signature: str,
    expected_challenge: str,
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
        pub = serialization.load_der_public_key(_b64d(public_key_der))
        signed = _b64d(authenticator_data) + hashlib.sha256(cd_bytes).digest()
        pub.verify(_b64d(signature), signed, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False
