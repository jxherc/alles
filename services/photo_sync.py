"""
photo sync — import a folder of images into the photos library, skipping anything
already imported (tracked by path + mtime/size). this is the cross-platform core:
point it at an iCloud Drive folder, a Photos export, Dropbox, whatever syncs to
disk, and it pulls new shots in.

the macOS Photos *library* itself (PhotoKit) isn't a plain folder. a scoped,
signed Swift helper reads it, while this module retains stable source identity
and feeds each materialized resource through the same local media store.
"""

import hashlib
import json
import sys
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from core.database import Photo, SessionLocal
from core.settings import data_dir, load_settings
from services import photos_store

_IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp"}
_STATE: Path | None = None
_MAC_JOBS: dict[str, dict] = {}
_MAC_JOB_LOCK = threading.Lock()


def _state_file() -> Path:
    return _STATE or data_dir() / "photo_sync_state.json"


def parse_takeout_sidecar(data: dict) -> dict:
    """pull taken-time + GPS out of a Google Takeout JSON sidecar. Takeout writes
    0.0 lat/lon when there's no location, so those are ignored."""
    out = {}
    ts = (data.get("photoTakenTime") or {}).get("timestamp")
    if ts:
        try:
            out["taken_at"] = datetime.utcfromtimestamp(int(ts))
        except (ValueError, TypeError):
            pass
    geo = data.get("geoData") or data.get("geoDataExif") or {}
    lat, lon = geo.get("latitude"), geo.get("longitude")
    if lat and lon:
        try:
            out["lat"], out["lon"] = round(float(lat), 6), round(float(lon), 6)
        except (ValueError, TypeError):
            pass
    return out


def _find_sidecar(p: Path):
    """Takeout sidecar next to an image: IMG.jpg.json / IMG.jpg.supplemental-metadata.json / IMG.json."""
    for cand in (
        p.parent / (p.name + ".json"),
        p.parent / (p.name + ".supplemental-metadata.json"),
        p.with_suffix(".json"),
    ):
        if cand.is_file():
            return cand
    return None


def _load_state() -> dict:
    try:
        return json.loads(_state_file().read_text("utf-8"))
    except Exception:
        return {}


def _save_state(s: dict):
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(s), "utf-8")


def _sig(p: Path) -> str:
    st = p.stat()
    return f"{int(st.st_mtime)}:{st.st_size}"


def sync_folder(src: str, db=None, limit: int = 2000) -> dict:
    """import new images from a folder (recursive). returns counts; re-running
    only pulls files that are new or changed since last time."""
    root = Path(src).expanduser()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"not a folder: {src}")
    state = _load_state()
    key_root = str(root.resolve())
    seen = state.get(key_root, {})
    own = db is None
    db = db or SessionLocal()
    imported = skipped = failed = 0
    try:
        for p in sorted(root.rglob("*")):
            if imported >= limit:
                break
            if not p.is_file() or p.suffix.lower() not in _IMG_EXT:
                continue
            k = str(p.resolve())
            sig = _sig(p)
            if seen.get(k) == sig:
                skipped += 1
                continue
            try:
                info = photos_store.import_image(p.read_bytes(), p.name)
                # Google Takeout sidecar (if present) is authoritative for date + GPS
                sc = _find_sidecar(p)
                if sc:
                    try:
                        meta = parse_takeout_sidecar(json.loads(sc.read_text("utf-8")))
                        if meta.get("taken_at"):
                            info["taken_at"] = meta["taken_at"]
                        if "lat" in meta:
                            ex = json.loads(info["exif"] or "{}")
                            ex["lat"], ex["lon"] = meta["lat"], meta["lon"]
                            info["exif"] = json.dumps(ex)
                    except Exception:
                        pass
                db.add(
                    Photo(
                        filename=info["filename"],
                        thumb=info["thumb"],
                        original_name=info["original_name"],
                        width=info["width"],
                        height=info["height"],
                        taken_at=info["taken_at"],
                        exif=info["exif"],
                        is_video=info.get("is_video", False),
                        aspect_ratio=info.get("aspect_ratio"),
                        preview=info.get("preview", ""),
                        checksum=info.get("checksum"),
                    )
                )
                seen[k] = sig
                imported += 1
            except Exception:
                failed += 1
        db.commit()
        state[key_root] = seen
        _save_state(state)
    finally:
        if own:
            db.close()
    return {"imported": imported, "skipped": skipped, "failed": failed}


