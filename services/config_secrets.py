"""Encrypted JSON config helpers for connector credentials."""

import json
import os
import tempfile
from pathlib import Path

from services.secretstore import needs_reseal, seal, unseal


def load_secret_config(path: Path, purpose: str) -> dict:
    try:
        stored = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(stored, dict):
        return {}
    result = dict(stored)
    password = result.get("password")
    if isinstance(password, str) and password:
        result["password"] = unseal(password, purpose)
    return result


def save_secret_config(path: Path, config: dict, purpose: str) -> None:
    from services.recovery_consistency import recovery_consistency_lock

    with recovery_consistency_lock:
        stored = dict(config)
        password = stored.get("password")
        if isinstance(password, str) and password:
            stored["password"] = seal(password, purpose)
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


def migrate_secret_config(path: Path, purpose: str) -> int:
    try:
        stored = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return 0
    if not isinstance(stored, dict):
        return 0
    password = stored.get("password")
    if not isinstance(password, str) or not password or not needs_reseal(password):
        return 0
    save_secret_config(path, load_secret_config(path, purpose), purpose)
    return 1
