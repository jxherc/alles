"""Verified Files-to-Photos imports without replacing the specialist Photos app."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

from core.database import Photo
from services import file_operations, photos_store, storage_backends, storage_locations

MAX_IMPORT_ITEMS = 2_000


class FilesToPhotosError(RuntimeError):
    pass


def _photo(info: dict, *, album_id: str, source_id: str, modified_at: datetime) -> Photo:
    return Photo(
        filename=info["filename"],
        thumb=info["thumb"],
        original_name=info["original_name"],
        width=info["width"],
        height=info["height"],
        taken_at=info["taken_at"],
        exif=info["exif"],
        aspect_ratio=info.get("aspect_ratio"),
        preview=info.get("preview", ""),
        checksum=info.get("checksum"),
        is_video=info.get("is_video", False),
        album_id=album_id or None,
        source="files",
        source_id=source_id,
        source_modified_at=modified_at,
    )


def _candidates(root: Path, *, source_name: str) -> tuple[list[Path], int]:
    if root.is_symlink():
        raise FilesToPhotosError("symbolic links are not supported")
    if root.is_file():
        return ([root] if photos_store.supports_media(source_name) else []), (
            0 if photos_store.supports_media(source_name) else 1
        )
    if not root.is_dir():
        raise FilesToPhotosError("file is unavailable")
    items = list(islice(root.rglob("*"), MAX_IMPORT_ITEMS + 1))
    if len(items) > MAX_IMPORT_ITEMS:
        raise FilesToPhotosError("folder has too many items")
    media = []
    ignored = 0
    for item in sorted(items, key=lambda value: value.relative_to(root).as_posix()):
        if item.is_symlink():
            ignored += 1
            continue
        if not item.is_file():
            continue
        if photos_store.supports_media(item.name):
            media.append(item)
        else:
            ignored += 1
    return media, ignored


def import_from_files(
    db,
    *,
    location_id: str,
    path: str,
    album_id: str = "",
) -> dict:
    location = storage_locations.require_browsable(db, location_id)
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise FilesToPhotosError("path required")
    temporary = None
    if location.kind == "local":
        root = storage_backends.local_path(location, normalized)
    else:
        temporary = storage_backends.temporary_path(location, normalized)
        try:
            storage_backends.materialize(location, normalized, temporary, resume=True)
        except storage_backends.StorageBackendError as exc:
            storage_backends.remove_temporary(temporary)
            raise FilesToPhotosError(str(exc)) from exc
        root = temporary
    imported = []
    skipped = []
    failed = []
    created_files = []
    try:
        candidates, ignored = _candidates(root, source_name=Path(normalized).name)
        for candidate in candidates:
            relative = "" if root.is_file() else candidate.relative_to(root).as_posix()
            source_path = normalized if not relative else f"{normalized}/{relative}"
            original_name = Path(source_path).name
            source_id = f"{location.id}:{source_path}"
            expected = file_operations.fingerprint(candidate)
            existing = (
                db.query(Photo)
                .filter(
                    Photo.source == "files",
                    Photo.source_id == source_id,
                    Photo.checksum == expected["checksum"],
                )
                .first()
            )
            if existing:
                skipped.append({"path": source_path, "photo_id": existing.id})
                continue
            created = None
            try:
                with db.begin_nested():
                    info = photos_store.import_media_path(candidate, original_name)
                    created = (info["filename"], info.get("thumb", ""))
                    modified_at = datetime.fromtimestamp(candidate.stat().st_mtime, UTC).replace(
                        tzinfo=None
                    )
                    photo = _photo(
                        info,
                        album_id=album_id,
                        source_id=source_id,
                        modified_at=modified_at,
                    )
                    db.add(photo)
                    db.flush()
                created_files.append(created)
                imported.append({"path": source_path, "photo_id": photo.id})
            except Exception as exc:
                if created is not None:
                    photos_store.delete_files(*created)
                failed.append({"path": source_path, "error": str(exc)[:120]})
        db.commit()
        return {
            "ok": not failed,
            "partial": bool(failed) and bool(imported or skipped),
            "location_id": location.id,
            "path": normalized,
            "imported": len(imported),
            "skipped": len(skipped),
            "ignored": ignored,
            "failed": failed,
            "items": imported + skipped,
        }
    except Exception:
        db.rollback()
        for filename, thumb in created_files:
            photos_store.delete_files(filename, thumb)
        raise
    finally:
        if temporary is not None:
            storage_backends.remove_temporary(temporary)