def run_watch(db=None, limit: int = 2000) -> dict:
    """phone-camera backup (7c): if a watch folder is configured, pull new shots from it.
    safe to call on a timer — no-ops when unset/missing, dedups via sync_folder state."""
    folder = (load_settings().get("photos_watch_folder") or "").strip()
    if not folder:
        return {"skipped": "no watch folder"}
    root = Path(folder).expanduser()
    if not root.exists() or not root.is_dir():
        return {"skipped": "folder not found"}
    return sync_folder(str(root), db, limit)


# ── native Apple Photos / PhotoKit sync ───────────────────────────────────────
def _apply_photokit_metadata(info: dict, item) -> dict:
    exif = json.loads(info.get("exif") or "{}")
    exif.update(item.exif or {})
    info["exif"] = json.dumps(exif)
    if item.taken_at:
        info["taken_at"] = item.taken_at
    if item.width and not info.get("width"):
        info["width"] = item.width
    if item.height and not info.get("height"):
        info["height"] = item.height
    if info.get("width") and info.get("height"):
        info["aspect_ratio"] = info["width"] / info["height"]
    return info


def _update_photokit_row(row: Photo, item) -> bool:
    changed = False
    values = {
        "source_asset_id": item.asset_id,
        "taken_at": item.taken_at or row.taken_at,
    }
    if item.modified_at is not None:
        values["source_modified_at"] = item.modified_at
    exif = json.loads(row.exif or "{}")
    merged = dict(exif)
    merged.update(item.exif or {})
    values["exif"] = json.dumps(merged)
    if item.width:
        values["width"] = item.width
    if item.height:
        values["height"] = item.height
    if (values.get("width", row.width) or 0) and (values.get("height", row.height) or 0):
        values["aspect_ratio"] = values.get("width", row.width) / values.get("height", row.height)
    for key, value in values.items():
        if getattr(row, key) != value:
            setattr(row, key, value)
            changed = True
    return changed


def _managed_copy_matches(filename: str, expected_checksum: str) -> bool:
    """Verify legacy adoption against bytes, not a possibly stale DB checksum."""
    try:
        path = photos_store.original_path(filename)
        if not path.is_file():
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest() == expected_checksum
    except (OSError, ValueError):
        return False


def _replace_photokit_media(row: Photo, info: dict):
    for key in (
        "filename",
        "thumb",
        "original_name",
        "width",
        "height",
        "taken_at",
        "exif",
        "is_video",
        "aspect_ratio",
        "preview",
        "checksum",
    ):
        if key in info:
            setattr(row, key, info[key])


def _photokit_failure_kind(exc: Exception) -> str:
    if isinstance(exc, SQLAlchemyError):
        return "database"
    if isinstance(exc, ValueError):
        return "unsupported_media"
    name = type(exc).__name__.lower()
    if "export" in name or "timeout" in name:
        return "export"
    return "processing"


