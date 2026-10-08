"""Explicit Files offline cache. Cached bytes are disposable and never a backup."""

from __future__ import annotations

import os
import shutil
import stat
import unicodedata
import uuid
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from core.database import OfflineFile
from core.settings import data_dir
from services import file_operations, internal_paths, storage_backends, storage_locations

MAX_REMOTE_ITEMS = 10_000
MAX_REMOTE_BYTES = 4 * 1024 * 1024 * 1024
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class OfflineFileError(RuntimeError):
    pass


class OfflineFileCancelled(OfflineFileError):
    pass


def _windows_namespace_rules() -> bool:
    return os.name == "nt"


def cache_root() -> Path:
    root = (data_dir() / "offline-files").resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _cache_path(cache_name: str) -> Path:
    root = cache_root().resolve()
    if not cache_name or Path(cache_name).name != cache_name:
        raise OfflineFileError("offline cache identity is invalid")
    path = (root / cache_name).resolve(strict=False)
    if root not in path.parents:
        raise OfflineFileError("offline cache identity is invalid")
    return path


def _remove_cache_entry(path: Path) -> None:
    try:
        if path.is_symlink() or not path.is_dir():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path)
    except OSError as exc:
        raise OfflineFileError("offline cache could not be removed") from exc
    if path.exists() or path.is_symlink():
        raise OfflineFileError("offline cache could not be removed")


def _attempt_artifacts(target: Path, row_id: str) -> tuple[Path, ...]:
    incoming = target.with_name(f".{target.name}.{row_id}.incoming")
    return (
        target.with_name(f".{target.name}.{row_id}.partial"),
        incoming,
        internal_paths.artifact_sibling(incoming, "download", suffix=".partial"),
        internal_paths.artifact_sibling(incoming, "download", suffix=".json"),
        target.with_name(f".{target.name}.{row_id}.old"),
    )


def _remove_attempt_artifacts(target: Path, row_id: str) -> None:
    for artifact in _attempt_artifacts(target, row_id):
        _remove_cache_entry(artifact)


def _source_path(location, normalized_path: str) -> Path:
    if location.kind != "local":
        raise OfflineFileError("remote offline download is not ready")
    root = storage_locations.local_root(location)
    try:
        normalized = storage_locations.normalize_path(normalized_path)
    except (TypeError, ValueError) as exc:
        raise OfflineFileError("path escapes storage location") from exc
    if normalized != normalized_path:
        raise OfflineFileError("path escapes storage location")
    path = root.joinpath(*normalized.split("/")) if normalized else root
    current = root
    for component in path.relative_to(root).parts:
        current = current / component
        if current.is_symlink():
            raise OfflineFileError("symbolic links are not supported for offline files")
    if not path.exists():
        raise OfflineFileError("file is unavailable")
    return path


def _check_cancelled(db, row: OfflineFile) -> None:
    db.refresh(row)
    if row.state == "cancelled":
        raise OfflineFileCancelled("offline copy cancelled")


def _remote_item(location, normalized: str) -> dict:
    parent = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
    for item in storage_backends.listdir(location, parent).get("items", []):
        if item.get("normalized_path") == normalized or item.get("path") == normalized:
            return item
    raise OfflineFileError("remote item is unavailable")


def _listed_size(item: dict) -> int | None:
    value = item.get("size")
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OfflineFileError("remote item size is invalid")
    return value


def _downloaded_size(result: dict) -> int:
    value = result.get("size")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OfflineFileError("offline download size did not match")
    return value


def _remote_descendant(item: dict, root: str) -> tuple[str, str]:
    raw = item.get("normalized_path") or item.get("path")
    if not isinstance(raw, str):
        raise OfflineFileError("remote folder returned an invalid path")
    try:
        normalized = storage_locations.normalize_path(raw)
    except (TypeError, ValueError) as exc:
        raise OfflineFileError("remote folder returned an unsafe path") from exc
    if normalized != raw or not normalized.startswith(root.rstrip("/") + "/"):
        raise OfflineFileError("remote folder returned an unsafe path")
    suffix = normalized[len(root.rstrip("/")) + 1 :]
    if not suffix:
        raise OfflineFileError("remote folder returned an unsafe path")
    return normalized, suffix


