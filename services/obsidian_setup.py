"""Explicit, ownership-safe installation of the optional Obsidian companion."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import uuid
from pathlib import Path
from typing import Callable

_MARKER = ".alles-owned-plugin.json"
_VERSION = 1
_PLUGIN_ID = "obsidian-alles"


class ObsidianSetupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _vault_path(vault: Path) -> Path:
    path = vault.expanduser()
    if not path.is_absolute():
        path = path.resolve()
    if path.is_symlink() or not path.is_dir() or path == Path(path.anchor):
        raise ObsidianSetupError("the configured Vault is missing or unsafe")
    return path.resolve()


def _source_path(source: Path | None) -> Path:
    path = (
        source
        if source is not None
        else Path(__file__).resolve().parent.parent / "static" / "plugins" / _PLUGIN_ID
    ).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ObsidianSetupError("the Obsidian companion source is missing or unsafe")
    path = path.resolve()
    if not (path / "manifest.json").is_file() or not (path / "main.js").is_file():
        raise ObsidianSetupError("the Obsidian companion source is incomplete")
    return path


def _source_files(source: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for candidate in source.rglob("*"):
        if candidate.is_symlink():
            raise ObsidianSetupError("the Obsidian companion source contains a symlink")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ObsidianSetupError("the Obsidian companion source contains an unsafe entry")
        relative = candidate.relative_to(source).as_posix()
        if relative == _MARKER:
            continue
        files[relative] = candidate
    if not files:
        raise ObsidianSetupError("the Obsidian companion source is empty")
    return files


def _read_marker(target: Path) -> dict:
    marker_path = target / _MARKER
    if not marker_path.is_file() or marker_path.is_symlink():
        raise ObsidianSetupError("the existing Obsidian companion is not owned by Alles")
    try:
        marker = json.loads(marker_path.read_text("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise ObsidianSetupError("the existing Obsidian companion ownership is invalid") from exc
    if not isinstance(marker, dict):
        raise ObsidianSetupError("the existing Obsidian companion ownership is invalid")
    files = marker.get("files")
    if marker.get("version") != _VERSION or not isinstance(files, dict) or not files:
        raise ObsidianSetupError("the existing Obsidian companion ownership is invalid")
    for relative, expected in files.items():
        if (
            not isinstance(relative, str)
            or not relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
            or not isinstance(expected, str)
        ):
            raise ObsidianSetupError("the existing Obsidian companion ownership is invalid")
        candidate = target / relative
        if candidate.is_symlink() or not candidate.is_file() or _sha256(candidate) != expected:
            raise ObsidianSetupError("the existing Obsidian companion changed after installation")
    actual = {
        item.relative_to(target).as_posix()
        for item in target.rglob("*")
        if item.is_file() and item != marker_path
    }
    if actual != set(files):
        raise ObsidianSetupError("the existing Obsidian companion changed after installation")
    return marker


def detect_obsidian() -> str | None:
    """Return the detected desktop app path without mutating anything."""
    system = platform.system()
    if system == "Darwin":
        candidates = (
            Path("/Applications/Obsidian.app"),
            Path.home() / "Applications" / "Obsidian.app",
        )
        found = next((path for path in candidates if path.is_dir()), None)
        return str(found) if found else None
    if system == "Linux":
        return shutil.which("obsidian")
    return None


def status(vault: Path, *, detector: Callable[[], str | None] = detect_obsidian) -> dict:
    """Inspect optional integration state. This function never creates Vault files."""
    vault = _vault_path(vault)
    target = vault / ".obsidian" / "plugins" / _PLUGIN_ID
    installed = False
    integrity = "not-installed"
    if target.exists():
        try:
            if target.is_symlink() or not target.is_dir():
                raise ObsidianSetupError("the existing Obsidian companion is not owned by Alles")
            _read_marker(target)
            installed = True
            integrity = "verified"
        except ObsidianSetupError:
            integrity = "unowned-or-changed"
    detected = detector()
    return {
        "obsidian_detected": bool(detected),
        "obsidian_path": str(detected or ""),
        "companion_installed": installed,
        "companion_integrity": integrity,
        "plugin_path": str(target),
    }


def _write_marker(path: Path, files: dict[str, str]) -> None:
    marker = {"version": _VERSION, "plugin_id": _PLUGIN_ID, "files": files}
    marker_path = path / _MARKER
    with marker_path.open("x", encoding="utf-8") as handle:
        json.dump(marker, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    marker_path.chmod(0o600)


def install_companion(vault: Path, *, source: Path | None = None) -> dict:
    """Install/update the companion only after an explicit owner action."""
    vault = _vault_path(vault)
    source = _source_path(source)
    source_files = _source_files(source)
    plugin_parent = vault / ".obsidian" / "plugins"
    target = plugin_parent / _PLUGIN_ID
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            raise ObsidianSetupError("the existing Obsidian companion is not owned by Alles")
        _read_marker(target)

    vault_root = vault.resolve()
    existing_parent = plugin_parent
    while not existing_parent.exists() and existing_parent != vault:
        existing_parent = existing_parent.parent
    try:
        existing_parent.resolve().relative_to(vault_root)
    except ValueError as exc:
        raise ObsidianSetupError("the Obsidian plugins folder is unsafe") from exc
    if existing_parent.is_symlink():
        raise ObsidianSetupError("the Obsidian plugins folder is unsafe")
    plugin_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        plugin_parent.resolve().relative_to(vault_root)
    except ValueError as exc:
        raise ObsidianSetupError("the Obsidian plugins folder is unsafe") from exc
    stage = plugin_parent / f".{_PLUGIN_ID}.{uuid.uuid4().hex}.staging"
    backup = plugin_parent / f".{_PLUGIN_ID}.{uuid.uuid4().hex}.previous"
    installed = False
    try:
        stage.mkdir(mode=0o700)
        hashes: dict[str, str] = {}
        for relative, candidate in source_files.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(candidate, destination)
            destination.chmod(0o600)
            hashes[relative] = _sha256(destination)
        _write_marker(stage, hashes)

        had_previous = target.exists()
        if had_previous:
            os.replace(target, backup)
        try:
            os.replace(stage, target)
        except OSError:
            if had_previous and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        try:
            _read_marker(target)
        except (ObsidianSetupError, OSError) as exc:
            failed = plugin_parent / f".{_PLUGIN_ID}.{uuid.uuid4().hex}.failed"
            try:
                if target.exists():
                    os.replace(target, failed)
                if had_previous:
                    if not backup.exists():
                        raise OSError("verified previous companion is unavailable")
                    os.replace(backup, target)
            except OSError as restore_exc:
                raise ObsidianSetupError(
                    "the previous Obsidian companion could not be restored safely"
                ) from restore_exc
            if isinstance(exc, ObsidianSetupError):
                raise
            raise ObsidianSetupError(
                "the Obsidian companion could not be verified after installation"
            ) from exc
        installed = True
        if backup.exists():
            shutil.rmtree(backup)
    except ObsidianSetupError:
        raise
    except OSError as exc:
        raise ObsidianSetupError("the Obsidian companion could not be installed safely") from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if installed and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

    return {"installed": True, **status(vault)}