def sync_macos_library(db=None, *, adapter=None, limit: int = 0, progress=None) -> dict:
    """Import native PhotoKit resources with stable source identity.

    The operation is one-way: removing something from Apple Photos never deletes
    the local copy. Existing source rows have safe metadata refreshed; media is
    re-exported only when PhotoKit reports a newer source revision.
    """
    if sys.platform != "darwin" and adapter is None:
        raise NotImplementedError("Apple Photos import is available only on macOS")
    if adapter is None:
        from services import photokit as adapter

    adapter.ensure_authorized(timeout=75)
    items = list(adapter.iter_resources())
    own = db is None
    db = db or SessionLocal()
    imported = adopted = skipped = updated = failed = remaining = 0
    failure_reasons = {}
    cap = max(0, int(limit or 0))
    attempted_exports = 0
    by_asset: dict[str, dict[str, str]] = {}
    newly_linked_assets: set[str] = set()
    work_dir = None

    def notify(index):
        if progress:
            progress(
                {
                    "processed": index,
                    "total": len(items),
                    "imported": imported,
                    "adopted": adopted,
                    "skipped": skipped,
                    "updated": updated,
                    "failed": failed,
                    "remaining": remaining,
                    "failure_reasons": dict(failure_reasons),
                }
            )

    try:
        source_rows = db.query(Photo).filter(Photo.source == "apple_photos").all()
        # Keep only primitive snapshots across exports. ORM rows expire on commit,
        # and touching one would reopen a transaction during an iCloud download.
        existing = {
            row.source_id: (row.id, row.source_modified_at) for row in source_rows if row.source_id
        }
        db.commit()
        work_dir = tempfile.TemporaryDirectory(prefix="alles-photokit-")

        for index, item in enumerate(items, 1):
            record = existing.get(item.source_id)
            revision_changed = bool(
                record is not None
                and item.modified_at is not None
                and item.modified_at != record[1]
            )
            needs_export = record is None or revision_changed
            if needs_export and cap and attempted_exports >= cap:
                remaining += 1
                notify(index)
                continue

            info = None
            if needs_export:
                attempted_exports += 1
                suffix = Path(item.original_name).suffix or (
                    ".mov" if item.kind in {"video", "paired_video"} else ".jpg"
                )
                staged = Path(work_dir.name) / f"{uuid.uuid4().hex}{suffix}"
                try:
                    adapter.export_resource(item, staged, timeout=300)
                    info = _apply_photokit_metadata(
                        photos_store.import_media_path(staged, item.original_name), item
                    )
                except Exception as exc:
                    if info:
                        photos_store.delete_files(info.get("filename", ""), info.get("thumb", ""))
                    failed += 1
                    kind = _photokit_failure_kind(exc)
                    failure_reasons[kind] = failure_reasons.get(kind, 0) + 1
                    notify(index)
                    continue
                finally:
                    staged.unlink(missing_ok=True)

            new_files = (info["filename"], info["thumb"]) if info else None
            old_files = None
            discard_new_files = False
            adopted_current = inserted_current = updated_current = skipped_current = False
            try:
                row = db.get(Photo, record[0]) if record else None
                if record is not None and row is None:
                    raise RuntimeError("PhotoKit source row disappeared during import")

                if row is None:
                    candidate_refs = []
                    checksum = info.get("checksum")
                    if checksum:
                        candidates = db.query(Photo).filter(
                            Photo.checksum == checksum,
                            (Photo.source_id == None) | (Photo.source_id == ""),  # noqa: E711
                            Photo.deleted_at == None,  # noqa: E711
                        )
                        if info.get("is_video"):
                            candidates = candidates.filter(Photo.is_video == True)  # noqa: E712
                        else:
                            candidates = candidates.filter(
                                (Photo.is_video == False) | (Photo.is_video == None)  # noqa: E711,E712
                            )
                        rows = candidates.order_by(Photo.created_at.asc(), Photo.id.asc()).all()
                        candidate_refs = [(candidate.id, candidate.filename) for candidate in rows]
                        db.commit()

                    verified_id = next(
                        (
                            candidate_id
                            for candidate_id, filename in candidate_refs
                            if _managed_copy_matches(filename, checksum)
                        ),
                        None,
                    )
                    adopt_id = verified_id or (candidate_refs[0][0] if candidate_refs else None)
                    if adopt_id:
                        row = db.get(Photo, adopt_id)
                        if row is None:
                            raise RuntimeError("legacy photo disappeared during import")
                        if verified_id:
                            discard_new_files = True
                            row.original_name = info["original_name"]
                        else:
                            old_files = (row.filename, row.thumb)
                            _replace_photokit_media(row, info)
                        row.source = "apple_photos"
                        row.source_id = item.source_id
                        row.source_asset_id = item.asset_id
                        row.source_modified_at = item.modified_at
                        _update_photokit_row(row, item)
                        adopted += 1
                        adopted_current = True
                    else:
                        row = Photo(
                            filename=info["filename"],
                            thumb=info["thumb"],
                            original_name=info["original_name"],
                            width=info["width"],
                            height=info["height"],
                            taken_at=info["taken_at"],
                            exif=info["exif"],
                            is_video=info.get("is_video", False),
                            aspect_ratio=info.get("aspect_ratio"),
                            preview=info.get("preview", ""),
                            checksum=info.get("checksum"),
                            favorite=bool(item.favorite),
                            hidden=bool(item.hidden),
                            source="apple_photos",
                            source_id=item.source_id,
                            source_asset_id=item.asset_id,
                            source_modified_at=item.modified_at,
                        )
                        db.add(row)
                        imported += 1
                        inserted_current = True
                elif info is not None:
                    old_files = (row.filename, row.thumb)
                    _replace_photokit_media(row, info)
                    _update_photokit_row(row, item)
                    updated += 1
                    updated_current = True
                elif _update_photokit_row(row, item):
                    updated += 1
                    updated_current = True
                else:
                    skipped += 1
                    skipped_current = True

                db.flush()
                current_id = row.id
                members = by_asset.setdefault(item.asset_id, {})
                still_id = current_id if item.kind == "photo" else members.get("photo")
                motion_id = (
                    current_id if item.kind == "paired_video" else members.get("paired_video")
                )
                should_pair = item.asset_id in newly_linked_assets or (
                    inserted_current or adopted_current
                )
                if still_id and motion_id and should_pair:
                    still = row if current_id == still_id else db.get(Photo, still_id)
                    motion = row if current_id == motion_id else db.get(Photo, motion_id)
                    if still is not None and motion is not None:
                        still.stack_id = still_id
                        motion.stack_id = still_id

                committed_revision = (
                    item.modified_at
                    if item.modified_at is not None
                    else (record[1] if record else None)
                )
                db.commit()
                existing[item.source_id] = (current_id, committed_revision)
                members[item.kind] = current_id
                if inserted_current or adopted_current:
                    newly_linked_assets.add(item.asset_id)

                if discard_new_files:
                    photos_store.delete_files(*new_files)
                elif old_files:
                    photos_store.delete_files(*old_files)
            except Exception as exc:
                db.rollback()
                if new_files:
                    photos_store.delete_files(*new_files)
                failed += 1
                kind = _photokit_failure_kind(exc)
                failure_reasons[kind] = failure_reasons.get(kind, 0) + 1
                # Counts are committed outcomes; undo optimistic increments.
                imported -= int(inserted_current)
                adopted -= int(adopted_current)
                updated -= int(updated_current)
                skipped -= int(skipped_current)
                notify(index)
                continue
            notify(index)
    finally:
        if work_dir:
            work_dir.cleanup()
        close = getattr(adapter, "close_export_session", None)
        if close:
            close()
        if own:
            db.close()
    return {
        "imported": imported,
        "adopted": adopted,
        "skipped": skipped,
        "updated": updated,
        "failed": failed,
        "remaining": remaining,
        "total": len(items),
        "failure_reasons": failure_reasons,
    }


