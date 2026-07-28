"""Alles-owned, loopback-only SearXNG container lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import time
import uuid
from pathlib import Path

from core.settings import data_dir, load_settings, save_settings
from services import service_manager

SERVICE_ID = "searxng"
PROJECT = "alles-searxng"
COMPOSE_SERVICE = "searxng"
VERSION = "2026.7.12-c19d86faa"
INDEX_DIGEST = "sha256:f433294b46a93564993c4371005341e013d94aa8ea4662d8ee521cd2cccb08e8"
IMAGE = f"docker.io/searxng/searxng@{INDEX_DIGEST}"
LICENSE = "AGPL-3.0"
LICENSE_URL = "https://github.com/searxng/searxng/blob/master/LICENSE"
UPSTREAM_URL = "https://docs.searxng.org/admin/installation-docker"
REVIEWED_ON = "2026-07-12"
DEFAULT_PORT = 8888
LIVE_SPIKE_VERIFIED = True
LIVE_SPIKE_NOTE = (
    "Live-verified on macOS with Colima, Docker 29.5.2, Compose 5.3.1, "
    "the pinned image, loopback health, and JSON search."
)


class ManagedSearxngError(RuntimeError):
    pass


class ManagedSearxngRollback(ManagedSearxngError):
    pass


def root_dir() -> Path:
    return data_dir() / "services" / SERVICE_ID


def _validated_port(raw: object, *, setting: str) -> int:
    value = str(raw).strip()
    try:
        port = int(value)
    except ValueError as exc:
        raise ManagedSearxngError(f"{setting} must be a valid port") from exc
    if not 1024 <= port <= 65535:
        raise ManagedSearxngError(f"{setting} must be between 1024 and 65535")
    return port


def _configured_port() -> int:
    return _validated_port(
        os.environ.get("ALLES_SEARXNG_PORT", str(DEFAULT_PORT)), setting="ALLES_SEARXNG_PORT"
    )


def managed_port() -> int:
    manifest = _read_manifest()
    if manifest:
        persisted = manifest.get("port")
        if persisted is None:
            bind = str(manifest.get("bind") or "")
            persisted = bind.rsplit(":", 1)[-1] if ":" in bind else None
        if persisted is not None:
            return _validated_port(persisted, setting="installed SearXNG port")
    return _configured_port()


def managed_url() -> str:
    return f"http://127.0.0.1:{managed_port()}"


def _compose(image: str = IMAGE, version: str = VERSION) -> str:
    port = managed_port()
    return f"""services:
  searxng:
    image: {image}
    user: "977:977"
    restart: unless-stopped
    ports:
      - "127.0.0.1:{port}:8080"
    env_file:
      - ./.env
    volumes:
      - ./config:/etc/searxng:ro
    read_only: true
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=64m,uid=977,gid=977,mode=0700
      - /var/cache/searxng:rw,noexec,nosuid,size=128m,uid=977,gid=977,mode=0700
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    pids_limit: 128
    mem_limit: 512m
    cpus: 1.0
    stop_grace_period: 20s
    healthcheck:
      test: ["CMD", "/usr/local/searxng/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/', timeout=3).read(1)"]
      interval: 20s
      timeout: 5s
      retries: 5
      start_period: 25s
    logging:
      driver: local
      options:
        max-size: "5m"
        max-file: "2"
    labels:
      app.alles.managed: "true"
      app.alles.upstream-version: "{version}"
"""


SETTINGS = """use_default_settings: true
general:
  debug: false
  instance_name: "Alles Search"
search:
  safe_search: 0
  autocomplete: ""
  formats:
    - html
    - json
server:
  limiter: false
  image_proxy: false
