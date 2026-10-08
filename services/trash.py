"""generic soft-delete / trash primitive (1d).

a TrashItem row is the registry entry. filesystem files stash their bytes under
<data>/.trash/<uid><ext>; photos keep their files in place and flip Photo.deleted_at.
restore() and purge_expired() dispatch on kind so a single "recently deleted" can
span both. default retention is 30 days.
"""

import json
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.database import (
    DEFAULT_LOCAL_STORAGE_LOCATION_ID,
    StorageLocation,
    TrashItem,
    normalize_file_identity_path,
)
from core.settings import data_dir

DEFAULT_TTL_DAYS = 30


def _trash_dir() -> Path:
    d = data_dir() / ".trash"
    d.mkdir(parents=True, exist_ok=True)
    return d


def stash_path(trash_name: str) -> Path:
    return _trash_dir() / trash_name


def stash_file(src: Path) -> str:
    """move a file or dir into the trash dir under a uid; return its trash name."""
    name = uuid.uuid4().hex + (src.suffix if src.is_file() else "")
    _stash_file_as(src, name)
    return name


def _stash_file_as(src: Path, trash_name: str) -> None:
    shutil.move(str(src), str(_trash_dir() / trash_name))


def unstash_file(trash_name: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(_trash_dir() / trash_name), str(dest))


def record(
    db,
    kind,
    ref,
    name,
    payload=None,
    ttl_days=DEFAULT_TTL_DAYS,
    *,
    location_id=None,
    commit=True,
) -> TrashItem:
    now = datetime.now(UTC).replace(tzinfo=None)
    it = TrashItem(
        kind=kind,
        ref=ref,
        name=name or "",
        payload=json.dumps(payload or {}),
        trashed_at=now,
        expires_at=now + timedelta(days=ttl_days),
    )
    if kind == "file":
        it.location_id = location_id or DEFAULT_LOCAL_STORAGE_LOCATION_ID
        it.normalized_path = normalize_file_identity_path(ref)
    db.add(it)
    if commit:
        db.commit()
        db.refresh(it)
    else:
        db.flush()
    return it


def list_items(db, kind=None) -> list[TrashItem]:
    q = db.query(TrashItem)
    if kind:
        q = q.filter_by(kind=kind)
    return q.order_by(TrashItem.trashed_at.desc()).all()


def get(db, tid) -> TrashItem | None:
    return db.get(TrashItem, tid)


def delete_row(db, item):
    if item.kind == "file":
        from services import file_operations

        file_operations.discard_trash_metadata(db, item)
    db.delete(item)
    db.commit()


# ── file kind ─────────────────────────────────────────────────────────────────
def soft_delete_path(
    db, kind: str, ref: str, abspath: Path, ttl_days=DEFAULT_TTL_DAYS
) -> TrashItem:
    is_dir = abspath.is_dir()
    trash_name = uuid.uuid4().hex + (abspath.suffix if abspath.is_file() else "")
    item = record(
        db,
        kind,
        ref,
        abspath.name,
        {"trash_name": trash_name, "is_dir": is_dir, "state": "pending"},
        ttl_days,
    )
    try:
        _stash_file_as(abspath, trash_name)
    except Exception:
        try:
            delete_row(db, item)
        except Exception:
            # A leftover row still points at an unchanged source. It can be reconciled safely;
            # never move the only bytes first and hope the registry commit works afterward.
            pass
        raise
    item.payload = json.dumps({"trash_name": trash_name, "is_dir": is_dir, "state": "ready"})
    db.commit()
    db.refresh(item)
    return item


def soft_delete_file(
    db,
    ref,
    abspath: Path,
    ttl_days=DEFAULT_TTL_DAYS,
    *,
    location_id=DEFAULT_LOCAL_STORAGE_LOCATION_ID,
) -> TrashItem:
    is_dir = abspath.is_dir()
    trash_name = uuid.uuid4().hex + (abspath.suffix if abspath.is_file() else "")
    item = record(
        db,
        "file",
        ref,
        abspath.name,
        {"trash_name": trash_name, "is_dir": is_dir, "state": "pending"},
        ttl_days,
        location_id=location_id,
    )
    try:
        _stash_file_as(abspath, trash_name)
    except Exception:
        try:
            delete_row(db, item)
        except Exception:
            pass
        raise
    item.payload = json.dumps({"trash_name": trash_name, "is_dir": is_dir, "state": "ready"})
    db.commit()
    db.refresh(item)
    return item


