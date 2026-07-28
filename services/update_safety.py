"""Durable maintenance marker for staged code/data updates."""

import json
import os
import stat
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


def update_command_lock_path(data_root: Path) -> Path:
    root = data_root.expanduser().resolve()
    return root.parent / f".{root.name}-update-command.lock"


class UpdateCommandLock:
    """Crash-released mutex for update rollback and acceptance commands."""

    def __init__(self, data_root: Path):
        self.path = update_command_lock_path(data_root)
        self._handle = None

    def acquire(self) -> "UpdateCommandLock":
        if self._handle is not None:
            raise UpdateSafetyError("this process already holds the update command lock")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = None
        fd = None
        try:
            if self.path.is_symlink():
                raise OSError("update command lock is unsafe")
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags, 0o600)
            metadata = os.fstat(fd)
            expected_uid = os.geteuid() if hasattr(os, "geteuid") else metadata.st_uid
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != expected_uid
                or metadata.st_nlink != 1
            ):
                raise OSError("update command lock is unsafe")
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
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
        except (BlockingIOError, OSError) as exc:
            if fd is not None:
                os.close(fd)
            if handle is not None and not handle.closed:
                handle.close()
            raise UpdateSafetyError("another update command is still running") from exc
        self._handle = handle
        return self

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
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

    def __enter__(self) -> "UpdateCommandLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


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
