"""Typed lifecycle controls for services that Alles installed and can prove it owns."""

import hashlib
import json
import os
import platform
import re
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from core.settings import data_dir

Manager = Literal["launchd", "systemd-user", "compose"]
Action = Literal["start", "stop", "restart"]
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_LAUNCHD = re.compile(r"^app\.alles\.[a-z0-9][a-z0-9.-]{0,80}$")
_SYSTEMD = re.compile(r"^alles-[a-z0-9][a-z0-9_-]{0,63}\.service$")
_COMPOSE_PROJECT = re.compile(r"^alles-[a-z0-9][a-z0-9_-]{0,63}$")
_OWNER_FILE = ".alles-owned-service.json"
_ACTIONS = {"start", "stop", "restart"}


class ServiceOwnershipError(RuntimeError):
    pass


class ServiceControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class OwnedService:
    service_id: str
    name: str
    manager: Manager
    root: str
    definition: str
    definition_sha256: str
    owner_id: str
    unit: str = ""
    project: str = ""
    compose_service: str = ""


def _registry_dir() -> Path:
    candidate = data_dir() / "owned-services"
    if candidate.is_symlink():
        raise ServiceOwnershipError("service registry is no longer trusted")
    resolved = candidate.resolve()
    if resolved.parent != data_dir().resolve():
        raise ServiceOwnershipError("service registry is no longer trusted")
    return resolved


def _home_dir() -> Path:
    return Path.home()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_root(path: Path) -> bool:
    resolved = path.resolve()
    return _within(resolved, data_dir().resolve()) or _within(resolved, _project_root().resolve())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _expected_definition(manager: Manager, root: Path, *, unit: str, compose_file: str) -> Path:
    if manager == "launchd":
        if not _LAUNCHD.fullmatch(unit):
            raise ValueError("invalid Alles launchd label")
        return _home_dir() / "Library" / "LaunchAgents" / f"{unit}.plist"
    if manager == "systemd-user":
        if not _SYSTEMD.fullmatch(unit):
            raise ValueError("invalid Alles systemd user unit")
        return _home_dir() / ".config" / "systemd" / "user" / unit
    if compose_file not in {"compose.yaml", "compose.yml", "docker-compose.yml"}:
        raise ValueError("invalid Compose definition name")
    return root / compose_file


def register_owned_service(
    *,
    service_id: str,
    name: str,
    manager: Manager,
    root: Path,
    unit: str = "",
    project: str = "",
    compose_service: str = "",
    compose_file: str = "compose.yaml",
) -> OwnedService:
    """Installer-only registration. The web API never creates ownership markers."""
    if not _ID.fullmatch(service_id):
        raise ValueError("invalid service id")
    if manager not in {"launchd", "systemd-user", "compose"}:
        raise ValueError("invalid service manager")
    if root.is_symlink():
        raise ValueError("service root is outside Alles-owned locations")
    root = root.resolve()
    if not root.is_dir() or not _allowed_root(root):
        raise ValueError("service root is outside Alles-owned locations")
    if manager == "compose":
        if unit:
            raise ValueError("unit is not valid for Compose services")
        if not _COMPOSE_PROJECT.fullmatch(project):
            raise ValueError("invalid Alles Compose project")
        if not _ID.fullmatch(compose_service):
            raise ValueError("invalid Compose service")
    elif project or compose_service:
        raise ValueError("Compose fields are only valid for Compose services")

    definition_path = _expected_definition(manager, root, unit=unit, compose_file=compose_file)
    if not definition_path.is_file() or definition_path.is_symlink():
        raise ValueError("service definition is missing or unsafe")
    definition = definition_path.resolve()
    owner_id = uuid.uuid4().hex
    service = OwnedService(
        service_id=service_id,
        name=((name or "").strip() or service_id)[:120],
        manager=manager,
        root=str(root),
        definition=str(definition),
        definition_sha256=_sha256(definition),
        owner_id=owner_id,
        unit=unit,
        project=project,
        compose_service=compose_service,
    )
    marker = asdict(service)
    _atomic_json(root / _OWNER_FILE, marker)
    _atomic_json(_registry_dir() / f"{service_id}.json", marker)
    return service


def _read_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ServiceOwnershipError("ownership marker is missing or unsafe")
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise ServiceOwnershipError("ownership marker is unreadable") from exc
    if not isinstance(value, dict):
        raise ServiceOwnershipError("ownership marker is invalid")
    return value


def _load(service_id: str) -> OwnedService:
    if not _ID.fullmatch(service_id):
        raise ServiceOwnershipError("invalid service id")
    registry = _read_json(_registry_dir() / f"{service_id}.json")
    try:
        service = OwnedService(**registry)
    except (TypeError, ValueError) as exc:
        raise ServiceOwnershipError("ownership marker is invalid") from exc
    _verify(service)
    return service


