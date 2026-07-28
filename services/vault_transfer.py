"""Verified, restart-safe Markdown vault move and relink operations."""

import hashlib
import os
import re
import shutil
import stat
import tempfile
import threading
import uuid
from pathlib import Path

from core.settings import data_dir, load_settings, save_settings
from services import document_safety, file_operations, vault_md

_OPERATION_ID = re.compile(r"^[0-9a-f]{32}$")
_SPACE_RESERVE = 16 * 1024 * 1024
_TRANSFER_LOCK = threading.RLock()


class VaultTransferError(RuntimeError):
    pass


class InsufficientSpace(VaultTransferError):
    pass


class TransferConflict(VaultTransferError):
    pass


def _operation_root() -> Path:
    return document_safety._state_dir("vault-transfers")


def _operation_dir(operation_id: str) -> Path:
    if not _OPERATION_ID.fullmatch(operation_id or ""):
        raise ValueError("invalid vault transfer id")
    return _operation_root() / operation_id


def _manifest(operation_id: str) -> tuple[Path, dict]:
    directory = _operation_dir(operation_id)
    return directory, document_safety._read_json(directory / "manifest.json")


def _write_manifest(directory: Path, manifest: dict) -> None:
    manifest["updated_at"] = document_safety._now()
    document_safety._write_json(directory / "manifest.json", manifest)


def _directory_identity(path: Path) -> dict:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise TransferConflict("vault staging directory identity is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise TransferConflict("vault staging directory identity changed")
    return {"device": metadata.st_dev, "inode": metadata.st_ino}


def _same_directory_identity(path: Path, expected: object) -> bool:
    if not isinstance(expected, dict):
        return False
    if not isinstance(expected.get("device"), int) or not isinstance(expected.get("inode"), int):
        return False
    try:
        return _directory_identity(path) == expected
    except TransferConflict:
        return False


def _normalise_destination(value: str) -> Path:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("destination is required")
    destination = Path(raw).expanduser()
    if not destination.is_absolute():
        raise ValueError("vault destination must be an absolute path")
    return destination.resolve(strict=False)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path) -> dict:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(str(root))
    directories = []
    files = []
    total_size = 0
    for path in sorted(root.rglob("*"), key=lambda item: str(item.relative_to(root))):
        relative = str(path.relative_to(root)).replace("\\", "/")
        if path.is_symlink():
            raise TransferConflict(f"vault symlink is unsupported: {relative}")
        if path.is_dir():
            directories.append(relative)
            continue
        if not path.is_file():
            raise TransferConflict(f"vault contains an unsupported filesystem entry: {relative}")
        size = path.stat().st_size
        files.append({"path": relative, "size": size, "hash": _hash_file(path)})
        total_size += size
    return {
        "directories": directories,
        "files": files,
        "total_size": total_size,
        "tree_hash": _inventory_hash(directories, files),
    }


