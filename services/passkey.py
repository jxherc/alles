"""passkey storage + use (9d).

The vault can hold passkeys it presents to *other* sites: each is an ES256 keypair whose private
key lives encrypted in a vault entry. `create_passkey` mints one; `sign` produces a WebAuthn
get-assertion signature with it (round-trips through `webauthn.verify_assertion`).
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from services.webauthn import _b64d


def create_passkey(rp_id: str, username: str) -> dict:
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    spki = priv.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return {
        "rp_id": rp_id,
        "username": username,
        "credential_id": base64.b64encode(os.urandom(16)).decode(),
        "public_key": base64.b64encode(spki).decode(),
        "private_key_pem": pem,
    }


def sign(private_key_pem: str, authenticator_data: str, client_data_json: str) -> str:
    """ES256 signature over authData || sha256(clientDataJSON), base64 — what an authenticator returns."""
    priv = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    signed = _b64d(authenticator_data) + hashlib.sha256(_b64d(client_data_json)).digest()
    sig = priv.sign(signed, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode()
