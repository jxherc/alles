"""Storage Location identity and safe public serialization for Files."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.database import (
    DEFAULT_LOCAL_STORAGE_LOCATION_ID,
    FileComment,
    FileOperation,
    FileTag,
    FileVersion,
    IndexChunk,
    OfflineFile,
    Share,
    StorageLocation,
    TrashItem,
    normalize_file_identity_path,
)

KINDS = frozenset({"local", "webdav", "s3"})
ACCESS = frozenset({"read_only", "managed"})


def normalize_path(value: str) -> str:
    return normalize_file_identity_path(value)


def ensure_default_local(db) -> StorageLocation:
    from services import files_store

    row = db.get(StorageLocation, DEFAULT_LOCAL_STORAGE_LOCATION_ID)
    if row is None:
        db.execute(
            sqlite_insert(StorageLocation)
            .values(
                id=DEFAULT_LOCAL_STORAGE_LOCATION_ID,
                name="on this server",
                kind="local",
                access="managed",
                root_path=str(files_store.root_dir()),
                enabled=True,
                is_default=True,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        db.commit()
        db.expire_all()
        row = db.get(StorageLocation, DEFAULT_LOCAL_STORAGE_LOCATION_ID)
        if row is None:
            raise RuntimeError("default storage location could not be initialized")
    elif not (row.root_path or "").strip():
        # m0033 cannot know the runtime ALLES_DATA path. Fill it lazily the first
        # time the application opens Files, without replacing an owner-set root.
        row.root_path = str(files_store.root_dir())
        db.commit()
        db.refresh(row)
    return row


def get_location(db, location_id: str | None = None) -> StorageLocation | None:
    if not location_id or location_id == DEFAULT_LOCAL_STORAGE_LOCATION_ID:
        return ensure_default_local(db)
    return db.get(StorageLocation, location_id)


def require_browsable(db, location_id: str | None = None) -> StorageLocation:
    row = get_location(db, location_id)
    if row is None:
        raise LookupError("storage location not found")
    if not row.enabled:
        raise RuntimeError("storage location is disabled")
    return row


def require_default_browsable(db, location_id: str | None = None) -> StorageLocation:
    """Compatibility name used by Files routes while all enabled locations become browsable."""
    return require_browsable(db, location_id)


def local_root(row: StorageLocation) -> Path:
    if row.kind != "local":
        raise RuntimeError("storage location is not local")
    raw_root = str(row.root_path or "").strip()
    if not raw_root:
        raise RuntimeError("storage location root is invalid")
    root = Path(raw_root).expanduser().resolve(strict=False)
    if not root.is_absolute():
        raise RuntimeError("storage location root is invalid")
    return root


def public_dict(row: StorageLocation) -> dict:
    try:
        config = json.loads(row.config or "{}")
    except (TypeError, ValueError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    try:
        public_config = clean_config(row.kind, config)
    except ValueError:
        # A legacy malformed value must not break the location list. It stays
        # unusable until the owner replaces the location with valid settings.
        public_config = {}
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "access": row.access,
        "root_path": row.root_path or "",
        "endpoint": row.endpoint or "",
        "bucket": row.bucket or "",
        "prefix": row.prefix or "",
        "config": public_config,
        "enabled": bool(row.enabled),
        "is_default": bool(row.is_default),
    }


def validate_values(
    *,
    name: str,
    kind: str,
    access: str,
    root_path: str = "",
    endpoint: str = "",
    bucket: str = "",
) -> dict:
    clean_name = str(name or "").strip()
    clean_kind = str(kind or "").strip().lower()
    clean_access = str(access or "").strip().lower()
    if not clean_name:
        raise ValueError("name required")
    if clean_kind not in KINDS:
        raise ValueError("kind must be local, webdav, or s3")
    if clean_access not in ACCESS:
        raise ValueError("access must be read_only or managed")
    clean_root = str(root_path or "").strip()
    clean_endpoint = str(endpoint or "").strip()
    clean_bucket = str(bucket or "").strip()
    if clean_kind == "local":
        root = Path(clean_root).expanduser()
        if not clean_root or not root.is_absolute():
            raise ValueError("local root must be an absolute path")
        clean_root = str(root.resolve(strict=False))
    elif clean_kind == "webdav":
        try:
            parsed = urlsplit(clean_endpoint)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("WebDAV endpoint is invalid") from exc
        if (
            not parsed.hostname
            or parsed.scheme not in {"https", "http"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (
                parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            )
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError("WebDAV endpoint must use HTTPS or loopback HTTP")
    else:
        from services import s3_backup

        try:
            clean_endpoint = s3_backup.normalize_endpoint(clean_endpoint)
            clean_bucket = s3_backup._clean_bucket(clean_bucket)
        except s3_backup.S3Error as exc:
            raise ValueError(str(exc)) from exc
    return {
        "name": clean_name,
        "kind": clean_kind,
        "access": clean_access,
        "root_path": clean_root,
        "endpoint": clean_endpoint,
        "bucket": clean_bucket,
    }


def clean_config(kind: str, value: dict | None) -> dict:
    if value is None:
        source = {}
    elif isinstance(value, dict):
        source = value
    else:
        raise ValueError("storage configuration is invalid")
    if kind == "s3":
        from services import s3_backup

        if set(source) - {"region", "addressing_style"}:
            raise ValueError("s3 configuration is invalid")
        result = {}
        try:
            if "region" in source:
                result["region"] = s3_backup._clean_region(source["region"])
            if "addressing_style" in source:
                result["addressing_style"] = s3_backup._clean_addressing(source["addressing_style"])
        except s3_backup.S3Error as exc:
            raise ValueError(str(exc)) from exc
        return result
    if source:
        raise ValueError("storage configuration is invalid")
    return {}


def clean_credentials(kind: str, value: dict | None) -> dict:
    source = value if isinstance(value, dict) else {}
    if kind == "webdav":
        if set(source) - {"username", "password"}:
            raise ValueError("WebDAV credentials are invalid")
        if any(not isinstance(source.get(key, ""), str) for key in ("username", "password")):
            raise ValueError("WebDAV credentials are invalid")
        return {"username": source.get("username", ""), "password": source.get("password", "")}
    if kind == "s3":
        from services import s3_backup

        if set(source) != {"access_key_id", "secret_access_key"}:
            raise ValueError("s3 credentials are invalid")
        try:
            canonical = s3_backup._credentials_json(
                source["access_key_id"], source["secret_access_key"]
            )
        except s3_backup.S3Error as exc:
            raise ValueError(str(exc)) from exc
        return json.loads(canonical)
    return source


def test_location(row: StorageLocation) -> dict:
    if row.kind == "webdav":
        from services import webdav_locations

        try:
            return webdav_locations.capabilities(row)
        except webdav_locations.WebDAVLocationError as exc:
            return {"ok": False, "state": "error", "writable": False, "error": str(exc)}
    if row.kind == "s3":
        from services import s3_locations

        try:
            return s3_locations.capabilities(row)
        except s3_locations.S3LocationError as exc:
            return {"ok": False, "state": "error", "writable": False, "error": str(exc)}
    root = Path(row.root_path or "").expanduser()
    if not root.is_absolute() or not root.exists() or not root.is_dir():
        return {"ok": False, "state": "unavailable", "writable": False}
    writable = root.stat().st_mode != 0 and root.is_dir() and _can_write(root)
    return {
        "ok": True,
        "state": "ready",
        "writable": bool(writable and row.access == "managed"),
    }


def _can_write(root: Path) -> bool:
    import os

    return os.access(root, os.W_OK)


def has_references(db, location_id: str) -> bool:
    metadata_reference = any(
        db.query(model).filter(column == location_id).first() is not None
        for model, column in (
            (FileTag, FileTag.location_id),
            (FileComment, FileComment.location_id),
            (FileVersion, FileVersion.location_id),
            (OfflineFile, OfflineFile.location_id),
            (TrashItem, TrashItem.location_id),
            (Share, Share.location_id),
        )
    )
    if metadata_reference:
        return True
    active = (
        db.query(FileOperation)
        .filter(
            (
                (FileOperation.source_location_id == location_id)
                | (FileOperation.destination_location_id == location_id)
            ),
            FileOperation.state.in_(
                ("queued", "running", "failed", "cancelled", "undoing", "undoing_claimed")
            ),
        )
        .first()
    )
    if active is not None:
        return True
    completed = (
        db.query(FileOperation)
        .filter(
            (
                (FileOperation.source_location_id == location_id)
                | (FileOperation.destination_location_id == location_id)
            ),
            FileOperation.state.in_(("completed", "undoing", "undoing_claimed")),
        )
        .all()
    )
    for operation in completed:
        try:
            details = json.loads(operation.undo_json or "{}")
        except (TypeError, ValueError):
            details = {}
        if details.get("undo"):
            return True
    return False


def clear_derived_index(db, location_id: str) -> int:
    """Remove search rows that can be rebuilt from the storage location."""
    return (
        db.query(IndexChunk)
        .filter(IndexChunk.location_id == location_id)
        .delete(synchronize_session=False)
    )
