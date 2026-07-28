"""generic file version history (1e).

snapshots the *previous* content of a file before it's overwritten, so any prior
version can be restored. blobs live under <data>/.versions, deduped by sha256; large
files are skipped and history is capped per path. (DocRevision still owns vault docs;
this is the same idea for arbitrary files.)
"""

import hashlib
import shutil
import uuid
from pathlib import Path

from sqlalchemy import and_, or_

from core.database import (
    DEFAULT_LOCAL_STORAGE_LOCATION_ID,
    FileVersion,
    normalize_file_identity_path,
)
from core.settings import data_dir

CAP_BYTES = 25 * 1024 * 1024  # don't version files larger than this (storage runaway)
KEEP = 20  # versions retained per path


def versions_dir() -> Path:
    d = data_dir() / ".versions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _identity_filter(rel: str, location_id: str):
    normalized = normalize_file_identity_path(rel)
    return and_(
        FileVersion.location_id == location_id,
        or_(
            FileVersion.normalized_path == normalized,
            and_(
                or_(
                    FileVersion.normalized_path.is_(None),
                    FileVersion.normalized_path == "",
                ),
                FileVersion.path == rel,
            ),
        ),
    )


def snapshot(
    db,
    rel,
    abspath: Path,
    location_id: str = DEFAULT_LOCAL_STORAGE_LOCATION_ID,
) -> FileVersion | None:
    """save the current bytes of `abspath` as a version of `rel`. returns None when
    skipped (missing / too big / unchanged since the latest version)."""
    if not abspath.is_file():
        return None
    size = abspath.stat().st_size
    if size > CAP_BYTES:
        return None
    data = abspath.read_bytes()
    sha = _sha(data)
    normalized = normalize_file_identity_path(rel)
    latest = (
        db.query(FileVersion)
        .filter(_identity_filter(rel, location_id))
        .order_by(FileVersion.created_at.desc())
        .first()
    )
    if latest and latest.sha == sha:
        return None  # dedup — no change
    stored = uuid.uuid4().hex
    (versions_dir() / stored).write_bytes(data)
    v = FileVersion(
        path=normalized,
        location_id=location_id,
        normalized_path=normalized,
        sha=sha,
        size=size,
        stored=stored,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    _prune(db, normalized, location_id)
    return v


def _prune(db, rel, location_id=DEFAULT_LOCAL_STORAGE_LOCATION_ID):
    rows = (
        db.query(FileVersion)
        .filter(_identity_filter(rel, location_id))
        .order_by(FileVersion.created_at.desc())
        .all()
    )
    for old in rows[KEEP:]:
        try:
            p = versions_dir() / old.stored
            if p.exists():
                p.unlink()
        except Exception:
            pass
        db.delete(old)
    if len(rows) > KEEP:
        db.commit()


def list_versions(db, rel, location_id=DEFAULT_LOCAL_STORAGE_LOCATION_ID) -> list[FileVersion]:
    return (
        db.query(FileVersion)
        .filter(_identity_filter(rel, location_id))
        .order_by(FileVersion.created_at.desc())
        .all()
    )


def delete_for_path(db, rel, location_id=DEFAULT_LOCAL_STORAGE_LOCATION_ID) -> int:
    normalized = normalize_file_identity_path(rel)
    pre = normalized.rstrip("/") + "/"
    rows = (
        db.query(FileVersion)
        .filter(
            FileVersion.location_id == location_id,
            or_(
                FileVersion.normalized_path == normalized,
                FileVersion.normalized_path.startswith(pre),
                and_(
                    or_(
                        FileVersion.normalized_path.is_(None),
                        FileVersion.normalized_path == "",
                    ),
                    or_(FileVersion.path == rel, FileVersion.path.startswith(pre)),
                ),
            ),
        )
        .all()
    )
    stored = {r.stored for r in rows if r.stored}
    for r in rows:
        db.delete(r)
    db.commit()
    for name in stored:
        if db.query(FileVersion).filter_by(stored=name).first():
            continue
        try:
            (versions_dir() / name).unlink(missing_ok=True)
        except OSError:
            pass
    return len(rows)


def get(db, vid) -> FileVersion | None:
    return db.get(FileVersion, vid)


def restore(db, vid, dest: Path) -> FileVersion | None:
    v = db.get(FileVersion, vid)
    if not v:
        return None
    src = versions_dir() / v.stored
    if not src.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(src), str(dest))
    return v