def photokit_status() -> dict:
    from services import photokit

    out = photokit.status()
    with _MAC_JOB_LOCK:
        active = next(
            (
                dict(job)
                for job in reversed(list(_MAC_JOBS.values()))
                if job["state"] in {"queued", "running"}
            ),
            None,
        )
    out["job"] = active
    return out


def _run_macos_job(job_id: str, limit: int):
    from services import photokit

    def update(values):
        with _MAC_JOB_LOCK:
            if job_id in _MAC_JOBS:
                _MAC_JOBS[job_id].update(values)

    update({"state": "running"})
    db = SessionLocal()
    try:
        result = sync_macos_library(db, adapter=photokit, limit=limit, progress=update)
        update({"state": "complete", **result})
    except photokit.PhotoKitPermissionError as exc:
        update({"state": "error", "error": "permission", "message": str(exc)})
    except photokit.PhotoKitUnavailableError as exc:
        update({"state": "error", "error": "unavailable", "message": str(exc)})
    except photokit.PhotoKitTimeoutError as exc:
        update({"state": "error", "error": "timeout", "message": str(exc)})
    except Exception:
        update(
            {
                "state": "error",
                "error": "failed",
                "message": "Apple Photos import failed",
            }
        )
    finally:
        db.close()


def start_macos_sync(limit: int = 500) -> dict:
    from services import photokit

    status = photokit.status()
    if not status["available"]:
        raise photokit.PhotoKitUnavailableError(status["reason"])
    with _MAC_JOB_LOCK:
        active = next(
            (job for job in _MAC_JOBS.values() if job["state"] in {"queued", "running"}), None
        )
        if active:
            return dict(active)
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "state": "queued",
            "processed": 0,
            "total": 0,
            "imported": 0,
            "adopted": 0,
            "skipped": 0,
            "updated": 0,
            "failed": 0,
            "remaining": 0,
            "failure_reasons": {},
        }
        _MAC_JOBS[job_id] = job
        # Bound memory if the server stays up through many manual syncs.
        while len(_MAC_JOBS) > 20:
            _MAC_JOBS.pop(next(iter(_MAC_JOBS)))
    safe_limit = 0 if limit <= 0 else min(limit, 50000)
    threading.Thread(target=_run_macos_job, args=(job_id, safe_limit), daemon=True).start()
    return dict(job)


def get_macos_sync_job(job_id: str) -> dict | None:
    with _MAC_JOB_LOCK:
        job = _MAC_JOBS.get(job_id)
        return dict(job) if job else None


def pull_from_macos_photos(dest_dir: str) -> dict:
    """Compatibility export helper backed by native PhotoKit.

    New Gallery code imports through ``sync_macos_library`` so stable source IDs
    are retained. This helper remains for callers that explicitly need a folder.
    """
    if sys.platform != "darwin":
        raise NotImplementedError("Apple Photos export is available only on macOS")
    from services import photokit

    photokit.ensure_authorized(timeout=60)
    root = Path(dest_dir)
    root.mkdir(parents=True, exist_ok=True)
    exported = failed = 0
    try:
        for item in photokit.iter_resources():
            target = root / f"{uuid.uuid4().hex}-{item.original_name}"
            try:
                photokit.export_resource(item, target)
                exported += 1
            except Exception:
                failed += 1
    finally:
        photokit.close_export_session()
    return {"exported_to": str(root), "exported": exported, "failed": failed}
