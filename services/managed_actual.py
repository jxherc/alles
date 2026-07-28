"""Alles-owned Actual 26.7.0 install, loopback lifecycle, backup, and restore."""

from __future__ import annotations

try:
    import fcntl
except ModuleNotFoundError:  # Windows can run Alles, but not its managed Actual lifecycle.
    fcntl = None
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from core.settings import data_dir
from services import actual_bridge

VERSION = "26.7.0"
MIN_UPGRADABLE_VERSION = "26.7.0"
MIN_NODE_VERSION = (22, 12, 0)
SERVICE_ID = "actual"
DEFAULT_PORT = 5007
LICENSE = "MIT"
REVIEWED_ON = "2026-07-18"
_ARTIFACT_CACHE_LOCK = threading.Lock()
_ARTIFACT_DIGEST_CACHE: dict[str, tuple[tuple, str, int]] = {}
_CHILDREN: dict[int, subprocess.Popen] = {}
_BACKUP_ID = re.compile(r"^actual-[0-9TZ-]{16,24}-[a-f0-9]{8}$")


class ManagedActualError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        details: dict | None = None,
        staging_possible: bool = True,
    ):
        super().__init__(message)
        self.details = dict(details or {})
        self.staging_possible = staging_possible


class ManagedActualRollback(ManagedActualError):
    pass


class ManagedActualColdState(ManagedActualError):
    pass


def root_dir() -> Path:
    return data_dir() / "services" / SERVICE_ID


class _InterprocessRLock:
    """Reentrant lifecycle lock shared by every Alles process for this data root."""

    def __init__(self):
        self._thread_lock = threading.RLock()
        self._state = threading.local()
        register_at_fork = getattr(os, "register_at_fork", None)
        if callable(register_at_fork):
            register_at_fork(after_in_child=self._reset_after_fork)

    def _reset_after_fork(self) -> None:
        self._thread_lock = threading.RLock()
        self._state = threading.local()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.release()

    def acquire(self) -> None:
        self._thread_lock.acquire()
        lock_fd = None
        root_fd = None
        try:
            if fcntl is None:
                raise ManagedActualError("managed Actual lifecycle is unavailable on this platform")
            depth = getattr(self._state, "depth", 0)
            if depth:
                self._state.depth = depth + 1
                return
            root = root_dir()
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            root_fd = os.open(
                root,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            )
            root_state = os.fstat(root_fd)
            if not stat.S_ISDIR(root_state.st_mode) or root_state.st_uid != os.geteuid():
                raise ManagedActualError("managed Actual service root is unsafe")
            lock_fd = os.open(
                ".operation.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_fd,
            )
            lock_state = os.fstat(lock_fd)
            if (
                not stat.S_ISREG(lock_state.st_mode)
                or lock_state.st_uid != os.geteuid()
                or lock_state.st_nlink != 1
            ):
                raise ManagedActualError("managed Actual lifecycle lock is unsafe")
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            self._state.fd = lock_fd
            self._state.depth = 1
        except Exception:
            if lock_fd is not None:
                os.close(lock_fd)
            self._thread_lock.release()
            raise
        finally:
            if root_fd is not None:
                os.close(root_fd)

    def release(self) -> None:
        depth = getattr(self._state, "depth", 0)
        if depth <= 0:
            raise RuntimeError("managed Actual lifecycle lock is not held")
        try:
            if depth > 1:
                self._state.depth = depth - 1
                return
            lock_fd = self._state.fd
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
                del self._state.fd
                del self._state.depth
        finally:
            self._thread_lock.release()


_SERVICE_LOCK = _InterprocessRLock()


def app_dir() -> Path:
    return root_dir() / "app"


def server_data_dir() -> Path:
    return root_dir() / "server-data"


def client_data_dir() -> Path:
    return root_dir() / "client-data"


def migration_exports_dir() -> Path:
    return root_dir() / "migration-exports"


def backups_dir() -> Path:
    return root_dir() / "backups"


def auth_file() -> Path:
    # Lives inside server-data so every cold backup and restore keeps the password
    # synchronized with Actual's hashed server credential database.
    return server_data_dir() / ".alles-managed-auth.json"


def rollback_manifest_file() -> Path:
    return root_dir() / ".rollback-manifest.json"


