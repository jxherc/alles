"""0d - content-addressed blob store. see docs/evidence/0d-blobstore/findings.md.

one Blob row per unique content (sha256); files live at <data>/.blobs/<sha[:2]>/<sha>. the
same bytes stored twice = one Blob (dedup). Attachments point resources at blobs and bump the
refcount; gc() purges blobs nothing references. encryption-at-rest per blob is a future
extension (4c, needs the vault password path) - not built here.

NOTE: a freshly put() blob has refcount 0 until attach() - callers attach immediately. gc only
reclaims blobs with no live Attachment.
"""

import hashlib
import json
from pathlib import Path

from core.database import Attachment, Blob
from core.settings import data_dir


def _blob_dir() -> Path:
    return data_dir() / ".blobs"


def path_for(blob) -> Path:
    sha = blob.sha256 if hasattr(blob, "sha256") else str(blob)
    return _blob_dir() / sha[:2] / sha


def put(db, data: bytes, *, mime="") -> Blob:
    """store bytes content-addressed; dedups by sha256. returns the (existing or new) Blob."""
    sha = hashlib.sha256(data).hexdigest()
    existing = db.query(Blob).filter(Blob.sha256 == sha).first()
    if existing:
        return existing
    p = path_for(Blob(sha256=sha))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    b = Blob(sha256=sha, size=len(data), mime=mime, refcount=0)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def read(blob) -> bytes:
    return path_for(blob).read_bytes()


def attach(db, blob, kind, rid, meta=None) -> Attachment:
    a = Attachment(
        resource_kind=kind, resource_id=str(rid), blob_id=blob.id, meta=json.dumps(meta or {})
    )
    db.add(a)
    blob.refcount = (blob.refcount or 0) + 1
    db.commit()
    db.refresh(a)
    return a


def detach(db, attachment):
    blob = db.get(Blob, attachment.blob_id)
    db.delete(attachment)
    if blob:
        blob.refcount = max(0, (blob.refcount or 0) - 1)
    db.commit()


def gc(db) -> int:
    """purge blobs nothing references (refcount <= 0): file + row. returns how many."""
    orphans = db.query(Blob).filter(Blob.refcount <= 0).all()
    n = 0
    for b in orphans:
        try:
            path_for(b).unlink(missing_ok=True)
        except OSError:
            pass
        db.delete(b)
        n += 1
    db.commit()
    return n
