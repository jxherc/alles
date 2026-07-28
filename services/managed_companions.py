"""Pinned, ownership-safe AdGuard Home and Nginx Proxy Manager companions.

Preparation writes definitions and private configuration but never starts a container. Activation is a
separate, fail-closed network preflight with an exact confirmation phrase and tested rollback.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import uuid
from pathlib import Path

import bcrypt
import httpx

from core.settings import data_dir
from services import managed_companion_clients, service_manager

DEFINITIONS = {
    "adguard-home": {
        "name": "AdGuard Home",
        "image": "adguard/adguardhome:v0.107.78",
        "version": "0.107.78",
        "license": "GPL-3.0",
        "project": "alles-adguard-home",
        "compose_service": "adguard-home",
        "admin_port": 3000,
        "network_ports": (53,),
        "confirmation": "activate adguard dns",
    },
    "nginx-proxy-manager": {
        "name": "Nginx Proxy Manager",
        "image": "jc21/nginx-proxy-manager:2.15.1",
        "version": "2.15.1",
        "license": "MIT",
        "project": "alles-nginx-proxy-manager",
        "compose_service": "nginx-proxy-manager",
        "admin_port": 8181,
        "network_ports": (80, 443),
        "confirmation": "activate nginx proxy",
    },
}


class ManagedCompanionError(RuntimeError):
    pass


def _definition(service_id: str) -> dict:
    try:
        return DEFINITIONS[service_id]
    except KeyError as exc:
        raise ManagedCompanionError("unknown managed companion") from exc


def root_dir(service_id: str) -> Path:
    _definition(service_id)
    root = (data_dir() / "managed-companions" / service_id).resolve()
    expected = (data_dir() / "managed-companions").resolve()
    if root.parent != expected or root.is_symlink():
        raise ManagedCompanionError("managed companion root is unsafe")
    return root


def _manifest_path(service_id: str) -> Path:
    return root_dir(service_id) / "manifest.json"


def _env_path(service_id: str) -> Path:
    return root_dir(service_id) / ".env"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic(path: Path, value: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    try:
        with temp.open("x", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_manifest(service_id: str) -> dict:
    path = _manifest_path(service_id)
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _runner(command: list[str], timeout: int = 120):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ManagedCompanionError("Docker Compose is unavailable") from exc


def docker_status(*, runner=_runner) -> dict:
    try:
        result = runner(["docker", "compose", "version", "--short"], timeout=20)
    except Exception:
        return {"available": False, "version": ""}
    return {"available": result.returncode == 0, "version": (result.stdout or "").strip()}


def _compose(service_id: str) -> str:
    d = _definition(service_id)
    if service_id == "adguard-home":
        ports = (
            '      - "127.0.0.1:${ADGUARD_ADMIN_PORT}:3000/tcp"\n'
            '      - "${ADGUARD_DNS_BIND}:${ADGUARD_DNS_PORT}:53/tcp"\n'
            '      - "${ADGUARD_DNS_BIND}:${ADGUARD_DNS_PORT}:53/udp"'
        )
        volumes = "      - ./work:/opt/adguardhome/work\n      - ./conf:/opt/adguardhome/conf"
    else:
        ports = (
            '      - "127.0.0.1:${NPM_ADMIN_PORT}:81/tcp"\n'
            '      - "${NPM_HTTP_BIND}:${NPM_HTTP_PORT}:80/tcp"\n'
            '      - "${NPM_HTTPS_BIND}:${NPM_HTTPS_PORT}:443/tcp"'
        )
        volumes = "      - ./data:/data\n      - ./letsencrypt:/etc/letsencrypt"
    return f"""services:
  {d['compose_service']}:
    image: {d['image']}
    restart: unless-stopped
    env_file:
      - .env
    ports:
{ports}
    volumes:
{volumes}
    security_opt:
      - no-new-privileges:true
