"""Owned macOS/Linux installation, service, and uninstall primitives.

The native installer is deliberately usable with a synthetic ``home`` in tests. Production callers
use :func:`platform_layout` with the real home directory. Personal data is never placed below the
versioned runtime tree, and uninstall verifies every program artifact before removing it.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from services import service_manager

_RELEASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_RELEASE_MARKER = ".alles-owned-release.json"
_RELEASE_FILES = ".alles-owned-files.json"
_INSTALL_VERSION = 1
_RELEASE_TRANSACTION = "release-transaction.json"
_RELEASE_REMOVAL = "release-removal.json"


class NativeInstallError(RuntimeError):
    pass


class _ServiceEnableError(NativeInstallError):
    def __init__(self, message: str, *, acquired: bool):
        super().__init__(message)
        self.acquired = acquired


@dataclass(frozen=True)
class NativeLayout:
    system: str
    home: Path
    support_root: Path
    runtime_root: Path
    releases: Path
    staging: Path
    data_root: Path
    vault_default: Path
    files_default: Path
    launcher: Path
    dispatcher: Path
    manifest: Path
    current_release: Path
    previous_release: Path
    service_root: Path
    service_definition: Path
    manager: str
    unit: str


def platform_layout(
    system: str | None = None,
    *,
    home: Path | None = None,
    xdg_data_home: Path | None = None,
    xdg_config_home: Path | None = None,
) -> NativeLayout:
    system = system or platform.system()
    home_was_explicit = home is not None
    home = (home or Path.home()).expanduser().resolve()
    if system == "Darwin":
        support = home / "Library" / "Application Support" / "Alles"
        definition = home / "Library" / "LaunchAgents" / "app.alles.server.plist"
        manager = "launchd"
        unit = "app.alles.server"
    elif system == "Linux":
        if xdg_data_home is None and not home_was_explicit:
            configured = os.environ.get("XDG_DATA_HOME", "").strip()
            if configured:
                xdg_data_home = Path(configured)
        if xdg_config_home is None and not home_was_explicit:
            configured = os.environ.get("XDG_CONFIG_HOME", "").strip()
            if configured:
                xdg_config_home = Path(configured)
        default_data_home = home / ".local" / "share"
        default_config_home = home / ".config"
        data_candidate = (xdg_data_home or default_data_home).expanduser()
        config_candidate = (xdg_config_home or default_config_home).expanduser()
        data_home = (
            data_candidate if data_candidate.is_absolute() else default_data_home
        ).resolve()
        config_home = (
            config_candidate if config_candidate.is_absolute() else default_config_home
        ).resolve()
        support = data_home / "alles"
        definition = config_home / "systemd" / "user" / "alles-server.service"
        manager = "systemd-user"
        unit = "alles-server.service"
    else:
        raise NativeInstallError("the native installer supports macOS and Linux")

    runtime = support / "runtime"
    data = support / "data"
    return NativeLayout(
        system=system,
        home=home,
        support_root=support,
        runtime_root=runtime,
        releases=runtime / "releases",
        staging=runtime / ".staging",
        data_root=data,
        vault_default=home / "Alles" / "Vault",
        files_default=home / "Alles" / "Files",
        launcher=home / ".local" / "bin" / "alles",
        dispatcher=runtime / "alles-dispatch",
        manifest=runtime / "install.json",
        current_release=runtime / "current-release",
        previous_release=runtime / "previous-release",
        service_root=data / "services" / "server",
        service_definition=definition,
        manager=manager,
        unit=unit,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _ensure_private_directory(path: Path, label: str) -> bool:
    """Create or verify one Alles-owned runtime directory without following symlinks."""
    created = False
    try:
        os.mkdir(path, 0o700)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise NativeInstallError(f"could not create private {label} directory") from exc

    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise NativeInstallError(f"refusing unsafe {label} directory") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise NativeInstallError(f"refusing unowned {label} directory")
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
    return created


def _atomic_bytes(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise NativeInstallError(f"refusing unsafe symlink at {path}")
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    try:
        with temp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(mode)
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_bytes(
        path,
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        ),
    )


def _validate_release_id(release_id: str) -> str:
    value = str(release_id or "").strip().lower()
    if not _RELEASE_ID.fullmatch(value):
        raise NativeInstallError("release id is invalid")
    return value


def _default_release_id(source: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=source,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    commit = (result.stdout or "").strip().lower() if result and result.returncode == 0 else ""
    return _validate_release_id(commit or f"local-{uuid.uuid4().hex[:12]}")


def _git_text(source: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=source,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (result.stdout or "").strip() if result.returncode == 0 else None


def source_metadata(source: Path) -> dict:
    """Capture the exact Git source an installed runtime may update from later."""
    source = source.expanduser().resolve()
    commit = (_git_text(source, ["rev-parse", "HEAD"]) or "").lower()
    upstream = _git_text(source, ["rev-parse", "--abbrev-ref", "@{upstream}"]) or ""
    dirty = _git_text(source, ["status", "--porcelain"])
    if dirty is None or dirty or not re.fullmatch(r"[0-9a-f]{40}", commit) or "/" not in upstream:
        return {"kind": "unavailable"}
    remote, branch = upstream.split("/", 1)
    url = _git_text(source, ["remote", "get-url", remote])
    if (
        not url
        or url.startswith("-")
        or any(char in url for char in "\0\r\n")
        or not re.fullmatch(r"[A-Za-z0-9._/-]{1,240}", branch)
    ):
        return {"kind": "unavailable"}
    return {
        "kind": "git",
        "url": url,
        "branch": branch,
        "commit": commit,
    }


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    blocked = {
        ".git",
        ".env",
        ".venv",
        ".agent",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "data",
        "dist",
        "node_modules",
    }
    return {name for name in names if name in blocked or name.endswith(".pyc")}


def build_release(source: Path, destination: Path) -> Path:
    """Copy one source release and build its private Python environment."""
    from services.credits import verify_release_notice_set

    source = source.expanduser().resolve()
    if source.is_symlink() or not all(
        (source / name).is_file()
        for name in ("app.py", "cli.py", "requirements.txt", "requirements.lock")
    ):
        raise NativeInstallError("source is not a complete Alles release")
    try:
        verify_release_notice_set(source)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise NativeInstallError("source release notices are incomplete") from exc
    try:
        # Preserve links while copying so copytree can never dereference a link to data outside
        # the source tree. Release sources are then required to contain no links at all.
        shutil.copytree(source, destination, ignore=_copy_ignore, symlinks=True)
    except OSError as exc:
        raise NativeInstallError("could not stage the Alles release") from exc
    for current, directories, files in os.walk(destination, followlinks=False):
        if any((Path(current) / name).is_symlink() for name in (*directories, *files)):
            raise NativeInstallError("source release contains an unsafe symlink")
    try:
        verify_release_notice_set(destination)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise NativeInstallError("staged release notices are incomplete") from exc
    python = destination / ".venv" / "bin" / "python"
    commands = (
        [sys.executable or "python3", "-m", "venv", str(destination / ".venv")],
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(destination / "requirements.lock"),
        ],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=1800, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise NativeInstallError("could not build the private Python environment") from exc
        if result.returncode != 0:
            raise NativeInstallError("could not build the private Python environment")
    return python


def _verify_private_python(release: Path, python: Path) -> None:
    expected = release / ".venv" / "bin" / "python"
    config = release / ".venv" / "pyvenv.cfg"
    if (
        python != expected
        or not python.is_file()
        or not os.access(python, os.X_OK)
        or not config.is_file()
        or config.is_symlink()
    ):
        raise NativeInstallError("private Python environment is incomplete")


def _dispatcher_source(layout: NativeLayout) -> bytes:
    runtime = shlex.quote(str(layout.runtime_root))
    data = shlex.quote(str(layout.data_root))
    xdg_environment = ""
    if layout.system == "Linux":
        xdg_environment = (
            f"export XDG_DATA_HOME={shlex.quote(str(layout.support_root.parent))}\n"
            f"export XDG_CONFIG_HOME={shlex.quote(str(layout.service_definition.parents[2]))}\n"
        )
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        f"runtime={runtime}\n"
        f"export ALLES_DATA={data}\n"
        f"export ALLES_NATIVE_ROOT={runtime}\n"
        f"{xdg_environment}"
        'release="$(sed -n \'1p\' "$runtime/current-release")"\n'
        'case "$release" in (*[!a-z0-9._-]*|"") echo "alles: invalid installed release" >&2; exit 1;; esac\n'
        'root="$runtime/releases/$release"\n'
        'python="$root/.venv/bin/python"\n'
        'if [ ! -x "$python" ] || [ ! -f "$root/cli.py" ] || [ ! -f "$root/app.py" ]; then\n'
        '  echo "alles: installed release is incomplete" >&2; exit 1\n'
        "fi\n"
        'if [ "${1:-}" = "__serve__" ]; then shift; export PORT=6769; cd "$root"; exec "$python" -B "$root/app.py" "$@"; fi\n'
        'exec "$python" -B "$root/cli.py" "$@"\n'
    ).encode("utf-8")


def _launcher_source(layout: NativeLayout) -> bytes:
    dispatcher = shlex.quote(str(layout.dispatcher))
    return f'#!/bin/sh\nexec {dispatcher} "$@"\n'.encode("utf-8")


def _xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _systemd_quote(value: Path | str) -> str:
    raw = str(value)
    if any(char in raw for char in "\n\r\0"):
        raise NativeInstallError("install path contains an unsupported character")
    return '"' + raw.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _service_source(layout: NativeLayout) -> bytes:
    if layout.manager == "launchd":
        args = "".join(
            f"<string>{_xml(value)}</string>" for value in (str(layout.dispatcher), "__serve__")
        )
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            f"<key>Label</key><string>{_xml(layout.unit)}</string>\n"
            f"<key>ProgramArguments</key><array>{args}</array>\n"
            "<key>EnvironmentVariables</key><dict><key>PORT</key><string>6769</string></dict>\n"
            "<key>RunAtLoad</key><true/>\n"
            "<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>\n"
            f"<key>StandardOutPath</key><string>{_xml(str(layout.data_root / 'alles-service.log'))}</string>\n"
            f"<key>StandardErrorPath</key><string>{_xml(str(layout.data_root / 'alles-service.log'))}</string>\n"
            "</dict></plist>\n"
        )
    else:
        content = (
            "[Unit]\nDescription=Alles personal server\nAfter=network-online.target\n\n"
            "[Service]\nType=simple\n"
            f"ExecStart={_systemd_quote(layout.dispatcher)} __serve__\n"
            "Environment=PORT=6769\n"
            f"Environment=ALLES_DATA={_systemd_quote(layout.data_root)}\n"
            f"Environment=ALLES_NATIVE_ROOT={_systemd_quote(layout.runtime_root)}\n"
            f"Environment=XDG_DATA_HOME={_systemd_quote(layout.support_root.parent)}\n"
            f"Environment=XDG_CONFIG_HOME={_systemd_quote(layout.service_definition.parents[2])}\n"
            f"StandardOutput=append:{_systemd_quote(layout.data_root / 'alles-service.log')}\n"
            "StandardError=inherit\n"
            "Restart=on-failure\nRestartSec=2\n\n"
            "[Install]\nWantedBy=default.target\n"
        )
    return content.encode("utf-8")


def _run_checked(runner, command: list[str], *, action: str) -> None:
    try:
        result = runner(command, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeInstallError(f"{action} failed") from exc
    if result.returncode != 0:
        raise NativeInstallError(f"{action} failed")


def _service_present(layout: NativeLayout, runner) -> bool:
    command = (
        ["launchctl", "print", f"gui/{os.getuid()}/{layout.unit}"]
        if layout.manager == "launchd"
        else ["systemctl", "--user", "show", "--property=LoadState", "--value", layout.unit]
    )
    try:
        result = runner(command, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeInstallError("service preflight failed") from exc
    output = f"{result.stdout}\n{result.stderr}".strip().lower()
    if layout.manager == "launchd":
        return result.returncode == 0 and bool(output)
    return result.returncode == 0 and output not in {"", "not-found"}


def _enable_service(layout: NativeLayout, runner) -> None:
    if _service_present(layout, runner):
        raise _ServiceEnableError("service install target already exists", acquired=False)
    if layout.manager == "launchd":
        try:
            _run_checked(
                runner,
                [
                    "launchctl",
                    "bootstrap",
                    f"gui/{os.getuid()}",
                    str(layout.service_definition),
                ],
                action="service install",
            )
        except NativeInstallError as exc:
            try:
                acquired = _service_present(layout, runner)
            except NativeInstallError:
                acquired = False
            raise _ServiceEnableError(str(exc), acquired=acquired) from exc
        try:
            _run_checked(
                runner,
                ["launchctl", "kickstart", f"gui/{os.getuid()}/{layout.unit}"],
                action="service start",
            )
        except NativeInstallError as exc:
            raise _ServiceEnableError(str(exc), acquired=True) from exc
    else:
        _run_checked(
            runner,
            ["systemctl", "--user", "daemon-reload"],
            action="service reload",
        )
        try:
            _run_checked(
                runner,
                ["systemctl", "--user", "enable", "--now", layout.unit],
                action="service install",
            )
        except NativeInstallError as exc:
            try:
                acquired = _service_present(layout, runner)
            except NativeInstallError:
                acquired = False
            raise _ServiceEnableError(str(exc), acquired=acquired) from exc


def _disable_service(layout: NativeLayout, runner) -> None:
    if layout.manager == "launchd":
        target = f"gui/{os.getuid()}/{layout.unit}"
        try:
            result = runner(
                ["launchctl", "bootout", target],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise NativeInstallError("service removal failed") from exc
        if result.returncode != 0:
            try:
                probe = runner(
                    ["launchctl", "print", target],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise NativeInstallError("service removal failed") from exc
            detail = f"{result.stdout}\n{result.stderr}\n{probe.stdout}\n{probe.stderr}".lower()
            absent = probe.returncode != 0 and any(
                marker in detail
                for marker in ("no such process", "could not find service", "service not found")
            )
            if not absent:
                raise NativeInstallError("service removal failed")
    else:
        _run_checked(
            runner,
            ["systemctl", "--user", "disable", "--now", layout.unit],
            action="service removal",
        )
        _run_checked(
            runner,
            ["systemctl", "--user", "daemon-reload"],
            action="service reload",
        )


def _validated_source_metadata(value, *, error: str) -> dict:
    if not isinstance(value, dict) or value.get("kind") not in {"git", "unavailable"}:
        raise NativeInstallError(error)
    if value.get("kind") == "git" and (
        not isinstance(value.get("url"), str)
        or not value["url"]
        or value["url"].startswith("-")
        or any(char in value["url"] for char in "\0\r\n")
        or not re.fullmatch(r"[A-Za-z0-9._/-]{1,240}", str(value.get("branch", "")))
        or not re.fullmatch(r"[0-9a-f]{40}", str(value.get("commit", "")))
    ):
        raise NativeInstallError(error)
    return dict(value)


def _load_manifest(layout: NativeLayout) -> dict:
    if not layout.manifest.is_file() or layout.manifest.is_symlink():
        raise NativeInstallError("owned install manifest is missing or unsafe")
    try:
        value = json.loads(layout.manifest.read_text("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise NativeInstallError("owned install manifest is invalid") from exc
    if not isinstance(value, dict) or value.get("version") != _INSTALL_VERSION:
        raise NativeInstallError("owned install manifest is invalid")
    exact = {
        "runtime_root": layout.runtime_root,
        "data_root": layout.data_root,
        "launcher": layout.launcher,
        "dispatcher": layout.dispatcher,
        "service_definition": layout.service_definition,
        "service_root": layout.service_root,
    }
    for key, expected in exact.items():
        if value.get(key) != str(expected):
            raise NativeInstallError("owned install manifest does not match this layout")
    if not re.fullmatch(r"[0-9a-f]{32}", str(value.get("installation_id", ""))):
        raise NativeInstallError("owned install manifest is invalid")
    source = _validated_source_metadata(
        value.get("source", {"kind": "unavailable"}),
        error="owned install source metadata is invalid",
    )
    raw_commits = value.get("release_commits", {})
    if not isinstance(raw_commits, dict) or any(
        not isinstance(release_id, str)
        or not _RELEASE_ID.fullmatch(release_id)
        or not isinstance(commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
        for release_id, commit in raw_commits.items()
    ):
        raise NativeInstallError("owned install release metadata is invalid")
    release_commits = dict(raw_commits)
    if source.get("kind") == "git":
        release_commits.setdefault(str(value.get("release_id") or ""), source["commit"])
    value = {**value, "source": source, "release_commits": release_commits}
    return value


def _verify_file(path: Path, digest: str, label: str) -> None:
    if not path.is_file() or path.is_symlink() or _sha256(path) != digest:
        raise NativeInstallError(f"{label} changed after installation")


def _release_file_entries(path: Path) -> list[dict]:
    entries = []
    for item in sorted(path.rglob("*"), key=lambda value: value.relative_to(path).as_posix()):
        relative = item.relative_to(path).as_posix()
        if relative == _RELEASE_FILES:
            continue
        if item.is_symlink():
            entries.append({"path": relative, "kind": "symlink", "target": os.readlink(item)})
        elif item.is_file():
            entries.append({"path": relative, "kind": "file", "sha256": _sha256(item)})
        elif item.is_dir():
            entries.append({"path": relative, "kind": "directory"})
        else:
            raise NativeInstallError("staged release contains an unsupported file type")
    return entries


def _write_release_ownership(path: Path) -> None:
    _atomic_json(
        path / _RELEASE_FILES,
        {"version": 2, "entries": _release_file_entries(path)},
    )


def _load_release_ownership(path: Path) -> list[dict]:
    manifest_path = path / _RELEASE_FILES
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise NativeInstallError("owned release file manifest is missing or unsafe")
    try:
        value = json.loads(manifest_path.read_text("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise NativeInstallError("owned release file manifest is invalid") from exc
    entries = (
        value.get("entries") if isinstance(value, dict) and value.get("version") == 2 else None
    )
    if not isinstance(entries, list):
        raise NativeInstallError("owned release file manifest is invalid")
    seen = set()
    clean = []
    for entry in entries:
        relative = str(entry.get("path") or "") if isinstance(entry, dict) else ""
        candidate = Path(relative)
        if (
            not relative
            or relative in seen
            or candidate.is_absolute()
            or candidate.as_posix() != relative
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or entry.get("kind") not in {"file", "symlink", "directory"}
        ):
            raise NativeInstallError("owned release file manifest is invalid")
        seen.add(relative)
        clean.append(entry)
    return clean


def _verify_release_files(path: Path) -> list[dict]:
    if path.is_symlink() or not path.is_dir():
        raise NativeInstallError("owned release contents changed after installation")
    entries = _load_release_ownership(path)
    for entry in entries:
        relative = Path(entry["path"])
        parent = path
        for component in relative.parts[:-1]:
            parent = parent / component
            if parent.is_symlink() or not parent.is_dir():
                raise NativeInstallError("owned release contents changed after installation")
        item = path / relative
        if entry["kind"] == "file":
            if (
                not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or ""))
                or not item.is_file()
                or item.is_symlink()
                or _sha256(item) != entry["sha256"]
            ):
                raise NativeInstallError("owned release contents changed after installation")
        elif entry["kind"] == "symlink" and (
            not isinstance(entry.get("target"), str)
            or not item.is_symlink()
            or os.readlink(item) != entry["target"]
        ):
            raise NativeInstallError("owned release contents changed after installation")
        elif entry["kind"] == "directory" and (item.is_symlink() or not item.is_dir()):
            raise NativeInstallError("owned release contents changed after installation")
    actual = {entry["path"]: entry for entry in _release_file_entries(path)}
    expected = {entry["path"]: entry for entry in entries}
    if actual != expected:
        raise NativeInstallError("owned release contents changed after installation")
    return entries


def _release_removal_path(runtime_root: Path) -> Path:
    return runtime_root / _RELEASE_REMOVAL


def _release_removal_quarantine(runtime_root: Path, release_id: str) -> Path:
    return runtime_root / ".staging" / f".remove-{release_id}"


def _load_release_removal(runtime_root: Path) -> dict | None:
    journal = _release_removal_path(runtime_root)
    if not journal.exists() and not journal.is_symlink():
        return None
    if not journal.is_file() or journal.is_symlink():
        raise NativeInstallError("release removal journal is unsafe")
    try:
        value = json.loads(journal.read_text("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise NativeInstallError("release removal journal is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or value.get("state") not in {"prepared", "detached"}
        or not re.fullmatch(r"[0-9a-f]{32}", str(value.get("installation_id", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("ownership_sha256", "")))
        or not isinstance(value.get("entries"), list)
    ):
        raise NativeInstallError("release removal journal is invalid")
    value["release_id"] = _validate_release_id(value.get("release_id"))
    seen: set[str] = set()
    for entry in value["entries"]:
        relative = str(entry.get("path") or "") if isinstance(entry, dict) else ""
        candidate = Path(relative)
        kind = entry.get("kind") if isinstance(entry, dict) else None
        if (
            not relative
            or relative in seen
            or candidate.is_absolute()
            or candidate.as_posix() != relative
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or kind not in {"file", "symlink", "directory"}
            or (kind == "file" and not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))))
            or (kind == "symlink" and not isinstance(entry.get("target"), str))
        ):
            raise NativeInstallError("release removal journal is invalid")
        seen.add(relative)
    return value


def _verify_quarantined_item(root: Path, entry: dict) -> Path | None:
    relative = Path(entry["path"])
    parent = root
    for component in relative.parts[:-1]:
        parent = parent / component
        if not parent.exists():
            return None
        if parent.is_symlink() or not parent.is_dir():
            raise NativeInstallError("quarantined release contents changed during removal")
    item = root / relative
    if not item.exists() and not item.is_symlink():
        return None
    if entry["kind"] == "file":
        if not item.is_file() or item.is_symlink() or _sha256(item) != entry["sha256"]:
            raise NativeInstallError("quarantined release contents changed during removal")
    elif entry["kind"] == "symlink":
        if not item.is_symlink() or os.readlink(item) != entry["target"]:
            raise NativeInstallError("quarantined release contents changed during removal")
    elif item.is_symlink() or not item.is_dir():
        raise NativeInstallError("quarantined release contents changed during removal")
    return item


def _remove_quarantined_release(root: Path, transaction: dict) -> None:
    for entry in transaction["entries"]:
        if entry["kind"] == "directory":
            continue
        item = _verify_quarantined_item(root, entry)
        if item is not None:
            item.unlink()
    ownership = root / _RELEASE_FILES
    if ownership.exists() or ownership.is_symlink():
        if (
            not ownership.is_file()
            or ownership.is_symlink()
            or _sha256(ownership) != transaction["ownership_sha256"]
        ):
            raise NativeInstallError("quarantined release ownership changed during removal")
        ownership.unlink()
    directories = [entry for entry in transaction["entries"] if entry["kind"] == "directory"]
    for entry in sorted(directories, key=lambda value: value["path"].count("/"), reverse=True):
        item = _verify_quarantined_item(root, entry)
        if item is not None:
            try:
                item.rmdir()
            except OSError as exc:
                raise NativeInstallError(
                    "quarantined release contains unexpected files during removal"
                ) from exc
    try:
        root.rmdir()
    except OSError as exc:
        raise NativeInstallError(
            "quarantined release contains unexpected files during removal"
        ) from exc


def _reconcile_release_removal(runtime_root: Path, *, retain_journal: bool = False) -> str | None:
    transaction = _load_release_removal(runtime_root)
    if transaction is None:
        return None
    release_id = transaction["release_id"]
    source = runtime_root / "releases" / release_id
    quarantine = _release_removal_quarantine(runtime_root, release_id)
    if transaction["state"] == "prepared":
        source_exists = source.exists() or source.is_symlink()
        quarantine_exists = quarantine.exists() or quarantine.is_symlink()
        if source_exists == quarantine_exists:
            raise NativeInstallError("release removal state is inconsistent")
        candidate = source if source_exists else quarantine
        _verify_release(
            candidate,
            installation_id=transaction["installation_id"],
            release_id=release_id,
        )
        if _sha256(candidate / _RELEASE_FILES) != transaction["ownership_sha256"]:
            raise NativeInstallError("release removal ownership changed")
        if source_exists:
            _ensure_private_directory(quarantine.parent, "release removal staging")
            os.rename(source, quarantine)
            _fsync_dir(source.parent)
            _fsync_dir(quarantine.parent)
        transaction["state"] = "detached"
        _atomic_json(_release_removal_path(runtime_root), transaction)
    if source.exists() or source.is_symlink():
        raise NativeInstallError("release removal state is inconsistent")
    if quarantine.exists() or quarantine.is_symlink():
        if quarantine.is_symlink() or not quarantine.is_dir():
            raise NativeInstallError("release removal quarantine is unsafe")
        _remove_quarantined_release(quarantine, transaction)
        _fsync_dir(quarantine.parent)
    if not retain_journal:
        _release_removal_path(runtime_root).unlink()
        _fsync_dir(runtime_root)
    return release_id


def _remove_owned_release(path: Path, *, retain_journal: bool = False) -> None:
    release_id = _validate_release_id(path.name)
    runtime_root = path.parent.parent
    if path.parent != runtime_root / "releases":
        raise NativeInstallError("owned release path is outside the releases directory")
    reconciled = _reconcile_release_removal(runtime_root, retain_journal=retain_journal)
    if reconciled == release_id and not path.exists() and not path.is_symlink():
        return
    entries = _verify_release_files(path)
    marker_path = path / _RELEASE_MARKER
    try:
        marker = json.loads(marker_path.read_text("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise NativeInstallError("owned release marker is invalid") from exc
    if (
        not isinstance(marker, dict)
        or marker.get("release_id") != release_id
        or not re.fullmatch(r"[0-9a-f]{32}", str(marker.get("installation_id", "")))
    ):
        raise NativeInstallError("owned release marker does not match the release path")
    quarantine = _release_removal_quarantine(runtime_root, release_id)
    if quarantine.exists() or quarantine.is_symlink():
        raise NativeInstallError("release removal quarantine already exists")
    _atomic_json(
        _release_removal_path(runtime_root),
        {
            "version": 1,
            "state": "prepared",
            "installation_id": marker["installation_id"],
            "release_id": release_id,
            "ownership_sha256": _sha256(path / _RELEASE_FILES),
            "entries": entries,
        },
    )
    _reconcile_release_removal(runtime_root, retain_journal=retain_journal)


def _verify_release(path: Path, *, installation_id: str, release_id: str) -> None:
    marker_path = path / _RELEASE_MARKER
    if path.is_symlink() or not marker_path.is_file() or marker_path.is_symlink():
        raise NativeInstallError("owned release marker is missing or unsafe")
    try:
        marker = json.loads(marker_path.read_text("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise NativeInstallError("owned release marker is invalid") from exc
    if marker != {"installation_id": installation_id, "release_id": release_id}:
        raise NativeInstallError("owned release marker does not match the installation")
    _verify_release_files(path)


def install(
    source: Path,
    layout: NativeLayout,
    *,
    release_id: str | None = None,
    release_builder: Callable[[Path, Path], Path] = build_release,
    release_probe: Callable[[Path, Path], bool],
    install_source: dict | None = None,
    runner=subprocess.run,
) -> dict:
    """Create a clean native install. Existing or unowned destinations fail closed."""
    source = source.expanduser().resolve()
    release_id = _validate_release_id(release_id) if release_id else _default_release_id(source)
    recorded_source = _validated_source_metadata(
        dict(install_source) if install_source is not None else source_metadata(source),
        error="install source metadata is invalid",
    )
    if layout.manifest.exists() or layout.manifest.is_symlink():
        raise NativeInstallError("an owned native installation already exists")
    for path, label in (
        (layout.launcher, "launcher"),
        (layout.service_definition, "service definition"),
        (layout.dispatcher, "dispatcher"),
        (layout.current_release, "current release pointer"),
        (layout.previous_release, "previous release pointer"),
        (layout.runtime_root / _RELEASE_TRANSACTION, "release transaction journal"),
        (layout.runtime_root / _RELEASE_REMOVAL, "release removal journal"),
        (layout.releases / release_id, "release"),
    ):
        if path.exists() or path.is_symlink():
            raise NativeInstallError(f"refusing to replace an unowned {label}")

    installation_id = uuid.uuid4().hex
    stage = layout.staging / f"{release_id}-{uuid.uuid4().hex}"
    published = layout.releases / release_id
    registered = False
    service_enable_attempted = False
    created_program_files: list[Path] = []
    created_program_directories: list[Path] = []
    manifest = None
    installed = False
    try:
        layout.support_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ensure_private_directory(layout.support_root, "support root")
        for directory, label in (
            (layout.runtime_root, "runtime root"),
            (layout.staging, "staging"),
            (layout.releases, "releases"),
        ):
            if _ensure_private_directory(directory, label):
                created_program_directories.append(directory)
        layout.data_root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ensure_private_directory(layout.data_root, "data root")
        python = release_builder(source, stage)
        _verify_private_python(stage, python)
        if not release_probe(stage, python):
            raise NativeInstallError("staged release health probe failed")
        _atomic_json(
            stage / _RELEASE_MARKER,
            {"installation_id": installation_id, "release_id": release_id},
        )
        _write_release_ownership(stage)
        layout.releases.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(stage, published)
        _fsync_dir(layout.releases)
        created_program_files.append(published)

        _atomic_bytes(layout.current_release, (release_id + "\n").encode("ascii"))
        created_program_files.append(layout.current_release)
        _atomic_bytes(layout.dispatcher, _dispatcher_source(layout), mode=0o700)
        created_program_files.append(layout.dispatcher)
        _atomic_bytes(layout.launcher, _launcher_source(layout), mode=0o700)
        created_program_files.append(layout.launcher)
        _atomic_bytes(layout.service_definition, _service_source(layout), mode=0o600)
        created_program_files.append(layout.service_definition)
        _ensure_private_directory(layout.service_root.parent, "services root")
        _ensure_private_directory(layout.service_root, "service root")

        manifest = {
            "version": _INSTALL_VERSION,
            "installation_id": installation_id,
            "system": layout.system,
            "manager": layout.manager,
            "unit": layout.unit,
            "release_id": release_id,
            "runtime_root": str(layout.runtime_root),
            "data_root": str(layout.data_root),
            "vault_default": str(layout.vault_default),
            "files_default": str(layout.files_default),
            "launcher": str(layout.launcher),
            "launcher_sha256": _sha256(layout.launcher),
            "dispatcher": str(layout.dispatcher),
            "dispatcher_sha256": _sha256(layout.dispatcher),
            "service_root": str(layout.service_root),
            "service_definition": str(layout.service_definition),
            "service_definition_sha256": _sha256(layout.service_definition),
            "source": recorded_source,
            "release_commits": (
                {release_id: recorded_source["commit"]}
                if recorded_source.get("kind") == "git"
                else {}
            ),
        }
        _atomic_json(layout.manifest, manifest)
        created_program_files.append(layout.manifest)
        service_manager.register_owned_service(
            service_id="server",
            name="Alles server",
            manager=layout.manager,
            root=layout.service_root,
            unit=layout.unit,
        )
        registered = True
        try:
            _enable_service(layout, runner)
        except _ServiceEnableError as exc:
            service_enable_attempted = exc.acquired
            raise
        service_enable_attempted = True
        installed = True
        return {
            "ok": True,
            "release_id": release_id,
            "runtime_root": str(layout.runtime_root),
            "data_root": str(layout.data_root),
            "vault_default": str(layout.vault_default),
            "files_default": str(layout.files_default),
        }
    except Exception:
        service_cleanup_failed = False
        if service_enable_attempted:
            try:
                _disable_service(layout, runner)
            except NativeInstallError:
                service_cleanup_failed = True
        if service_cleanup_failed:
            # The service may still be enabled. Preserve its owned manifest and
            # program files so it never points at artifacts rollback deleted.
            raise
        service_unregistered = not registered
        if registered:
            try:
                service_manager.unregister_owned_service("server")
                service_unregistered = True
            except Exception:
                pass
        release_cleanup_failed = False
        if published in created_program_files:
            try:
                if published.is_dir() and not published.is_symlink():
                    _remove_owned_release(published)
                elif published.exists() or published.is_symlink():
                    release_cleanup_failed = True
            except (NativeInstallError, OSError):
                # Keep the complete owned install record if release removal cannot be
                # proven. A later uninstall can resume from its release-removal journal.
                release_cleanup_failed = True
        if (
            release_cleanup_failed
            and isinstance(manifest, dict)
            and layout.manifest in created_program_files
        ):
            recovery_manifest = dict(manifest)
            recovery_manifest.update(
                {
                    "uninstalling": True,
                    "service_disabled": True,
                    "service_unregistered": service_unregistered,
                }
            )
            _atomic_json(layout.manifest, recovery_manifest)
        for path in reversed(created_program_files):
            if release_cleanup_failed or path == published:
                continue
            try:
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                else:
                    path.unlink(missing_ok=True)
            except (NativeInstallError, OSError):
                pass
        if layout.manager != "launchd" and service_enable_attempted:
            try:
                _run_checked(
                    runner,
                    ["systemctl", "--user", "daemon-reload"],
                    action="service reload",
                )
            except NativeInstallError:
                pass
        raise
    finally:
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage, ignore_errors=True)
        if not installed:
            for directory in reversed(created_program_directories):
                try:
                    directory.rmdir()
                except OSError:
                    pass


def uninstall_keep_data(layout: NativeLayout, *, runner=subprocess.run) -> dict:
    """Remove only verified program/service artifacts. Personal data is always retained."""
    _reconcile_release_transaction(layout)
    reconciled_removal = _reconcile_release_removal(
        layout.runtime_root,
        retain_journal=True,
    )
    manifest = _load_manifest(layout)
    resuming = manifest.get("uninstalling") is True

    def verify_program_file(path: Path, digest: str, label: str) -> None:
        if path.exists() or path.is_symlink() or not resuming:
            _verify_file(path, digest, label)

    verify_program_file(layout.launcher, manifest["launcher_sha256"], "launcher")
    verify_program_file(layout.dispatcher, manifest["dispatcher_sha256"], "dispatcher")
    verify_program_file(
        layout.service_definition, manifest["service_definition_sha256"], "service definition"
    )
    release_id = _validate_release_id(str(manifest.get("release_id", "")))
    current_release = None
    if layout.current_release.exists() or layout.current_release.is_symlink() or not resuming:
        current_release = _read_release_pointer(layout.current_release, "current")
        if current_release != release_id:
            raise NativeInstallError("current release pointer does not match the install manifest")
    release = layout.releases / release_id
    if release.exists() or not resuming:
        _verify_release(
            release,
            installation_id=manifest["installation_id"],
            release_id=release_id,
        )
    if layout.previous_release.exists() or layout.previous_release.is_symlink():
        previous = _read_release_pointer(layout.previous_release, "previous")
        previous_path = layout.releases / previous
        if (
            reconciled_removal == previous
            and not previous_path.exists()
            and not previous_path.is_symlink()
        ):
            layout.previous_release.unlink()
            _fsync_dir(layout.releases)
        elif previous_path.exists() or previous_path.is_symlink() or not resuming:
            _verify_release(
                previous_path,
                installation_id=manifest["installation_id"],
                release_id=previous,
            )
    if reconciled_removal is not None and current_release != reconciled_removal:
        _release_removal_path(layout.runtime_root).unlink(missing_ok=True)
        _fsync_dir(layout.runtime_root)

    owned_releases = []
    try:
        release_entries = list(layout.releases.iterdir()) if layout.releases.is_dir() else []
    except OSError as exc:
        raise NativeInstallError("installed releases cannot be enumerated safely") from exc
    for candidate in release_entries:
        candidate_id = _validate_release_id(candidate.name)
        _verify_release(
            candidate,
            installation_id=manifest["installation_id"],
            release_id=candidate_id,
        )
        owned_releases.append(candidate)

    if not resuming:
        manifest["uninstalling"] = True
        _atomic_json(layout.manifest, manifest)

    if not manifest.get("service_disabled"):
        _disable_service(layout, runner)
        manifest["service_disabled"] = True
        _atomic_json(layout.manifest, manifest)
    if not manifest.get("service_unregistered"):
        if not manifest.get("service_unregister_started"):
            manifest["service_unregister_started"] = True
            _atomic_json(layout.manifest, manifest)
        try:
            service_manager.unregister_owned_service("server")
        except service_manager.ServiceOwnershipError:
            raise
        manifest["service_unregistered"] = True
        _atomic_json(layout.manifest, manifest)
    layout.service_definition.unlink(missing_ok=True)
    if layout.manager != "launchd":
        _run_checked(
            runner,
            ["systemctl", "--user", "daemon-reload"],
            action="service reload",
        )
    layout.launcher.unlink(missing_ok=True)
    for owned_release in owned_releases:
        _remove_owned_release(owned_release)
    layout.current_release.unlink(missing_ok=True)
    layout.previous_release.unlink(missing_ok=True)
    layout.dispatcher.unlink(missing_ok=True)
    layout.manifest.unlink()
    for directory in (layout.staging, layout.releases, layout.runtime_root):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        layout.service_root.rmdir()
        layout.service_root.parent.rmdir()
    except OSError:
        pass
    return {
        "ok": True,
        "data_kept": True,
        "data_root": str(layout.data_root),
        "vault_kept": str(layout.vault_default),
        "files_kept": str(layout.files_default),
    }


def _read_release_pointer(path: Path, label: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise NativeInstallError(f"{label} release pointer is missing or unsafe")
    try:
        return _validate_release_id(path.read_text("utf-8").strip())
    except OSError as exc:
        raise NativeInstallError(f"{label} release pointer is unreadable") from exc


def _release_transaction_path(layout: NativeLayout) -> Path:
    return layout.runtime_root / _RELEASE_TRANSACTION


def _manifest_for_release(
    manifest: dict, release_id: str, *, source_commit: str | None = None
) -> dict:
    updated = dict(manifest)
    updated["release_id"] = release_id
    source = dict(updated.get("source") or {})
    release_commits = dict(updated.get("release_commits") or {})
    candidate = source_commit or release_id
    if source.get("kind") == "git" and re.fullmatch(r"[0-9a-f]{40}", candidate):
        source["commit"] = candidate
        updated["source"] = source
        release_commits[release_id] = candidate
    updated["release_commits"] = release_commits
    return updated


def _start_release_transaction(
    layout: NativeLayout,
    manifest: dict,
    *,
    from_release: str,
    to_release: str,
    previous_before: str,
    source_commit: str | None,
) -> None:
    recorded_commit = source_commit if re.fullmatch(r"[0-9a-f]{40}", source_commit or "") else ""
    _atomic_json(
        _release_transaction_path(layout),
        {
            "version": 1,
            "installation_id": manifest["installation_id"],
            "from_release": from_release,
            "to_release": to_release,
            "previous_before": previous_before,
            "source_commit": recorded_commit,
        },
    )


def _finish_release_transaction(layout: NativeLayout) -> None:
    _release_transaction_path(layout).unlink(missing_ok=True)
    _fsync_dir(layout.runtime_root)


def _reconcile_release_transaction(layout: NativeLayout) -> None:
    journal = _release_transaction_path(layout)
    if not journal.exists() and not journal.is_symlink():
        return
    if not journal.is_file() or journal.is_symlink():
        raise NativeInstallError("release transaction journal is unsafe")
    try:
        transaction = json.loads(journal.read_text("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise NativeInstallError("release transaction journal is invalid") from exc
    manifest = _load_manifest(layout)
    if not isinstance(transaction, dict) or transaction.get("version") != 1:
        raise NativeInstallError("release transaction journal is invalid")
    if transaction.get("installation_id") != manifest["installation_id"]:
        raise NativeInstallError("release transaction journal is not owned by this installation")
    source = _validate_release_id(transaction.get("from_release"))
    target = _validate_release_id(transaction.get("to_release"))
    previous_before = str(transaction.get("previous_before") or "")
    if previous_before:
        previous_before = _validate_release_id(previous_before)
    source_commit = str(transaction.get("source_commit") or "")
    if source_commit and not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise NativeInstallError("release transaction journal is invalid")
    current = _read_release_pointer(layout.current_release, "current")
    manifest_release = _validate_release_id(manifest.get("release_id"))
    if current not in {source, target} or manifest_release not in {source, target}:
        raise NativeInstallError("release transaction state is inconsistent")

    if current == target or manifest_release == target:
        for release_id in (source, target):
            _verify_release(
                layout.releases / release_id,
                installation_id=manifest["installation_id"],
                release_id=release_id,
            )
        _atomic_bytes(layout.current_release, (target + "\n").encode("ascii"))
        _atomic_bytes(layout.previous_release, (source + "\n").encode("ascii"))
        _atomic_json(
            layout.manifest,
            _manifest_for_release(manifest, target, source_commit=source_commit or None),
        )
    else:
        if previous_before:
            _atomic_bytes(layout.previous_release, (previous_before + "\n").encode("ascii"))
        else:
            layout.previous_release.unlink(missing_ok=True)
            _fsync_dir(layout.runtime_root)
    _finish_release_transaction(layout)


def _verify_active_install(layout: NativeLayout) -> dict:
    manifest = _load_manifest(layout)
    _verify_file(layout.launcher, manifest["launcher_sha256"], "launcher")
    _verify_file(layout.dispatcher, manifest["dispatcher_sha256"], "dispatcher")
    _verify_file(
        layout.service_definition,
        manifest["service_definition_sha256"],
        "service definition",
    )
    current = _read_release_pointer(layout.current_release, "current")
    if current != manifest.get("release_id"):
        raise NativeInstallError("current release pointer does not match the install manifest")
    _verify_release(
        layout.releases / current,
        installation_id=manifest["installation_id"],
        release_id=current,
    )
    return manifest


def verify_install(layout: NativeLayout) -> dict:
    """Verify the program boundary without reading personal data."""
    _reconcile_release_transaction(layout)
    manifest = _verify_active_install(layout)
    current = manifest["release_id"]
    if layout.previous_release.exists() or layout.previous_release.is_symlink():
        previous = _read_release_pointer(layout.previous_release, "previous")
        if previous == current:
            raise NativeInstallError("previous release pointer matches the current release")
        _verify_release(
            layout.releases / previous,
            installation_id=manifest["installation_id"],
            release_id=previous,
        )
    return manifest


def stage_update_release(
    source: Path,
    layout: NativeLayout,
    *,
    release_id: str,
    release_builder: Callable[[Path, Path], Path] = build_release,
    release_probe: Callable[[Path, Path], bool],
) -> Path:
    """Build and publish an inert candidate without changing the current pointer."""
    manifest = verify_install(layout)
    if layout.previous_release.exists() or layout.previous_release.is_symlink():
        raise NativeInstallError("accept or roll back the current update before staging another")
    release_id = _validate_release_id(release_id)
    if release_id == manifest["release_id"]:
        raise NativeInstallError("the requested release is already active")
    removal = _load_release_removal(layout.runtime_root)
    if removal is not None:
        raise NativeInstallError(
            "finish the interrupted release removal before staging another update"
        )
    published = layout.releases / release_id
    if published.exists() or published.is_symlink():
        raise NativeInstallError("the candidate release path already exists")
    stage = layout.staging / f"{release_id}-{uuid.uuid4().hex}"
    try:
        python = release_builder(source.expanduser().resolve(), stage)
        _verify_private_python(stage, python)
        if not release_probe(stage, python):
            raise NativeInstallError("staged release health probe failed")
        _atomic_json(
            stage / _RELEASE_MARKER,
            {"installation_id": manifest["installation_id"], "release_id": release_id},
        )
        _write_release_ownership(stage)
        layout.releases.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(stage, published)
        _fsync_dir(layout.releases)
        return published
    finally:
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage, ignore_errors=True)


def _save_active_release(
    layout: NativeLayout,
    manifest: dict,
    release_id: str,
    *,
    source_commit: str | None = None,
) -> None:
    _atomic_json(
        layout.manifest,
        _manifest_for_release(manifest, release_id, source_commit=source_commit),
    )


def activate_release(
    layout: NativeLayout,
    release_id: str,
    *,
    source_commit: str | None = None,
) -> str:
    """Atomically point the dispatcher at one already-probed candidate."""
    manifest = verify_install(layout)
    if layout.previous_release.exists() or layout.previous_release.is_symlink():
        raise NativeInstallError("accept or roll back the current update before switching again")
    current = manifest["release_id"]
    release_id = _validate_release_id(release_id)
    if release_id == current:
        raise NativeInstallError("the requested release is already active")
    _verify_release(
        layout.releases / release_id,
        installation_id=manifest["installation_id"],
        release_id=release_id,
    )
    _start_release_transaction(
        layout,
        manifest,
        from_release=current,
        to_release=release_id,
        previous_before="",
        source_commit=source_commit,
    )
    _atomic_bytes(layout.previous_release, (current + "\n").encode("ascii"))
    try:
        _atomic_bytes(layout.current_release, (release_id + "\n").encode("ascii"))
        _save_active_release(layout, manifest, release_id, source_commit=source_commit)
        _finish_release_transaction(layout)
    except Exception:
        _atomic_bytes(layout.current_release, (current + "\n").encode("ascii"))
        _atomic_json(layout.manifest, manifest)
        layout.previous_release.unlink(missing_ok=True)
        _fsync_dir(layout.runtime_root)
        _finish_release_transaction(layout)
        raise
    return release_id


def rollback_release(layout: NativeLayout, *, source_commit: str | None = None) -> str:
    """Swap the current and previous verified release pointers."""
    manifest = verify_install(layout)
    previous = _read_release_pointer(layout.previous_release, "previous")
    current = manifest["release_id"]
    rollback_commit = source_commit or manifest.get("release_commits", {}).get(previous)
    if manifest.get("source", {}).get("kind") == "git" and not rollback_commit:
        raise NativeInstallError("previous release source commit is unavailable")
    _verify_release(
        layout.releases / previous,
        installation_id=manifest["installation_id"],
        release_id=previous,
    )
    _start_release_transaction(
        layout,
        manifest,
        from_release=current,
        to_release=previous,
        previous_before=previous,
        source_commit=rollback_commit,
    )
    _atomic_bytes(layout.current_release, (previous + "\n").encode("ascii"))
    try:
        _atomic_bytes(layout.previous_release, (current + "\n").encode("ascii"))
        _save_active_release(
            layout,
            manifest,
            previous,
            source_commit=rollback_commit,
        )
        _finish_release_transaction(layout)
    except Exception:
        _atomic_bytes(layout.current_release, (current + "\n").encode("ascii"))
        _atomic_bytes(layout.previous_release, (previous + "\n").encode("ascii"))
        _atomic_json(layout.manifest, manifest)
        _finish_release_transaction(layout)
        raise
    return previous


def accept_release(layout: NativeLayout, *, expected_previous: str | None = None) -> str:
    """Drop the previous release, safely resuming an accepted partial removal."""
    reconciled = _reconcile_release_removal(layout.runtime_root, retain_journal=True)
    expected = _validate_release_id(expected_previous) if expected_previous else None
    manifest = (
        _verify_active_install(layout)
        if expected is not None or reconciled is not None
        else verify_install(layout)
    )
    if not layout.previous_release.exists() and not layout.previous_release.is_symlink():
        if reconciled is not None and (expected is None or reconciled == expected):
            _release_removal_path(layout.runtime_root).unlink(missing_ok=True)
            _fsync_dir(layout.runtime_root)
            return reconciled
        if expected is None or (layout.releases / expected).exists():
            raise NativeInstallError("previous release pointer is missing")
        return expected
    previous = _read_release_pointer(layout.previous_release, "previous")
    if expected is not None and previous != expected:
        raise NativeInstallError("previous release does not match the accepted update")
    if previous == manifest["release_id"]:
        raise NativeInstallError("cannot remove the active release")
    path = layout.releases / previous
    if path.exists() or path.is_symlink():
        _verify_release(
            path,
            installation_id=manifest["installation_id"],
            release_id=previous,
        )
        _remove_owned_release(path, retain_journal=True)
    elif expected is None and reconciled != previous:
        raise NativeInstallError("previous release is missing")
    layout.previous_release.unlink()
    _fsync_dir(layout.releases)
    _release_removal_path(layout.runtime_root).unlink(missing_ok=True)
    _fsync_dir(layout.runtime_root)
    return previous


def discard_inactive_release(layout: NativeLayout, release_id: str) -> str:
    """Remove one verified release only when neither dispatcher pointer can select it."""
    manifest = verify_install(layout)
    release_id = _validate_release_id(release_id)
    current = manifest["release_id"]
    previous = (
        _read_release_pointer(layout.previous_release, "previous")
        if layout.previous_release.exists() or layout.previous_release.is_symlink()
        else None
    )
    if release_id in {current, previous}:
        raise NativeInstallError("cannot discard an active or rollback release")
    path = layout.releases / release_id
    _verify_release(
        path,
        installation_id=manifest["installation_id"],
        release_id=release_id,
    )
    _remove_owned_release(path)
    _fsync_dir(layout.releases)
    return release_id


def current_layout() -> NativeLayout | None:
    raw = os.environ.get("ALLES_NATIVE_ROOT", "").strip()
    if not raw:
        return None
    layout = platform_layout()
    return layout if layout.runtime_root == Path(raw).expanduser().resolve() else None


def public_layout(layout: NativeLayout) -> dict:
    """Stable diagnostics without ownership secrets or private file contents."""
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in asdict(layout).items()
    }
