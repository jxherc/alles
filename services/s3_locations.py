"""Fail-closed S3-compatible transport for browsable Files locations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from core.settings import data_dir
from services import internal_paths, s3_backup, storage_locations

MAX_FILE_BYTES = s3_backup.MAX_ARTIFACT_BYTES
MAX_LISTING_BYTES = s3_backup.MAX_LISTING_BYTES
MAX_LISTING_PAGES = s3_backup.MAX_LISTING_PAGES
MAX_ITEMS = s3_backup.MAX_LISTED_ARTIFACTS
CHUNK_SIZE = 1024 * 1024
CLIENT_FACTORY = None


class S3LocationError(RuntimeError):
    pass


class S3VersionedDeleteRefused(S3LocationError):
    """A logical delete that stopped before issuing any DELETE request."""

    def __init__(self, message: str, *, metadata: dict):
        self.metadata = dict(metadata)
        super().__init__(message)


class S3NotFoundError(S3LocationError):
    pass


class S3ConflictError(S3LocationError):
    def __init__(self, conflict_path: Path):
        self.conflict_path = conflict_path
        super().__init__(f"remote file changed; preserved at {conflict_path.name}")


def _json_object(value: str, message: str) -> dict:
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError) as exc:
        raise S3LocationError(message) from exc
    if not isinstance(result, dict):
        raise S3LocationError(message)
    return result


def _config(row) -> dict:
    public = _json_object(row.config, "s3 configuration is invalid")
    secret = _json_object(row.secret, "s3 credentials are invalid")
    try:
        credentials = s3_backup._credentials_json(
            secret.get("access_key_id", ""),
            secret.get("secret_access_key", ""),
        )
        return s3_backup._validated_config(
            {
                "endpoint": row.endpoint,
                "region": public.get("region", "us-east-1"),
                "bucket": row.bucket,
                "prefix": str(row.prefix or "").strip("/"),
                "addressing_style": public.get("addressing_style", "path"),
                "credentials": credentials,
            }
        )
    except s3_backup.S3Error as exc:
        raise S3LocationError(str(exc)) from exc


def _client(config):
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY(config)
    return s3_backup._new_client(config)


def _send(client, config, method: str, url: str, **kwargs):
    try:
        return s3_backup._send(client, config, method, url, **kwargs)
    except s3_backup.S3Error as exc:
        raise S3LocationError(str(exc)) from exc


def _require(response, accepted: set[int], action: str) -> None:
    if response.status_code in accepted:
        return
    if response.status_code in {401, 403}:
        raise S3LocationError("s3 authentication or permission check failed")
    if response.status_code in {409, 412}:
        raise S3LocationError(f"s3 {action} conflicted with remote state")
    if response.status_code == 507:
        raise S3LocationError("s3 storage is full")
    raise S3LocationError(f"s3 {action} failed with status {response.status_code}")


def _root(document: bytes, action: str):
    try:
        return s3_backup._xml_root(document, action)
    except s3_backup.S3Error as exc:
        raise S3LocationError(str(exc)) from exc


def _bounded(response, maximum: int) -> bytes:
    try:
        return s3_backup._read_bounded(response, maximum)
    except s3_backup.S3Error as exc:
        raise S3LocationError(str(exc)) from exc


def _safe_etag(value: str) -> str:
    try:
        return s3_backup._safe_etag(value)
    except s3_backup.S3Error as exc:
        raise S3LocationError(str(exc)) from exc


def _prefix(config: dict, path: str = "", *, folder: bool = False) -> str:
    normalized = storage_locations.normalize_path(path)
    parts = [value for value in (config.get("prefix", ""), normalized) if value]
    result = "/".join(parts)
    if folder and result and not result.endswith("/"):
        result += "/"
    return result


def _relative(config: dict, key: str) -> str | None:
    base = _prefix(config, folder=True)
    if base and not key.startswith(base):
        return None
    value = key[len(base) :] if base else key
    try:
        return storage_locations.normalize_path(value)
    except ValueError:
        return None


def _listing_url(
    config: dict,
    path: str,
    token: str | tuple[str, str] = "",
    *,
    versions: bool = False,
) -> str:
    query = [
        ("delimiter", "/"),
        ("max-keys", "1000"),
        ("prefix", _prefix(config, path, folder=True)),
    ]
    if versions:
        query.insert(0, ("versions", ""))
        key_marker, version_marker = token if isinstance(token, tuple) else (token, "")
        if key_marker:
            query.append(("key-marker", key_marker))
        if version_marker:
            query.append(("version-id-marker", version_marker))
    else:
        query.insert(0, ("list-type", "2"))
        if token:
            query.append(("continuation-token", token))
    return s3_backup._bucket_url(config, query)


def _text(node, name: str) -> str:
    for child in node:
        if s3_backup._local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _version_id(value: str) -> str:
    normalized = str(value or "").strip()[:1024]
    return "" if normalized.casefold() == "null" else normalized


def _parse_page(
    config: dict, document: bytes, requested_path: str, *, versions: bool
) -> tuple[list[dict], str | tuple[str, str]]:
    root = _root(document, "listing")
    requested = storage_locations.normalize_path(requested_path)
    found: dict[str, dict] = {}
    next_token = ""
    next_version_token = ""
    for node in root:
        name = s3_backup._local_name(node.tag)
        if name in {"NextContinuationToken", "NextKeyMarker"}:
            next_token = (node.text or "").strip()[:2048]
            continue
        if name == "NextVersionIdMarker":
            next_version_token = (node.text or "").strip()[:2048]
            continue
        if name == "CommonPrefixes":
            key = _text(node, "Prefix").rstrip("/")
            relative = _relative(config, key)
            if relative is None or relative == requested:
                continue
            item_name = relative.rsplit("/", 1)[-1]
            found[relative] = {
                "name": item_name,
                "path": relative,
                "normalized_path": relative,
                "type": "dir",
                "size": 0,
                "mtime": "",
                "etag": "",
                "version_id": "",
            }
            continue
        if name not in ({"Version"} if versions else {"Contents"}):
            continue
        if versions and _text(node, "IsLatest").casefold() not in {"true", "1"}:
            continue
        key = _text(node, "Key")
        if not key or key.endswith("/"):
            continue
        relative = _relative(config, key)
        if relative is None:
            continue
        parent = relative.rsplit("/", 1)[0] if "/" in relative else ""
        if parent != requested:
            continue
        size_raw = _text(node, "Size")
        if size_raw and not size_raw.isdigit():
            raise S3LocationError("s3 listing size is invalid")
        etag = _text(node, "ETag")
        if etag:
            etag = _safe_etag(etag)
        found[relative] = {
            "name": relative.rsplit("/", 1)[-1],
            "path": relative,
            "normalized_path": relative,
            "type": "file",
            "size": int(size_raw) if size_raw else None,
            "mtime": _text(node, "LastModified")[:256],
            "etag": etag,
            "version_id": _version_id(_text(node, "VersionId")) if versions else "",
        }
    token = (next_token, next_version_token) if versions else next_token
    return list(found.values()), token


def _list(config: dict, path: str, *, versions: bool) -> list[dict]:
    items: dict[str, dict] = {}
    token: str | tuple[str, str] = ("", "") if versions else ""
    with _client(config) as client:
        for _page in range(MAX_LISTING_PAGES):
            response = _send(
                client, config, "GET", _listing_url(config, path, token, versions=versions)
            )
            with closing(response):
                _require(response, {200}, "listing")
                page, token = _parse_page(
                    config,
                    _bounded(response, MAX_LISTING_BYTES),
                    path,
                    versions=versions,
                )
            for item in page:
                items[item["path"]] = item
                if len(items) > MAX_ITEMS:
                    raise S3LocationError("s3 listing is too large")
            has_next = any(token) if isinstance(token, tuple) else bool(token)
            if not has_next:
                break
        else:
            raise S3LocationError("s3 listing has too many pages")
    return sorted(items.values(), key=lambda item: (item["type"] != "dir", item["name"].lower()))


def capabilities(row) -> dict:
    config = _config(row)
    with _client(config) as client:
        response = _send(client, config, "GET", _listing_url(config, ""))
        with closing(response):
            _require(response, {200}, "connection test")
            _parse_page(config, _bounded(response, MAX_LISTING_BYTES), "", versions=False)
    try:
        versioned = versioning_state(row) == "enabled"
    except S3LocationError:
        versioned = False
    return {
        "ok": True,
        "state": "ready",
        "writable": row.access == "managed",
        "supports_etag": True,
        "supports_ranges": True,
        "supports_versions": versioned,
        "non_atomic_move": True,
    }


def versioning_state(row) -> str:
    """Return enabled, suspended, or unversioned before any transfer artifact is written."""
    config = _config(row)
    with _client(config) as client:
        response = _send(
            client,
            config,
            "GET",
            s3_backup._bucket_url(config, [("versioning", "")]),
        )
        with closing(response):
            _require(response, {200}, "versioning check")
            root = _root(_bounded(response, 64 * 1024), "versioning check")
    status = _text(root, "Status")
    if status == "Enabled":
        return "enabled"
    if status == "Suspended":
        return "suspended"
    if not status:
        return "unversioned"
    raise S3LocationError("s3 versioning state is invalid")


def listdir(row, path: str = "") -> dict:
    normalized = storage_locations.normalize_path(path)
    config = _config(row)
    live_items = _list(config, normalized, versions=False)
    try:
        versioned = versioning_state(row) == "enabled"
    except S3LocationError:
        versioned = False
    if not versioned:
        return {"path": normalized, "items": live_items, "version_ids": False}
    version_items = _list(config, normalized, versions=True)
    current_versions = {item["path"]: item for item in version_items if item.get("type") == "file"}
    items = [
        current_versions.get(item["path"], item) if item.get("type") == "file" else item
        for item in live_items
    ]
    return {"path": normalized, "items": items, "version_ids": True}


def _version_url(url: str, version_id: str) -> str:
    if not version_id:
        return url
    return f"{url}?versionId={quote(version_id, safe='-_.~')}"


def _head(row, path: str, *, folder: bool = False, version_id: str = "") -> dict:
    config = _config(row)
    key = _prefix(config, path, folder=folder)
    if not key:
        raise S3LocationError("path required")
    with _client(config) as client:
        url = _version_url(s3_backup._object_url(config, key), version_id)
        response = _send(client, config, "HEAD", url)
        with closing(response):
            if response.status_code == 404:
                raise S3NotFoundError("source not found")
            _require(response, {200}, "metadata check")
            length = response.headers.get("content-length", "")
            if not length.isdigit():
                raise S3LocationError("s3 object size is invalid")
            return {
                "size": int(length),
                "etag": _safe_etag(response.headers.get("etag", "")),
                "version_id": _version_id(response.headers.get("x-amz-version-id", "")),
                "supports_ranges": response.headers.get("accept-ranges", "").lower() == "bytes",
            }


def directory_marker_metadata(row, path: str) -> dict | None:
    """Return the current exact identity of an optional S3 directory marker."""
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise S3LocationError("path required")
    try:
        return _head(row, normalized, folder=True)
    except S3NotFoundError:
        return None


def _partial_paths(target: Path) -> tuple[Path, Path]:
    partial = internal_paths.artifact_sibling(target, "download", suffix=".partial")
    identity = internal_paths.artifact_sibling(target, "download", suffix=".json")
    return partial, identity


def _discard_partial(partial: Path, identity_path: Path) -> None:
    partial.unlink(missing_ok=True)
    identity_path.unlink(missing_ok=True)


def _load_partial_identity(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _file_chunks(path: Path):
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            yield chunk


def read_prefix(
    row,
    path: str,
    limit: int,
    *,
    expected_etag: str,
    expected_size: int,
    expected_version_id: str = "",
) -> dict:
    """Read a bounded prefix after proving the listed object is still current."""
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise S3LocationError("path required")
    if not expected_etag:
        raise S3LocationError("a verified ETag is required before previewing")
    if not isinstance(expected_size, int) or not 0 <= expected_size <= MAX_FILE_BYTES:
        raise S3LocationError("s3 object size is invalid")
    if not isinstance(limit, int) or limit <= 0:
        raise S3LocationError("s3 preview limit is invalid")
    metadata = _head(row, normalized, version_id=expected_version_id)
    if (
        metadata["size"] != expected_size
        or metadata["etag"] != expected_etag
        or (expected_version_id and metadata["version_id"] != expected_version_id)
    ):
        raise S3LocationError("remote file changed")
    if expected_size == 0:
        return {
            "content": b"",
            "size": 0,
            "etag": metadata["etag"],
            "version_id": metadata["version_id"],
        }
    prefix_size = min(limit, expected_size)
    config = _config(row)
    url = _version_url(
        s3_backup._object_url(config, _prefix(config, normalized)),
        metadata["version_id"],
    )
    headers = {
        "Accept-Encoding": "identity",
        "If-Match": metadata["etag"],
        "Range": f"bytes=0-{prefix_size - 1}",
    }
    with _client(config) as client:
        response = _send(client, config, "GET", url, headers=headers)
        with closing(response):
            if response.status_code == 200:
                if prefix_size != expected_size:
                    raise S3LocationError("s3 server ignored the preview range")
            if response.status_code == 412:
                raise S3LocationError("remote file changed")
            _require(response, {200, 206}, "preview")
            response_etag = _safe_etag(response.headers.get("etag", ""))
            response_version = _version_id(response.headers.get("x-amz-version-id", ""))
            if response_etag != metadata["etag"] or (
                metadata["version_id"] and response_version != metadata["version_id"]
            ):
                raise S3LocationError("remote file changed")
            if response.status_code == 206:
                match = re.fullmatch(
                    r"bytes\s+(\d+)-(\d+)/(\d+)",
                    response.headers.get("content-range", "").strip(),
                    flags=re.IGNORECASE,
                )
                if match is None:
                    raise S3LocationError("s3 preview range is invalid")
                range_start, range_end, range_total = (int(value) for value in match.groups())
                if range_start != 0 or range_end != prefix_size - 1 or range_total != expected_size:
                    raise S3LocationError("s3 preview range did not match")
            declared = response.headers.get("content-length", "")
            if declared and (not declared.isdigit() or int(declared) != prefix_size):
                raise S3LocationError("s3 preview range did not match")
            content = _bounded(response, prefix_size)
            if len(content) != prefix_size:
                raise S3LocationError("s3 preview range did not match")
    return {
        "content": content,
        "size": metadata["size"],
        "etag": metadata["etag"],
        "version_id": metadata["version_id"],
    }


def download(
    row,
    path: str,
    destination: Path,
    *,
    expected_etag: str = "",
    expected_size: int | None = None,
    resume: bool = False,
    max_bytes: int | None = None,
    expected_version_id: str = "",
) -> dict:
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise S3LocationError("path required")
    config = _config(row)
    metadata = _head(row, normalized, version_id=expected_version_id)
    if metadata["size"] > MAX_FILE_BYTES:
        raise S3LocationError("s3 file is too large")
    if expected_size is not None:
        if (
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or expected_size < 0
        ):
            raise S3LocationError("s3 object size is invalid")
        if metadata["size"] != expected_size:
            raise S3LocationError("download size did not match")
    if max_bytes is not None and metadata["size"] > max_bytes:
        raise S3LocationError("s3 file is too large")
    if expected_etag and metadata["etag"] != expected_etag:
        raise S3LocationError("remote file changed")
    if expected_version_id and metadata["version_id"] != expected_version_id:
        raise S3LocationError("remote file changed")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial, identity_path = _partial_paths(target)
    identity = _load_partial_identity(identity_path)
    current_identity = {
        "etag": metadata["etag"],
        "version_id": metadata["version_id"],
        "size": metadata["size"],
    }
    resumable = (
        resume
        and metadata["supports_ranges"]
        and partial.is_file()
        and identity == current_identity
        and 0 < partial.stat().st_size < metadata["size"]
    )
    start = partial.stat().st_size if resumable else 0
    if partial.exists() and not start:
        _discard_partial(partial, identity_path)
    identity_path.write_text(json.dumps(current_identity, sort_keys=True), encoding="utf-8")
    headers = {"Accept-Encoding": "identity", "If-Match": metadata["etag"]}
    if start:
        headers["Range"] = f"bytes={start}-"
    digest = hashlib.sha256()
    if start:
        with partial.open("rb") as previous:
            for chunk in iter(lambda: previous.read(CHUNK_SIZE), b""):
                digest.update(chunk)
    with _client(config) as client:
        response = _send(
            client,
            config,
            "GET",
            _version_url(
                s3_backup._object_url(config, _prefix(config, normalized)),
                metadata["version_id"],
            ),
            headers=headers,
        )
        with closing(response):
            if start and response.status_code != 206:
                _discard_partial(partial, identity_path)
                return download(
                    row,
                    normalized,
                    target,
                    expected_etag=metadata["etag"],
                    expected_size=expected_size,
                    resume=False,
                    max_bytes=max_bytes,
                    expected_version_id=metadata["version_id"],
                )
            _require(response, {200, 206}, "download")
            try:
                response_etag = _safe_etag(response.headers.get("etag", ""))
            except S3LocationError:
                _discard_partial(partial, identity_path)
                raise
            response_version = _version_id(response.headers.get("x-amz-version-id", ""))
            if response_etag != metadata["etag"] or response_version != metadata["version_id"]:
                _discard_partial(partial, identity_path)
                raise S3LocationError("remote file changed")
            if start:
                match = re.fullmatch(
                    r"bytes\s+(\d+)-(\d+)/(\d+)",
                    response.headers.get("content-range", "").strip(),
                    flags=re.IGNORECASE,
                )
                if match is None:
                    _discard_partial(partial, identity_path)
                    raise S3LocationError("s3 download range is invalid")
                range_start, range_end, range_total = (int(value) for value in match.groups())
                if (
                    range_start != start
                    or range_end < range_start
                    or range_end + 1 != range_total
                    or range_total != metadata["size"]
                ):
                    _discard_partial(partial, identity_path)
                    raise S3LocationError("s3 download range did not match")
            mode = "ab" if start else "xb"
            total = start
            try:
                with partial.open(mode) as handle:
                    for chunk in s3_backup._response_chunks(response):
                        total += len(chunk)
                        if total > MAX_FILE_BYTES or (max_bytes is not None and total > max_bytes):
                            raise S3LocationError("s3 file is too large")
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                if not resume:
                    _discard_partial(partial, identity_path)
                raise
    if total != metadata["size"]:
        if not resume:
            _discard_partial(partial, identity_path)
        raise S3LocationError("s3 download size did not match")
    os.replace(partial, target)
    identity_path.unlink(missing_ok=True)
    return {
        "size": total,
        "checksum": digest.hexdigest(),
        "etag": metadata["etag"],
        "version_id": metadata["version_id"],
    }


def _conflict_path(row, path: str) -> Path:
    root = data_dir() / "storage-conflicts" / row.id
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return internal_paths.bounded_named_child(
        root,
        Path(path).name or "remote-file",
        prefix=uuid.uuid4().hex[:12],
    )


def _preserve_incoming_conflict(incoming: Path, conflict: Path, checksum: str) -> None:
    digest = hashlib.sha256()
    try:
        with incoming.open("rb") as source, conflict.open("xb") as destination:
            for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if digest.hexdigest() != checksum:
            raise S3LocationError("incoming conflict copy could not be verified")
    except Exception:
        conflict.unlink(missing_ok=True)
        raise


def upload(row, path: str, source: Path, *, expected_etag: str = "") -> dict:
    if row.access != "managed":
        raise S3LocationError("storage location is read-only")
    normalized = storage_locations.normalize_path(path)
    incoming = Path(source)
    if not normalized or incoming.is_symlink() or not incoming.is_file():
        raise S3LocationError("upload source is invalid")
    size = incoming.stat().st_size
    if size > MAX_FILE_BYTES:
        raise S3LocationError("s3 file is too large")
    digest = hashlib.sha256()
    with incoming.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    checksum = digest.hexdigest()
    config = _config(row)
    if expected_etag:
        expected_etag = _safe_etag(expected_etag)
    headers = {
        "Content-Length": str(size),
        "If-Match" if expected_etag else "If-None-Match": expected_etag or "*",
    }
    with _client(config) as client:
        response = _send(
            client,
            config,
            "PUT",
            s3_backup._object_url(config, _prefix(config, normalized)),
            headers=headers,
            content=_file_chunks(incoming),
            payload_hash=checksum,
        )
        with closing(response):
            if response.status_code == 412:
                conflict = _conflict_path(row, normalized)
                try:
                    _preserve_incoming_conflict(incoming, conflict, checksum)
                except Exception:
                    conflict.unlink(missing_ok=True)
                    raise S3LocationError("incoming file changed and could not be preserved")
                raise S3ConflictError(conflict)
            _require(response, {200, 201}, "upload")
            etag = _safe_etag(response.headers.get("etag", ""))
            version_id = _version_id(response.headers.get("x-amz-version-id", ""))
    verify_root = data_dir() / "storage-conflicts" / row.id
    verify_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    verify = internal_paths.bounded_named_child(
        verify_root,
        "verify",
        prefix=uuid.uuid4().hex[:12],
    )
    try:
        remote = download(
            row,
            normalized,
            verify,
            expected_etag=etag,
            expected_version_id=version_id,
        )
        if remote["size"] != size or remote["checksum"] != checksum:
            raise S3LocationError("uploaded file could not be verified")
        if version_id:
            if remote["version_id"] != version_id:
                raise S3LocationError("uploaded s3 version could not be verified")
        elif remote["version_id"]:
            raise S3LocationError(
                "s3 did not return the created version identity; uploaded object was preserved"
            )
    except Exception as verification_error:
        if etag and version_id:
            try:
                delete_owned_version(
                    row,
                    normalized,
                    expected_etag=etag,
                    version_id=version_id,
                )
            except S3LocationError as cleanup_error:
                raise S3LocationError(
                    "upload verification failed and the owned s3 object could not be removed"
                ) from cleanup_error
        if etag and not version_id:
            raise S3LocationError(
                "upload verification failed without an exact s3 version identity; "
                "the uploaded object was preserved for reconciliation"
            ) from verification_error
        raise
    finally:
        verify.unlink(missing_ok=True)
    return {"size": size, "checksum": checksum, "etag": etag, "version_id": version_id}


def delete(
    row,
    path: str,
    *,
    expected_etag: str = "",
    version_id: str = "",
    directory: bool = False,
) -> None:
    if row.access != "managed":
        raise S3LocationError("storage location is read-only")
    normalized = storage_locations.normalize_path(path)
    config = _config(row)
    key = _prefix(config, normalized, folder=directory)
    base_url = s3_backup._object_url(config, key)
    exact_metadata = _head(row, normalized, folder=directory, version_id=version_id)
    if expected_etag and exact_metadata["etag"] != expected_etag:
        raise S3LocationError("remote file changed")
    if version_id and exact_metadata["version_id"] and exact_metadata["version_id"] != version_id:
        raise S3LocationError("remote file changed")
    if version_id or exact_metadata["version_id"]:
        raise S3VersionedDeleteRefused(
            "versioned s3 objects cannot be deleted atomically; source was preserved",
            metadata=exact_metadata,
        )
    if versioning_state(row) != "unversioned":
        raise S3VersionedDeleteRefused(
            "versioned s3 objects cannot be deleted atomically; source was preserved",
            metadata=exact_metadata,
        )
    metadata = exact_metadata
    url = base_url
    with _client(config) as client:
        headers = {
            "Content-Length": "0",
            "If-Match": expected_etag or metadata["etag"],
        }
        response = _send(client, config, "DELETE", url, headers=headers, content=b"")
        with closing(response):
            if response.status_code == 412:
                raise S3LocationError("remote file changed")
            _require(response, {200, 204}, "delete")
    try:
        _head(row, normalized, folder=directory)
    except S3NotFoundError:
        return
    raise S3LocationError("s3 delete could not be verified")


def delete_owned_version(
    row,
    path: str,
    *,
    expected_etag: str,
    version_id: str,
    directory: bool = False,
) -> None:
    """Delete only an exact S3 version created by a durable operation."""
    if row.access != "managed":
        raise S3LocationError("storage location is read-only")
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise S3LocationError("path required")
    if not isinstance(expected_etag, str) or not expected_etag:
        raise S3LocationError("a verified ETag is required before deleting an owned version")
    if (
        not isinstance(version_id, str)
        or not version_id.strip()
        or version_id.strip().lower() == "null"
    ):
        raise S3LocationError("an exact version ID is required before deleting an owned version")
    expected_etag = _safe_etag(expected_etag)

    try:
        metadata = _head(row, normalized, folder=directory, version_id=version_id)
    except S3NotFoundError:
        return
    if metadata["etag"] != expected_etag or metadata["version_id"] != version_id:
        raise S3LocationError("remote file changed")

    config = _config(row)
    key = _prefix(config, normalized, folder=directory)
    url = _version_url(s3_backup._object_url(config, key), version_id)
    with _client(config) as client:
        response = _send(
            client,
            config,
            "DELETE",
            url,
            headers={"Content-Length": "0"},
            content=b"",
        )
        with closing(response):
            _require(response, {200, 204, 404}, "owned version delete")

    try:
        _head(row, normalized, folder=directory, version_id=version_id)
    except S3NotFoundError:
        return
    raise S3LocationError("s3 owned version delete could not be verified")


def delete_directory_marker(row, path: str) -> None:
    """Logically delete an optional zero-byte folder marker."""
    try:
        metadata = _head(row, path, folder=True)
        if metadata["size"] != 0:
            raise S3LocationError("s3 directory marker is not empty; object was preserved")
        if metadata["version_id"]:
            raise S3VersionedDeleteRefused(
                "versioned s3 directory markers cannot be deleted atomically; marker was preserved",
                metadata=metadata,
            )
        else:
            delete(row, path, expected_etag=metadata["etag"], directory=True)
    except S3NotFoundError:
        return


def mkdir(row, path: str) -> dict:
    if row.access != "managed":
        raise S3LocationError("storage location is read-only")
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise S3LocationError("path required")
    if versioning_state(row) != "unversioned":
        raise S3LocationError(
            "s3 folder creation is unavailable while bucket versioning is enabled or suspended"
        )
    config = _config(row)
    key = _prefix(config, normalized, folder=True)
    checksum = hashlib.sha256(b"").hexdigest()
    with _client(config) as client:
        response = _send(
            client,
            config,
            "PUT",
            s3_backup._object_url(config, key),
            headers={"Content-Length": "0", "If-None-Match": "*"},
            content=b"",
            payload_hash=checksum,
        )
        with closing(response):
            _require(response, {200, 201}, "create folder")
    return {"path": normalized, "type": "dir"}
