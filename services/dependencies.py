"""the optional tools Aide can use: node, pi, Aide's browser and SearXNG.

each one reports its real state and installs with one click into the user's cache folder (no sudo,
no system package manager). pi and SearXNG keep their own installers; this module only asks them.
releases are immutable, so nothing is ever installed into the release's own python environment.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import httpx

from core.tool_path import cache_dir, find_tool

log = logging.getLogger("alles.dependencies")

IDS = ("node", "pi", "browser", "searxng")
NAMES = {"node": "node", "pi": "pi", "browser": "Aide's browser", "searxng": "SearXNG"}
NODE_DIST = "https://nodejs.org/dist"
PLAYWRIGHT_VERSION = "1.64.1"
DOCKER_URL = "https://docs.docker.com/engine/install/"


class DependencyError(RuntimeError):
    """the plain sentence the panel shows under the row"""


# ── helpers ──


def _tail(text: str) -> str:
    lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


def _run(command: list[str], what: str, timeout: int, env: dict | None = None) -> str:
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, env=env, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise DependencyError(f"{what} took longer than {timeout // 60} minutes") from exc
    except OSError as exc:
        raise DependencyError(f"could not run {what}: {exc.strerror or exc}") from exc
    if done.returncode != 0:
        raise DependencyError(_tail(done.stderr) or _tail(done.stdout) or f"{what} failed")
    return f"{done.stdout}\n{done.stderr}"


def _get_text(url: str) -> str:
    response = httpx.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def _download(url: str, dest: Path) -> str:
    """streams to dest and returns the sha-256 of what arrived"""
    digest = hashlib.sha256()
    with httpx.stream("GET", url, timeout=httpx.Timeout(30, read=120)) as response:
        response.raise_for_status()
        with dest.open("wb") as out:
            for chunk in response.iter_bytes(1 << 16):
                digest.update(chunk)
                out.write(chunk)
    return digest.hexdigest()


# ── node ──


def _node_target() -> tuple[str, str, str]:
    """(os, arch, the key nodejs.org's index.json uses for this machine)"""
    system = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine().lower()
    )
    if not system or not arch:
        raise DependencyError(
            f"there is no node download for {platform.system()} {platform.machine()}"
        )
    return system, arch, f"osx-{arch}-tar" if system == "darwin" else f"linux-{arch}"


def _latest_lts(index: list, key: str) -> str:
    for entry in index:
        version = str(entry.get("version", ""))
        if (
            entry.get("lts")
            and key in entry.get("files", [])
            and re.fullmatch(r"v\d+\.\d+\.\d+", version)
        ):
            return version
    raise DependencyError("nodejs.org lists no LTS release for this machine")


def install_node() -> str:
    """the newest node LTS, checked against nodejs.org's published checksum, into
    <cache>/alles/node-<version>, with <cache>/alles/node pointing at it."""
    system, arch, key = _node_target()
    try:
        version = _latest_lts(json.loads(_get_text(f"{NODE_DIST}/index.json")), key)
        name = f"node-{version}-{system}-{arch}"
        sums = _get_text(f"{NODE_DIST}/{version}/SHASUMS256.txt")
    except (httpx.HTTPError, ValueError) as exc:
        raise DependencyError(f"could not reach nodejs.org ({type(exc).__name__})") from exc
    wanted = next(
        (
            parts[0]
            for parts in (line.split() for line in sums.splitlines())
            if len(parts) == 2 and parts[1] == f"{name}.tar.gz"
        ),
        "",
    )
    if not wanted:
        raise DependencyError("nodejs.org's checksum list doesn't include this download")
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    final = root / f"node-{version}"
    with tempfile.TemporaryDirectory(dir=root, prefix=".node-download-") as work:
        tarball = Path(work) / f"{name}.tar.gz"
        try:
            got = _download(f"{NODE_DIST}/{version}/{name}.tar.gz", tarball)
        except (httpx.HTTPError, OSError) as exc:
            raise DependencyError(f"the node download failed ({type(exc).__name__})") from exc
        if got != wanted:
            raise DependencyError(
                "the node download didn't match its published checksum, so it was thrown away"
            )
        extras = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        with tarfile.open(tarball) as archive:
            archive.extractall(Path(work) / "out", **extras)
        unpacked = Path(work) / "out" / name
        # a tarball built for another libc downloads fine and then can't start
        try:
            ran = _run([str(unpacked / "bin" / "node"), "-v"], "the new node", 30).strip()
        except DependencyError as exc:
            raise DependencyError(f"the downloaded node doesn't run here: {exc}") from exc
        if ran.splitlines()[0] != version:
            raise DependencyError("the downloaded node reports the wrong version")
        shutil.rmtree(final, ignore_errors=True)
        os.replace(unpacked, final)
    link, fresh = root / "node", root / ".node-link"
    fresh.unlink(missing_ok=True)
    fresh.symlink_to(final.name)
    os.replace(fresh, link)
    for old in root.glob("node-v*"):
        if old != final:
            shutil.rmtree(old, ignore_errors=True)
    return version


