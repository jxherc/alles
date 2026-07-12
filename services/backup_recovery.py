"""Versioned, bounded backup archives and restore staging.

Nothing in this module replaces live data. An archive is only unpacked into a
sibling staging directory. The CLI performs the later offline swap.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.build_info import RECOVERY_COMPATIBILITY, SQLITE_APPLICATION_ID, build_info
from core.credential_inventory import (
    CONFIG_CREDENTIAL_FIELDS,
    DATABASE_CREDENTIAL_FIELDS,
    SETTING_CREDENTIAL_KEYS,
)

ARCHIVE_FORMAT = "alles-recovery"
ARCHIVE_VERSION = 1
MANIFEST_NAME = "manifest.json"
PAYLOAD_PREFIX = "payload/data/"
CHUNK_SIZE = 1024 * 1024

_RESTORE_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TRANSIENT_ROOT_FILES = {
    "aide.db-journal",
    "aide.db-shm",
    "aide.db-wal",
    "alles-server.log",
    "alles.pid",
}

LEGACY_LOCATION_ROLES = ("data", "vault", "files", "photos")
LOCATION_ROLES = (
    *LEGACY_LOCATION_ROLES,
    "photos_watch",
    "agent_allowed_roots",
    "project_workspaces",
    "photokit_library",
    "remote_services",
    "webdav",
    "s3",
    "model_cache",
    "codex_home",
    "recovery_work",
)

# This policy inventory is deliberately content-free. The file/hash inventory below proves what
# bytes are present; these rows explain which current data classes those bytes represent and which
# classes are intentionally outside a full backup.
DATA_CLASS_POLICIES = (
    {
        "id": "database_rows",
        "coverage": "included",
        "policy": "consistent-aide-db-snapshot",
    },
    {
        "id": "settings_and_connector_config",
        "coverage": "included-when-present",
        "policy": "alles-data-files-and-database-rows",
    },
    {
        "id": "application_keys",
        "coverage": "included-when-present",
        "policy": "dependency-checked-secret-recovery-and-push-keys",
    },
    {
        "id": "passwords_ciphertext_and_attachments",
        "coverage": "included",
        "policy": "database-plus-checked-vault-attachment-blobs",
    },
    {
        "id": "markdown_vault",
        "coverage": "location-policy",
        "policy": "included-only-when-under-alles-data",
    },
    {
        "id": "managed_files",
        "coverage": "location-policy",
        "policy": "included-only-when-under-alles-data",
    },
    {
        "id": "photos_and_thumbnails",
        "coverage": "opt-in",
        "policy": "included-only-when-selected-and-under-alles-data",
    },
    {
        "id": "uploads_and_legacy_gallery",
        "coverage": "included-when-present",
        "policy": "alles-data-tree",
    },
    {
        "id": "contact_media",
        "coverage": "included-when-present",
        "policy": "alles-data-tree",
    },
    {
        "id": "skills",
        "coverage": "included-when-present",
        "policy": "alles-data-tree",
    },
    {
        "id": "blob_store",
        "coverage": "included-when-present",
        "policy": "alles-data-tree",
    },
    {
        "id": "file_history_and_trash",
        "coverage": "included-when-present",
        "policy": "alles-data-tree",
    },
    {
        "id": "agent_research_and_compare_state",
        "coverage": "included-when-present",
        "policy": "alles-data-tree",
    },
    {
        "id": "andromeda_saved_searches",
        "coverage": "included",
        "policy": "consistent-aide-db-snapshot",
    },
    {
        "id": "sync_state",
        "coverage": "included-when-present",
        "policy": "alles-data-tree",
    },
    {
        "id": "native_helpers",
        "coverage": "included-when-present",
        "policy": "alles-data-tree-rebuildable",
    },
    {
        "id": "indexes",
        "coverage": "included-when-present",
        "policy": "database-and-alles-data-tree",
    },
    {
        "id": "runtime_transients",
        "coverage": "excluded",
        "policy": "pid-log-and-sqlite-sidecars-rebuilt",
    },
    {
        "id": "recovery_work",
        "coverage": "excluded",
        "policy": "sibling-staging-rollbacks-and-temp-exports",
    },
    {
        "id": "external_sources_and_workspaces",
        "coverage": "excluded",
        "policy": "metadata-only-never-copy-unselected-roots",
    },
    {
        "id": "remote_service_content",
        "coverage": "excluded",
        "policy": "local-config-and-cache-only",
    },
    {
        "id": "model_and_tool_caches",
        "coverage": "excluded",
        "policy": "rebuildable-state-outside-alles-data",
    },
)


class RecoveryError(ValueError):
    """A safe, user-facing recovery validation failure."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 256 * 1024**3
    max_manifest_bytes: int = 64 * 1024**2
    max_files: int = 250_000
    max_path_bytes: int = 1024
    max_component_bytes: int = 255
    max_file_bytes: int = 256 * 1024**3
    max_total_bytes: int = 1024**4
    max_compression_ratio: float = 200.0
    ratio_check_min_bytes: int = 64 * 1024**2
    total_ratio_check_min_bytes: int = 256 * 1024**2
    free_space_min_margin_bytes: int = 1024**3
    free_space_margin_fraction: float = 0.10


DEFAULT_LIMITS = ArchiveLimits()


@dataclass(frozen=True)
class StagedRecovery:
    restore_id: str
    root: Path
    data_dir: Path
    manifest: dict
    state: str


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_relative_path(path: str, *, limits: ArchiveLimits = DEFAULT_LIMITS) -> str:
    """Return one canonical portable relative path, or reject it."""
    if not isinstance(path, str) or not path:
        raise RecoveryError("archive path must be a non-empty string")
    if "\\" in path or path.startswith("/"):
        raise RecoveryError(f"unsafe archive path: {path!r}")
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise RecoveryError("archive path contains a control character")

    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise RecoveryError(f"unsafe archive path: {path!r}")
    if len(parts[0]) >= 2 and parts[0][1] == ":" and parts[0][0].isalpha():
        raise RecoveryError(f"unsafe archive path: {path!r}")
    if len(path.encode("utf-8")) > limits.max_path_bytes:
        raise RecoveryError("archive path is too long")
    if any(len(part.encode("utf-8")) > limits.max_component_bytes for part in parts):
        raise RecoveryError("archive path component is too long")
    return path


def _portable_key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def _supported_migrations() -> dict[int, str]:
    from core.migrations.runner import migration_catalog

    return migration_catalog()


def current_schema_version() -> int:
    supported = _supported_migrations()
    return max(supported, default=0)