def _inventory_hash(directories: list[str], files: list[dict]) -> str:
    digest = hashlib.sha256()
    for directory in directories:
        digest.update(b"d\0")
        digest.update(directory.encode("utf-8"))
        digest.update(b"\0")
    for item in files:
        digest.update(b"f\0")
        digest.update(item["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["size"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(item["hash"].encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _same_inventory(left: dict, right: dict) -> bool:
    return (
        left.get("tree_hash") == right.get("tree_hash")
        and left.get("total_size") == right.get("total_size")
        and left.get("files") == right.get("files")
        and left.get("directories") == right.get("directories")
    )


def _available_bytes(path: Path) -> int:
    probe = path.expanduser().resolve(strict=False)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _require_space(path: Path, total_size: int, label: str) -> None:
    required = total_size + _SPACE_RESERVE
    if _available_bytes(path) < required:
        raise InsufficientSpace(f"not enough free space for the verified {label} copy")


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        try:
            os.chmod(temporary, source.stat().st_mode)
        except OSError:
            pass
        os.replace(temporary, destination)
        document_safety._fsync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_snapshot(source: Path, destination: Path, inventory: dict, *, on_create=None) -> None:
    if destination.exists():
        raise FileExistsError(str(destination))
    destination.mkdir(parents=True, mode=0o700)
    identity = _directory_identity(destination)
    directory_modes: list[tuple[Path, int]] = []
    try:
        source_mode = stat.S_IMODE(source.stat(follow_symlinks=False).st_mode)
        if on_create is not None:
            on_create(identity)
        for relative in inventory["directories"]:
            source_directory = source / relative
            metadata = source_directory.stat(follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode):
                raise TransferConflict(f"source changed while copying: {relative}")
            destination_directory = destination / relative
            destination_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory_modes.append((destination_directory, stat.S_IMODE(metadata.st_mode)))
        for item in inventory["files"]:
            source_file = source / item["path"]
            if source_file.is_symlink() or not source_file.is_file():
                raise TransferConflict(f"source changed while copying: {item['path']}")
            if source_file.stat().st_size != item["size"]:
                raise TransferConflict(f"source changed while copying: {item['path']}")
            _copy_file(source_file, destination / item["path"])
    except Exception:
        if _same_directory_identity(destination, identity):
            shutil.rmtree(destination, ignore_errors=True)
        raise
    if not _same_directory_identity(destination, identity):
        raise TransferConflict("vault staging directory identity changed during copying")
    copied_inventory = _inventory(destination)
    if not _same_directory_identity(destination, identity):
        raise TransferConflict("vault staging directory identity changed during verification")
    if not _same_inventory(copied_inventory, inventory):
        shutil.rmtree(destination, ignore_errors=True)
        raise TransferConflict("copied vault does not match its verified manifest")
    try:
        for directory, mode in sorted(
            directory_modes,
            key=lambda item: len(item[0].parts),
            reverse=True,
        ):
            os.chmod(directory, mode, follow_symlinks=False)
        os.chmod(destination, source_mode, follow_symlinks=False)
    except Exception:
        try:
            os.chmod(destination, 0o700, follow_symlinks=False)
        except OSError:
            pass
        for directory, _mode in directory_modes:
            try:
                os.chmod(directory, 0o700, follow_symlinks=False)
            except OSError:
                pass
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _active_vault() -> Path:
    configured = load_settings().get("vault_dir")
    return Path(configured or (data_dir() / "vault")).expanduser().resolve()


def _set_active_vault(path: Path) -> None:
    destination = path.expanduser().resolve()
    save_settings({"vault_dir": str(destination)})
    if _active_vault() != destination:
        raise VaultTransferError("vault setting could not be verified after switching")


def _source_is_safe_for_state(source: Path) -> None:
    state = document_safety._state_root().expanduser().resolve(strict=False)
    if _is_within(state, source):
        raise TransferConflict("the private recovery directory cannot live inside the vault")


def _new_operation(
    kind: str,
    destination: Path,
    destination_inventory: dict | None = None,
    *,
    source: Path | None = None,
) -> dict:
    source = (source or vault_md.root_dir()).expanduser().resolve()
    _source_is_safe_for_state(source)
    if source == destination:
        raise ValueError("the selected vault is already active")
    if _is_within(destination, source) or _is_within(source, destination):
        raise ValueError("the old and new vault locations cannot contain each other")

    source_inventory = _inventory(source)
    operation_id = uuid.uuid4().hex
    directory = _operation_dir(operation_id)
    vault_md.root_dir()
    previous_active = _active_vault()
    previous_active_inventory = (
        source_inventory if previous_active == source else _inventory(previous_active)
    )
    manifest = {
        "id": operation_id,
        "kind": kind,
        "state": "prepared",
        "source": str(source),
        "destination": str(destination),
        "source_inventory": source_inventory,
        "destination_inventory": destination_inventory,
        "previous_active": str(previous_active),
        "previous_active_inventory": previous_active_inventory,
        "old_deleted": False,
        "delete_confirmation": f"delete old vault {source.name}",
        "created_at": document_safety._now(),
    }
    _write_manifest(directory, manifest)
    _ensure_backup(directory, manifest)
    return manifest


def _ensure_backup(directory: Path, manifest: dict) -> None:
    backup = directory / "backup"
    source = Path(manifest["source"])
    expected = manifest["source_inventory"]
    if backup.exists():
        try:
            if _same_inventory(_inventory(backup), expected):
                manifest["state"] = "backed_up"
                _write_manifest(directory, manifest)
                return
        except (FileNotFoundError, TransferConflict):
            pass
        shutil.rmtree(backup, ignore_errors=True)

    if not _same_inventory(_inventory(source), expected):
        raise TransferConflict("source vault changed before its recovery copy completed")
    _require_space(backup.parent, expected["total_size"], "backup")
    _copy_snapshot(source, backup, expected)
    if not _same_inventory(_inventory(source), expected):
        raise TransferConflict("source vault changed while its recovery copy was being made")
    manifest["state"] = "backed_up"
    _write_manifest(directory, manifest)


def prepare_vault_move(destination: str) -> dict:
    with _TRANSFER_LOCK:
        return _prepare_vault_move(destination)


def _prepare_vault_move(destination: str) -> dict:
    target = _normalise_destination(destination)
    if target.exists():
        raise FileExistsError(str(target))
    return _new_operation("move", target)


def prepare_vault_relink(destination: str) -> dict:
    with _TRANSFER_LOCK:
        return _prepare_vault_relink(destination)


def _prepare_vault_relink(destination: str) -> dict:
    target = _normalise_destination(destination)
    if not target.is_dir():
        raise FileNotFoundError(str(target))
    before = _inventory(target)
    after = _inventory(target)
    if not _same_inventory(before, after):
        raise TransferConflict("selected vault changed while it was being verified")
    return _new_operation("relink", target, destination_inventory=before)


def _managed_import_destination(name: str) -> Path:
    clean = re.sub(r"[^a-zA-Z0-9._ -]+", "-", str(name or "").strip()).strip(" .-")
    if not clean or clean in {".", ".."}:
        raise ValueError("vault name is required")
    root = (data_dir() / "vaults").resolve(strict=False)
    destination = (root / clean[:80]).resolve(strict=False)
    if destination.parent != root:
        raise ValueError("vault name is invalid")
    return destination


def preview_external_vault(source: str, name: str) -> dict:
    selected = _normalise_destination(source)
    if not selected.is_dir():
        raise FileNotFoundError(str(selected))
    before = _inventory(selected)
    after = _inventory(selected)
    if not _same_inventory(before, after):
        raise TransferConflict("selected vault changed while it was being reviewed")
    destination = _managed_import_destination(name)
    required = before["total_size"] * 2 + (_SPACE_RESERVE * 2)
    available = _available_bytes(destination.parent)
    return {
        "source": str(selected),
        "destination": str(destination),
        "source_files": len(before["files"]),
        "source_bytes": before["total_size"],
        "required_bytes": required,
        "available_bytes": available,
        "conflicts": [destination.name] if destination.exists() else [],
        "can_import": not destination.exists() and available >= required,
        "links_preserved": True,
    }


def prepare_vault_import(source: str, name: str) -> dict:
    with _TRANSFER_LOCK:
        preview = preview_external_vault(source, name)
        if preview["conflicts"]:
            raise FileExistsError(preview["destination"])
        if not preview["can_import"]:
            raise InsufficientSpace("not enough free space for the verified destination and rollback snapshot")
        return _new_operation(
            "import",
            Path(preview["destination"]),
            source=Path(preview["source"]),
        )


def import_external_vault(source: str, name: str, *, move: bool = False) -> dict:
    with _TRANSFER_LOCK:
        manifest = prepare_vault_import(source, name)
        manifest = _resume_vault_transfer(manifest["id"])
        if move:
            manifest = delete_old_vault(manifest["id"], manifest["delete_confirmation"])
        return manifest


def _install_move(directory: Path, manifest: dict) -> None:
    destination = Path(manifest["destination"])
    stage = destination.parent / f".{destination.name}.alles-stage-{manifest['id']}"
    expected = manifest["source_inventory"]

    if destination.exists():
        if not destination.is_dir() or not _same_inventory(_inventory(destination), expected):
            raise TransferConflict("destination exists but does not match the staged vault")
        manifest.pop("stage_identity", None)
        manifest["state"] = "installed"
        _write_manifest(directory, manifest)
        return

    if stage.exists():
        stage_identity = manifest.get("stage_identity")
        if stage_identity and not _same_directory_identity(stage, stage_identity):
            raise TransferConflict("vault staging directory identity changed")
        if not stage.is_dir() or not _same_inventory(_inventory(stage), expected):
            if not stage_identity:
                raise TransferConflict("vault staging directory is incomplete or changed")
            shutil.rmtree(stage)
            document_safety._fsync_directory(stage.parent)
            manifest.pop("stage_identity", None)
            _write_manifest(directory, manifest)
        elif not stage_identity:
            # A complete stage from an older release can be adopted only after
            # binding its no-follow identity to a second exact inventory check.
            stage_identity = _directory_identity(stage)
            if not _same_inventory(_inventory(stage), expected) or not _same_directory_identity(
                stage, stage_identity
            ):
                raise TransferConflict("vault staging directory identity changed")
            manifest["stage_identity"] = stage_identity
            _write_manifest(directory, manifest)
    if not stage.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        _require_space(destination.parent, expected["total_size"], "destination")

        def remember_stage(identity):
            manifest["stage_identity"] = identity
            _write_manifest(directory, manifest)

        _copy_snapshot(directory / "backup", stage, expected, on_create=remember_stage)
        manifest["state"] = "staged"
        _write_manifest(directory, manifest)

    if not _same_inventory(_inventory(Path(manifest["source"])), expected):
        raise TransferConflict("source vault changed before the destination was installed")
    if not _same_directory_identity(stage, manifest.get("stage_identity")):
        raise TransferConflict("vault staging directory identity changed before publication")
    try:
        file_operations._rename_no_replace(stage, destination)
    except file_operations.FileOperationError as exc:
        raise TransferConflict("destination appeared while the vault was being installed") from exc
    document_safety._fsync_directory(destination.parent)
    if not _same_inventory(_inventory(destination), expected):
        raise TransferConflict("installed vault failed final verification")
    manifest.pop("stage_identity", None)
    manifest["state"] = "installed"
    _write_manifest(directory, manifest)


def resume_vault_transfer(operation_id: str) -> dict:
    with _TRANSFER_LOCK:
        return _resume_vault_transfer(operation_id)


def _resume_vault_transfer(operation_id: str) -> dict:
    directory, manifest = _manifest(operation_id)
    if manifest.get("state") == "complete":
        return manifest
    if manifest.get("state") == "rolled_back":
        raise TransferConflict("a rolled-back vault transfer cannot be resumed")

    _ensure_backup(directory, manifest)
    source = Path(manifest["source"])
    destination = Path(manifest["destination"])
    allowed_active = {source, destination}
    if manifest.get("kind") == "import":
        allowed_active.add(Path(manifest["previous_active"]))
    if _active_vault() not in allowed_active:
        raise TransferConflict("another vault transfer changed the active vault")
    expected_source = manifest["source_inventory"]
    if not _same_inventory(_inventory(source), expected_source):
        raise TransferConflict("source vault changed after the transfer was prepared")

    if manifest["kind"] in {"move", "import"}:
        _install_move(directory, manifest)
        expected_destination = expected_source
    elif manifest["kind"] == "relink":
        expected_destination = manifest["destination_inventory"]
        if not _same_inventory(_inventory(destination), expected_destination):
            raise TransferConflict("selected vault changed before relinking")
        manifest["state"] = "installed"
        _write_manifest(directory, manifest)
    else:
        raise TransferConflict("unknown vault transfer kind")

    _set_active_vault(destination)
    manifest["state"] = "switched"
    _write_manifest(directory, manifest)
    if _active_vault() != destination:
        raise VaultTransferError("active vault does not match the verified destination")
    if manifest["kind"] in {"move", "import"} and not _same_inventory(_inventory(source), expected_source):
        _set_active_vault(Path(manifest["previous_active"]))
        raise TransferConflict("source vault changed during the final vault switch")
    if not _same_inventory(_inventory(destination), expected_destination):
        _set_active_vault(source)
        raise TransferConflict("destination changed during the final vault switch")
    manifest["state"] = "complete"
    _write_manifest(directory, manifest)
    return manifest


def move_vault(destination: str) -> dict:
    with _TRANSFER_LOCK:
        manifest = _prepare_vault_move(destination)
        return _resume_vault_transfer(manifest["id"])


def relink_vault(destination: str) -> dict:
    with _TRANSFER_LOCK:
        manifest = _prepare_vault_relink(destination)
        return _resume_vault_transfer(manifest["id"])


def rollback_vault_transfer(operation_id: str) -> dict:
    with _TRANSFER_LOCK:
        return _rollback_vault_transfer(operation_id)


def _rollback_vault_transfer(operation_id: str) -> dict:
    directory, manifest = _manifest(operation_id)
    if manifest.get("state") == "rolled_back":
        return manifest
    source = Path(manifest["source"])
    destination = Path(manifest["destination"])
    expected = manifest["source_inventory"]
    state = manifest.get("state")
    if state in {"switched", "complete"}:
        expected_destination = expected if manifest["kind"] in {"move", "import"} else manifest["destination_inventory"]
        if _active_vault() != destination:
            raise TransferConflict("this transfer destination is no longer the active vault")
        if not _same_inventory(_inventory(destination), expected_destination):
            raise TransferConflict("active destination changed; rollback was not applied")
    elif _active_vault() not in {source, Path(manifest.get("previous_active") or source)}:
        raise TransferConflict("another vault transfer changed the active vault")
    backup = directory / "backup"
    if not _same_inventory(_inventory(backup), expected):
        raise TransferConflict("private vault recovery copy is damaged")

    if source.exists():
        if not source.is_dir() or not _same_inventory(_inventory(source), expected):
            raise TransferConflict("old vault changed; rollback will not overwrite it")
    else:
        stage = source.parent / f".{source.name}.alles-rollback-{manifest['id']}"
        if stage.exists():
            if not _same_directory_identity(stage, manifest.get("rollback_stage_identity")):
                raise TransferConflict("vault rollback staging directory identity changed")
            shutil.rmtree(stage)
            manifest.pop("rollback_stage_identity", None)
            _write_manifest(directory, manifest)
        _require_space(source.parent, expected["total_size"], "rollback")

        def remember_rollback_stage(identity):
            manifest["rollback_stage_identity"] = identity
            _write_manifest(directory, manifest)

        _copy_snapshot(backup, stage, expected, on_create=remember_rollback_stage)
        source.parent.mkdir(parents=True, exist_ok=True)
        if not _same_directory_identity(stage, manifest.get("rollback_stage_identity")):
            raise TransferConflict("vault rollback staging directory identity changed")
        try:
            file_operations._rename_no_replace(stage, source)
        except file_operations.FileOperationError as exc:
            raise TransferConflict("old vault location appeared during rollback") from exc
        document_safety._fsync_directory(source.parent)
        manifest.pop("rollback_stage_identity", None)
        _write_manifest(directory, manifest)

    rollback_target = Path(manifest.get("previous_active") or source) if manifest["kind"] == "import" else source
    rollback_inventory = manifest.get("previous_active_inventory") if manifest["kind"] == "import" else expected
    if not rollback_target.is_dir() or not _same_inventory(_inventory(rollback_target), rollback_inventory):
        raise TransferConflict("previous active vault changed; rollback was not applied")
    _set_active_vault(rollback_target)
    if _active_vault() != rollback_target or not _same_inventory(_inventory(source), expected):
        raise TransferConflict("old vault could not be verified after rollback")
    manifest["state"] = "rolled_back"
    if manifest.get("old_deleted"):
        manifest["old_deleted"] = False
        manifest["old_restored_at"] = document_safety._now()
    _write_manifest(directory, manifest)
    return manifest


def delete_old_vault(operation_id: str, confirmation: str) -> dict:
    with _TRANSFER_LOCK:
        directory, manifest = _manifest(operation_id)
        if manifest.get("state") != "complete":
            raise TransferConflict("vault transfer must finish before deleting the old location")
        if confirmation != manifest.get("delete_confirmation"):
            raise ValueError("old-vault deletion confirmation does not match")
        if manifest.get("old_deleted"):
            return manifest
        source = Path(manifest["source"])
        destination = Path(manifest["destination"])
        expected_source = manifest["source_inventory"]
        expected_destination = expected_source if manifest["kind"] in {"move", "import"} else manifest["destination_inventory"]
        if _active_vault() != destination:
            raise TransferConflict("the verified destination is not the active vault")
        if not _same_inventory(_inventory(destination), expected_destination):
            raise TransferConflict("active destination changed; old vault was not deleted")
        if not _same_inventory(_inventory(directory / "backup"), expected_source):
            raise TransferConflict("private recovery copy is damaged; old vault was not deleted")

        quarantine = source.with_name(f".{source.name}.alles-delete-{operation_id}")
        if source.exists() and quarantine.exists():
            raise TransferConflict("old vault deletion has two preserved source trees")
        if source.exists():
            if not source.is_dir() or not _same_inventory(_inventory(source), expected_source):
                raise TransferConflict("old vault changed; it was not deleted")
            quarantine_identity = _directory_identity(source)
            manifest["delete_quarantine"] = str(quarantine)
            manifest["delete_quarantine_identity"] = quarantine_identity
            manifest["delete_state"] = "prepared"
            _write_manifest(directory, manifest)
            os.rename(source, quarantine)
            document_safety._fsync_directory(source.parent)
            if not _same_directory_identity(quarantine, quarantine_identity):
                raise TransferConflict("old vault deletion quarantine identity changed")
            manifest["delete_state"] = "quarantined"
            _write_manifest(directory, manifest)
        elif not quarantine.exists():
            if manifest.get("delete_state") not in {"quarantined", "deleting"}:
                raise TransferConflict("old vault is missing; deletion was not verified")
            manifest["old_deleted"] = True
            manifest["old_deleted_at"] = document_safety._now()
            manifest.pop("delete_quarantine", None)
            manifest.pop("delete_quarantine_identity", None)
            manifest.pop("delete_state", None)
            _write_manifest(directory, manifest)
            return manifest

        quarantine_identity = manifest.get("delete_quarantine_identity")
        if not _same_directory_identity(quarantine, quarantine_identity):
            raise TransferConflict("old vault deletion quarantine identity changed")

        if manifest.get("delete_state") != "deleting":
            try:
                if source.exists() or not quarantine.is_dir():
                    raise TransferConflict(
                        "old vault changed during deletion; preserved both trees"
                    )
                if not _same_inventory(_inventory(quarantine), expected_source):
                    raise TransferConflict("old vault changed during deletion; it was restored")
            except Exception:
                if (
                    not source.exists()
                    and quarantine.exists()
                    and _same_directory_identity(quarantine, quarantine_identity)
                ):
                    os.rename(quarantine, source)
                    document_safety._fsync_directory(source.parent)
                    manifest.pop("delete_quarantine", None)
                    manifest.pop("delete_quarantine_identity", None)
                    manifest.pop("delete_state", None)
                    _write_manifest(directory, manifest)
                raise
            # Once recursive removal starts, the quarantine may be incomplete.
            # Persist that boundary so a retry finishes deleting it instead of
            # restoring a partial tree as though it were the original vault.
            manifest["delete_state"] = "deleting"
            _write_manifest(directory, manifest)
        elif source.exists() or not quarantine.is_dir():
            raise TransferConflict("old vault deletion recovery state is invalid")

        shutil.rmtree(quarantine)
        document_safety._fsync_directory(source.parent)
        manifest["old_deleted"] = True
        manifest["old_deleted_at"] = document_safety._now()
        manifest.pop("delete_quarantine", None)
        manifest.pop("delete_quarantine_identity", None)
        manifest.pop("delete_state", None)
        _write_manifest(directory, manifest)
        return manifest


def transfer_status(operation_id: str) -> dict:
    _, manifest = _manifest(operation_id)
    return manifest


def public_status(manifest: dict) -> dict:
    source_inventory = manifest.get("source_inventory") or {}
    destination_inventory = manifest.get("destination_inventory") or source_inventory
    return {
        "id": manifest.get("id", ""),
        "kind": manifest.get("kind", ""),
        "state": manifest.get("state", ""),
        "source": manifest.get("source", ""),
        "destination": manifest.get("destination", ""),
        "source_files": len(source_inventory.get("files", [])),
        "source_bytes": source_inventory.get("total_size", 0),
        "destination_files": len(destination_inventory.get("files", [])),
        "previous_active": manifest.get("previous_active", ""),
        "old_deleted": bool(manifest.get("old_deleted")),
        "delete_confirmation": manifest.get("delete_confirmation", ""),
        "created_at": manifest.get("created_at", ""),
        "updated_at": manifest.get("updated_at", ""),
    }


def pending_transfers() -> list[dict]:
    pending = []
    for directory in _operation_root().iterdir():
        if not directory.is_dir() or not _OPERATION_ID.fullmatch(directory.name):
            continue
        try:
            manifest = document_safety._read_json(directory / "manifest.json")
        except document_safety.RecoveryConflict:
            continue
        if manifest.get("state") not in {"complete", "rolled_back"}:
            pending.append(manifest)
    return sorted(pending, key=lambda item: item.get("created_at", ""))