def _verify(service: OwnedService) -> None:
    root = Path(service.root)
    if (
        not root.is_absolute()
        or root.is_symlink()
        or root.resolve() != root
        or not _allowed_root(root)
    ):
        raise ServiceOwnershipError("service root is no longer trusted")
    local = _read_json(root / _OWNER_FILE)
    if local != asdict(service):
        raise ServiceOwnershipError("ownership markers do not match")
    definition = Path(service.definition)
    expected_path = _expected_definition(
        service.manager,
        root,
        unit=service.unit,
        compose_file=definition.name,
    )
    if expected_path.is_symlink():
        raise ServiceOwnershipError("service definition is no longer trusted")
    expected = expected_path.resolve()
    if definition != expected or not definition.is_file():
        raise ServiceOwnershipError("service definition is no longer trusted")
    if _sha256(definition) != service.definition_sha256:
        raise ServiceOwnershipError("service definition changed after registration")
    if service.manager == "compose":
        if not _COMPOSE_PROJECT.fullmatch(service.project) or not _ID.fullmatch(
            service.compose_service
        ):
            raise ServiceOwnershipError("Compose ownership fields are invalid")


def _base_command(service: OwnedService) -> list[str]:
    if service.manager == "launchd":
        if platform.system() != "Darwin":
            raise ServiceControlError("launchd is unavailable on this host")
        return ["launchctl"]
    if service.manager == "systemd-user":
        if platform.system() == "Windows":
            raise ServiceControlError("systemd-user is unavailable on this host")
        return ["systemctl", "--user"]
    return [
        "docker",
        "compose",
        "--project-directory",
        service.root,
        "--project-name",
        service.project,
    ]


def _command(service: OwnedService, action: str) -> list[str]:
    if action not in _ACTIONS and action != "status":
        raise ServiceControlError("unsupported service action")
    base = _base_command(service)
    if service.manager == "launchd":
        target = f"gui/{os.getuid()}/{service.unit}"
        if action == "status":
            return [*base, "print", target]
        if action == "start":
            return [*base, "kickstart", target]
        if action == "restart":
            return [*base, "kickstart", "-k", target]
        return [*base, "kill", "SIGTERM", target]
    if service.manager == "systemd-user":
        if action == "status":
            return [*base, "show", service.unit, "--property=ActiveState", "--value"]
        return [*base, action, service.unit]
    if action == "status":
        return [*base, "ps", "--status", "running", "--quiet", service.compose_service]
    return [*base, action, service.compose_service]


def _environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "HOME",
        "TMPDIR",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "DOCKER_HOST",
    )
    return {key: os.environ[key] for key in allowed if os.environ.get(key)}


def _run(command: list[str], *, timeout: int = 20):
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceControlError("service manager is unavailable") from exc


def status(service_id: str, *, runner=_run) -> dict:
    service = _load(service_id)
    try:
        result = runner(_command(service, "status"))
    except (OSError, subprocess.SubprocessError, ServiceControlError):
        return {
            "service_id": service.service_id,
            "name": service.name,
            "manager": service.manager,
            "owned": True,
            "available": False,
            "running": False,
            "actions": [],
        }
    output = (result.stdout or "").strip().lower()
    running = result.returncode == 0
    if service.manager == "systemd-user":
        running = running and output == "active"
    elif service.manager == "compose":
        running = running and bool(output)
    return {
        "service_id": service.service_id,
        "name": service.name,
        "manager": service.manager,
        "owned": True,
        "available": True,
        "running": running,
        "actions": sorted(_ACTIONS),
    }


def control(service_id: str, action: Action, *, runner=None) -> dict:
    service = _load(service_id)
    result = (
        _run(_command(service, action), timeout=60)
        if runner is None
        else runner(_command(service, action))
    )
    if result.returncode != 0:
        raise ServiceControlError(f"{action} failed for the owned service")
    return {"ok": True, "service_id": service.service_id, "action": action}


def unregister_owned_service(service_id: str) -> dict:
    """Remove matching ownership markers only; service data and definitions stay untouched."""
    service = _load(service_id)
    local = Path(service.root) / _OWNER_FILE
    registry = _registry_dir() / f"{service_id}.json"
    local.unlink()
    registry.unlink()
    return {"ok": True, "service_id": service_id, "kept_root": service.root}


def list_services(*, runner=_run) -> list[dict]:
    rows = []
    try:
        root = _registry_dir()
    except ServiceOwnershipError:
        return [
            {
                "service_id": "registry",
                "name": "service registry",
                "manager": "unknown",
                "owned": False,
                "available": False,
                "running": False,
                "actions": [],
            }
        ]
    if not root.is_dir():
        return rows
    for marker in sorted(root.glob("*.json")):
        service_id = marker.stem
        try:
            rows.append(status(service_id, runner=runner))
        except ServiceOwnershipError:
            rows.append(
                {
                    "service_id": service_id if _ID.fullmatch(service_id) else "invalid",
                    "name": service_id if _ID.fullmatch(service_id) else "invalid",
                    "manager": "unknown",
                    "owned": False,
                    "available": False,
                    "running": False,
                    "actions": [],
                }
            )
    return rows
