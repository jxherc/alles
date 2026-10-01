"""Lossless draft, revision, conflict, and rename recovery for Markdown documents.

All recovery state lives under the private Alles data directory, outside the visible vault.
The owner vault remains plain Markdown and every vault replacement is atomic.
"""

import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.settings import data_dir
from services import vault_md

_LINK = re.compile(r"\[\[([^\[\]|#]+)((?:[#|][^\[\]]*)?)\]\]")
_TRANSACTION_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_REVISIONS = 50
_DRAFT_LOCK = threading.RLock()


class DocumentSaveConflict(vault_md.DocumentConflictError):
    """A safe save preserved the local candidate instead of overwriting the vault."""

    def __init__(self, conflict: dict):
        super().__init__("document changed since it was opened")
        self.conflict = conflict


class RecoveryConflict(vault_md.DocumentConflictError):
    """Recovery stopped because bytes no longer match either verified transaction state."""


class RenameRecoveryRequired(RecoveryConflict):
    """A rename is safely paused and has a durable transaction to recover."""

    def __init__(self, transaction_id: str, message: str):
        super().__init__(message)
        self.transaction_id = transaction_id


def _state_root() -> Path:
    return data_dir() / ".document-safety"


def _state_dir(name: str) -> Path:
    root = _state_root().expanduser().resolve()
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path_key(rel: str) -> str:
    return hashlib.sha256(rel.encode("utf-8")).hexdigest()


def _normalise_rel(rel: str, *, add_markdown_suffix: bool = True) -> tuple[str, Path]:
    path = vault_md._safe(rel)
    if add_markdown_suffix and path.suffix == "":
        path = path.with_suffix(".md")
    root = vault_md.root_dir()
    try:
        normalised = str(path.relative_to(root)).replace("\\", "/")
    except ValueError as exc:
        raise ValueError("path escapes vault") from exc
    return normalised, path


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_exclusive(backup: Path, path: Path) -> None:
    """Restore a quarantined file without replacing a newly-created owner file."""
    _require_exclusive_publication(backup.parent, path.parent)
    _publish_exclusive(backup, path)
    _fsync_directory(path.parent)


def _publish_exclusive(source: Path, destination: Path) -> None:
    """Move one file into a vacant name with the platform's no-replace primitive."""
    from services import file_operations

    try:
        file_operations._rename_no_replace(source, destination)
    except file_operations.FileOperationError as exc:
        raise RecoveryConflict(
            f"document changed during recovery; preserved prior bytes at {source.name}"
        ) from exc


def _require_exclusive_publication(source_parent: Path, destination_parent: Path) -> None:
    """Prove the target filesystem supports create-only publication before hiding live bytes."""
    source_fd, source_name = tempfile.mkstemp(prefix=".alles-publish-probe.", dir=source_parent)
    os.close(source_fd)
    source = Path(source_name)
    destination = destination_parent / f".alles-publish-probe.{uuid.uuid4().hex}"
    try:
        _publish_exclusive(source, destination)
    finally:
        source.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)


