"""Encrypted JSON config helpers for connector credentials."""

import json
import os
import tempfile
from pathlib import Path

from services.secretstore import needs_reseal, seal, unseal


def load_secret_config(path: Path, purpose: str, field: str = "password") -> dict:
    try:
        stored = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(stored, dict):
        return {}
    result = dict(stored)
    secret = result.get(field)
    if isinstance(secret, str) and secret:
        result[field] = unseal(secret, purpose)
    return result


def save_secret_config(
    path: Path,
    config: dict,
    purpose: str,
    field: str = "password",
) -> None:
    from services.recovery_consistency import recovery_consistency_lock

    with recovery_consistency_lock:
        stored = dict(config)
        secret = stored.get(field)
        if secret not in (None, "") and not isinstance(secret, str):
            raise ValueError("credential field must be a string")
        if isinstance(secret, str) and secret:
            stored[field] = seal(secret, purpose)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(stored, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            temp.chmod(0o600)
            os.replace(temp, path)
            path.chmod(0o600)
        except Exception:
            temp.unlink(missing_ok=True)
            raise


def migrate_secret_config(path: Path, purpose: str, field: str = "password") -> int:
    try:
        stored = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return 0
    if not isinstance(stored, dict):
        return 0
    secret = stored.get(field)
    if not isinstance(secret, str) or not secret or not needs_reseal(secret):
        return 0
    save_secret_config(
        path,
        load_secret_config(path, purpose, field=field),
        purpose,
        field=field,
    )
    return 1
