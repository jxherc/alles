"""Bounded background indexing for one Files storage location at a time."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from core.database import SessionLocal, StorageLocation
from services import file_operations, storage_backends, textindex

MAX_ITEMS = 10_000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_INDEX_TEXT_BYTES = 64 * 1024 * 1024
TEXT_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".conf",
        ".cpp",
        ".css",
        ".csv",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".log",
        ".md",
        ".mjs",
        ".py",
        ".rb",
        ".rs",
        ".rst",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)

_lock = Lock()
_states: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _base(location_id: str) -> dict:
    return {
        "location_id": location_id,
        "state": "idle",
        "items_seen": 0,
        "files_indexed": 0,
        "chunks": 0,
        "error": "",
        "started_at": "",
        "finished_at": "",
    }


def status(location_id: str) -> dict:
    with _lock:
        return dict(_states.get(location_id, _base(location_id)))


def is_active(location_id: str) -> bool:
    """Return whether this process has queued or running index work."""
    with _lock:
        return _states.get(location_id, {}).get("state") in {"queued", "running"}


def forget(location_id: str) -> None:
    """Drop process-local progress after a location is removed."""
    with _lock:
        _states.pop(location_id, None)


def enqueue(location_id: str) -> tuple[dict, bool]:
    with _lock:
        current = _states.get(location_id, _base(location_id))
        if current["state"] in {"queued", "running"}:
            return dict(current), False
        queued = _base(location_id)
        queued.update({"state": "queued", "started_at": _now()})
        _states[location_id] = queued
        return dict(queued), True


def _update(location_id: str, **values) -> None:
    with _lock:
        current = _states.setdefault(location_id, _base(location_id))
        current.update(values)


def _is_indexable(item: dict) -> bool:
    if item.get("type") != "file":
        return False
    size = item.get("size")
    if size is not None:
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            return False
        if size > MAX_FILE_BYTES:
            return False
    path = str(item.get("normalized_path") or item.get("path") or "")
    return Path(path).suffix.casefold() in TEXT_EXTENSIONS


def _collect(row) -> tuple[list[tuple[str, str]], int]:
    queue = deque([""])
    records: list[tuple[str, str]] = []
    seen = 0
    text_bytes = 0
    while queue:
        folder = queue.popleft()
        listing = storage_backends.listdir(row, folder)
        for item in listing.get("items", []):
            seen += 1
            if seen > MAX_ITEMS:
                raise RuntimeError("storage location has too many items to index")
            path = str(item.get("normalized_path") or item.get("path") or "")
            if item.get("type") == "dir":
                queue.append(path)
                continue
            if not _is_indexable(item):
                continue
            result = storage_backends.read_text(row, path, limit=MAX_FILE_BYTES)
            if result.get("is_text") and str(result.get("content") or "").strip():
                content = str(result["content"])
                text_bytes += len(content.encode("utf-8"))
                if text_bytes > MAX_INDEX_TEXT_BYTES:
                    raise RuntimeError("storage location has too much text to index at once")
                records.append((path, content))
            _update(row.id, items_seen=seen, files_indexed=len(records))
    return records, seen


def run(location_id: str) -> None:
    _update(location_id, state="running", error="")
    db = SessionLocal()
    try:
        row = db.get(StorageLocation, location_id)
        if row is None or not row.enabled:
            raise RuntimeError("storage location is unavailable")
        with file_operations.direct_mutation_claim(db, row, ""):
            records, seen = _collect(row)
            verification_db = SessionLocal()
            try:
                still_available = (
                    verification_db.query(StorageLocation.id)
                    .filter(
                        StorageLocation.id == location_id,
                        StorageLocation.enabled.is_(True),
                    )
                    .first()
                )
            finally:
                verification_db.close()
            if still_available is None:
                raise RuntimeError("storage location is unavailable")
            chunks = textindex.reindex_file_location(db, location_id, records)
        _update(
            location_id,
            state="completed",
            items_seen=seen,
            files_indexed=len(records),
            chunks=chunks,
            finished_at=_now(),
        )
    except Exception as exc:
        db.rollback()
        _update(
            location_id,
            state="error",
            error=str(exc)[:240] or "indexing failed",
            finished_at=_now(),
        )
    finally:
        db.close()
