"""Validated, read-only release credit inventory for Settings and release gates."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "credits" / "manifest.json"
NOTICE_SET_PATH = ROOT / "credits" / "release-notice-files.json"
LICENSE_INDEX_PATH = ROOT / "licenses" / "index.json"
REQUIRED_ENTRY_FIELDS = {
    "id",
    "name",
    "category",
    "summary",
    "version",
    "license",
    "source_url",
    "bundled",
    "notice_required",
    "license_files",
}
ALLOWED_CATEGORIES = {"code", "data", "companion", "inspiration"}


def _safe_repo_file(value: str) -> Path:
    relative = Path(str(value or ""))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("credit text paths must stay inside the repository")
    resolved = (ROOT / relative).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError("credit text paths must stay inside the repository")
    return resolved


def _read_text_files(
    entry: dict, field: str, *, include_text: bool
) -> tuple[list[dict], list[str]]:
    texts: list[dict] = []
    missing: list[str] = []
    values = entry.get(field, [])
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ValueError(f"credit entry {entry['id']} has invalid {field}")
    for value in values:
        path = _safe_repo_file(value)
        if not path.is_file():
            missing.append(value)
            continue
        record = {"path": value, "name": path.name}
        if include_text:
            record["text"] = path.read_text("utf-8")
        texts.append(record)
    return texts, missing


def _load_payload(path: Path) -> dict:
    payload = json.loads(path.read_text("utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("entries"), list):
        raise ValueError("unsupported credits manifest schema")
    return payload


def _validate_entry(raw: dict, seen: set[str], *, include_text: bool) -> tuple[dict, list[dict]]:
    if not isinstance(raw, dict) or REQUIRED_ENTRY_FIELDS - set(raw):
        raise ValueError("credit entries must contain every required field")
    entry_id = str(raw["id"]).strip()
    if not entry_id or entry_id in seen:
        raise ValueError("credit entry IDs must be unique and non-empty")
    seen.add(entry_id)
    if raw["category"] not in ALLOWED_CATEGORIES:
        raise ValueError(f"credit entry {entry_id} has an invalid category")
    source = urlsplit(str(raw["source_url"]))
    if source.scheme != "https" or not source.hostname:
        raise ValueError(f"credit entry {entry_id} needs an HTTPS source URL")
    if not isinstance(raw["bundled"], bool) or not isinstance(raw["notice_required"], bool):
        raise ValueError(f"credit entry {entry_id} has invalid boolean fields")

    license_texts, missing_license_files = _read_text_files(
        raw, "license_files", include_text=include_text
    )
    notice_texts, missing_notice_files = _read_text_files(
        raw, "notice_files", include_text=include_text
    )
    entry = {
        key: raw[key]
        for key in (
            "id",
            "name",
            "category",
            "summary",
            "version",
            "license",
            "source_url",
            "bundled",
            "notice_required",
        )
    }
    entry["local_file_count"] = len(license_texts) + len(notice_texts)
    if include_text:
        entry["license_texts"] = license_texts
        entry["notice_texts"] = notice_texts

    gaps: list[dict] = []
    if str(raw["version"]).strip().lower() == "unrecorded":
        gaps.append({"entry_id": entry_id, "code": "missing_exact_version"})
    if str(raw["license"]).strip().lower() == "not recorded":
        gaps.append({"entry_id": entry_id, "code": "missing_license"})
    if raw["notice_required"] and not license_texts:
        gaps.append({"entry_id": entry_id, "code": "missing_local_license_text"})
    for value in missing_license_files:
        gaps.append({"entry_id": entry_id, "code": "missing_license_file", "path": value})
    for value in missing_notice_files:
        gaps.append({"entry_id": entry_id, "code": "missing_notice_file", "path": value})
    return entry, gaps


def load_credits_manifest(path: Path | None = None, *, include_text: bool = False) -> dict:
    manifest_path = Path(path or MANIFEST_PATH)
    payload = _load_payload(manifest_path)

    seen: set[str] = set()
    entries: list[dict] = []
    gaps: list[dict] = []
    for raw in payload["entries"]:
        entry, entry_gaps = _validate_entry(raw, seen, include_text=include_text)
        entries.append(entry)
        gaps.extend(entry_gaps)

    return {
        "schema_version": 1,
        "state": str(payload.get("state") or "inventory_in_progress"),
        "entries": entries,
        "coverage": {
            "complete": not gaps,
            "entry_count": len(entries),
            "gap_count": len(gaps),
            "gaps": gaps,
        },
    }


def load_credit_detail(entry_id: str, path: Path | None = None) -> dict:
    """Return one fully validated credit with its local text, never the whole bundle."""
    manifest_path = Path(path or MANIFEST_PATH)
    payload = _load_payload(manifest_path)
    requested = str(entry_id or "").strip()
    selected: dict | None = None
    seen: set[str] = set()
    for raw in payload["entries"]:
        include_text = isinstance(raw, dict) and str(raw.get("id", "")).strip() == requested
        entry, _ = _validate_entry(raw, seen, include_text=include_text)
        if include_text:
            selected = entry
    if selected is None:
        raise KeyError(requested)
    return selected


def verify_release_notice_set(root: Path | None = None) -> dict:
    """Verify the exact generated notice/license set inside a release root."""
    release_root = Path(root or ROOT).resolve()

    def safe_path(relative: str) -> Path:
        value = Path(str(relative or ""))
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("release notice paths must stay inside the release")
        resolved = (release_root / value).resolve()
        if resolved != release_root and release_root not in resolved.parents:
            raise ValueError("release notice paths must stay inside the release")
        return resolved

    notice_set_path = release_root / NOTICE_SET_PATH.relative_to(ROOT)
    license_index_path = release_root / LICENSE_INDEX_PATH.relative_to(ROOT)
    manifest_path = release_root / MANIFEST_PATH.relative_to(ROOT)
    notice_set = json.loads(notice_set_path.read_text("utf-8"))
    license_index = json.loads(license_index_path.read_text("utf-8"))
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if any(item.get("schema_version") != 1 for item in (notice_set, license_index, manifest)):
        raise ValueError("unsupported release notice schema")
    revisions = {
        str(item.get("source_revision") or "") for item in (notice_set, license_index, manifest)
    }
    if len(revisions) != 1 or not next(iter(revisions)):
        raise ValueError("release notice revisions do not match")

    expected = notice_set.get("files")
    if not isinstance(expected, list) or not expected or len(expected) != len(set(expected)):
        raise ValueError("release notice set must contain unique files")
    expected_set = set(expected)
    required_docs = {
        "ACKNOWLEDGMENTS.md",
        "THIRD_PARTY_NOTICES.md",
        "credits/manifest.json",
        "licenses/index.json",
    }
    indexed = license_index.get("files")
    if not isinstance(indexed, list):
        raise ValueError("release license index is invalid")
    indexed_paths = {str(item.get("path") or "") for item in indexed}
    manifest_paths = {
        str(relative)
        for entry in manifest.get("entries", [])
        for relative in [*entry.get("license_files", []), *entry.get("notice_files", [])]
        if str(relative).startswith("licenses/")
    }
    if expected_set != required_docs | indexed_paths or indexed_paths != manifest_paths:
        raise ValueError("release notice set does not exactly match the generated inventory")

    for relative in expected:
        if not safe_path(relative).is_file():
            raise ValueError(f"release notice file is missing: {relative}")
    actual_license_paths = {
        path.relative_to(release_root).as_posix()
        for path in (release_root / "licenses").rglob("*")
        if path.is_file() and path.name != "index.json"
    }
    if actual_license_paths != indexed_paths:
        raise ValueError("release license directory does not exactly match its index")
    for item in indexed:
        path = safe_path(str(item["path"]))
        if path.stat().st_size != item.get("bytes"):
            raise ValueError(f"release license size changed: {item['path']}")
        import hashlib

        if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            raise ValueError(f"release license hash changed: {item['path']}")
    return {"source_revision": revisions.pop(), "file_count": len(expected)}
