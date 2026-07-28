"""Restart-safe local Files operations with verified copy/move and bounded undo."""

from __future__ import annotations

import contextvars
import ctypes
import errno
import hashlib
import ipaddress
import json
import os
import shutil
import stat
import sys
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy.exc import IntegrityError

from core.database import (
    FileComment,
    FileOperation,
    FileOperationPathClaim,
    FileOperationSourceClaim,
    FileTag,
    FileVersion,
    IndexChunk,
    OfflineFile,
    Share,
    StorageLocation,
    TrashItem,
    canonical_local_physical_claim_path,
)
from core.database import (
    local_claim_case_insensitive as _local_claim_case_insensitive,
)
from core.settings import data_dir
from services import fileversions, internal_paths, storage_backends, storage_locations, trash

CHUNK_SIZE = 1024 * 1024
FINAL_STATES = frozenset({"completed", "failed", "cancelled", "undone"})
ACTIONS = frozenset({"copy", "move", "rename", "delete", "restore"})
DIRECT_MUTATION_ACTION = "_direct_mutation"
SOURCE_MUTATION_ACTIONS = frozenset({"move", "rename", "delete"})
METADATA_MODELS = (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk)
METADATA_MODELS_BY_NAME = {model.__name__: model for model in METADATA_MODELS}
_LOCAL_ROOTS: contextvars.ContextVar[tuple[Path, ...]] = contextvars.ContextVar(
    "alles_file_operation_local_roots", default=()
)


class FileOperationError(RuntimeError):
    pass


class _SourceConflictPublished(FileOperationError):
    """A detached replacement was safely published at a visible local path."""

    def __init__(self, path: str, conflict_fingerprint: dict):
        self.path = path
        self.conflict_fingerprint = conflict_fingerprint
        super().__init__(f"source changed; detached replacement preserved at {path}")


class _SurvivorRecovered(FileOperationError):
    """A destructive attempt was rolled back to a verified visible copy."""

    def __init__(self, path: str, *, undo: bool):
        self.path = path
        self.undo = undo
        super().__init__(f"concurrent change detected; verified bytes recovered at {path}")


class _RestoreRolledBack(FileOperationError):
    """A restore kept its verified bytes and metadata in Trash after a race."""

    def __init__(self):
        super().__init__("concurrent change detected; restore was rolled back to Trash")


def _normal(value: str) -> str:
    try:
        path = storage_locations.normalize_path(value)
    except ValueError as exc:
        raise FileOperationError(str(exc)) from exc
    if not path:
        raise FileOperationError("path required")
    return path


def _location(db, location_id: str) -> StorageLocation:
    return storage_locations.require_browsable(db, location_id)


def _absolute(row: StorageLocation, relative: str) -> Path:
    if row.kind != "local":
        raise FileOperationError("storage item is not local")
    root = storage_locations.local_root(row)
    path = root / _normal(relative)
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise FileOperationError("symbolic links are not supported")
    roots = _LOCAL_ROOTS.get()
    if root not in roots:
        _LOCAL_ROOTS.set((*roots[-15:], root))
    return path


def _registered_root(path: Path) -> Path | None:
    absolute = type(path)(os.path.abspath(os.fspath(path)))
    matches = []
    for root in _LOCAL_ROOTS.get():
        try:
            absolute.relative_to(root)
        except ValueError:
            continue
        matches.append(root)
    return max(matches, key=lambda item: len(item.parts), default=None)


@contextmanager
def _anchored_parent(path: Path, *, create: bool = False):
    """Hold the real parent directory open while one local path is accessed."""
    root = _registered_root(path)
    if root is None or os.name == "nt":
        current = root
        if current is not None:
            for part in Path(os.path.abspath(path)).relative_to(root).parts[:-1]:
                current = current / part
                if current.is_symlink():
                    raise FileOperationError("symbolic links are not supported")
            if create:
                path.parent.mkdir(parents=True, exist_ok=True)
        yield None, os.fspath(path)
        return
    relative = type(path)(os.path.abspath(os.fspath(path))).relative_to(root)
    if not relative.parts:
        raise FileOperationError("storage root cannot be used as a file item")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError as exc:
        raise FileOperationError("storage root is unavailable or symbolic") from exc
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
                raise FileOperationError("symbolic links are not supported") from exc
            os.close(descriptor)
            descriptor = child
        yield descriptor, relative.parts[-1]
    finally:
        os.close(descriptor)


def _open_exact(path: Path, flags: int, mode: int = 0o600, *, create_parent: bool = False) -> int:
    flags |= getattr(os, "O_NOFOLLOW", 0)
    with _anchored_parent(path, create=create_parent) as (parent_fd, name):
        try:
            if parent_fd is None:
                return os.open(name, flags, mode)
            return os.open(name, flags, mode, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise FileOperationError("symbolic links are not supported") from exc
            raise


def _mkdir_parent(path: Path) -> None:
    with _anchored_parent(path, create=True):
        return


def _copy_file_descriptors(source_fd: int, destination_fd: int) -> None:
    while True:
        chunk = os.read(source_fd, CHUNK_SIZE)
        if not chunk:
            break
        view = memoryview(chunk)
        while view:
            written = os.write(destination_fd, view)
            view = view[written:]


def _copy_directory_descriptor(source_fd: int, destination_fd: int) -> None:
    entries = sorted(os.scandir(source_fd), key=lambda item: item.name)
    for entry in entries:
        if entry.is_symlink():
            raise FileOperationError("symbolic links are not supported")
        source_child = os.open(
            entry.name,
            os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=source_fd,
        )
        try:
            identity = os.fstat(source_child)
            if stat.S_ISDIR(identity.st_mode):
                os.mkdir(entry.name, stat.S_IMODE(identity.st_mode), dir_fd=destination_fd)
                destination_child = os.open(
                    entry.name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=destination_fd,
                )
                try:
                    _copy_directory_descriptor(source_child, destination_child)
                    os.fsync(destination_child)
                finally:
                    os.close(destination_child)
            elif stat.S_ISREG(identity.st_mode):
                destination_child = os.open(
                    entry.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    stat.S_IMODE(identity.st_mode),
                    dir_fd=destination_fd,
                )
                try:
                    _copy_file_descriptors(source_child, destination_child)
                    os.fsync(destination_child)
                finally:
                    os.close(destination_child)
            else:
                raise FileOperationError("unsupported file type")
        finally:
            os.close(source_child)


def _copy_exact(source: Path, destination: Path) -> None:
    source_fd = _open_exact(source, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    try:
        identity = os.fstat(source_fd)
        if stat.S_ISREG(identity.st_mode):
            destination_fd = _open_exact(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                stat.S_IMODE(identity.st_mode),
                create_parent=True,
            )
            try:
                _copy_file_descriptors(source_fd, destination_fd)
                os.fsync(destination_fd)
            finally:
                os.close(destination_fd)
            return
        if not stat.S_ISDIR(identity.st_mode):
            raise FileOperationError("unsupported file type")
        with _anchored_parent(destination, create=True) as (parent_fd, name):
            if parent_fd is None:
                os.mkdir(name, stat.S_IMODE(identity.st_mode))
                destination_fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                )
            else:
                os.mkdir(name, stat.S_IMODE(identity.st_mode), dir_fd=parent_fd)
                destination_fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
        try:
            _copy_directory_descriptor(source_fd, destination_fd)
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)


def _require_managed(row: StorageLocation) -> None:
    if row.access != "managed":
        raise FileOperationError("storage location is read-only")


def _file_descriptor_hash(descriptor: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, CHUNK_SIZE)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _file_hash(path: Path) -> tuple[int, str]:
    descriptor = _open_exact(path, os.O_RDONLY)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise FileOperationError("unsupported file type")
        return _file_descriptor_hash(descriptor)
    finally:
        os.close(descriptor)


