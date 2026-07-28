"""Restart-safe Journal-to-Markdown migration staging.

This foundation copies entries into verified daily notes but deliberately does not switch the
source of truth. The approved Docs UI will own that later cutover. Until then the database remains
authoritative, rollback is available, and locked Journal content is never copied implicitly.
"""

import ctypes
import errno
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from core.settings import data_dir, load_settings
from services import journal_vault, vault_md

OPERATION_DIR = "journal-migrations"
ParentHandle = int | Path | None


def _root() -> Path:
    root = data_dir() / OPERATION_DIR
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _operation_dir(operation_id: str) -> Path:
    if not operation_id or any(char not in "0123456789abcdef" for char in operation_id):
        raise ValueError("invalid journal migration id")
    path = _root() / operation_id
    if not path.is_dir():
        raise FileNotFoundError("journal migration not found")
    return path


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def _target_parent(rel: str, *, create: bool = False):
    """Anchor a Journal target's parent without following replaceable symlinks."""
    safe = vault_md._safe(rel)
    root = vault_md.root_dir()
    relative = safe.relative_to(root)
    if not relative.parts:
        raise vault_md.DocumentConflictError("Journal migration target is invalid")
    if os.name == "nt":
        candidate = root
        for part in relative.parts[:-1]:
            candidate = candidate / part
            if candidate.is_symlink():
                raise vault_md.DocumentConflictError(
                    f"Journal migration refuses symbolic link {rel}"
                )
            if create:
                candidate.mkdir(exist_ok=True)
        yield safe.parent, safe.name, safe.parent
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError as exc:
        raise vault_md.DocumentConflictError(
            "Journal vault root is unavailable or symbolic"
        ) from exc
    try:
        for part in relative.parts[:-1]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError as exc:
                raise vault_md.DocumentConflictError(
                    f"Journal migration refuses symbolic link {rel}"
                ) from exc
            os.close(descriptor)
            descriptor = child
        yield descriptor, relative.parts[-1], safe.parent
    finally:
        os.close(descriptor)


def _metadata_name(row: dict, field: str, suffix: str) -> str | None:
    value = row.get(field)
    if not value:
        return None
    name = str(value)
    if Path(name).name != name or not name.endswith(suffix):
        raise ValueError("journal migration recovery metadata is invalid")
    return name


def _path_at(parent_fd: ParentHandle, name: str) -> str | Path:
    return parent_fd / name if isinstance(parent_fd, Path) else name


def _open_at(parent_fd: ParentHandle, name: str, flags: int, mode: int = 0o777) -> int:
    if isinstance(parent_fd, int):
        return os.open(name, flags, mode, dir_fd=parent_fd)
    return os.open(_path_at(parent_fd, name), flags, mode)


def _stat_at(parent_fd: ParentHandle, name: str):
    if isinstance(parent_fd, Path):
        return os.stat(parent_fd / name, follow_symlinks=False)
    if parent_fd is None:
        return os.stat(name, follow_symlinks=False)
    return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)


def _exists_at(parent_fd: ParentHandle, name: str) -> bool:
    try:
        _stat_at(parent_fd, name)
        return True
    except FileNotFoundError:
        return False


def _is_file_at(parent_fd: ParentHandle, name: str) -> bool:
    try:
        return stat.S_ISREG(_stat_at(parent_fd, name).st_mode)
    except FileNotFoundError:
        return False


def _owns_at(parent_fd: ParentHandle, name: str, row: dict) -> bool:
    try:
        identity = _stat_at(parent_fd, name)
    except FileNotFoundError:
        return False
    return (
        stat.S_ISREG(identity.st_mode)
        and int(row.get("owned_device") or -1) == identity.st_dev
        and int(row.get("owned_inode") or -1) == identity.st_ino
    )


