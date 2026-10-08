"""Crash-safe directory swap and rollback journal for offline restores."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from services.backup_recovery import staging_root

_ID = re.compile(r"^[0-9a-f]{32}$")


class RestoreApplyError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestoreOperation:
    operation_id: str
    restore_id: str
    live_root: Path
    recovery_root: Path
    journal_path: Path
    rollback_data: Path
    failed_parent: Path
    lock_path: Path


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise RestoreApplyError(f"invalid {label}")
    return value


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def maintenance_lock_path(live_root: Path) -> Path:
    return staging_root(live_root) / "maintenance.json"


def _operation(live_root: Path, operation_id: str, restore_id: str) -> RestoreOperation:
    live = live_root.expanduser().resolve()
    recovery = staging_root(live)
    return RestoreOperation(
        operation_id=_safe_id(operation_id, "restore operation id"),
        restore_id=_safe_id(restore_id, "restore id"),
        live_root=live,
        recovery_root=recovery,
        journal_path=recovery / "operations" / f"{operation_id}.json",
        rollback_data=recovery / "rollbacks" / operation_id / "data",
        failed_parent=recovery / "failed" / operation_id,
        lock_path=maintenance_lock_path(live),
    )


def _fsync_dir(directory: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, path)
        _fsync_dir(path.parent)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RestoreApplyError(f"{label} is missing or invalid") from exc
    if not isinstance(value, dict):
        raise RestoreApplyError(f"{label} is invalid")
    return value


def _write_lock(operation: RestoreOperation) -> None:
    operation.lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = {
        "operation_id": operation.operation_id,
        "restore_id": operation.restore_id,
        "pid": os.getpid(),
        "created_at": _now(),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        fd = os.open(operation.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RestoreApplyError(
            "another restore operation is already active; run `alles restore recover`"
        ) from exc
    except OSError as exc:
        raise RestoreApplyError("could not create the restore maintenance lock") from exc
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(operation.lock_path.parent)


def _release_lock(operation: RestoreOperation) -> None:
    lock = _read_json(operation.lock_path, "restore maintenance lock")
    if lock.get("operation_id") != operation.operation_id:
        raise RestoreApplyError("restore maintenance lock belongs to another operation")
    try:
        operation.lock_path.unlink()
        _fsync_dir(operation.lock_path.parent)
    except OSError as exc:
        raise RestoreApplyError("could not release the restore maintenance lock") from exc


def _journal(operation: RestoreOperation) -> dict:
    value = _read_json(operation.journal_path, "restore operation journal")
    if (
        value.get("operation_id") != operation.operation_id
        or value.get("restore_id") != operation.restore_id
    ):
        raise RestoreApplyError("restore operation journal does not match")
    return value


def mark_restore_state(
    operation: RestoreOperation, state: str, *, reason: str | None = None
) -> None:
    value = _journal(operation)
    value["state"] = state
    value["updated_at"] = _now()
    if reason:
        value["reason"] = reason
    _atomic_json(operation.journal_path, value)


def begin_restore_operation(live_root: Path, restore_id: str) -> RestoreOperation:
    restore_id = _safe_id(restore_id, "restore id")
    raw_live = live_root.expanduser()
    if _is_link_like(raw_live):
        raise RestoreApplyError("live Alles data directory cannot be a link")
    live = raw_live.resolve()
    if not live.is_dir():
        raise RestoreApplyError("live Alles data directory is missing")
    operation = _operation(live, uuid.uuid4().hex, restore_id)
    _write_lock(operation)
    try:
        _atomic_json(
            operation.journal_path,
            {
                "operation_id": operation.operation_id,
                "restore_id": restore_id,
                "state": "locked",
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
    except Exception:
        operation.lock_path.unlink(missing_ok=True)
        raise
    return operation


def _same_filesystem(left: Path, right: Path) -> bool:
    try:
        return left.stat().st_dev == right.stat().st_dev
    except OSError as exc:
        raise RestoreApplyError("could not check restore filesystem") from exc


def swap_in_staged(operation: RestoreOperation, staged_data: Path) -> None:
    raw_staged = staged_data.expanduser()
    if _is_link_like(raw_staged):
        raise RestoreApplyError("prepared restore data cannot be a link")
    staged = raw_staged.resolve()
    if not staged.is_dir():
        raise RestoreApplyError("prepared restore data is missing")
    if _is_link_like(operation.live_root) or not operation.live_root.is_dir():
        raise RestoreApplyError("live Alles data directory is missing")
    if operation.rollback_data.exists():
        raise RestoreApplyError("rollback destination already exists")
    if not _same_filesystem(operation.live_root.parent, staged.parent):
        raise RestoreApplyError("staged and live data must be on the same filesystem")

    operation.rollback_data.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
    mark_restore_state(operation, "moving_live")
    try:
        os.replace(operation.live_root, operation.rollback_data)
        _fsync_dir(operation.live_root.parent)
        mark_restore_state(operation, "live_saved")
        os.replace(staged, operation.live_root)
        _fsync_dir(operation.live_root.parent)
        mark_restore_state(operation, "candidate_installed")
    except Exception as exc:
        if not operation.live_root.exists() and operation.rollback_data.is_dir():
            try:
                os.replace(operation.rollback_data, operation.live_root)
                _fsync_dir(operation.live_root.parent)
                mark_restore_state(operation, "rolled_back", reason="swap-failed")
                _release_lock(operation)
            except Exception as rollback_exc:
                raise RestoreApplyError(
                    "restore swap failed and automatic rollback also failed; "
                    "run `alles restore recover`"
                ) from rollback_exc
        elif operation.live_root.is_dir() and not operation.rollback_data.exists():
            try:
                mark_restore_state(operation, "rolled_back", reason="swap-not-started")
                _release_lock(operation)
            except Exception as cleanup_exc:
                raise RestoreApplyError(
                    "restore swap did not start, but its lock could not be cleared; "
                    "run `alles restore recover`"
                ) from cleanup_exc
        raise RestoreApplyError("restore swap failed; original data was put back") from exc


def _next_failed_data(operation: RestoreOperation) -> Path:
    candidate = operation.failed_parent / "data"
    if not candidate.exists() and not candidate.parent.exists():
        return candidate
    return (
        operation.failed_parent.parent / f"{operation.operation_id}-{uuid.uuid4().hex[:8]}" / "data"
    )


def rollback_restore_operation(operation: RestoreOperation, *, reason: str) -> Path:
    if not operation.rollback_data.is_dir() or _is_link_like(operation.rollback_data):
        raise RestoreApplyError("verified rollback data is missing")
    mark_restore_state(operation, "rolling_back", reason=reason)
    failed_data = _next_failed_data(operation)
    moved_candidate = False
    try:
        if operation.live_root.exists():
            if _is_link_like(operation.live_root) or not operation.live_root.is_dir():
                raise RestoreApplyError("installed candidate path is unsafe")
            failed_data.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
            os.replace(operation.live_root, failed_data)
            moved_candidate = True
            _fsync_dir(operation.live_root.parent)
        os.replace(operation.rollback_data, operation.live_root)
        _fsync_dir(operation.live_root.parent)
        mark_restore_state(operation, "rolled_back", reason=reason)
        _release_lock(operation)
        return failed_data
    except Exception as exc:
        if moved_candidate and not operation.live_root.exists() and failed_data.is_dir():
            try:
                os.replace(failed_data, operation.live_root)
                _fsync_dir(operation.live_root.parent)
            except OSError:
                pass
        raise RestoreApplyError(
            "automatic rollback did not finish; run `alles restore recover`"
        ) from exc


def complete_restore_operation(operation: RestoreOperation) -> None:
    if not operation.live_root.is_dir() or not operation.rollback_data.is_dir():
        raise RestoreApplyError("restore cannot be completed without live and rollback data")
    mark_restore_state(operation, "applied")
    _release_lock(operation)


def _load_active_operation(live_root: Path) -> tuple[RestoreOperation, dict]:
    live = live_root.expanduser().resolve()
    lock_path = maintenance_lock_path(live)
    lock = _read_json(lock_path, "restore maintenance lock")
    operation_id = _safe_id(lock.get("operation_id"), "restore operation id")
    restore_id = _safe_id(lock.get("restore_id"), "restore id")
    operation = _operation(live, operation_id, restore_id)
    return operation, _journal(operation)


def active_restore_operation(live_root: Path) -> RestoreOperation | None:
    """Return the validated active restore, or ``None`` when no lock exists.

    Update rollback uses this before touching Git so it never mistakes recovery
    of an unrelated restore for recovery of its own data snapshot.
    """
    live = live_root.expanduser().resolve()
    if not maintenance_lock_path(live).exists():
        return None
    operation, _ = _load_active_operation(live)
    return operation


def recover_interrupted_restore(live_root: Path) -> dict:
    operation, journal = _load_active_operation(live_root)
    state = journal.get("state")
    if state in {"applied", "rolled_back", "abandoned"} and operation.live_root.is_dir():
        _release_lock(operation)
        return {"status": "applied" if state == "applied" else "rolled_back"}

    if operation.rollback_data.is_dir() and not _is_link_like(operation.rollback_data):
        failed_data = None
        if operation.live_root.exists():
            if _is_link_like(operation.live_root) or not operation.live_root.is_dir():
                raise RestoreApplyError("live data path is unsafe; refusing automatic recovery")
            failed_data = _next_failed_data(operation)
            failed_data.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
            os.replace(operation.live_root, failed_data)
            _fsync_dir(operation.live_root.parent)
        try:
            os.replace(operation.rollback_data, operation.live_root)
            _fsync_dir(operation.live_root.parent)
        except OSError as exc:
            if failed_data and failed_data.is_dir() and not operation.live_root.exists():
                os.replace(failed_data, operation.live_root)
            raise RestoreApplyError("interrupted restore recovery failed") from exc
        mark_restore_state(operation, "rolled_back", reason="interrupted-restore")
        _release_lock(operation)
        result = {"status": "rolled_back"}
        if failed_data is not None:
            result["failed_data"] = str(failed_data)
        return result

    if operation.live_root.is_dir() and not _is_link_like(operation.live_root):
        mark_restore_state(operation, "abandoned", reason="swap-not-started")
        _release_lock(operation)
        return {"status": "rolled_back"}
    raise RestoreApplyError("live and rollback data are both missing; refusing automatic changes")


def _operation_from_journal(live_root: Path, operation_id: str) -> tuple[RestoreOperation, dict]:
    operation_id = _safe_id(operation_id, "restore operation id")
    live = live_root.expanduser().resolve()
    path = staging_root(live) / "operations" / f"{operation_id}.json"
    journal = _read_json(path, "restore operation journal")
    restore_id = _safe_id(journal.get("restore_id"), "restore id")
    operation = _operation(live, operation_id, restore_id)
    return operation, _journal(operation)


def begin_manual_rollback(live_root: Path, operation_id: str) -> RestoreOperation:
    operation, journal = _operation_from_journal(live_root, operation_id)
    if journal.get("state") != "applied":
        raise RestoreApplyError("only a completed restore can be rolled back manually")
    if not operation.live_root.is_dir() or not operation.rollback_data.is_dir():
        raise RestoreApplyError("manual rollback data is missing")
    _write_lock(operation)
    try:
        mark_restore_state(operation, "manual_rollback_locked")
    except Exception:
        operation.lock_path.unlink(missing_ok=True)
        raise
    return operation


def discard_completed_restore(live_root: Path, operation_id: str) -> None:
    """Forget an accepted restore's local rollback copy and journal."""
    live = live_root.expanduser().resolve()
    if maintenance_lock_path(live).exists():
        raise RestoreApplyError("an active restore cannot be discarded")
    operation, journal = _operation_from_journal(live, operation_id)
    if journal.get("state") != "applied":
        raise RestoreApplyError("only a completed restore can be accepted")
    if operation.rollback_data.exists():
        if not operation.rollback_data.is_dir() or _is_link_like(operation.rollback_data):
            raise RestoreApplyError("restore rollback data is unsafe")
        try:
            shutil.rmtree(operation.rollback_data.parent)
            _fsync_dir(operation.rollback_data.parent.parent)
        except OSError as exc:
            raise RestoreApplyError("could not discard restore rollback data") from exc
    try:
        operation.journal_path.unlink()
        _fsync_dir(operation.journal_path.parent)
    except OSError as exc:
        raise RestoreApplyError("could not discard restore operation journal") from exc
