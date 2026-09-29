"""Create one encrypted recovery artifact for local and remote backup targets."""

import uuid
from pathlib import Path

from services.backup_recovery import (
    DEFAULT_LIMITS,
    ArchiveLimits,
    RecoveryError,
    create_recovery_archive,
)
from services.recovery_crypto import encrypt_recovery_archive, load_or_create_recovery_key


def create_encrypted_backup(
    root: Path,
    archive: Path,
    *,
    include_photos: bool = False,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> Path:
    """Write a verified archive, then remove its plaintext even when encryption fails."""
    plaintext = archive.parent / f".{archive.name}.{uuid.uuid4().hex}.zip"
    try:
        recovery_key = load_or_create_recovery_key(root)
        create_recovery_archive(
            root,
            plaintext,
            include_photos=include_photos,
            expected_recovery_key=recovery_key,
            limits=limits,
        )
        try:
            plaintext.chmod(0o600)
        except OSError:
            pass
        encrypt_recovery_archive(plaintext, archive, recovery_key, limits=limits)
        return archive
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    finally:
        try:
            plaintext.unlink(missing_ok=True)
        except OSError as exc:
            archive.unlink(missing_ok=True)
            raise RecoveryError("temporary plaintext backup could not be removed") from exc
