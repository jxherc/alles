"""generic soft-delete / trash primitive (1d).

a TrashItem row is the registry entry. filesystem files stash their bytes under
<data>/.trash/<uid><ext>; photos keep their files in place and flip Photo.deleted_at.
restore() and purge_expired() dispatch on kind so a single "recently deleted" can
span both. default retention is 30 days.
"""

import json
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from core.database import TrashItem
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
    shutil.move(str(src), str(_trash_dir() / name))
    return name


def unstash_file(trash_name: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(_trash_dir() / trash_name), str(dest))


def record(db, kind, ref, name, payload=None, ttl_days=DEFAULT_TTL_DAYS) -> TrashItem:
    now = datetime.utcnow()
    it = TrashItem(
        kind=kind,
        ref=ref,
        name=name or "",
        payload=json.dumps(payload or {}),
        trashed_at=now,
        expires_at=now + timedelta(days=ttl_days),
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def list_items(db, kind=None) -> list[TrashItem]:
    q = db.query(TrashItem)
    if kind:
        q = q.filter_by(kind=kind)
    return q.order_by(TrashItem.trashed_at.desc()).all()


def get(db, tid) -> TrashItem | None:
    return db.get(TrashItem, tid)


def delete_row(db, item):
    db.delete(item)
    db.commit()


# ── file kind ─────────────────────────────────────────────────────────────────
def soft_delete_file(db, ref, abspath: Path, ttl_days=DEFAULT_TTL_DAYS) -> TrashItem:
    is_dir = abspath.is_dir()
    trash_name = stash_file(abspath)
    return record(
        db, "file", ref, abspath.name, {"trash_name": trash_name, "is_dir": is_dir}, ttl_days
    )


def restore_file(db, item, dest: Path):
    data = json.loads(item.payload or "{}")
    tn = data.get("trash_name")
    if tn and stash_path(tn).exists():
        unstash_file(tn, dest)
    delete_row(db, item)


# ── purge ─────────────────────────────────────────────────────────────────────
def purge_expired(db, now=None) -> int:
    now = now or datetime.utcnow()
    expired = (
        db.query(TrashItem)
        .filter(TrashItem.expires_at.isnot(None), TrashItem.expires_at <= now)
        .all()
    )
    n = 0
    for it in expired:
        if it.kind == "file":
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