def _remote_tree(location, normalized: str) -> tuple[list[dict], list[dict], int | None]:
    queue = [normalized]
    files = []
    directories = []
    total = 0
    total_is_known = True
    count = 0
    while queue:
        current = queue.pop(0)
        for item in storage_backends.listdir(location, current).get("items", []):
            normalized_path, _suffix = _remote_descendant(item, normalized)
            item = {**item, "path": normalized_path, "normalized_path": normalized_path}
            count += 1
            if count > MAX_REMOTE_ITEMS:
                raise OfflineFileError("offline folder has too many items")
            if item.get("type") == "dir":
                directories.append(item)
                queue.append(normalized_path)
                continue
            size = _listed_size(item)
            if size is None:
                total_is_known = False
            else:
                total += size
            if total > MAX_REMOTE_BYTES:
                raise OfflineFileError("offline folder is too large")
            files.append(item)
    return files, directories, total if total_is_known else None


def _validate_remote_namespace(files: list[dict], directories: list[dict], root: str) -> None:
    """Reject names that collapse onto one cache path on common local filesystems."""
    seen: dict[str, str] = {}
    for item in [*directories, *files]:
        _remote_path, suffix = _remote_descendant(item, root)
        key_parts = []
        for part in suffix.split("/"):
            normalized_part = unicodedata.normalize("NFC", part).casefold()
            if _windows_namespace_rules():
                if any(ord(char) < 32 or char in '<>:"\\|?*' for char in part):
                    raise OfflineFileError("remote folder contains a Windows-incompatible name")
                normalized_part = normalized_part.rstrip(" .")
                reserved_stem = normalized_part.split(".", 1)[0].upper()
                if not normalized_part or reserved_stem in _WINDOWS_RESERVED_NAMES:
                    raise OfflineFileError("remote folder contains a Windows-incompatible name")
            key_parts.append(normalized_part)
        collision_key = "/".join(key_parts)
        previous = seen.get(collision_key)
        if previous is not None and previous != suffix:
            raise OfflineFileError("remote folder contains colliding local names")
        if previous is not None:
            raise OfflineFileError("remote folder contains duplicate local names")
        seen[collision_key] = suffix


def _replace_verified(target: Path, incoming: Path, expected: dict, token: str) -> None:
    # A ready refresh also has a separately verified ``.previous`` snapshot.
    # ``enable`` keeps that snapshot until the new checksum/state commit, and
    # ``recover_interrupted`` restores it after a hard stop before that commit.
    # After the commit, recovery removes it only when the published target still
    # matches the newly committed checksum and size.
    if file_operations.fingerprint(incoming) != expected:
        raise OfflineFileError("offline copy verification failed")
    old = target.with_name(f".{target.name}.{token}.old")
    if old.exists():
        if old.is_dir():
            shutil.rmtree(old)
        else:
            old.unlink()
    if target.exists():
        target.rename(old)
    incoming.rename(target)
    if file_operations.fingerprint(target) != expected:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
        if old.exists():
            old.rename(target)
        raise OfflineFileError("offline copy verification failed")
    # Keep the displaced target until the caller durably commits the new ready
    # checksum. It is attempt-scoped and removed by post-commit cleanup or
    # restart recovery, never before the database owns the replacement.