def _database_info(path: Path, *, require_application_id: bool) -> dict:
    if _is_link_like(path):
        raise RecoveryError("staged SQLite database cannot be a link")
    try:
        with path.open("rb") as handle:
            header = handle.read(16)
        if header != b"SQLite format 3\x00":
            raise RecoveryError("aide.db is not a SQLite database")
    except OSError as exc:
        raise RecoveryError("could not read staged SQLite database") from exc

    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)]:
                raise RecoveryError("SQLite integrity check failed")
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RecoveryError("SQLite foreign-key check failed")

            application_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
            if require_application_id and application_id != SQLITE_APPLICATION_ID:
                raise RecoveryError("SQLite application id does not match Alles")

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not {"sessions", "tasks"}.issubset(tables):
                raise RecoveryError("SQLite database is not an Alles database")

            applied = []
            if "schema_migrations" in tables:
                rows = conn.execute(
                    "SELECT version, name FROM schema_migrations ORDER BY version"
                ).fetchall()
                for version, name in rows:
                    if not _is_int(version) or not isinstance(name, str):
                        raise RecoveryError("invalid schema migration record")
                    applied.append({"version": version, "name": name})
    except RecoveryError:
        raise
    except sqlite3.Error as exc:
        raise RecoveryError("SQLite validation failed") from exc

    return {"application_id": application_id, "applied_migrations": applied}


def _validate_migrations(applied: list[dict]) -> None:
    from core.migrations.runner import MigrationHistoryError, validate_migration_history

    versions = [item["version"] for item in applied]
    if versions and versions != list(range(1, versions[-1] + 1)):
        raise RecoveryError("database migration history has gaps")
    try:
        validate_migration_history(applied, allow_known_photo_fork=True)
    except MigrationHistoryError as exc:
        raise RecoveryError(str(exc)) from exc


def snapshot_sqlite(source_path: Path, snapshot_path: Path) -> None:
    """Create a consistent SQLite/WAL snapshot and mark it as an Alles database."""
    if _is_link_like(source_path) or not source_path.is_file():
        raise RecoveryError("aide.db is missing")
    snapshot_path.unlink(missing_ok=True)
    source_uri = f"{source_path.resolve().as_uri()}?mode=ro"
    try:
        with (
            closing(sqlite3.connect(source_uri, uri=True)) as source,
            closing(sqlite3.connect(snapshot_path)) as snapshot,
        ):
            source.backup(snapshot)
            snapshot.execute("PRAGMA journal_mode = DELETE")
            snapshot.execute(f"PRAGMA application_id = {SQLITE_APPLICATION_ID}")
            snapshot.commit()
    except sqlite3.Error as exc:
        snapshot_path.unlink(missing_ok=True)
        raise RecoveryError("could not create a consistent SQLite snapshot") from exc
    _database_info(snapshot_path, require_application_id=True)