def _node_state() -> dict:
    from services import pi_agent

    found = pi_agent.node_version()
    need = ".".join(map(str, pi_agent.MIN_NODE))
    if found is None:
        return {"state": "missing", "detail": "node isn't installed", "can_install": True}
    version = ".".join(map(str, found))
    if found < pi_agent.MIN_NODE:
        return {
            "state": "outdated",
            "version": version,
            "detail": f"node {version} is too old, pi needs {need} or newer",
            "can_install": True,
        }
    return {"state": "ready", "version": version, "detail": f"node {version}"}


# ── pi ──


def _pi_state() -> dict:
    from services import pi_agent

    info = pi_agent.status("pi")
    state = info["state"]
    detail = {
        "ready": f"pi {info['version']}",
        "installing": "installing pi",
        "needs_node": "pi needs node 22.19 or newer first",
        "failed": "the pi install failed",
        "missing": "pi isn't installed",
    }[state]
    return {
        "state": state,
        "version": info["version"] if state == "ready" else "",
        "detail": detail,
        "error": info.get("error", "") if state == "failed" else "",
        "can_install": state in ("missing", "failed"),
    }


# ── Aide's browser ──


def packages_dir() -> Path:
    return cache_dir() / "browser-packages"


def browsers_dir() -> Path:
    return cache_dir() / "browser-browsers"


def _default_browsers() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"


def _has_chromium(folder: Path) -> bool:
    # playwright writes this marker last, so a half-finished download doesn't count
    try:
        return any(folder.glob("chromium*-*/INSTALLATION_COMPLETE"))
    except OSError:
        return False


def prepare_browser() -> None:
    """call right before importing playwright. when the python package isn't importable the normal
    way, use the copy alles installed into the cache folder, and its chromium."""
    importlib.invalidate_caches()
    packages = packages_dir()
    if importlib.util.find_spec("playwright") is None and packages.is_dir():
        if str(packages) not in sys.path:
            # last, so alles's own packages are never shadowed by playwright's pins
            sys.path.append(str(packages))
        importlib.invalidate_caches()
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and _has_chromium(browsers_dir()):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir())


def _browser_state() -> dict:
    prepare_browser()
    package = importlib.util.find_spec("playwright") is not None
    folder = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or _default_browsers())
    if package and _has_chromium(folder):
        try:
            version = importlib.metadata.version("playwright")
        except importlib.metadata.PackageNotFoundError:
            version = ""
        return {"state": "ready", "version": version, "detail": "chromium is installed"}
    return {
        "state": "missing",
        "detail": "Aide's browser isn't installed" if not package else "chromium isn't downloaded",
        "can_install": True,
    }


def _browser_env() -> dict:
    env = {
        **os.environ,
        "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        or str(browsers_dir()),
    }
    if packages_dir().is_dir():
        env["PYTHONPATH"] = os.pathsep.join(
            [str(packages_dir()), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
        )
    return env


def _pip_command(target: Path) -> list[str]:
    spec = f"playwright=={PLAYWRIGHT_VERSION}"
    if importlib.util.find_spec("pip"):
        return [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--progress-bar",
            "off",
            "--only-binary",
            ":all:",
            "--target",
            str(target),
            spec,
        ]
    uv = find_tool("uv")
    if uv:
        return [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--only-binary",
            ":all:",
            "--target",
            str(target),
            spec,
        ]
    raise DependencyError("pip isn't available in alles's python environment")


_LAUNCH_CHECK = (
    "from playwright.sync_api import sync_playwright\n"
    "with sync_playwright() as p:\n"
    "    p.chromium.launch().close()\n"
)


def install_browser() -> None:
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    if importlib.util.find_spec("playwright") is None and not packages_dir().is_dir():
        staging = root / "browser-packages.partial"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            _run(_pip_command(staging), "installing playwright", 900)
        except DependencyError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        os.replace(staging, packages_dir())
    env = _browser_env()
    _run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        "downloading chromium",
        1200,
        env,
    )
    try:
        _run([sys.executable, "-c", _LAUNCH_CHECK], "starting chromium", 120, env)
    except DependencyError as exc:
        if re.search(r"missing dependencies|shared librar|libnss|libgbm", str(exc), re.I):
            fix = f"{shlex.quote(sys.executable)} -m playwright install-deps chromium"
            if env.get("PYTHONPATH"):
                fix = f"env PYTHONPATH={shlex.quote(env['PYTHONPATH'])} {fix}"
            raise DependencyError(
                f"chromium needs system libraries. run this in a terminal, then try again: sudo {fix}"
            ) from exc
        raise
    prepare_browser()


