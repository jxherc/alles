"""Daily encrypted local backups for the first-run protection choice."""

from __future__ import annotations

import os
import re
import stat
import threading
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Callable

from core.settings import data_dir, load_settings, save_settings
from services.recovery_crypto import is_encrypted_recovery

_ARTIFACT = re.compile(r"^alles-auto-([0-9a-f]{16})-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.alles-backup$")
_INTERVAL = timedelta(hours=24)
_RETENTION = 7
_LOCK = threading.Lock()


class AutomaticBackupError(RuntimeError):
    pass


class _BackupProcessLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = None
        handle = None
        try:
            if self.path.is_symlink():
                raise AutomaticBackupError("automatic backup lock is unsafe")
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags, 0o600)
            metadata = os.fstat(fd)
            expected_uid = os.geteuid() if hasattr(os, "geteuid") else metadata.st_uid
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != expected_uid
                or metadata.st_nlink != 1
            ):
                raise AutomaticBackupError("automatic backup lock is unsafe")
            handle = os.fdopen(fd, "r+b", buffering=0)
            fd = None
            if os.name == "nt":
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except AutomaticBackupError:
            if fd is not None:
                os.close(fd)
            if handle is not None and not handle.closed:
                handle.close()
            raise
        except (BlockingIOError, OSError):
            if fd is not None:
                os.close(fd)
            if handle is not None and not handle.closed:
                handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        handle = self.handle
        if handle is None:
            return
        self.handle = None
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _owner_id(root: Path) -> str:
    return sha256(str(root.resolve()).encode()).hexdigest()[:16]


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def _destination(settings: dict, root: Path) -> Path:
    raw = settings.get("automatic_backup_dir")
    if not isinstance(raw, str) or not raw.strip():
        raise AutomaticBackupError("automatic backup destination is not configured")
    destination = Path(raw).expanduser()
    if not destination.is_absolute() or destination.is_symlink():
        raise AutomaticBackupError("automatic backup destination is unsafe")
    try:
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise AutomaticBackupError("automatic backup destination is unavailable") from exc
    if not destination.is_dir():
        raise AutomaticBackupError("automatic backup destination is not a folder")
    destination = destination.resolve()
    root = root.resolve()
    if destination == root or root in destination.parents:
        raise AutomaticBackupError("automatic backups must be stored outside Alles data")
    return destination


def _default_creator(root: Path, artifact: Path) -> Path:
    # Keep the existing, heavily tested encrypted-backup implementation as the single writer.
    from routes.backup import _create_encrypted_backup

    return _create_encrypted_backup(root, artifact)


def _prune(
    destination: Path,
    *,
    owner_id: str,
    keep: int = _RETENTION,
    current: Path | None = None,
) -> list[str]:
    owned = sorted(
        (
            path
            for path in destination.iterdir()
            if path.is_file()
            and not path.is_symlink()
            and (match := _ARTIFACT.fullmatch(path.name))
            and match.group(1) == owner_id
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    current = current.resolve() if current is not None else None
    retained = [path for path in owned if current is None or path.resolve() != current]
    retained = retained[: max(0, max(1, keep) - (1 if current is not None else 0))]
    keep_paths = {path.resolve() for path in retained}
    if current is not None:
        keep_paths.add(current)
    removed = []
    for path in owned:
        if path.resolve() in keep_paths:
            continue
        try:
            path.unlink()
        except OSError as exc:
            raise AutomaticBackupError("an expired automatic backup could not be removed") from exc
        removed.append(path.name)
    return removed


def run_if_due(
    *,
    now: datetime | None = None,
    force: bool = False,
    creator: Callable[[Path, Path], Path] = _default_creator,
) -> dict:
    """Create one encrypted artifact when enabled and due; never expose plaintext output."""
    settings = load_settings()
    if not settings.get("automatic_backup_enabled"):
        return {"status": "disabled", "created": False}
    now = _utc(now)
    previous = _parse_time(settings.get("automatic_backup_last_success"))
    if not force and previous is not None and timedelta(0) <= now - previous < _INTERVAL:
        return {"status": "not-due", "created": False, "last_success": previous.isoformat()}
    if not _LOCK.acquire(blocking=False):
        return {"status": "busy", "created": False}

    partial: Path | None = None
    process_lock: _BackupProcessLock | None = None
    try:
        root = data_dir().expanduser().resolve()
        process_lock = _BackupProcessLock(root / ".automatic-backup.lock")
        if not process_lock.acquire():
            return {"status": "busy", "created": False}
        settings = load_settings()
        if not settings.get("automatic_backup_enabled"):
            return {"status": "disabled", "created": False}
        previous = _parse_time(settings.get("automatic_backup_last_success"))
        if not force and previous is not None and timedelta(0) <= now - previous < _INTERVAL:
            return {"status": "not-due", "created": False, "last_success": previous.isoformat()}
        destination = _destination(settings, root)
        owner_id = _owner_id(root)
        name = (
            f"alles-auto-{owner_id}-{now.strftime('%Y%m%dT%H%M%SZ')}-"
            f"{uuid.uuid4().hex[:8]}.alles-backup"
        )
        final = destination / name
        partial = destination / f".{name}.{uuid.uuid4().hex}.partial"
        creator(root, partial)
        if partial.is_symlink() or not partial.is_file() or not is_encrypted_recovery(partial):
            raise AutomaticBackupError("automatic backup did not produce an encrypted artifact")
        partial.chmod(0o600)
        os.replace(partial, final)
        removed = _prune(destination, owner_id=owner_id, current=final)
        completed = now.isoformat().replace("+00:00", "Z")
        save_settings(
            {
                "automatic_backup_last_success": completed,
                "automatic_backup_last_error": "",
            }
        )
        return {
            "status": "created",
            "created": True,
            "filename": final.name,
            "bytes": final.stat().st_size,
            "last_success": completed,
            "removed": removed,
        }
    except Exception as exc:
        if isinstance(exc, AutomaticBackupError):
            error = exc
        else:
            error = AutomaticBackupError("automatic encrypted backup failed")
        save_settings({"automatic_backup_last_error": str(error)})
        raise error from exc
    finally:
        try:
            if partial is not None:
                partial.unlink(missing_ok=True)
        finally:
            try:
                if process_lock is not None:
                    process_lock.release()
            finally:
                _LOCK.release()


def status() -> dict:
    settings = load_settings()
    return {
        "enabled": bool(settings.get("automatic_backup_enabled")),
        "destination": str(settings.get("automatic_backup_dir") or ""),
        "last_success": str(settings.get("automatic_backup_last_success") or ""),
        "last_error": str(settings.get("automatic_backup_last_error") or ""),
        "interval_hours": 24,
        "retention": _RETENTION,
    }