def _conditional_replace(path: Path, data: bytes, expected_hash: str) -> None:
    """Publish bytes only if the target still has the reviewed identity.

    Moving the old path aside first means a concurrent replacement is preserved
    rather than overwritten. Publication uses the platform's atomic no-replace
    primitive and fails when another writer wins the vacant-name race.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    transaction_id = uuid.uuid4().hex
    backup = path.with_name(f".{path.name}.alles-{transaction_id}.backup")
    temporary = path.with_name(f".{path.name}.alles-{transaction_id}.conditional")
    transaction_dir = None
    transaction_resolved = False
    moved = False
    try:
        if expected_hash:
            _require_exclusive_publication(path.parent, path.parent)
        vault_root = vault_md.root_dir().resolve()
        rel = str(path.resolve(strict=False).relative_to(vault_root)).replace("\\", "/")
        backup_rel = str(backup.resolve(strict=False).relative_to(vault_root)).replace("\\", "/")
        temporary_rel = str(temporary.resolve(strict=False).relative_to(vault_root)).replace(
            "\\", "/"
        )
        transaction_dir = _publish_write_transaction(
            transaction_id,
            data,
            {
                "id": transaction_id,
                "path": rel,
                "backup_path": backup_rel,
                "staging_path": temporary_rel,
                "expected_hash": expected_hash,
                "replacement_hash": _hash(data),
                "created_at": _now(),
            },
        )
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_hash:
            try:
                os.rename(path, backup)
            except FileNotFoundError as exc:
                transaction_resolved = True
                raise RecoveryConflict("document disappeared before the write") from exc
            moved = True
            _fsync_directory(path.parent)
            if _hash(backup.read_bytes()) != expected_hash:
                _restore_exclusive(backup, path)
                moved = False
                transaction_resolved = True
                raise RecoveryConflict("document changed immediately before the write")
        try:
            _publish_exclusive(temporary, path)
        except RecoveryConflict as exc:
            if moved and not path.exists():
                _restore_exclusive(backup, path)
                moved = False
                transaction_resolved = True
            raise RecoveryConflict("document appeared immediately before the write") from exc
        _fsync_directory(path.parent)
        if moved:
            backup.unlink()
            moved = False
        _fsync_directory(path.parent)
        transaction_resolved = True
    except Exception:
        if moved and backup.exists() and not path.exists():
            _restore_exclusive(backup, path)
            moved = False
            transaction_resolved = True
        elif not moved:
            transaction_resolved = True
        raise
    finally:
        temporary.unlink(missing_ok=True)
        if transaction_dir is not None and transaction_resolved:
            _remove_tree(transaction_dir)


def _publish_write_transaction(transaction_id: str, replacement: bytes, manifest: dict) -> Path:
    """Build a complete write journal privately, then expose it with one directory rename."""
    root = _state_dir("write-transactions")
    destination = root / transaction_id
    staging = Path(tempfile.mkdtemp(prefix=f".{transaction_id}.", suffix=".preparing", dir=root))
    try:
        _atomic_write(staging / "replacement.blob", replacement)
        _write_json(staging / "manifest.json", manifest)
        _fsync_directory(staging)
        os.rename(staging, destination)
        _fsync_directory(root)
        return destination
    except BaseException:
        _remove_tree(staging)
        raise


def _move_exclusive(
    source: Path,
    destination: Path,
    expected_hash: str,
    *,
    quarantine: Path | None = None,
    allow_source_alias: bool = False,
) -> None:
    """Move a verified file without replacing a concurrently-created destination."""
    source.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    quarantine = quarantine or source.with_name(f".{source.name}.alles-{uuid.uuid4().hex}.moving")
    _require_exclusive_publication(source.parent, destination.parent)
    try:
        os.rename(source, quarantine)
    except FileNotFoundError as exc:
        raise RecoveryConflict("rename source disappeared") from exc
    try:
        if _hash(quarantine.read_bytes()) != expected_hash:
            _restore_exclusive(quarantine, source)
            raise RecoveryConflict("rename source changed immediately before the move")
        try:
            _publish_exclusive(quarantine, destination)
        except RecoveryConflict as exc:
            _restore_exclusive(quarantine, source)
            raise RecoveryConflict("rename destination appeared during the move") from exc
        _fsync_directory(source.parent)
        _fsync_directory(destination.parent)
        source_is_destination = (
            allow_source_alias
            and source.exists()
            and destination.exists()
            and os.path.samefile(source, destination)
        )
        if source.exists() and not source_is_destination:
            raise RecoveryConflict("rename source reappeared during the move")
    except Exception:
        if quarantine.exists() and not source.exists():
            _restore_exclusive(quarantine, source)
        raise


def recover_interrupted_writes() -> int:
    """Restore or finish every journaled conditional document replacement."""
    recovered = 0
    root = _state_dir("write-transactions")
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not _TRANSACTION_ID.fullmatch(directory.name):
            continue
        manifest = _read_json(directory / "manifest.json")
        _, path = _normalise_rel(str(manifest.get("path") or ""))
        _, backup = _normalise_rel(
            str(manifest.get("backup_path") or ""), add_markdown_suffix=False
        )
        staging = None
        if manifest.get("staging_path"):
            _, staging = _normalise_rel(
                str(manifest.get("staging_path")), add_markdown_suffix=False
            )
        expected_hash = str(manifest.get("expected_hash") or "")
        replacement_hash = str(manifest.get("replacement_hash") or "")
        if not replacement_hash:
            raise RecoveryConflict("write recovery metadata is invalid")
        if staging is not None:
            staging.unlink(missing_ok=True)
        path_hash = _hash(path.read_bytes()) if path.is_file() else ""
        backup_hash = _hash(backup.read_bytes()) if backup.is_file() else ""
        if not expected_hash:
            if backup_hash:
                raise RecoveryConflict("create recovery unexpectedly has a backup")
            if path_hash and path_hash != replacement_hash:
                raise RecoveryConflict("document appeared during interrupted create recovery")
        else:
            if backup_hash and backup_hash != expected_hash:
                raise RecoveryConflict("write recovery backup changed")
            if path_hash == replacement_hash:
                backup.unlink(missing_ok=True)
            elif path_hash == expected_hash and not backup_hash:
                pass
            elif not path_hash and backup_hash == expected_hash:
                _restore_exclusive(backup, path)
            else:
                raise RecoveryConflict("document changed during interrupted write recovery")
        _remove_tree(directory)
        recovered += 1
    return recovered


def _write_json(path: Path, value: dict) -> None:
    _atomic_write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryConflict("recovery metadata is missing or invalid") from exc
    if not isinstance(value, dict):
        raise RecoveryConflict("recovery metadata is invalid")
    return value


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


# Drafts ---------------------------------------------------------------------


def save_draft(
    path: str,
    content: str,
    base_hash: str,
    write_session: str = "",
    write_revision: int = 0,
    write_generation: int = 0,
) -> dict:
    rel, _ = _normalise_rel(path)
    draft_dir = _state_dir("drafts") / _path_key(rel)
    raw = (content or "").encode("utf-8")
    revision = max(0, int(write_revision or 0))
    generation = max(0, int(write_generation or 0))
    session = str(write_session or "")
    bundle_path = draft_dir / "draft.json"
    with _DRAFT_LOCK:
        if session and bundle_path.is_file():
            current = _read_json(bundle_path)
            current_session = str(current.get("write_session") or "")
            current_generation = max(0, int(current.get("write_generation") or 0))
            if current_session == session and int(current.get("write_revision") or 0) > revision:
                return {key: value for key, value in current.items() if key != "content"}
            if (
                current_session
                and current_session != session
                and (
                    generation,
                    session,
                )
                < (current_generation, current_session)
            ):
                return {key: value for key, value in current.items() if key != "content"}
        metadata = {
            "path": rel,
            "base_hash": str(base_hash or ""),
            "draft_hash": _hash(raw),
            "updated_at": _now(),
            "write_session": session,
            "write_revision": revision,
            "write_generation": generation,
        }
        _write_json(bundle_path, {**metadata, "content": content or ""})
        (draft_dir / "content.md").unlink(missing_ok=True)
        (draft_dir / "meta.json").unlink(missing_ok=True)
        return metadata


def load_draft(path: str) -> dict | None:
    rel, _ = _normalise_rel(path)
    draft_dir = _state_dir("drafts") / _path_key(rel)
    bundle_path = draft_dir / "draft.json"
    if bundle_path.is_file():
        bundle = _read_json(bundle_path)
        content = bundle.pop("content", None)
        if not isinstance(content, str):
            raise RecoveryConflict("draft content is missing or invalid")
        raw = content.encode("utf-8")
        if bundle.get("path") != rel:
            raise RecoveryConflict("draft path does not match its recovery metadata")
        if _hash(raw) != bundle.get("draft_hash"):
            raise RecoveryConflict("draft content does not match its recovery metadata")
        return {**bundle, "content": content}

    # Read the pre-bundle layout so existing drafts migrate on their next save.
    metadata_path = draft_dir / "meta.json"
    content_path = draft_dir / "content.md"
    if not metadata_path.is_file() or not content_path.is_file():
        return None
    metadata = _read_json(metadata_path)
    if metadata.get("path") != rel:
        raise RecoveryConflict("draft path does not match its recovery metadata")
    raw = content_path.read_bytes()
    if _hash(raw) != metadata.get("draft_hash"):
        raise RecoveryConflict("draft content does not match its recovery metadata")
    return {**metadata, "content": vault_md._decode_for_edit(raw)}


def delete_draft(path: str) -> bool:
    with _DRAFT_LOCK:
        rel, _ = _normalise_rel(path)
        draft_dir = _state_dir("drafts") / _path_key(rel)
        existed = draft_dir.exists()
        _remove_tree(draft_dir)
        return existed


def delete_draft_if_hash(path: str, expected_hash: str) -> bool:
    """Delete only the recovery copy represented by a completed document write."""
    with _DRAFT_LOCK:
        draft = load_draft(path)
        if draft is None or draft.get("draft_hash") != expected_hash:
            return False
        rel, _ = _normalise_rel(path)
        _remove_tree(_state_dir("drafts") / _path_key(rel))
        return True


def list_drafts() -> list[dict]:
    drafts = []
    for directory in _state_dir("drafts").iterdir():
        if not directory.is_dir():
            continue
        try:
            bundle_path = directory / "draft.json"
            if bundle_path.is_file():
                bundle = _read_json(bundle_path)
                bundle.pop("content", None)
                drafts.append(bundle)
            else:
                metadata = _read_json(directory / "meta.json")
                if (directory / "content.md").is_file():
                    drafts.append(metadata)
        except RecoveryConflict:
            continue
    return sorted(drafts, key=lambda item: item.get("updated_at", ""), reverse=True)


# Revisions and conflicts ----------------------------------------------------


def _revision_root(rel: str) -> Path:
    return _state_dir("revisions") / _path_key(rel)


def _snapshot_revision(
    rel: str, raw: bytes, reason: str, *, document_exists: bool = True
) -> dict | None:
    if not document_exists:
        return None
    revision_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex[:12]
    revision_dir = _revision_root(rel) / revision_id
    metadata = {
        "id": revision_id,
        "path": rel,
        "hash": _hash(raw),
        "size": len(raw),
        "reason": reason,
        "created_at": _now(),
    }
    _atomic_write(revision_dir / "content.blob", raw)
    _write_json(revision_dir / "meta.json", metadata)
    _prune_revisions(rel)
    return metadata


def _prune_revisions(rel: str) -> None:
    root = _revision_root(rel)
    directories = sorted((path for path in root.iterdir() if path.is_dir()), reverse=True)
    for old in directories[MAX_REVISIONS:]:
        _remove_tree(old)


def list_revisions(path: str) -> list[dict]:
    rel, _ = _normalise_rel(path)
    root = _revision_root(rel)
    revisions = []
    if not root.exists():
        return revisions
    for directory in sorted(root.iterdir(), reverse=True):
        if not directory.is_dir():
            continue
        try:
            metadata = _read_json(directory / "meta.json")
            raw = (directory / "content.blob").read_bytes()
            if metadata.get("path") == rel and metadata.get("hash") == _hash(raw):
                revisions.append(metadata)
        except (OSError, RecoveryConflict):
            continue
    return revisions


def _revision(rel: str, revision_id: str) -> tuple[dict, bytes]:
    if not re.fullmatch(r"^[0-9TZ.\-a-f]+$", revision_id or ""):
        raise ValueError("invalid revision id")
    revision_dir = _revision_root(rel) / revision_id
    metadata = _read_json(revision_dir / "meta.json")
    raw = (revision_dir / "content.blob").read_bytes()
    if metadata.get("path") != rel or metadata.get("hash") != _hash(raw):
        raise RecoveryConflict("revision content does not match its recovery metadata")
    vault_md._decode_for_edit(raw)
    return metadata, raw


def _store_conflict(
    rel: str,
    local: bytes,
    external: bytes,
    base_hash: str,
    current_hash: str,
) -> dict:
    conflict_id = uuid.uuid4().hex
    conflict_dir = _state_dir("conflicts") / conflict_id
    metadata = {
        "id": conflict_id,
        "path": rel,
        "base_hash": base_hash,
        "local_hash": _hash(local),
        "external_hash": current_hash,
        "external_exists": bool(current_hash),
        "created_at": _now(),
    }
    _atomic_write(conflict_dir / "local.md", local)
    _atomic_write(conflict_dir / "external.md", external)
    _write_json(conflict_dir / "meta.json", metadata)
    return metadata


def load_conflict(conflict_id: str) -> dict:
    if not _TRANSACTION_ID.fullmatch(conflict_id or ""):
        raise ValueError("invalid conflict id")
    conflict_dir = _state_dir("conflicts") / conflict_id
    metadata = _read_json(conflict_dir / "meta.json")
    local = (conflict_dir / "local.md").read_bytes()
    external = (conflict_dir / "external.md").read_bytes()
    if _hash(local) != metadata.get("local_hash"):
        raise RecoveryConflict("local conflict copy is damaged")
    external_exists = metadata.get("external_exists", bool(metadata.get("external_hash")))
    if (external_exists and _hash(external) != metadata.get("external_hash")) or (
        not external_exists and external
    ):
        raise RecoveryConflict("external conflict copy is damaged")
    return {
        **metadata,
        "local": vault_md._decode_for_edit(local),
        "external": vault_md._decode_for_edit(external),
    }


def compare_document(path: str, candidate: str, base_hash: str) -> dict:
    rel, document_path = _normalise_rel(path)
    document_exists = document_path.is_file()
    external = document_path.read_bytes() if document_exists else b""
    external_text = vault_md._decode_for_edit(external) if external else ""
    local_text = candidate or ""
    current_hash = _hash(external) if document_exists else ""
    diff = "".join(
        difflib.unified_diff(
            external_text.splitlines(keepends=True),
            local_text.splitlines(keepends=True),
            fromfile=f"{rel} · external",
            tofile=f"{rel} · local draft",
        )
    )
    return {
        "path": rel,
        "base_hash": base_hash or "",
        "current_hash": current_hash,
        "base_matches": (base_hash or "") == current_hash,
        "external": external_text,
        "local": local_text,
        "diff": diff,
    }


def record_local_write(path: str, written_hash: str) -> dict:
    rel, _ = _normalise_rel(path)
    metadata = {"path": rel, "hash": written_hash, "written_at": _now()}
    _write_json(_state_dir("local-writes") / f"{_path_key(rel)}.json", metadata)
    return metadata


def classify_observed_change(path: str, current_hash: str) -> str:
    """Classify a watcher observation as local, external, or conflicting with a draft."""
    rel, _ = _normalise_rel(path)
    draft = load_draft(rel)
    if draft and draft.get("base_hash", "") != current_hash:
        draft_hash = _hash(draft["content"].encode("utf-8"))
        if draft_hash != current_hash:
            return "conflict"

    marker_path = _state_dir("local-writes") / f"{_path_key(rel)}.json"
    if marker_path.is_file():
        try:
            marker = _read_json(marker_path)
        except RecoveryConflict:
            marker = {}
        if marker.get("path") == rel and marker.get("hash") == current_hash:
            marker_path.unlink(missing_ok=True)
            return "local"
    return "external"


def save_document(
    path: str,
    content: str,
    expected_hash: str,
    *,
    clear_draft: bool = True,
) -> dict:
    """Save a full source document without losing either side of a stale edit."""
    if expected_hash is None:
        raise ValueError("expected_hash is required for a safe document save")
    rel, document_path = _normalise_rel(path)
    document_exists = document_path.is_file()
    current = document_path.read_bytes() if document_exists else b""
    if current:
        vault_md._decode_for_edit(current)
    current_hash = _hash(current) if document_exists else ""
    local = (content or "").encode("utf-8")
    if expected_hash != current_hash:
        conflict = _store_conflict(rel, local, current, expected_hash, current_hash)
        raise DocumentSaveConflict(conflict)

    revision = _snapshot_revision(rel, current, "before save", document_exists=document_exists)
    try:
        _conditional_replace(document_path, local, expected_hash)
    except RecoveryConflict as exc:
        external = document_path.read_bytes() if document_path.is_file() else b""
        conflict = _store_conflict(
            rel,
            local,
            external,
            expected_hash,
            _hash(external) if document_path.is_file() else "",
        )
        raise DocumentSaveConflict(conflict) from exc
    result = {"path": rel, "ok": True, "hash": _hash(local)}
    record_local_write(rel, result["hash"])
    if clear_draft:
        delete_draft_if_hash(rel, result["hash"])
    return {**result, "revision": revision}


def restore_revision(path: str, revision_id: str, expected_hash: str) -> dict:
    rel, document_path = _normalise_rel(path)
    _, revision_raw = _revision(rel, revision_id)
    document_exists = document_path.is_file()
    current = document_path.read_bytes() if document_exists else b""
    current_hash = _hash(current) if document_exists else ""
    if current_hash != expected_hash:
        raise vault_md.DocumentConflictError("document changed since the revision list was opened")
    before_restore = _snapshot_revision(
        rel, current, "before revision restore", document_exists=document_exists
    )
    _conditional_replace(document_path, revision_raw, expected_hash)
    restored_hash = _hash(revision_raw)
    record_local_write(rel, restored_hash)
    delete_draft_if_hash(rel, restored_hash)
    return {
        "ok": True,
        "path": rel,
        "hash": restored_hash,
        "revision": before_restore,
    }


# Crash-safe rename ----------------------------------------------------------


def _rewrite_links(
    text: str,
    old_name: str,
    new_name: str,
    *,
    old_path: str = "",
    new_path: str = "",
    allow_bare: bool = True,
) -> str:
    old_lower = old_name.strip().lower()
    old_path_lower = old_path.removesuffix(".md").strip().lower()
    new_path_target = new_path.removesuffix(".md")

    def replace(match: re.Match) -> str:
        target = match.group(1).strip()
        target_lower = target.removesuffix(".md").lower()
        if old_path_lower and target_lower == old_path_lower:
            return f"[[{new_path_target}{match.group(2)}]]"
        if allow_bare and target_lower == old_lower:
            return f"[[{new_name}{match.group(2)}]]"
        return match.group(0)

    return _LINK.sub(replace, text)


def _transaction_dir(transaction_id: str) -> Path:
    if not _TRANSACTION_ID.fullmatch(transaction_id or ""):
        raise ValueError("invalid transaction id")
    return _state_dir("rename-transactions") / transaction_id


def _transaction_manifest(transaction_id: str) -> tuple[Path, dict]:
    directory = _transaction_dir(transaction_id)
    return directory, _read_json(directory / "manifest.json")


def _write_manifest(directory: Path, manifest: dict) -> None:
    manifest["updated_at"] = _now()
    _write_json(directory / "manifest.json", manifest)


def prepare_rename(old_path: str, new_path: str) -> dict:
    old_rel, source = _normalise_rel(old_path)
    new_rel, destination = _normalise_rel(new_path)
    if not source.is_file():
        raise FileNotFoundError(old_rel)
    if old_rel == new_rel:
        raise ValueError("source and destination are the same")
    case_only_alias = old_rel.casefold() == new_rel.casefold()
    if destination.exists() and not (
        case_only_alias and destination.is_file() and os.path.samefile(source, destination)
    ):
        raise FileExistsError(new_rel)

    source_raw = source.read_bytes()
    transaction_id = uuid.uuid4().hex
    directory = _transaction_dir(transaction_id)
    changes_dir = directory / "changes"
    changes = []
    unsupported = []
    old_name = source.stem
    new_name = destination.stem
    duplicate_stem = any(
        document != source and document.stem.casefold() == old_name.casefold()
        for document in vault_md._all_md()
    )

    for index, document in enumerate(vault_md._all_md()):
        raw = document.read_bytes()
        try:
            text = vault_md._decode_for_edit(raw)
        except vault_md.DocumentEncodingError:
            unsupported.append(str(document.relative_to(vault_md.root_dir())).replace("\\", "/"))
            continue
        rewritten = _rewrite_links(
            text,
            old_name,
            new_name,
            old_path=old_rel,
            new_path=new_rel,
            allow_bare=not duplicate_stem,
        )
        if rewritten == text:
            continue
        target = rewritten.encode("utf-8")
        path_before = str(document.relative_to(vault_md.root_dir())).replace("\\", "/")
        path_after = new_rel if path_before == old_rel else path_before
        original_blob = f"{index:05d}.original"
        target_blob = f"{index:05d}.target"
        _atomic_write(changes_dir / original_blob, raw)
        _atomic_write(changes_dir / target_blob, target)
        changes.append(
            {
                "path_before": path_before,
                "path_after": path_after,
                "original_hash": _hash(raw),
                "target_hash": _hash(target),
                "original_blob": original_blob,
                "target_blob": target_blob,
            }
        )

    _atomic_write(directory / "source.original", source_raw)
    manifest = {
        "id": transaction_id,
        "kind": "rename",
        "state": "prepared",
        "old_path": old_rel,
        "new_path": new_rel,
        "source_hash": _hash(source_raw),
        "quarantine_path": str(
            source.with_name(f".{source.name}.alles-{transaction_id}.moving").relative_to(
                vault_md.root_dir()
            )
        ).replace("\\", "/"),
        "changes": changes,
        "unsupported": unsupported,
        "applied": [],
        "created_at": _now(),
    }
    _write_manifest(directory, manifest)
    return manifest.copy()


def _verified_blob(directory: Path, name: str, expected_hash: str) -> bytes:
    raw = (directory / "changes" / name).read_bytes()
    if _hash(raw) != expected_hash:
        raise RecoveryConflict("rename recovery blob is damaged")
    return raw


def _move_forward(manifest: dict) -> None:
    _, source = _normalise_rel(manifest["old_path"])
    _, destination = _normalise_rel(manifest["new_path"])
    source_exists = source.is_file()
    destination_exists = destination.is_file()
    _, quarantine = _normalise_rel(
        str(manifest.get("quarantine_path") or ""), add_markdown_suffix=False
    )
    quarantine_exists = quarantine.is_file()
    if destination_exists and quarantine_exists:
        if (
            _hash(destination.read_bytes()) == manifest["source_hash"]
            and _hash(quarantine.read_bytes()) == manifest["source_hash"]
        ):
            quarantine.unlink()
            quarantine_exists = False
        else:
            raise RecoveryConflict("rename quarantine conflicts with the destination")
    case_only_alias = str(manifest["old_path"]).casefold() == str(
        manifest["new_path"]
    ).casefold() and str(manifest["old_path"]) != str(manifest["new_path"])
    aliases_same_file = (
        source_exists
        and destination_exists
        and case_only_alias
        and os.path.samefile(source, destination)
    )
    if source_exists and destination_exists and not aliases_same_file:
        raise RecoveryConflict("both rename paths exist; recovery stopped")
    if aliases_same_file:
        destination_exists = False
    if not source_exists and not destination_exists and quarantine_exists:
        if _hash(quarantine.read_bytes()) != manifest["source_hash"]:
            raise RecoveryConflict("rename quarantine changed; recovery stopped")
        try:
            _publish_exclusive(quarantine, destination)
        except RecoveryConflict as exc:
            raise RecoveryConflict("rename destination appeared during recovery") from exc
        _fsync_directory(destination.parent)
        return
    if not source_exists and not destination_exists:
        raise RecoveryConflict("neither rename path exists; recovery stopped")
    if quarantine_exists:
        raise RecoveryConflict("rename quarantine conflicts with a visible path")
    if source_exists:
        if _hash(source.read_bytes()) != manifest["source_hash"]:
            raise RecoveryConflict("source changed after rename was prepared")
        _move_exclusive(
            source,
            destination,
            manifest["source_hash"],
            quarantine=quarantine,
            allow_source_alias=case_only_alias,
        )
        return

    allowed = {manifest["source_hash"]}
    allowed.update(
        change["target_hash"]
        for change in manifest["changes"]
        if change["path_after"] == manifest["new_path"]
    )
    if _hash(destination.read_bytes()) not in allowed:
        raise RecoveryConflict("renamed source no longer matches a verified transaction state")


def resume_rename(transaction_id: str) -> dict:
    directory, manifest = _transaction_manifest(transaction_id)
    if manifest.get("state") == "complete":
        return manifest
    if manifest.get("state") == "rolled_back":
        raise RecoveryConflict("a rolled-back rename cannot be resumed")

    _move_forward(manifest)
    manifest["state"] = "renamed"
    _write_manifest(directory, manifest)

    applied = set(manifest.get("applied", []))
    for change in manifest.get("changes", []):
        _, path = _normalise_rel(change["path_after"])
        if not path.is_file():
            raise RecoveryConflict(f"rename target disappeared: {change['path_after']}")
        current_hash = _hash(path.read_bytes())
        if current_hash == change["target_hash"]:
            pass
        elif current_hash == change["original_hash"]:
            target = _verified_blob(directory, change["target_blob"], change["target_hash"])
            _conditional_replace(path, target, change["original_hash"])
        else:
            raise RecoveryConflict(
                f"document changed during rename recovery: {change['path_after']}"
            )
        applied.add(change["path_after"])
        manifest["applied"] = sorted(applied)
        _write_manifest(directory, manifest)

    manifest["state"] = "complete"
    _write_manifest(directory, manifest)
    return manifest


def rollback_rename(transaction_id: str) -> dict:
    directory, manifest = _transaction_manifest(transaction_id)
    if manifest.get("state") == "rolled_back":
        return manifest

    for change in reversed(manifest.get("changes", [])):
        _, path = _normalise_rel(change["path_after"])
        if not path.is_file():
            continue
        current_hash = _hash(path.read_bytes())
        if current_hash == change["original_hash"]:
            continue
        if current_hash != change["target_hash"]:
            raise RecoveryConflict(
                f"document changed during rename rollback: {change['path_after']}"
            )
        original = _verified_blob(directory, change["original_blob"], change["original_hash"])
        _conditional_replace(path, original, change["target_hash"])

    _, source = _normalise_rel(manifest["old_path"])
    _, destination = _normalise_rel(manifest["new_path"])
    source_exists = source.is_file()
    destination_exists = destination.is_file()
    case_only_alias = str(manifest["old_path"]).casefold() == str(
        manifest["new_path"]
    ).casefold() and str(manifest["old_path"]) != str(manifest["new_path"])
    _, quarantine = _normalise_rel(
        str(manifest.get("quarantine_path") or ""), add_markdown_suffix=False
    )
    case_alias_rolled_back = False
    if (
        source_exists
        and destination_exists
        and case_only_alias
        and os.path.samefile(source, destination)
    ):
        if _hash(destination.read_bytes()) != manifest["source_hash"]:
            raise RecoveryConflict("renamed source changed; rollback stopped")
        _move_exclusive(
            destination,
            source,
            manifest["source_hash"],
            allow_source_alias=True,
        )
        source_exists = True
        destination_exists = False
        case_alias_rolled_back = True
    elif source_exists and destination_exists:
        if (
            _hash(source.read_bytes()) != manifest["source_hash"]
            or _hash(destination.read_bytes()) != manifest["source_hash"]
            or not os.path.samefile(source, destination)
        ):
            raise RecoveryConflict("both rename paths exist; rollback stopped")
        destination.unlink()
        _fsync_directory(destination.parent)
        destination_exists = False
    if not case_alias_rolled_back and source_exists and quarantine.is_file():
        if _hash(quarantine.read_bytes()) != manifest["source_hash"] or not os.path.samefile(
            source, quarantine
        ):
            raise RecoveryConflict("rename quarantine changed; rollback stopped")
        quarantine.unlink()
        _fsync_directory(quarantine.parent)
    if (
        not case_alias_rolled_back
        and not source_exists
        and destination_exists
        and quarantine.is_file()
    ):
        if (
            _hash(destination.read_bytes()) != manifest["source_hash"]
            or _hash(quarantine.read_bytes()) != manifest["source_hash"]
        ):
            raise RecoveryConflict("rename quarantine changed; rollback stopped")
        _restore_exclusive(quarantine, source)
        destination.unlink()
        _fsync_directory(destination.parent)
        source_exists = True
        destination_exists = False
    if (
        not case_alias_rolled_back
        and not source_exists
        and not destination_exists
        and quarantine.is_file()
    ):
        if _hash(quarantine.read_bytes()) != manifest["source_hash"]:
            raise RecoveryConflict("rename quarantine changed; rollback stopped")
        _restore_exclusive(quarantine, source)
        source_exists = True
    if not source_exists and not destination_exists:
        raise RecoveryConflict("neither rename path exists; rollback stopped")
    if case_alias_rolled_back:
        pass
    elif destination_exists:
        if _hash(destination.read_bytes()) != manifest["source_hash"]:
            raise RecoveryConflict("renamed source changed; rollback stopped")
        _move_exclusive(destination, source, manifest["source_hash"])
    elif _hash(source.read_bytes()) != manifest["source_hash"]:
        raise RecoveryConflict("source changed; rollback stopped")

    manifest["state"] = "rolled_back"
    manifest["applied"] = []
    _write_manifest(directory, manifest)
    return manifest


def rename_document(old_path: str, new_path: str) -> dict:
    manifest = prepare_rename(old_path, new_path)
    try:
        return resume_rename(manifest["id"])
    except Exception as exc:
        raise RenameRecoveryRequired(manifest["id"], str(exc)) from exc


def pending_renames() -> list[dict]:
    pending = []
    for directory in _state_dir("rename-transactions").iterdir():
        if not directory.is_dir() or not _TRANSACTION_ID.fullmatch(directory.name):
            continue
        try:
            manifest = _read_json(directory / "manifest.json")
        except RecoveryConflict:
            continue
        if manifest.get("state") not in {"complete", "rolled_back"}:
            pending.append(manifest)
    return sorted(pending, key=lambda item: item.get("created_at", ""))