def fingerprint(path: Path) -> dict:
    """Return a stable content fingerprint without following external links."""
    try:
        root_fd = _open_exact(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError as exc:
        raise FileOperationError("source not found") from exc
    root_identity = os.fstat(root_fd)
    if stat.S_ISREG(root_identity.st_mode):
        try:
            size, checksum = _file_descriptor_hash(root_fd)
            return {"kind": "file", "size": size, "count": 1, "checksum": checksum}
        finally:
            os.close(root_fd)
    if not stat.S_ISDIR(root_identity.st_mode):
        os.close(root_fd)
        raise FileOperationError("source not found")
    digest = hashlib.sha256()
    total = 0
    count = 0

    def add_record(record: list[str | int]) -> None:
        payload = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)

    def visit(directory_fd: int, prefix: str = "") -> None:
        nonlocal total, count
        for entry in sorted(os.scandir(directory_fd), key=lambda item: item.name):
            if entry.is_symlink():
                raise FileOperationError("symbolic links are not supported")
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            child_fd = os.open(
                entry.name,
                os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            try:
                identity = os.fstat(child_fd)
                if stat.S_ISDIR(identity.st_mode):
                    add_record(["dir", relative])
                    visit(child_fd, relative)
                elif stat.S_ISREG(identity.st_mode):
                    size, checksum = _file_descriptor_hash(child_fd)
                    total += size
                    count += 1
                    add_record(["file", relative, size, checksum])
                else:
                    raise FileOperationError("unsupported file type")
            finally:
                os.close(child_fd)

    try:
        visit(root_fd)
        return {
            "kind": "dir",
            "size": total,
            "count": count,
            "checksum": digest.hexdigest(),
        }
    finally:
        os.close(root_fd)


def _same(path: Path, expected: dict) -> bool:
    try:
        return fingerprint(path) == expected
    except (FileOperationError, OSError):
        return False


def _partial_copy_path(destination: Path, operation_id: str) -> Path:
    try:
        return internal_paths.operation_sibling(destination, operation_id, ".partial")
    except ValueError as exc:
        raise FileOperationError(str(exc)) from exc


def _prepare_verified_copy(
    source: Path,
    destination: Path,
    operation_id: str,
    *,
    expected: dict | None = None,
) -> tuple[dict, Path]:
    source_resolved = source.resolve(strict=False)
    destination_resolved = destination.resolve(strict=False)
    if source_resolved == destination_resolved or (
        source.is_dir() and source_resolved in destination_resolved.parents
    ):
        raise FileOperationError("destination must be outside the source")
    expected = expected or fingerprint(source)
    if fingerprint(source) != expected:
        raise FileOperationError("source changed during copy")
    if destination.exists() or destination.is_symlink():
        raise FileOperationError("destination already exists")
    _mkdir_parent(destination)
    temp = _partial_copy_path(destination, operation_id)
    if temp.exists() or temp.is_symlink():
        if temp.is_dir():
            _remove(temp)
        else:
            _remove(temp)
    try:
        _copy_exact(source, temp)
        if fingerprint(temp) != expected or fingerprint(source) != expected:
            raise FileOperationError("source changed during copy")
        return expected, temp
    except Exception:
        if temp.is_dir():
            try:
                _remove(temp)
            except FileNotFoundError:
                pass
        else:
            try:
                _remove(temp)
            except FileNotFoundError:
                pass
        raise


def _publish_verified_copy(temp: Path, destination: Path, expected: dict) -> str:
    publication_identity = _local_publication_identity(temp)
    _rename_no_replace(temp, destination)
    if (
        _local_publication_identity(destination) != publication_identity
        or fingerprint(destination) != expected
    ):
        raise FileOperationError("destination verification failed")
    return publication_identity


def _local_publication_identity(path: Path) -> str:
    """Bind a local publication to every inode moved from its staging path."""
    digest = hashlib.sha256()
    root_fd = _open_exact(Path(path), os.O_RDONLY)

    def add(identity, relative: str, kind: str) -> None:
        payload = json.dumps(
            [
                kind,
                relative,
                int(identity.st_dev),
                int(identity.st_ino),
                int(identity.st_size),
                int(identity.st_mtime_ns),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)

    def visit(directory_fd: int, prefix: str = "") -> None:
        for entry in sorted(os.scandir(directory_fd), key=lambda item: item.name):
            if entry.is_symlink():
                raise FileOperationError("symbolic links are not supported")
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            child_fd = os.open(
                entry.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            try:
                identity = os.fstat(child_fd)
                if stat.S_ISDIR(identity.st_mode):
                    add(identity, relative, "dir")
                    visit(child_fd, relative)
                elif stat.S_ISREG(identity.st_mode):
                    add(identity, relative, "file")
                else:
                    raise FileOperationError("unsupported file type")
            finally:
                os.close(child_fd)

    try:
        identity = os.fstat(root_fd)
        if stat.S_ISDIR(identity.st_mode):
            add(identity, ".", "dir")
            visit(root_fd)
        elif stat.S_ISREG(identity.st_mode):
            add(identity, ".", "file")
        else:
            raise FileOperationError("local publication identity is invalid")
        return digest.hexdigest()
    finally:
        os.close(root_fd)


def _copy_verified(source: Path, destination: Path, operation_id: str) -> dict:
    temp = _partial_copy_path(destination, operation_id)
    try:
        expected, temp = _prepare_verified_copy(source, destination, operation_id)
        _publish_verified_copy(temp, destination, expected)
        return expected
    except Exception:
        try:
            _remove(temp)
        except FileNotFoundError:
            pass
        raise


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish one path without replacing a concurrent destination."""
    if os.name == "nt":
        try:
            os.rename(source, destination)
        except FileExistsError as exc:
            raise FileOperationError("destination already exists") from exc
        return
    libc = ctypes.CDLL(None, use_errno=True)
    result = -1
    supported = False
    with (
        _anchored_parent(source) as (source_parent, source_name),
        _anchored_parent(destination, create=True) as (destination_parent, destination_name),
    ):
        source_dir_fd = source_parent if source_parent is not None else -100
        destination_dir_fd = destination_parent if destination_parent is not None else -100
        if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
            renameatx_np = libc.renameatx_np
            renameatx_np.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameatx_np.restype = ctypes.c_int
            result = renameatx_np(
                source_dir_fd,
                os.fsencode(source_name),
                destination_dir_fd,
                os.fsencode(destination_name),
                0x00000004,
            )
            supported = True
        elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            renameat2 = libc.renameat2
            renameat2.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameat2.restype = ctypes.c_int
            result = renameat2(
                source_dir_fd,
                os.fsencode(source_name),
                destination_dir_fd,
                os.fsencode(destination_name),
                0x00000001,
            )
            supported = True
        elif source_parent is not None and destination_parent is not None:
            try:
                os.link(
                    source_name,
                    destination_name,
                    src_dir_fd=source_parent,
                    dst_dir_fd=destination_parent,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise FileOperationError("destination already exists") from exc
            os.unlink(source_name, dir_fd=source_parent)
            return
    if supported:
        if result == 0:
            return
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileOperationError("destination already exists")
        raise OSError(error, os.strerror(error), str(destination))
    if _registered_root(source) is not None or _registered_root(destination) is not None:
        raise FileOperationError("atomic local publication is unavailable on this system")
    if source.is_file():
        try:
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise FileOperationError("destination already exists") from exc
        source.unlink()
        return
    raise FileOperationError("atomic directory publication is unavailable on this system")


def _workspace(row: FileOperation) -> Path:
    root = data_dir() / "storage-operations" / row.id
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _clean_workspace(row: FileOperation) -> None:
    shutil.rmtree(_workspace(row), ignore_errors=True)


def _materialize(location, path: str, target: Path) -> dict:
    if location.kind == "local":
        _absolute(location, path)
    try:
        return storage_backends.materialize(location, path, target, resume=True)
    except storage_backends.StorageBackendError as exc:
        raise FileOperationError(str(exc)) from exc


def _remote_or_cross(source_location, destination_location=None) -> bool:
    return source_location.kind != "local" or (
        destination_location is not None
        and (destination_location.kind != "local" or destination_location.id != source_location.id)
    )


def _remove(path: Path) -> None:
    def remove_tree(parent_fd: int | None, name: str) -> None:
        if parent_fd is None:
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
        else:
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        try:
            for entry in list(os.scandir(descriptor)):
                if entry.is_symlink():
                    os.unlink(entry.name, dir_fd=descriptor)
                elif entry.is_dir(follow_symlinks=False):
                    remove_tree(descriptor, entry.name)
                else:
                    os.unlink(entry.name, dir_fd=descriptor)
        finally:
            os.close(descriptor)
        if parent_fd is None:
            os.rmdir(name)
        else:
            os.rmdir(name, dir_fd=parent_fd)

    with _anchored_parent(path) as (parent_fd, name):
        try:
            identity = (
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if parent_fd is not None
                else os.stat(name, follow_symlinks=False)
            )
        except FileNotFoundError:
            raise
        if stat.S_ISLNK(identity.st_mode):
            raise FileOperationError("symbolic links are not supported")
        if stat.S_ISDIR(identity.st_mode):
            remove_tree(parent_fd, name)
        elif parent_fd is None:
            os.unlink(name)
        else:
            os.unlink(name, dir_fd=parent_fd)


def _quarantine_path(source: Path, operation_id: str) -> Path:
    try:
        return internal_paths.operation_sibling(source, operation_id, ".quarantine")
    except ValueError as exc:
        raise FileOperationError(str(exc)) from exc


def _quarantine_verified(source: Path, expected: dict, operation_id: str) -> Path:
    """Atomically detach the verified source so later path changes cannot be removed."""
    quarantine = _quarantine_path(source, operation_id)
    if quarantine.exists() or quarantine.is_symlink():
        if not _same(quarantine, expected):
            raise FileOperationError("quarantined source changed during operation")
        return quarantine
    if not source.exists():
        raise FileOperationError("source not found")
    _rename_no_replace(source, quarantine)
    if _same(quarantine, expected):
        return quarantine
    if not source.exists() and not source.is_symlink():
        _rename_no_replace(quarantine, source)
    raise FileOperationError("source changed during operation")


def _same_local_path_publication_identity(path: Path, stored: dict | None) -> bool:
    """Verify a detached local path is still the exact published inode/tree."""
    if not isinstance(stored, dict) or path.is_symlink():
        return False
    try:
        current = _local_publication_identity(path)
    except (OSError, FileOperationError):
        return False
    expected = str(stored.get("local_publication_identity") or "")
    return bool(expected and current == expected)


def _quarantine_verified_publication(
    source: Path,
    expected: dict,
    stored: dict | None,
    operation_id: str,
) -> Path:
    """Detach only the local object/tree whose publication identity we recorded."""
    detached = _quarantine_verified(source, expected, operation_id)
    if _same_local_path_publication_identity(detached, stored):
        return detached
    if not (source.exists() or source.is_symlink()):
        _rename_no_replace(detached, source)
    raise FileOperationError("copy destination identity changed; undo stopped")


def _source_conflict_relative_path(row: FileOperation, source: Path) -> str:
    conflict = internal_paths.bounded_named_child(
        source.parent,
        source.name,
        prefix=f"alles-recovered-{row.id}",
    )
    parent = row.source_path.rpartition("/")[0]
    return f"{parent}/{conflict.name}" if parent else conflict.name


def _prepare_source_conflict(
    db,
    row: FileOperation,
    details: dict,
    path: str,
    conflict_fingerprint: dict,
) -> None:
    details["source_conflict_path"] = path
    details["source_conflict_fingerprint"] = conflict_fingerprint
    details["source_conflict_pending"] = True
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()


def _finish_pending_source_conflict(
    db,
    row: FileOperation,
    details: dict,
    source: Path,
) -> None:
    path = str(details.get("source_conflict_path") or "")
    expected = details.get("source_conflict_fingerprint")
    if not path or not isinstance(expected, dict):
        raise FileOperationError("source conflict recovery state is invalid")
    location = _location(db, row.source_location_id)
    conflict = _absolute(location, path)
    quarantine = _quarantine_path(source, row.id)
    quarantine_exists = quarantine.exists() or quarantine.is_symlink()
    conflict_exists = conflict.exists() or conflict.is_symlink()
    if quarantine_exists:
        if conflict_exists:
            raise FileOperationError(
                f"source conflict path {path} is occupied; quarantined replacement was preserved"
            )
        _mkdir_parent(conflict)
        _rename_no_replace(quarantine, conflict)
        conflict_exists = True
    if not conflict_exists or not _same(conflict, expected):
        raise FileOperationError("source conflict recovery copy changed; operation remains locked")
    raise _SourceConflictPublished(path, expected)


def _quarantine_operation_source(
    db,
    row: FileOperation,
    details: dict,
    source: Path,
    expected: dict,
) -> Path:
    """Detach one source or publish any raced replacement without hiding bytes."""
    if details.get("source_conflict_pending"):
        _finish_pending_source_conflict(db, row, details, source)
    try:
        return _quarantine_verified(source, expected, row.id)
    except FileOperationError:
        quarantine = _quarantine_path(source, row.id)
        if quarantine.exists() or quarantine.is_symlink():
            if _same(quarantine, expected):
                raise
            conflict_fingerprint = fingerprint(quarantine)
            path = (
                row.source_path
                if not (source.exists() or source.is_symlink())
                else _source_conflict_relative_path(row, source)
            )
            _prepare_source_conflict(db, row, details, path, conflict_fingerprint)
            _finish_pending_source_conflict(db, row, details, source)
        if (source.exists() or source.is_symlink()) and not _same(source, expected):
            conflict_fingerprint = fingerprint(source)
            _prepare_source_conflict(
                db,
                row,
                details,
                row.source_path,
                conflict_fingerprint,
            )
            _finish_pending_source_conflict(db, row, details, source)
        raise


def _restore_detached(detached: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileOperationError("destination changed while restoring a safe copy")
    _rename_no_replace(detached, destination)


def _recover_local_operation_quarantine_for_undo(
    db,
    row: FileOperation,
    details: dict,
    source: Path,
    expected: dict,
) -> bool:
    """Reconcile a verified source detached around its ownership commit."""
    recovery_key = "undo_source_quarantine_recovery_started"
    hold_identity_key = "undo_source_quarantine_hold_identity"
    recovery_started = bool(details.get(recovery_key))
    quarantine = _quarantine_path(source, row.id)
    cleanup = _quarantine_path(source, f"undo-clean-{row.id}")
    quarantine_exists = quarantine.exists() or quarantine.is_symlink()
    cleanup_exists = cleanup.exists() or cleanup.is_symlink()
    if quarantine_exists and cleanup_exists:
        hold_identity = str(details.get(hold_identity_key) or "")
        if (
            source.exists()
            or source.is_symlink()
            or not hold_identity
            or not _same(cleanup, expected)
            or not _same(quarantine, expected)
            or _local_publication_identity(quarantine) != hold_identity
        ):
            raise FileOperationError("multiple source recovery copies need owner attention")
        _remove(cleanup)
        _restore_detached(quarantine, source)
        if not _same(source, expected) or _local_publication_identity(source) != hold_identity:
            raise FileOperationError("source recovery verification failed")
        details.pop(hold_identity_key, None)
        return True
    detached = cleanup if cleanup_exists else quarantine
    if not (quarantine_exists or cleanup_exists):
        return recovery_started
    if not _same(detached, expected):
        raise FileOperationError("source recovery copy changed; undo stopped")
    if not recovery_started:
        details[recovery_key] = True
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        recovery_started = True
    if not (source.exists() or source.is_symlink()):
        hold_identity = str(details.get(hold_identity_key) or "")
        if hold_identity and (
            detached != quarantine or _local_publication_identity(detached) != hold_identity
        ):
            raise FileOperationError("source recovery copy identity changed; undo stopped")
        _mkdir_parent(source)
        _restore_detached(detached, source)
        if not _same(source, expected) or (
            hold_identity and _local_publication_identity(source) != hold_identity
        ):
            raise FileOperationError("source recovery verification failed")
        details.pop(hold_identity_key, None)
        return True
    if not _same(source, expected):
        raise FileOperationError("source changed; detached recovery copy was preserved")
    if detached == quarantine:
        _rename_no_replace(quarantine, cleanup)
        detached = cleanup
    if not _same(source, expected) or not _same(detached, expected):
        if not (quarantine.exists() or quarantine.is_symlink()):
            _restore_detached(detached, quarantine)
        raise FileOperationError("source changed; detached recovery copy was preserved")
    hold_identity = _local_publication_identity(source)
    held_source = _quarantine_verified(source, expected, row.id)
    if _local_publication_identity(held_source) != hold_identity:
        if not (source.exists() or source.is_symlink()):
            _restore_detached(held_source, source)
        raise FileOperationError("source identity changed while preparing recovery cleanup")
    details[hold_identity_key] = hold_identity
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()
    if not _same(detached, expected) or _local_publication_identity(held_source) != hold_identity:
        raise FileOperationError("source changed; detached recovery copy was preserved")
    _remove(detached)
    _restore_detached(held_source, source)
    if not _same(source, expected) or _local_publication_identity(source) != hold_identity:
        raise FileOperationError("source changed while cleaning its recovery copy")
    details.pop(hold_identity_key, None)
    return True


def _require_run_access(db, row: FileOperation) -> None:
    source = _location(db, row.source_location_id)
    destination = _location(db, row.destination_location_id or row.source_location_id)
    if row.action == "copy":
        _require_managed(destination)
    elif row.action == "move":
        _require_managed(source)
        _require_managed(destination)
    elif row.action in {"rename", "delete", "restore"}:
        _require_managed(source)


def _require_undo_access(source, destination, details: dict) -> None:
    action = details.get("undo")
    if action == "remove_copy":
        _require_managed(destination)
    elif action in {"move_back", "rename_back"}:
        _require_managed(source)
        _require_managed(destination)
    elif action == "restore_trash":
        _require_managed(source)
    elif action == "delete_restored":
        _require_managed(destination)


def _mapped_path(path: str, source: str, destination: str) -> str:
    if path == source:
        return destination
    return f"{destination}{path[len(source) :]}"


def _metadata_identity(model, record) -> str | None:
    raw = str(record.normalized_path or "")
    if not raw and model in {FileTag, FileComment, FileVersion}:
        raw = str(record.path or "")
    elif not raw and model in {Share, IndexChunk}:
        raw = str(record.ref or "")
    if not raw:
        return None
    try:
        return _normal(raw)
    except FileOperationError:
        return None


def _rekey_metadata(
    db,
    source_location_id: str,
    source_path: str,
    destination_location_id: str,
    destination_path: str,
) -> None:
    """Move live location-scoped Files identity with its bytes, including descendants."""
    source = _normal(source_path)
    destination = _normal(destination_path)
    models = (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk)
    for model in models:
        query = db.query(model).filter(model.location_id == source_location_id)
        for record in query.all():
            if model is Share and record.kind not in {"file", "folder"}:
                continue
            if model is IndexChunk and record.kind != "file":
                continue
            identity = _metadata_identity(model, record)
            if identity is None:
                continue
            if identity != source and not identity.startswith(f"{source}/"):
                continue
            moved = _mapped_path(identity, source, destination)
            record.location_id = destination_location_id
            record.normalized_path = moved
            if hasattr(record, "path"):
                record.path = moved
            if hasattr(record, "ref"):
                record.ref = moved


def _live_metadata_records(db, location_id: str, path: str):
    source = _normal(path)
    for model in METADATA_MODELS:
        query = db.query(model).filter(model.location_id == location_id)
        for record in query.all():
            if model is Share and record.kind not in {"file", "folder"}:
                continue
            if model is IndexChunk and record.kind != "file":
                continue
            identity = _metadata_identity(model, record)
            if identity is None:
                continue
            if identity == source or identity.startswith(f"{source}/"):
                yield model, record


def _encode_metadata_value(value):
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    return value


def _decode_metadata_value(value):
    if isinstance(value, dict) and set(value) == {"datetime"}:
        return datetime.fromisoformat(value["datetime"])
    return value


def _snapshot_live_metadata(db, location_id: str, path: str) -> list[dict]:
    snapshot = []
    for model, record in list(_live_metadata_records(db, location_id, path)):
        values = {
            column.name: _encode_metadata_value(getattr(record, column.name))
            for column in model.__table__.columns
        }
        snapshot.append({"model": model.__name__, "values": values})
        db.delete(record)
    db.flush()
    return snapshot


def _trash_metadata(item: TrashItem | None) -> tuple[dict, list[dict]]:
    if item is None:
        return {}, []
    try:
        payload = json.loads(item.payload or "{}")
    except (TypeError, ValueError):
        payload = {}
    snapshot = payload.get("metadata_snapshot")
    return payload, snapshot if isinstance(snapshot, list) else []


def _detach_live_metadata_to_trash(db, item: TrashItem, location_id: str, path: str) -> None:
    payload, snapshot = _trash_metadata(item)
    if snapshot or "metadata_snapshot" in payload:
        return
    payload["metadata_root"] = _normal(path)
    payload["metadata_snapshot"] = _snapshot_live_metadata(db, location_id, path)
    item.payload = json.dumps(payload, sort_keys=True)
    db.flush()


def _rebased_metadata_path(value: str, source: str, destination: str) -> str:
    if value == source:
        return destination
    if value.startswith(f"{source}/"):
        return f"{destination}{value[len(source) :]}"
    return value


def _restore_trash_metadata(
    db,
    item: TrashItem | None,
    location_id: str,
    destination_path: str,
) -> None:
    payload, snapshot = _trash_metadata(item)
    if not snapshot:
        return
    destination = _normal(destination_path)
    _ensure_metadata_destination_clear(db, location_id, destination)
    source = str(payload.get("metadata_root") or item.normalized_path or item.ref)
    for entry in snapshot:
        model = METADATA_MODELS_BY_NAME.get(str(entry.get("model") or ""))
        raw_values = entry.get("values")
        if model is None or not isinstance(raw_values, dict):
            raise FileOperationError("trashed metadata is invalid")
        values = {key: _decode_metadata_value(value) for key, value in raw_values.items()}
        values["location_id"] = location_id
        for key in ("normalized_path", "path", "ref"):
            if key in values and isinstance(values[key], str):
                values[key] = _rebased_metadata_path(values[key], source, destination)
        db.add(model(**values))
    db.flush()
    payload.pop("metadata_snapshot", None)
    payload.pop("metadata_root", None)
    item.payload = json.dumps(payload, sort_keys=True)


def _ensure_trash_metadata_destination_clear(
    db,
    item: TrashItem | None,
    location_id: str,
    destination_path: str,
) -> None:
    _payload, snapshot = _trash_metadata(item)
    if snapshot:
        _ensure_metadata_destination_clear(db, location_id, destination_path)


def discard_trash_metadata(db, item: TrashItem) -> None:
    """Release external metadata assets when a trash copy is permanently purged."""
    _payload, snapshot = _trash_metadata(item)
    stored_versions = set()
    cache_names = set()
    share_tokens = set()
    for entry in snapshot:
        values = entry.get("values") if isinstance(entry, dict) else None
        if not isinstance(values, dict):
            continue
        if entry.get("model") == "FileVersion" and values.get("stored"):
            stored_versions.add(str(values["stored"]))
        elif entry.get("model") == "OfflineFile" and values.get("cache_name"):
            cache_names.add(str(values["cache_name"]))
        elif entry.get("model") == "Share" and values.get("token"):
            share_tokens.add(str(values["token"]))
    for stored in stored_versions:
        referenced_by_trash = False
        for other in db.query(TrashItem).all():
            if other.id == item.id:
                continue
            _other_payload, other_snapshot = _trash_metadata(other)
            if any(
                isinstance(entry, dict)
                and entry.get("model") == "FileVersion"
                and isinstance(entry.get("values"), dict)
                and str(entry["values"].get("stored") or "") == stored
                for entry in other_snapshot
            ):
                referenced_by_trash = True
                break
        if (
            Path(stored).name == stored
            and db.query(FileVersion).filter_by(stored=stored).first() is None
            and not referenced_by_trash
        ):
            (fileversions.versions_dir() / stored).unlink(missing_ok=True)
    if cache_names:
        from services import offline_files

        for cache_name in cache_names:
            if db.query(OfflineFile).filter_by(cache_name=cache_name).first() is None:
                offline_files._remove_cache_entry(  # noqa: SLF001 - same service boundary
                    offline_files._cache_path(cache_name)  # noqa: SLF001
                )
    if share_tokens:
        from services import share as share_service

        for token in share_tokens:
            if db.query(Share).filter_by(token=token).first() is None:
                share_service.revoke_grants(token)


def _purge_live_metadata(db, location_id: str, path: str) -> None:
    """Remove every live Files identity after a verified delete keeps its trash copy."""
    source = _normal(path)
    # FileVersion owns deduplicated blobs outside the database. Let that service
    # remove rows and then unlink only blobs that no remaining version references.
    fileversions.delete_for_path(db, source, location_id)
    for model, record in list(_live_metadata_records(db, location_id, source)):
        if model is FileVersion:
            continue
        if model is OfflineFile:
            from services import offline_files

            offline_files._remove_cache_entry(  # noqa: SLF001 - same service boundary
                offline_files._cache_path(record.cache_name)  # noqa: SLF001
            )
        if model is Share:
            from services import share as share_service

            share_service.revoke_grants(record.token)
        db.delete(record)
    db.flush()


def purge_live_metadata(db, location_id: str, path: str) -> None:
    """Public deletion boundary for routes that already preserved recoverable bytes."""
    _purge_live_metadata(db, location_id, path)
    db.commit()


def _ensure_metadata_destination_clear(db, location_id: str, path: str) -> None:
    """Reject stale destination identities before moving any bytes."""
    destination = _normal(path)
    models = (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk)
    for model in models:
        query = db.query(model).filter(model.location_id == location_id)
        for record in query.all():
            if model is Share and record.kind not in {"file", "folder"}:
                continue
            if model is IndexChunk and record.kind != "file":
                continue
            identity = _metadata_identity(model, record)
            if identity is None:
                continue
            if identity == destination or identity.startswith(f"{destination}/"):
                raise FileOperationError("destination metadata already exists")


def _validate_destination(
    source_location_id: str,
    source_path: str,
    destination_location_id: str,
    destination_path: str,
) -> None:
    if source_location_id != destination_location_id:
        return
    if destination_path == source_path or destination_path.startswith(f"{source_path}/"):
        raise FileOperationError("destination must be outside the source")


def _validate_local_physical_destination(
    source_location,
    source_path: str,
    destination_location,
    destination_path: str,
) -> None:
    """Reject local aliases and nested roots that resolve into the source tree."""
    if source_location.kind != "local" or destination_location.kind != "local":
        return
    source = _absolute(source_location, source_path).resolve(strict=False)
    destination = _absolute(destination_location, destination_path).resolve(strict=False)
    if source == destination or (source.is_dir() and source in destination.parents):
        raise FileOperationError("destination must be outside the source")


def _canonical_remote_claim_path(*values: str) -> str:
    parts: list[str] = []
    for value in values:
        for part in unicodedata.normalize("NFC", str(value or "")).split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
    return "/".join(parts)


def _webdav_source_claim_identity(location, path: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(str(location.endpoint or "").strip())
        scheme = parsed.scheme.casefold()
        raw_host = parsed.hostname or ""
        try:
            address = ipaddress.ip_address(raw_host)
            host = address.compressed.casefold()
            rendered_host = f"[{host}]" if address.version == 6 else host
        except ValueError:
            host = raw_host.encode("idna").decode("ascii").removesuffix(".").casefold()
            rendered_host = host
        port = parsed.port
        if port is None:
            port = {"http": 80, "https": 443}.get(scheme)
        endpoint_path = unquote(parsed.path, errors="strict").replace("\\", "/")
    except (UnicodeError, ValueError) as exc:
        raise FileOperationError("webdav source claim identity is invalid") from exc
    if scheme not in {"http", "https"} or not host or port is None or not 1 <= port <= 65535:
        raise FileOperationError("webdav source claim identity is invalid")
    scope = f"webdav:{scheme}://{rendered_host}:{port}"
    effective_path = _canonical_remote_claim_path(
        endpoint_path,
        str(location.prefix or ""),
        path,
    )
    return scope, effective_path


def _s3_source_claim_identity(location, path: str) -> tuple[str, str]:
    from services import s3_backup

    try:
        endpoint = s3_backup.normalize_endpoint(str(location.endpoint or ""))
        bucket = s3_backup._clean_bucket(str(location.bucket or ""))
    except s3_backup.S3Error as exc:
        raise FileOperationError("s3 source claim identity is invalid") from exc
    scope = f"s3:{endpoint}/{bucket}"
    effective_path = _canonical_remote_claim_path(str(location.prefix or ""), path)
    return scope, effective_path


def _source_mutation_claim_identity(db, row: FileOperation) -> tuple[str, str]:
    """Return one durable overlap identity for this operation's mutable source."""
    location = _location(db, row.source_location_id)
    return _path_claim_identity(location, row.source_path)


def _path_claim_identity(location, path: str) -> tuple[str, str]:
    """Return a canonical physical identity shared by aliased storage roots."""
    if location.kind == "webdav":
        return _webdav_source_claim_identity(location, path)
    if location.kind == "s3":
        return _s3_source_claim_identity(location, path)
    if location.kind != "local":
        return f"location:{location.id}", path
    local_path = (
        storage_locations.local_root(location)
        if not path
        else _absolute(location, path).resolve(strict=False)
    )
    case_insensitive = _local_claim_case_insensitive(local_path)
    physical_path = canonical_local_physical_claim_path(
        local_path.as_posix(),
        case_sensitive=not case_insensitive,
    )
    return f"local-physical-{'ci' if case_insensitive else 'cs'}", physical_path


def _restore_destination_claim_path(db, row: FileOperation) -> str:
    try:
        details = json.loads(row.undo_json or "{}")
    except (TypeError, ValueError):
        details = {}
    destination = details.get("destination_path") or row.destination_path
    if not destination:
        item = db.get(TrashItem, row.source_path)
        if item and item.kind == "file" and item.location_id == row.source_location_id:
            destination = item.normalized_path or item.ref
    if not destination:
        raise FileOperationError("restore destination is missing")
    return _normal(destination)


def _base_operation_path_claim_targets(db, row: FileOperation) -> list[tuple[StorageLocation, str]]:
    """Return every live Files path that must stay stable for run or undo."""
    if row.action == DIRECT_MUTATION_ACTION:
        source_location = storage_locations.get_location(db, row.source_location_id)
        if source_location is None:
            raise FileOperationError("storage location not found")
    else:
        source_location = _location(db, row.source_location_id)
    if row.action == "restore":
        return [(source_location, _restore_destination_claim_path(db, row))]
    targets = [(source_location, row.source_path)]
    if row.action in {"copy", "move", "rename"}:
        destination_location = _location(
            db,
            row.destination_location_id or row.source_location_id,
        )
        targets.append((destination_location, row.destination_path))
    return targets


def _operation_path_claim_targets(db, row: FileOperation) -> list[tuple[StorageLocation, str]]:
    targets = _base_operation_path_claim_targets(db, row)
    try:
        details = json.loads(row.undo_json or "{}")
    except (TypeError, ValueError):
        details = {}
    recovery = details.get("survivor_recovery")
    if isinstance(recovery, dict) and recovery.get("path") and recovery.get("location_id"):
        targets.append((_location(db, recovery["location_id"]), _normal(recovery["path"])))
    return targets


def _expected_operation_path_claims(
    db,
    row: FileOperation,
) -> dict[tuple[str, str], StorageLocation]:
    expected: dict[tuple[str, str], StorageLocation] = {}
    for location, path in _operation_path_claim_targets(db, row):
        identity = _path_claim_identity(location, path)
        expected.setdefault(identity, location)
    return expected


def _operation_path_claims_owned(db, row: FileOperation) -> bool:
    expected = set(_expected_operation_path_claims(db, row))
    actual = {
        (claim.claim_scope, claim.normalized_path)
        for claim in db.query(FileOperationPathClaim)
        .filter(FileOperationPathClaim.operation_id == row.id)
        .all()
    }
    return actual == expected


def _acquire_operation_path_claims(db, row: FileOperation) -> None:
    """Atomically claim every source/destination path and overlapping subtree."""
    expected = _expected_operation_path_claims(db, row)
    existing = {
        (claim.claim_scope, claim.normalized_path): claim
        for claim in db.query(FileOperationPathClaim)
        .filter(FileOperationPathClaim.operation_id == row.id)
        .all()
    }
    unexpected = set(existing).difference(expected)
    if unexpected:
        raise FileOperationError("Files path claim does not match this operation")
    for (claim_scope, normalized_path), location in expected.items():
        if (claim_scope, normalized_path) in existing:
            continue
        claim_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"alles-file-operation:{row.id}:{claim_scope}:{normalized_path}",
            )
        )
        db.add(
            FileOperationPathClaim(
                id=claim_id,
                operation_id=row.id,
                location_id=location.id,
                claim_scope=claim_scope,
                normalized_path=normalized_path,
            )
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise FileOperationError(
            "source or destination is already in use by another operation"
        ) from exc
    if not _operation_path_claims_owned(db, row):
        raise FileOperationError("Files path ownership claim is missing")


def _release_operation_path_claims(db, row: FileOperation) -> None:
    db.query(FileOperationPathClaim).filter(FileOperationPathClaim.operation_id == row.id).delete(
        synchronize_session=False
    )


def _source_mutation_claim_owned(db, row: FileOperation) -> bool:
    if row.action not in SOURCE_MUTATION_ACTIONS:
        return False
    claim = db.get(FileOperationSourceClaim, row.id)
    claim_scope, normalized_path = _source_mutation_claim_identity(db, row)
    return bool(
        claim
        and claim.location_id == row.source_location_id
        and claim.claim_scope == claim_scope
        and claim.normalized_path == normalized_path
    )


def _acquire_source_mutation_claim(db, row: FileOperation) -> None:
    """Atomically own one mutable source and every ancestor/descendant conflict."""
    if row.action not in SOURCE_MUTATION_ACTIONS:
        return
    if _source_mutation_claim_owned(db, row):
        return
    existing = db.get(FileOperationSourceClaim, row.id)
    if existing is not None:
        raise FileOperationError("source mutation claim does not match this operation")
    claim_scope, normalized_path = _source_mutation_claim_identity(db, row)
    db.add(
        FileOperationSourceClaim(
            operation_id=row.id,
            location_id=row.source_location_id,
            claim_scope=claim_scope,
            normalized_path=normalized_path,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise FileOperationError("source is already in use by another operation") from exc


def _release_source_mutation_claim(db, row: FileOperation) -> None:
    if row.action in SOURCE_MUTATION_ACTIONS:
        db.query(FileOperationSourceClaim).filter(
            FileOperationSourceClaim.operation_id == row.id
        ).delete(synchronize_session=False)


def _release_operation_claims(db, row: FileOperation) -> None:
    _release_source_mutation_claim(db, row)
    _release_operation_path_claims(db, row)


@contextmanager
def direct_mutation_claim(db, location: StorageLocation, path: str):
    """Serialize a legacy/direct Files write with every durable operation path claim."""
    try:
        normalized = storage_locations.normalize_path(path)
    except ValueError as exc:
        raise FileOperationError(str(exc)) from exc
    row = FileOperation(
        action=DIRECT_MUTATION_ACTION,
        source_location_id=location.id,
        source_path=normalized,
        destination_location_id=None,
        destination_path="",
        state="running",
        undo_json=json.dumps({"internal_direct_mutation": True}, sort_keys=True),
    )
    db.add(row)
    db.commit()
    try:
        _acquire_operation_path_claims(db, row)
        yield row
    finally:
        db.rollback()
        current = db.get(FileOperation, row.id)
        if current is not None:
            _release_operation_claims(db, current)
            db.delete(current)
            db.commit()


def _record_local_source_ownership(db, row: FileOperation, details: dict) -> None:
    """Persist ownership after the atomic source quarantine and before unlink."""
    if details.get("source_owned"):
        return
    if not _source_mutation_claim_owned(db, row) or not _operation_path_claims_owned(db, row):
        raise FileOperationError("source mutation ownership claim is missing")
    details["source_owned"] = True
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()


def _has_versioned_s3_source(location, metadata: dict | None) -> bool:
    """Return whether logical source deletion would require deleting an S3 version."""
    if location.kind != "s3" or not isinstance(metadata, dict):
        return False
    if metadata.get("version_id"):
        return True
    manifest = metadata.get("manifest")
    if isinstance(manifest, list) and any(
        isinstance(child, dict) and child.get("type") == "file" and child.get("version_id")
        for child in manifest
    ):
        return True
    markers = metadata.get("directory_markers")
    return isinstance(markers, list) and any(
        isinstance(marker, dict) and marker.get("version_id") for marker in markers
    )


def _is_exact_s3_version_id(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() != "null"


def _remote_identity(metadata: dict | None) -> dict | None:
    """Return the immutable remote identity fields needed for fail-closed recovery."""
    if not isinstance(metadata, dict):
        return None
    manifest = metadata.get("manifest") if "manifest" in metadata else None
    markers = metadata.get("directory_markers") if "directory_markers" in metadata else None
    identity = {
        "etag": metadata.get("etag", ""),
        "version_id": metadata.get("version_id", ""),
        "manifest": manifest,
        "directory_markers": markers,
    }
    if not (
        identity["etag"]
        or identity["version_id"]
        or isinstance(manifest, list)
        or isinstance(markers, list)
    ):
        return None
    return identity


def _same_remote_identity(current: dict | None, stored: dict | None) -> bool:
    """Require an exact ETag/version/manifest match, not merely identical bytes."""
    current_identity = _remote_identity(current)
    stored_identity = _remote_identity(stored)
    return (
        current_identity is not None
        and stored_identity is not None
        and current_identity == stored_identity
    )


def _source_identity_matches_refusal(current: dict | None, details: dict) -> bool:
    """Match only the exact identity observed by a proven pre-mutation refusal."""
    return bool(
        details.get("source_delete_refused_before_mutation")
        and _same_remote_identity(
            current,
            details.get("source_delete_refusal_identity"),
        )
    )


def _clear_source_delete_refusal(db, row: FileOperation, details: dict) -> None:
    """Do not let proof from an earlier failed attempt authorize a later undo."""
    changed = False
    for key in (
        "source_delete_refused_before_mutation",
        "source_delete_refusal_identity",
    ):
        if key in details:
            details.pop(key, None)
            changed = True
    if changed:
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()


def _record_source_delete_refusal(
    db,
    row: FileOperation,
    details: dict,
    exc: storage_backends.StorageVersionedDeleteRefused,
) -> None:
    """Persist proof only when no source mutation occurred and identity is known."""
    if not exc.before_mutation or not isinstance(exc.source_identity, dict):
        return
    details["source_delete_refused_before_mutation"] = True
    details["source_delete_refusal_identity"] = exc.source_identity
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()


def _delete_remote_operation_source(
    db,
    row: FileOperation,
    details: dict,
    location,
    **kwargs,
) -> None:
    """Delete a logical source while retaining exact pre-mutation refusal proof."""
    _clear_source_delete_refusal(db, row, details)
    try:
        storage_backends.delete_tree(location, row.source_path, **kwargs)
    except storage_backends.StorageVersionedDeleteRefused as exc:
        _record_source_delete_refusal(db, row, details, exc)
        raise FileOperationError(str(exc)) from exc
    except storage_backends.StorageBackendError as exc:
        raise FileOperationError(str(exc)) from exc


def _uploaded_destination_identity(metadata: dict) -> dict:
    return {
        "etag": str(metadata.get("etag") or ""),
        "version_id": str(metadata.get("version_id") or ""),
        "local_device": int(metadata.get("local_device") or 0),
        "local_inode": int(metadata.get("local_inode") or 0),
        "local_mtime_ns": int(metadata.get("local_mtime_ns") or 0),
        "local_ctime_ns": int(metadata.get("local_ctime_ns") or 0),
        "local_tree_identity": str(metadata.get("local_tree_identity") or ""),
        "local_publication_identity": str(metadata.get("local_publication_identity") or ""),
    }


def _same_published_destination_identity(
    location, current: dict | None, stored: dict | None
) -> bool:
    """Match the physical object/tree published by this operation, not only its bytes."""
    if not isinstance(current, dict) or not isinstance(stored, dict):
        return False
    if location.kind != "local":
        return _same_remote_identity(current, stored)
    current_identity = _uploaded_destination_identity(current)
    stored_identity = _uploaded_destination_identity(stored)
    return bool(
        current_identity["local_device"]
        and current_identity["local_inode"]
        and current_identity == stored_identity
    )


def _require_uploaded_identity(location, snapshot: Path, uploaded, current: dict) -> None:
    """Bind ownership to the identity returned by this operation's publication."""
    if not isinstance(uploaded, dict):
        raise FileOperationError("uploaded destination identity is incomplete")
    published = _uploaded_destination_identity(uploaded)
    observed = _uploaded_destination_identity(current)
    if location.kind == "local":
        if not published["local_device"] or not published["local_inode"]:
            raise FileOperationError("uploaded local destination identity is incomplete")
        if published != observed:
            raise FileOperationError(
                "uploaded local destination changed before ownership was saved"
            )
        return
    if snapshot.is_file():
        if not published["etag"]:
            raise FileOperationError("uploaded remote destination identity is incomplete")
        if (
            location.kind == "s3"
            and published["version_id"]
            and not _is_exact_s3_version_id(published["version_id"])
        ):
            raise FileOperationError(
                "s3 version identity is invalid; uploaded object was preserved"
            )
        if any(published[key] != observed[key] for key in ("etag", "version_id")):
            raise FileOperationError(
                "uploaded remote destination changed before ownership was saved"
            )
    elif not _same_remote_identity(current, uploaded):
        raise FileOperationError("uploaded remote directory changed before ownership was saved")


def _release_published_receipt(
    db,
    row: FileOperation,
    details: dict,
    *,
    started_key: str,
    location,
    path: str,
    operation_id: str,
    expected: dict,
) -> None:
    """Durably record the release boundary, then clean ownership artifacts fail-closed."""
    if not details.get(started_key):
        if not storage_backends.operation_receipt_matches(
            location,
            path,
            operation_id,
            expected,
        ):
            raise FileOperationError("destination ownership receipt is missing")
        details[started_key] = True
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    try:
        storage_backends.release_operation_receipt(
            location,
            path,
            operation_id,
            expected,
        )
    except storage_backends.StorageBackendError as exc:
        raise FileOperationError(str(exc)) from exc


def _survivor_recovery_operation_id(row: FileOperation, location_id: str, path: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"alles-survivor-recovery:{row.id}:{location_id}:{path}",
        )
    )


def _survivor_snapshot(row: FileOperation, details: dict) -> Path:
    recovery = details.get("survivor_recovery")
    if not isinstance(recovery, dict):
        raise FileOperationError("survivor recovery state is invalid")
    snapshot_name = str(recovery.get("snapshot") or "")
    if not snapshot_name or Path(snapshot_name).name != snapshot_name:
        raise FileOperationError("survivor recovery snapshot is invalid")
    snapshot = _workspace(row) / snapshot_name
    expected = details.get("fingerprint")
    if not isinstance(expected, dict) or not snapshot.exists() or fingerprint(snapshot) != expected:
        raise FileOperationError("survivor recovery snapshot is unavailable")
    return snapshot


def _arm_survivor_recovery(
    db,
    row: FileOperation,
    details: dict,
    *,
    snapshot_name: str,
    location,
    path: str,
    undo: bool,
    metadata_origin: str | None = None,
) -> None:
    current = details.get("survivor_recovery")
    if isinstance(current, dict):
        if undo and current.get("adopted_for_undo"):
            if (
                current.get("state") != "armed"
                or not current.get("undo")
                or current.get("metadata_origin") != "source"
            ):
                raise FileOperationError("survivor recovery state does not match this operation")
            _survivor_snapshot(row, details)
            return
        if (
            current.get("snapshot") != snapshot_name
            or current.get("location_id") != location.id
            or current.get("preferred_path") != path
            or bool(current.get("undo")) != undo
            or (metadata_origin and current.get("metadata_origin") != metadata_origin)
        ):
            raise FileOperationError("survivor recovery state does not match this operation")
        _survivor_snapshot(row, details)
        return
    snapshot = _workspace(row) / snapshot_name
    expected = details.get("fingerprint")
    if not isinstance(expected, dict) or not snapshot.exists() or fingerprint(snapshot) != expected:
        raise FileOperationError("verified survivor snapshot is unavailable")
    details["survivor_recovery"] = {
        "state": "armed",
        "snapshot": snapshot_name,
        "location_id": location.id,
        "preferred_path": path,
        "path": path,
        "attempt": 0,
        "undo": undo,
        "metadata_origin": metadata_origin or "",
    }
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()


def _adopt_run_survivor_recovery_for_undo(
    db,
    row: FileOperation,
    details: dict,
    source_location,
) -> dict | None:
    """Reuse an armed move snapshot when undo starts before run recovery finished."""
    recovery = details.get("survivor_recovery")
    if not isinstance(recovery, dict) or recovery.get("undo"):
        return recovery if isinstance(recovery, dict) else None
    if (
        recovery.get("state") != "armed"
        or recovery.get("location_id") != source_location.id
        or recovery.get("preferred_path") != row.source_path
    ):
        raise FileOperationError("survivor recovery state does not match this operation")
    _survivor_snapshot(row, details)
    recovery["undo"] = True
    recovery["metadata_origin"] = "source"
    recovery["adopted_for_undo"] = True
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()
    return recovery


def _disarm_survivor_recovery(row: FileOperation, details: dict) -> None:
    """Clear recovery only in the caller's final state transition transaction."""
    if "survivor_recovery" not in details:
        return
    details.pop("survivor_recovery", None)
    details.pop("survivor_recovery_receipt_release_started", None)
    row.undo_json = json.dumps(details, sort_keys=True)


def _survivor_recovery_sibling(
    row: FileOperation,
    location: StorageLocation,
    base_path: str,
    attempt: int,
) -> str:
    logical = Path(base_path)
    if location.kind == "local":
        limit_parent = storage_backends.local_path(location, base_path).parent
    else:
        # S3 has no component limit and WebDAV commonly accepts 255-byte segments.
        limit_parent = Path("/")
    recovery_id = hashlib.sha256(row.id.encode("utf-8")).hexdigest()[:12]
    name = internal_paths.bounded_named_child(
        limit_parent,
        logical.name or "file",
        prefix=f"alles-recovered-{recovery_id}-{attempt}",
    ).name
    parent = base_path.rpartition("/")[0]
    return f"{parent}/{name}" if parent else name


def _drop_extra_recovery_claim(db, row: FileOperation, location, path: str) -> None:
    identity = _path_claim_identity(location, path)
    base_identities = {
        _path_claim_identity(base_location, base_path)
        for base_location, base_path in _base_operation_path_claim_targets(db, row)
    }
    if identity in base_identities:
        return
    db.query(FileOperationPathClaim).filter(
        FileOperationPathClaim.operation_id == row.id,
        FileOperationPathClaim.claim_scope == identity[0],
        FileOperationPathClaim.normalized_path == identity[1],
    ).delete(synchronize_session=False)


def _rotate_survivor_recovery_path(db, row: FileOperation, details: dict) -> None:
    recovery = details["survivor_recovery"]
    location = _location(db, recovery["location_id"])
    old_path = recovery["path"]
    _drop_extra_recovery_claim(db, row, location, old_path)
    attempt = int(recovery.get("attempt") or 0) + 1
    recovery["attempt"] = attempt
    recovery["path"] = _survivor_recovery_sibling(
        row,
        location,
        recovery["preferred_path"],
        attempt,
    )
    recovery["state"] = "required"
    recovery.pop("meta", None)
    recovery.pop("upload_started", None)
    recovery.pop("cleanup_claimed", None)
    details.pop("survivor_recovery_receipt_release_started", None)
    row.undo_json = json.dumps(details, sort_keys=True)
    _acquire_operation_path_claims(db, row)


def _release_survivor_recovery_artifacts(
    location,
    path: str,
    operation_id: str,
    expected: dict,
) -> None:
    try:
        storage_backends.release_operation_receipt(
            location,
            path,
            operation_id,
            expected,
        )
    except storage_backends.StorageBackendError as exc:
        raise FileOperationError(str(exc)) from exc


def _recover_survivor(db, row: FileOperation, details: dict) -> str:
    """Publish the armed verified snapshot without replacing any concurrent bytes."""
    expected = details.get("fingerprint")
    snapshot = _survivor_snapshot(row, details)
    recovery = details["survivor_recovery"]
    if recovery.get("state") == "armed":
        recovery["state"] = "required"
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    for _attempt in range(32):
        recovery = details["survivor_recovery"]
        location = _location(db, recovery["location_id"])
        path = _normal(recovery["path"])
        operation_id = _survivor_recovery_operation_id(row, location.id, path)
        existing_target = _workspace(row) / "survivor-recovery-existing"
        existing_meta = _destination_snapshot(location, path, existing_target)
        state = recovery.get("state")
        if state == "recovered":
            if (
                existing_meta is not None
                and fingerprint(existing_target) == expected
                and _same_published_destination_identity(
                    location,
                    existing_meta,
                    recovery.get("meta"),
                )
            ):
                return path
            _rotate_survivor_recovery_path(db, row, details)
            continue
        if state == "published":
            stored_meta = recovery.get("meta")
            if (
                existing_meta is None
                or fingerprint(existing_target) != expected
                or not _same_published_destination_identity(location, existing_meta, stored_meta)
            ):
                _release_survivor_recovery_artifacts(location, path, operation_id, expected)
                _rotate_survivor_recovery_path(db, row, details)
                continue
        else:
            receipt_owned = bool(
                existing_meta is not None
                and storage_backends.operation_receipt_matches(
                    location,
                    path,
                    operation_id,
                    expected,
                )
            )
            if existing_meta is not None and not receipt_owned:
                if recovery.get("upload_started"):
                    try:
                        cleanup_safe = storage_backends.incomplete_operation_upload_is_releasable(
                            location,
                            path,
                            operation_id,
                            expected,
                        )
                    except storage_backends.StorageBackendError as exc:
                        raise FileOperationError(str(exc)) from exc
                    if not cleanup_safe:
                        _release_survivor_recovery_artifacts(
                            location,
                            path,
                            operation_id,
                            expected,
                        )
                    else:
                        recovery["cleanup_claimed"] = True
                        row.undo_json = json.dumps(details, sort_keys=True)
                        db.commit()
                        try:
                            storage_backends.release_incomplete_operation_upload(
                                location,
                                path,
                                operation_id,
                                expected,
                                ownership_was_claimed=True,
                            )
                        except storage_backends.StorageBackendError as exc:
                            raise FileOperationError(str(exc)) from exc
                _rotate_survivor_recovery_path(db, row, details)
                continue
            if existing_meta is None:
                recovery["state"] = "publishing"
                recovery["upload_started"] = True
                row.undo_json = json.dumps(details, sort_keys=True)
                db.commit()
                try:
                    uploaded_meta = storage_backends.upload_tree(
                        location,
                        path,
                        snapshot,
                        operation_id=operation_id,
                    )
                except storage_backends.StorageBackendError as exc:
                    raise FileOperationError(str(exc)) from exc
                verify = _workspace(row) / "survivor-recovery-verify"
                existing_meta = _materialize(location, path, verify)
                if fingerprint(verify) != expected:
                    raise FileOperationError("survivor recovery verification failed")
                _require_uploaded_identity(location, snapshot, uploaded_meta, existing_meta)
                try:
                    storage_backends.seal_operation_receipt(
                        location,
                        path,
                        operation_id,
                        expected,
                        uploaded_meta,
                    )
                except storage_backends.StorageBackendError as exc:
                    raise FileOperationError(str(exc)) from exc
            if not storage_backends.operation_receipt_matches(
                location,
                path,
                operation_id,
                expected,
            ):
                raise FileOperationError("survivor recovery ownership receipt is missing")
            verify = _workspace(row) / "survivor-recovery-owned"
            existing_meta = _materialize(location, path, verify)
            if fingerprint(verify) != expected:
                raise FileOperationError("survivor recovery verification failed")
            recovery["state"] = "published"
            recovery["meta"] = existing_meta
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        _release_published_receipt(
            db,
            row,
            details,
            started_key="survivor_recovery_receipt_release_started",
            location=location,
            path=path,
            operation_id=operation_id,
            expected=expected,
        )
        final = _workspace(row) / "survivor-recovery-final"
        final_meta = _materialize(location, path, final)
        if fingerprint(final) != expected or not _same_published_destination_identity(
            location,
            final_meta,
            recovery["meta"],
        ):
            _rotate_survivor_recovery_path(db, row, details)
            continue
        recovery["state"] = "recovered"
        recovery["path"] = path
        details.pop("survivor_recovery_receipt_release_started", None)
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        return path
    raise FileOperationError("survivor recovery could not reserve a visible path")


def _release_operation_artifacts(
    location,
    path: str,
    operation_id: str,
    expected: dict,
) -> None:
    try:
        storage_backends.release_operation_receipt(location, path, operation_id, expected)
    except storage_backends.StorageBackendError as exc:
        raise FileOperationError(str(exc)) from exc


def _finish_failed_move_survivor_recovery(
    db,
    row: FileOperation,
    details: dict,
    source_location,
    destination_location,
) -> None:
    recovery = details.get("survivor_recovery")
    if not isinstance(recovery, dict):
        raise FileOperationError("survivor recovery state is invalid")
    recovery_location = _location(db, recovery.get("location_id"))
    path = _recover_survivor(db, row, details)
    if details.get("source_delete_completed"):
        metadata_location = destination_location
        metadata_path = row.destination_path
    else:
        metadata_location = source_location
        metadata_path = row.source_path
    _rekey_metadata(
        db,
        metadata_location.id,
        metadata_path,
        recovery_location.id,
        path,
    )
    if _remote_or_cross(source_location, destination_location):
        _release_operation_artifacts(
            destination_location,
            row.destination_path,
            row.id,
            details["fingerprint"],
        )
    for key in (
        "destination_owned",
        "destination_claimed",
        "destination_meta",
        "destination_etag",
        "destination_version_id",
        "source_delete_started",
        "source_delete_completed",
        "source_owned",
        "survivor_recovery_receipt_release_started",
    ):
        details.pop(key, None)
    details.pop("survivor_recovery", None)
    details["survivor_recovered"] = True
    details["survivor_recovery_path"] = path
    details["survivor_recovery_location_id"] = recovery_location.id
    terminal_error = _SurvivorRecovered(path, undo=False)
    row.undo_json = json.dumps(details, sort_keys=True)
    row.state = "failed"
    row.error_code = str(terminal_error)[:160]
    _release_operation_claims(db, row)
    db.commit()
    _clean_workspace(row)
    raise terminal_error


def _finish_undo_survivor_recovery(
    db,
    row: FileOperation,
    details: dict,
    source_location,
    destination_location,
) -> None:
    recovery = details.get("survivor_recovery")
    if not isinstance(recovery, dict):
        raise FileOperationError("survivor recovery state is invalid")
    recovery_location = _location(db, recovery.get("location_id"))
    path = _recover_survivor(db, row, details)
    metadata_origin = str(recovery.get("metadata_origin") or "")
    if (
        details.get("undo_metadata_rekeyed")
        or details.get("undo_source_receipt_release_started")
        or metadata_origin == "source"
        or (
            metadata_origin != "destination"
            and (row.action == "copy" or not details.get("source_delete_completed"))
        )
    ):
        metadata_location = source_location
        metadata_path = row.source_path
    else:
        metadata_location = destination_location
        metadata_path = row.destination_path
    if (
        (metadata_location.id, _normal(metadata_path)) != (recovery_location.id, _normal(path))
        and recovery_location.id == destination_location.id
        and _normal(path) == _normal(row.destination_path)
    ):
        _purge_live_metadata(db, recovery_location.id, path)
    _rekey_metadata(
        db,
        metadata_location.id,
        metadata_path,
        recovery_location.id,
        path,
    )
    if details.get("undo_source_owned") or details.get("undo_source_claimed"):
        _release_operation_artifacts(
            source_location,
            row.source_path,
            f"undo-{row.id}",
            details["fingerprint"],
        )
    for key in (
        "undo_mutation_started",
        "undo_source_owned",
        "undo_source_claimed",
        "undo_source_meta",
        "undo_source_receipt_release_started",
        "undo_metadata_rekeyed",
        "survivor_recovery_receipt_release_started",
    ):
        details.pop(key, None)
    details.pop("survivor_recovery", None)
    details["survivor_recovered"] = True
    details["survivor_recovery_path"] = path
    details["survivor_recovery_location_id"] = recovery_location.id
    return_state = str(details.pop("undo_return_state", "completed"))
    if return_state not in {"completed", "failed"}:
        return_state = "completed"
    terminal_error = _SurvivorRecovered(path, undo=True)
    row.undo_json = json.dumps(details, sort_keys=True)
    row.state = return_state
    row.error_code = str(terminal_error)[:160]
    _release_operation_claims(db, row)
    db.commit()
    _clean_workspace(row)
    raise terminal_error


def _path_matches_verified_identity(
    location,
    path: str,
    target: Path,
    expected: dict,
    stored_meta: dict | None,
) -> bool:
    metadata = _destination_snapshot(location, path, target)
    return bool(
        metadata is not None
        and fingerprint(target) == expected
        and _same_published_destination_identity(location, metadata, stored_meta)
    )


def _trash_survivor_snapshot(row: FileOperation, details: dict) -> Path:
    recovery = details.get("trash_survivor_recovery")
    if not isinstance(recovery, dict):
        raise FileOperationError("trash recovery state is invalid")
    snapshot_name = str(recovery.get("snapshot") or "")
    if not snapshot_name or Path(snapshot_name).name != snapshot_name:
        raise FileOperationError("trash recovery snapshot is invalid")
    snapshot = _workspace(row) / snapshot_name
    expected = details.get("fingerprint")
    if not isinstance(expected, dict) or not snapshot.exists() or fingerprint(snapshot) != expected:
        raise FileOperationError("trash recovery snapshot is unavailable")
    return snapshot


def _arm_trash_survivor_recovery(
    db,
    row: FileOperation,
    details: dict,
    *,
    item: TrashItem,
    snapshot_name: str,
) -> None:
    current = details.get("trash_survivor_recovery")
    if isinstance(current, dict):
        if current.get("trash_id") != item.id or current.get("snapshot") != snapshot_name:
            raise FileOperationError("trash recovery state does not match this restore")
        _trash_survivor_snapshot(row, details)
        return
    snapshot = _workspace(row) / snapshot_name
    expected = details.get("fingerprint")
    if not isinstance(expected, dict) or not snapshot.exists() or fingerprint(snapshot) != expected:
        raise FileOperationError("verified trash recovery snapshot is unavailable")
    _payload, metadata_snapshot = _trash_metadata(item)
    details["trash_survivor_recovery"] = {
        "state": "armed",
        "trash_id": item.id,
        "snapshot": snapshot_name,
        "metadata_restore_expected": bool(metadata_snapshot),
    }
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()


def _clear_trash_survivor_recovery(row: FileOperation, details: dict) -> None:
    details.pop("trash_survivor_recovery", None)
    row.undo_json = json.dumps(details, sort_keys=True)


def _finish_restore_rollback(
    db,
    row: FileOperation,
    location,
    destination_path: str,
    *,
    undo: bool = False,
) -> None:
    """Restore the verified trash copy and its metadata before releasing claims."""
    row_id = row.id
    db.rollback()
    current = db.get(FileOperation, row_id)
    if current is None:
        raise FileOperationError("restore operation disappeared during rollback")
    try:
        details = json.loads(current.undo_json or "{}")
    except (TypeError, ValueError) as exc:
        raise FileOperationError("restore recovery state is invalid") from exc
    snapshot = _trash_survivor_snapshot(current, details)
    recovery = details.get("trash_survivor_recovery")
    item = db.get(TrashItem, recovery.get("trash_id")) if isinstance(recovery, dict) else None
    if item is None:
        raise FileOperationError("trash record is missing during restore rollback")
    payload, metadata_snapshot = _trash_metadata(item)
    if (
        bool(recovery.get("metadata_restore_expected"))
        and not metadata_snapshot
        and "metadata_snapshot" not in payload
    ):
        _detach_live_metadata_to_trash(db, item, location.id, destination_path)
        payload, _metadata_snapshot = _trash_metadata(item)
    trash_name = str(payload.get("trash_name") or "")
    stash = trash.stash_path(trash_name) if trash_name else None
    if (
        stash is not None
        and (stash.exists() or stash.is_symlink())
        and not _same(stash, details["fingerprint"])
    ):
        stash = None
    if stash is None:
        trash_name = uuid.uuid4().hex + (snapshot.suffix if snapshot.is_file() else "")
        payload["trash_name"] = trash_name
        item.payload = json.dumps(payload, sort_keys=True)
        stash = trash.stash_path(trash_name)
    if not (stash.exists() or stash.is_symlink()):
        _copy_verified(snapshot, stash, f"restore-rollback-{current.id}")
    if not _same(stash, details["fingerprint"]):
        raise FileOperationError("restore rollback copy could not be verified")
    expected = details["fingerprint"]
    stored_meta = details.get("undo_source_meta" if undo else "destination_meta")
    owned = bool(details.get("undo_source_owned" if undo else "destination_owned"))
    operation_id = f"undo-{current.id}" if undo else current.id
    if owned and isinstance(stored_meta, dict):
        if location.kind == "local":
            destination = _absolute(location, destination_path)
            detached = _quarantine_path(destination, f"restore-rollback-{current.id}")
            if (
                destination.exists()
                or destination.is_symlink()
                or detached.exists()
                or detached.is_symlink()
            ):
                try:
                    detached = _quarantine_verified_publication(
                        destination,
                        expected,
                        stored_meta,
                        f"restore-rollback-{current.id}",
                    )
                except FileOperationError:
                    # A replacement at the visible path is not ours to remove.
                    pass
                else:
                    _remove(detached)
        else:
            destination_snapshot = _workspace(current) / "restore-rollback-destination"
            destination_meta = _destination_snapshot(
                location,
                destination_path,
                destination_snapshot,
            )
            if (
                destination_meta is not None
                and fingerprint(destination_snapshot) == expected
                and _same_published_destination_identity(
                    location,
                    destination_meta,
                    stored_meta,
                )
            ):
                try:
                    storage_backends.delete_tree(
                        location,
                        destination_path,
                        expected=expected,
                        expected_etag=str(stored_meta.get("etag") or ""),
                        version_id=str(stored_meta.get("version_id") or ""),
                        verified_meta=destination_meta,
                        operation_id=operation_id,
                    )
                except storage_backends.StorageBackendError as exc:
                    raise FileOperationError(str(exc)) from exc
    if (
        location.kind != "local"
        and undo
        and (details.get("undo_source_owned") or details.get("undo_source_receipt_release_started"))
    ):
        _release_operation_artifacts(
            location,
            destination_path,
            operation_id,
            expected,
        )
    elif location.kind != "local" and (
        details.get("destination_owned") or details.get("destination_receipt_release_started")
    ):
        _release_operation_artifacts(
            location,
            destination_path,
            operation_id,
            expected,
        )
    run_keys = (
        "destination_claimed",
        "destination_owned",
        "destination_meta",
        "destination_etag",
        "destination_version_id",
        "destination_receipt_release_started",
        "upload_started",
        "upload_cleanup_safe",
        "upload_cleanup_claimed",
    )
    undo_keys = (
        "undo_mutation_started",
        "undo_source_owned",
        "undo_source_claimed",
        "undo_source_meta",
        "undo_source_receipt_release_started",
    )
    for key in (*run_keys, *undo_keys, "trash_survivor_recovery"):
        details.pop(key, None)
    details["restore_rolled_back"] = True
    terminal_error = _RestoreRolledBack()
    terminal_state = "failed"
    if undo:
        terminal_state = str(details.pop("undo_return_state", "completed"))
        if terminal_state not in {"completed", "failed"}:
            terminal_state = "completed"
    current.undo_json = json.dumps(details, sort_keys=True)
    current.state = terminal_state
    current.error_code = str(terminal_error)[:160]
    _release_operation_claims(db, current)
    db.commit()
    _clean_workspace(current)
    raise terminal_error


def _mark_undo_mutation_started(db, row: FileOperation, details: dict) -> None:
    """Persist the boundary after which undo must retain its recovery leases."""
    if details.get("undo_mutation_started"):
        return
    details["undo_mutation_started"] = True
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()


def _is_pre_source_mutation_move(row: FileOperation, details: dict) -> bool:
    return bool(
        row.action == "move"
        and details.get("destination_owned")
        and not details.get("source_owned")
        and not details.get("source_delete_started")
        and not details.get("source_conflict_pending")
        and not details.get("source_conflict_published")
    )


def _has_recoverable_side_effects(row: FileOperation, details: dict) -> bool:
    """Return whether a failed operation owns data that its undo can recover."""
    if details.get("source_conflict_published") or details.get("survivor_recovered"):
        return False
    if not details.get("undo"):
        return False
    if any(
        bool(details.get(key))
        for key in (
            "upload_started",
            "destination_owned",
            "source_quarantine_started",
            "source_owned",
            "source_delete_started",
            "undo_source_owned",
        )
    ):
        return True
    return row.action == "delete" and bool(details.get("trash_id"))


def _has_undoable_side_effects(row: FileOperation, details: dict) -> bool:
    """Return whether undo can safely act without first resuming an upload."""
    if (
        details.get("source_conflict_pending")
        or details.get("source_conflict_published")
        or details.get("survivor_recovered")
    ):
        return False
    if not details.get("undo"):
        return False
    if any(
        bool(details.get(key))
        for key in ("destination_owned", "source_delete_started", "undo_source_owned")
    ):
        return True
    return row.action == "delete" and bool(details.get("trash_id"))


def _has_cleanup_only_upload(details: dict) -> bool:
    """Return whether discard can preserve bytes while removing upload bookkeeping."""
    return bool(details.get("upload_started") and details.get("upload_cleanup_safe")) and not any(
        bool(details.get(key))
        for key in ("destination_owned", "source_delete_started", "undo_source_owned")
    )


def _record_upload_cleanup_safety(
    db,
    row: FileOperation,
    details: dict,
    destination_location,
    destination_path: str,
) -> None:
    """Persist cleanup permission only after proving no destination bytes are visible."""
    try:
        safe = storage_backends.incomplete_operation_upload_is_releasable(
            destination_location,
            destination_path,
            row.id,
            details.get("fingerprint") or {},
        )
    except storage_backends.StorageBackendError:
        safe = False
    if safe:
        details["upload_cleanup_safe"] = True
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()


def public_dict(row: FileOperation) -> dict:
    try:
        details = json.loads(row.undo_json or "{}")
    except (TypeError, ValueError):
        details = {}
    public_state = "undoing" if row.state == "undoing_claimed" else row.state
    recoverable = _has_recoverable_side_effects(row, details)
    cleanup_only_upload = _has_cleanup_only_upload(details)
    can_discard = row.state == "completed" or (
        row.state in {"failed", "cancelled"} and (not recoverable or cleanup_only_upload)
    )
    return {
        "id": row.id,
        "action": row.action,
        "source_location_id": row.source_location_id,
        "source_path": row.source_path,
        "destination_location_id": row.destination_location_id,
        "destination_path": row.destination_path,
        "state": public_state,
        "bytes_total": row.bytes_total or 0,
        "bytes_done": row.bytes_done or 0,
        "error_code": row.error_code or "",
        "recovery_location_id": str(details.get("survivor_recovery_location_id") or ""),
        "recovery_path": str(details.get("survivor_recovery_path") or ""),
        "can_run": row.state == "queued",
        "can_retry": row.state in {"failed", "cancelled"}
        and not bool(details.get("source_conflict_published") or details.get("survivor_recovered")),
        "can_discard": can_discard,
        "can_cancel": row.state == "queued" and not recoverable,
        "can_undo": bool(details.get("undo"))
        and not bool(details.get("source_conflict_published") or details.get("survivor_recovered"))
        and (
            row.state in {"completed", "undoing"}
            or (row.state == "failed" and _has_undoable_side_effects(row, details))
        ),
        "non_atomic": bool(details.get("non_atomic")),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def recover_interrupted(db) -> int:
    direct_rows = (
        db.query(FileOperation)
        .filter(
            FileOperation.action == DIRECT_MUTATION_ACTION,
            FileOperation.state == "running",
        )
        .all()
    )
    for row in direct_rows:
        _release_operation_claims(db, row)
        db.delete(row)
    rows = (
        db.query(FileOperation)
        .filter(
            FileOperation.action != DIRECT_MUTATION_ACTION,
            FileOperation.state.in_(("running", "undoing_claimed")),
        )
        .all()
    )
    for row in rows:
        row.state = "queued" if row.state == "running" else "undoing"
        row.error_code = "recovered_after_restart"
    if direct_rows or rows:
        db.commit()
    return len(direct_rows) + len(rows)


def enqueue(
    db,
    *,
    action: str,
    source_location_id: str,
    source_path: str,
    destination_location_id: str | None = None,
    destination_path: str = "",
) -> FileOperation:
    clean_action = str(action or "").strip().lower()
    if clean_action not in ACTIONS:
        raise FileOperationError("unsupported Files operation")
    source = _normal(source_path)
    has_restore_destination = clean_action == "restore" and bool(
        str(destination_path or "").strip()
    )
    destination = (
        _normal(destination_path)
        if clean_action in {"copy", "move", "rename"} or has_restore_destination
        else ""
    )
    source_location = _location(db, source_location_id)
    destination_id = destination_location_id or source_location.id
    destination_location = _location(db, destination_id)
    if clean_action == "restore" and destination_location.id != source_location.id:
        raise FileOperationError("restore stays inside its original storage location")
    if clean_action in {"move", "rename", "delete", "restore"}:
        _require_managed(source_location)
    if clean_action in {"copy", "move", "rename"}:
        _require_managed(destination_location)
    if clean_action == "rename" and source_location.id != destination_location.id:
        raise FileOperationError("rename stays inside one storage location")
    if clean_action in {"copy", "move", "rename"}:
        _validate_destination(
            source_location.id,
            source,
            destination_location.id,
            destination,
        )
        _validate_local_physical_destination(
            source_location,
            source,
            destination_location,
            destination,
        )
    row = FileOperation(
        action=clean_action,
        source_location_id=source_location.id,
        source_path=source,
        destination_location_id=(destination_location.id if destination else None),
        destination_path=destination,
        state="queued",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _execute_copy_or_move(db, row: FileOperation, *, move: bool) -> dict:
    source_location = _location(db, row.source_location_id)
    destination_location = _location(db, row.destination_location_id or row.source_location_id)
    _validate_destination(
        source_location.id,
        row.source_path,
        destination_location.id,
        row.destination_path,
    )
    _validate_local_physical_destination(
        source_location,
        row.source_path,
        destination_location,
        row.destination_path,
    )
    if _remote_or_cross(source_location, destination_location):
        return _execute_transfer(
            db,
            row,
            source_location,
            destination_location,
            move=move,
        )
    source = _absolute(source_location, row.source_path)
    destination = _absolute(destination_location, row.destination_path)
    details = json.loads(row.undo_json or "{}")
    recovery = details.get("survivor_recovery")
    if move and isinstance(recovery, dict) and recovery.get("state") != "armed":
        _finish_failed_move_survivor_recovery(
            db,
            row,
            details,
            source_location,
            destination_location,
        )

    def arm_local_move_recovery(candidate: Path) -> None:
        snapshot = _workspace(row) / "source"
        expected_fingerprint = details.get("fingerprint")
        if not isinstance(expected_fingerprint, dict):
            raise FileOperationError("move recovery fingerprint is missing")
        if snapshot.exists() or snapshot.is_symlink():
            if fingerprint(snapshot) != expected_fingerprint:
                raise FileOperationError("verified survivor snapshot changed during move")
        else:
            _copy_verified(candidate, snapshot, f"move-survivor-{row.id}")
        _arm_survivor_recovery(
            db,
            row,
            details,
            snapshot_name="source",
            location=source_location,
            path=row.source_path,
            undo=False,
        )

    if move and details.get("source_conflict_pending"):
        _finish_pending_source_conflict(db, row, details, source)
    expected = details.get("fingerprint")
    if (
        move
        and isinstance(recovery, dict)
        and isinstance(expected, dict)
        and not _same(source, expected)
        and not _same(destination, expected)
    ):
        _finish_failed_move_survivor_recovery(
            db,
            row,
            details,
            source_location,
            destination_location,
        )
    destination_claimed = bool(details.get("destination_claimed"))
    destination_owned = bool(details.get("destination_owned"))
    staged = _partial_copy_path(destination, row.id)
    staged_identity_key = "destination_staged_publication_identity"

    def persist_staged_publication_identity(candidate: Path) -> str:
        publication_identity = _local_publication_identity(candidate)
        stored_identity = str(details.get(staged_identity_key) or "")
        if stored_identity:
            if publication_identity != stored_identity:
                raise FileOperationError("staged copy identity changed during operation")
            return stored_identity
        details[staged_identity_key] = publication_identity
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        return publication_identity

    def record_destination_identity(publication_identity: str) -> None:
        try:
            destination_meta = storage_backends._local_path_receipt_identity(  # noqa: SLF001
                destination
            )
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
        if fingerprint(destination) != expected or (
            destination_meta.get("local_publication_identity") != publication_identity
        ):
            raise FileOperationError("destination verification failed")
        details["destination_meta"] = {**expected, **destination_meta}

    def owned_destination_matches() -> bool:
        destination_meta = details.get("destination_meta")
        if not isinstance(destination_meta, dict) or not _same(destination, expected):
            return False
        try:
            return storage_backends._same_local_path_receipt_identity(  # noqa: SLF001
                destination,
                destination_meta,
            )
        except storage_backends.StorageBackendError:
            return False

    if expected and destination_owned:
        if not owned_destination_matches():
            if move and not source.exists() and isinstance(details.get("survivor_recovery"), dict):
                _finish_failed_move_survivor_recovery(
                    db,
                    row,
                    details,
                    source_location,
                    destination_location,
                )
            action = "move" if move else "copy"
            raise FileOperationError(f"{action} destination changed during operation")
        if not move:
            return details
        quarantine = _quarantine_path(source, row.id)
        if quarantine.exists() or quarantine.is_symlink():
            quarantine = _quarantine_operation_source(db, row, details, source, expected)
            arm_local_move_recovery(quarantine)
            _record_local_source_ownership(db, row, details)
            with db.begin_nested():
                _rekey_metadata(
                    db,
                    source_location.id,
                    row.source_path,
                    destination_location.id,
                    row.destination_path,
                )
                db.flush()
                _remove(quarantine)
            details["source_delete_completed"] = True
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
            if not owned_destination_matches():
                _finish_failed_move_survivor_recovery(
                    db,
                    row,
                    details,
                    source_location,
                    destination_location,
                )
            details.pop("survivor_recovery", None)
            return details
        if not source.exists():
            if not details.get("source_owned") or not _source_mutation_claim_owned(db, row):
                raise FileOperationError("source not found")
            _rekey_metadata(
                db,
                source_location.id,
                row.source_path,
                destination_location.id,
                row.destination_path,
            )
            details["source_delete_completed"] = True
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
            details.pop("survivor_recovery", None)
            return details
    if expected and destination_claimed and not destination_owned:
        if not source.exists() or not _same(source, expected):
            raise FileOperationError("source changed during operation")
        if destination.exists() or destination.is_symlink():
            stored_identity = str(details.get(staged_identity_key) or "")
            if (
                staged.exists()
                or staged.is_symlink()
                or not stored_identity
                or not _same(destination, expected)
                or _local_publication_identity(destination) != stored_identity
            ):
                raise FileOperationError("destination already exists")
            publication_identity = stored_identity
        else:
            if staged.exists() or staged.is_symlink():
                if not _same(staged, expected):
                    raise FileOperationError("staged copy changed during operation")
            else:
                _, staged = _prepare_verified_copy(
                    source,
                    destination,
                    row.id,
                    expected=expected,
                )
            staged_identity = persist_staged_publication_identity(staged)
            publication_identity = _publish_verified_copy(staged, destination, expected)
            if publication_identity != staged_identity:
                raise FileOperationError("destination verification failed")
        record_destination_identity(publication_identity)
        details["destination_owned"] = True
        details.pop(staged_identity_key, None)
        row.bytes_total = expected["size"]
        row.bytes_done = expected["size"]
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        destination_owned = True
    if not source.exists():
        raise FileOperationError("source not found")
    if not destination_owned:
        _ensure_metadata_destination_clear(db, destination_location.id, row.destination_path)
    if not destination_owned:
        expected, staged = _prepare_verified_copy(source, destination, row.id)
        details = {
            "fingerprint": expected,
            "destination_claimed": True,
            "destination_owned": False,
            "undo": "move_back" if move else "remove_copy",
        }
        staged_identity = persist_staged_publication_identity(staged)
        row.bytes_total = expected["size"]
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        publication_identity = _publish_verified_copy(staged, destination, expected)
        if publication_identity != staged_identity:
            raise FileOperationError("destination verification failed")
        record_destination_identity(publication_identity)
        details["destination_owned"] = True
        details.pop(staged_identity_key, None)
        row.bytes_done = expected["size"]
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        destination_owned = True
    if move:
        if not owned_destination_matches():
            raise FileOperationError("move destination changed during operation")
        _ensure_metadata_destination_clear(db, destination_location.id, row.destination_path)
        arm_local_move_recovery(source)
        quarantine = _quarantine_operation_source(db, row, details, source, expected)
        _record_local_source_ownership(db, row, details)
        with db.begin_nested():
            _rekey_metadata(
                db,
                source_location.id,
                row.source_path,
                destination_location.id,
                row.destination_path,
            )
            db.flush()
            _remove(quarantine)
        details["source_delete_completed"] = True
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        if not owned_destination_matches():
            _finish_failed_move_survivor_recovery(
                db,
                row,
                details,
                source_location,
                destination_location,
            )
        details.pop("survivor_recovery", None)
    return details


def _destination_snapshot(location, path: str, target: Path) -> dict | None:
    try:
        return _materialize(location, path, target)
    except FileOperationError as exc:
        if isinstance(exc.__cause__, storage_backends.StorageNotFoundError):
            return None
        raise


def _execute_transfer(
    db,
    row: FileOperation,
    source_location,
    destination_location,
    *,
    move: bool,
) -> dict:
    _validate_destination(
        source_location.id,
        row.source_path,
        destination_location.id,
        row.destination_path,
    )
    _validate_local_physical_destination(
        source_location,
        row.source_path,
        destination_location,
        row.destination_path,
    )
    work = _workspace(row)
    source_snapshot = work / "source"
    destination_snapshot = work / "destination"
    details = json.loads(row.undo_json or "{}")
    expected = details.get("fingerprint")
    if expected is None:
        source_meta = _materialize(source_location, row.source_path, source_snapshot)
        if move and source_location.kind == "s3" and source_snapshot.is_dir():
            raise FileOperationError(
                "s3 folder moves are unavailable because safe source deletion is unsupported"
            )
        if move and _has_versioned_s3_source(source_location, source_meta):
            raise FileOperationError(
                "versioned s3 sources cannot be moved atomically; source was preserved"
            )
        expected = fingerprint(source_snapshot)
        details = {
            "fingerprint": expected,
            "source_etag": source_meta.get("etag", ""),
            "source_version_id": source_meta.get("version_id", ""),
            "source_meta": source_meta,
            "destination_claimed": False,
            "destination_owned": False,
            "undo": "move_back" if move else "remove_copy",
            "non_atomic": True,
        }
        row.bytes_total = expected["size"]
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    elif not source_snapshot.exists():
        _materialize(source_location, row.source_path, source_snapshot)
    if fingerprint(source_snapshot) != expected:
        raise FileOperationError("source changed during transfer")
    recovery = details.get("survivor_recovery")
    if move and isinstance(recovery, dict) and recovery.get("state") != "armed":
        _finish_failed_move_survivor_recovery(
            db,
            row,
            details,
            source_location,
            destination_location,
        )
    if move and _has_versioned_s3_source(source_location, details.get("source_meta")):
        raise FileOperationError(
            "versioned s3 sources cannot be moved atomically; source was preserved"
        )
    if move and source_location.kind in {"s3", "webdav"} and source_snapshot.is_dir():
        raise FileOperationError(
            f"{source_location.kind} folder moves are unavailable because safe source deletion "
            "is unsupported"
        )
    if move and not details.get("source_delete_completed"):
        _ensure_metadata_destination_clear(db, destination_location.id, row.destination_path)
    existing = _destination_snapshot(
        destination_location,
        row.destination_path,
        destination_snapshot,
    )
    destination_owned = bool(details.get("destination_owned"))
    receipt_owned = bool(
        not destination_owned
        and existing is not None
        and storage_backends.operation_receipt_matches(
            destination_location,
            row.destination_path,
            row.id,
            expected,
        )
    )
    if not destination_owned and not receipt_owned:
        _ensure_metadata_destination_clear(db, destination_location.id, row.destination_path)
    if existing is not None and not destination_owned and not receipt_owned:
        if details.get("upload_started"):
            _record_upload_cleanup_safety(
                db,
                row,
                details,
                destination_location,
                row.destination_path,
            )
        raise FileOperationError("destination already exists")
    destination_complete = existing is not None and fingerprint(destination_snapshot) == expected
    if destination_owned:
        stored_destination_meta = details.get("destination_meta")
        if (
            not destination_complete
            or not isinstance(stored_destination_meta, dict)
            or not _same_published_destination_identity(
                destination_location,
                existing,
                stored_destination_meta,
            )
        ):
            recovery = details.get("survivor_recovery")
            if move and isinstance(recovery, dict) and recovery.get("state") == "armed":
                source_still_verified = _path_matches_verified_identity(
                    source_location,
                    row.source_path,
                    work / "source-after-destination-change",
                    expected,
                    details.get("source_meta"),
                )
                if not source_still_verified:
                    _finish_failed_move_survivor_recovery(
                        db,
                        row,
                        details,
                        source_location,
                        destination_location,
                    )
            raise FileOperationError("destination changed during transfer")
    uploaded_meta = None
    if not destination_owned and not receipt_owned:
        if not details.get("upload_started"):
            details["upload_started"] = True
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        if "upload_cleanup_safe" in details:
            details.pop("upload_cleanup_safe", None)
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        try:
            uploaded_meta = storage_backends.upload_tree(
                destination_location,
                row.destination_path,
                source_snapshot,
                operation_id=row.id,
            )
        except storage_backends.StorageBackendError as exc:
            _record_upload_cleanup_safety(
                db,
                row,
                details,
                destination_location,
                row.destination_path,
            )
            raise FileOperationError(str(exc)) from exc
    destination_meta = _materialize(
        destination_location,
        row.destination_path,
        destination_snapshot,
    )
    if fingerprint(destination_snapshot) != expected:
        raise FileOperationError("destination verification failed")
    if uploaded_meta is not None:
        _require_uploaded_identity(
            destination_location,
            source_snapshot,
            uploaded_meta,
            destination_meta,
        )
        try:
            storage_backends.seal_operation_receipt(
                destination_location,
                row.destination_path,
                row.id,
                expected,
                uploaded_meta,
            )
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
    if not details.get("destination_owned"):
        if not storage_backends.operation_receipt_matches(
            destination_location,
            row.destination_path,
            row.id,
            expected,
        ):
            raise FileOperationError("destination ownership receipt is missing")
        details["destination_owned"] = True
        details.pop("upload_started", None)
        details["destination_etag"] = destination_meta.get("etag", "")
        details["destination_version_id"] = destination_meta.get("version_id", "")
        details["destination_meta"] = destination_meta
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    row.bytes_done = expected["size"]
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()
    if move:
        if not _source_mutation_claim_owned(db, row) or not _operation_path_claims_owned(db, row):
            raise FileOperationError("source mutation ownership claim is missing")
        _arm_survivor_recovery(
            db,
            row,
            details,
            snapshot_name="source",
            location=source_location,
            path=row.source_path,
            undo=False,
        )
        recovering_source_delete = bool(details.get("source_delete_started"))
        fresh = work / "source-before-delete"
        fresh_source_meta = _destination_snapshot(source_location, row.source_path, fresh)
        source_already_deleted = fresh_source_meta is None
        if source_already_deleted and not recovering_source_delete:
            _finish_failed_move_survivor_recovery(
                db,
                row,
                details,
                source_location,
                destination_location,
            )
        if fresh_source_meta is not None and fingerprint(fresh) != expected:
            _finish_failed_move_survivor_recovery(
                db,
                row,
                details,
                source_location,
                destination_location,
            )
        destination_before_delete = work / "destination-before-source-delete"
        destination_before_delete_meta = _materialize(
            destination_location,
            row.destination_path,
            destination_before_delete,
        )
        stored_destination_meta = details.get("destination_meta")
        if (
            fingerprint(destination_before_delete) != expected
            or not isinstance(stored_destination_meta, dict)
            or not _same_published_destination_identity(
                destination_location,
                destination_before_delete_meta,
                stored_destination_meta,
            )
        ):
            raise FileOperationError("destination changed; move delete stopped")
        if fresh_source_meta is not None and not storage_backends.operation_receipt_matches(
            destination_location,
            row.destination_path,
            row.id,
            expected,
        ):
            raise FileOperationError("destination ownership receipt is missing")
        if not recovering_source_delete:
            details["source_delete_started"] = True
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        _clear_source_delete_refusal(db, row, details)
        _ensure_metadata_destination_clear(db, destination_location.id, row.destination_path)
        try:
            with db.begin_nested():
                _rekey_metadata(
                    db,
                    source_location.id,
                    row.source_path,
                    destination_location.id,
                    row.destination_path,
                )
                db.flush()
                if not source_already_deleted:
                    storage_backends.delete_tree(
                        source_location,
                        row.source_path,
                        expected=expected,
                        expected_etag=details.get("source_etag", ""),
                        version_id=details.get("source_version_id", ""),
                        verified_meta=details.get("source_meta"),
                        operation_id=row.id,
                        missing_ok=False,
                    )
        except storage_backends.StorageVersionedDeleteRefused as exc:
            _record_source_delete_refusal(db, row, details, exc)
            raise FileOperationError(str(exc)) from exc
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
        details["source_delete_completed"] = True
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        final = work / "destination-after-delete"
        final_meta = _materialize(destination_location, row.destination_path, final)
        if fingerprint(final) != expected or not _same_published_destination_identity(
            destination_location,
            final_meta,
            stored_destination_meta,
        ):
            _finish_failed_move_survivor_recovery(
                db,
                row,
                details,
                source_location,
                destination_location,
            )
    _release_published_receipt(
        db,
        row,
        details,
        started_key="destination_receipt_release_started",
        location=destination_location,
        path=row.destination_path,
        operation_id=row.id,
        expected=expected,
    )
    if move:
        details.pop("survivor_recovery", None)
        details.pop("survivor_recovery_receipt_release_started", None)
    return details


def _execute_rename(db, row: FileOperation) -> dict:
    location = _location(db, row.source_location_id)
    if location.kind != "local":
        return _execute_transfer(db, row, location, location, move=True)
    source = _absolute(location, row.source_path)
    destination = _absolute(location, row.destination_path)
    _validate_destination(location.id, row.source_path, location.id, row.destination_path)
    details = json.loads(row.undo_json or "{}")
    recovery = details.get("survivor_recovery")
    if isinstance(recovery, dict) and recovery.get("state") != "armed":
        _finish_failed_move_survivor_recovery(db, row, details, location, location)

    def arm_rename_recovery(candidate: Path) -> None:
        snapshot = _workspace(row) / "source"
        expected_fingerprint = details.get("fingerprint")
        if not isinstance(expected_fingerprint, dict):
            raise FileOperationError("rename recovery fingerprint is missing")
        if snapshot.exists() or snapshot.is_symlink():
            if fingerprint(snapshot) != expected_fingerprint:
                raise FileOperationError("verified survivor snapshot changed during rename")
        else:
            _copy_verified(candidate, snapshot, f"rename-survivor-{row.id}")
        _arm_survivor_recovery(
            db,
            row,
            details,
            snapshot_name="source",
            location=location,
            path=row.source_path,
            undo=False,
        )

    staged_identity_key = "destination_staged_publication_identity"

    def persist_destination_identity(candidate: Path) -> str:
        publication_identity = _local_publication_identity(candidate)
        stored_identity = str(details.get(staged_identity_key) or "")
        if stored_identity:
            if publication_identity != stored_identity:
                raise FileOperationError("rename source identity changed during operation")
            return stored_identity
        details[staged_identity_key] = publication_identity
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        return publication_identity

    def record_destination_identity(publication_identity: str) -> None:
        try:
            destination_meta = storage_backends._local_path_receipt_identity(  # noqa: SLF001
                destination
            )
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
        if fingerprint(destination) != expected or (
            destination_meta.get("local_publication_identity") != publication_identity
        ):
            raise FileOperationError("rename destination verification failed")
        details["destination_meta"] = {**expected, **destination_meta}

    def owned_destination_matches() -> bool:
        destination_meta = details.get("destination_meta")
        return bool(
            isinstance(destination_meta, dict)
            and _same(destination, expected)
            and _same_local_path_publication_identity(destination, destination_meta)
        )

    if details.get("source_conflict_pending"):
        _finish_pending_source_conflict(db, row, details, source)
    expected = details.get("fingerprint")
    if expected and not source.exists() and _same(destination, expected):
        if not details.get("source_owned") or not _source_mutation_claim_owned(db, row):
            raise FileOperationError("source not found")
        if details.get("destination_owned"):
            if not owned_destination_matches():
                _finish_failed_move_survivor_recovery(db, row, details, location, location)
        else:
            stored_identity = str(details.get(staged_identity_key) or "")
            if not stored_identity or _local_publication_identity(destination) != stored_identity:
                _finish_failed_move_survivor_recovery(db, row, details, location, location)
            record_destination_identity(stored_identity)
            details["destination_owned"] = True
            details.pop(staged_identity_key, None)
        _rekey_metadata(db, location.id, row.source_path, location.id, row.destination_path)
        details["source_delete_completed"] = True
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        details.pop("survivor_recovery", None)
        return details
    quarantine = _quarantine_path(source, row.id)
    if expected and (quarantine.exists() or quarantine.is_symlink()):
        quarantine = _quarantine_operation_source(db, row, details, source, expected)
        if destination.exists() or destination.is_symlink():
            raise FileOperationError("destination already exists")
        arm_rename_recovery(quarantine)
        _record_local_source_ownership(db, row, details)
        publication_identity = persist_destination_identity(quarantine)
        _mkdir_parent(destination)
        _rename_no_replace(quarantine, destination)
        if (
            not _same(destination, expected)
            or _local_publication_identity(destination) != publication_identity
        ):
            _finish_failed_move_survivor_recovery(db, row, details, location, location)
        record_destination_identity(publication_identity)
        _rekey_metadata(db, location.id, row.source_path, location.id, row.destination_path)
        details["source_delete_completed"] = True
        details["destination_owned"] = True
        details.pop(staged_identity_key, None)
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
        details.pop("survivor_recovery", None)
        return details
    if (
        isinstance(recovery, dict)
        and isinstance(expected, dict)
        and not _same(source, expected)
        and not _same(destination, expected)
    ):
        _finish_failed_move_survivor_recovery(db, row, details, location, location)
    if not source.exists() and not source.is_symlink():
        raise FileOperationError("source not found")
    if destination.exists() or destination.is_symlink():
        raise FileOperationError("destination already exists")
    _ensure_metadata_destination_clear(db, location.id, row.destination_path)
    expected = fingerprint(source)
    details = {
        "fingerprint": expected,
        "destination_claimed": True,
        "destination_owned": False,
        "undo": "rename_back",
    }
    row.bytes_total = expected["size"]
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()
    _mkdir_parent(destination)
    arm_rename_recovery(source)
    details["source_quarantine_started"] = True
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()
    quarantine = _quarantine_operation_source(db, row, details, source, expected)
    _record_local_source_ownership(db, row, details)
    publication_identity = persist_destination_identity(quarantine)
    _rename_no_replace(quarantine, destination)
    if (
        not _same(destination, expected)
        or _local_publication_identity(destination) != publication_identity
    ):
        _finish_failed_move_survivor_recovery(db, row, details, location, location)
    record_destination_identity(publication_identity)
    _rekey_metadata(db, location.id, row.source_path, location.id, row.destination_path)
    details["destination_owned"] = True
    details["source_delete_completed"] = True
    details.pop(staged_identity_key, None)
    row.undo_json = json.dumps(details, sort_keys=True)
    db.commit()
    details.pop("survivor_recovery", None)
    row.bytes_done = expected["size"]
    return details


def _execute_delete(db, row: FileOperation) -> dict:
    location = _location(db, row.source_location_id)
    if location.kind != "local":
        return _execute_remote_delete(db, row, location)
    source = _absolute(location, row.source_path)
    details = json.loads(row.undo_json or "{}")
    if details.get("source_conflict_pending"):
        _finish_pending_source_conflict(db, row, details, source)
    trash_id = details.get("trash_id")
    if trash_id:
        item = db.get(TrashItem, trash_id)
        if not item:
            raise FileOperationError("trash record is missing")
        payload = json.loads(item.payload or "{}")
        stash = trash.stash_path(payload.get("trash_name", ""))
        expected = details.get("fingerprint") or {}
        quarantine = _quarantine_path(source, row.id)
        if (quarantine.exists() or quarantine.is_symlink()) and _same(stash, expected):
            quarantine = _quarantine_operation_source(db, row, details, source, expected)
            _record_local_source_ownership(db, row, details)
            _remove(quarantine)
            _detach_live_metadata_to_trash(db, item, location.id, row.source_path)
            return details
        if not source.exists() and _same(stash, expected):
            if not details.get("source_owned") or not _source_mutation_claim_owned(db, row):
                raise FileOperationError("source not found")
            _detach_live_metadata_to_trash(db, item, location.id, row.source_path)
            return details
        if not source.exists():
            raise FileOperationError("source disappeared before a verified trash copy existed")
        if stash.exists() or stash.is_symlink():
            if not _same(stash, expected):
                raise FileOperationError("verified trash copy changed during operation")
        else:
            _copy_verified(source, stash, row.id)
        if not _same(source, expected) or not _same(stash, expected):
            raise FileOperationError("trash verification failed")
        quarantine = _quarantine_operation_source(db, row, details, source, expected)
        _record_local_source_ownership(db, row, details)
        _remove(quarantine)
        _detach_live_metadata_to_trash(db, item, location.id, row.source_path)
        return details
    if not source.exists():
        raise FileOperationError("source not found")
    expected = fingerprint(source)
    trash_name = uuid.uuid4().hex + (source.suffix if source.is_file() else "")
    item = trash.record(
        db,
        "file",
        row.source_path,
        source.name,
        {"trash_name": trash_name, "is_dir": source.is_dir()},
        location_id=location.id,
        commit=False,
    )
    details = {"fingerprint": expected, "trash_id": item.id, "undo": "restore_trash"}
    row.undo_json = json.dumps(details, sort_keys=True)
    row.bytes_total = expected["size"]
    row.bytes_done = expected["size"]
    db.commit()
    stash = trash.stash_path(trash_name)
    _copy_verified(source, stash, row.id)
    if not _same(source, expected) or not _same(stash, expected):
        raise FileOperationError("trash verification failed")
    quarantine = _quarantine_operation_source(db, row, details, source, expected)
    _record_local_source_ownership(db, row, details)
    _remove(quarantine)
    _detach_live_metadata_to_trash(db, item, location.id, row.source_path)
    return details


def _execute_remote_delete(db, row: FileOperation, location) -> dict:
    details = json.loads(row.undo_json or "{}")
    trash_id = details.get("trash_id")
    if trash_id:
        item = db.get(TrashItem, trash_id)
        if item:
            payload = json.loads(item.payload or "{}")
            if location.kind == "webdav" and payload.get("is_dir"):
                raise FileOperationError(
                    "webdav folder deletion is unavailable because the server cannot guarantee a safe delete"
                )
            stash = trash.stash_path(payload.get("trash_name", ""))
            expected = details.get("fingerprint") or {}
            source_meta = details.get("source_meta")
            if stash.exists():
                if not _same(stash, expected):
                    raise FileOperationError("remote trash verification failed")
                if isinstance(source_meta, dict) and source_meta:
                    _delete_remote_operation_source(
                        db,
                        row,
                        details,
                        location,
                        expected=expected,
                        expected_etag=details.get("source_etag", ""),
                        version_id=details.get("source_version_id", ""),
                        verified_meta=source_meta,
                        operation_id=row.id,
                    )
                    _detach_live_metadata_to_trash(db, item, location.id, row.source_path)
                    return details
                check = _workspace(row) / "delete-retry-source"
                try:
                    _materialize(location, row.source_path, check)
                except FileOperationError as exc:
                    if isinstance(exc.__cause__, storage_backends.StorageNotFoundError):
                        _detach_live_metadata_to_trash(db, item, location.id, row.source_path)
                        return details
                    raise
                if fingerprint(check) != expected:
                    raise FileOperationError("source changed; delete stopped")
                _delete_remote_operation_source(
                    db,
                    row,
                    details,
                    location,
                    expected=expected,
                    expected_etag=details.get("source_etag", ""),
                    version_id=details.get("source_version_id", ""),
                    operation_id=row.id,
                )
                _detach_live_metadata_to_trash(db, item, location.id, row.source_path)
                return details
            retry_snapshot = _workspace(row) / "delete-source"
            try:
                _materialize(location, row.source_path, retry_snapshot)
            except FileOperationError as exc:
                if isinstance(exc.__cause__, storage_backends.StorageNotFoundError):
                    raise FileOperationError(
                        "source disappeared before a verified trash copy existed"
                    ) from exc
                raise
            if fingerprint(retry_snapshot) != expected:
                raise FileOperationError("source changed; delete stopped")
            retry_snapshot.rename(stash)
            if fingerprint(stash) != expected:
                raise FileOperationError("remote trash verification failed")
            _delete_remote_operation_source(
                db,
                row,
                details,
                location,
                expected=expected,
                expected_etag=details.get("source_etag", ""),
                version_id=details.get("source_version_id", ""),
                verified_meta=(source_meta if isinstance(source_meta, dict) else None),
                operation_id=row.id,
            )
            _detach_live_metadata_to_trash(db, item, location.id, row.source_path)
            return details
    work = _workspace(row)
    snapshot = work / "delete-source"
    source_meta = _materialize(location, row.source_path, snapshot)
    if _has_versioned_s3_source(location, source_meta):
        raise FileOperationError(
            "versioned s3 objects cannot be deleted atomically; source was preserved"
        )
    if location.kind == "webdav" and snapshot.is_dir():
        raise FileOperationError(
            "webdav folder deletion is unavailable because the server cannot guarantee a safe delete"
        )
    expected = fingerprint(snapshot)
    trash_name = uuid.uuid4().hex + (snapshot.suffix if snapshot.is_file() else "")
    item = trash.record(
        db,
        "file",
        row.source_path,
        Path(row.source_path).name,
        {
            "trash_name": trash_name,
            "is_dir": snapshot.is_dir(),
            "remote": True,
            "etag": source_meta.get("etag", ""),
            "version_id": source_meta.get("version_id", ""),
        },
        location_id=location.id,
        commit=False,
    )
    details = {
        "fingerprint": expected,
        "trash_id": item.id,
        "undo": "restore_trash",
        "remote": True,
        "source_etag": source_meta.get("etag", ""),
        "source_version_id": source_meta.get("version_id", ""),
        "source_meta": source_meta,
    }
    row.undo_json = json.dumps(details, sort_keys=True)
    row.bytes_total = expected["size"]
    row.bytes_done = expected["size"]
    db.commit()
    stash = trash.stash_path(trash_name)
    try:
        snapshot.rename(stash)
        if fingerprint(stash) != expected:
            raise FileOperationError("remote trash verification failed")
        _delete_remote_operation_source(
            db,
            row,
            details,
            location,
            expected=expected,
            expected_etag=details.get("source_etag", ""),
            version_id=details.get("source_version_id", ""),
            verified_meta=source_meta,
            operation_id=row.id,
        )
        _detach_live_metadata_to_trash(db, item, location.id, row.source_path)
        return details
    except Exception:
        if not stash.exists():
            db.delete(item)
            db.commit()
        raise


def _execute_restore(db, row: FileOperation) -> dict:
    location = _location(db, row.source_location_id)
    details = json.loads(row.undo_json or "{}")
    item = db.get(TrashItem, row.source_path)
    if item and (item.kind != "file" or item.location_id != location.id):
        raise FileOperationError("trash item not found")
    expected = details.get("fingerprint")
    destination_path = details.get("destination_path") or row.destination_path
    stash = None
    if item:
        payload = json.loads(item.payload or "{}")
        trash_name = payload.get("trash_name", "")
        stash = trash.stash_path(trash_name) if trash_name else None
        destination_path = destination_path or item.normalized_path or item.ref
    if expected is None:
        if not item or not stash or not stash.exists():
            raise FileOperationError("the trashed copy is missing")
        expected = fingerprint(stash)
        details = {
            "fingerprint": expected,
            "destination_path": destination_path,
            "trash_id": item.id,
            "destination_claimed": False,
            "destination_owned": False,
            "undo": "delete_restored",
        }
        row.destination_location_id = location.id
        row.destination_path = destination_path
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    if not destination_path:
        raise FileOperationError("restore destination is missing")
    if details.get("destination_path") != destination_path:
        details["destination_path"] = destination_path
        row.destination_location_id = location.id
        row.destination_path = destination_path
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    if isinstance(details.get("trash_survivor_recovery"), dict) and (
        item is None or stash is None or not _same(stash, expected)
    ):
        _finish_restore_rollback(db, row, location, destination_path)
    if location.kind != "local":
        return _execute_remote_restore(db, row, location, item, stash, details)
    destination = _absolute(location, destination_path)
    _ensure_trash_metadata_destination_clear(db, item, location.id, destination_path)
    destination_claimed = bool(
        details.get("destination_claimed") or details.get("destination_owned")
    )
    staged = _partial_copy_path(destination, row.id)
    staged_identity_key = "destination_staged_publication_identity"

    def record_destination_identity(publication_identity: str) -> None:
        try:
            destination_meta = storage_backends._local_path_receipt_identity(  # noqa: SLF001
                destination
            )
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
        if fingerprint(destination) != expected or (
            destination_meta.get("local_publication_identity") != publication_identity
        ):
            raise FileOperationError("restored file could not be verified")
        details["destination_meta"] = {**expected, **destination_meta}

    def owned_destination_matches() -> bool:
        destination_meta = details.get("destination_meta")
        if not isinstance(destination_meta, dict) or not _same(destination, expected):
            return False
        try:
            return storage_backends._same_local_path_receipt_identity(  # noqa: SLF001
                destination,
                destination_meta,
            )
        except storage_backends.StorageBackendError:
            return False

    if destination.exists() or destination.is_symlink():
        if details.get("destination_owned"):
            if not owned_destination_matches():
                raise FileOperationError("restore destination changed during operation")
        else:
            stored_identity = str(details.get(staged_identity_key) or "")
            if (
                not destination_claimed
                or staged.exists()
                or staged.is_symlink()
                or not stored_identity
                or not _same(destination, expected)
                or _local_publication_identity(destination) != stored_identity
            ):
                if isinstance(details.get("trash_survivor_recovery"), dict):
                    _finish_restore_rollback(db, row, location, destination_path)
                raise FileOperationError("restore destination already exists")
            record_destination_identity(stored_identity)
            details["destination_owned"] = True
            details.pop(staged_identity_key, None)
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
    else:
        if not stash or not stash.exists() or fingerprint(stash) != expected:
            raise FileOperationError("the trashed copy is missing")
        if not destination_claimed:
            details["destination_claimed"] = True
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        if staged.exists() or staged.is_symlink():
            if not _same(staged, expected):
                raise FileOperationError("staged restore changed during operation")
        else:
            _, staged = _prepare_verified_copy(
                stash,
                destination,
                row.id,
                expected=expected,
            )
        staged_identity = _local_publication_identity(staged)
        stored_identity = str(details.get(staged_identity_key) or "")
        if stored_identity and staged_identity != stored_identity:
            raise FileOperationError("staged restore identity changed during operation")
        if not stored_identity:
            details[staged_identity_key] = staged_identity
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        publication_identity = _publish_verified_copy(staged, destination, expected)
        if publication_identity != staged_identity:
            raise FileOperationError("restored file could not be verified")
        record_destination_identity(publication_identity)
        details["destination_owned"] = True
        details.pop(staged_identity_key, None)
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    recovery_snapshot = _workspace(row) / "restore-survivor"
    if recovery_snapshot.exists() or recovery_snapshot.is_symlink():
        if fingerprint(recovery_snapshot) != expected:
            raise FileOperationError("verified trash recovery snapshot changed")
    else:
        if stash is None or not _same(stash, expected):
            raise FileOperationError("the trashed copy is missing")
        _copy_verified(stash, recovery_snapshot, f"restore-survivor-{row.id}")
    if item is None:
        raise FileOperationError("trash record is missing")
    _arm_trash_survivor_recovery(
        db,
        row,
        details,
        item=item,
        snapshot_name="restore-survivor",
    )
    _restore_trash_metadata(db, item, location.id, destination_path)
    if stash and stash.exists():
        _remove(stash)
    if not _same(destination, expected):
        _finish_restore_rollback(db, row, location, destination_path)
    if item:
        db.delete(item)
    _clear_trash_survivor_recovery(row, details)
    return details


def _execute_remote_restore(db, row, location, item, stash: Path | None, details: dict) -> dict:
    destination_path = details["destination_path"]
    expected = details["fingerprint"]
    _ensure_trash_metadata_destination_clear(db, item, location.id, destination_path)
    existing = _workspace(row) / "restore-existing"
    existing_meta = _destination_snapshot(location, destination_path, existing)
    destination_owned = bool(details.get("destination_owned"))
    receipt_owned = bool(
        not destination_owned
        and existing_meta is not None
        and storage_backends.operation_receipt_matches(
            location,
            destination_path,
            row.id,
            expected,
        )
    )
    if existing_meta is not None:
        if (not destination_owned and not receipt_owned) or fingerprint(existing) != expected:
            if isinstance(details.get("trash_survivor_recovery"), dict):
                _finish_restore_rollback(db, row, location, destination_path)
            if details.get("upload_started") and not destination_owned and not receipt_owned:
                _record_upload_cleanup_safety(
                    db,
                    row,
                    details,
                    location,
                    destination_path,
                )
            raise FileOperationError("restore destination already exists")
    uploaded_meta = None
    if not destination_owned and not receipt_owned:
        if not stash or not stash.exists() or fingerprint(stash) != expected:
            raise FileOperationError("the trashed copy is missing")
        if not details.get("upload_started"):
            details["upload_started"] = True
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        if "upload_cleanup_safe" in details:
            details.pop("upload_cleanup_safe", None)
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        try:
            uploaded_meta = storage_backends.upload_tree(
                location,
                destination_path,
                stash,
                operation_id=row.id,
            )
        except storage_backends.StorageBackendError as exc:
            _record_upload_cleanup_safety(
                db,
                row,
                details,
                location,
                destination_path,
            )
            raise FileOperationError(str(exc)) from exc
    verify = _workspace(row) / "restore-verify"
    destination_meta = _materialize(location, destination_path, verify)
    if fingerprint(verify) != expected:
        raise FileOperationError("restored file could not be verified")
    if uploaded_meta is not None and stash is not None:
        _require_uploaded_identity(location, stash, uploaded_meta, destination_meta)
        try:
            storage_backends.seal_operation_receipt(
                location,
                destination_path,
                row.id,
                expected,
                uploaded_meta,
            )
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
    if not details.get("destination_owned"):
        if not storage_backends.operation_receipt_matches(
            location,
            destination_path,
            row.id,
            expected,
        ):
            raise FileOperationError("destination ownership receipt is missing")
        details["destination_owned"] = True
        details.pop("upload_started", None)
        details["destination_etag"] = destination_meta.get("etag", "")
        details["destination_version_id"] = destination_meta.get("version_id", "")
        details["destination_meta"] = destination_meta
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    elif not isinstance(details.get("destination_meta"), dict):
        details["destination_meta"] = destination_meta
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    if item is None:
        raise FileOperationError("trash record is missing")
    _arm_trash_survivor_recovery(
        db,
        row,
        details,
        item=item,
        snapshot_name="restore-verify",
    )
    _restore_trash_metadata(db, item, location.id, destination_path)
    if stash and stash.exists():
        _remove(stash)
    final = _workspace(row) / "restore-after-trash-delete"
    final_meta = _materialize(location, destination_path, final)
    if fingerprint(final) != expected or not _same_published_destination_identity(
        location,
        final_meta,
        details["destination_meta"],
    ):
        _finish_restore_rollback(db, row, location, destination_path)
    _release_published_receipt(
        db,
        row,
        details,
        started_key="destination_receipt_release_started",
        location=location,
        path=destination_path,
        operation_id=row.id,
        expected=expected,
    )
    if item:
        db.delete(item)
    _clear_trash_survivor_recovery(row, details)
    details["remote"] = True
    return details


def run(db, row: FileOperation) -> FileOperation:
    if row.state == "completed":
        return row
    if row.state == "cancelled":
        raise FileOperationError("operation is cancelled")
    claimed = (
        db.query(FileOperation)
        .filter(
            FileOperation.id == row.id,
            FileOperation.state.in_(("queued", "failed")),
        )
        .update(
            {FileOperation.state: "running", FileOperation.error_code: ""},
            synchronize_session=False,
        )
    )
    db.commit()
    if claimed != 1:
        db.expire_all()
        current = db.get(FileOperation, row.id)
        if current is None:
            raise FileOperationError("operation not found")
        if current.state == "completed":
            return current
        if current.state == "cancelled":
            raise FileOperationError("operation is cancelled")
        raise FileOperationError("operation is already running")
    db.refresh(row)
    try:
        _require_run_access(db, row)
        _acquire_source_mutation_claim(db, row)
        _acquire_operation_path_claims(db, row)
        if row.action == "copy":
            details = _execute_copy_or_move(db, row, move=False)
        elif row.action == "move":
            details = _execute_copy_or_move(db, row, move=True)
        elif row.action == "rename":
            details = _execute_rename(db, row)
        elif row.action == "delete":
            details = _execute_delete(db, row)
        elif row.action == "restore":
            details = _execute_restore(db, row)
        else:
            raise FileOperationError("unsupported Files operation")
        row.undo_json = json.dumps(details, sort_keys=True)
        row.state = "completed"
        row.error_code = ""
        _release_operation_claims(db, row)
        db.commit()
        db.refresh(row)
        _clean_workspace(row)
        return row
    except (_SurvivorRecovered, _RestoreRolledBack) as exc:
        db.rollback()
        current = db.get(FileOperation, row.id)
        if current is not None:
            current.state = "failed"
            current.error_code = str(exc)[:160]
            _release_operation_claims(db, current)
            db.commit()
        _clean_workspace(row)
        raise FileOperationError(str(exc)) from exc
    except _SourceConflictPublished as exc:
        db.rollback()
        db.refresh(row)
        try:
            conflict_details = json.loads(row.undo_json or "{}")
        except (TypeError, ValueError):
            conflict_details = {}
        conflict_details["source_conflict_path"] = exc.path
        conflict_details["source_conflict_fingerprint"] = exc.conflict_fingerprint
        conflict_details["source_conflict_published"] = True
        conflict_details.pop("source_conflict_pending", None)
        row.undo_json = json.dumps(conflict_details, sort_keys=True)
        row.state = "failed"
        row.error_code = str(exc)[:160]
        _release_operation_claims(db, row)
        db.commit()
        raise FileOperationError(str(exc)) from exc
    except Exception as exc:
        db.rollback()
        db.refresh(row)
        try:
            failure_details = json.loads(row.undo_json or "{}")
        except (TypeError, ValueError):
            failure_details = {}
        if not _has_recoverable_side_effects(row, failure_details):
            _release_operation_claims(db, row)
        row.state = "failed"
        row.error_code = str(exc)[:160] or "operation_failed"
        db.commit()
        if isinstance(exc, FileOperationError):
            raise
        raise FileOperationError("Files operation failed") from exc


def cancel(db, row: FileOperation) -> FileOperation:
    current = db.get(FileOperation, row.id)
    if current is None:
        raise FileOperationError("operation not found")
    try:
        details = json.loads(current.undo_json or "{}")
    except (TypeError, ValueError):
        details = {}
    if _has_recoverable_side_effects(current, details):
        raise FileOperationError("operation must finish recovery before it can be cancelled")
    changed = (
        db.query(FileOperation)
        .filter(FileOperation.id == row.id, FileOperation.state == "queued")
        .update(
            {FileOperation.state: "cancelled", FileOperation.error_code: "cancelled"},
            synchronize_session=False,
        )
    )
    if changed != 1:
        db.rollback()
        raise FileOperationError("only a queued operation can be cancelled")
    _release_operation_claims(db, current)
    db.commit()
    db.refresh(row)
    return row


def retry(db, row: FileOperation) -> FileOperation:
    if row.state not in {"failed", "cancelled"}:
        raise FileOperationError("operation cannot be retried")
    try:
        details = json.loads(row.undo_json or "{}")
    except (TypeError, ValueError):
        details = {}
    if details.get("source_conflict_published") or details.get("survivor_recovered"):
        raise FileOperationError("verified recovery was preserved; discard this failed operation")
    changed = (
        db.query(FileOperation)
        .filter(
            FileOperation.id == row.id,
            FileOperation.state.in_(("failed", "cancelled")),
        )
        .update(
            {FileOperation.state: "queued", FileOperation.error_code: ""},
            synchronize_session=False,
        )
    )
    db.commit()
    if changed != 1:
        db.expire_all()
        raise FileOperationError("operation cannot be retried")
    db.refresh(row)
    return run(db, row)


def discard(db, row: FileOperation) -> None:
    try:
        details = json.loads(row.undo_json or "{}")
    except (TypeError, ValueError):
        details = {}
    cleanup_only_upload = _has_cleanup_only_upload(details)
    allowed = row.state == "completed" or (
        row.state in {"failed", "cancelled"}
        and (not _has_recoverable_side_effects(row, details) or cleanup_only_upload)
    )
    if not allowed:
        raise FileOperationError("operation has recoverable side effects; retry or undo it first")
    if cleanup_only_upload:
        expected = details.get("fingerprint")
        if not isinstance(expected, dict) or not row.destination_path:
            raise FileOperationError("incomplete upload recovery state is invalid")
        destination_location = _location(db, row.destination_location_id or row.source_location_id)
        try:
            cleanup_safe = storage_backends.incomplete_operation_upload_is_releasable(
                destination_location,
                row.destination_path,
                row.id,
                expected,
            )
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
        if not cleanup_safe:
            raise FileOperationError(
                "incomplete upload private artifacts cannot be released safely"
            )
        if not details.get("upload_cleanup_claimed"):
            details["upload_cleanup_claimed"] = True
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        try:
            storage_backends.release_incomplete_operation_upload(
                destination_location,
                row.destination_path,
                row.id,
                expected,
                ownership_was_claimed=True,
            )
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
    _clean_workspace(row)
    _release_operation_claims(db, row)
    db.delete(row)
    db.commit()


def undo(db, row: FileOperation) -> FileOperation:
    try:
        undo_details = json.loads(row.undo_json or "{}")
    except (TypeError, ValueError):
        undo_details = {}
    if undo_details.get("source_conflict_published") or undo_details.get("survivor_recovered"):
        raise FileOperationError("verified recovery was preserved; discard this operation")
    failed_recovery = row.state == "failed" and _has_undoable_side_effects(row, undo_details)
    if row.state not in {"completed", "undoing"} and not failed_recovery:
        if row.state == "undoing_claimed":
            raise FileOperationError("operation undo is already running")
        raise FileOperationError("operation is not ready to undo")
    return_state_after_safe_refusal = "failed" if failed_recovery else "completed"
    claimed = (
        db.query(FileOperation)
        .filter(
            FileOperation.id == row.id,
            FileOperation.state.in_(("completed", "undoing", "failed")),
        )
        .update(
            {FileOperation.state: "undoing_claimed", FileOperation.error_code: ""},
            synchronize_session=False,
        )
    )
    db.commit()
    if claimed != 1:
        db.expire_all()
        current = db.get(FileOperation, row.id)
        if current is not None and current.state == "undoing_claimed":
            raise FileOperationError("operation undo is already running")
        raise FileOperationError("operation is not ready to undo")
    db.refresh(row)
    details = json.loads(row.undo_json or "{}")
    if details.get("undo_return_state") != return_state_after_safe_refusal:
        details["undo_return_state"] = return_state_after_safe_refusal
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    expected = details.get("fingerprint") or {}
    source_location = _location(db, row.source_location_id)
    destination_location = _location(db, row.destination_location_id or row.source_location_id)
    try:
        _acquire_source_mutation_claim(db, row)
        _acquire_operation_path_claims(db, row)
        _require_undo_access(source_location, destination_location, details)
        nonlocal_operation = _remote_or_cross(source_location, destination_location)
        if (
            details.get("undo") in {"move_back", "rename_back"}
            and not nonlocal_operation
            and not _is_pre_source_mutation_move(row, details)
        ):
            _ensure_metadata_destination_clear(db, source_location.id, row.source_path)
        if nonlocal_operation:
            _undo_nonlocal(
                db,
                row,
                details,
                expected,
                source_location,
                destination_location,
            )
        else:
            _undo_local(
                db,
                row,
                details,
                expected,
                source_location,
                destination_location,
            )
        details.pop("undo_return_state", None)
        row.undo_json = json.dumps(details, sort_keys=True)
        row.state = "undone"
        row.error_code = ""
        _release_operation_claims(db, row)
        db.commit()
        db.refresh(row)
        _clean_workspace(row)
        return row
    except (_SurvivorRecovered, _RestoreRolledBack) as exc:
        db.rollback()
        current = db.get(FileOperation, row.id)
        if current is not None:
            current.state = return_state_after_safe_refusal
            current.error_code = str(exc)[:160]
            _release_operation_claims(db, current)
            db.commit()
        _clean_workspace(row)
        raise FileOperationError(str(exc)) from exc
    except Exception as exc:
        db.rollback()
        current = db.get(FileOperation, row.id)
        if current:
            try:
                current_details = json.loads(current.undo_json or "{}")
            except (TypeError, ValueError):
                current_details = {}
            undo_mutated = bool(
                current_details.get("undo_mutation_started")
                or current_details.get("undo_source_owned")
                or current_details.get("undo_trash_id")
            )
            current.state = "undoing" if undo_mutated else return_state_after_safe_refusal
            current.error_code = str(exc)[:160] or "undo_failed"
            if not undo_mutated:
                _release_operation_claims(db, current)
            db.commit()
        if isinstance(exc, FileOperationError):
            raise
        raise FileOperationError("Files undo failed") from exc


def _undo_local(
    db,
    row: FileOperation,
    details: dict,
    expected: dict,
    source_location,
    destination_location,
) -> None:
    source = _absolute(source_location, row.source_path)
    destination = (
        _absolute(destination_location, row.destination_path) if row.destination_path else None
    )
    action = details.get("undo")
    recovery = _adopt_run_survivor_recovery_for_undo(
        db,
        row,
        details,
        source_location,
    )

    def finish_survivor_recovery() -> None:
        _finish_undo_survivor_recovery(
            db,
            row,
            details,
            source_location,
            destination_location,
        )

    if isinstance(recovery, dict):
        if recovery.get("state") != "armed" or (
            (source.exists() or source.is_symlink()) and not _same(source, expected)
        ):
            finish_survivor_recovery()
    recovered_operation_quarantine = False
    if action in {"move_back", "rename_back"}:
        recovered_operation_quarantine = _recover_local_operation_quarantine_for_undo(
            db,
            row,
            details,
            source,
            expected,
        )
    if action == "remove_copy" or (
        action == "move_back"
        and (_is_pre_source_mutation_move(row, details) or recovered_operation_quarantine)
        and _same(source, expected)
    ):
        if not _same(source, expected) or not destination:
            if isinstance(recovery, dict):
                finish_survivor_recovery()
            raise FileOperationError("copy changed; undo would risk the only verified copy")
        stored_destination_meta = details.get("destination_meta")
        if not isinstance(stored_destination_meta, dict):
            raise FileOperationError("copy destination identity is missing; undo stopped")
        detached = _quarantine_path(destination, f"undo-{row.id}")
        if isinstance(recovery, dict) and (detached.exists() or detached.is_symlink()):
            if not _same(detached, expected):
                raise FileOperationError("quarantined copy changed during undo")
            if not _same_local_path_publication_identity(detached, stored_destination_meta):
                if not (destination.exists() or destination.is_symlink()):
                    _restore_detached(detached, destination)
                raise FileOperationError("copy destination identity changed; undo stopped")
            _remove(detached)
            if not _same(source, expected):
                finish_survivor_recovery()
            _disarm_survivor_recovery(row, details)
            _purge_live_metadata(db, destination_location.id, row.destination_path)
            return
        if destination.exists() or destination.is_symlink():
            if not _same(destination, expected):
                if isinstance(recovery, dict):
                    _disarm_survivor_recovery(row, details)
                    return
                raise FileOperationError("copy changed; undo would risk the only verified copy")
            recovery_snapshot = _workspace(row) / "undo-local-destination"
            if recovery_snapshot.exists() or recovery_snapshot.is_symlink():
                if fingerprint(recovery_snapshot) != expected:
                    raise FileOperationError("verified survivor snapshot changed during undo")
            else:
                _copy_verified(
                    destination,
                    recovery_snapshot,
                    f"undo-survivor-{row.id}",
                )
            _arm_survivor_recovery(
                db,
                row,
                details,
                snapshot_name="undo-local-destination",
                location=destination_location,
                path=row.destination_path,
                undo=True,
                metadata_origin="source",
            )
            _mark_undo_mutation_started(db, row, details)
            detached = _quarantine_verified_publication(
                destination,
                expected,
                stored_destination_meta,
                f"undo-{row.id}",
            )
            if not _same(source, expected):
                if _same(detached, expected):
                    _remove(detached)
                finish_survivor_recovery()
            if not _same(detached, expected):
                finish_survivor_recovery()
            _remove(detached)
            if not _same(source, expected):
                finish_survivor_recovery()
            _disarm_survivor_recovery(row, details)
        elif isinstance(recovery, dict):
            _disarm_survivor_recovery(row, details)
        _purge_live_metadata(db, destination_location.id, row.destination_path)
        return
    if action in {"move_back", "rename_back"}:
        stored_destination_meta = details.get("destination_meta")
        if source.exists() or source.is_symlink():
            if isinstance(recovery, dict) and _same(source, expected):
                if not _same_local_path_publication_identity(source, stored_destination_meta):
                    finish_survivor_recovery()
                _rekey_metadata(
                    db,
                    destination_location.id,
                    row.destination_path,
                    source_location.id,
                    row.source_path,
                )
                _disarm_survivor_recovery(row, details)
                return
            if not _same(source, expected) or (
                destination and (destination.exists() or destination.is_symlink())
            ):
                raise FileOperationError("moved file changed; undo stopped")
        else:
            if not destination or not _same(destination, expected):
                if isinstance(recovery, dict):
                    finish_survivor_recovery()
                raise FileOperationError("moved file changed; undo stopped")
            if not _same_local_path_publication_identity(destination, stored_destination_meta):
                raise FileOperationError("move destination identity changed; undo stopped")
            recovery_snapshot = _workspace(row) / "undo-local-moved"
            if recovery_snapshot.exists() or recovery_snapshot.is_symlink():
                if fingerprint(recovery_snapshot) != expected:
                    raise FileOperationError("verified survivor snapshot changed during undo")
            else:
                _copy_verified(
                    destination,
                    recovery_snapshot,
                    f"undo-move-survivor-{row.id}",
                )
            _arm_survivor_recovery(
                db,
                row,
                details,
                snapshot_name="undo-local-moved",
                location=destination_location,
                path=row.destination_path,
                undo=True,
                metadata_origin="destination",
            )
            _mkdir_parent(source)
            _mark_undo_mutation_started(db, row, details)
            _rename_no_replace(destination, source)
            if not _same(source, expected) or not _same_local_path_publication_identity(
                source, stored_destination_meta
            ):
                finish_survivor_recovery()
        _rekey_metadata(
            db,
            destination_location.id,
            row.destination_path,
            source_location.id,
            row.source_path,
        )
        _disarm_survivor_recovery(row, details)
        return
    if action == "restore_trash":
        item = db.get(TrashItem, details.get("trash_id"))
        payload = json.loads(item.payload or "{}") if item else {}
        trash_name = str(payload.get("trash_name") or "")
        stash = trash.stash_path(trash_name) if item and trash_name else None
        if isinstance(details.get("trash_survivor_recovery"), dict) and (
            item is None or stash is None or not _same(stash, expected)
        ):
            _finish_restore_rollback(
                db,
                row,
                source_location,
                row.source_path,
                undo=True,
            )

        def arm_trash_recovery(candidate: Path) -> None:
            recovery_snapshot = _workspace(row) / "undo-trash-survivor"
            if recovery_snapshot.exists() or recovery_snapshot.is_symlink():
                if fingerprint(recovery_snapshot) != expected:
                    raise FileOperationError("verified trash recovery snapshot changed")
            else:
                _copy_verified(candidate, recovery_snapshot, f"undo-trash-survivor-{row.id}")
            if item is None:
                raise FileOperationError("trash record is missing")
            _arm_trash_survivor_recovery(
                db,
                row,
                details,
                item=item,
                snapshot_name="undo-trash-survivor",
            )

        _ensure_trash_metadata_destination_clear(db, item, source_location.id, row.source_path)
        _recover_local_operation_quarantine_for_undo(db, row, details, source, expected)
        if source.exists() or source.is_symlink():
            if not _same(source, expected):
                raise FileOperationError("trash restore is no longer safe")
            if item:
                if stash is not None and (stash.exists() or stash.is_symlink()):
                    if not _same(stash, expected):
                        raise FileOperationError("trashed copy changed; undo stopped")
                    arm_trash_recovery(stash)
                    _mark_undo_mutation_started(db, row, details)
                    _remove(stash)
                    if not _same(source, expected):
                        _finish_restore_rollback(
                            db,
                            row,
                            source_location,
                            row.source_path,
                            undo=True,
                        )
                _restore_trash_metadata(db, item, source_location.id, row.source_path)
                db.delete(item)
                _clear_trash_survivor_recovery(row, details)
            return
        if not item:
            raise FileOperationError("trash restore is no longer safe")
        if stash is None or not _same(stash, expected):
            raise FileOperationError("trashed copy changed; undo stopped")
        _mark_undo_mutation_started(db, row, details)
        _copy_verified(stash, source, f"undo-{row.id}")
        if not _same(source, expected):
            raise FileOperationError("restored file could not be verified")
        arm_trash_recovery(stash)
        _restore_trash_metadata(db, item, source_location.id, row.source_path)
        _remove(stash)
        if not _same(source, expected):
            _finish_restore_rollback(
                db,
                row,
                source_location,
                row.source_path,
                undo=True,
            )
        db.delete(item)
        _clear_trash_survivor_recovery(row, details)
        return
    if action == "delete_restored":
        restored = destination
        if not restored:
            raise FileOperationError("restored file changed; undo stopped")
        _undo_delete_local(db, row, details, expected, restored, destination_location)
        return
    raise FileOperationError("operation has no undo")


def _undo_delete_local(
    db,
    row: FileOperation,
    details: dict,
    expected: dict,
    restored: Path,
    location,
) -> None:
    _mark_undo_mutation_started(db, row, details)
    undo_trash_id = details.get("undo_trash_id")
    item = db.get(TrashItem, undo_trash_id) if undo_trash_id else None
    if item:
        payload = json.loads(item.payload or "{}")
        trash_name = payload.get("trash_name", "")
    else:
        if not _same(restored, expected):
            raise FileOperationError("restored file changed; undo stopped")
        trash_name = uuid.uuid4().hex + (restored.suffix if restored.is_file() else "")
        item = trash.record(
            db,
            "file",
            row.destination_path,
            restored.name,
            {"trash_name": trash_name, "is_dir": restored.is_dir()},
            location_id=location.id,
            commit=False,
        )
        details["undo_trash_id"] = item.id
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    stash = trash.stash_path(trash_name)
    if not (stash.exists() or stash.is_symlink()):
        if not _same(restored, expected):
            raise FileOperationError("restored file changed; undo stopped")
        _copy_verified(restored, stash, f"undo-{row.id}")
    if not _same(stash, expected):
        raise FileOperationError("trash verification failed")
    _detach_live_metadata_to_trash(db, item, location.id, row.destination_path)
    if restored.exists() or restored.is_symlink():
        quarantine = _quarantine_verified(restored, expected, f"undo-{row.id}")
        _remove(quarantine)
        if not _same(stash, expected):
            raise FileOperationError("trash copy changed during undo")


def _verified_snapshot(location, path: str, target: Path, expected: dict) -> Path:
    _materialize(location, path, target)
    if fingerprint(target) != expected:
        raise FileOperationError("file changed; undo stopped")
    return target


def _require_absent(location, path: str, target: Path) -> None:
    existing = _destination_snapshot(location, path, target)
    if existing is not None:
        raise FileOperationError("undo destination already exists")


def _delete_owned_s3_destination(
    db,
    row: FileOperation,
    details: dict,
    expected: dict,
    location,
    path: str,
    *,
    operation_id: str,
    snapshot_name: str,
    purge_metadata: bool = True,
) -> bool:
    """Delete only this operation's S3 version and preserve any live successor."""
    version_id = details.get("destination_version_id", "")
    if location.kind != "s3" or not _is_exact_s3_version_id(version_id):
        return False
    _mark_undo_mutation_started(db, row, details)
    try:
        storage_backends.delete_tree(
            location,
            path,
            expected=expected,
            expected_etag=details.get("destination_etag", ""),
            version_id=version_id,
            operation_id=operation_id,
            owned_version=True,
        )
    except storage_backends.StorageBackendError as exc:
        raise FileOperationError(str(exc)) from exc
    remaining = _destination_snapshot(
        location,
        path,
        _workspace(row) / snapshot_name,
    )
    if remaining is None and purge_metadata:
        _purge_live_metadata(db, location.id, path)
    return True


def _undo_nonlocal(
    db,
    row: FileOperation,
    details: dict,
    expected: dict,
    source_location,
    destination_location,
) -> None:
    action = details.get("undo")
    work = _workspace(row)

    def finish_survivor_recovery() -> None:
        _finish_undo_survivor_recovery(
            db,
            row,
            details,
            source_location,
            destination_location,
        )

    recovery = _adopt_run_survivor_recovery_for_undo(
        db,
        row,
        details,
        source_location,
    )
    if isinstance(recovery, dict) and recovery.get("state") != "armed":
        finish_survivor_recovery()

    def verify_original_source(snapshot_name: str, message: str) -> dict:
        snapshot = work / snapshot_name
        metadata = _materialize(source_location, row.source_path, snapshot)
        stored = details.get("source_meta")
        if (
            fingerprint(snapshot) != expected
            or not isinstance(stored, dict)
            or not (
                _same_published_destination_identity(source_location, metadata, stored)
                or _source_identity_matches_refusal(metadata, details)
            )
        ):
            raise FileOperationError(message)
        return metadata

    remove_published_destination = action == "remove_copy"
    pre_source_mutation_move = _is_pre_source_mutation_move(row, details)
    if remove_published_destination:
        try:
            source_meta = verify_original_source(
                "undo-source",
                "copy changed; undo would risk the only verified copy",
            )
        except FileOperationError:
            if isinstance(recovery, dict):
                finish_survivor_recovery()
            raise
    elif pre_source_mutation_move:
        source_meta = _destination_snapshot(
            source_location,
            row.source_path,
            work / "undo-source",
        )
        if source_meta is None and isinstance(recovery, dict):
            finish_survivor_recovery()
        if source_meta is not None:
            if fingerprint(
                work / "undo-source"
            ) != expected or not _same_published_destination_identity(
                source_location,
                source_meta,
                details.get("source_meta"),
            ):
                raise FileOperationError("move source changed; undo stopped")
            remove_published_destination = True
    if remove_published_destination:
        if (
            pre_source_mutation_move
            and source_location.kind != "local"
            and not _same_remote_identity(source_meta, details.get("source_meta"))
        ):
            raise FileOperationError("move source changed; undo stopped")
        exact_s3_destination = bool(
            destination_location.kind == "s3"
            and _is_exact_s3_version_id(details.get("destination_version_id"))
        )
        if exact_s3_destination:
            _arm_survivor_recovery(
                db,
                row,
                details,
                snapshot_name="undo-source",
                location=destination_location,
                path=row.destination_path,
                undo=True,
                metadata_origin="source",
            )
        if exact_s3_destination and _delete_owned_s3_destination(
            db,
            row,
            details,
            expected,
            destination_location,
            row.destination_path,
            operation_id=f"undo-{row.id}",
            snapshot_name="undo-destination-after-owned-delete",
        ):
            try:
                verify_original_source(
                    "undo-source-after-owned-delete",
                    "copy source changed during undo",
                )
            except FileOperationError:
                finish_survivor_recovery()
            _disarm_survivor_recovery(row, details)
            return
        destination = _destination_snapshot(
            destination_location,
            row.destination_path,
            work / "undo-destination",
        )
        if destination is None:
            _disarm_survivor_recovery(row, details)
            _purge_live_metadata(db, destination_location.id, row.destination_path)
            return
        if fingerprint(work / "undo-destination") != expected:
            if isinstance(recovery, dict):
                _disarm_survivor_recovery(row, details)
                return
            raise FileOperationError("copy changed; undo would risk the only verified copy")
        stored_destination_meta = details.get("destination_meta")
        if not isinstance(stored_destination_meta, dict) or not (
            _same_published_destination_identity(
                destination_location,
                destination,
                stored_destination_meta,
            )
        ):
            if isinstance(recovery, dict):
                _disarm_survivor_recovery(row, details)
                return
            raise FileOperationError("copy destination identity changed; undo stopped")
        _arm_survivor_recovery(
            db,
            row,
            details,
            snapshot_name="undo-source",
            location=destination_location,
            path=row.destination_path,
            undo=True,
            metadata_origin="source",
        )
        _mark_undo_mutation_started(db, row, details)
        try:
            storage_backends.delete_tree(
                destination_location,
                row.destination_path,
                expected=expected,
                expected_etag=details.get("destination_etag", ""),
                version_id=details.get("destination_version_id", ""),
                verified_meta=(
                    stored_destination_meta if destination_location.kind == "local" else destination
                ),
                operation_id=f"undo-{row.id}",
                owned_version=bool(
                    destination_location.kind == "s3"
                    and _is_exact_s3_version_id(details.get("destination_version_id"))
                ),
            )
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
        after_delete = work / "undo-copy-destination-after-delete"
        after_delete_meta = _destination_snapshot(
            destination_location,
            row.destination_path,
            after_delete,
        )
        try:
            verify_original_source(
                "undo-source-after-destination-delete",
                "copy source changed during undo",
            )
        except FileOperationError:
            finish_survivor_recovery()
        if after_delete_meta is not None:
            if fingerprint(after_delete) == expected and _same_published_destination_identity(
                destination_location,
                after_delete_meta,
                destination,
            ):
                raise FileOperationError("copy destination still exists; undo stopped")
            _disarm_survivor_recovery(row, details)
            return
        _disarm_survivor_recovery(row, details)
        _purge_live_metadata(db, destination_location.id, row.destination_path)
        return
    if action in {"move_back", "rename_back"}:
        undo_id = f"undo-{row.id}"
        source_snapshot = work / "undo-source-check"
        source_meta = _destination_snapshot(source_location, row.source_path, source_snapshot)
        original_source_intact = bool(
            details.get("destination_owned")
            and details.get("source_delete_started")
            and source_meta is not None
            and fingerprint(source_snapshot) == expected
            and (
                _same_published_destination_identity(
                    source_location,
                    source_meta,
                    details.get("source_meta"),
                )
                or _source_identity_matches_refusal(source_meta, details)
            )
        )
        if isinstance(recovery, dict):
            recovery_source_meta = details.get("undo_source_meta")
            if not isinstance(recovery_source_meta, dict):
                recovery_source_meta = details.get("source_meta")
            recovery_source_valid = bool(
                source_meta is not None
                and fingerprint(source_snapshot) == expected
                and isinstance(recovery_source_meta, dict)
                and (
                    _same_published_destination_identity(
                        source_location,
                        source_meta,
                        recovery_source_meta,
                    )
                    or _source_identity_matches_refusal(source_meta, details)
                )
            )
            if not recovery_source_valid:
                finish_survivor_recovery()
        if original_source_intact:
            exact_s3_destination = bool(
                destination_location.kind == "s3"
                and _is_exact_s3_version_id(details.get("destination_version_id"))
            )
            if exact_s3_destination:
                _arm_survivor_recovery(
                    db,
                    row,
                    details,
                    snapshot_name="undo-source-check",
                    location=destination_location,
                    path=row.destination_path,
                    undo=True,
                    metadata_origin="source",
                )
            if exact_s3_destination and _delete_owned_s3_destination(
                db,
                row,
                details,
                expected,
                destination_location,
                row.destination_path,
                operation_id=undo_id,
                snapshot_name="undo-late-move-after-owned-delete",
            ):
                try:
                    verify_original_source(
                        "undo-late-move-source-after-owned-delete",
                        "move source changed during undo",
                    )
                except FileOperationError:
                    finish_survivor_recovery()
                _disarm_survivor_recovery(row, details)
                return
            destination_snapshot = work / "undo-late-move-destination"
            destination_meta = _destination_snapshot(
                destination_location,
                row.destination_path,
                destination_snapshot,
            )
            if destination_meta is None:
                if isinstance(recovery, dict):
                    _disarm_survivor_recovery(row, details)
                return
            stored_destination_meta = details.get("destination_meta")
            if not isinstance(stored_destination_meta, dict):
                stored_destination_meta = {
                    "etag": details.get("destination_etag", ""),
                    "version_id": details.get("destination_version_id", ""),
                }
            destination_identity_matches = _same_published_destination_identity(
                destination_location,
                destination_meta,
                stored_destination_meta,
            )
            if fingerprint(destination_snapshot) != expected or not destination_identity_matches:
                if isinstance(recovery, dict):
                    _disarm_survivor_recovery(row, details)
                    return
                raise FileOperationError("move destination changed; undo stopped")
            _arm_survivor_recovery(
                db,
                row,
                details,
                snapshot_name="undo-source-check",
                location=destination_location,
                path=row.destination_path,
                undo=True,
                metadata_origin="source",
            )
            _mark_undo_mutation_started(db, row, details)
            try:
                storage_backends.delete_tree(
                    destination_location,
                    row.destination_path,
                    expected=expected,
                    expected_etag=details.get("destination_etag", ""),
                    version_id=details.get("destination_version_id", ""),
                    verified_meta=destination_meta,
                    operation_id=undo_id,
                    owned_version=bool(
                        destination_location.kind == "s3"
                        and _is_exact_s3_version_id(details.get("destination_version_id"))
                    ),
                )
            except storage_backends.StorageBackendError as exc:
                raise FileOperationError(str(exc)) from exc
            after_delete = work / "undo-late-move-destination-after-delete"
            after_delete_meta = _destination_snapshot(
                destination_location,
                row.destination_path,
                after_delete,
            )
            try:
                verify_original_source(
                    "undo-late-move-source-after-destination-delete",
                    "move source changed during undo",
                )
            except FileOperationError:
                finish_survivor_recovery()
            if after_delete_meta is not None:
                if fingerprint(after_delete) == expected and _same_published_destination_identity(
                    destination_location,
                    after_delete_meta,
                    destination_meta,
                ):
                    raise FileOperationError("move destination still exists; undo stopped")
                _disarm_survivor_recovery(row, details)
                return
            _disarm_survivor_recovery(row, details)
            _purge_live_metadata(db, destination_location.id, row.destination_path)
            return
        exact_s3_destination = bool(
            destination_location.kind == "s3"
            and _is_exact_s3_version_id(details.get("destination_version_id"))
        )
        stored_destination_meta = details.get("destination_meta")
        if not isinstance(stored_destination_meta, dict):
            stored_destination_meta = {
                "etag": details.get("destination_etag", ""),
                "version_id": details.get("destination_version_id", ""),
            }
        if exact_s3_destination:
            destination_preflight = work / "undo-owned-destination-preflight"
            destination_preflight_meta = _destination_snapshot(
                destination_location,
                row.destination_path,
                destination_preflight,
            )
            if (
                destination_preflight_meta is None
                or fingerprint(destination_preflight) != expected
                or not _same_remote_identity(
                    destination_preflight_meta,
                    stored_destination_meta,
                )
            ) and not isinstance(recovery, dict):
                raise FileOperationError("moved s3 destination changed; undo stopped")
        source_owned = bool(details.get("undo_source_owned"))
        source_claimed = bool(details.get("undo_source_claimed"))
        receipt_owned = bool(
            not source_owned
            and source_meta is not None
            and storage_backends.operation_receipt_matches(
                source_location,
                row.source_path,
                undo_id,
                expected,
            )
        )
        if source_meta is not None:
            if fingerprint(source_snapshot) != expected or (not source_owned and not receipt_owned):
                raise FileOperationError("undo destination already exists")
            source_destination_meta = source_meta
        else:
            destination = _verified_snapshot(
                destination_location,
                row.destination_path,
                work / "undo-moved",
                expected,
            )
            _ensure_metadata_destination_clear(db, source_location.id, row.source_path)
            if not source_claimed:
                details["undo_source_claimed"] = True
                row.undo_json = json.dumps(details, sort_keys=True)
                db.commit()
            try:
                uploaded_meta = storage_backends.upload_tree(
                    source_location,
                    row.source_path,
                    destination,
                    operation_id=undo_id,
                )
            except storage_backends.StorageBackendError as exc:
                raise FileOperationError(str(exc)) from exc
            verify = work / "undo-source-verify"
            source_destination_meta = _materialize(source_location, row.source_path, verify)
            if fingerprint(verify) != expected:
                raise FileOperationError("file changed; undo stopped")
            _require_uploaded_identity(
                source_location,
                destination,
                uploaded_meta,
                source_destination_meta,
            )
            try:
                storage_backends.seal_operation_receipt(
                    source_location,
                    row.source_path,
                    undo_id,
                    expected,
                    uploaded_meta,
                )
            except storage_backends.StorageBackendError as exc:
                raise FileOperationError(str(exc)) from exc
            if not storage_backends.operation_receipt_matches(
                source_location, row.source_path, undo_id, expected
            ):
                raise FileOperationError("undo ownership receipt is missing")
        if not details.get("undo_source_owned"):
            details["undo_source_owned"] = True
            details["undo_source_meta"] = source_destination_meta
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        elif not isinstance(details.get("undo_source_meta"), dict):
            if not storage_backends.operation_receipt_matches(
                source_location,
                row.source_path,
                undo_id,
                expected,
            ):
                raise FileOperationError("undo ownership receipt is missing")
            details["undo_source_meta"] = source_destination_meta
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()

        def finish_move_back() -> None:
            final_source = work / "undo-source-after-destination-delete"
            final_source_meta = _materialize(
                source_location,
                row.source_path,
                final_source,
            )
            if fingerprint(final_source) != expected or not _same_published_destination_identity(
                source_location,
                final_source_meta,
                details["undo_source_meta"],
            ):
                if isinstance(details.get("survivor_recovery"), dict):
                    finish_survivor_recovery()
                raise FileOperationError("restored source changed during undo")
            _rekey_metadata(
                db,
                destination_location.id,
                row.destination_path,
                source_location.id,
                row.source_path,
            )
            details["undo_metadata_rekeyed"] = True
            row.undo_json = json.dumps(details, sort_keys=True)
            _release_published_receipt(
                db,
                row,
                details,
                started_key="undo_source_receipt_release_started",
                location=source_location,
                path=row.source_path,
                operation_id=undo_id,
                expected=expected,
            )
            details.pop("undo_metadata_rekeyed", None)
            _disarm_survivor_recovery(row, details)

        if not details.get("undo_source_receipt_release_started") and not (
            storage_backends.operation_receipt_matches(
                source_location,
                row.source_path,
                undo_id,
                expected,
            )
        ):
            raise FileOperationError("undo ownership receipt is missing")
        destination_snapshot = work / "undo-destination-check"
        destination_meta = _destination_snapshot(
            destination_location,
            row.destination_path,
            destination_snapshot,
        )
        if destination_meta is None:
            finish_move_back()
            return
        if fingerprint(
            destination_snapshot
        ) != expected or not _same_published_destination_identity(
            destination_location,
            destination_meta,
            stored_destination_meta,
        ):
            if isinstance(recovery, dict):
                finish_move_back()
                return
            raise FileOperationError("moved file changed; undo stopped")
        _arm_survivor_recovery(
            db,
            row,
            details,
            snapshot_name="undo-destination-check",
            location=destination_location,
            path=row.destination_path,
            undo=True,
            metadata_origin="destination",
        )
        if exact_s3_destination and _delete_owned_s3_destination(
            db,
            row,
            details,
            expected,
            destination_location,
            row.destination_path,
            operation_id=undo_id,
            snapshot_name="undo-destination-after-owned-delete",
            purge_metadata=False,
        ):
            finish_move_back()
            return
        _mark_undo_mutation_started(db, row, details)
        try:
            storage_backends.delete_tree(
                destination_location,
                row.destination_path,
                expected=expected,
                expected_etag=details.get("destination_etag", ""),
                version_id=details.get("destination_version_id", ""),
                verified_meta=destination_meta,
                operation_id=undo_id,
                owned_version=False,
            )
        except storage_backends.StorageBackendError as exc:
            raise FileOperationError(str(exc)) from exc
        after_delete = work / "undo-destination-after-delete"
        after_delete_meta = _destination_snapshot(
            destination_location,
            row.destination_path,
            after_delete,
        )
        if after_delete_meta is not None:
            if fingerprint(after_delete) == expected and _same_published_destination_identity(
                destination_location,
                after_delete_meta,
                destination_meta,
            ):
                raise FileOperationError(
                    "move destination still exists; undo metadata was preserved"
                )
            finish_move_back()
            return
        finish_move_back()
        return
    if action == "restore_trash":
        item = db.get(TrashItem, details.get("trash_id"))
        stash = None
        if item:
            payload = json.loads(item.payload or "{}")
            trash_name = str(payload.get("trash_name") or "")
            stash = trash.stash_path(trash_name) if trash_name else None
        if isinstance(details.get("trash_survivor_recovery"), dict) and (
            item is None or stash is None or not _same(stash, expected)
        ):
            _finish_restore_rollback(
                db,
                row,
                source_location,
                row.source_path,
                undo=True,
            )

        def arm_trash_recovery(candidate: Path) -> None:
            recovery_snapshot = work / "undo-trash-survivor"
            if recovery_snapshot.exists() or recovery_snapshot.is_symlink():
                if fingerprint(recovery_snapshot) != expected:
                    raise FileOperationError("verified trash recovery snapshot changed")
            else:
                _copy_verified(candidate, recovery_snapshot, f"undo-trash-survivor-{row.id}")
            if item is None:
                raise FileOperationError("trash record is missing")
            _arm_trash_survivor_recovery(
                db,
                row,
                details,
                item=item,
                snapshot_name="undo-trash-survivor",
            )

        undo_id = f"undo-{row.id}"
        source_snapshot = work / "undo-restore-check"
        source_meta = _destination_snapshot(source_location, row.source_path, source_snapshot)
        source_owned = bool(details.get("undo_source_owned"))
        source_claimed = bool(details.get("undo_source_claimed"))
        original_source_intact = bool(
            source_meta is not None
            and fingerprint(source_snapshot) == expected
            and (
                _same_published_destination_identity(
                    source_location,
                    source_meta,
                    details.get("source_meta"),
                )
                or _source_identity_matches_refusal(source_meta, details)
            )
        )
        if original_source_intact:
            _payload, metadata_snapshot = _trash_metadata(item)
            if metadata_snapshot:
                raise FileOperationError("trash metadata changed; undo stopped")
            if stash and (stash.exists() or stash.is_symlink()):
                if not _same(stash, expected):
                    raise FileOperationError("trashed copy changed; undo stopped")
                arm_trash_recovery(stash)
                _mark_undo_mutation_started(db, row, details)
                _remove(stash)
            try:
                verify_original_source(
                    "undo-restore-original-source-after-trash-delete",
                    "original source changed during undo",
                )
            except FileOperationError:
                if isinstance(details.get("trash_survivor_recovery"), dict):
                    _finish_restore_rollback(
                        db,
                        row,
                        source_location,
                        row.source_path,
                        undo=True,
                    )
                raise
            if item:
                db.delete(item)
            _clear_trash_survivor_recovery(row, details)
            return
        _ensure_trash_metadata_destination_clear(db, item, source_location.id, row.source_path)
        receipt_owned = bool(
            not source_owned
            and source_meta is not None
            and storage_backends.operation_receipt_matches(
                source_location,
                row.source_path,
                undo_id,
                expected,
            )
        )
        if source_meta is not None:
            if fingerprint(source_snapshot) != expected or (not source_owned and not receipt_owned):
                raise FileOperationError("trash restore is no longer safe")
            source_destination_meta = source_meta
            trash_recovery_candidate = source_snapshot
        else:
            if not item or not stash or not _same(stash, expected):
                raise FileOperationError("trashed copy changed; undo stopped")
            if not source_claimed:
                details["undo_source_claimed"] = True
                row.undo_json = json.dumps(details, sort_keys=True)
                db.commit()
            try:
                uploaded_meta = storage_backends.upload_tree(
                    source_location,
                    row.source_path,
                    stash,
                    operation_id=undo_id,
                )
            except storage_backends.StorageBackendError as exc:
                raise FileOperationError(str(exc)) from exc
            verify = work / "undo-restore-verify"
            source_destination_meta = _materialize(source_location, row.source_path, verify)
            if fingerprint(verify) != expected:
                raise FileOperationError("file changed; undo stopped")
            _require_uploaded_identity(
                source_location,
                stash,
                uploaded_meta,
                source_destination_meta,
            )
            try:
                storage_backends.seal_operation_receipt(
                    source_location,
                    row.source_path,
                    undo_id,
                    expected,
                    uploaded_meta,
                )
            except storage_backends.StorageBackendError as exc:
                raise FileOperationError(str(exc)) from exc
            if not storage_backends.operation_receipt_matches(
                source_location, row.source_path, undo_id, expected
            ):
                raise FileOperationError("undo ownership receipt is missing")
            trash_recovery_candidate = verify
        if not details.get("undo_source_owned"):
            details["undo_source_owned"] = True
            details["undo_source_meta"] = source_destination_meta
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        elif not isinstance(details.get("undo_source_meta"), dict):
            if not storage_backends.operation_receipt_matches(
                source_location,
                row.source_path,
                undo_id,
                expected,
            ):
                raise FileOperationError("undo ownership receipt is missing")
            details["undo_source_meta"] = source_destination_meta
            row.undo_json = json.dumps(details, sort_keys=True)
            db.commit()
        if not details.get("undo_source_receipt_release_started") and not (
            storage_backends.operation_receipt_matches(
                source_location,
                row.source_path,
                undo_id,
                expected,
            )
        ):
            raise FileOperationError("undo ownership receipt is missing")
        if stash and (stash.exists() or stash.is_symlink()):
            if not _same(stash, expected):
                raise FileOperationError("trashed copy changed; undo stopped")
        arm_trash_recovery(trash_recovery_candidate)
        _restore_trash_metadata(db, item, source_location.id, row.source_path)
        if stash and (stash.exists() or stash.is_symlink()):
            _remove(stash)
        final_source = work / "undo-restore-after-trash-delete"
        final_source_meta = _materialize(source_location, row.source_path, final_source)
        if fingerprint(final_source) != expected or not _same_published_destination_identity(
            source_location,
            final_source_meta,
            details["undo_source_meta"],
        ):
            _finish_restore_rollback(
                db,
                row,
                source_location,
                row.source_path,
                undo=True,
            )
        _release_published_receipt(
            db,
            row,
            details,
            started_key="undo_source_receipt_release_started",
            location=source_location,
            path=row.source_path,
            operation_id=undo_id,
            expected=expected,
        )
        if item:
            db.delete(item)
        _clear_trash_survivor_recovery(row, details)
        return
    if action == "delete_restored":
        _undo_delete_nonlocal(
            db,
            row,
            details,
            expected,
            destination_location,
            row.destination_path,
        )
        return
    raise FileOperationError("operation has no undo")


def _undo_delete_nonlocal(
    db,
    row: FileOperation,
    details: dict,
    expected: dict,
    location,
    path: str,
) -> None:
    work = _workspace(row)
    undo_trash_id = details.get("undo_trash_id")
    item = db.get(TrashItem, undo_trash_id) if undo_trash_id else None
    snapshot = work / "undo-restored"
    current = _destination_snapshot(location, path, snapshot)
    if current is not None and fingerprint(snapshot) != expected:
        raise FileOperationError("restored file changed; undo stopped")
    owned_s3_version = bool(
        location.kind == "s3" and _is_exact_s3_version_id(details.get("destination_version_id"))
    )
    if owned_s3_version and item is None:
        stored_destination = {
            "etag": details.get("destination_etag", ""),
            "version_id": details.get("destination_version_id", ""),
        }
        if current is None or not _same_remote_identity(current, stored_destination):
            raise FileOperationError("restored s3 version is no longer current; undo stopped")
    if item:
        payload = json.loads(item.payload or "{}")
        trash_name = payload.get("trash_name", "")
    else:
        if current is None:
            raise FileOperationError("restored file changed; undo stopped")
        trash_name = uuid.uuid4().hex + (snapshot.suffix if snapshot.is_file() else "")
        item = trash.record(
            db,
            "file",
            path,
            Path(path).name,
            {"trash_name": trash_name, "is_dir": snapshot.is_dir(), "remote": True},
            location_id=location.id,
            commit=False,
        )
        details["undo_trash_id"] = item.id
        row.undo_json = json.dumps(details, sort_keys=True)
        db.commit()
    stash = trash.stash_path(trash_name)
    if not (stash.exists() or stash.is_symlink()):
        if current is None:
            raise FileOperationError("restored file changed; undo stopped")
        _copy_verified(snapshot, stash, f"undo-{row.id}")
    if not _same(stash, expected):
        raise FileOperationError("remote trash verification failed")
    if current is None:
        _detach_live_metadata_to_trash(db, item, location.id, path)
        return
    _mark_undo_mutation_started(db, row, details)
    try:
        storage_backends.delete_tree(
            location,
            path,
            expected=expected,
            expected_etag=details.get("destination_etag", ""),
            version_id=details.get("destination_version_id", ""),
            verified_meta=current,
            operation_id=f"undo-{row.id}",
            owned_version=bool(
                location.kind == "s3"
                and _is_exact_s3_version_id(details.get("destination_version_id"))
            ),
        )
    except storage_backends.StorageBackendError as exc:
        raise FileOperationError(str(exc)) from exc
    remaining = _destination_snapshot(location, path, work / "undo-restored-after-delete")
    if not _same(stash, expected):
        raise FileOperationError("trash copy changed during undo")
    if remaining is not None and not owned_s3_version:
        raise FileOperationError("restored destination still exists; undo stopped")
    if remaining is None or owned_s3_version:
        _detach_live_metadata_to_trash(db, item, location.id, path)
