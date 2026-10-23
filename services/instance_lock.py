"""One cross-platform owner lock per Alles data directory."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from services.backup_recovery import staging_root


class InstanceLockError(RuntimeError):
    pass


def instance_lock_path(data_root: Path) -> Path:
    return staging_root(data_root) / "instance.lock"


class InstanceLock:
    def __init__(self, data_root: Path):
        self.data_root = data_root.expanduser().resolve()
        self.path = instance_lock_path(self.data_root)
        self._handle = None

    def acquire(self) -> "InstanceLock":
        if self._handle is not None:
            raise InstanceLockError("this process already holds the Alles instance lock")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = None
        try:
            handle = self.path.open("a+b")
            if os.name == "nt":
                self._lock_windows(handle)
            else:
                self._lock_unix(handle)
        except InstanceLockError:
            if handle is not None and not handle.closed:
                handle.close()
            raise
        except OSError as exc:
            if handle is not None and not handle.closed:
                handle.close()
            raise InstanceLockError("could not acquire the Alles data lock") from exc

        self._handle = handle
        metadata = {
            "pid": os.getpid(),
            "data_name": self.data_root.name,
            "locked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(metadata, sort_keys=True).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        except OSError:
            self.release()
            raise InstanceLockError("could not record the Alles data lock") from None
        return self

    @staticmethod
    def _lock_unix(handle) -> None:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise InstanceLockError(
                "another Alles process is already using this data directory"
            ) from exc

    @staticmethod
    def _lock_windows(handle) -> None:
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            handle.close()
            raise InstanceLockError(
                "another Alles process is already using this data directory"
            ) from exc

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

    def __enter__(self) -> "InstanceLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
