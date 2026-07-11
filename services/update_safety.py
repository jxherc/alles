"""Durable maintenance marker for staged code/data updates."""

import json
import os
from pathlib import Path


class UpdateSafetyError(RuntimeError):
    pass


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def update_lock_path(data_root: Path) -> Path:
    root = data_root.expanduser().resolve()
    return root.parent / f".{root.name}-update-maintenance.json"


def update_start_allowed(data_root: Path, token: str | None) -> bool:
    if not token:
        return False
    try:
        current = json.loads(update_lock_path(data_root).read_text("utf-8"))
    except Exception:
        return False
    return current.get("update_id") == token


def begin_update(data_root: Path, update_id: str) -> Path:
    path = update_lock_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = json.dumps(
        {"update_id": update_id, "pid": os.getpid()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            current = json.loads(path.read_text("utf-8"))
        except Exception as exc:
            raise UpdateSafetyError(
                "an unfinished update has an invalid maintenance marker"
            ) from exc
        if current.get("update_id") == update_id:
            return path
        raise UpdateSafetyError("another unfinished update needs recovery")
    except OSError as exc:
        raise UpdateSafetyError("could not create the update maintenance marker") from exc
    try:
        os.write(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)
    return path


def finish_update(data_root: Path, update_id: str) -> None:
    path = update_lock_path(data_root)
    try:
        current = json.loads(path.read_text("utf-8"))
    except Exception as exc:
        raise UpdateSafetyError("the update maintenance marker is missing or invalid") from exc
    if current.get("update_id") != update_id:
        raise UpdateSafetyError("the update maintenance marker belongs to another update")
    try:
        path.unlink()
    except OSError as exc:
        raise UpdateSafetyError("could not clear the update maintenance marker") from exc
    _fsync_directory(path.parent)
