"""One dispatch boundary for local, WebDAV, and S3 Files locations."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import uuid
from pathlib import Path

from core.settings import data_dir
from services import files_store, internal_paths, s3_locations, storage_locations, webdav_locations

CHUNK_SIZE = 1024 * 1024
RECEIPT_SUFFIX = ".alles-receipt"
CLAIM_SUFFIX = ".alles-claim"
SEAL_SUFFIX = ".alles-seal"
PARTIAL_SUFFIX = ".alles-partial"
_UUID_PATTERN = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_OPERATION_ID_PATTERN = rf"(?:undo-)?{_UUID_PATTERN}"
_INTERNAL_TRANSFER_NAME = re.compile(
    rf"^\.alles-(?P<operation_id>{_OPERATION_ID_PATTERN})"
    rf"(?P<suffix>{re.escape(RECEIPT_SUFFIX)}|{re.escape(CLAIM_SUFFIX)}|"
    rf"{re.escape(SEAL_SUFFIX)}|{re.escape(PARTIAL_SUFFIX)})$"
)


class StorageBackendError(RuntimeError):
    pass


class StorageVersionedDeleteRefused(StorageBackendError):
    """A versioned logical delete refusal with explicit mutation-state proof."""

    def __init__(
        self,
        message: str,
        *,
        before_mutation: bool,
        source_identity: dict | None = None,
    ):
        self.before_mutation = before_mutation
        self.source_identity = dict(source_identity) if source_identity else None
        super().__init__(message)


class StorageNotFoundError(StorageBackendError):
    pass


def _translate(exc: Exception) -> StorageBackendError:
    return StorageBackendError(str(exc) or "storage operation failed")


def _optional_file_size(value) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise StorageBackendError("storage file size is invalid")
    return value


def local_path(row, path: str) -> Path:
    if row.kind != "local":
        raise StorageBackendError("storage item is not local")
    try:
        root = storage_locations.local_root(row)
        return files_store.abspath(storage_locations.normalize_path(path), root=root)
    except (RuntimeError, ValueError) as exc:
        raise _translate(exc) from exc


def _raw_listdir(row, normalized: str, *, sort: str = "name", order: str = "") -> dict:
    if row.kind == "local":
        return files_store.listdir(
            normalized,
            sort=sort,
            order=order,
            root=storage_locations.local_root(row),
        )
    if row.kind == "webdav":
        return webdav_locations.listdir(row, normalized)
    if row.kind == "s3":
        return s3_locations.listdir(row, normalized)
    raise StorageBackendError("unsupported storage location")


def listdir(row, path: str = "", *, sort: str = "name", order: str = "") -> dict:
    normalized = storage_locations.normalize_path(path)
    try:
        result = _raw_listdir(row, normalized, sort=sort, order=order)
        result["items"] = [
            item for item in result.get("items", []) if not _is_internal_transfer_item(row, item)
        ]
        return result
    except (
        RuntimeError,
        ValueError,
        webdav_locations.WebDAVLocationError,
        s3_locations.S3LocationError,
    ) as exc:
        raise _translate(exc) from exc
    raise StorageBackendError("unsupported storage location")


def _operation_receipt_path(path: str, operation_id: str) -> str:
    normalized = storage_locations.normalize_path(path)
    clean_id = "".join(value for value in str(operation_id) if value.isalnum() or value == "-")
    if not normalized or not clean_id:
        raise StorageBackendError("operation receipt identity is invalid")
    parent = normalized.rpartition("/")[0]
    receipt = f".alles-{clean_id}{RECEIPT_SUFFIX}"
    return f"{parent}/{receipt}" if parent else receipt


def _operation_claim_path(path: str) -> str:
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise StorageBackendError("operation claim identity is invalid")
    parent = normalized.rpartition("/")[0]
    destination_name = normalized.rpartition("/")[2]
    claim_id = uuid.uuid5(uuid.NAMESPACE_URL, f"alles-storage-destination:{destination_name}")
    claim = f".alles-{claim_id}{CLAIM_SUFFIX}"
    return f"{parent}/{claim}" if parent else claim


def _operation_seal_path(path: str, operation_id: str) -> str:
    normalized = storage_locations.normalize_path(path)
    clean_id = "".join(value for value in str(operation_id) if value.isalnum() or value == "-")
    if not normalized or not clean_id:
        raise StorageBackendError("operation seal identity is invalid")
    parent = normalized.rpartition("/")[0]
    seal = f".alles-{clean_id}{SEAL_SUFFIX}"
    return f"{parent}/{seal}" if parent else seal


def _operation_partial_path(path: str, operation_id: str) -> str:
    normalized = storage_locations.normalize_path(path)
    clean_id = "".join(value for value in str(operation_id) if value.isalnum() or value == "-")
    if not normalized or not clean_id:
        raise StorageBackendError("operation partial identity is invalid")
    parent = normalized.rpartition("/")[0]
    partial = f".alles-{clean_id}{PARTIAL_SUFFIX}"
    return f"{parent}/{partial}" if parent else partial


def _operation_receipt_payload(row, path: str, operation_id: str, expected: dict) -> dict:
    return {
        "version": 1,
        "operation_id": operation_id,
        "location_id": row.id,
        "destination_path": storage_locations.normalize_path(path),
        "fingerprint": expected,
    }


def _destination_receipt_identity(metadata: dict) -> dict:
    return {
        "etag": str(metadata.get("etag") or "")[:512],
        "version_id": str(metadata.get("version_id") or "")[:1024],
        "local_device": int(metadata.get("local_device") or 0),
        "local_inode": int(metadata.get("local_inode") or 0),
        "local_mtime_ns": int(metadata.get("local_mtime_ns") or 0),
        "local_ctime_ns": int(metadata.get("local_ctime_ns") or 0),
        "local_tree_identity": str(metadata.get("local_tree_identity") or "")[:128],
        "local_publication_identity": str(metadata.get("local_publication_identity") or "")[:128],
    }


def _exact_s3_version_id(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() != "null"


def _local_tree_receipt_identity(path: Path) -> str:
    """Bind a local directory receipt to every published child's filesystem identity."""
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise StorageBackendError("published local directory identity is invalid")
    digest = hashlib.sha256()
    children = [root, *sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())]
    for child in children:
        if child.is_symlink():
            raise StorageBackendError("symbolic links are not supported")
        try:
            stat = child.stat(follow_symlinks=False)
        except OSError as exc:
            raise _translate(exc) from exc
        if child == root:
            relative = "."
            kind = "dir"
        else:
            relative = child.relative_to(root).as_posix()
            if child.is_dir():
                kind = "dir"
            elif child.is_file():
                kind = "file"
            else:
                raise StorageBackendError("unsupported file type")
        payload = json.dumps(
            [
                kind,
                relative,
                int(stat.st_dev),
                int(stat.st_ino),
                int(stat.st_size),
                int(stat.st_mtime_ns),
                int(stat.st_ctime_ns),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _local_path_receipt_identity(path: Path) -> dict:
    """Return the physical identity used to seal a local published path."""
    from services import file_operations

    target = Path(path)
    if target.is_symlink() or not (target.is_file() or target.is_dir()):
        raise StorageBackendError("published local destination identity is invalid")
    try:
        stat = target.stat(follow_symlinks=False)
    except OSError as exc:
        raise _translate(exc) from exc
    try:
        tree_identity = _local_tree_receipt_identity(target) if target.is_dir() else ""
        publication_identity = file_operations._local_publication_identity(target)  # noqa: SLF001
    except (file_operations.FileOperationError, OSError) as exc:
        raise StorageBackendError("published local destination identity is unavailable") from exc
    metadata = {
        "local_device": stat.st_dev,
        "local_inode": stat.st_ino,
        "local_mtime_ns": stat.st_mtime_ns,
        "local_ctime_ns": stat.st_ctime_ns,
        "local_tree_identity": tree_identity,
        "local_publication_identity": publication_identity,
    }
    return _destination_receipt_identity(metadata)


def _same_local_path_receipt_identity(path: Path, expected: dict) -> bool:
    stored = _destination_receipt_identity(expected)
    return bool(
        stored["local_device"]
        and stored["local_inode"]
        and _local_path_receipt_identity(path) == stored
    )


def _operation_seal_payload(
    row,
    path: str,
    operation_id: str,
    expected: dict,
    destination_identity: dict,
) -> dict:
    return {
        **_operation_receipt_payload(row, path, operation_id, expected),
        "version": 2,
        "state": "published",
        "destination_identity": _destination_receipt_identity(destination_identity),
    }


def _read_operation_artifact(row, artifact_path: str) -> tuple[dict, dict] | None:
    try:
        metadata = item(row, artifact_path)
    except StorageNotFoundError:
        return None
    try:
        size = _optional_file_size(metadata.get("size"))
        if metadata.get("type") != "file" or (size is not None and not 0 < size <= 8192):
            raise StorageBackendError("operation ownership artifact is invalid")
        target = temporary_path(row, artifact_path)
        try:
            downloaded = download(
                row,
                artifact_path,
                target,
                expected_etag=str(metadata.get("etag") or ""),
                expected_size=size,
                resume=False,
                max_bytes=8192,
            )
            if not 0 < target.stat().st_size <= 8192:
                raise StorageBackendError("operation ownership artifact is invalid")
            payload = json.loads(target.read_text(encoding="utf-8"))
        finally:
            target.unlink(missing_ok=True)
    except StorageBackendError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise StorageBackendError("operation ownership artifact could not be verified") from exc
    if not isinstance(payload, dict):
        raise StorageBackendError("operation ownership artifact is invalid")
    return (
        {
            **metadata,
            "etag": downloaded.get("etag", metadata.get("etag", "")),
            "version_id": downloaded.get("version_id", metadata.get("version_id", "")),
        },
        payload,
    )


def _read_operation_receipt(row, receipt_path: str) -> dict | None:
    artifact = _read_operation_artifact(row, receipt_path)
    return artifact[1] if artifact is not None else None


def _is_internal_transfer_item(row, item: dict) -> bool:
    """Hide only exact operation artifacts; suffixes alone remain valid user names."""
    name = str(item.get("name") or Path(item.get("path", "")).name)
    match = _INTERNAL_TRANSFER_NAME.fullmatch(name)
    if match is None:
        return False
    try:
        path = storage_locations.normalize_path(str(item.get("path") or name))
        suffix = match.group("suffix")
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if suffix in {RECEIPT_SUFFIX, PARTIAL_SUFFIX}:
            operation_id = match.group("operation_id")
            placeholder = f"{parent}/item" if parent else "item"
            receipt_path = _operation_receipt_path(placeholder, operation_id)
            payload = _read_operation_receipt(row, receipt_path)
            if payload is None:
                return False
        else:
            artifact = _read_operation_artifact(row, path)
            if artifact is None:
                return False
            payload = artifact[1]
            operation_id = payload.get("operation_id")
            if not isinstance(operation_id, str):
                return False
        destination_path = payload.get("destination_path")
        expected = payload.get("fingerprint")
        if not isinstance(destination_path, str) or not isinstance(expected, dict):
            return False
        if suffix == SEAL_SUFFIX:
            destination_identity = payload.get("destination_identity")
            if not isinstance(destination_identity, dict) or payload != _operation_seal_payload(
                row,
                destination_path,
                operation_id,
                expected,
                destination_identity,
            ):
                return False
            return _operation_seal_path(destination_path, operation_id) == path
        if payload != _operation_receipt_payload(row, destination_path, operation_id, expected):
            return False
        if suffix == CLAIM_SUFFIX:
            return _operation_claim_path(destination_path) == path
        receipt_path = _operation_receipt_path(destination_path, operation_id)
        if suffix == PARTIAL_SUFFIX:
            if row.kind != "local" or item.get("type") not in {"file", "dir"}:
                return False
            return _operation_partial_path(destination_path, operation_id) == path
        return receipt_path == path
    except (OSError, TypeError, ValueError, StorageBackendError):
        return False


def _operation_receipt_identity(row, path: str, operation_id: str, expected: dict) -> dict | None:
    """Return the HEAD-verified identity of this operation's receipt."""
    receipt_path = _operation_receipt_path(path, operation_id)
    artifact = _read_operation_artifact(row, receipt_path)
    if artifact is None:
        return None
    metadata, payload = artifact
    if payload != _operation_receipt_payload(row, path, operation_id, expected):
        return None
    return metadata


def _operation_claim_identity(row, path: str, operation_id: str, expected: dict) -> dict | None:
    claim_path = _operation_claim_path(path)
    artifact = _read_operation_artifact(row, claim_path)
    if artifact is None:
        return None
    metadata, payload = artifact
    if payload != _operation_receipt_payload(row, path, operation_id, expected):
        return None
    return metadata


def _operation_seal_identity(row, path: str, operation_id: str, expected: dict) -> dict | None:
    seal_path = _operation_seal_path(path, operation_id)
    artifact = _read_operation_artifact(row, seal_path)
    if artifact is None:
        return None
    metadata, payload = artifact
    destination_identity = payload.get("destination_identity")
    if not isinstance(destination_identity, dict) or payload != _operation_seal_payload(
        row,
        path,
        operation_id,
        expected,
        destination_identity,
    ):
        return None
    return {**metadata, "destination_identity": destination_identity}


def operation_receipt_matches(row, path: str, operation_id: str, expected: dict) -> bool:
    """Prove exclusive intent plus a post-publication destination seal."""
    if (
        _operation_claim_identity(row, path, operation_id, expected) is None
        or _operation_receipt_identity(row, path, operation_id, expected) is None
    ):
        return False
    seal = _operation_seal_identity(row, path, operation_id, expected)
    if seal is None:
        return False
    try:
        destination = item(row, path)
    except StorageBackendError:
        return False
    expected_kind = expected.get("kind")
    if expected_kind not in {"file", "dir"} or destination.get("type") != expected_kind:
        return False
    if expected_kind == "dir":
        if row.kind != "local":
            return False
        from services import file_operations

        try:
            destination_path = local_path(row, path)
            if file_operations.fingerprint(destination_path) != expected:
                return False
            destination["local_tree_identity"] = _local_tree_receipt_identity(destination_path)
        except (file_operations.FileOperationError, OSError, StorageBackendError):
            return False
    if row.kind == "local":
        from services import file_operations

        try:
            destination_path = local_path(row, path)
            destination["local_publication_identity"] = file_operations._local_publication_identity(  # noqa: SLF001
                destination_path
            )
        except (file_operations.FileOperationError, OSError):
            return False
    destination_identity = _destination_receipt_identity(destination)
    if row.kind == "local" and (
        not destination_identity["local_device"] or not destination_identity["local_inode"]
    ):
        return False
    if row.kind in {"webdav", "s3"} and destination.get("type") == "file":
        if not destination_identity["etag"]:
            return False
    return seal["destination_identity"] == destination_identity


def _assert_no_foreign_destination_claim(
    row,
    path: str,
    operation_id: str = "",
) -> None:
    """Reject writes beneath any destination reserved by another operation."""
    normalized = storage_locations.normalize_path(path)
    parts = normalized.split("/") if normalized else []
    for length in range(1, len(parts) + 1):
        candidate = "/".join(parts[:length])
        claim_path = _operation_claim_path(candidate)
        try:
            item(row, claim_path)
        except StorageNotFoundError:
            continue
        artifact = _read_operation_artifact(row, claim_path)
        if artifact is not None:
            payload = artifact[1]
            owner = payload.get("operation_id")
            expected = payload.get("fingerprint")
            if (
                operation_id
                and owner == operation_id
                and isinstance(expected, dict)
                and payload == _operation_receipt_payload(row, candidate, owner, expected)
            ):
                continue
        raise StorageBackendError("destination is in use by another operation")


def _write_operation_claim(row, path: str, operation_id: str, expected: dict) -> dict:
    _assert_no_foreign_destination_claim(row, path, operation_id)
    claim_path = _operation_claim_path(path)
    target = temporary_path(row, claim_path)
    try:
        target.write_text(
            json.dumps(
                _operation_receipt_payload(row, path, operation_id, expected),
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        try:
            identity = upload(row, claim_path, target, operation_id=operation_id)
        except StorageBackendError:
            identity = _operation_claim_identity(row, path, operation_id, expected)
            if identity is not None:
                pass
            else:
                raise
        _assert_no_foreign_destination_claim(row, path, operation_id)
        return identity
    finally:
        target.unlink(missing_ok=True)


def _write_operation_receipt(row, path: str, operation_id: str, expected: dict) -> dict:
    receipt_path = _operation_receipt_path(path, operation_id)
    target = temporary_path(row, receipt_path)
    try:
        target.write_text(
            json.dumps(
                _operation_receipt_payload(row, path, operation_id, expected),
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        try:
            return upload(row, receipt_path, target, operation_id=operation_id)
        except StorageBackendError:
            identity = _operation_receipt_identity(row, path, operation_id, expected)
            if identity is not None:
                return identity
            raise
    finally:
        target.unlink(missing_ok=True)


def seal_operation_receipt(
    row,
    path: str,
    operation_id: str,
    expected: dict,
    destination_identity: dict,
) -> dict:
    """Seal ownership only after this attempt publishes and verifies the destination."""
    if (
        _operation_claim_identity(row, path, operation_id, expected) is None
        or _operation_receipt_identity(row, path, operation_id, expected) is None
    ):
        raise StorageBackendError("destination ownership intent is missing")
    try:
        current = item(row, path)
    except StorageBackendError as exc:
        raise StorageBackendError("published destination is unavailable") from exc
    expected_kind = expected.get("kind")
    if expected_kind not in {"file", "dir"} or current.get("type") != expected_kind:
        raise StorageBackendError("published destination type changed before ownership was sealed")
    if expected_kind == "dir":
        if row.kind != "local":
            raise StorageBackendError(
                "remote folder transfers are unavailable because this backend cannot publish "
                "a complete tree atomically"
            )
        from services import file_operations

        try:
            current_path = local_path(row, path)
            current_fingerprint = file_operations.fingerprint(current_path)
            current["local_tree_identity"] = _local_tree_receipt_identity(current_path)
        except (file_operations.FileOperationError, OSError, StorageBackendError) as exc:
            raise StorageBackendError(
                "published destination changed before ownership was sealed"
            ) from exc
        if current_fingerprint != expected:
            raise StorageBackendError("published destination changed before ownership was sealed")
    if row.kind == "local":
        from services import file_operations

        try:
            current_path = local_path(row, path)
            current["local_publication_identity"] = file_operations._local_publication_identity(  # noqa: SLF001
                current_path
            )
        except (file_operations.FileOperationError, OSError) as exc:
            raise StorageBackendError(
                "published destination changed before ownership was sealed"
            ) from exc
    published_identity = _destination_receipt_identity(destination_identity)
    current_identity = _destination_receipt_identity(current)
    if row.kind == "local" and (
        not published_identity["local_device"] or not published_identity["local_inode"]
    ):
        raise StorageBackendError("published local destination identity is incomplete")
    if row.kind == "local" and not published_identity["local_publication_identity"]:
        raise StorageBackendError("published local destination identity is incomplete")
    if (
        row.kind == "local"
        and expected_kind == "dir"
        and not published_identity["local_tree_identity"]
    ):
        raise StorageBackendError("published local directory identity is incomplete")
    if row.kind in {"webdav", "s3"} and current.get("type") == "file":
        if not published_identity["etag"]:
            raise StorageBackendError("published remote destination identity is incomplete")
    if published_identity != current_identity:
        raise StorageBackendError("published destination changed before ownership was sealed")
    seal_path = _operation_seal_path(path, operation_id)
    target = temporary_path(row, seal_path)
    try:
        target.write_text(
            json.dumps(
                _operation_seal_payload(
                    row,
                    path,
                    operation_id,
                    expected,
                    published_identity,
                ),
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        try:
            identity = upload(row, seal_path, target, operation_id=operation_id)
        except StorageBackendError:
            identity = _operation_seal_identity(row, path, operation_id, expected)
            if identity is None:
                raise
        if _operation_seal_identity(
            row, path, operation_id, expected
        ) is None or not operation_receipt_matches(row, path, operation_id, expected):
            raise StorageBackendError("destination ownership seal could not be verified")
        return identity
    finally:
        target.unlink(missing_ok=True)


def temporary_path(row, path: str) -> Path:
    name = Path(storage_locations.normalize_path(path)).name or "storage-item"
    root = data_dir() / "storage-transfers" / row.id
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    prefix = f"{uuid.uuid4().hex}-"
    try:
        component_limit = int(os.pathconf(root, "PC_NAME_MAX"))
    except (AttributeError, OSError, TypeError, ValueError):
        component_limit = 255
    available = max(1, component_limit - len(prefix.encode("utf-8")))
    suffix = Path(name).suffix
    if len(suffix.encode("utf-8")) >= available:
        suffix = ""
    stem = name[: -len(suffix)] if suffix else name
    stem_limit = max(1, available - len(suffix.encode("utf-8")))
    encoded = stem.encode("utf-8")
    if len(encoded) > stem_limit:
        stem = encoded[:stem_limit].decode("utf-8", errors="ignore")
    if not stem:
        stem = "item"[:stem_limit]
    return root / f"{prefix}{stem}{suffix}"


def _copy_file(source: Path, destination: Path, *, max_bytes: int | None = None) -> dict:
    if source.is_symlink() or not source.is_file():
        raise StorageBackendError("source file is unavailable")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256()
    size = 0
    created = False
    try:
        with source.open("rb") as incoming:
            with destination.open("xb") as outgoing:
                created = True
                for chunk in iter(lambda: incoming.read(CHUNK_SIZE), b""):
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise StorageBackendError("storage file is too large")
                    digest.update(chunk)
                    outgoing.write(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return {"size": size, "checksum": digest.hexdigest(), "etag": "", "version_id": ""}


def _download_local(
    source: Path,
    target: Path,
    *,
    expected_size: int | None,
    max_bytes: int | None,
) -> dict:
    partial = internal_paths.artifact_sibling(target, "download", suffix=".partial")
    partial.unlink(missing_ok=True)
    try:
        result = _copy_file(source, partial, max_bytes=max_bytes)
        if expected_size is not None and result["size"] != expected_size:
            raise StorageBackendError("download size did not match")
        os.replace(partial, target)
        return result
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def download(
    row,
    path: str,
    destination: Path,
    *,
    expected_etag: str = "",
    expected_size: int | None = None,
    resume: bool = False,
    max_bytes: int | None = None,
) -> dict:
    normalized = storage_locations.normalize_path(path)
    target = Path(destination)
    expected_size = _optional_file_size(expected_size)
    max_bytes = _optional_file_size(max_bytes)
    try:
        if row.kind == "local":
            return _download_local(
                local_path(row, normalized),
                target,
                expected_size=expected_size,
                max_bytes=max_bytes,
            )
        if row.kind == "webdav":
            return webdav_locations.download(
                row,
                normalized,
                target,
                expected_etag=expected_etag,
                expected_size=expected_size,
                resume=resume,
                max_bytes=max_bytes,
            )
        if row.kind == "s3":
            result = s3_locations.download(
                row,
                normalized,
                target,
                expected_etag=expected_etag,
                expected_size=expected_size,
                resume=resume,
                max_bytes=max_bytes,
            )
            return result
    except (
        RuntimeError,
        ValueError,
        OSError,
        webdav_locations.WebDAVLocationError,
        s3_locations.S3LocationError,
    ) as exc:
        raise _translate(exc) from exc
    raise StorageBackendError("unsupported storage location")


def upload(
    row,
    path: str,
    source: Path,
    *,
    expected_etag: str = "",
    operation_id: str = "",
) -> dict:
    normalized = storage_locations.normalize_path(path)
    if row.access != "managed":
        raise StorageBackendError("storage location is read-only")
    _assert_no_foreign_destination_claim(row, normalized, operation_id)
    try:
        if row.kind == "local":
            destination = local_path(row, normalized)
            if destination.exists():
                raise StorageBackendError("destination already exists")
            result = _copy_file(Path(source), destination)
            result.update({"path": normalized, "name": destination.name})
            return result
        if row.kind == "webdav":
            return webdav_locations.upload(row, normalized, source, expected_etag=expected_etag)
        if row.kind == "s3":
            if operation_id and s3_locations.versioning_state(row) != "enabled":
                raise StorageBackendError(
                    "s3 operation ownership requires enabled bucket versioning"
                )
            result = s3_locations.upload(row, normalized, source, expected_etag=expected_etag)
            if operation_id and not _exact_s3_version_id(result.get("version_id")):
                raise StorageBackendError(
                    "s3 operation upload has no immutable version identity; "
                    "the remote object was preserved for reconciliation"
                )
            return result
    except StorageBackendError:
        raise
    except (
        RuntimeError,
        ValueError,
        OSError,
        webdav_locations.WebDAVLocationError,
        s3_locations.S3LocationError,
    ) as exc:
        raise _translate(exc) from exc
    raise StorageBackendError("unsupported storage location")


def mkdir(row, path: str, *, operation_id: str = "") -> dict:
    normalized = storage_locations.normalize_path(path)
    if row.access != "managed":
        raise StorageBackendError("storage location is read-only")
    _assert_no_foreign_destination_claim(row, normalized, operation_id)
    try:
        if row.kind == "local":
            return files_store.mkdir(normalized, root=storage_locations.local_root(row))
        if row.kind == "webdav":
            return webdav_locations.mkdir(row, normalized)
        if row.kind == "s3":
            return s3_locations.mkdir(row, normalized)
    except (
        RuntimeError,
        ValueError,
        OSError,
        webdav_locations.WebDAVLocationError,
        s3_locations.S3LocationError,
    ) as exc:
        raise _translate(exc) from exc
    raise StorageBackendError("unsupported storage location")


def read_text(row, path: str, limit: int = 200_000) -> dict:
    normalized = storage_locations.normalize_path(path)
    if row.kind == "local":
        try:
            return files_store.read_text(
                normalized, limit=limit, root=storage_locations.local_root(row)
            )
        except (RuntimeError, ValueError, OSError) as exc:
            raise _translate(exc) from exc
    info = item(row, normalized)
    if info.get("type") != "file":
        raise StorageBackendError("file preview requires a file")
    size = _optional_file_size(info.get("size"))
    etag = str(info.get("etag") or "")
    try:
        if size is None or size <= limit:
            target = temporary_path(row, normalized)
            try:
                result = download(
                    row,
                    normalized,
                    target,
                    expected_etag=etag,
                    expected_size=size,
                    max_bytes=limit,
                )
                raw = target.read_bytes()
            finally:
                target.unlink(missing_ok=True)
        elif row.kind == "webdav":
            result = webdav_locations.read_prefix(
                row,
                normalized,
                limit,
                expected_etag=etag,
                expected_size=size,
            )
            raw = result["content"]
        elif row.kind == "s3":
            result = s3_locations.read_prefix(
                row,
                normalized,
                limit,
                expected_etag=etag,
                expected_size=size,
                expected_version_id=str(info.get("version_id") or ""),
            )
            raw = result["content"]
        else:
            raise StorageBackendError("unsupported storage location")
    except StorageBackendError:
        raise
    except (
        RuntimeError,
        ValueError,
        OSError,
        webdav_locations.WebDAVLocationError,
        s3_locations.S3LocationError,
    ) as exc:
        raise _translate(exc) from exc
    result_size = _optional_file_size(result.get("size"))
    if result_size is None or len(raw) > limit or (size is None and result_size > limit):
        raise StorageBackendError("storage file preview is too large")
    try:
        content = raw.decode("utf-8")
        is_text = True
    except UnicodeError:
        content = ""
        is_text = False
    return {
        "path": normalized,
        "mime": mimetypes.guess_type(normalized)[0] or "application/octet-stream",
        "is_text": is_text,
        "content": content,
        "size": result_size,
        "truncated": result_size > limit,
        "etag": result.get("etag", ""),
        "version_id": result.get("version_id", ""),
    }


def remove_temporary(path: Path) -> None:
    target = Path(path)
    root = (data_dir() / "storage-transfers").resolve()
    try:
        resolved = target.resolve(strict=False)
        if root not in resolved.parents:
            return
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink(missing_ok=True)
            for artifact in (
                internal_paths.artifact_sibling(resolved, "download", suffix=".partial"),
                internal_paths.artifact_sibling(resolved, "download", suffix=".json"),
            ):
                artifact.unlink(missing_ok=True)
    except OSError:
        return


def item(row, path: str) -> dict:
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        return {"path": "", "normalized_path": "", "type": "dir", "etag": "", "version_id": ""}
    if row.kind == "local":
        target = local_path(row, normalized)
        if not target.exists():
            raise StorageNotFoundError("source not found")
        stat = target.stat()
        return {
            "path": normalized,
            "normalized_path": normalized,
            "type": "dir" if target.is_dir() else "file",
            "size": stat.st_size if target.is_file() else 0,
            "etag": "",
            "version_id": "",
            "local_device": stat.st_dev,
            "local_inode": stat.st_ino,
            "local_mtime_ns": stat.st_mtime_ns,
            "local_ctime_ns": stat.st_ctime_ns,
        }
    parent = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
    if normalized.endswith((RECEIPT_SUFFIX, CLAIM_SUFFIX, SEAL_SUFFIX)):
        try:
            listing = _raw_listdir(row, parent)
        except (
            RuntimeError,
            ValueError,
            webdav_locations.WebDAVLocationError,
            s3_locations.S3LocationError,
        ) as exc:
            raise _translate(exc) from exc
    else:
        listing = listdir(row, parent)
    for candidate in listing.get("items", []):
        if candidate.get("normalized_path") == normalized or candidate.get("path") == normalized:
            return candidate
    raise StorageNotFoundError("source not found")


def materialize(row, path: str, destination: Path, *, resume: bool = True) -> dict:
    """Create a verified local snapshot of a file or tree for a transfer operation."""
    from services import file_operations

    normalized = storage_locations.normalize_path(path)
    target = Path(destination)
    info = item(row, normalized)
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    if row.kind == "local":
        source = local_path(row, normalized)
        if source.is_dir():
            if any(child.is_symlink() for child in source.rglob("*")):
                raise StorageBackendError("symbolic links are not supported")
            source_tree_identity = _local_tree_receipt_identity(source)
        else:
            source_tree_identity = ""
        try:
            source_publication_identity = (
                file_operations._local_publication_identity(source)  # noqa: SLF001
            )
        except file_operations.FileOperationError as exc:
            raise StorageBackendError(str(exc)) from exc
        source_expected = file_operations.fingerprint(source)
        if source.is_dir():
            try:
                shutil.copytree(source, target, copy_function=shutil.copy2, symlinks=True)
                expected = file_operations.fingerprint(target)
            except file_operations.FileOperationError as exc:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
                raise StorageBackendError(str(exc)) from exc
        else:
            _copy_file(source, target)
            expected = file_operations.fingerprint(target)
        try:
            source_stable = file_operations.fingerprint(source) == source_expected
            source_stable = source_stable and (
                file_operations._local_publication_identity(source)  # noqa: SLF001
                == source_publication_identity
            )
            if source_tree_identity:
                source_stable = source_stable and (
                    _local_tree_receipt_identity(source) == source_tree_identity
                )
        except (file_operations.FileOperationError, OSError, StorageBackendError):
            source_stable = False
        if expected != source_expected or not source_stable:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
            raise StorageBackendError("source changed during transfer")
        info["local_tree_identity"] = source_tree_identity
        info["local_publication_identity"] = source_publication_identity
        return {
            **expected,
            **_destination_receipt_identity(info),
            "kind": expected["kind"],
        }
    if info.get("type") == "file":
        remote = download(
            row,
            normalized,
            target,
            expected_etag=info.get("etag", ""),
            expected_size=info.get("size"),
            resume=resume,
        )
        expected = file_operations.fingerprint(target)
        if remote.get("checksum") and remote["checksum"] != expected["checksum"]:
            raise StorageBackendError("download verification failed")
        return {**expected, **remote, "kind": "file", "type": "file"}
    target.mkdir(parents=True, exist_ok=False)
    queue = [normalized]
    manifest = []
    directory_markers = []

    def record_s3_marker(marker_path: str) -> None:
        if row.kind != "s3":
            return
        try:
            marker = s3_locations.directory_marker_metadata(row, marker_path)
        except s3_locations.S3LocationError as exc:
            raise _translate(exc) from exc
        if marker is not None:
            directory_markers.append(
                {
                    "path": marker_path,
                    "etag": marker.get("etag", ""),
                    "version_id": marker.get("version_id", ""),
                }
            )

    record_s3_marker(normalized)
    count = 0
    total = 0
    while queue:
        current = queue.pop(0)
        for child in listdir(row, current).get("items", []):
            count += 1
            if count > 10_000:
                raise StorageBackendError("storage folder has too many items")
            suffix = child["path"][len(normalized) :].lstrip("/")
            local = target / suffix
            if child.get("type") == "dir":
                local.mkdir(parents=True, exist_ok=True)
                queue.append(child["path"])
                manifest.append(dict(child))
                record_s3_marker(child["path"])
            else:
                local.parent.mkdir(parents=True, exist_ok=True)
                result = download(
                    row,
                    child["path"],
                    local,
                    expected_etag=child.get("etag", ""),
                    expected_size=child.get("size"),
                    resume=resume,
                )
                total += result["size"]
                manifest.append(
                    {
                        **child,
                        "etag": result.get("etag", child.get("etag", "")),
                        "version_id": result.get("version_id", child.get("version_id", "")),
                    }
                )
                if total > 4 * 1024 * 1024 * 1024:
                    raise StorageBackendError("storage folder is too large")
    expected = file_operations.fingerprint(target)
    return {
        **expected,
        "etag": info.get("etag", ""),
        "version_id": info.get("version_id", ""),
        "kind": "dir",
        "type": "dir",
        "manifest": manifest,
        "directory_markers": directory_markers,
    }


def upload_tree(row, path: str, source: Path, *, operation_id: str = "") -> dict:
    """Upload a local snapshot without replacing an existing destination."""
    from services import file_operations

    normalized = storage_locations.normalize_path(path)
    incoming = Path(source)
    expected = file_operations.fingerprint(incoming)
    try:
        current = item(row, normalized)
    except StorageNotFoundError:
        current = None
    owned = bool(
        operation_id
        and current is not None
        and operation_receipt_matches(row, normalized, operation_id, expected)
    )
    s3_versioning_state = ""
    if row.kind == "s3" and operation_id and (current is None or owned):
        try:
            s3_versioning_state = s3_locations.versioning_state(row)
        except s3_locations.S3LocationError as exc:
            raise _translate(exc) from exc
        if s3_versioning_state == "suspended" and not owned:
            raise StorageBackendError(
                "s3 transfers are unavailable while bucket versioning is suspended"
            )
    if current is not None and not owned:
        raise StorageBackendError("destination already exists")
    if current is not None and owned:
        check = temporary_path(row, f"verify-owned-{Path(normalized).name}")
        try:
            materialize(row, normalized, check, resume=False)
            if file_operations.fingerprint(check) != expected:
                raise StorageBackendError("destination changed during transfer")
        finally:
            remove_temporary(check)
        if s3_versioning_state == "enabled" and not _exact_s3_version_id(current.get("version_id")):
            raise StorageBackendError(
                "versioned s3 destination identity is incomplete; ownership was preserved"
            )
        return {
            **expected,
            "etag": current.get("etag", ""),
            "version_id": current.get("version_id", ""),
        }
    if current is None and operation_id and row.kind == "webdav" and incoming.is_file():
        try:
            webdav_locations._mutation_capabilities(row)  # noqa: SLF001
        except webdav_locations.WebDAVLocationError as exc:
            raise _translate(exc) from exc
    if current is None and operation_id:
        if row.kind == "s3":
            if incoming.is_dir() and s3_versioning_state == "enabled":
                raise StorageBackendError(
                    "versioned s3 folder transfers are unavailable because exact child versions cannot be owned"
                )
        if incoming.is_dir() and row.kind in {"webdav", "s3"}:
            raise StorageBackendError(
                "remote folder transfers are unavailable because this backend cannot publish "
                "a complete tree atomically"
            )
        if row.kind == "s3" and s3_versioning_state != "enabled":
            raise StorageBackendError("s3 operation ownership requires enabled bucket versioning")
        claim_identity = _write_operation_claim(row, normalized, operation_id, expected)
        receipt_identity = _write_operation_receipt(row, normalized, operation_id, expected)
        artifact_identities = (claim_identity, receipt_identity)
        if row.kind == "s3" and any(
            str(identity.get("version_id") or "").strip().lower() == "null"
            for identity in artifact_identities
        ):
            raise StorageBackendError(
                "s3 null-version transfers are unavailable; private ownership intent was preserved"
            )
        if s3_versioning_state == "enabled" and any(
            not _exact_s3_version_id(identity.get("version_id")) for identity in artifact_identities
        ):
            raise StorageBackendError(
                "versioned s3 transfer artifact identity is incomplete; private ownership intent was preserved"
            )
    elif current is None and incoming.is_dir() and row.kind in {"webdav", "s3"}:
        raise StorageBackendError(
            "remote folder transfers are unavailable because this backend cannot publish "
            "a complete tree atomically"
        )
    if incoming.is_file():
        if row.kind == "local" and operation_id:
            destination = local_path(row, normalized)
            clean_id = "".join(
                value for value in str(operation_id) if value.isalnum() or value == "-"
            )
            if not clean_id:
                raise StorageBackendError("operation identity is invalid")
            partial = internal_paths.operation_sibling(destination, clean_id, PARTIAL_SUFFIX)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if partial.exists() or partial.is_symlink():
                if partial.is_symlink() or not partial.is_file():
                    if partial.is_dir() and not partial.is_symlink():
                        shutil.rmtree(partial)
                    else:
                        partial.unlink(missing_ok=True)
                elif file_operations.fingerprint(partial) != expected:
                    partial.unlink()
            if not partial.exists():
                try:
                    _copy_file(incoming, partial)
                except OSError as exc:
                    raise _translate(exc) from exc
            if (
                file_operations.fingerprint(incoming) != expected
                or file_operations.fingerprint(partial) != expected
            ):
                partial.unlink(missing_ok=True)
                raise StorageBackendError("source changed during transfer")
            if destination.exists() or destination.is_symlink():
                raise StorageBackendError("destination already exists")
            publication_identity = file_operations._local_publication_identity(  # noqa: SLF001
                partial
            )
            file_operations._rename_no_replace(partial, destination)  # noqa: SLF001
            published = item(row, normalized)
            if (
                file_operations._local_publication_identity(destination)  # noqa: SLF001
                != publication_identity
                or file_operations.fingerprint(destination) != expected
            ):
                raise StorageBackendError("upload verification failed")
            published["local_publication_identity"] = publication_identity
            return {**expected, **_destination_receipt_identity(published)}
        result = upload(row, normalized, incoming, operation_id=operation_id)
        if s3_versioning_state == "enabled" and not _exact_s3_version_id(result.get("version_id")):
            raise StorageBackendError(
                "versioned s3 upload identity is incomplete; private ownership intent was preserved"
            )
        return {**expected, **result}

    if row.kind == "local" and operation_id:
        destination = local_path(row, normalized)
        clean_id = "".join(value for value in str(operation_id) if value.isalnum() or value == "-")
        if not clean_id:
            raise StorageBackendError("operation identity is invalid")
        partial = internal_paths.operation_sibling(destination, clean_id, PARTIAL_SUFFIX)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if partial.exists() or partial.is_symlink():
            if partial.is_symlink() or not partial.is_dir():
                partial.unlink(missing_ok=True)
            elif file_operations.fingerprint(partial) != expected:
                shutil.rmtree(partial)
        if not partial.exists():
            try:
                shutil.copytree(incoming, partial, copy_function=shutil.copy2)
            except Exception as exc:
                if partial.is_dir():
                    shutil.rmtree(partial, ignore_errors=True)
                else:
                    partial.unlink(missing_ok=True)
                if isinstance(exc, file_operations.FileOperationError):
                    raise StorageBackendError(str(exc)) from exc
                if isinstance(exc, OSError):
                    raise _translate(exc) from exc
                raise
        if (
            file_operations.fingerprint(incoming) != expected
            or file_operations.fingerprint(partial) != expected
        ):
            shutil.rmtree(partial, ignore_errors=True)
            raise StorageBackendError("source changed during transfer")
        if destination.exists() or destination.is_symlink():
            raise StorageBackendError("destination already exists")
        publication_identity = file_operations._local_publication_identity(  # noqa: SLF001
            partial
        )
        file_operations._rename_no_replace(partial, destination)  # noqa: SLF001
        published = item(row, normalized)
        published["local_tree_identity"] = _local_tree_receipt_identity(destination)
        if (
            file_operations._local_publication_identity(destination)  # noqa: SLF001
            != publication_identity
            or file_operations.fingerprint(destination) != expected
        ):
            raise StorageBackendError("upload verification failed")
        published["local_publication_identity"] = publication_identity
        return {**expected, **_destination_receipt_identity(published)}

    created_dirs: set[str] = set()

    def ensure_dir(destination: str) -> None:
        try:
            current = item(row, destination)
        except StorageNotFoundError:
            mkdir(row, destination, operation_id=operation_id)
            created_dirs.add(destination)
            return
        if current.get("type") != "dir" or destination not in created_dirs:
            raise StorageBackendError("destination already exists")

    if current is None:
        ensure_dir(normalized)
    for child in sorted(
        incoming.rglob("*"), key=lambda value: value.relative_to(incoming).as_posix()
    ):
        relative = child.relative_to(incoming).as_posix()
        destination = f"{normalized}/{relative}" if normalized else relative
        if child.is_dir():
            ensure_dir(destination)
        else:
            try:
                existing = item(row, destination)
            except StorageNotFoundError:
                existing = None
            if existing is not None:
                raise StorageBackendError("destination already exists")
            upload(row, destination, child, operation_id=operation_id)
    return {**expected, **_destination_receipt_identity(item(row, normalized))}


def delete_tree(
    row,
    path: str,
    *,
    expected: dict | None = None,
    expected_etag: str = "",
    version_id: str = "",
    verified_meta: dict | None = None,
    operation_id: str = "",
    owned_version: bool = False,
    missing_ok: bool = True,
) -> None:
    """Delete a source only after an optional fresh snapshot matches expected bytes."""
    from services import file_operations

    normalized = storage_locations.normalize_path(path)
    if row.kind == "s3" and owned_version:
        if expected and expected.get("kind") != "file":
            raise StorageBackendError(
                "operation-owned s3 folder versions cannot be deleted without a complete version manifest"
            )
        if not expected_etag or not _exact_s3_version_id(version_id):
            raise StorageBackendError("operation-owned s3 version identity is incomplete")
        try:
            s3_locations.delete_owned_version(
                row,
                normalized,
                expected_etag=expected_etag,
                version_id=version_id,
            )
        except s3_locations.S3LocationError as exc:
            raise _translate(exc) from exc
        return
    source_meta = dict(verified_meta or {})
    if expected and source_meta:
        verified_identity = {
            key: source_meta.get(key) for key in ("kind", "size", "count", "checksum")
        }
        if verified_identity != expected:
            raise StorageBackendError("verified source metadata does not match its fingerprint")
    elif expected:
        check = temporary_path(row, f"verify-delete-{Path(normalized).name}")
        try:
            source_meta = materialize(row, normalized, check, resume=False)
            if file_operations.fingerprint(check) != expected:
                raise StorageBackendError("source changed; delete stopped")
        finally:
            remove_temporary(check)
    if row.kind == "local":
        target = local_path(row, normalized)
        clean_id = "".join(value for value in str(operation_id) if value.isalnum() or value == "-")
        quarantine = internal_paths.operation_sibling(
            target,
            f"delete-{clean_id or uuid.uuid4().hex}",
            "",
        )

        def restore_quarantine() -> None:
            if not (target.exists() or target.is_symlink()):
                file_operations._rename_no_replace(quarantine, target)  # noqa: SLF001

        if clean_id and (quarantine.exists() or quarantine.is_symlink()):
            try:
                quarantine_fingerprint = (
                    file_operations.fingerprint(quarantine) if expected else None
                )
            except (file_operations.FileOperationError, OSError) as exc:
                restore_quarantine()
                raise StorageBackendError("source identity changed; delete stopped") from exc
            if expected and quarantine_fingerprint != expected:
                restore_quarantine()
                raise StorageBackendError("quarantined source changed during operation")
            expected_publication = str(source_meta.get("local_publication_identity") or "")
            try:
                quarantine_publication = (
                    file_operations._local_publication_identity(quarantine)  # noqa: SLF001
                    if source_meta
                    else ""
                )
            except (file_operations.FileOperationError, OSError) as exc:
                restore_quarantine()
                raise StorageBackendError("source identity changed; delete stopped") from exc
            if source_meta and (
                not expected_publication or quarantine_publication != expected_publication
            ):
                restore_quarantine()
                raise StorageBackendError("quarantined source identity changed during operation")
            if quarantine.is_dir():
                shutil.rmtree(quarantine)
            else:
                quarantine.unlink()
            return
        if source_meta and not (target.exists() or target.is_symlink()):
            if missing_ok:
                return
            raise StorageNotFoundError("source disappeared before delete")
        if source_meta and not _same_local_path_receipt_identity(target, source_meta):
            raise StorageBackendError("source changed; delete stopped")
        publication_identity = str(source_meta.get("local_publication_identity") or "")
        try:
            file_operations._rename_no_replace(target, quarantine)  # noqa: SLF001
        except FileNotFoundError as exc:
            if missing_ok:
                return
            raise StorageNotFoundError("source disappeared before delete") from exc

        try:
            quarantine_identity = (
                file_operations._local_publication_identity(quarantine)  # noqa: SLF001
                if source_meta
                else ""
            )
            quarantine_fingerprint = file_operations.fingerprint(quarantine) if expected else None
        except (file_operations.FileOperationError, OSError) as exc:
            restore_quarantine()
            raise StorageBackendError("source identity changed; delete stopped") from exc
        if source_meta and (
            not publication_identity or quarantine_identity != publication_identity
        ):
            restore_quarantine()
            raise StorageBackendError("source identity changed; delete stopped")
        if expected and quarantine_fingerprint != expected:
            restore_quarantine()
            raise StorageBackendError("source changed; delete stopped")
        if quarantine.is_dir():
            shutil.rmtree(quarantine)
        else:
            quarantine.unlink()
        return
    if source_meta:
        info = source_meta
    else:
        try:
            info = item(row, normalized)
        except StorageNotFoundError:
            if missing_ok:
                return
            raise
    delete_etag = expected_etag or info.get("etag", "")
    delete_version = version_id or info.get("version_id", "")
    if row.kind == "webdav":
        if info.get("type") != "file":
            raise StorageBackendError(
                "webdav folder deletion is unavailable because the server cannot guarantee a safe delete"
            )
        try:
            webdav_locations.delete(row, normalized, expected_etag=delete_etag)
        except webdav_locations.WebDAVNotFoundError as exc:
            if source_meta and missing_ok:
                return
            if not missing_ok:
                raise StorageNotFoundError("source disappeared before delete") from exc
            raise StorageBackendError("webdav delete failed with status 404")
        except webdav_locations.WebDAVLocationError as exc:
            raise _translate(exc) from exc
        return
    if info.get("type") == "file":
        try:
            s3_locations.delete(
                row,
                normalized,
                expected_etag=delete_etag,
                version_id=delete_version,
            )
        except s3_locations.S3NotFoundError as exc:
            if source_meta and missing_ok:
                return
            if not missing_ok:
                raise StorageNotFoundError("source disappeared before delete") from exc
            raise
        except s3_locations.S3VersionedDeleteRefused as exc:
            identity = {
                "etag": exc.metadata.get("etag", ""),
                "version_id": exc.metadata.get("version_id", ""),
                "manifest": None,
                "directory_markers": None,
            }
            raise StorageVersionedDeleteRefused(
                str(exc),
                before_mutation=True,
                source_identity=identity,
            ) from exc
        except s3_locations.S3LocationError as exc:
            raise _translate(exc) from exc
        return
    if expected:
        manifest = source_meta.get("manifest")
        if not isinstance(manifest, list):
            raise StorageBackendError("verified s3 directory manifest is missing")
        clean_manifest = []
        prefix = f"{normalized}/" if normalized else ""
        for child in manifest:
            if not isinstance(child, dict) or child.get("type") not in {"file", "dir"}:
                raise StorageBackendError("verified s3 directory manifest is invalid")
            try:
                child_path = storage_locations.normalize_path(child.get("path", ""))
            except ValueError as exc:
                raise StorageBackendError("verified s3 directory manifest is invalid") from exc
            if not child_path or not child_path.startswith(prefix):
                raise StorageBackendError("verified s3 directory manifest escaped its source")
            clean_manifest.append({**child, "path": child_path})
        directories = [
            normalized,
            *[child["path"] for child in clean_manifest if child.get("type") == "dir"],
        ]
        files = [child for child in clean_manifest if child.get("type") == "file"]
        allowed = {child["path"]: child for child in clean_manifest}
        seen = set()
        queue = [normalized]
        while queue:
            current_path = queue.pop(0)
            for child in listdir(row, current_path).get("items", []):
                try:
                    child_path = storage_locations.normalize_path(child.get("path", ""))
                except ValueError as exc:
                    raise StorageBackendError("source changed; delete stopped") from exc
                verified_child = allowed.get(child_path)
                if not verified_child or verified_child.get("type") != child.get("type"):
                    raise StorageBackendError("source changed; delete stopped")
                seen.add(child_path)
                if child.get("type") == "file":
                    for key in ("etag", "version_id"):
                        verified_value = str(verified_child.get(key) or "")
                        if verified_value and str(child.get(key) or "") != verified_value:
                            raise StorageBackendError("source changed; delete stopped")
                else:
                    queue.append(child_path)
        if not missing_ok and seen != set(allowed):
            raise StorageBackendError("source changed; delete stopped")
    else:
        queue = [normalized]
        directories = [normalized]
        files = []
        while queue:
            current = queue.pop(0)
            for child in listdir(row, current).get("items", []):
                if child.get("type") == "dir":
                    directories.append(child["path"])
                    queue.append(child["path"])
                else:
                    files.append(child)
    if owned_version:
        raise StorageBackendError(
            "operation-owned s3 folder versions cannot be deleted without a complete version manifest"
        )
    if any(str(child.get("version_id") or "") for child in files):
        raise StorageVersionedDeleteRefused(
            "versioned s3 objects cannot be deleted atomically; source was preserved",
            before_mutation=True,
        )
    expected_markers = None
    if expected and "directory_markers" in source_meta:
        markers = source_meta.get("directory_markers")
        if not isinstance(markers, list):
            raise StorageBackendError("verified s3 directory marker manifest is invalid")
        expected_markers = {
            str(marker.get("path") or ""): marker
            for marker in markers
            if isinstance(marker, dict) and marker.get("path")
        }
        if len(expected_markers) != len(markers):
            raise StorageBackendError("verified s3 directory marker manifest is invalid")
        for directory in directories:
            try:
                current_marker = s3_locations.directory_marker_metadata(row, directory)
            except s3_locations.S3LocationError as exc:
                raise _translate(exc) from exc
            verified_marker = expected_markers.get(directory)
            if verified_marker is None:
                if current_marker is not None:
                    raise StorageBackendError("source changed; delete stopped")
                continue
            if current_marker is None or any(
                str(current_marker.get(key) or "") != str(verified_marker.get(key) or "")
                for key in ("etag", "version_id")
            ):
                raise StorageBackendError("source changed; delete stopped")
            if current_marker.get("version_id"):
                raise StorageVersionedDeleteRefused(
                    "versioned s3 objects cannot be deleted atomically; source was preserved",
                    before_mutation=True,
                )
    deleted_any = False
    for child in reversed(files):
        try:
            s3_locations.delete(
                row,
                child["path"],
                expected_etag=child.get("etag", ""),
                version_id=child.get("version_id", ""),
            )
        except s3_locations.S3NotFoundError as exc:
            if source_meta and missing_ok:
                continue
            if not missing_ok:
                raise StorageNotFoundError("source disappeared before delete") from exc
            raise
        except s3_locations.S3VersionedDeleteRefused as exc:
            raise StorageVersionedDeleteRefused(
                str(exc),
                before_mutation=not deleted_any,
            ) from exc
        except s3_locations.S3LocationError as exc:
            raise _translate(exc) from exc
        deleted_any = True
    for directory in sorted(directories, key=lambda value: value.count("/"), reverse=True):
        try:
            verified_marker = (
                expected_markers.get(directory) if expected_markers is not None else None
            )
            if expected_markers is not None and verified_marker is None:
                continue
            if verified_marker is not None:
                s3_locations.delete(
                    row,
                    directory,
                    expected_etag=verified_marker.get("etag", ""),
                    version_id=verified_marker.get("version_id", ""),
                    directory=True,
                )
            else:
                s3_locations.delete_directory_marker(row, directory)
        except s3_locations.S3NotFoundError as exc:
            if not missing_ok and verified_marker is not None:
                raise StorageNotFoundError("source disappeared before delete") from exc
            if missing_ok:
                continue
            raise
        except s3_locations.S3VersionedDeleteRefused as exc:
            raise StorageVersionedDeleteRefused(
                str(exc),
                before_mutation=not deleted_any,
            ) from exc
        except s3_locations.S3LocationError as exc:
            raise _translate(exc) from exc
        deleted_any = True
    if expected:
        queue = [normalized]
        while queue:
            current_path = queue.pop(0)
            remaining = listdir(row, current_path).get("items", [])
            if remaining:
                raise StorageBackendError("source changed; delete stopped")


def _release_operation_artifact(row, artifact_path: str, metadata: dict) -> None:
    try:
        if row.kind == "local":
            target = local_path(row, artifact_path)
            if target.is_symlink():
                raise StorageBackendError("operation ownership artifact changed before cleanup")
            try:
                stat = target.stat(follow_symlinks=False)
            except FileNotFoundError:
                return
            expected_identity = (
                int(metadata.get("local_device") or 0),
                int(metadata.get("local_inode") or 0),
                int(metadata.get("local_mtime_ns") or 0),
                int(metadata.get("local_ctime_ns") or 0),
                int(metadata.get("size") or 0),
            )
            current_identity = (
                int(stat.st_dev),
                int(stat.st_ino),
                int(stat.st_mtime_ns),
                int(stat.st_ctime_ns),
                int(stat.st_size),
            )
            if not expected_identity[0] or expected_identity != current_identity:
                raise StorageBackendError("operation ownership artifact changed before cleanup")
            target.unlink()
        elif row.kind == "webdav":
            webdav_locations.delete(row, artifact_path, expected_etag=metadata.get("etag", ""))
        elif row.kind == "s3":
            artifact_version = str(metadata.get("version_id") or "")
            if artifact_version:
                s3_locations.delete_owned_version(
                    row,
                    artifact_path,
                    expected_etag=metadata.get("etag", ""),
                    version_id=artifact_version,
                )
            else:
                s3_locations.delete(
                    row,
                    artifact_path,
                    expected_etag=metadata.get("etag", ""),
                    version_id="",
                )
    except (webdav_locations.WebDAVLocationError, s3_locations.S3LocationError) as exc:
        raise _translate(exc) from exc


def release_operation_receipt(row, path: str, operation_id: str, expected: dict) -> None:
    """Remove this operation's exclusive intent and post-publication seal."""
    artifacts = (
        (
            _operation_seal_path(path, operation_id),
            _operation_seal_identity(row, path, operation_id, expected),
        ),
        (
            _operation_receipt_path(path, operation_id),
            _operation_receipt_identity(row, path, operation_id, expected),
        ),
        (
            _operation_claim_path(path),
            _operation_claim_identity(row, path, operation_id, expected),
        ),
    )
    verified_artifacts = []
    for artifact_path, metadata in artifacts:
        if metadata is None:
            try:
                item(row, artifact_path)
            except StorageNotFoundError:
                continue
            raise StorageBackendError("operation ownership artifact is invalid")
        verified_artifacts.append((artifact_path, metadata))
    for artifact_path, metadata in verified_artifacts:
        _release_operation_artifact(row, artifact_path, metadata)


def incomplete_operation_upload_is_releasable(
    row, path: str, operation_id: str, expected: dict
) -> bool:
    """Return whether private intent can be removed without deleting visible data."""
    identities = []
    claim_identity = _operation_claim_identity(row, path, operation_id, expected)
    if claim_identity is not None:
        identities.append(claim_identity)
    seal_path = _operation_seal_path(path, operation_id)
    try:
        item(row, seal_path)
    except StorageNotFoundError:
        pass
    else:
        # A sealed destination has provable ownership and must resume normal recovery.
        return False
    for artifact_path, identity in (
        (
            _operation_receipt_path(path, operation_id),
            _operation_receipt_identity(row, path, operation_id, expected),
        ),
    ):
        try:
            item(row, artifact_path)
        except StorageNotFoundError:
            continue
        if identity is None:
            return False
        identities.append(identity)
    if row.kind in {"webdav", "s3"} and any(
        not str(identity.get("etag") or "") for identity in identities
    ):
        return False
    return True


def release_incomplete_operation_upload(
    row,
    path: str,
    operation_id: str,
    expected: dict,
    *,
    ownership_was_claimed: bool = False,
) -> None:
    """Remove private upload artifacts while preserving any visible destination."""
    if not incomplete_operation_upload_is_releasable(row, path, operation_id, expected):
        raise StorageBackendError(
            "incomplete upload still has data or private artifacts that cannot be released safely"
        )
    artifact_owned = any(
        identity is not None
        for identity in (
            _operation_claim_identity(row, path, operation_id, expected),
            _operation_receipt_identity(row, path, operation_id, expected),
            _operation_seal_identity(row, path, operation_id, expected),
        )
    )
    if not artifact_owned and not ownership_was_claimed:
        raise StorageBackendError("incomplete upload ownership receipt is missing")
    # A local partial has no independently durable inode receipt. Preserve it;
    # once the receipt is removed it becomes a normal visible Files entry.
    if artifact_owned:
        release_operation_receipt(row, path, operation_id, expected)