# ── SearXNG ──


def _searxng_state() -> dict:
    from services import managed_searxng

    if not find_tool("docker"):
        # alles never installs docker itself: it needs the system's package manager and root
        return {"state": "needs_docker", "detail": "Docker isn't installed", "link": DOCKER_URL}
    info = managed_searxng.status()
    if not info["available"]:
        return {"state": "docker_off", "detail": "Docker isn't running"}
    if not info["installed"]:
        return {"state": "missing", "detail": "SearXNG isn't installed", "can_install": True}
    if info["running"] and info["healthy"]:
        return {
            "state": "ready",
            "version": info["version"],
            "detail": f"SearXNG {info['version']}",
        }
    return {
        "state": "stopped",
        "version": info["version"],
        "detail": "SearXNG is installed but not running",
        "error": info.get("error", ""),
        "can_install": True,
    }


def _searxng_install() -> None:
    from services import managed_searxng

    try:
        if _searxng_state()["state"] == "stopped":
            managed_searxng.control("start")
        else:
            managed_searxng.install()
    except managed_searxng.ManagedSearxngError as exc:
        raise DependencyError(str(exc)) from exc


# ── states and installs ──

_STATES = {
    "node": _node_state,
    "pi": _pi_state,
    "browser": _browser_state,
    "searxng": _searxng_state,
}
_installers = {
    "node": install_node,
    "browser": install_browser,
    "searxng": _searxng_install,
}
_jobs: dict[str, dict] = {dep_id: {"task": None, "error": ""} for dep_id in _installers}


def _running(dep_id: str) -> bool:
    task = _jobs.get(dep_id, {}).get("task")
    return task is not None and not task.done()


async def state(dep_id: str) -> dict:
    row = {
        "id": dep_id,
        "name": NAMES[dep_id],
        "version": "",
        "detail": "",
        "error": "",
        "can_install": False,
    }
    if _running(dep_id):
        return {**row, "state": "installing", "detail": f"installing {NAMES[dep_id]}"}
    found = await asyncio.to_thread(_STATES[dep_id])
    row.update(found)
    error = _jobs.get(dep_id, {}).get("error", "")
    # a failed try shows until the next check finds it working or the owner tries again
    if error and found["state"] != "ready":
        row.update(
            state="failed",
            error=error,
            detail=f"installing {NAMES[dep_id]} failed",
            can_install=True,
        )
    return row


async def list_all() -> list[dict]:
    return list(await asyncio.gather(*(state(dep_id) for dep_id in IDS)))


async def _run_job(dep_id: str) -> None:
    try:
        await asyncio.to_thread(_installers[dep_id])
    except DependencyError as exc:
        _jobs[dep_id]["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - the panel needs a sentence, not a stack
        log.warning("installing %s failed: %s", dep_id, type(exc).__name__, exc_info=True)
        _jobs[dep_id]["error"] = f"installing {NAMES[dep_id]} failed ({type(exc).__name__})"


async def install(dep_id: str) -> dict:
    """starts the install in the background and returns the state right away; asking again while
    it runs changes nothing."""
    if dep_id == "pi":
        from services import pi_agent

        pi_agent.ensure_installed("pi")
    elif not _running(dep_id):
        _jobs[dep_id]["error"] = ""
        _jobs[dep_id]["task"] = asyncio.get_running_loop().create_task(_run_job(dep_id))
    return await state(dep_id)