def managed_port() -> int:
    raw = os.environ.get("ALLES_ACTUAL_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise ManagedActualError("ALLES_ACTUAL_PORT must be a valid port") from exc
    if not 1024 <= port <= 65535:
        raise ManagedActualError("ALLES_ACTUAL_PORT must be between 1024 and 65535")
    return port


def managed_url() -> str:
    return f"http://127.0.0.1:{managed_port()}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_BUNDLE_FILES = ("package.json", "package-lock.json", "bridge.mjs", "THIRD_PARTY.md")


def _bundle_digest_at(root: Path) -> str:
    digest = hashlib.sha256()
    for name in _BUNDLE_FILES:
        source = root / name
        if source.is_symlink() or not source.is_file():
            raise ManagedActualError("managed Actual bundle is incomplete or unsafe")
        digest.update(name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def _bundle_digest() -> str:
    return _bundle_digest_at(actual_bridge.integration_dir())


def _installed_bundle_digest() -> str:
    try:
        return _bundle_digest_at(app_dir())
    except (ManagedActualError, OSError):
        return ""


def _unsymlinked_artifact(
    root: Path,
    parts: tuple[str, ...],
    *,
    directory: bool,
) -> bool:
    path = root
    if path.is_symlink():
        return False
    for part in parts:
        path /= part
        if path.is_symlink():
            return False
    return path.is_dir() if directory else path.is_file()


def _install_artifacts_at(root: Path) -> bool:
    return _unsymlinked_artifact(
        root,
        ("node_modules", "@actual-app", "api"),
        directory=True,
    ) and _unsymlinked_artifact(
        root,
        (
            "node_modules",
            "@actual-app",
            "sync-server",
            "build",
            "bin",
            "actual-server.js",
        ),
        directory=False,
    )


def _artifact_signature(root: Path, files: list[Path]) -> tuple:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            stat.st_dev,
            stat.st_ino,
            stat.st_mode,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
        for path in files
        for stat in (path.stat(follow_symlinks=False),)
    )


def _artifact_digest_at(root: Path) -> tuple[str, int]:
    """Hash every installed file, caching only while its unforgeable stat tuple is stable."""
    if root.is_symlink() or not root.is_dir():
        raise ManagedActualError("managed Actual app directory is incomplete or unsafe")
    files = list(_walk_files(root))
    signature = _artifact_signature(root, files)
    cache_key = str(root.resolve())
    with _ARTIFACT_CACHE_LOCK:
        cached = _ARTIFACT_DIGEST_CACHE.get(cache_key)
    if cached and cached[0] == signature:
        return cached[1], cached[2]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        with path.open("rb") as handle:
            digest.update(hashlib.file_digest(handle, "sha256").digest())
    verified_files = list(_walk_files(root))
    if [path.relative_to(root) for path in verified_files] != [
        path.relative_to(root) for path in files
    ] or _artifact_signature(root, verified_files) != signature:
        raise ManagedActualError("managed Actual app changed during integrity verification")
    value = digest.hexdigest()
    with _ARTIFACT_CACHE_LOCK:
        _ARTIFACT_DIGEST_CACHE[cache_key] = (signature, value, len(files))
    return value, len(files)


def _manifest(artifact_root: Path | None = None) -> dict:
    install_sha256, install_files = _artifact_digest_at(artifact_root or app_dir())
    return {
        "managed_by": "alles",
        "service_id": SERVICE_ID,
        "version": VERSION,
        "bind": f"127.0.0.1:{managed_port()}",
        "license": LICENSE,
        "reviewed_on": REVIEWED_ON,
        "bundle_sha256": _bundle_digest(),
        "install_sha256": install_sha256,
        "install_files": install_files,
        "dependencies": {
            "@actual-app/api": VERSION,
            "@actual-app/cli": VERSION,
            "@actual-app/sync-server": VERSION,
        },
    }


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_root() -> Path:
    root = root_dir()
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ManagedActualError("existing Actual service root is unsafe")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _ensure_managed_data_directories(*, create: bool = True) -> tuple[Path, ...]:
    """Reject links and non-directories before managed Actual can read or write data."""
    root = _safe_root() if create else root_dir()
    if not create and (root.is_symlink() or (root.exists() and not root.is_dir())):
        raise ManagedActualError("existing Actual service root is unsafe")
    paths = (
        root / "server-data",
        root / "client-data",
        root / "migration-exports",
        root / "backups",
    )
    for path in paths:
        if path.is_symlink():
            raise ManagedActualError(
                f"managed Actual data directory is an unsafe symlink: {path.name}"
            )
        if path.exists() and not path.is_dir():
            raise ManagedActualError(f"managed Actual data directory is unsafe: {path.name}")
        if create:
            path.mkdir(parents=False, exist_ok=True, mode=0o700)
            if path.is_symlink() or not path.is_dir():
                raise ManagedActualError(f"managed Actual data directory is unsafe: {path.name}")
    return paths


def _managed_password() -> str:
    value = _read_json(auth_file()).get("password")
    if not isinstance(value, str) or len(value) < 32:
        raise ManagedActualError("managed Actual authentication is unavailable")
    return value


def _bootstrap_listener_owned() -> bool:
    pid = _owned_pid()
    return bool(pid is not None and _listener_owned_by(pid))


def _ensure_bootstrap(*, client=httpx, ownership_check=_bootstrap_listener_owned) -> None:
    _ensure_managed_data_directories()
    if not ownership_check():
        raise ManagedActualError("managed Actual bootstrap listener ownership could not be proven")
    try:
        response = client.get(
            f"{managed_url()}/account/needs-bootstrap", timeout=5, follow_redirects=False
        )
        response.raise_for_status()
        payload = response.json()
        bootstrapped = bool(payload.get("data", {}).get("bootstrapped"))
    except Exception as exc:
        raise ManagedActualError("managed Actual bootstrap status is unavailable") from exc
    existing = _read_json(auth_file()).get("password")
    has_managed_password = isinstance(existing, str) and len(existing) >= 32
    if bootstrapped:
        if not has_managed_password:
            raise ManagedActualError(
                "managed Actual is bootstrapped but its Alles authentication file is missing; restore a verified backup"
            )
        return
    password = existing if has_managed_password else secrets.token_urlsafe(48)
    if not has_managed_password:
        _atomic_json(auth_file(), {"version": 1, "password": password})
    try:
        if not ownership_check():
            raise ManagedActualError("managed Actual bootstrap listener ownership changed")
        response = client.post(
            f"{managed_url()}/account/bootstrap",
            json={"password": password},
            timeout=15,
            follow_redirects=False,
        )
        response.raise_for_status()
        if response.json().get("status") != "ok":
            raise ManagedActualError("managed Actual bootstrap was rejected")
    except ManagedActualError:
        raise
    except Exception as exc:
        raise ManagedActualError("managed Actual bootstrap failed") from exc


def _node_status(*, runner=subprocess.run) -> dict:
    try:
        result = runner(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=actual_bridge._environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "version": ""}
    version = str(result.stdout or "").strip().lstrip("v")
    parsed = _node_version_tuple(version)
    supported = bool(result.returncode == 0 and parsed and parsed >= MIN_NODE_VERSION)
    return {"available": supported, "version": version[:40]}


def _probe() -> bool:
    try:
        response = httpx.get(f"{managed_url()}/health", timeout=3, follow_redirects=False)
        return response.status_code == 200 and response.json().get("status") == "UP"
    except Exception:
        return False


def _linux_listener_inodes(port: int, *, proc_root: Path = Path("/proc")) -> set[str] | None:
    """Read loopback LISTEN socket identities without depending on lsof."""
    wanted_port = f"{port:04X}"
    loopbacks = {
        "0100007F",
        "00000000000000000000000001000000",
    }
    inodes: set[str] = set()
    read_any = False
    for table in (proc_root / "net" / "tcp", proc_root / "net" / "tcp6"):
        try:
            lines = table.read_text("ascii").splitlines()[1:]
        except OSError:
            continue
        read_any = True
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            address, separator, encoded_port = fields[1].partition(":")
            if separator and encoded_port.upper() == wanted_port and address.upper() in loopbacks:
                inodes.add(fields[9])
    return inodes if read_any else None


def _linux_listener_pids(
    inodes: set[str],
    *,
    proc_root: Path = Path("/proc"),
) -> set[int] | None:
    if not inodes:
        return set()
    remaining = set(inodes)
    found: set[int] = set()
    for process in proc_root.glob("[0-9]*"):
        if not process.name.isdigit():
            continue
        try:
            descriptors = list((process / "fd").iterdir())
        except OSError:
            continue
        owned = set()
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            match = re.fullmatch(r"socket:\[(\d+)\]", target)
            if match and match.group(1) in inodes:
                owned.add(match.group(1))
        if owned:
            found.add(int(process.name))
            remaining.difference_update(owned)
    return found if not remaining else None


def _listener_owned_by(pid: int, *, runner=subprocess.run) -> bool:
    """Prove the managed child, not another loopback process, owns the configured listener."""
    if sys.platform.startswith("linux"):
        inodes = _linux_listener_inodes(managed_port())
        if inodes is None:
            return False
        owners = _linux_listener_pids(inodes)
        return owners == {pid}
    try:
        result = runner(
            [
                "lsof",
                "-nP",
                "-a",
                "-p",
                str(pid),
                f"-iTCP:{managed_port()}",
                "-sTCP:LISTEN",
                "-Fpn",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    lines = {line.strip() for line in str(result.stdout or "").splitlines()}
    return (
        result.returncode == 0
        and f"p{pid}" in lines
        and any(
            line.startswith("n127.0.0.1:") and line.endswith(f":{managed_port()}") for line in lines
        )
    )


def _listener_pids(*, runner=subprocess.run) -> set[int] | None:
    """Return every listener on the managed port, or ``None`` when absence is unknowable."""
    if sys.platform.startswith("linux"):
        inodes = _linux_listener_inodes(managed_port())
        return None if inodes is None else _linux_listener_pids(inodes)
    try:
        result = runner(
            [
                "lsof",
                "-nP",
                f"-iTCP:{managed_port()}",
                "-sTCP:LISTEN",
                "-Fp",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    if result.returncode == 1 and not stdout and not stderr:
        return set()
    if result.returncode != 0 or stderr:
        return None
    return {
        int(line[1:])
        for line in stdout.splitlines()
        if line.startswith("p") and line[1:].isdigit() and int(line[1:]) > 1
    }


def _managed_server_pids(*, runner=subprocess.run) -> set[int] | None:
    """Find markerless processes whose entrypoint is the exact managed server script."""
    try:
        result = runner(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    expected = str(
        (
            app_dir()
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        ).resolve()
    )
    matches = set()
    for line in str(result.stdout or "").splitlines():
        match = re.match(r"\s*(\d+)\s+(.+)$", line)
        if match and int(match[1]) > 1 and _command_owns_script(match[2], expected):
            matches.add(int(match[1]))
    return matches


def _cold_operation_absent() -> bool:
    listeners = _listener_pids()
    servers = _managed_server_pids()
    return listeners == set() and servers == set()


def _require_cold_operation_absent(check) -> None:
    if not check():
        raise ManagedActualColdState(
            "managed Actual listener and process absence could not be proven"
        )


def _process_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _process_command(pid: int) -> tuple[str, ...] | str:
    proc = Path("/proc") / str(pid) / "cmdline"
    try:
        if proc.is_file():
            return tuple(
                value.decode("utf-8", "replace")
                for value in proc.read_bytes().split(b"\0")
                if value
            )
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _owned_pid(*, process_alive=_process_alive, process_command=_process_command) -> int | None:
    marker = _read_json(root_dir() / "server.pid.json")
    try:
        pid = int(marker.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    if not process_alive(pid):
        return None
    expected = str(
        (
            app_dir()
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        ).resolve()
    )
    if marker.get("server_script") != expected:
        return None
    command = process_command(pid)
    if not command or not _command_owns_script(command, expected):
        return None
    return pid


def _command_owns_script(command: tuple[str, ...] | list[str] | str, expected: str) -> bool:
    """Require the exact managed script as Node's entrypoint argument."""

    def is_node(value: str) -> bool:
        return Path(str(value or "")).name == "node"

    def is_expected(value: str) -> bool:
        if not str(value or "").startswith("/"):
            return False
        try:
            return str(Path(value).resolve()) == expected
        except OSError:
            return False

    if isinstance(command, str):
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = []
        if len(tokens) >= 2 and is_node(tokens[0]) and is_expected(tokens[1]):
            return True
        # macOS ps can flatten an unquoted script path containing spaces. Only
        # rebuild argv[1], never scan later arguments where an unrelated process
        # could merely mention the managed path.
        words = command.split()
        if not words or not is_node(words[0]):
            return False
        return any(is_expected(" ".join(words[1:end])) for end in range(2, len(words) + 1))
    tokens = list(command)
    return len(tokens) >= 2 and is_node(tokens[0]) and is_expected(tokens[1])


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, match.groups())) if match else None


def _node_version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", str(value or "").strip())
    return tuple(map(int, match.groups())) if match else None


def _supported_installed_version(value: str) -> bool:
    candidate = _version_tuple(value)
    floor = _version_tuple(MIN_UPGRADABLE_VERSION)
    target = _version_tuple(VERSION)
    return bool(candidate and floor and target and floor <= candidate <= target)


def _managed_install_claim(manifest: dict | None = None) -> bool:
    manifest = manifest if manifest is not None else _read_json(root_dir() / "manifest.json")
    return (
        manifest.get("managed_by") == "alles"
        and manifest.get("service_id") == SERVICE_ID
        and _supported_installed_version(manifest.get("version"))
    )


def _trusted_app_at(root: Path, manifest: dict) -> bool:
    try:
        install_sha256, install_files = _artifact_digest_at(root)
        return (
            _managed_install_claim(manifest)
            and _bundle_digest_at(root) == str(manifest.get("bundle_sha256") or "")
            and install_sha256 == str(manifest.get("install_sha256") or "")
            and install_files == int(manifest.get("install_files", -1))
            and _install_artifacts_at(root)
        )
    except (ManagedActualError, OSError, TypeError, ValueError):
        return False


def _trusted_install() -> bool:
    manifest = _read_json(root_dir() / "manifest.json")
    return _trusted_app_at(app_dir(), manifest)


def status(
    *,
    probe=_probe,
    process_alive=_process_alive,
    node_status=_node_status,
    listener_owner=_listener_owned_by,
    trusted_install: bool | None = None,
) -> dict:
    node = node_status()
    manifest = _read_json(root_dir() / "manifest.json")
    installed = _trusted_install() if trusted_install is None else trusted_install
    installed_version = str(manifest.get("version") or "") if installed else ""
    pid = _owned_pid(process_alive=process_alive) if installed else None
    running = pid is not None
    return {
        "service_id": SERVICE_ID,
        "installed": installed,
        "owned": installed,
        "available": bool(node.get("available")),
        "node_version": node.get("version", ""),
        "version": installed_version or VERSION,
        "target_version": VERSION,
        "bind": f"127.0.0.1:{managed_port()}",
        "url": managed_url(),
        "running": running,
        "healthy": bool(running and listener_owner(pid) and probe()),
        "data_kept": server_data_dir().is_dir(),
        "actions": ["start", "stop", "restart", "update", "rollback", "backup", "restore"]
        if installed
        else ["install"],
    }


def _copy_bundle(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name in ("package.json", "package-lock.json", "bridge.mjs", "THIRD_PARTY.md"):
        shutil.copy2(actual_bridge.integration_dir() / name, destination / name)


def _remove_install_executable_links(destination: Path) -> None:
    """Remove npm's script-only .bin links and reject every other installed symlink."""
    bin_directories = sorted(
        (path for path in destination.rglob(".bin")),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in bin_directories:
        if path.is_symlink() or not path.is_dir():
            raise ManagedActualError("installed Actual contains an unsafe executable link")
        shutil.rmtree(path)
    for path in destination.rglob("*"):
        if path.is_symlink():
            raise ManagedActualError("installed Actual contains an unsafe symlink")


def _install_candidate(
    destination: Path, *, runner=subprocess.run, bridge_call=actual_bridge.call
) -> dict:
    _copy_bundle(destination)
    result = runner(
        ["npm", "ci", "--omit=dev", "--no-audit", "--no-fund"],
        cwd=destination,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        env=actual_bridge._environment(),
    )
    if result.returncode != 0:
        raise ManagedActualError("pinned Actual dependency installation failed")
    _remove_install_executable_links(destination)
    versions = bridge_call({"command": "versions"}, script=destination / "bridge.mjs", timeout=30)
    if any(versions.get(key) != VERSION for key in ("api", "cli", "sync_server")):
        raise ManagedActualError("installed Actual versions do not match the reviewed lock")
    node_version = _node_version_tuple(versions.get("node", ""))
    if node_version is None:
        raise ManagedActualError("installed Node version is invalid")
    if node_version < MIN_NODE_VERSION:
        raise ManagedActualError("Actual requires Node 22.12 or newer")
    return versions


def install(
    *,
    runner=subprocess.run,
    bridge_call=actual_bridge.call,
    start_fn=None,
    stop_fn=None,
) -> dict:
    with _SERVICE_LOCK:
        start_service = start_fn or start
        stop_service = stop_fn or stop
        node = _node_status(runner=runner)
        if not node["available"]:
            raise ManagedActualError("Node 22 or newer is required for managed Actual")
        root = _safe_root()
        _ensure_managed_data_directories()
        if _trusted_install():
            current = status()
            if not current["healthy"]:
                (start_fn or start)()
            _ensure_bootstrap()
            return status()
        managed_existing = _managed_install_claim()
        if app_dir().exists() and not managed_existing:
            raise ManagedActualError("existing untrusted Actual app directory was not replaced")
        operation_id = uuid.uuid4().hex
        candidate = root / f".install-{operation_id}"
        previous_app = root / f".repair-app-previous-{operation_id}"
        previous_manifest = root / f".repair-manifest-previous-{operation_id}.json"
        manifest_file = root / "manifest.json"
        repairing = app_dir().exists()
        previous_stashed = False
        published = False
        repair_was_running = False
        repair_stop_attempted = False
        repair_stopped = False
        try:
            _install_candidate(candidate, runner=runner, bridge_call=bridge_call)
            if repairing:
                repair_was_running = _owned_pid() is not None
                if repair_was_running:
                    repair_stop_attempted = True
                    stop_service()
                    repair_stopped = True
                _require_cold_operation_absent(_cold_operation_absent)
                _replace_pair(app_dir(), manifest_file, previous_app, previous_manifest)
                previous_stashed = True
            os.replace(candidate, app_dir())
            published = True
            _ensure_managed_data_directories()
            _atomic_json(manifest_file, _manifest())
        except Exception:
            recovery_error = None
            try:
                if published:
                    _remove_path(app_dir())
                    manifest_file.unlink(missing_ok=True)
                if previous_stashed:
                    _replace_pair(previous_app, previous_manifest, app_dir(), manifest_file)
            except Exception as rollback_exc:
                recovery_error = rollback_exc
            if recovery_error is None and repair_was_running:
                still_running = _owned_pid() is not None
                if repair_stopped or (repair_stop_attempted and not still_running):
                    try:
                        start_service()
                    except Exception as restart_exc:
                        recovery_error = restart_exc
            if recovery_error is not None:
                raise ManagedActualRollback(
                    "Actual repair failed and the previous managed app could not fully recover"
                ) from recovery_error
            raise
        finally:
            if candidate.exists():
                shutil.rmtree(candidate)
        try:
            start_service()
            _ensure_bootstrap()
        except Exception as exc:
            recovery_error = None
            try:
                stop_service()
            except Exception as stop_exc:
                if _owned_pid() is not None:
                    recovery_error = stop_exc
            if recovery_error is None:
                try:
                    _require_cold_operation_absent(_cold_operation_absent)
                except Exception as absence_exc:
                    recovery_error = absence_exc
            restored_previous = False
            if repairing and previous_stashed and recovery_error is None:
                try:
                    _remove_path(app_dir())
                    manifest_file.unlink(missing_ok=True)
                    _replace_pair(previous_app, previous_manifest, app_dir(), manifest_file)
                    previous_stashed = False
                    restored_previous = True
                    if repair_was_running:
                        start_service()
                except Exception as rollback_exc:
                    recovery_error = rollback_exc
            if recovery_error is not None:
                raise ManagedActualRollback(
                    "Actual repair failed and recovery was incomplete; the previous app was preserved"
                ) from recovery_error
            if restored_previous:
                raise ManagedActualRollback(
                    "Actual repair failed and the previous managed app was restored"
                ) from exc
            raise
        if previous_stashed:
            _cleanup_best_effort(previous_app, previous_manifest)
        return status()


def _server_environment() -> dict[str, str]:
    env = actual_bridge._environment()
    env.update(
        {
            "ACTUAL_DATA_DIR": str(server_data_dir()),
            "ACTUAL_PORT": str(managed_port()),
            "ACTUAL_HOSTNAME": "127.0.0.1",
            "NODE_ENV": "production",
        }
    )
    return env


def start(
    *,
    popen=subprocess.Popen,
    probe=_probe,
    sleep=time.sleep,
    listener_owner=_listener_owned_by,
) -> dict:
    with _SERVICE_LOCK:
        current = status(probe=probe, listener_owner=listener_owner)
        if not current["installed"]:
            raise ManagedActualError("managed Actual is not installed", staging_possible=False)
        _ensure_managed_data_directories()
        if current["healthy"]:
            return current
        if current["running"]:
            stop()
        script = (
            app_dir()
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        )
        if not script.is_file():
            raise ManagedActualError("managed Actual server entrypoint is missing")
        log_path = root_dir() / "server.log"
        if log_path.is_file() and log_path.stat().st_size > 5 * 1024 * 1024:
            os.replace(log_path, root_dir() / "server.log.previous")
        log = log_path.open("ab")
        try:
            process = popen(
                ["node", str(script)],
                cwd=app_dir(),
                env=_server_environment(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()
        _CHILDREN[process.pid] = process
        marker = root_dir() / "server.pid.json"
        try:
            _atomic_json(
                marker,
                {
                    "pid": process.pid,
                    "server_script": str(script.resolve()),
                    "started_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            try:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            finally:
                _CHILDREN.pop(process.pid, None)
                marker.unlink(missing_ok=True)
            raise ManagedActualError(
                "managed Actual PID ownership marker could not be persisted"
            ) from exc
        for _attempt in range(120):
            if listener_owner(process.pid) and probe():
                return status(
                    probe=lambda: True,
                    listener_owner=lambda pid: pid == process.pid,
                )
            if process.poll() is not None:
                break
            sleep(0.25)
        try:
            stop()
        except ManagedActualError:
            pass
        raise ManagedActualError("managed Actual started but failed loopback health")


def stop(*, process_alive=_process_alive, sleep=time.sleep) -> dict:
    with _SERVICE_LOCK:
        pid = _owned_pid(process_alive=process_alive)
        marker = root_dir() / "server.pid.json"
        if pid is None:
            marker.unlink(missing_ok=True)
            return {"ok": True, "action": "stop", "running": False}
        child = _CHILDREN.pop(pid, None)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            if child is not None:
                child.wait(timeout=1)
            marker.unlink(missing_ok=True)
            return {"ok": True, "action": "stop", "running": False}
        except OSError as exc:
            raise ManagedActualError("managed Actual could not be stopped") from exc
        for _attempt in range(100):
            if child is not None and child.poll() is not None:
                child.wait(timeout=1)
                marker.unlink(missing_ok=True)
                return {"ok": True, "action": "stop", "running": False}
            if not process_alive(pid):
                if child is not None:
                    child.wait(timeout=1)
                marker.unlink(missing_ok=True)
                return {"ok": True, "action": "stop", "running": False}
            sleep(0.1)
        already_gone = False
        owned_after_term = _owned_pid(process_alive=process_alive)
        if owned_after_term == pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                already_gone = True
        elif process_alive(pid):
            if child is not None:
                _CHILDREN[pid] = child
            raise ManagedActualError("managed Actual ownership changed before it stopped")
        if child is not None:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired as exc:
                _CHILDREN[pid] = child
                raise ManagedActualError("managed Actual did not exit after it was killed") from exc
        elif not already_gone:
            for _attempt in range(50):
                if not process_alive(pid):
                    break
                sleep(0.1)
            else:
                raise ManagedActualError("managed Actual did not exit after it was killed")
        marker.unlink(missing_ok=True)
        return {"ok": True, "action": "stop", "running": False}


def control(action: str) -> dict:
    with _SERVICE_LOCK:
        if action == "start":
            return start()
        if action == "stop":
            stop()
            return status(probe=lambda: False)
        if action == "restart":
            stop()
            return start()
        raise ManagedActualError("unsupported managed Actual action")


def bridge_request(request: dict, *, timeout: int = 120, bridge_call=actual_bridge.call) -> dict:
    with _SERVICE_LOCK:
        trusted_install = _trusted_install()
        if not trusted_install:
            raise ManagedActualError("managed Actual is not installed")
        _ensure_managed_data_directories()
        # Reuse the integrity result while this lifecycle lock is held. Calling
        # status() without it would recursively scan the full node_modules tree
        # a second time for every canonical Finance request.
        if not status(trusted_install=trusted_install)["healthy"]:
            raise ManagedActualError("managed Actual is not healthy", staging_possible=False)
        payload = {
            **request,
            "server_url": managed_url(),
            "data_dir": str(client_data_dir()),
            "password": str(
                request.get("password")
                or _managed_password()
                or os.environ.get("ALLES_ACTUAL_PASSWORD", "")
            ),
        }
        try:
            return bridge_call(payload, script=app_dir() / "bridge.mjs", timeout=timeout)
        except actual_bridge.ActualBridgeError as exc:
            raise ManagedActualError(
                str(exc),
                details=exc.details,
                staging_possible=exc.code
                not in {
                    "actual_bridge_unavailable",
                    "actual_bridge_invalid",
                    "actual_bridge_too_large",
                    "actual_stage_cleanup_verified",
                },
            ) from exc


def _walk_files(root: Path):
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ManagedActualError("managed Actual data contains an unsafe symlink")
        if path.is_file():
            yield path


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _cleanup_best_effort(*paths: Path) -> list[str]:
    pending = []
    for path in paths:
        try:
            _remove_path(path)
        except Exception:
            pending.append(path.name)
    return pending


def _replace_pair(
    source_app: Path,
    source_manifest: Path,
    target_app: Path,
    target_manifest: Path,
) -> None:
    """Move an app and its manifest together, reverting the first move on failure."""
    os.replace(source_app, target_app)
    try:
        os.replace(source_manifest, target_manifest)
    except Exception:
        os.replace(target_app, source_app)
        raise


def _backup_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    return f"actual-{stamp}-{uuid.uuid4().hex[:8]}"


def _restart_after_cold_abort(
    status_fn,
    start_fn,
    cold_absent,
    failure_message: str = "backup aborted and the original service could not recover",
) -> None:
    """Restore an owned pre-operation service only after absence is proven again."""
    try:
        safe_to_restart = cold_absent()
    except Exception:
        safe_to_restart = False
    if not safe_to_restart:
        return
    _recover_running_service(
        status_fn,
        start_fn,
        failure_message,
    )


def backup(*, status_fn=status, stop_fn=stop, start_fn=start, absence_check=None) -> dict:
    with _SERVICE_LOCK:
        cold_absent = absence_check or _cold_operation_absent
        _ensure_managed_data_directories()
        was_running = bool(status_fn().get("running"))
        if was_running:
            try:
                stop_fn()
            except Exception:
                _recover_running_service(
                    status_fn,
                    start_fn,
                    "backup stop failed and the original service could not recover",
                )
                raise
        backup_id = ""
        partial = None
        files = {}
        cold_aborted = False
        try:
            _require_cold_operation_absent(cold_absent)
            backup_id = _backup_id()
            partial = backups_dir() / f".{backup_id}.partial"
            target = backups_dir() / backup_id
            partial.mkdir(parents=True, exist_ok=False, mode=0o700)
            for source_root, name in (
                (server_data_dir(), "server-data"),
                (client_data_dir(), "client-data"),
                (migration_exports_dir(), "migration-exports"),
            ):
                _require_cold_operation_absent(cold_absent)
                if source_root.exists():
                    if source_root.is_symlink():
                        raise ManagedActualError("managed Actual data contains an unsafe symlink")
                    # Preserve links during the copy and reject them again in the
                    # private target. A link introduced after the source walk must
                    # never be followed outside the managed root.
                    list(_walk_files(source_root))
                    shutil.copytree(source_root, partial / name, symlinks=True)
                    for path in _walk_files(partial / name):
                        relative = path.relative_to(partial).as_posix()
                        files[relative] = {"sha256": _sha(path), "size": path.stat().st_size}
            _require_cold_operation_absent(cold_absent)
            _atomic_json(
                partial / "manifest.json",
                {
                    "version": 1,
                    "service_version": VERSION,
                    "backup_id": backup_id,
                    "created_at": datetime.now(UTC).isoformat(),
                    "files": files,
                },
            )
            os.replace(partial, target)
        except ManagedActualColdState:
            cold_aborted = True
            raise
        finally:
            if partial is not None and partial.exists():
                shutil.rmtree(partial)
            if was_running:
                if cold_aborted:
                    _restart_after_cold_abort(status_fn, start_fn, cold_absent)
                else:
                    start_fn()
        return {"ok": True, "backup_id": backup_id, "files": len(files)}


def _recover_running_service(status_fn, start_fn, failure_message: str) -> None:
    """Best-effort restoration after a stop call reports an uncertain outcome."""
    try:
        if status_fn().get("running"):
            return
    except Exception:
        # An unreadable status is uncertain, so an idempotent start remains the
        # safest attempt to restore the pre-operation running state.
        pass
    try:
        start_fn()
    except Exception as exc:
        raise ManagedActualRollback(failure_message) from exc


def _verify_backup_folder(folder: Path, backup_id: str, manifest: dict) -> int:
    if _read_json(folder / "manifest.json") != manifest:
        raise ManagedActualError("Actual backup manifest changed during verification")
    if manifest.get("backup_id") != backup_id or manifest.get("version") != 1:
        raise ManagedActualError("Actual backup manifest is invalid")
    expected = manifest.get("files")
    if not isinstance(expected, dict):
        raise ManagedActualError("Actual backup file inventory is invalid")
    seen = set()
    for path in _walk_files(folder):
        relative = path.relative_to(folder).as_posix()
        if relative == "manifest.json":
            continue
        seen.add(relative)
        record = expected.get(relative)
        if not isinstance(record, dict) or record.get("sha256") != _sha(path):
            raise ManagedActualError("Actual backup file hash does not match")
        if record.get("size") != path.stat().st_size:
            raise ManagedActualError("Actual backup file size does not match")
    if seen != set(expected):
        raise ManagedActualError("Actual backup file inventory does not match")
    return len(seen)


def verify_backup(backup_id: str) -> dict:
    _ensure_managed_data_directories(create=False)
    if not _BACKUP_ID.fullmatch(str(backup_id or "")):
        raise ManagedActualError("invalid Actual backup id")
    folder = backups_dir() / backup_id
    if folder.is_symlink() or not folder.is_dir():
        raise ManagedActualError("Actual backup was not found")
    manifest = _read_json(folder / "manifest.json")
    files = _verify_backup_folder(folder, backup_id, manifest)
    return {
        "ok": True,
        "backup_id": backup_id,
        "files": files,
        "folder": folder,
        "manifest": manifest,
    }


def restore(
    backup_id: str,
    *,
    verify_fn,
    status_fn=status,
    stop_fn=stop,
    start_fn=start,
    absence_check=None,
) -> dict:
    with _SERVICE_LOCK:
        cold_absent = absence_check or _cold_operation_absent
        verified = verify_backup(backup_id)
        folder = root_dir() / f".restore-source-{uuid.uuid4().hex}"
        previous = root_dir() / f".restore-previous-{uuid.uuid4().hex}"
        names = ("server-data", "client-data", "migration-exports")
        recovery = None
        result = None
        was_running = False
        service_stopped = False
        swap_started = False
        service_started = False
        restore_succeeded = False
        rollback_succeeded = False
        cleanup_pending = []
        swapped_names = []
        try:
            try:
                # Anchor the expected manifest in memory, then copy without
                # following links and verify the private snapshot. Live data is
                # untouched until this immutable source is proven complete.
                shutil.copytree(verified["folder"], folder, symlinks=True)
                _verify_backup_folder(folder, backup_id, verified["manifest"])
            except ManagedActualError:
                raise
            except Exception as exc:
                raise ManagedActualError("Actual backup could not be staged for restore") from exc
            was_running = bool(status_fn().get("running"))
            if was_running:
                try:
                    stop_fn()
                    service_stopped = True
                except Exception:
                    _recover_running_service(
                        status_fn,
                        start_fn,
                        "restore stop failed and the original service could not recover",
                    )
                    raise
            _require_cold_operation_absent(cold_absent)
            try:
                recovery = backup(
                    status_fn=lambda: {"running": False},
                    stop_fn=lambda: None,
                    start_fn=lambda: None,
                    absence_check=cold_absent,
                )
                previous.mkdir(mode=0o700)
            except ManagedActualColdState:
                raise
            except Exception as exc:
                if was_running:
                    try:
                        start_fn()
                        service_stopped = False
                    except Exception as restart_exc:
                        raise ManagedActualRollback(
                            "restore preparation failed and the original service could not restart"
                        ) from restart_exc
                raise ManagedActualRollback(
                    "restore preparation failed; original managed Actual data was unchanged"
                ) from exc
            _require_cold_operation_absent(cold_absent)
            swap_started = True
            for name in names:
                live = root_dir() / name
                if live.exists():
                    os.replace(live, previous / name)
                swapped_names.append(name)
                source = folder / name
                if source.exists():
                    shutil.copytree(source, live)
                else:
                    live.mkdir(mode=0o700)
            start_fn()
            service_started = True
            result = verify_fn()
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise ManagedActualError("restored Actual data failed fresh read-back")
            if not was_running:
                stop_fn()
                service_started = False
            restore_succeeded = True
        except Exception as exc:
            if not swap_started:
                if service_stopped:
                    _restart_after_cold_abort(
                        status_fn,
                        start_fn,
                        cold_absent,
                        "restore aborted and the original service could not recover",
                    )
                raise
            if service_started:
                try:
                    stop_fn()
                    service_started = False
                except Exception as stop_exc:
                    raise ManagedActualRollback(
                        f"restore failed and Actual could not be stopped; prior data remains at {previous.name}"
                    ) from stop_exc
            else:
                try:
                    if status_fn().get("running"):
                        stop_fn()
                except Exception as stop_exc:
                    raise ManagedActualRollback(
                        f"restore failed and Actual stop state is unknown; prior data remains at {previous.name}"
                    ) from stop_exc
            try:
                for name in reversed(swapped_names):
                    live = root_dir() / name
                    _remove_path(live)
                    saved = previous / name
                    if saved.exists():
                        os.replace(saved, live)
                rollback_succeeded = True
            except Exception as rollback_exc:
                raise ManagedActualRollback(
                    f"restore failed and filesystem rollback was incomplete; prior data remains at {previous.name}"
                ) from rollback_exc
            if was_running:
                try:
                    start_fn()
                except Exception as restart_exc:
                    raise ManagedActualRollback(
                        "restore failed; prior data was restored but the service could not restart"
                    ) from restart_exc
            raise ManagedActualRollback(
                "restore failed and the prior managed Actual data was restored"
            ) from exc
        finally:
            if previous.exists() and (restore_succeeded or rollback_succeeded):
                cleanup_pending.extend(_cleanup_best_effort(previous))
            cleanup_pending.extend(_cleanup_best_effort(folder))
        return {
            "ok": True,
            "backup_id": backup_id,
            "recovery_backup_id": recovery["backup_id"],
            "readback": result,
            **({"cleanup_pending": cleanup_pending} if cleanup_pending else {}),
        }


def update(*, runner=subprocess.run, bridge_call=actual_bridge.call) -> dict:
    with _SERVICE_LOCK:
        if not _trusted_install():
            raise ManagedActualError("managed Actual is not installed")
        root = root_dir()
        manifest_file = root / "manifest.json"
        manifest = _read_json(manifest_file)
        if manifest.get("bundle_sha256") == _bundle_digest():
            return {**status(), "update": "up_to_date"}
        was_running = status()["running"]
        operation_id = uuid.uuid4().hex
        candidate = root / f".update-{operation_id}"
        rollback_app = root / ".rollback-app"
        rollback_manifest = rollback_manifest_file()
        previous_app = root / f".rollback-app-previous-{operation_id}"
        previous_manifest = root / f".rollback-manifest-previous-{operation_id}.json"
        previous_app_stashed = False
        previous_manifest_stashed = False
        manifest_stashed = False
        app_stashed = False
        candidate_active = False
        preserve_staged = False
        stop_attempted = False
        service_stopped = False
        cleanup_pending = []
        try:
            _install_candidate(candidate, runner=runner, bridge_call=bridge_call)
            if was_running:
                stop_attempted = True
                stop()
                service_stopped = True
            _require_cold_operation_absent(_cold_operation_absent)
            if rollback_app.exists() and rollback_manifest.exists():
                os.replace(rollback_app, previous_app)
                previous_app_stashed = True
                try:
                    os.replace(rollback_manifest, previous_manifest)
                    previous_manifest_stashed = True
                except Exception:
                    os.replace(previous_app, rollback_app)
                    previous_app_stashed = False
                    raise
            else:
                if rollback_app.exists():
                    shutil.rmtree(rollback_app)
                rollback_manifest.unlink(missing_ok=True)
            _replace_pair(app_dir(), manifest_file, rollback_app, rollback_manifest)
            manifest_stashed = True
            app_stashed = True
            os.replace(candidate, app_dir())
            candidate_active = True
            _atomic_json(manifest_file, _manifest())
            if was_running:
                start()
        except Exception as exc:
            recovery_error = None
            recovery_warnings = []
            replacement_started = app_stashed or candidate_active
            active_app_restored = not app_stashed
            restarted = not was_running
            try:
                if candidate_active:
                    # Never swap files out from under a target process that may
                    # have started before the update failed.
                    try:
                        stop()
                    except Exception as stop_exc:
                        try:
                            _require_cold_operation_absent(_cold_operation_absent)
                        except Exception:
                            raise
                        recovery_warnings.append(stop_exc)
                    else:
                        _require_cold_operation_absent(_cold_operation_absent)
                if candidate_active and app_dir().exists():
                    os.replace(app_dir(), candidate)
                if app_stashed and manifest_stashed:
                    _replace_pair(rollback_app, rollback_manifest, app_dir(), manifest_file)
                    active_app_restored = True
                if previous_app_stashed and previous_app.exists():
                    os.replace(previous_app, rollback_app)
                if previous_manifest_stashed and previous_manifest.exists():
                    os.replace(previous_manifest, rollback_manifest)
                if was_running:
                    if service_stopped or not status().get("running"):
                        start()
                    restarted = True
            except Exception as recovery_exc:
                recovery_error = recovery_exc
                preserve_staged = True
            if recovery_error and not active_app_restored:
                detail = (
                    "Actual update failed and recovery was incomplete; "
                    "the staged previous app was preserved"
                )
            elif recovery_error:
                detail = (
                    "Actual update failed; the active app was restored but recovery was incomplete"
                )
            elif not restarted:
                detail = (
                    "Actual update failed; the active app was restored but could not be restarted"
                )
            elif replacement_started:
                detail = "Actual update failed and the previous locked app was restored"
                if recovery_warnings:
                    detail += " after confirming the replacement service had stopped"
            elif stop_attempted and not service_stopped:
                detail = "Actual update failed before app replacement; the active app stop did not complete"
            else:
                detail = (
                    "Actual update failed before app replacement; the active app was left in place"
                )
            raise ManagedActualRollback(detail) from (recovery_error or exc)
        finally:
            if not preserve_staged:
                cleanup_pending.extend(
                    _cleanup_best_effort(candidate, previous_app, previous_manifest)
                )
        return {
            **status(),
            "update": "updated",
            **({"cleanup_pending": cleanup_pending} if cleanup_pending else {}),
        }


def rollback() -> dict:
    with _SERVICE_LOCK:
        rollback_app = root_dir() / ".rollback-app"
        rollback_manifest = rollback_manifest_file()
        target_manifest = _read_json(rollback_manifest)
        if (
            not rollback_app.is_dir()
            or rollback_app.is_symlink()
            or not rollback_manifest.is_file()
            or target_manifest.get("managed_by") != "alles"
            or target_manifest.get("service_id") != SERVICE_ID
            or not _supported_installed_version(target_manifest.get("version"))
        ):
            raise ManagedActualError("no complete managed Actual app rollback is available")
        if not _trusted_app_at(rollback_app, target_manifest):
            raise ManagedActualError("no complete managed Actual app rollback is available")
        was_running = status()["running"]
        if was_running:
            try:
                stop()
            except Exception as stop_exc:
                try:
                    if not status().get("running"):
                        start()
                except Exception as recovery_exc:
                    raise ManagedActualRollback(
                        "Actual rollback failed before app replacement and the service running state could not be recovered"
                    ) from recovery_exc
                raise ManagedActualRollback(
                    "Actual rollback failed before app replacement; the active app remained in place and its running state was recovered"
                ) from stop_exc
        _require_cold_operation_absent(_cold_operation_absent)
        operation_id = uuid.uuid4().hex
        manifest_file = root_dir() / "manifest.json"
        current_app = root_dir() / f".rollback-current-{operation_id}"
        current_manifest = root_dir() / f".rollback-current-{operation_id}.json"
        current_app_stashed = False
        current_manifest_stashed = False
        target_app_active = False
        target_manifest_active = False
        preserve_staged = False
        cleanup_pending = []
        try:
            _replace_pair(app_dir(), manifest_file, current_app, current_manifest)
            current_app_stashed = True
            current_manifest_stashed = True
            _replace_pair(rollback_app, rollback_manifest, app_dir(), manifest_file)
            target_app_active = True
            target_manifest_active = True
            if was_running:
                start()
            _replace_pair(current_app, current_manifest, rollback_app, rollback_manifest)
            current_app_stashed = False
            current_manifest_stashed = False
        except Exception as exc:
            recovery_errors = []

            def recover(step):
                try:
                    step()
                    return True
                except Exception as recovery_exc:
                    recovery_errors.append(recovery_exc)
                    return False

            target_stopped = True
            if target_app_active and target_manifest_active and was_running:
                recover(stop)
                target_stopped = recover(
                    lambda: _require_cold_operation_absent(_cold_operation_absent)
                )
            if target_manifest_active and target_app_active and target_stopped:
                if recover(
                    lambda: _replace_pair(app_dir(), manifest_file, rollback_app, rollback_manifest)
                ):
                    target_app_active = False
                    target_manifest_active = False
            if (
                current_manifest_stashed
                and current_app_stashed
                and not target_manifest_active
                and not target_app_active
            ):
                if recover(
                    lambda: _replace_pair(current_app, current_manifest, app_dir(), manifest_file)
                ):
                    current_app_stashed = False
                    current_manifest_stashed = False
            preserve_staged = current_app_stashed or current_manifest_stashed
            restarted = not was_running
            if was_running and not preserve_staged:
                restarted = recover(start)
            if preserve_staged:
                detail = "Actual rollback failed and recovery was incomplete; the staged current app was preserved"
            elif not restarted:
                detail = "Actual rollback failed; the current app was restored but could not be restarted"
            elif recovery_errors:
                detail = "Actual rollback failed; the current app was restored and restarted, but recovery reported errors"
            else:
                detail = "Actual rollback failed and the current app was restored"
            raise ManagedActualRollback(detail) from (
                recovery_errors[-1] if recovery_errors else exc
            )
        finally:
            if not preserve_staged:
                cleanup_pending.extend(_cleanup_best_effort(current_app, current_manifest))
        return {
            **status(),
            "update": "rolled_back",
            **({"cleanup_pending": cleanup_pending} if cleanup_pending else {}),
        }
