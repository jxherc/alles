"""Streaming authenticated encryption for complete Alles recovery archives."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from services.backup_recovery import (
    CHUNK_SIZE,
    DEFAULT_LIMITS,
    ArchiveLimits,
    RecoveryError,
)

MAGIC = b"ALLES-BACKUP-V1\0"
KEY_PREFIX = b"ALLES-RECOVERY-KEY-V1\n"
HEADER_MAX_BYTES = 64 * 1024
TAG_BYTES = 16
_HEADER_LENGTH = struct.Struct(">I")
_HKDF_INFO = b"alles-recovery-container-v1"


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def recovery_key_path(data_root: Path) -> Path:
    return data_root.expanduser().resolve() / "recovery.key"


def recovery_key_document(key: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) != 32:
        raise RecoveryError("recovery key must contain 32 bytes")
    token = base64.urlsafe_b64encode(key).rstrip(b"=")
    return KEY_PREFIX + token + b"\n"


def parse_recovery_key(document: bytes) -> bytes:
    if not isinstance(document, bytes) or len(document) > 4096:
        raise RecoveryError("recovery key file is invalid")
    lines = document.strip().splitlines()
    if len(lines) != 2 or lines[0] != KEY_PREFIX.rstrip(b"\n"):
        raise RecoveryError("recovery key file is invalid")
    token = lines[1]
    try:
        padded = token + b"=" * (-len(token) % 4)
        key = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise RecoveryError("recovery key file is invalid") from exc
    if len(key) != 32:
        raise RecoveryError("recovery key file is invalid")
    return key


def load_recovery_key(path: Path) -> bytes:
    if _is_link_like(path) or not path.is_file():
        raise RecoveryError("recovery key file was not found")
    try:
        return parse_recovery_key(path.read_bytes())
    except OSError as exc:
        raise RecoveryError("recovery key file could not be read") from exc


def load_or_create_recovery_key(data_root: Path) -> bytes:
    path = recovery_key_path(data_root)
    if path.exists() or _is_link_like(path):
        return load_recovery_key(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = os.urandom(32)
    document = recovery_key_document(key)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return load_recovery_key(path)
    except OSError as exc:
        raise RecoveryError("recovery key file could not be created") from exc
    try:
        os.write(fd, document)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def _key_id(key: bytes) -> str:
    if not isinstance(key, bytes) or len(key) != 32:
        raise RecoveryError("recovery key must contain 32 bytes")
    return hashlib.sha256(key).hexdigest()[:16]


def _derive_key(master_key: bytes, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=_HKDF_INFO).derive(master_key)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value, label: str, expected_bytes: int) -> bytes:
    if not isinstance(value, str):
        raise RecoveryError(f"encrypted backup {label} is invalid")
    try:
        raw = base64.b64decode(
            value.encode("ascii") + b"=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeError, ValueError, base64.binascii.Error) as exc:
        raise RecoveryError(f"encrypted backup {label} is invalid") from exc
    if len(raw) != expected_bytes:
        raise RecoveryError(f"encrypted backup {label} is invalid")
    return raw


def _header_bytes(plaintext_size: int, key: bytes, salt: bytes, nonce: bytes) -> bytes:
    header = {
        "format": "alles-encrypted-recovery",
        "format_version": 1,
        "cipher": "aes-256-gcm",
        "kdf": "hkdf-sha256",
        "salt": _b64(salt),
        "nonce": _b64(nonce),
        "key_id": _key_id(key),
        "plaintext_size": plaintext_size,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > HEADER_MAX_BYTES:
        raise RecoveryError("encrypted backup header is too large")
    return encoded


def _atomic_target(output_path: Path) -> tuple[Path, Path]:
    output = output_path.expanduser()
    if _is_link_like(output):
        raise RecoveryError("encrypted backup output cannot be a link")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = output.parent / f".{output.name}.{uuid.uuid4().hex}.partial"
    return output, temp


def encrypt_recovery_archive(
    archive_path: Path,
    output_path: Path,
    key: bytes,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> None:
    raw_source = archive_path.expanduser()
    if _is_link_like(raw_source):
        raise RecoveryError("plaintext recovery archive cannot be a link")
    source = raw_source.resolve()
    if not source.is_file():
        raise RecoveryError("plaintext recovery archive was not found")
    plaintext_size = source.stat().st_size
    if plaintext_size <= 0 or plaintext_size > limits.max_archive_bytes:
        raise RecoveryError("plaintext recovery archive size is invalid")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = _header_bytes(plaintext_size, key, salt, nonce)
    length = _HEADER_LENGTH.pack(len(header))
    aad = MAGIC + length + header
    encryptor = Cipher(algorithms.AES(_derive_key(key, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    output, temp = _atomic_target(output_path)
    try:
        with source.open("rb") as plain, temp.open("xb") as encrypted:
            encrypted.write(aad)
            while chunk := plain.read(CHUNK_SIZE):
                encrypted.write(encryptor.update(chunk))
            encrypted.write(encryptor.finalize())
            encrypted.write(encryptor.tag)
            encrypted.flush()
            os.fsync(encrypted.fileno())
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, output)
    except RecoveryError:
        temp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise RecoveryError("encrypted backup could not be written") from exc


def is_encrypted_recovery(path: Path) -> bool:
    if _is_link_like(path) or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryError(f"duplicate encrypted backup header field: {key}")
        result[key] = value
    return result


def _read_header(handle, container_size: int, limits: ArchiveLimits) -> tuple[dict, bytes, int]:
    magic = handle.read(len(MAGIC))
    if magic != MAGIC:
        raise RecoveryError("file is not an encrypted Alles backup")
    length_bytes = handle.read(_HEADER_LENGTH.size)
    if len(length_bytes) != _HEADER_LENGTH.size:
        raise RecoveryError("encrypted backup header is incomplete")
    header_size = _HEADER_LENGTH.unpack(length_bytes)[0]
    if header_size <= 0 or header_size > HEADER_MAX_BYTES:
        raise RecoveryError("encrypted backup header size is invalid")
    raw = handle.read(header_size)
    if len(raw) != header_size:
        raise RecoveryError("encrypted backup header is incomplete")
    try:
        header = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except RecoveryError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("encrypted backup header is invalid") from exc
    expected = {
        "format",
        "format_version",
        "cipher",
        "kdf",
        "salt",
        "nonce",
        "key_id",
        "plaintext_size",
        "created_at",
    }
    if not isinstance(header, dict) or set(header) != expected:
        raise RecoveryError("encrypted backup header fields are invalid")
    if (
        header["format"] != "alles-encrypted-recovery"
        or header["format_version"] != 1
        or header["cipher"] != "aes-256-gcm"
        or header["kdf"] != "hkdf-sha256"
    ):
        raise RecoveryError("encrypted backup format is not supported")
    plaintext_size = header["plaintext_size"]
    if (
        not isinstance(plaintext_size, int)
        or isinstance(plaintext_size, bool)
        or plaintext_size <= 0
        or plaintext_size > limits.max_archive_bytes
    ):
        raise RecoveryError("encrypted backup plaintext size is invalid")
    try:
        created = datetime.fromisoformat(header["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError
    except (AttributeError, ValueError):
        raise RecoveryError("encrypted backup creation time is invalid") from None
    header_end = len(MAGIC) + _HEADER_LENGTH.size + header_size
    if container_size != header_end + plaintext_size + TAG_BYTES:
        raise RecoveryError("encrypted backup size does not match its header")
    return header, MAGIC + length_bytes + raw, header_end


def decrypt_recovery_container(
    container_path: Path,
    output_path: Path,
    key: bytes,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> None:
    raw_container = container_path.expanduser()
    if _is_link_like(raw_container):
        raise RecoveryError("encrypted backup cannot be a link")
    container = raw_container.resolve()
    if not container.is_file():
        raise RecoveryError("encrypted backup was not found")
    try:
        container_size = container.stat().st_size
    except OSError as exc:
        raise RecoveryError("encrypted backup could not be inspected") from exc
    if container_size > limits.max_archive_bytes + HEADER_MAX_BYTES + len(MAGIC) + 32:
        raise RecoveryError("encrypted backup exceeds the configured size limit")

    output, temp = _atomic_target(output_path)
    try:
        with container.open("rb") as encrypted:
            header, aad, header_end = _read_header(encrypted, container_size, limits)
            if header["key_id"] != _key_id(key):
                raise RecoveryError("recovery key does not match this backup")
            salt = _unb64(header["salt"], "salt", 16)
            nonce = _unb64(header["nonce"], "nonce", 12)
            encrypted.seek(container_size - TAG_BYTES)
            tag = encrypted.read(TAG_BYTES)
            encrypted.seek(header_end)
            decryptor = Cipher(
                algorithms.AES(_derive_key(key, salt)), modes.GCM(nonce, tag)
            ).decryptor()
            decryptor.authenticate_additional_data(aad)
            remaining = header["plaintext_size"]
            with temp.open("xb") as plain:
                while remaining:
                    chunk = encrypted.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise RecoveryError("encrypted backup ciphertext is incomplete")
                    remaining -= len(chunk)
                    plain.write(decryptor.update(chunk))
                try:
                    plain.write(decryptor.finalize())
                except InvalidTag as exc:
                    raise RecoveryError("encrypted backup authentication failed") from exc
                plain.flush()
                os.fsync(plain.fileno())
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, output)
    except RecoveryError:
        temp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise RecoveryError("encrypted backup could not be decrypted") from exc
