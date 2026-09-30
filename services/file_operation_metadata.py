"""live Files metadata, trash snapshots and external metadata asset cleanup.

file_operations owns byte verification, claims and recovery before these
transitions. rekey and trash snapshots use its transaction; permanent purge
retains fileversions' existing commit-before-blob-cleanup behavior.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_

from core.database import (
    FileComment,
    FileTag,
    FileVersion,
    IndexChunk,
    OfflineFile,
    Photo,
    Share,
    TrashItem,
)
from services import fileversions
from services.file_operation_paths import FileOperationError
from services.file_operation_paths import normalize_item_path as _normal

METADATA_MODELS = (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk)
METADATA_MODELS_BY_NAME = {model.__name__: model for model in METADATA_MODELS}


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
    for model, record in _live_metadata_records(db, source_location_id, source):
        identity = _metadata_identity(model, record)
        moved = _mapped_path(identity, source, destination)
        record.location_id = destination_location_id
        record.normalized_path = moved
        if hasattr(record, "path"):
            record.path = moved
        if hasattr(record, "ref"):
            record.ref = moved

    old_photo_key = f"{source_location_id}:{source}"
    escaped_key = old_photo_key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    photos = (
        db.query(Photo)
        .filter(
            Photo.source == "files",
            or_(
                Photo.source_id == old_photo_key,
                Photo.source_id.like(f"{escaped_key}/%", escape="\\"),
            ),
        )
        .all()
    )
    for photo in photos:
        old_path = photo.source_id[len(source_location_id) + 1 :]
        new_key = f"{destination_location_id}:{_mapped_path(old_path, source, destination)}"
        owner = db.query(Photo).filter_by(source="files", source_id=new_key).first()
        if owner is None or owner.id == photo.id:
            photo.source_id = new_key


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


def _ensure_metadata_destination_clear(db, location_id: str, path: str) -> None:
    """Reject stale destination identities before moving any bytes."""
    for _model, _record in _live_metadata_records(db, location_id, path):
        raise FileOperationError("destination metadata already exists")