def _copy_remote_to_cache(db, row: OfflineFile, location, target: Path) -> dict:
    normalized = row.normalized_path
    item = _remote_item(location, normalized)
    incoming = target.with_name(f".{target.name}.{row.id}.incoming")
    if incoming.exists():
        if incoming.is_dir():
            shutil.rmtree(incoming)
        else:
            incoming.unlink()
    _check_cancelled(db, row)
    if item.get("type") == "file":
        size = _listed_size(item)
        free = shutil.disk_usage(cache_root()).free
        if size is not None and size > free:
            raise OfflineFileError("not enough space for offline copy")
        if size is not None and size > MAX_REMOTE_BYTES:
            raise OfflineFileError("offline file is too large")
        limit = min(free, MAX_REMOTE_BYTES)
        try:
            result = storage_backends.download(
                location,
                normalized,
                incoming,
                expected_etag=item.get("etag", ""),
                expected_size=size,
                resume=True,
                max_bytes=limit if size is None else min(size, limit),
            )
            _check_cancelled(db, row)
            actual = _downloaded_size(result)
            if actual > limit or (size is not None and actual != size):
                raise OfflineFileError("offline download size did not match")
            expected = file_operations.fingerprint(incoming)
            if expected["size"] != actual:
                raise OfflineFileError("offline download size did not match")
            if result.get("checksum") and result["checksum"] != expected["checksum"]:
                raise OfflineFileError("offline copy verification failed")
            _replace_verified(target, incoming, expected, row.id)
            return {
                **expected,
                "etag": result.get("etag", ""),
                "version_id": result.get("version_id", ""),
            }
        except Exception:
            _remove_cache_entry(incoming)
            for artifact in (
                internal_paths.artifact_sibling(incoming, "download", suffix=".partial"),
                internal_paths.artifact_sibling(incoming, "download", suffix=".json"),
            ):
                _remove_cache_entry(artifact)
            raise
    files, directories, total = _remote_tree(location, normalized)
    _validate_remote_namespace(files, directories, normalized)
    free = shutil.disk_usage(cache_root()).free
    known_total = sum(size for item in files if (size := _listed_size(item)) is not None)
    if known_total > free or (total is not None and total > free):
        raise OfflineFileError("not enough space for offline copy")
    incoming.mkdir(parents=True, exist_ok=False)
    downloaded = 0
    try:
        for remote in sorted(
            directories,
            key=lambda value: (value["path"].count("/"), value["path"]),
        ):
            _check_cancelled(db, row)
            _remote_path, suffix = _remote_descendant(remote, normalized)
            destination = (incoming / suffix).resolve(strict=False)
            if incoming.resolve() not in destination.parents:
                raise OfflineFileError("remote folder returned an unsafe path")
            destination.mkdir(parents=True, exist_ok=True)
        for remote in files:
            _check_cancelled(db, row)
            remote_path, suffix = _remote_descendant(remote, normalized)
            destination = (incoming / suffix).resolve(strict=False)
            if incoming.resolve() not in destination.parents:
                raise OfflineFileError("remote folder returned an unsafe path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            advertised = _listed_size(remote)
            remaining = min(MAX_REMOTE_BYTES - downloaded, free - downloaded)
            if advertised is not None and advertised > remaining:
                if advertised > free - downloaded:
                    raise OfflineFileError("not enough space for offline copy")
                raise OfflineFileError("offline folder is too large")
            result = storage_backends.download(
                location,
                remote_path,
                destination,
                expected_etag=remote.get("etag", ""),
                expected_size=advertised,
                resume=True,
                max_bytes=(remaining if advertised is None else min(advertised, remaining)),
            )
            actual = _downloaded_size(result)
            if (
                actual > remaining
                or (advertised is not None and actual != advertised)
                or destination.stat().st_size != actual
            ):
                raise OfflineFileError("offline download size did not match")
            expected_file = file_operations.fingerprint(destination)
            if result.get("checksum") and result["checksum"] != expected_file["checksum"]:
                raise OfflineFileError("offline copy verification failed")
            downloaded += actual
            if downloaded > MAX_REMOTE_BYTES or downloaded > free:
                raise OfflineFileError("offline folder is too large")
            _check_cancelled(db, row)
        expected = file_operations.fingerprint(incoming)
        _check_cancelled(db, row)
        _replace_verified(target, incoming, expected, row.id)
        return {**expected, "etag": "", "version_id": ""}
    except Exception:
        if incoming.exists():
            shutil.rmtree(incoming, ignore_errors=True)
        raise


def public_dict(row: OfflineFile) -> dict:
    cached = _cache_path(row.cache_name)
    verified_size = row.size if row.state == "ready" and row.checksum else None
    return {
        "id": row.id,
        "location_id": row.location_id,
        "normalized_path": row.normalized_path,
        "state": row.state,
        "size": verified_size,
        "checksum": row.checksum or "",
        "etag": row.etag or "",
        "version_id": row.version_id or "",
        "error_code": row.error_code or "",
        "type": "dir" if cached.is_dir() else "file",
        "cache_only": True,
        "is_backup": False,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_items(db, *, location_id: str | None = None) -> list[OfflineFile]:
    query = db.query(OfflineFile)
    if location_id:
        query = query.filter(OfflineFile.location_id == location_id)
    return query.order_by(OfflineFile.normalized_path).all()


def _safe_local_copy_supported() -> bool:
    return os.name != "nt"


def _open_local_source(root: Path, path: Path):
    """Open one file beneath a local location without following any symlink component."""
    root = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OfflineFileError("path escapes storage location") from exc
    if not relative.parts:
        raise OfflineFileError("offline source is not a file")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptors = []
    try:
        current = os.open(root, directory_flags)
        descriptors.append(current)
        for component in relative.parts[:-1]:
            current = os.open(component, directory_flags, dir_fd=current)
            descriptors.append(current)
        file_descriptor = os.open(relative.parts[-1], file_flags, dir_fd=current)
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            os.close(file_descriptor)
            raise OfflineFileError("offline source is not a regular file")
        return os.fdopen(file_descriptor, "rb")
    except OSError as exc:
        raise OfflineFileError("symbolic links are not supported for offline files") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _open_local_directory(root: Path, path: Path) -> int:
    """Open one directory beneath a local location without following symlinks."""
    root = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OfflineFileError("path escapes storage location") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = []
    try:
        current = os.open(root, flags)
        descriptors.append(current)
        for component in relative.parts:
            current = os.open(component, flags, dir_fd=current)
            descriptors.append(current)
        return os.dup(current)
    except OSError as exc:
        raise OfflineFileError("symbolic links are not supported for offline files") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _copy_local_tree(source_root: Path, source: Path, target: Path, check) -> None:
    """Copy a local tree through no-follow directory descriptors."""
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK

    def copy_directory(source_fd: int, destination: Path) -> None:
        destination.mkdir()
        with os.scandir(source_fd) as entries:
            for entry in entries:
                check()
                outgoing = destination / entry.name
                if entry.is_symlink():
                    raise OfflineFileError("symbolic links are not supported for offline files")
                if entry.is_dir(follow_symlinks=False):
                    try:
                        child_fd = os.open(entry.name, directory_flags, dir_fd=source_fd)
                    except OSError as exc:
                        raise OfflineFileError(
                            "symbolic links are not supported for offline files"
                        ) from exc
                    try:
                        copy_directory(child_fd, outgoing)
                    finally:
                        os.close(child_fd)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise OfflineFileError("unsupported local file type in offline folder")
                try:
                    file_fd = os.open(entry.name, file_flags, dir_fd=source_fd)
                except OSError as exc:
                    raise OfflineFileError(
                        "symbolic links are not supported for offline files"
                    ) from exc
                try:
                    if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                        raise OfflineFileError("unsupported local file type in offline folder")
                    with (
                        os.fdopen(file_fd, "rb", closefd=False) as incoming,
                        open(outgoing, "xb") as copied,
                    ):
                        for chunk in iter(lambda: incoming.read(file_operations.CHUNK_SIZE), b""):
                            check()
                            copied.write(chunk)
                        copied.flush()
                        os.fsync(copied.fileno())
                finally:
                    os.close(file_fd)

    source_fd = _open_local_directory(source_root, source)
    try:
        copy_directory(source_fd, target)
    finally:
        os.close(source_fd)


def _copy_to_cache(
    source: Path,
    target: Path,
    token: str,
    *,
    source_root: Path,
    check_cancelled=None,
) -> dict:
    check = check_cancelled or (lambda: None)
    source_resolved = source.resolve(strict=False)
    offline_root = cache_root().resolve()
    if source.is_dir() and (
        source_resolved == offline_root or source_resolved in offline_root.parents
    ):
        raise OfflineFileError("a local offline source cannot contain the offline cache")
    expected = file_operations.fingerprint(source)
    free = shutil.disk_usage(offline_root).free
    if expected["size"] > free:
        raise OfflineFileError("not enough space for offline copy")
    temp = target.with_name(f".{target.name}.{token}.partial")
    if temp.exists():
        if temp.is_dir():
            shutil.rmtree(temp)
        else:
            temp.unlink()
    try:
        if source.is_dir():
            check()
            _copy_local_tree(source_root, source, temp, check)
        else:
            with _open_local_source(source_root, source) as incoming, temp.open("xb") as outgoing:
                for chunk in iter(lambda: incoming.read(file_operations.CHUNK_SIZE), b""):
                    check()
                    outgoing.write(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        check()
        if file_operations.fingerprint(temp) != expected:
            raise OfflineFileError("offline copy verification failed")
        old = target.with_name(f".{target.name}.{token}.old")
        if old.exists():
            if old.is_dir():
                shutil.rmtree(old)
            else:
                old.unlink()
        if target.exists():
            target.rename(old)
        check()
        temp.rename(target)
        if file_operations.fingerprint(target) != expected:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            if old.exists():
                old.rename(target)
            raise OfflineFileError("offline copy verification failed")
        # Keep the displaced target through the ready-state commit. The caller
        # removes this attempt artifact only after the checksum is durable.
        return expected
    except Exception:
        if temp.is_dir():
            shutil.rmtree(temp, ignore_errors=True)
        else:
            temp.unlink(missing_ok=True)
        raise


def enable(db, *, location_id: str, path: str) -> OfflineFile:
    location = storage_locations.require_browsable(db, location_id)
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise OfflineFileError("path required")
    if location.kind == "local" and not _safe_local_copy_supported():
        raise OfflineFileError(
            "local offline copies are unavailable on Windows because safe no-follow copying "
            "is not supported"
        )
    with file_operations.direct_mutation_claim(db, location, normalized):
        return _enable_claimed(db, location=location, normalized=normalized)


def _enable_claimed(db, *, location, normalized: str) -> OfflineFile:
    row = (
        db.query(OfflineFile)
        .filter(
            OfflineFile.location_id == location.id,
            OfflineFile.normalized_path == normalized,
        )
        .first()
    )
    if row is None:
        row = OfflineFile(
            location_id=location.id,
            normalized_path=normalized,
            state="queued",
            cache_name=uuid.uuid4().hex,
        )
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
        except IntegrityError:
            db.rollback()
            row = (
                db.query(OfflineFile)
                .filter(
                    OfflineFile.location_id == location.id,
                    OfflineFile.normalized_path == normalized,
                )
                .one()
            )
    target = _cache_path(row.cache_name)
    claimed_state = row.state
    if claimed_state not in {"queued", "failed", "ready", "cancelled"}:
        raise OfflineFileError("offline copy is already running")
    previous_ready = False
    invalid_ready = False
    if claimed_state == "ready" and target.exists():
        try:
            cached = file_operations.fingerprint(target)
            previous_ready = cached["checksum"] == row.checksum and cached["size"] == row.size
        except Exception:
            previous_ready = False
        if not previous_ready:
            invalid_ready = True
    previous = target.with_name(f".{target.name}.{row.id}.previous")
    snapshot_ready = False
    claimed = (
        db.query(OfflineFile)
        .filter(OfflineFile.id == row.id, OfflineFile.state == claimed_state)
        .update(
            {OfflineFile.state: "syncing", OfflineFile.error_code: ""},
            synchronize_session=False,
        )
    )
    db.commit()
    if claimed != 1:
        db.expire_all()
        raise OfflineFileError("offline copy is already running")
    db.refresh(row)
    published_ready = False
    try:
        if invalid_ready:
            _remove_cache_entry(target)
        if previous_ready:
            _remove_cache_entry(previous)
            old_expected = file_operations.fingerprint(target)
            if old_expected["size"] > shutil.disk_usage(cache_root()).free:
                raise OfflineFileError("not enough space for offline cache recovery copy")
            if target.is_dir():
                shutil.copytree(target, previous, copy_function=shutil.copy2)
            else:
                shutil.copy2(target, previous)
            if file_operations.fingerprint(previous) != old_expected:
                raise OfflineFileError("offline cache recovery copy failed")
            snapshot_ready = True
        if location.kind == "local":
            source = _source_path(location, normalized)
            expected = _copy_to_cache(
                source,
                target,
                row.id,
                source_root=storage_locations.local_root(location),
                check_cancelled=lambda: _check_cancelled(db, row),
            )
        else:
            expected = _copy_remote_to_cache(
                db,
                row,
                location,
                target,
            )
        _check_cancelled(db, row)
        published = (
            db.query(OfflineFile)
            .filter(OfflineFile.id == row.id, OfflineFile.state == "syncing")
            .update(
                {
                    OfflineFile.state: "ready",
                    OfflineFile.size: expected["size"],
                    OfflineFile.checksum: expected["checksum"],
                    OfflineFile.etag: expected.get("etag", ""),
                    OfflineFile.version_id: expected.get("version_id", ""),
                    OfflineFile.error_code: "",
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if published != 1:
            db.expire_all()
            current = db.get(OfflineFile, row.id)
            if current and current.state == "cancelled":
                raise OfflineFileCancelled("offline copy cancelled")
            raise OfflineFileError("offline copy state changed")
        published_ready = True
        try:
            db.refresh(row)
        except Exception:
            # The ready row and target are already committed. A later request or
            # restart can refresh state without rolling verified bytes backward.
            pass
        try:
            _remove_cache_entry(previous)
            _remove_attempt_artifacts(target, row.id)
        except Exception:
            # The ready checksum is already durable. Restart recovery can safely
            # remove the old snapshot/artifacts without rolling bytes backward.
            pass
        return row
    except Exception as exc:
        if published_ready:
            raise OfflineFileError(
                "offline copy was published; cleanup will resume after restart"
            ) from exc
        if snapshot_ready and previous.exists():
            _remove_cache_entry(target)
            previous.rename(target)
        elif not previous_ready:
            _remove_cache_entry(target)
        _remove_cache_entry(previous)
        _remove_attempt_artifacts(target, row.id)
        db.expire_all()
        current = db.get(OfflineFile, row.id)
        if current and previous_ready:
            was_cancelled = current.state == "cancelled" or isinstance(exc, OfflineFileCancelled)
            current.state = "ready"
            current.error_code = (
                "refresh_cancelled" if was_cancelled else "refresh_failed: " + str(exc)[:140]
            )
            db.commit()
        elif current and current.state != "cancelled":
            current.state = "failed"
            current.error_code = str(exc)[:140]
            db.commit()
        if isinstance(exc, (OfflineFileError, RuntimeError, ValueError)):
            raise OfflineFileError(str(exc)) from exc
        raise OfflineFileError("offline copy failed") from exc


def cancel(db, row: OfflineFile) -> None:
    cancelled = (
        db.query(OfflineFile)
        .filter(
            OfflineFile.id == row.id,
            OfflineFile.state.in_(("queued", "syncing")),
        )
        .update(
            {OfflineFile.state: "cancelled", OfflineFile.error_code: "cancelled"},
            synchronize_session=False,
        )
    )
    db.commit()
    if cancelled != 1:
        raise OfflineFileError("offline copy is not running")
    db.refresh(row)


def recover_interrupted(db) -> int:
    cleaned_ready = 0
    invalid_ready = 0
    ready = db.query(OfflineFile).filter(OfflineFile.state == "ready").all()
    for row in ready:
        target = _cache_path(row.cache_name)
        previous = target.with_name(f".{target.name}.{row.id}.previous")
        if not previous.exists():
            continue
        try:
            expected = file_operations.fingerprint(target)
        except Exception:
            row.state = "failed"
            row.error_code = "offline_cache_integrity_unverified"
            invalid_ready += 1
            continue
        if expected["checksum"] != row.checksum or expected["size"] != row.size:
            row.state = "failed"
            row.error_code = "offline_cache_integrity_unverified"
            invalid_ready += 1
            continue
        _remove_cache_entry(previous)
        _remove_attempt_artifacts(target, row.id)
        cleaned_ready += 1
    deleting = db.query(OfflineFile).filter(OfflineFile.state == "deleting").all()
    for row in deleting:
        target = _cache_path(row.cache_name)
        _remove_attempt_artifacts(target, row.id)
        for artifact in (
            target,
            target.with_name(f".{target.name}.{row.id}.previous"),
        ):
            _remove_cache_entry(artifact)
        db.delete(row)
    rows = db.query(OfflineFile).filter(OfflineFile.state == "syncing").all()
    for row in rows:
        target = _cache_path(row.cache_name)
        previous = target.with_name(f".{target.name}.{row.id}.previous")
        if previous.exists():
            try:
                expected = file_operations.fingerprint(previous)
                if expected["checksum"] == row.checksum and expected["size"] == row.size:
                    _remove_cache_entry(target)
                    previous.rename(target)
                    row.state = "ready"
                    row.error_code = "refresh_interrupted"
                    _remove_attempt_artifacts(target, row.id)
                    continue
            except Exception:
                pass
            _remove_cache_entry(previous)
        if target.exists():
            try:
                expected = file_operations.fingerprint(target)
                if expected["checksum"] == row.checksum and expected["size"] == row.size:
                    row.state = "ready"
                    row.error_code = "refresh_interrupted"
                    _remove_attempt_artifacts(target, row.id)
                    continue
            except Exception:
                pass
            _remove_cache_entry(target)
        row.state = "queued"
        row.error_code = "recovered_after_restart"
        _remove_attempt_artifacts(target, row.id)
    cancelled = db.query(OfflineFile).filter(OfflineFile.state == "cancelled").all()
    recovered_cancelled = 0
    for row in cancelled:
        target = _cache_path(row.cache_name)
        previous = target.with_name(f".{target.name}.{row.id}.previous")
        if (
            not target.exists()
            and not previous.exists()
            and not any(artifact.exists() for artifact in _attempt_artifacts(target, row.id))
        ):
            continue
        recovered_cancelled += 1
        if previous.exists():
            try:
                expected = file_operations.fingerprint(previous)
                if expected["checksum"] == row.checksum and expected["size"] == row.size:
                    _remove_cache_entry(target)
                    previous.rename(target)
                    row.state = "ready"
                    row.error_code = "refresh_cancelled"
                    _remove_attempt_artifacts(target, row.id)
                    continue
            except Exception:
                pass
            row.state = "failed"
            row.error_code = "offline_cache_integrity_unverified"
            continue
        if target.exists():
            try:
                expected = file_operations.fingerprint(target)
                if expected["checksum"] == row.checksum and expected["size"] == row.size:
                    row.state = "ready"
                    row.error_code = "refresh_cancelled"
                    _remove_attempt_artifacts(target, row.id)
                    continue
            except Exception:
                pass
        _remove_cache_entry(target)
        _remove_attempt_artifacts(target, row.id)
    if cleaned_ready or invalid_ready or rows or deleting or recovered_cancelled:
        db.commit()
    return cleaned_ready + invalid_ready + len(rows) + len(deleting) + recovered_cancelled


def disable(db, row: OfflineFile) -> None:
    location = storage_locations.get_location(db, row.location_id)
    if location is None:
        raise LookupError("storage location not found")
    current = db.get(OfflineFile, row.id)
    if current is None:
        raise OfflineFileError("offline copy not found")
    normalized = storage_locations.normalize_path(current.normalized_path)
    with file_operations.direct_mutation_claim(db, location, normalized):
        current = db.get(OfflineFile, row.id)
        if current is None:
            raise OfflineFileError("offline copy not found")
        _disable_claimed(db, current)


def _disable_claimed(db, row: OfflineFile) -> None:
    claimed = (
        db.query(OfflineFile)
        .filter(
            OfflineFile.id == row.id,
            OfflineFile.state.notin_(("syncing", "deleting")),
        )
        .update(
            {OfflineFile.state: "deleting", OfflineFile.error_code: ""},
            synchronize_session=False,
        )
    )
    db.commit()
    if claimed != 1:
        db.expire_all()
        current = db.get(OfflineFile, row.id)
        if current and current.state == "syncing":
            raise OfflineFileError("offline copy is still syncing")
        raise OfflineFileError("offline copy is already being removed")
    db.refresh(row)
    target = _cache_path(row.cache_name)
    _remove_attempt_artifacts(target, row.id)
    for artifact in (
        target,
        target.with_name(f".{target.name}.{row.id}.previous"),
    ):
        _remove_cache_entry(artifact)
    current = db.get(OfflineFile, row.id)
    if current is not None:
        db.delete(current)
    db.commit()


def resolve_cached(db, *, location_id: str, path: str) -> Path | None:
    normalized = storage_locations.normalize_path(path)
    rows = (
        db.query(OfflineFile)
        .filter(OfflineFile.location_id == location_id, OfflineFile.state == "ready")
        .all()
    )
    best = None
    for row in rows:
        base = row.normalized_path
        if normalized == base or normalized.startswith(base.rstrip("/") + "/"):
            if best is None or len(base) > len(best.normalized_path):
                best = row
    if best is None:
        return None
    target = _cache_path(best.cache_name)
    suffix = normalized[len(best.normalized_path) :].lstrip("/")
    resolved = (target / suffix).resolve(strict=False) if suffix else target.resolve(strict=False)
    cache = cache_root().resolve()
    if (
        resolved != target.resolve(strict=False)
        and target.resolve(strict=False) not in resolved.parents
    ):
        return None
    if cache not in resolved.parents:
        return None
    return resolved if resolved.exists() else None