def _read_at(parent_fd: ParentHandle, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = _open_at(parent_fd, name, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise vault_md.DocumentConflictError("Journal migration target is not a regular file")
        chunks = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _link_at(parent_fd: ParentHandle, source: str, destination: str) -> None:
    if isinstance(parent_fd, int):
        os.link(
            source,
            destination,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        return
    os.link(_path_at(parent_fd, source), _path_at(parent_fd, destination), follow_symlinks=False)


def _unlink_at(parent_fd: ParentHandle, name: str, *, missing_ok: bool = False) -> None:
    try:
        if isinstance(parent_fd, int):
            os.unlink(name, dir_fd=parent_fd)
        else:
            os.unlink(_path_at(parent_fd, name))
    except FileNotFoundError:
        if not missing_ok:
            raise


def _rename_at_no_replace(parent_fd: ParentHandle, source: str, destination: str) -> None:
    if os.name == "nt" or not isinstance(parent_fd, int):
        source_path = _path_at(parent_fd, source)
        destination_path = _path_at(parent_fd, destination)
        if os.path.exists(destination_path):
            raise FileExistsError(destination_path)
        os.rename(source_path, destination_path)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        result = function(parent_fd, os.fsencode(source), parent_fd, os.fsencode(destination), 4)
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        result = function(parent_fd, os.fsencode(source), parent_fd, os.fsencode(destination), 1)
    else:
        raise vault_md.DocumentConflictError(
            "Journal migration requires atomic non-replacing filesystem operations"
        )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(destination)
    raise OSError(error, os.strerror(error), destination)


def _fsync_parent(parent_fd: ParentHandle, fallback: Path) -> None:
    if not isinstance(parent_fd, int):
        _fsync_directory(parent_fd if isinstance(parent_fd, Path) else fallback)
        return
    try:
        os.fsync(parent_fd)
    except OSError:
        pass


def _read_manifest(operation_id: str) -> tuple[Path, dict]:
    operation = _operation_dir(operation_id)
    try:
        manifest = json.loads((operation / "manifest.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("journal migration manifest is unavailable") from exc
    if manifest.get("operation_id") != operation_id or manifest.get("version") != 1:
        raise ValueError("journal migration manifest is invalid")
    return operation, manifest


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _restore_quarantine_at(parent_fd: ParentHandle, quarantine: str, target: str) -> bool:
    try:
        _rename_at_no_replace(parent_fd, quarantine, target)
    except FileExistsError:
        return False
    return True


def _remove_if_hash_at(
    operation: Path,
    manifest: dict,
    parent_fd: ParentHandle,
    parent_path: Path,
    target_name: str,
    row: dict,
) -> bool:
    """Atomically detach and verify the exact owned note through its parent descriptor."""
    quarantine = _metadata_name(row, "rollback_quarantine", ".rollback")
    if quarantine is None:
        quarantine = f".{target_name}.alles-{uuid.uuid4().hex}.rollback"
        row["rollback_quarantine"] = quarantine
        _atomic_json(operation / "manifest.json", manifest)
    if not _exists_at(parent_fd, quarantine):
        try:
            _rename_at_no_replace(parent_fd, target_name, quarantine)
            _fsync_parent(parent_fd, parent_path)
        except FileNotFoundError:
            row["rollback_quarantine"] = None
            return True
    if not _owns_at(parent_fd, quarantine, row) or (
        _hash_bytes(_read_at(parent_fd, quarantine)) != row["desired_hash"]
    ):
        _restore_quarantine_at(parent_fd, quarantine, target_name)
        if not _exists_at(parent_fd, quarantine):
            row["rollback_quarantine"] = None
        return False
    _fsync_parent(parent_fd, parent_path)
    return True


def _detach_owned_sidecar_at(
    parent_fd: ParentHandle,
    parent_path: Path,
    name: str,
    row: dict,
    *,
    suffix: str,
    require_desired_hash: bool = True,
) -> bool:
    """Move one owned sidecar out of its live name before validating it."""
    quarantine = f".{name}.alles-{uuid.uuid4().hex}{suffix}"
    try:
        _rename_at_no_replace(parent_fd, name, quarantine)
    except FileNotFoundError:
        return True
    _fsync_parent(parent_fd, parent_path)
    if not _owns_at(parent_fd, quarantine, row) or (
        require_desired_hash and _hash_bytes(_read_at(parent_fd, quarantine)) != row["desired_hash"]
    ):
        _restore_quarantine_at(parent_fd, quarantine, name)
        return False
    # Retain the detached inode: an editor may still hold it open and write after
    # verification, and unlinking it here would discard those bytes.
    return True


def _install_created_row(operation: Path, manifest: dict, row: dict) -> None:
    """Publish one complete note and durably bind rollback ownership to its inode."""
    staged = operation / "stage" / row["path"]
    desired = staged.read_bytes()
    if _hash_bytes(desired) != row["desired_hash"]:
        raise ValueError("journal migration stage failed verification")
    restart = True
    while restart:
        restart = False
        with _target_parent(row["path"], create=True) as (parent_fd, target_name, parent_path):
            temp_name = _metadata_name(row, "installing", ".installing")
            seed_name = (
                _metadata_name(row, "install_seed", ".seed")
                if row.get("install_seed_location") == "target"
                else None
            )
            if temp_name is None:
                seed_name = f".{target_name}.alles-{uuid.uuid4().hex}.seed"
                temp_name = f".{target_name}.alles-{uuid.uuid4().hex}.installing"
                flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                descriptor = _open_at(parent_fd, seed_name, flags, 0o600)
                try:
                    identity = os.fstat(descriptor)
                    row["installing"] = temp_name
                    row["install_seed"] = seed_name
                    row["install_seed_location"] = "target"
                    row["owned_device"] = identity.st_dev
                    row["owned_inode"] = identity.st_ino
                    _atomic_json(operation / "manifest.json", manifest)
                    try:
                        _link_at(parent_fd, seed_name, temp_name)
                    except FileExistsError as exc:
                        raise vault_md.DocumentConflictError(
                            f"Journal daily note {row['path']} has an occupied install sidecar"
                        ) from exc
                    _fsync_parent(parent_fd, parent_path)
                    view = memoryview(desired)
                    while view:
                        written = os.write(descriptor, view)
                        view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            elif row.get("owned_device") is None or row.get("owned_inode") is None:
                if not _exists_at(parent_fd, temp_name):
                    row["installing"] = None
                    row["install_seed"] = None
                    row["install_seed_location"] = None
                    _atomic_json(operation / "manifest.json", manifest)
                    restart = True
                    continue
                raise vault_md.DocumentConflictError(
                    f"Journal daily note {row['path']} has unowned interrupted install state"
                )
            else:
                if _exists_at(parent_fd, target_name) and (
                    not _owns_at(parent_fd, target_name, row)
                    or _hash_bytes(_read_at(parent_fd, target_name)) != row["desired_hash"]
                ):
                    raise vault_md.DocumentConflictError(
                        f"Journal daily note {row['path']} changed after publication"
                    )
                if (
                    not _exists_at(parent_fd, temp_name)
                    and seed_name is not None
                    and _owns_at(parent_fd, seed_name, row)
                ):
                    try:
                        _link_at(parent_fd, seed_name, temp_name)
                    except FileExistsError as exc:
                        raise vault_md.DocumentConflictError(
                            f"Journal daily note {row['path']} has an occupied install sidecar"
                        ) from exc
                    _fsync_parent(parent_fd, parent_path)
                if _owns_at(parent_fd, temp_name, row) and (
                    _hash_bytes(_read_at(parent_fd, temp_name)) != row["desired_hash"]
                ):
                    flags = os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
                    descriptor = _open_at(parent_fd, temp_name, flags)
                    try:
                        identity = os.fstat(descriptor)
                        if (
                            identity.st_dev != row["owned_device"]
                            or identity.st_ino != row["owned_inode"]
                        ):
                            raise vault_md.DocumentConflictError(
                                f"Journal daily note {row['path']} has invalid interrupted install state"
                            )
                        view = memoryview(desired)
                        while view:
                            written = os.write(descriptor, view)
                            view = view[written:]
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            if (
                not _owns_at(parent_fd, temp_name, row)
                or _hash_bytes(_read_at(parent_fd, temp_name)) != row["desired_hash"]
            ):
                raise vault_md.DocumentConflictError(
                    f"Journal daily note {row['path']} has invalid interrupted install state"
                )
            try:
                _link_at(parent_fd, temp_name, target_name)
            except FileExistsError as exc:
                if not _owns_at(parent_fd, target_name, row) or (
                    _hash_bytes(_read_at(parent_fd, target_name)) != row["desired_hash"]
                ):
                    raise vault_md.DocumentConflictError(
                        f"Journal daily note {row['path']} appeared during migration"
                    ) from exc
            _fsync_parent(parent_fd, parent_path)
            if not _owns_at(parent_fd, target_name, row) or (
                _hash_bytes(_read_at(parent_fd, target_name)) != row["desired_hash"]
            ):
                raise vault_md.DocumentConflictError(
                    f"Journal daily note {row['path']} changed during migration"
                )
            _unlink_at(parent_fd, temp_name, missing_ok=True)
            if seed_name is not None and _owns_at(parent_fd, seed_name, row):
                _unlink_at(parent_fd, seed_name, missing_ok=True)
            _fsync_parent(parent_fd, parent_path)
            row["install_seed"] = None
            row["install_seed_location"] = None
            row["installing"] = None


def _remove_stage(operation: Path) -> None:
    try:
        shutil.rmtree(operation / "stage")
    except FileNotFoundError:
        return
    _fsync_directory(operation)


def _remove_install_seeds(operation: Path) -> None:
    try:
        shutil.rmtree(operation / "installing")
    except FileNotFoundError:
        return
    _fsync_directory(operation)


def _entry_source_hash(entry) -> str:
    payload = {
        "content": entry.content or "",
        "date": entry.date,
        "id": entry.id,
        "mood": entry.mood or "",
        "tags": entry.tags or "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash_bytes(raw.encode("utf-8"))


def _desired_bytes(entry) -> bytes:
    return journal_vault.compose_migration_document(
        entry.content or "", entry.mood or "", entry.tags or ""
    ).encode("utf-8")


def _entries(db):
    from core.database import JournalEntry

    return db.query(JournalEntry).order_by(JournalEntry.date.asc()).all()


def _target_path(rel: str) -> Path:
    candidate = vault_md.root_dir()
    for part in Path(rel).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise vault_md.DocumentConflictError(f"Journal migration refuses symbolic link {rel}")
    return vault_md._safe(rel)


def migration_plan(db) -> dict:
    rows = []
    conflicts = []
    invalid_dates = []
    entries = _entries(db)
    for entry in entries:
        day = str(entry.date or "")
        rel = journal_vault._rel(day)
        if journal_vault.is_daily(rel) != day:
            invalid_dates.append(day)
            continue
        desired = _desired_bytes(entry)
        try:
            target = _target_path(rel)
        except vault_md.DocumentConflictError:
            current_hash = ""
            action = "conflict"
        else:
            if target.is_file():
                current_hash = _hash_bytes(target.read_bytes())
                action = "reuse" if current_hash == _hash_bytes(desired) else "conflict"
            elif target.exists():
                current_hash = ""
                action = "conflict"
            else:
                current_hash = ""
                action = "create"
        row = {
            "action": action,
            "date": entry.date,
            "path": rel,
            "source_hash": _entry_source_hash(entry),
            "target_hash": current_hash,
        }
        rows.append(row)
        if action == "conflict":
            conflicts.append(rel)

    count = len(entries)
    locked = bool(load_settings().get("journal_passcode"))
    return {
        "count": count,
        "locked": locked,
        "conflicts": conflicts,
        "invalid_dates": invalid_dates,
        "confirmation": f"migrate {count} journal entries to markdown",
        "privacy_warning": (
            "This creates plaintext Markdown daily notes in the configured vault. "
            "Locked Journal content requires an unlocked Journal session."
        ),
        "rows": rows,
        "source_of_truth": "database until the approved Docs cutover",
    }


def prepare(db, confirmation: str, *, locked_session_confirmed: bool = False) -> dict:
    plan = migration_plan(db)
    if confirmation != plan["confirmation"]:
        raise ValueError("journal migration confirmation does not match")
    if plan["locked"] and not locked_session_confirmed:
        raise PermissionError("unlock the Journal before preparing this migration")
    if plan["conflicts"]:
        raise ValueError("journal migration has existing-file conflicts")
    if plan["invalid_dates"]:
        raise ValueError("journal migration has invalid legacy dates")

    operation_id = uuid.uuid4().hex
    operation = _root() / operation_id
    stage = operation / "stage"
    stage.mkdir(parents=True, mode=0o700)
    try:
        manifest_rows = []
        entries = {entry.date: entry for entry in _entries(db)}
        for row in plan["rows"]:
            entry = entries[row["date"]]
            desired = _desired_bytes(entry)
            staged = stage / row["path"]
            staged.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            staged.write_bytes(desired)
            try:
                staged.chmod(0o600)
            except OSError:
                pass
            manifest_rows.append(
                {
                    **row,
                    "desired_hash": _hash_bytes(desired),
                    "installed": row["action"] == "reuse",
                    "owned_device": None,
                    "owned_inode": None,
                    "installing": None,
                    "install_seed": None,
                    "install_seed_location": None,
                    "rollback_quarantine": None,
                    "rolled_back": False,
                }
            )

        manifest = {
            "operation_id": operation_id,
            "version": 1,
            "state": "prepared",
            "locked_source": plan["locked"],
            "source_of_truth": plan["source_of_truth"],
            "rows": manifest_rows,
        }
        _atomic_json(operation / "manifest.json", manifest)
    except BaseException:
        shutil.rmtree(operation, ignore_errors=True)
        raise
    return status(operation_id)


def _verify_source(db, row: dict) -> None:
    from core.database import JournalEntry

    entry = db.query(JournalEntry).filter(JournalEntry.date == row["date"]).first()
    if entry is None or _entry_source_hash(entry) != row["source_hash"]:
        raise vault_md.DocumentConflictError(
            f"Journal entry {row['date']} changed after the migration preview"
        )


def apply(db, operation_id: str) -> dict:
    operation, manifest = _read_manifest(operation_id)
    if manifest["state"] == "applied":
        _remove_stage(operation)
        _remove_install_seeds(operation)
        return status(operation_id)
    if manifest["state"] in {"rolled_back", "rolled_back_with_conflicts"}:
        raise ValueError("journal migration was already rolled back")

    # Verify the complete operation before creating its first new file. Expected-hash writes below
    # still close the race if an external program changes a target after this preflight.
    for row in manifest["rows"]:
        _verify_source(db, row)
        staged = operation / "stage" / row["path"]
        if (
            staged.is_symlink()
            or not staged.is_file()
            or _hash_bytes(staged.read_bytes()) != row["desired_hash"]
        ):
            raise ValueError("journal migration stage failed verification")
        try:
            with _target_parent(row["path"]) as (parent_fd, target_name, parent_path):
                target_exists = _exists_at(parent_fd, target_name)
                if target_exists and not _is_file_at(parent_fd, target_name):
                    raise vault_md.DocumentConflictError(
                        f"Journal daily note {row['path']} is no longer a regular file"
                    )
                current_hash = (
                    _hash_bytes(_read_at(parent_fd, target_name)) if target_exists else ""
                )
                installing = _metadata_name(row, "installing", ".installing")
                seed = (
                    _metadata_name(row, "install_seed", ".seed")
                    if row.get("install_seed_location") == "target"
                    else None
                )
                if row["action"] == "reuse":
                    if current_hash != row["desired_hash"]:
                        raise vault_md.DocumentConflictError(
                            f"Journal daily note {row['path']} changed after preparation"
                        )
                elif current_hash:
                    if _owns_at(parent_fd, target_name, row):
                        if current_hash == row["desired_hash"]:
                            if installing is not None and _exists_at(parent_fd, installing):
                                if not _owns_at(parent_fd, installing, row) or (
                                    _hash_bytes(_read_at(parent_fd, installing))
                                    != row["desired_hash"]
                                ):
                                    raise vault_md.DocumentConflictError(
                                        f"Journal daily note {row['path']} has invalid interrupted install state"
                                    )
                                if not _detach_owned_sidecar_at(
                                    parent_fd,
                                    parent_path,
                                    installing,
                                    row,
                                    suffix=".cleanup",
                                ):
                                    raise vault_md.DocumentConflictError(
                                        f"Journal daily note {row['path']} has invalid interrupted install state"
                                    )
                            if seed is not None and _exists_at(parent_fd, seed):
                                if not _detach_owned_sidecar_at(
                                    parent_fd,
                                    parent_path,
                                    seed,
                                    row,
                                    suffix=".cleanup",
                                ):
                                    raise vault_md.DocumentConflictError(
                                        f"Journal daily note {row['path']} has invalid interrupted install seed"
                                    )
                            row["install_seed"] = None
                            row["install_seed_location"] = None
                            row["installing"] = None
                            row["installed"] = True
                        elif installing is None or not _owns_at(parent_fd, installing, row):
                            raise vault_md.DocumentConflictError(
                                f"Journal daily note {row['path']} appeared after preparation"
                            )
                    else:
                        raise vault_md.DocumentConflictError(
                            f"Journal daily note {row['path']} appeared after preparation"
                        )
                elif row.get("owned_device") is not None or row.get("owned_inode") is not None:
                    installing_owned = bool(
                        installing is not None and _owns_at(parent_fd, installing, row)
                    )
                    seed_owned = bool(seed is not None and _owns_at(parent_fd, seed, row))
                    if not installing_owned and not seed_owned:
                        raise vault_md.DocumentConflictError(
                            f"Journal daily note {row['path']} disappeared after migration started"
                        )
        except FileNotFoundError:
            if row["action"] == "reuse":
                raise vault_md.DocumentConflictError(
                    f"Journal daily note {row['path']} changed after preparation"
                )
            if row.get("owned_device") is not None or row.get("owned_inode") is not None:
                raise vault_md.DocumentConflictError(
                    f"Journal daily note {row['path']} disappeared after migration started"
                )

    for row in manifest["rows"]:
        if row["action"] == "create" and not row["installed"]:
            _install_created_row(operation, manifest, row)
            row["installed"] = True
        _atomic_json(operation / "manifest.json", manifest)

    manifest["state"] = "applied"
    _atomic_json(operation / "manifest.json", manifest)
    _remove_stage(operation)
    _remove_install_seeds(operation)
    return status(operation_id)


def rollback(operation_id: str) -> dict:
    operation, manifest = _read_manifest(operation_id)
    conflicts = []
    for row in manifest["rows"]:
        if row["action"] != "create" or row["rolled_back"]:
            continue
        try:
            target_context = _target_parent(row["path"])
            with target_context as (parent_fd, target_name, parent_path):
                installing = _metadata_name(row, "installing", ".installing")
                seed = (
                    _metadata_name(row, "install_seed", ".seed")
                    if row.get("install_seed_location") == "target"
                    else None
                )
                if installing is not None:
                    if _owns_at(parent_fd, installing, row):
                        target_was_present = _exists_at(parent_fd, target_name)
                        if target_was_present:
                            if (
                                not _owns_at(parent_fd, target_name, row)
                                or _hash_bytes(_read_at(parent_fd, target_name))
                                != row["desired_hash"]
                                or _hash_bytes(_read_at(parent_fd, installing))
                                != row["desired_hash"]
                                or not _remove_if_hash_at(
                                    operation,
                                    manifest,
                                    parent_fd,
                                    parent_path,
                                    target_name,
                                    row,
                                )
                            ):
                                conflicts.append(row["path"])
                                _atomic_json(operation / "manifest.json", manifest)
                                continue
                        if not _detach_owned_sidecar_at(
                            parent_fd,
                            parent_path,
                            installing,
                            row,
                            suffix=".rollback",
                            require_desired_hash=target_was_present,
                        ):
                            conflicts.append(row["path"])
                            _atomic_json(operation / "manifest.json", manifest)
                            continue
                        if seed is not None and _exists_at(parent_fd, seed):
                            if not _detach_owned_sidecar_at(
                                parent_fd,
                                parent_path,
                                seed,
                                row,
                                suffix=".rollback",
                                require_desired_hash=target_was_present,
                            ):
                                conflicts.append(row["path"])
                                _atomic_json(operation / "manifest.json", manifest)
                                continue
                        row["install_seed"] = None
                        row["install_seed_location"] = None
                        row["installing"] = None
                        row["rolled_back"] = True
                        _atomic_json(operation / "manifest.json", manifest)
                        continue
                    if (
                        not _exists_at(parent_fd, installing)
                        and _owns_at(parent_fd, target_name, row)
                        and _hash_bytes(_read_at(parent_fd, target_name)) == row["desired_hash"]
                    ):
                        if seed is not None and _exists_at(parent_fd, seed):
                            if not _detach_owned_sidecar_at(
                                parent_fd,
                                parent_path,
                                seed,
                                row,
                                suffix=".rollback",
                            ):
                                conflicts.append(row["path"])
                                _atomic_json(operation / "manifest.json", manifest)
                                continue
                        row["install_seed"] = None
                        row["install_seed_location"] = None
                        row["installing"] = None
                    elif (
                        not _exists_at(parent_fd, installing)
                        and seed is not None
                        and _owns_at(parent_fd, seed, row)
                        and not _exists_at(parent_fd, target_name)
                    ):
                        if not _detach_owned_sidecar_at(
                            parent_fd,
                            parent_path,
                            seed,
                            row,
                            suffix=".rollback",
                        ):
                            conflicts.append(row["path"])
                            _atomic_json(operation / "manifest.json", manifest)
                            continue
                        row["install_seed"] = None
                        row["install_seed_location"] = None
                        row["installing"] = None
                        row["rolled_back"] = True
                        _atomic_json(operation / "manifest.json", manifest)
                        continue
                    elif (
                        not _exists_at(parent_fd, installing)
                        and seed is None
                        and not _exists_at(parent_fd, target_name)
                        and row.get("owned_device") is None
                        and row.get("owned_inode") is None
                    ):
                        row["installing"] = None
                        row["rolled_back"] = True
                        _atomic_json(operation / "manifest.json", manifest)
                        continue
                    else:
                        conflicts.append(row["path"])
                        _atomic_json(operation / "manifest.json", manifest)
                        continue
                if not row["installed"]:
                    if _owns_at(parent_fd, target_name, row) and (
                        _hash_bytes(_read_at(parent_fd, target_name)) == row["desired_hash"]
                    ):
                        row["installed"] = True
                    else:
                        row["rolled_back"] = True
                        _atomic_json(operation / "manifest.json", manifest)
                        continue
                quarantine = _metadata_name(row, "rollback_quarantine", ".rollback")
                if quarantine is not None and _remove_if_hash_at(
                    operation, manifest, parent_fd, parent_path, target_name, row
                ):
                    row["rolled_back"] = True
                elif not _exists_at(parent_fd, target_name):
                    row["rolled_back"] = True
                elif _is_file_at(parent_fd, target_name) and _remove_if_hash_at(
                    operation, manifest, parent_fd, parent_path, target_name, row
                ):
                    row["rolled_back"] = True
                else:
                    conflicts.append(row["path"])
                _atomic_json(operation / "manifest.json", manifest)
        except FileNotFoundError:
            if not row["installed"]:
                row["rolled_back"] = True
                _atomic_json(operation / "manifest.json", manifest)
            else:
                conflicts.append(row["path"])
                _atomic_json(operation / "manifest.json", manifest)

    manifest["state"] = "rolled_back_with_conflicts" if conflicts else "rolled_back"
    manifest["rollback_conflicts"] = conflicts
    _atomic_json(operation / "manifest.json", manifest)
    _remove_stage(operation)
    if not conflicts:
        _remove_install_seeds(operation)
    return status(operation_id)


def status(operation_id: str) -> dict:
    _, manifest = _read_manifest(operation_id)
    return {
        "operation_id": operation_id,
        "state": manifest["state"],
        "count": len(manifest["rows"]),
        "installed": sum(
            1 for row in manifest["rows"] if row["installed"] and not row["rolled_back"]
        ),
        "rollback_conflicts": manifest.get("rollback_conflicts", []),
        "source_of_truth": manifest["source_of_truth"],
    }