def _read_settings(root: Path) -> dict:
    path = root / "settings.json"
    if not path.is_file() or _is_link_like(path):
        return {}
    try:
        value = json.loads(path.read_text("utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _configured_path(root: Path, settings: dict, key: str, default: str) -> Path:
    raw = settings.get(key)
    value = raw.strip() if isinstance(raw, str) and raw.strip() else str(root / default)
    return Path(value).expanduser().resolve()


def _require_managed_database(root: Path) -> None:
    raw = os.environ.get("ALLES_DB", "").strip()
    if not raw:
        return
    try:
        configured = Path(raw).expanduser().resolve()
        managed = (root / "aide.db").resolve()
    except OSError as exc:
        raise RecoveryError("could not verify the configured database path") from exc
    if configured != managed:
        raise RecoveryError("full backup is disabled while ALLES_DB points outside ALLES_DATA")


def _relative_to(path: Path, root: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _overlaps(left: Path, right: Path) -> bool:
    return _relative_to(left, right) is not None or _relative_to(right, left) is not None


def _excluded_location(role: str, policy: str) -> dict:
    return {
        "role": role,
        "included": False,
        "storage": None,
        "subpath": None,
        "policy": policy,
    }


def _other_location_policies(
    settings: dict,
    *,
    webdav_config: dict | None = None,
    s3_config: dict | None = None,
) -> list[dict]:
    photos_watch = settings.get("photos_watch_folder")
    watch_configured = isinstance(photos_watch, str) and bool(photos_watch.strip())
    agent_roots = settings.get("agent_allowed_roots")
    agent_roots_configured = isinstance(agent_roots, list) and any(
        isinstance(item, str) and item.strip() for item in agent_roots
    )
    webdav_config = webdav_config or {}
    webdav_configured = all(
        isinstance(webdav_config.get(key), str) and bool(webdav_config[key].strip())
        for key in ("url", "username", "password")
    )
    s3_config = s3_config or {}
    s3_configured = all(
        isinstance(s3_config.get(key), str) and bool(s3_config[key].strip())
        for key in ("endpoint", "region", "bucket", "credentials")
    )
    return [
        _excluded_location(
            "photos_watch",
            "source-only-excluded" if watch_configured else "not-configured",
        ),
        _excluded_location(
            "agent_allowed_roots",
            "workspace-content-excluded" if agent_roots_configured else "not-configured",
        ),
        _excluded_location("project_workspaces", "database-metadata-only"),
        _excluded_location("photokit_library", "source-only-imported-copies-follow-photos"),
        _excluded_location("remote_services", "local-config-and-cache-only"),
        _excluded_location("webdav", "configured" if webdav_configured else "not-configured"),
        _excluded_location("s3", "configured" if s3_configured else "not-configured"),
        _excluded_location("model_cache", "rebuildable-excluded"),
        _excluded_location("codex_home", "separate-tool-state-excluded"),
        _excluded_location("recovery_work", "runtime-staging-and-rollbacks-excluded"),
    ]


def _location_plan(
    root: Path,
    *,
    include_photos: bool,
    settings: dict | None = None,
    webdav_config: dict | None = None,
    s3_config: dict | None = None,
) -> tuple[list[dict], Path | None]:
    settings = _read_settings(root) if settings is None else settings
    if webdav_config is None:
        webdav_config = _credential_config(
            root / "webdav_backup.json",
            require_sealed=False,
        )
    if s3_config is None:
        s3_config = _credential_config(
            root / "s3_backup.json",
            require_sealed=False,
        )
    vault = _configured_path(root, settings, "vault_dir", "vault")
    files = _configured_path(root, settings, "files_dir", "files")
    photos = _configured_path(root, settings, "photos_dir", "photos")

    locations = [
        {
            "role": "data",
            "included": True,
            "storage": "data",
            "subpath": "",
            "policy": "required",
        }
    ]
    for role, path in (("vault", vault), ("files", files)):
        relative = _relative_to(path, root)
        locations.append(
            {
                "role": role,
                "included": relative is not None,
                "storage": "data" if relative is not None else None,
                "subpath": relative,
                "policy": "default" if relative is not None else "external-not-selected",
            }
        )

    photo_relative = _relative_to(photos, root)
    forced_by_overlap = photo_relative is not None and (
        _overlaps(photos, vault) or _overlaps(photos, files)
    )
    photo_included = photo_relative is not None and (include_photos or forced_by_overlap)
    if photo_included:
        photo_policy = "selected" if include_photos else "included-overlap"
    elif photo_relative is None:
        photo_policy = "external-not-selected"
    else:
        photo_policy = "opt-in-required"
    locations.append(
        {
            "role": "photos",
            "included": photo_included,
            "storage": "data" if photo_included else None,
            "subpath": photo_relative if photo_included else None,
            "policy": photo_policy,
        }
    )
    locations.extend(
        _other_location_policies(
            settings,
            webdav_config=webdav_config,
            s3_config=s3_config,
        )
    )
    excluded_photos = photos if photo_relative is not None and not photo_included else None
    return locations, excluded_photos


def _is_excluded(path: Path, excluded_root: Path | None) -> bool:
    return excluded_root is not None and _relative_to(path.resolve(), excluded_root) is not None


def _collect_data_tree(
    root: Path, *, excluded_root: Path | None, limits: ArchiveLimits
) -> tuple[list[tuple[str, Path]], list[str], list[dict]]:
    files: list[tuple[str, Path]] = []
    directories: list[str] = []
    skipped_symlinks = 0
    skipped_special = 0

    for current_raw, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(current_raw)
        if current != root and _is_excluded(current, excluded_root):
            dirnames[:] = []
            continue

        kept_dirs = []
        for name in sorted(dirnames):
            path = current / name
            if _is_link_like(path):
                skipped_symlinks += 1
            elif _is_excluded(path, excluded_root):
                continue
            else:
                kept_dirs.append(name)
        dirnames[:] = kept_dirs

        if current != root:
            relative = current.relative_to(root).as_posix()
            validate_relative_path(relative, limits=limits)
            directories.append(relative)

        for name in sorted(filenames):
            path = current / name
            relative = path.relative_to(root).as_posix()
            if current == root and name in _TRANSIENT_ROOT_FILES | {"aide.db"}:
                continue
            if _is_excluded(path, excluded_root):
                continue
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                raise RecoveryError(f"could not inspect backup file: {relative}") from exc
            if stat.S_ISLNK(mode):
                skipped_symlinks += 1
                continue
            if not stat.S_ISREG(mode):
                skipped_special += 1
                continue
            validate_relative_path(relative, limits=limits)
            files.append((relative, path))

    warnings = []
    if skipped_symlinks:
        warnings.append({"kind": "symlinks-skipped", "count": skipped_symlinks})
    if skipped_special:
        warnings.append({"kind": "special-files-skipped", "count": skipped_special})
    return files, directories, warnings


def _check_path_collisions(files: list[str], directories: list[str]) -> None:
    seen: dict[str, str] = {}
    file_set = set(files)
    portable_files = {_portable_key(path): path for path in files}
    for path in [*files, *directories]:
        key = _portable_key(path)
        if key in seen and seen[key] != path:
            raise RecoveryError(f"archive paths collide: {seen[key]!r} and {path!r}")
        seen[key] = path
    for path in files:
        parts = path.split("/")
        for index in range(1, len(parts)):
            prefix = "/".join(parts[:index])
            portable_prefix = _portable_key(prefix)
            if portable_prefix in portable_files:
                conflict = portable_files[portable_prefix]
                raise RecoveryError(f"archive file path conflicts with child path: {conflict!r}")
    if file_set.intersection(directories):
        raise RecoveryError("archive path is both a file and directory")


def _copy_to_zip(
    source: Path,
    zf: zipfile.ZipFile,
    archive_name: str,
    *,
    limits: ArchiveLimits,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    try:
        with source.open("rb") as src, zf.open(archive_name, "w", force_zip64=True) as dest:
            while chunk := src.read(CHUNK_SIZE):
                total += len(chunk)
                if total > limits.max_file_bytes:
                    raise RecoveryError(f"backup file is too large: {source.name}")
                digest.update(chunk)
                dest.write(chunk)
    except RecoveryError:
        raise
    except OSError as exc:
        raise RecoveryError(f"could not read backup file: {source.name}") from exc
    return total, digest.hexdigest()


def _manifest_bytes(manifest: dict, limits: ArchiveLimits) -> bytes:
    encoded = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > limits.max_manifest_bytes:
        raise RecoveryError("backup manifest is too large")
    return encoded


def _hash_path(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                total += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise RecoveryError(f"could not hash staged file: {path.name}") from exc
    return total, digest.hexdigest()


_FROZEN_ROOT_DEPENDENCIES = (
    "settings.json",
    *(name for name, _key, _purpose in CONFIG_CREDENTIAL_FIELDS),
    "secret.key",
    "recovery.key",
    "vapid.pem",
)


def _freeze_backup_source(
    source: Path,
    destination: Path,
    *,
    limits: ArchiveLimits,
) -> Path:
    if _is_link_like(source):
        raise RecoveryError(f"backup dependency cannot be a link: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    source_fd = None
    try:
        source_fd = os.open(source, flags)
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise RecoveryError(f"backup dependency is not a file: {source.name}")
        total = 0
        with os.fdopen(source_fd, "rb") as src, destination.open("xb") as dest:
            source_fd = None
            while chunk := src.read(CHUNK_SIZE):
                total += len(chunk)
                if total > limits.max_file_bytes:
                    raise RecoveryError(f"backup file is too large: {source.name}")
                dest.write(chunk)
            dest.flush()
            os.fsync(dest.fileno())
        try:
            destination.chmod(0o600)
        except OSError:
            pass
        return destination
    except RecoveryError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise RecoveryError(f"could not freeze backup dependency: {source.name}") from exc
    finally:
        if source_fd is not None:
            os.close(source_fd)


def _freeze_root_dependencies(
    root: Path,
    frozen_root: Path,
    *,
    limits: ArchiveLimits,
) -> dict[str, Path]:
    frozen = {}
    for relative in _FROZEN_ROOT_DEPENDENCIES:
        source = root / relative
        if _is_link_like(source):
            raise RecoveryError(f"backup dependency cannot be a link: {relative}")
        if source.exists():
            frozen[relative] = _freeze_backup_source(
                source,
                frozen_root / relative,
                limits=limits,
            )
    return frozen


def _freeze_dependency_sources(
    sources: list[tuple[str, Path]],
    frozen_root: Path,
    frozen_root_sources: dict[str, Path],
    *,
    limits: ArchiveLimits,
) -> list[tuple[str, Path]]:
    source_map = dict(sources)
    for relative in _FROZEN_ROOT_DEPENDENCIES:
        source_map.pop(relative, None)
    source_map.update(frozen_root_sources)

    for relative, source in list(source_map.items()):
        if relative.startswith("vault_attachments/") and relative.endswith(".enc"):
            source_map[relative] = _freeze_backup_source(
                source,
                frozen_root / relative,
                limits=limits,
            )
    return sorted(source_map.items())


def create_recovery_archive(
    data_root: Path,
    output_path: Path,
    *,
    include_photos: bool = False,
    expected_recovery_key: bytes | None = None,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> dict:
    """Create one atomic v1 archive without copying a live SQLite file directly."""
    raw_root = data_root.expanduser()
    if _is_link_like(raw_root):
        raise RecoveryError("Alles data directory cannot be a link")
    root = raw_root.resolve()
    output = output_path.expanduser().resolve()
    if not root.is_dir():
        raise RecoveryError("Alles data directory does not exist")
    _require_managed_database(root)
    if _relative_to(output, root) is not None:
        raise RecoveryError("backup output must be outside the live data directory")
    output.parent.mkdir(parents=True, exist_ok=True)

    temp_output = output.parent / f".{output.name}.{uuid.uuid4().hex}.partial"

    try:
        with tempfile.TemporaryDirectory(prefix="alles-snapshot-", dir=output.parent) as tmp:
            from services.recovery_consistency import recovery_consistency_lock

            with recovery_consistency_lock:
                snapshot = Path(tmp) / "aide.db"
                snapshot_sqlite(root / "aide.db", snapshot)
                db_info = _database_info(snapshot, require_application_id=True)
                _validate_migrations(db_info["applied_migrations"])
                _validate_database_dependencies(root, snapshot, require_sealed=False)
                frozen_root = Path(tmp) / "dependencies"
                frozen_root.mkdir(mode=0o700)
                frozen_root_sources = _freeze_root_dependencies(
                    root,
                    frozen_root,
                    limits=limits,
                )
                if expected_recovery_key is not None:
                    from services.recovery_crypto import load_recovery_key

                    captured_key = load_recovery_key(frozen_root / "recovery.key")
                    if not hmac.compare_digest(captured_key, expected_recovery_key):
                        raise RecoveryError(
                            "recovery key changed while the backup was being created"
                        )
                locations, excluded_photos = _location_plan(
                    root,
                    include_photos=include_photos,
                    settings=_read_settings(frozen_root),
                    webdav_config=_credential_config(
                        frozen_root / "webdav_backup.json",
                        require_sealed=True,
                    ),
                    s3_config=_credential_config(
                        frozen_root / "s3_backup.json",
                        require_sealed=True,
                    ),
                )
                sources, directories, warnings = _collect_data_tree(
                    root, excluded_root=excluded_photos, limits=limits
                )
                sources = _freeze_dependency_sources(
                    sources,
                    frozen_root,
                    frozen_root_sources,
                    limits=limits,
                )
                _validate_database_dependencies(frozen_root, snapshot, require_sealed=True)
            sources.append(("aide.db", snapshot))
            sources.sort(key=lambda item: item[0])
            directories = sorted(set(directories))
            _check_path_collisions([path for path, _ in sources], directories)

            if len(sources) + len(directories) > limits.max_files:
                raise RecoveryError("backup contains too many files")

            entries = []
            total_bytes = 0
            with zipfile.ZipFile(
                temp_output,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                allowZip64=True,
            ) as zf:
                for relative, source in sources:
                    size, checksum = _copy_to_zip(
                        source, zf, f"{PAYLOAD_PREFIX}{relative}", limits=limits
                    )
                    total_bytes += size
                    if total_bytes > limits.max_total_bytes:
                        raise RecoveryError("backup extracted size exceeds the configured limit")
                    entries.append(
                        {
                            "storage": "data",
                            "path": relative,
                            "size": size,
                            "sha256": checksum,
                        }
                    )

                producer = build_info()
                manifest = {
                    "format": ARCHIVE_FORMAT,
                    "format_version": ARCHIVE_VERSION,
                    "restore_compatibility": RECOVERY_COMPATIBILITY,
                    "created_at": _now(),
                    "producer": {
                        "name": producer["name"],
                        "version": producer["version"],
                        "build_id": producer["build_id"],
                        "migration_head": current_schema_version(),
                    },
                    "database": {
                        "storage": "data",
                        "path": "aide.db",
                        "application_id": SQLITE_APPLICATION_ID,
                        "applied_migrations": db_info["applied_migrations"],
                    },
                    "data_classes": [dict(item) for item in DATA_CLASS_POLICIES],
                    "storages": [{"id": "data", "source_kind": "alles_data"}],
                    "locations": locations,
                    "files": entries,
                    "directories": [{"storage": "data", "path": path} for path in directories],
                    "totals": {"files": len(entries), "bytes": total_bytes},
                    "warnings": warnings,
                }
                zf.writestr(MANIFEST_NAME, _manifest_bytes(manifest, limits))

        if temp_output.stat().st_size > limits.max_archive_bytes:
            raise RecoveryError("backup archive exceeds the configured size limit")
        os.replace(temp_output, output)
        return manifest
    except Exception:
        temp_output.unlink(missing_ok=True)
        raise


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryError(f"duplicate JSON key in manifest: {key}")
        result[key] = value
    return result


def _exact_keys(value: dict, expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise RecoveryError(f"invalid {label} fields")


def _validate_manifest(manifest: dict, *, limits: ArchiveLimits) -> dict:
    if not isinstance(manifest, dict):
        raise RecoveryError("backup manifest must be a JSON object")
    required = {
        "format",
        "format_version",
        "restore_compatibility",
        "created_at",
        "producer",
        "database",
        "storages",
        "locations",
        "files",
        "directories",
        "totals",
        "warnings",
    }
    allowed = required | {"source_format_version", "data_classes"}
    if not required.issubset(manifest) or not set(manifest).issubset(allowed):
        raise RecoveryError("backup manifest fields do not match format v1")
    if manifest["format"] != ARCHIVE_FORMAT or manifest["format_version"] != ARCHIVE_VERSION:
        raise RecoveryError("unsupported backup format")
    if manifest["restore_compatibility"] != RECOVERY_COMPATIBILITY:
        raise RecoveryError("backup recovery compatibility is not supported")
    if "source_format_version" in manifest and manifest["source_format_version"] != 0:
        raise RecoveryError("invalid source backup format")
    if "data_classes" in manifest:
        data_classes = manifest["data_classes"]
        if data_classes != [dict(item) for item in DATA_CLASS_POLICIES]:
            raise RecoveryError("backup data-class policy inventory is invalid")
    try:
        created = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError
    except (AttributeError, ValueError):
        raise RecoveryError("invalid backup creation time") from None

    producer = manifest["producer"]
    if not isinstance(producer, dict):
        raise RecoveryError("invalid backup producer")
    _exact_keys(producer, {"name", "version", "build_id", "migration_head"}, "producer")
    if producer["name"] != "alles":
        raise RecoveryError("backup was not produced by Alles")
    if not all(isinstance(producer[key], str) for key in ("version", "build_id")):
        raise RecoveryError("invalid backup build metadata")
    if not _is_int(producer["migration_head"]) or producer["migration_head"] < 0:
        raise RecoveryError("invalid producer migration head")

    storages = manifest["storages"]
    if storages != [{"id": "data", "source_kind": "alles_data"}]:
        raise RecoveryError("backup storage layout is not supported")

    files = manifest["files"]
    directories = manifest["directories"]
    if not isinstance(files, list) or not isinstance(directories, list):
        raise RecoveryError("invalid backup path inventory")
    if len(files) + len(directories) > limits.max_files:
        raise RecoveryError("backup contains too many files")

    clean_files = []
    total = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise RecoveryError("invalid backup file entry")
        _exact_keys(entry, {"storage", "path", "size", "sha256"}, "file entry")
        if entry["storage"] != "data":
            raise RecoveryError("backup file uses an unsupported storage")
        path = validate_relative_path(entry["path"], limits=limits)
        size = entry["size"]
        checksum = entry["sha256"]
        if not _is_int(size) or size < 0 or size > limits.max_file_bytes:
            raise RecoveryError(f"invalid size for backup file: {path}")
        if not isinstance(checksum, str) or not _SHA256.fullmatch(checksum):
            raise RecoveryError(f"invalid checksum for backup file: {path}")
        total += size
        if total > limits.max_total_bytes:
            raise RecoveryError("backup extracted size exceeds the configured limit")
        clean_files.append(entry)

    clean_directories = []
    for entry in directories:
        if not isinstance(entry, dict):
            raise RecoveryError("invalid backup directory entry")
        _exact_keys(entry, {"storage", "path"}, "directory entry")
        if entry["storage"] != "data":
            raise RecoveryError("backup directory uses an unsupported storage")
        validate_relative_path(entry["path"], limits=limits)
        clean_directories.append(entry)

    paths = [entry["path"] for entry in clean_files]
    dir_paths = [entry["path"] for entry in clean_directories]
    if paths != sorted(paths) or dir_paths != sorted(dir_paths):
        raise RecoveryError("backup path inventory is not sorted")
    if len(set(paths)) != len(paths) or len(set(dir_paths)) != len(dir_paths):
        raise RecoveryError("backup path inventory contains duplicates")
    _check_path_collisions(paths, dir_paths)

    totals = manifest["totals"]
    if not isinstance(totals, dict):
        raise RecoveryError("invalid backup totals")
    _exact_keys(totals, {"files", "bytes"}, "totals")
    if totals != {"files": len(files), "bytes": total}:
        raise RecoveryError("backup totals do not match its inventory")

    database = manifest["database"]
    if not isinstance(database, dict):
        raise RecoveryError("invalid backup database metadata")
    _exact_keys(
        database,
        {"storage", "path", "application_id", "applied_migrations"},
        "database",
    )
    if (
        database["storage"] != "data"
        or database["path"] != "aide.db"
        or database["application_id"] != SQLITE_APPLICATION_ID
    ):
        raise RecoveryError("invalid backup database location")
    if paths.count("aide.db") != 1:
        raise RecoveryError("backup must contain one aide.db")
    applied = database["applied_migrations"]
    if not isinstance(applied, list):
        raise RecoveryError("invalid database migration inventory")
    for item in applied:
        if not isinstance(item, dict):
            raise RecoveryError("invalid database migration entry")
        _exact_keys(item, {"version", "name"}, "database migration")
        if not _is_int(item["version"]) or item["version"] < 1 or not isinstance(item["name"], str):
            raise RecoveryError("invalid database migration entry")

    locations = manifest["locations"]
    if not isinstance(locations, list):
        raise RecoveryError("invalid backup location inventory")
    roles = []
    for location in locations:
        if not isinstance(location, dict):
            raise RecoveryError("invalid backup location")
        _exact_keys(
            location,
            {"role", "included", "storage", "subpath", "policy"},
            "location",
        )
        if not isinstance(location["role"], str) or not isinstance(location["included"], bool):
            raise RecoveryError("invalid backup location")
        if location["storage"] not in {None, "data"}:
            raise RecoveryError("invalid backup location storage")
        if location["subpath"] is not None:
            if location["subpath"] != "":
                validate_relative_path(location["subpath"], limits=limits)
        if not isinstance(location["policy"], str):
            raise RecoveryError("invalid backup location policy")
        roles.append(location["role"])
    if roles not in [list(LEGACY_LOCATION_ROLES), list(LOCATION_ROLES)]:
        raise RecoveryError("backup location inventory is incomplete")

    warnings = manifest["warnings"]
    if not isinstance(warnings, list):
        raise RecoveryError("invalid backup warnings")
    for warning in warnings:
        if not isinstance(warning, dict):
            raise RecoveryError("invalid backup warning")
        _exact_keys(warning, {"kind", "count"}, "warning")
        if (
            not isinstance(warning["kind"], str)
            or not _is_int(warning["count"])
            or warning["count"] < 0
        ):
            raise RecoveryError("invalid backup warning")

    return manifest


def _zip_mode(info: zipfile.ZipInfo) -> int:
    return stat.S_IFMT(info.external_attr >> 16)


def _validate_zip_info(
    info: zipfile.ZipInfo, *, limits: ArchiveLimits, allow_directory: bool
) -> None:
    if info.flag_bits & 0x1:
        raise RecoveryError("encrypted ZIP members are not supported")
    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise RecoveryError("unsupported ZIP compression method")
    mode = _zip_mode(info)
    if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise RecoveryError(f"ZIP member is a link or special file: {info.filename}")
    if info.is_dir() and not allow_directory:
        raise RecoveryError("v1 backups must not contain ZIP directory members")
    if info.file_size < 0 or info.file_size > limits.max_file_bytes:
        raise RecoveryError(f"ZIP member is too large: {info.filename}")
    if info.file_size >= limits.ratio_check_min_bytes:
        ratio = info.file_size / max(info.compress_size, 1)
        if ratio > limits.max_compression_ratio:
            raise RecoveryError(f"ZIP member compression ratio is unsafe: {info.filename}")


def _zip_inventory(
    zf: zipfile.ZipFile, *, limits: ArchiveLimits, legacy: bool
) -> dict[str, zipfile.ZipInfo]:
    infos: dict[str, zipfile.ZipInfo] = {}
    portable = {}
    total_size = 0
    total_compressed = 0
    for info in zf.infolist():
        name = info.filename
        if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
            raise RecoveryError("ZIP contains an unsafe member name")
        if name in infos:
            raise RecoveryError(f"duplicate ZIP member: {name}")
        key = _portable_key(name)
        if key in portable and portable[key] != name:
            raise RecoveryError("ZIP member names collide on a portable filesystem")
        portable[key] = name
        _validate_zip_info(info, limits=limits, allow_directory=legacy)
        total_size += info.file_size
        total_compressed += info.compress_size
        if total_size > limits.max_total_bytes + limits.max_manifest_bytes:
            raise RecoveryError("ZIP extracted size exceeds the configured limit")
        infos[name] = info
        if len(infos) > limits.max_files + 1:
            raise RecoveryError("ZIP contains too many members")
    if total_size >= limits.total_ratio_check_min_bytes:
        ratio = total_size / max(total_compressed, 1)
        if ratio > limits.max_compression_ratio:
            raise RecoveryError("ZIP total compression ratio is unsafe")
    return infos


def _read_manifest(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limits: ArchiveLimits) -> dict:
    if info.file_size > limits.max_manifest_bytes:
        raise RecoveryError("backup manifest is too large")
    try:
        raw = zf.read(info)
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except RecoveryError:
        raise
    except (UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise RecoveryError("backup manifest is not valid JSON") from exc
    return _validate_manifest(manifest, limits=limits)


def _preflight_space(parent: Path, extracted_bytes: int, limits: ArchiveLimits) -> None:
    margin = max(
        limits.free_space_min_margin_bytes,
        int(extracted_bytes * limits.free_space_margin_fraction),
    )
    try:
        free = shutil.disk_usage(parent).free
    except OSError as exc:
        raise RecoveryError("could not check free space for restore staging") from exc
    if free < extracted_bytes + margin:
        raise RecoveryError("not enough free space to stage this backup")


def _extract_member(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    *,
    expected_size: int,
    expected_hash: str | None,
    limits: ArchiveLimits,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with zf.open(info, "r") as source, destination.open("xb") as dest:
            while chunk := source.read(CHUNK_SIZE):
                total += len(chunk)
                if total > expected_size or total > limits.max_file_bytes:
                    raise RecoveryError(
                        f"ZIP member expanded past its declared size: {info.filename}"
                    )
                digest.update(chunk)
                dest.write(chunk)
            dest.flush()
            os.fsync(dest.fileno())
        try:
            destination.chmod(0o600)
        except OSError:
            pass
    except RecoveryError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile) as exc:
        raise RecoveryError(f"could not extract ZIP member: {info.filename}") from exc
    checksum = digest.hexdigest()
    if total != expected_size:
        raise RecoveryError(f"ZIP member size does not match: {info.filename}")
    if expected_hash is not None and checksum != expected_hash:
        raise RecoveryError(f"backup checksum does not match: {info.filename}")
    return total, checksum


def _credential_config(path: Path, *, require_sealed: bool) -> dict:
    if _is_link_like(path):
        raise RecoveryError(f"backup credential config cannot be a link: {path.name}")
    if not path.exists():
        return {}
    if not path.is_file():
        raise RecoveryError(f"backup credential config is invalid: {path.name}")
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        if require_sealed:
            raise RecoveryError(f"backup credential config is invalid: {path.name}") from exc
        return {}
    if not isinstance(value, dict):
        if require_sealed:
            raise RecoveryError(f"backup credential config is invalid: {path.name}")
        return {}
    return value


def _validate_database_dependencies(
    data_dir: Path,
    db_path: Path,
    *,
    require_sealed: bool = False,
) -> None:
    from services import secretstore

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            credentials: list[tuple[str, str]] = []
            table_columns: dict[str, set[str]] = {}
            for table, column, purpose in DATABASE_CREDENTIAL_FIELDS:
                if table not in tables:
                    continue
                have = table_columns.get(table)
                if have is None:
                    have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                    table_columns[table] = have
                if column not in have:
                    continue
                rows = conn.execute(
                    f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL AND {column} != ''"
                ).fetchall()
                credentials.extend((row[0], purpose) for row in rows)

            settings = _credential_config(data_dir / "settings.json", require_sealed=require_sealed)
            for key in SETTING_CREDENTIAL_KEYS:
                value = settings.get(key)
                if value not in (None, ""):
                    credentials.append((value, f"settings.{key}"))
            for config_name, key, purpose in CONFIG_CREDENTIAL_FIELDS:
                config = _credential_config(data_dir / config_name, require_sealed=require_sealed)
                value = config.get(key)
                if value not in (None, ""):
                    credentials.append((value, purpose))

            sealed = []
            for value, purpose in credentials:
                if isinstance(value, str) and secretstore.is_sealed(value):
                    sealed.append((value, purpose))
                elif require_sealed:
                    raise RecoveryError("backup credential is not encrypted")
            try:
                secretstore.validate_sealed_values(
                    data_dir / "secret.key",
                    sealed,
                    validate_existing=require_sealed,
                )
            except secretstore.SecretStoreError as exc:
                message = str(exc)
                if message == "secret key file is missing":
                    raise RecoveryError(
                        "backup is missing secret.key for encrypted credentials"
                    ) from exc
                if message == "secret key file cannot be a link":
                    raise RecoveryError("backup secret.key cannot be a link") from exc
                raise RecoveryError(f"backup credential validation failed: {message}") from exc

            if "push_subscriptions" in tables:
                subscribed = conn.execute("SELECT 1 FROM push_subscriptions LIMIT 1").fetchone()
                vapid_key = data_dir / "vapid.pem"
                if subscribed and (_is_link_like(vapid_key) or not vapid_key.is_file()):
                    raise RecoveryError("backup is missing vapid.pem for push subscriptions")

            if "vault_attachments" in tables:
                for (attachment_id,) in conn.execute("SELECT id FROM vault_attachments"):
                    if not isinstance(attachment_id, str) or not _SAFE_RECORD_ID.fullmatch(
                        attachment_id
                    ):
                        raise RecoveryError("backup has an invalid vault attachment id")
                    attachment = data_dir / "vault_attachments" / f"{attachment_id}.enc"
                    if _is_link_like(attachment) or not attachment.is_file():
                        raise RecoveryError("backup is missing an encrypted vault attachment")
    except RecoveryError:
        raise
    except sqlite3.Error as exc:
        raise RecoveryError("could not cross-check SQLite backup dependencies") from exc


def staging_root(data_root: Path) -> Path:
    root = data_root.expanduser().resolve()
    return root.parent / f".{root.name}-recovery"


def _write_stage_metadata(path: Path, restore_id: str, manifest: dict, *, state: str) -> None:
    value = {
        "restore_id": restore_id,
        "state": state,
        "staged_at": _now(),
        "manifest": manifest,
    }
    temp = path.parent / f".stage-{uuid.uuid4().hex}.partial"
    with temp.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    os.replace(temp, path)


def _stage_v1(
    zf: zipfile.ZipFile,
    infos: dict[str, zipfile.ZipInfo],
    partial: Path,
    *,
    limits: ArchiveLimits,
) -> dict:
    manifest_info = infos.get(MANIFEST_NAME)
    if manifest_info is None or manifest_info.is_dir():
        raise RecoveryError("backup manifest is missing")
    manifest = _read_manifest(zf, manifest_info, limits)
    expected = {MANIFEST_NAME}
    entries = {}
    for entry in manifest["files"]:
        archive_name = f"payload/{entry['storage']}/{entry['path']}"
        expected.add(archive_name)
        entries[archive_name] = entry
    if set(infos) != expected:
        missing = expected - set(infos)
        if missing:
            raise RecoveryError("backup is missing a file declared by its manifest")
        raise RecoveryError("backup contains a file not declared by its manifest")

    extracted = manifest["totals"]["bytes"]
    _preflight_space(partial.parent, extracted, limits)
    data_dir = partial / "data"
    data_dir.mkdir(parents=True, mode=0o700)
    for directory in manifest["directories"]:
        destination = data_dir / directory["path"]
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for archive_name, entry in entries.items():
        info = infos[archive_name]
        if info.is_dir() or info.file_size != entry["size"]:
            raise RecoveryError(f"ZIP member size does not match: {archive_name}")
        _extract_member(
            zf,
            info,
            data_dir / entry["path"],
            expected_size=entry["size"],
            expected_hash=entry["sha256"],
            limits=limits,
        )

    actual_db = _database_info(data_dir / "aide.db", require_application_id=True)
    if actual_db["applied_migrations"] != manifest["database"]["applied_migrations"]:
        raise RecoveryError("database migrations do not match the backup manifest")
    _validate_migrations(actual_db["applied_migrations"])
    _validate_database_dependencies(data_dir, data_dir / "aide.db")
    return manifest


def _legacy_member_path(name: str, limits: ArchiveLimits) -> str:
    logical = name[:-1] if name.endswith("/") else name
    return validate_relative_path(logical, limits=limits)


def _legacy_locations(paths: set[str], data_dir: Path) -> list[dict]:
    locations = [
        {
            "role": "data",
            "included": True,
            "storage": "data",
            "subpath": "",
            "policy": "legacy",
        }
    ]
    for role in ("vault", "files", "photos"):
        included = any(path == role or path.startswith(f"{role}/") for path in paths)
        locations.append(
            {
                "role": role,
                "included": included,
                "storage": "data" if included else None,
                "subpath": role if included else None,
                "policy": "legacy" if included else "not-present",
            }
        )
    locations.extend(
        _other_location_policies(
            _read_settings(data_dir),
            webdav_config=_credential_config(
                data_dir / "webdav_backup.json",
                require_sealed=False,
            ),
            s3_config=_credential_config(
                data_dir / "s3_backup.json",
                require_sealed=False,
            ),
        )
    )
    return locations


def _stage_legacy(
    zf: zipfile.ZipFile,
    infos: dict[str, zipfile.ZipInfo],
    partial: Path,
    *,
    limits: ArchiveLimits,
) -> dict:
    files = []
    directories = []
    for name, info in infos.items():
        logical = _legacy_member_path(name, limits)
        if info.is_dir():
            directories.append(logical)
        else:
            files.append((logical, info))
    paths = sorted(path for path, _ in files)
    directories = sorted(set(directories))
    if len(files) + len(directories) > limits.max_files:
        raise RecoveryError("backup contains too many files")
    if paths.count("aide.db") != 1:
        raise RecoveryError("legacy backup must contain one aide.db")
    _check_path_collisions(paths, directories)

    declared_total = sum(info.file_size for _, info in files)
    if declared_total > limits.max_total_bytes:
        raise RecoveryError("backup extracted size exceeds the configured limit")
    _preflight_space(partial.parent, declared_total, limits)
    data_dir = partial / "data"
    data_dir.mkdir(parents=True, mode=0o700)
    for directory in directories:
        (data_dir / directory).mkdir(parents=True, exist_ok=True, mode=0o700)

    entries = []
    total = 0
    for logical, info in sorted(files, key=lambda item: item[0]):
        size, checksum = _extract_member(
            zf,
            info,
            data_dir / logical,
            expected_size=info.file_size,
            expected_hash=None,
            limits=limits,
        )
        total += size
        entries.append({"storage": "data", "path": logical, "size": size, "sha256": checksum})

    _database_info(data_dir / "aide.db", require_application_id=False)
    try:
        with closing(sqlite3.connect(data_dir / "aide.db")) as conn:
            conn.execute(f"PRAGMA application_id = {SQLITE_APPLICATION_ID}")
            conn.commit()
    except sqlite3.Error as exc:
        raise RecoveryError("could not normalize the legacy SQLite database") from exc

    normalized_db = _database_info(data_dir / "aide.db", require_application_id=True)
    _validate_migrations(normalized_db["applied_migrations"])
    _validate_database_dependencies(data_dir, data_dir / "aide.db")
    db_entry = next(entry for entry in entries if entry["path"] == "aide.db")
    db_size, db_hash = _hash_path(data_dir / "aide.db")
    total += db_size - db_entry["size"]
    db_entry["size"] = db_size
    db_entry["sha256"] = db_hash

    producer = build_info()
    manifest = {
        "format": ARCHIVE_FORMAT,
        "format_version": ARCHIVE_VERSION,
        "source_format_version": 0,
        "restore_compatibility": RECOVERY_COMPATIBILITY,
        "created_at": _now(),
        "producer": {
            "name": producer["name"],
            "version": producer["version"],
            "build_id": producer["build_id"],
            "migration_head": current_schema_version(),
        },
        "database": {
            "storage": "data",
            "path": "aide.db",
            "application_id": SQLITE_APPLICATION_ID,
            "applied_migrations": normalized_db["applied_migrations"],
        },
        "data_classes": [dict(item) for item in DATA_CLASS_POLICIES],
        "storages": [{"id": "data", "source_kind": "alles_data"}],
        "locations": _legacy_locations(set(paths), data_dir),
        "files": entries,
        "directories": [{"storage": "data", "path": path} for path in directories],
        "totals": {"files": len(entries), "bytes": total},
        "warnings": [],
    }
    return _validate_manifest(manifest, limits=limits)


def stage_recovery_archive(
    archive_path: Path,
    data_root: Path,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> StagedRecovery:
    """Validate and extract an archive beside live data, never into it."""
    raw_archive = archive_path.expanduser()
    if _is_link_like(raw_archive):
        raise RecoveryError("backup archive cannot be a link")
    archive = raw_archive.resolve()
    live = data_root.expanduser().resolve()
    if not archive.is_file():
        raise RecoveryError("backup archive does not exist")
    try:
        archive_size = archive.stat().st_size
    except OSError as exc:
        raise RecoveryError("could not inspect backup archive") from exc
    if archive_size <= 0:
        raise RecoveryError("backup archive is empty")
    if archive_size > limits.max_archive_bytes:
        raise RecoveryError("backup archive exceeds the configured size limit")

    base = staging_root(live)
    staged_root = base / "staged"
    staged_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    restore_id = uuid.uuid4().hex
    partial = staged_root / f".{restore_id}.partial"
    final = staged_root / restore_id
    partial.mkdir(mode=0o700)

    try:
        with zipfile.ZipFile(archive) as zf:
            raw_names = [info.filename for info in zf.infolist()]
            legacy = MANIFEST_NAME not in raw_names
            infos = _zip_inventory(zf, limits=limits, legacy=legacy)
            if legacy:
                manifest = _stage_legacy(zf, infos, partial, limits=limits)
            else:
                manifest = _stage_v1(zf, infos, partial, limits=limits)
        _write_stage_metadata(partial / "stage.json", restore_id, manifest, state="staged")
        os.replace(partial, final)
    except RecoveryError:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        shutil.rmtree(partial, ignore_errors=True)
        raise RecoveryError("backup ZIP is invalid or incomplete") from exc
    except Exception:
        shutil.rmtree(partial, ignore_errors=True)
        raise

    return StagedRecovery(
        restore_id=restore_id,
        root=final,
        data_dir=final / "data",
        manifest=manifest,
        state="staged",
    )


def _valid_restore_id(restore_id: str) -> str:
    if not isinstance(restore_id, str) or not _RESTORE_ID.fullmatch(restore_id):
        raise RecoveryError("invalid restore id")
    return restore_id


def get_staged_recovery(data_root: Path, restore_id: str) -> StagedRecovery:
    restore_id = _valid_restore_id(restore_id)
    root = staging_root(data_root) / "staged" / restore_id
    metadata_path = root / "stage.json"
    data_dir = root / "data"
    if (
        not root.is_dir()
        or not metadata_path.is_file()
        or not data_dir.is_dir()
        or _is_link_like(root)
        or _is_link_like(metadata_path)
        or _is_link_like(data_dir)
    ):
        raise RecoveryError("staged restore was not found")
    try:
        if metadata_path.stat().st_size > DEFAULT_LIMITS.max_manifest_bytes + 1024 * 1024:
            raise RecoveryError("staged restore metadata is too large")
        metadata = json.loads(
            metadata_path.read_text("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except RecoveryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("staged restore metadata is invalid") from exc
    if not isinstance(metadata, dict):
        raise RecoveryError("staged restore metadata is invalid")
    _exact_keys(metadata, {"restore_id", "state", "staged_at", "manifest"}, "stage metadata")
    if metadata["restore_id"] != restore_id or metadata["state"] not in {
        "staged",
        "prepared",
    }:
        raise RecoveryError("staged restore metadata does not match")
    manifest = _validate_manifest(metadata["manifest"], limits=DEFAULT_LIMITS)
    return StagedRecovery(
        restore_id=restore_id,
        root=root,
        data_dir=data_dir,
        manifest=manifest,
        state=metadata["state"],
    )


def verify_staged_recovery(data_root: Path, restore_id: str) -> StagedRecovery:
    """Re-check every staged byte before preflight or a live swap."""
    staged = get_staged_recovery(data_root, restore_id)
    sources, directories, warnings = _collect_data_tree(
        staged.data_dir, excluded_root=None, limits=DEFAULT_LIMITS
    )
    if warnings:
        raise RecoveryError("staged restore contains a link or special file")
    database = staged.data_dir / "aide.db"
    if _is_link_like(database) or not database.is_file():
        raise RecoveryError("staged restore is missing aide.db")
    sources.append(("aide.db", database))
    sources.sort(key=lambda item: item[0])
    directories = sorted(set(directories))

    expected_files = {entry["path"]: entry for entry in staged.manifest["files"]}
    actual_paths = [path for path, _ in sources]
    if set(actual_paths) != set(expected_files):
        raise RecoveryError("staged restore files no longer match its manifest")
    expected_directories = {entry["path"] for entry in staged.manifest["directories"]}
    if set(directories) != expected_directories:
        raise RecoveryError("staged restore directories no longer match its manifest")
    _check_path_collisions(actual_paths, directories)

    total = 0
    for relative, source in sources:
        size, checksum = _hash_path(source)
        expected = expected_files[relative]
        if size != expected["size"] or checksum != expected["sha256"]:
            raise RecoveryError(f"staged restore checksum does not match: {relative}")
        total += size
    if total != staged.manifest["totals"]["bytes"]:
        raise RecoveryError("staged restore totals no longer match")

    db_info = _database_info(database, require_application_id=True)
    if db_info["applied_migrations"] != staged.manifest["database"]["applied_migrations"]:
        raise RecoveryError("staged database migrations no longer match")
    _validate_migrations(db_info["applied_migrations"])
    _validate_database_dependencies(staged.data_dir, database)
    return staged


def refresh_prepared_recovery(data_root: Path, restore_id: str) -> StagedRecovery:
    """Record the trusted output of two successful staged preflight boots."""
    staged = get_staged_recovery(data_root, restore_id)
    database = staged.data_dir / "aide.db"
    consolidated = staged.data_dir / f".aide-{uuid.uuid4().hex}.snapshot"
    try:
        # The preflight server uses WAL. Never delete its sidecars directly: committed migrations
        # may still live there. A fresh online snapshot folds main DB + WAL into one atomic file.
        snapshot_sqlite(database, consolidated)
        try:
            consolidated.chmod(0o600)
        except OSError:
            pass
        os.replace(consolidated, database)
    finally:
        consolidated.unlink(missing_ok=True)
    for sidecar in ("aide.db-wal", "aide.db-shm", "aide.db-journal"):
        (staged.data_dir / sidecar).unlink(missing_ok=True)

    sources, directories, warnings = _collect_data_tree(
        staged.data_dir, excluded_root=None, limits=DEFAULT_LIMITS
    )
    if warnings:
        raise RecoveryError("prepared restore contains a link or special file")
    if _is_link_like(database) or not database.is_file():
        raise RecoveryError("prepared restore is missing aide.db")
    sources.append(("aide.db", database))
    sources.sort(key=lambda item: item[0])
    directories = sorted(set(directories))
    if len(sources) + len(directories) > DEFAULT_LIMITS.max_files:
        raise RecoveryError("prepared restore contains too many paths")
    _check_path_collisions([path for path, _ in sources], directories)

    entries = []
    total = 0
    for relative, source in sources:
        size, checksum = _hash_path(source)
        if size > DEFAULT_LIMITS.max_file_bytes:
            raise RecoveryError(f"prepared restore file is too large: {relative}")
        total += size
        if total > DEFAULT_LIMITS.max_total_bytes:
            raise RecoveryError("prepared restore is too large")
        entries.append({"storage": "data", "path": relative, "size": size, "sha256": checksum})

    db_info = _database_info(database, require_application_id=True)
    _validate_migrations(db_info["applied_migrations"])
    applied = db_info["applied_migrations"]
    if not applied or applied[-1]["version"] != current_schema_version():
        raise RecoveryError("staged preflight did not reach the current schema")
    _validate_database_dependencies(staged.data_dir, database)

    manifest = json.loads(json.dumps(staged.manifest))
    producer = build_info()
    manifest["producer"] = {
        "name": producer["name"],
        "version": producer["version"],
        "build_id": producer["build_id"],
        "migration_head": current_schema_version(),
    }
    manifest["database"] = {
        "storage": "data",
        "path": "aide.db",
        "application_id": SQLITE_APPLICATION_ID,
        "applied_migrations": applied,
    }
    manifest["files"] = entries
    manifest["directories"] = [{"storage": "data", "path": path} for path in directories]
    manifest["totals"] = {"files": len(entries), "bytes": total}
    manifest["warnings"] = []
    manifest = _validate_manifest(manifest, limits=DEFAULT_LIMITS)
    _write_stage_metadata(staged.root / "stage.json", restore_id, manifest, state="prepared")
    return StagedRecovery(
        restore_id=restore_id,
        root=staged.root,
        data_dir=staged.data_dir,
        manifest=manifest,
        state="prepared",
    )


def discard_staged_recovery(data_root: Path, restore_id: str) -> None:
    staged = get_staged_recovery(data_root, restore_id)
    shutil.rmtree(staged.root)


def discard_consumed_staged_recovery(data_root: Path, restore_id: str) -> None:
    """Remove stage metadata only after its data directory was atomically consumed."""
    restore_id = _valid_restore_id(restore_id)
    root = staging_root(data_root) / "staged" / restore_id
    metadata_path = root / "stage.json"
    data_path = root / "data"
    if (
        not root.is_dir()
        or not metadata_path.is_file()
        or data_path.exists()
        or _is_link_like(root)
        or _is_link_like(metadata_path)
    ):
        raise RecoveryError("consumed restore stage was not found")
    try:
        metadata = json.loads(
            metadata_path.read_text("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("consumed restore stage metadata is invalid") from exc
    if not isinstance(metadata, dict) or metadata.get("restore_id") != restore_id:
        raise RecoveryError("consumed restore stage metadata does not match")
    shutil.rmtree(root)