"""


def _sha(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _atomic_text(path: Path, value: str, mode: int = 0o600) -> None:
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


def _manifest(*, image: str = IMAGE, version: str = VERSION) -> dict:
    return {
        "managed_by": "alles",
        "service_id": SERVICE_ID,
        "version": version,
        "image": image,
        "digest": image.rsplit("@", 1)[-1] if "@" in image else "",
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "upstream_url": UPSTREAM_URL,
        "reviewed_on": REVIEWED_ON,
        "port": managed_port(),
        "bind": f"127.0.0.1:{managed_port()}",
        "compose_sha256": _sha(_compose(image, version)),
    }


def _read_manifest(path: Path | None = None) -> dict:
    target = path or (root_dir() / "manifest.json")
    try:
        value = json.loads(target.read_text("utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) and value.get("managed_by") == "alles" else {}


def _runner(command: list[str], timeout: int = 120):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=service_manager._environment(),
    )


def _compose_command(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(root_dir()),
        "--project-name",
        PROJECT,
        *args,
    ]


def _ok(result, message: str) -> None:
    if result.returncode != 0:
        raise ManagedSearxngError(message)


def docker_status(*, runner=_runner) -> dict:
    try:
        result = runner(["docker", "version", "--format", "{{.Server.Version}}"], 15)
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "version": ""}
    return {
        "available": result.returncode == 0 and bool((result.stdout or "").strip()),
        "version": (result.stdout or "").strip()[:80] if result.returncode == 0 else "",
    }


def _probe(url: str | None = None) -> bool:
    import httpx

    try:
        response = httpx.get(url or managed_url(), timeout=5, follow_redirects=False)
        return response.status_code == 200
    except Exception:
        return False


def _registered() -> bool:
    try:
        return (service_manager._registry_dir() / f"{SERVICE_ID}.json").is_file()
    except service_manager.ServiceOwnershipError:
        return False


def status(*, runner=_runner, probe=_probe) -> dict:
    docker = docker_status(runner=runner)
    root = root_dir()
    manifest = _read_manifest()
    base = {
        "service_id": SERVICE_ID,
        "installed": False,
        "owned": False,
        "available": docker["available"],
        "docker_version": docker["version"],
        "running": False,
        "healthy": False,
        "url": managed_url(),
        "bind": f"127.0.0.1:{managed_port()}",
        "version": manifest.get("version") or VERSION,
        "image": manifest.get("image") or IMAGE,
        "digest": manifest.get("digest") or INDEX_DIGEST,
        "license": LICENSE,
        "support_verified": LIVE_SPIKE_VERIFIED,
        "spike_note": LIVE_SPIKE_NOTE,
        "data_kept": root.is_dir(),
        "actions": [],
    }
    if not _registered():
        return base
    try:
        owned = service_manager.status(SERVICE_ID, runner=lambda command: runner(command, 20))
    except service_manager.ServiceOwnershipError:
        return {**base, "installed": True, "owned": False, "error": "ownership check failed"}
    running = bool(owned["running"])
    return {
        **base,
        "installed": True,
        "owned": True,
        "available": bool(owned["available"] and docker["available"]),
        "running": running,
        "healthy": bool(running and probe()),
        "actions": owned["actions"],
    }


def _write_definition(*, image: str = IMAGE, version: str = VERSION) -> None:
    root = root_dir()
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ManagedSearxngError("existing SearXNG service root is unsafe")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = root / "config"
    if config.is_symlink() or (config.exists() and not config.is_dir()):
        raise ManagedSearxngError("existing SearXNG config path is unsafe")
    config.mkdir(exist_ok=True, mode=0o755)
    # The container intentionally runs as UID 977. The mounted directory holds
    # only the public settings file, so it must be traversable by that user;
    # the secret remains one level above in the owner-only .env file.
    config.chmod(0o755)
    compose = _compose(image, version)
    existing_manifest = _read_manifest()
    if (root / "compose.yaml").exists() and not _registered():
        actual = _sha((root / "compose.yaml").read_bytes())
        if not existing_manifest or actual != existing_manifest.get("compose_sha256"):
            raise ManagedSearxngError("existing SearXNG files are not a trusted Alles definition")
    _atomic_text(root / "compose.yaml", compose)
    _atomic_text(config / "settings.yml", SETTINGS, 0o644)
    if not (root / ".env").exists():
        env = (
            f"SEARXNG_SECRET={secrets.token_hex(32)}\n"
            f"SEARXNG_BASE_URL={managed_url()}/\n"
            "FORCE_OWNERSHIP=false\n"
        )
        _atomic_text(root / ".env", env)
    _atomic_text(root / "manifest.json", json.dumps(_manifest(image=image, version=version)))


def _register() -> None:
    service_manager.register_owned_service(
        service_id=SERVICE_ID,
        name="managed SearXNG",
        manager="compose",
        root=root_dir(),
        project=PROJECT,
        compose_service=COMPOSE_SERVICE,
    )


def _verify_config_mount(*, runner=_runner) -> None:
    config = (root_dir() / "config").resolve()
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--user",
        "977:977",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "32",
        "--memory",
        "64m",
        "--cpus",
        "0.25",
        "--mount",
        f"type=bind,source={config},target=/alles-config,readonly",
        "--entrypoint",
        "/usr/local/searxng/.venv/bin/python",
        IMAGE,
        "-c",
        (
            "from pathlib import Path; "
            "p=Path('/alles-config/settings.yml'); "
            "raise SystemExit(0 if p.is_file() and p.open('rb').read(1) else 1)"
        ),
    ]
    result = runner(command, 30)
    if result.returncode == 0:
        return
    raise ManagedSearxngError(
        "Docker cannot read the SearXNG configuration under ALLES_DATA; "
        "move ALLES_DATA to a folder shared with Docker, then install again"
    )


def install(*, runner=_runner, probe=_probe, allow_unverified: bool = False) -> dict:
    if not LIVE_SPIKE_VERIFIED and not allow_unverified:
        raise ManagedSearxngError(
            "managed SearXNG is not live-verified in this build; configure an external HTTPS SearXNG URL"
        )
    if not docker_status(runner=runner)["available"]:
        raise ManagedSearxngError("Docker is unavailable; use an external search provider")
    _write_definition()
    _ok(runner(_compose_command("pull", COMPOSE_SERVICE), 300), "SearXNG image pull failed")
    _verify_config_mount(runner=runner)
    _register()
    _ok(
        runner(
            _compose_command("up", "-d", "--wait", "--wait-timeout", "60", COMPOSE_SERVICE),
            120,
        ),
        "SearXNG did not start",
    )
    if not probe():
        runner(_compose_command("stop", COMPOSE_SERVICE), 30)
        raise ManagedSearxngError("SearXNG started but failed its loopback health check")
    current = load_settings()
    fallback = current.get("search_provider") or "duckduckgo"
    chain = [item for item in current.get("search_fallback_chain") or [] if item != "searxng"]
    if fallback != "searxng" and fallback not in chain:
        chain.insert(0, fallback)
    save_settings(
        {
            "searxng_url": managed_url(),
            "search_provider": "searxng",
            "search_fallback_chain": chain or ["duckduckgo"],
        }
    )
    return status(runner=runner, probe=probe)


def control(
    action: str,
    *,
    runner=_runner,
    probe=_probe,
    sleep=time.sleep,
) -> dict:
    if action not in {"start", "stop", "restart"}:
        raise ManagedSearxngError("unsupported managed SearXNG action")
    current = status(runner=runner, probe=probe)
    if not current["installed"] or not current["owned"]:
        raise ManagedSearxngError("managed SearXNG is not installed")
    try:
        service_manager.control(
            SERVICE_ID,
            action,
            runner=lambda command: runner(command, 60),
        )
    except (service_manager.ServiceControlError, service_manager.ServiceOwnershipError) as exc:
        raise ManagedSearxngError(str(exc)) from exc
    if action == "stop":
        return status(runner=runner, probe=lambda: False)
    for _attempt in range(120):
        if probe():
            return status(runner=runner, probe=lambda: True)
        sleep(0.5)
    try:
        service_manager.control(
            SERVICE_ID,
            "stop",
            runner=lambda command: runner(command, 60),
        )
    except (service_manager.ServiceControlError, service_manager.ServiceOwnershipError):
        pass
    raise ManagedSearxngError(f"SearXNG {action}ed but failed its loopback health check")


def _restore_definition(compose: str, manifest: dict) -> None:
    _atomic_text(root_dir() / "compose.yaml", compose)
    _atomic_text(root_dir() / "manifest.json", json.dumps(manifest))
    _register()


def update(
    *,
    image: str = IMAGE,
    version: str = VERSION,
    runner=_runner,
    probe=_probe,
) -> dict:
    current = status(runner=runner, probe=probe)
    if not current["installed"] or not current["owned"]:
        raise ManagedSearxngError("managed SearXNG is not installed")
    old_manifest = _read_manifest()
    if old_manifest.get("image") == image and old_manifest.get("version") == version:
        return {**current, "update": "up_to_date"}
    _ok(runner(["docker", "pull", image], 300), "candidate SearXNG image pull failed")
    old_compose = (root_dir() / "compose.yaml").read_text("utf-8")
    rollback = root_dir() / ".rollback"
    _atomic_text(rollback / "compose.yaml", old_compose)
    _atomic_text(rollback / "manifest.json", json.dumps(old_manifest))
    try:
        _write_definition(image=image, version=version)
        _register()
        _ok(
            runner(
                _compose_command("up", "-d", "--wait", "--wait-timeout", "60", COMPOSE_SERVICE),
                120,
            ),
            "candidate SearXNG did not start",
        )
        if not probe():
            raise ManagedSearxngError("candidate SearXNG failed health")
    except Exception as exc:
        _restore_definition(old_compose, old_manifest)
        runner(_compose_command("up", "-d", COMPOSE_SERVICE), 120)
        raise ManagedSearxngRollback(
            "update failed and the previous definition was restored"
        ) from exc
    return {**status(runner=runner, probe=probe), "update": "updated"}


def rollback(*, runner=_runner, probe=_probe) -> dict:
    rollback_dir = root_dir() / ".rollback"
    previous = _read_manifest(rollback_dir / "manifest.json")
    previous_compose = rollback_dir / "compose.yaml"
    if not previous or not previous_compose.is_file():
        raise ManagedSearxngError("no reviewed SearXNG rollback is available")
    current_manifest = _read_manifest()
    current_compose = (root_dir() / "compose.yaml").read_text("utf-8")
    try:
        _restore_definition(previous_compose.read_text("utf-8"), previous)
        _ok(
            runner(
                _compose_command("up", "-d", "--wait", "--wait-timeout", "60", COMPOSE_SERVICE),
                120,
            ),
            "rollback SearXNG did not start",
        )
        if not probe():
            raise ManagedSearxngError("rollback SearXNG failed health")
    except Exception:
        _restore_definition(current_compose, current_manifest)
        runner(_compose_command("up", "-d", COMPOSE_SERVICE), 120)
        raise
    _atomic_text(rollback_dir / "compose.yaml", current_compose)
    _atomic_text(rollback_dir / "manifest.json", json.dumps(current_manifest))
    return {**status(runner=runner, probe=probe), "update": "rolled_back"}


def uninstall_keep_data(*, runner=_runner) -> dict:
    current = status(runner=runner, probe=lambda: False)
    if not current["installed"] or not current["owned"]:
        raise ManagedSearxngError("managed SearXNG is not installed")
    _ok(
        runner(_compose_command("down", "--remove-orphans"), 90),
        "SearXNG could not be stopped for uninstall",
    )
    service_manager.unregister_owned_service(SERVICE_ID)
    settings = load_settings()
    if (
        settings.get("search_provider") == "searxng"
        and settings.get("searxng_url") == managed_url()
    ):
        fallback = next(
            (item for item in settings.get("search_fallback_chain") or [] if item != "searxng"),
            "duckduckgo",
        )
        save_settings({"search_provider": fallback})
    return {
        "ok": True,
        "installed": False,
        "data_kept": True,
        "root": str(root_dir()),
    }


def json_search(query: str, *, runner=_runner) -> dict:
    if not status(runner=runner)["healthy"]:
        raise ManagedSearxngError("managed SearXNG is not healthy")
    import httpx

    response = httpx.get(
        f"{managed_url()}/search",
        params={"q": query, "format": "json"},
        timeout=15,
    )
    response.raise_for_status()
    value = response.json()
    return {
        "ok": isinstance(value.get("results"), list),
        "results": len(value.get("results") or []),
    }