"""


def _prepared_env(service_id: str) -> str:
    if service_id == "adguard-home":
        return "ADGUARD_ADMIN_PORT=3000\nADGUARD_DNS_BIND=127.0.0.1\nADGUARD_DNS_PORT=5353\n"
    return "NPM_ADMIN_PORT=8181\nNPM_HTTP_BIND=127.0.0.1\nNPM_HTTP_PORT=8080\nNPM_HTTPS_BIND=127.0.0.1\nNPM_HTTPS_PORT=8443\n"


def prepare(service_id: str, *, runner=_runner) -> dict:
    d = _definition(service_id)
    docker = docker_status(runner=runner)
    if not docker["available"]:
        raise ManagedCompanionError("Docker Compose is required to prepare this companion")
    root = root_dir(service_id)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for folder in (("work", "conf") if service_id == "adguard-home" else ("data", "letsencrypt")):
        (root / folder).mkdir(mode=0o700, exist_ok=True)
    compose = root / "compose.yaml"
    env = _env_path(service_id)
    expected_compose = _compose(service_id)
    if compose.exists():
        if compose.is_symlink() or compose.read_text("utf-8") != expected_compose:
            raise ManagedCompanionError("managed companion definition changed outside Alles")
    else:
        _atomic(compose, expected_compose)
    if not env.exists():
        _atomic(env, _prepared_env(service_id))
    elif env.is_symlink():
        raise ManagedCompanionError("managed companion environment is unsafe")
    local_marker = root / ".alles-owned-service.json"
    registry_marker = data_dir() / "owned-services" / f"{service_id}.json"
    if local_marker.exists() or registry_marker.exists():
        try:
            service_manager.status(service_id, runner=runner)
        except service_manager.ServiceOwnershipError as exc:
            raise ManagedCompanionError(str(exc)) from exc
    else:
        try:
            service_manager.register_owned_service(
                service_id=service_id,
                name=d["name"],
                manager="compose",
                root=root,
                project=d["project"],
                compose_service=d["compose_service"],
            )
        except ValueError as exc:
            raise ManagedCompanionError(str(exc)) from exc
    pull = runner(_compose_command(service_id, "pull"), timeout=300)
    if pull.returncode != 0:
        raise ManagedCompanionError("could not download the pinned companion image")
    manifest = {
        "schema": 1,
        "service_id": service_id,
        "image": d["image"],
        "version": d["version"],
        "license": d["license"],
        "compose_sha256": _sha(compose),
        "prepared": True,
        "activated": False,
        "activation": {},
        "rollback": {},
    }
    _atomic(_manifest_path(service_id), json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return status(service_id, runner=runner)


def _port_free(bind: str, port: int, socket_type: int) -> bool:
    family = socket.AF_INET6 if ":" in bind else socket.AF_INET
    sock = socket.socket(family, socket_type)
    try:
        sock.bind((bind, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _verify_prepared(service_id: str, *, runner=_runner) -> dict:
    manifest = _read_manifest(service_id)
    compose = root_dir(service_id) / "compose.yaml"
    env = _env_path(service_id)
    if not manifest.get("prepared"):
        raise ManagedCompanionError("prepare the companion first")
    if (
        not compose.is_file()
        or compose.is_symlink()
        or compose.read_text("utf-8") != _compose(service_id)
        or manifest.get("compose_sha256") != _sha(compose)
        or not env.is_file()
        or env.is_symlink()
    ):
        raise ManagedCompanionError("managed companion files failed verification")
    try:
        owned = service_manager.status(service_id, runner=runner)
    except service_manager.ServiceOwnershipError as exc:
        raise ManagedCompanionError(str(exc)) from exc
    if not owned.get("owned"):
        raise ManagedCompanionError("managed companion ownership is unverified")
    return manifest


def preflight(service_id: str, *, bind: str, ports: dict | None = None, runner=_runner, port_free=_port_free) -> dict:
    d = _definition(service_id)
    _verify_prepared(service_id, runner=runner)
    clean_bind = str(bind or "").strip()
    if not clean_bind or clean_bind in {"0.0.0.0", "::"}:
        raise ManagedCompanionError("choose one exact LAN or loopback interface address")
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in clean_bind else socket.AF_INET, clean_bind)
    except OSError as exc:
        raise ManagedCompanionError("interface address is invalid") from exc
    requested = {str(key): int(value) for key, value in (ports or {}).items()}
    expected = ({"dns": 53} if service_id == "adguard-home" else {"http": 80, "https": 443})
    resolved = {key: requested.get(key, default) for key, default in expected.items()}
    checks = []
    for key, port in resolved.items():
        if not 1 <= port <= 65535:
            raise ManagedCompanionError(f"{key} port is invalid")
        protocols = (socket.SOCK_STREAM, socket.SOCK_DGRAM) if key == "dns" else (socket.SOCK_STREAM,)
        free = all(port_free(clean_bind, port, protocol) for protocol in protocols)
        checks.append({"name": f"{key} {clean_bind}:{port}", "ok": free})
    docker = docker_status(runner=runner)
    checks.insert(0, {"name": "Docker Compose", "ok": docker["available"]})
    return {
        "ok": all(item["ok"] for item in checks),
        "service_id": service_id,
        "bind": clean_bind,
        "ports": resolved,
        "checks": checks,
        "confirmation_phrase": d["confirmation"],
        "rollback_available": True,
    }


def _activation_env(service_id: str, *, bind: str, ports: dict, username: str, password: str) -> str:
    if service_id == "adguard-home":
        if len(password) < 12:
            raise ManagedCompanionError("admin password must be at least 12 characters")
        digest = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        config = root_dir(service_id) / "conf" / "AdGuardHome.yaml"
        yaml = f"http:\n  address: 0.0.0.0:3000\nusers:\n  - name: {json.dumps(username or 'admin')}\n    password: {json.dumps(digest)}\ndns:\n  bind_hosts:\n    - 0.0.0.0\n  port: 53\n"
        _atomic(config, yaml)
        return f"ADGUARD_ADMIN_PORT=3000\nADGUARD_DNS_BIND={bind}\nADGUARD_DNS_PORT={ports['dns']}\n"
    # NPM 2.15.1 prints INITIAL_ADMIN_PASSWORD during its legacy automated setup.
    # Keep credentials out of Docker environment and logs; its private loopback UI owns setup.
    return f"NPM_ADMIN_PORT=8181\nNPM_HTTP_BIND={bind}\nNPM_HTTP_PORT={ports['http']}\nNPM_HTTPS_BIND={bind}\nNPM_HTTPS_PORT={ports['https']}\n"


def _compose_command(service_id: str, *args: str) -> list[str]:
    d = _definition(service_id)
    return ["docker", "compose", "--project-directory", str(root_dir(service_id)), "--project-name", d["project"], *args]


def activate(
    service_id: str,
    *,
    bind: str,
    ports: dict,
    admin_username: str,
    admin_password: str,
    confirmation: str,
    runner=_runner,
    port_free=_port_free,
    probe=None,
) -> dict:
    d = _definition(service_id)
    if str(confirmation or "").strip() != d["confirmation"]:
        raise ManagedCompanionError("activation confirmation phrase does not match")
    check = preflight(service_id, bind=bind, ports=ports, runner=runner, port_free=port_free)
    if not check["ok"]:
        raise ManagedCompanionError("network preflight did not pass")
    env_path = _env_path(service_id)
    previous_env = env_path.read_text("utf-8")
    manifest = _read_manifest(service_id)
    backup = root_dir(service_id) / "rollback.env"
    _atomic(backup, previous_env)
    config = root_dir(service_id) / "conf" / "AdGuardHome.yaml"
    config_backup = root_dir(service_id) / "rollback.AdGuardHome.yaml"
    config_existed = service_id == "adguard-home" and config.is_file() and not config.is_symlink()
    if config_existed:
        _atomic(config_backup, config.read_text("utf-8"))
    elif config_backup.exists():
        config_backup.unlink()
    try:
        _atomic(env_path, _activation_env(service_id, bind=check["bind"], ports=check["ports"], username=admin_username, password=admin_password))
        result = runner(_compose_command(service_id, "up", "-d"), timeout=180)
        if result.returncode != 0:
            raise ManagedCompanionError("companion did not start")
        healthy = probe(service_id) if probe else _probe(service_id)
        if not healthy:
            raise ManagedCompanionError("companion health probe failed")
    except Exception:
        _atomic(env_path, previous_env)
        if service_id == "adguard-home":
            if config_existed:
                _atomic(config, config_backup.read_text("utf-8"))
            else:
                config.unlink(missing_ok=True)
        runner(_compose_command(service_id, "down"), timeout=90)
        raise
    manifest["activated"] = True
    manifest["activation"] = {"bind": check["bind"], "ports": check["ports"]}
    manifest["rollback"] = {
        "env": backup.name,
        "config": config_backup.name if config_existed else "",
        "config_existed": config_existed,
        "available": True,
    }
    if service_id == "adguard-home":
        try:
            managed_companion_clients.save_adguard_credentials(admin_username or "admin", admin_password)
        except managed_companion_clients.CompanionClientError as exc:
            runner(_compose_command(service_id, "down"), timeout=90)
            _atomic(env_path, previous_env)
            if config_existed:
                _atomic(config, config_backup.read_text("utf-8"))
            else:
                config.unlink(missing_ok=True)
            raise ManagedCompanionError("could not secure AdGuard credentials") from exc
    _atomic(_manifest_path(service_id), json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return status(service_id, runner=runner, probe=probe)


def _probe(service_id: str) -> bool:
    port = _definition(service_id)["admin_port"]
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/", timeout=4, follow_redirects=False)
        return response.status_code < 500
    except Exception:
        return False


def status(service_id: str, *, runner=_runner, probe=None) -> dict:
    d = _definition(service_id)
    manifest = _read_manifest(service_id)
    prepared = bool(manifest.get("prepared"))
    owned = False
    running = False
    if prepared:
        try:
            current = service_manager.status(service_id, runner=runner)
            owned, running = bool(current["owned"]), bool(current["running"])
        except service_manager.ServiceOwnershipError:
            pass
    healthy = bool((probe(service_id) if probe else _probe(service_id)) if running else False)
    return {
        "service_id": service_id,
        "name": d["name"],
        "image": d["image"],
        "version": d["version"],
        "license": d["license"],
        "prepared": prepared,
        "activated": bool(manifest.get("activated")),
        "owned": owned,
        "running": running,
        "healthy": healthy,
        "admin_url": f"http://127.0.0.1:{d['admin_port']}/" if healthy else "",
        "activation": manifest.get("activation") or {},
        "confirmation_phrase": d["confirmation"],
        "network_mutation": service_id == "adguard-home",
        "admin_setup": "private_wizard" if service_id == "nginx-proxy-manager" else "alles_managed",
    }


def statuses(*, runner=_runner, probe=None) -> list[dict]:
    return [status(service_id, runner=runner, probe=probe) for service_id in DEFINITIONS]


def rollback(service_id: str, *, runner=_runner) -> dict:
    manifest = _read_manifest(service_id)
    rollback_file = root_dir(service_id) / str((manifest.get("rollback") or {}).get("env") or "")
    if not rollback_file.is_file() or rollback_file.is_symlink():
        raise ManagedCompanionError("no verified activation rollback is available")
    config_backup = None
    if service_id == "adguard-home" and (manifest.get("rollback") or {}).get("config_existed"):
        config_name = str((manifest.get("rollback") or {}).get("config") or "")
        config_backup = root_dir(service_id) / config_name if config_name else None
        if not config_backup or not config_backup.is_file() or config_backup.is_symlink():
            raise ManagedCompanionError("AdGuard configuration rollback is unavailable")
    result = runner(_compose_command(service_id, "down"), timeout=90)
    if result.returncode != 0:
        raise ManagedCompanionError("could not stop the companion for rollback")
    _atomic(_env_path(service_id), rollback_file.read_text("utf-8"))
    if service_id == "adguard-home":
        config = root_dir(service_id) / "conf" / "AdGuardHome.yaml"
        if (manifest.get("rollback") or {}).get("config_existed"):
            _atomic(config, config_backup.read_text("utf-8"))
        else:
            config.unlink(missing_ok=True)
    manifest["activated"] = False
    manifest["activation"] = {}
    _atomic(_manifest_path(service_id), json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    managed_companion_clients.clear_credentials(service_id)
    return status(service_id, runner=runner)


def uninstall_keep_data(service_id: str, *, runner=_runner) -> dict:
    root = root_dir(service_id)
    if not _read_manifest(service_id).get("prepared"):
        return {"ok": True, "service_id": service_id, "kept_data": str(root)}
    runner(_compose_command(service_id, "down"), timeout=90)
    try:
        service_manager.unregister_owned_service(service_id)
    except service_manager.ServiceOwnershipError as exc:
        raise ManagedCompanionError(str(exc)) from exc
    # Definitions and private data remain recoverable; only the active claim is removed.
    return {"ok": True, "service_id": service_id, "kept_data": str(root)}