def recover_interrupted_files(db) -> int:
    """Reconcile a path trash row committed before its local move finished."""
    from services import files_store, storage_locations, vault_md

    recovered = 0
    rows = db.query(TrashItem).filter(TrashItem.kind.in_({"file", "vault"})).all()
    for item in rows:
        try:
            payload = json.loads(item.payload or "{}")
        except (TypeError, ValueError):
            continue
        if payload.get("state") != "pending":
            continue
        trash_name = str(payload.get("trash_name") or "")
        if not trash_name:
            continue
        try:
            if item.kind == "vault":
                source = vault_md._safe(item.ref)
            else:
                location_id = item.location_id or DEFAULT_LOCAL_STORAGE_LOCATION_ID
                if location_id == DEFAULT_LOCAL_STORAGE_LOCATION_ID:
                    location = storage_locations.ensure_default_local(db)
                else:
                    location = db.get(StorageLocation, location_id)
                if location is not None and location.kind == "local":
                    root = storage_locations.local_root(location)
                else:
                    continue
                source = files_store.abspath(
                    item.normalized_path or item.ref,
                    root=root,
                )
        except ValueError:
            continue
        stash = stash_path(trash_name)
        if source.exists() or source.is_symlink():
            if stash.exists() or stash.is_symlink():
                payload["state"] = "conflicted"
                payload["error"] = "source_reappeared_after_trash_move"
                item.payload = json.dumps(payload)
            else:
                db.delete(item)
        elif stash.exists() or stash.is_symlink():
            payload["state"] = "ready"
            item.payload = json.dumps(payload)
        else:
            db.delete(item)
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def restore_path(db, item, dest: Path):
    if dest.exists():
        raise FileExistsError(str(dest))
    data = json.loads(item.payload or "{}")
    tn = data.get("trash_name")
    if not tn or not stash_path(tn).exists():
        raise FileNotFoundError("the trashed copy is missing")
    unstash_file(tn, dest)
    delete_row(db, item)


def restore_file(db, item, dest: Path):
    restore_path(db, item, dest)


# ── purge ─────────────────────────────────────────────────────────────────────
def purge_expired(db, now=None, *, kind=None, location_id=None) -> int:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    query = db.query(TrashItem).filter(
        TrashItem.expires_at.isnot(None), TrashItem.expires_at <= now
    )
    if kind:
        query = query.filter(TrashItem.kind == kind)
    if location_id:
        if location_id == DEFAULT_LOCAL_STORAGE_LOCATION_ID:
            query = query.filter(
                (TrashItem.location_id == location_id) | TrashItem.location_id.is_(None)
            )
        else:
            query = query.filter(TrashItem.location_id == location_id)
    expired = query.all()
    n = 0
    for it in expired:
        if it.kind in {"file", "vault"}:
            data = json.loads(it.payload or "{}")
            tn = data.get("trash_name")
            if tn:
                p = stash_path(tn)
                try:
                    if p.is_dir():
                        shutil.rmtree(p)
                    elif p.exists():
                        p.unlink()
                except Exception:
                    pass
            if it.kind == "file":
                from services import file_operations

                file_operations.discard_trash_metadata(db, it)
        elif it.kind == "photo":
            _hard_delete_photo(db, it.ref)
        db.delete(it)
        n += 1
    db.commit()
    return n


def _hard_delete_photo(db, pid):
    from core.database import Photo
    from services import photos_store as ps

    p = db.get(Photo, pid)
    if not p:
        return
    try:
        ps.delete_files(p.filename, p.thumb)
    except Exception:
        pass
    db.delete(p)
