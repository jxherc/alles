"""the coding harnesses alles can drive, and how to install and start each one.

most come from the public ACP registry (agentclientprotocol.com), which pins an exact package or
binary per harness; a few popular ones that aren't listed there are added below. every harness
speaks ACP over stdio except pi, which alles drives through its own rpc mode.
installs go into the user cache, outside the data folder that backups copy.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import platform
import shutil
import tarfile
import time
import zipfile
from pathlib import Path

from core.settings import data_dir

REGISTRY_URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
REGISTRY_MAX_AGE = 24 * 3600
OPEN_LICENSES = ("mit", "apache", "bsd", "gpl", "agpl", "lgpl", "mpl", "isc", "unlicense")
MAX_DOWNLOAD = 600 * 1024 * 1024

# harnesses the registry doesn't carry; same shape as a registry entry
EXTRA = [
    {
        "id": "pi",
        "name": "pi",
        "description": "the coding agent alles runs natively, with steering and exact cache stats",
        "license": "MIT",
        "repository": "https://github.com/earendil-works/pi",
        "native": "pi",
    },
    {
        "id": "omp",
        "name": "oh-my-pi",
        "description": "a pi fork with a rust core and 60+ providers",
        "license": "MIT",
        "repository": "https://github.com/can1357/oh-my-pi",
        "version": "18.12.3",
        "distribution": {
            "bun": {"package": "@oh-my-pi/pi-coding-agent@18.12.3", "bin": "omp", "args": ["acp"]}
        },
    },
    # popular harnesses the registry doesn't list (or lists at an old or archived version)
    {
        "id": "deepseek-harness",
        "name": "DeepSeek Harness",
        "description": "DeepSeek's own coding harness (developer preview)",
        "license": "MIT",
        "repository": "https://github.com/deepseek-ai/deepseek-harness",
        "version": "0.2.1-rc.2",
        "distribution": {
            "npx": {"package": "@deepseek-ai/dsh@0.2.1-rc.2", "bin": "dsh", "args": ["acp"]}
        },
    },
    {
        "id": "kimi",
        "name": "Kimi Code",
        "description": "Moonshot's coding CLI (replaces the archived Kimi CLI)",
        "license": "MIT",
        "repository": "https://github.com/MoonshotAI/kimi-code",
        "version": "2.2.0",
        "distribution": {
            "npx": {"package": "@moonshot-ai/kimi-code@2.2.0", "bin": "kimi", "args": ["acp"]}
        },
    },
    {
        "id": "minimax-code",
        "name": "MiniMax Code",
        "description": "MiniMax's coding CLI",
        "license": "MIT",
        "repository": "https://www.npmjs.com/package/@minimax-ai/code",
        "version": "0.6.12",
        "distribution": {
            "npx": {"package": "@minimax-ai/code@0.6.12", "bin": "mcode", "args": ["acp"]}
        },
    },
    {
        "id": "codewhale",
        "name": "Codewhale",
        "description": "community DeepSeek-first coding agent (was DeepSeek-TUI)",
        "license": "MIT",
        "repository": "https://github.com/codewhale-hq/Codewhale",
        "version": "0.10.1",
        "distribution": {
            "npx": {"package": "codewhale@0.10.1", "bin": "codewhale", "args": ["serve", "--acp"]}
        },
    },
    {
        "id": "kode",
        "name": "Kode",
        "description": "open coding agent for any OpenAI-like endpoint",
        "license": "Apache-2.0",
        "repository": "https://github.com/shareAI-lab/Kode-CLI",
        "version": "2.2.1",
        "distribution": {
            "npx": {"package": "@shareai-lab/kode@2.2.1", "bin": "kode-acp", "args": []}
        },
    },
    {
        "id": "neovate",
        "name": "Neovate Code",
        "description": "Ant Group's coding agent",
        "license": "MIT",
        "repository": "https://github.com/neovateai/neovate-code",
        "version": "0.28.5",
        "distribution": {
            "npx": {"package": "@neovate/code@0.28.5", "bin": "neovate", "args": ["acp"]}
        },
    },
    {
        "id": "nanocoder",
        "name": "Nanocoder",
        "description": "local-first coding agent from the Nano Collective",
        "license": "MIT",
        "repository": "https://github.com/Nano-Collective/nanocoder",
        "version": "1.31.0",
        "distribution": {
            "npx": {
                "package": "@nanocollective/nanocoder@1.31.0",
                "bin": "nanocoder",
                "args": ["--acp"],
            }
        },
    },
    {
        "id": "strands",
        "name": "Strands CLI",
        "description": "AWS's open agent harness",
        "license": "Apache-2.0",
        "repository": "https://github.com/strands-agents/harness-sdk",
        "version": "0.2.1",
        "distribution": {
            "npx": {
                "package": "@strands-agents/cli@0.2.1",
                "bin": "strands",
                "args": ["--acp-server"],
            }
        },
    },
    {
        "id": "openhands",
        "name": "OpenHands",
        "description": "the OpenHands coding agent, as a CLI",
        "license": "MIT",
        "repository": "https://github.com/OpenHands/OpenHands-CLI",
        "version": "1.16.0",
        "distribution": {"uvx": {"package": "openhands==1.16.0", "args": ["acp"]}},
    },
    {
        "id": "qwenpaw",
        "name": "QwenPaw",
        "description": "Alibaba AgentScope's personal agent (was CoPaw)",
        "license": "Apache-2.0",
        "repository": "https://github.com/agentscope-ai/QwenPaw",
        "version": "2.2.2",
        "distribution": {"uvx": {"package": "qwenpaw==2.2.2", "args": ["acp"]}},
    },
    {
        "id": "open-interpreter",
        "name": "Open Interpreter",
        "description": "the new Rust Open Interpreter (a Codex fork)",
        "license": "Apache-2.0",
        "repository": "https://github.com/openinterpreter/openinterpreter",
        "distribution": {
            "path": {
                "cmd": "interpreter",
                "args": ["acp"],
                "install": "curl -fsSL https://www.openinterpreter.com/install | sh",
            }
        },
    },
    {
        "id": "gptme",
        "name": "gptme",
        "description": "a terminal agent with tools",
        "license": "MIT",
        "repository": "https://github.com/gptme/gptme",
        "distribution": {"path": {"cmd": "gptme-acp", "args": [], "install": "pipx install gptme"}},
    },
    {
        "id": "hermes",
        "name": "Hermes Agent",
        "description": "Nous Research's general personal agent",
        "license": "MIT",
        "repository": "https://github.com/NousResearch/hermes-agent",
        "distribution": {
            "path": {
                "cmd": "hermes",
                "args": ["acp"],
                "install": "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash",
            }
        },
    },
]


def _cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "alles" / "harness"


def _registry_file() -> Path:
    return data_dir() / "pi" / "acp-registry.json"


def platform_key() -> str:
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}.get(platform.system(), "")
    machine = platform.machine().lower()
    arch = (
        "aarch64"
        if machine in ("arm64", "aarch64")
        else "x86_64"
        if machine in ("x86_64", "amd64")
        else machine
    )
    return f"{system}-{arch}"


def is_open(entry: dict) -> bool:
    license_name = str(entry.get("license") or "").lower()
    return any(name in license_name for name in OPEN_LICENSES) and "proprietary" not in license_name


async def refresh_registry(force: bool = False) -> list[dict]:
    """the registry, fetched at most once a day; the last good copy is kept for offline use."""
    path = _registry_file()
    fresh = path.exists() and time.time() - path.stat().st_mtime < REGISTRY_MAX_AGE
    if force or not fresh:
        from services.net_guard import safe_get_public_async

        try:
            response = await safe_get_public_async(REGISTRY_URL, timeout=15, max_bytes=4_000_000)
            response.raise_for_status()
            agents = response.json().get("agents")
            if isinstance(agents, list):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"agents": agents}))
        except Exception:
            pass  # offline or the cdn is down; the cached copy still works
    try:
        return json.loads(path.read_text()).get("agents") or []
    except (OSError, ValueError):
        return []


def catalog(registry: list[dict]) -> list[dict]:
    """every harness alles knows, extras first, then the registry in its own order."""
    seen, rows = set(), []
    for entry in EXTRA + registry:
        if entry.get("id") in seen or entry.get("id") == "pi-acp":
            continue  # pi is driven natively, so its acp adapter would be a duplicate
        seen.add(entry["id"])
        rows.append(entry)
    return rows


def find(registry: list[dict], harness_id: str) -> dict | None:
    return next((e for e in catalog(registry) if e.get("id") == harness_id), None)


def _kind(entry: dict) -> tuple[str, dict]:
    if entry.get("native"):
        return "native", {}
    dist = entry.get("distribution") or {}
    if "npx" in dist:
        return "npx", dist["npx"]
    if "uvx" in dist:
        return "uvx", dist["uvx"]
    if "bun" in dist:
        return "bun", dist["bun"]
    binary = (dist.get("binary") or {}).get(platform_key())
    if binary:
        return "binary", binary
    if "path" in dist:
        return "path", dist["path"]
    return "unavailable", {}


def _home(entry: dict) -> Path:
    return _cache() / f"{entry['id']}-{entry.get('version') or 'any'}"


def _npm_bin(home: Path, package: str, wanted: str = "") -> Path | None:
    name = (
        package.rsplit("@", 1)[0]
        if package.count("@") > (1 if package.startswith("@") else 0)
        else package
    )
    manifest = home / "node_modules" / name / "package.json"
    try:
        bins = json.loads(manifest.read_text()).get("bin")
    except (OSError, ValueError):
        return None
    if wanted:
        bin_name = wanted
    elif isinstance(bins, str):
        bin_name = name.split("/")[-1]
    elif isinstance(bins, dict) and bins:
        bin_name = next(iter(bins))
    else:
        return None
    path = home / "node_modules" / ".bin" / bin_name
    return path if path.exists() else None


def launch(entry: dict) -> tuple[list[str], dict] | None:
    """the command and env that start this harness in ACP mode, or None when it isn't installed."""
    kind, spec = _kind(entry)
    home = _home(entry)
    env = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
    args = [str(a) for a in spec.get("args") or []]
    if kind == "npx":
        exe = _npm_bin(home, spec["package"], spec.get("bin", ""))
        return ([str(exe), *args], env) if exe else None
    if kind == "bun":
        exe = home / "bin" / spec.get("bin", entry["id"])
        found = exe if exe.exists() else shutil.which(spec.get("bin", ""))
        return ([str(found), *args], env) if found else None
    if kind == "uvx":
        exe = home / "venv" / "bin" / spec["package"].split("==")[0].split("[")[0]
        if exe.exists():
            return [str(exe), *args], env
        uvx = shutil.which("uvx")
        return ([uvx, spec["package"], *args], env) if uvx and (home / ".uvx").exists() else None
    if kind == "binary":
        exe = (home / spec["cmd"]).resolve()
        return ([str(exe), *args], env) if exe.exists() and home.resolve() in exe.parents else None
    if kind == "path":
        exe = shutil.which(spec["cmd"])
        return ([exe, *args], env) if exe else None
    return None


_jobs: dict[str, asyncio.Task] = {}
_errors: dict[str, str] = {}


def public(entry: dict) -> dict:
    kind, spec = _kind(entry)
    job = _jobs.get(entry["id"])
    if kind == "native":
        from services import pi_agent

        state = pi_agent.status()["state"]
    elif job is not None and not job.done():
        state = "installing"
    elif launch(entry):
        state = "ready"
    elif kind == "unavailable":
        state = "unavailable"
    elif _errors.get(entry["id"]):
        state = "failed"
    elif kind == "path":
        state = "manual"
    else:
        state = "missing"
    return {
        "id": entry["id"],
        "name": entry.get("name") or entry["id"],
        "description": entry.get("description") or "",
        "license": entry.get("license") or "unknown",
        "open_source": is_open(entry) or kind == "native",
        "version": entry.get("version") or "",
        "repository": entry.get("repository") or entry.get("website") or "",
        "install": kind,
        "install_hint": spec.get("install", "") if kind == "path" else "",
        "state": state,
        "error": _errors.get(entry["id"], ""),
    }


async def _run(*cmd: str, env: dict | None = None, cwd: Path | None = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, **(env or {})},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=900)
    except TimeoutError:
        proc.kill()
        raise RuntimeError("the install took longer than 15 minutes") from None
    if proc.returncode != 0:
        tail = (err or b"").decode(errors="replace").strip().splitlines()[-1:] or ["install failed"]
        raise RuntimeError(tail[0][:300])


async def _download(spec: dict, home: Path) -> None:
    from services.net_guard import safe_get_public_async

    url = spec["archive"]
    response = await safe_get_public_async(
        url, timeout=600, max_bytes=MAX_DOWNLOAD, max_redirects=5
    )
    response.raise_for_status()
    blob = response.content
    if spec.get("sha256") and hashlib.sha256(blob).hexdigest().lower() != spec["sha256"].lower():
        raise RuntimeError("the download did not match its published checksum")
    home.mkdir(parents=True, exist_ok=True)
    name = url.lower().split("?")[0]
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for member in archive.namelist():
                if (home / member).resolve() != home.resolve() and home.resolve() not in (
                    home / member
                ).resolve().parents:
                    raise RuntimeError("the archive tried to write outside its folder")
            archive.extractall(home)
    elif name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tbz2")):
        with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
            archive.extractall(home, filter="data")
    else:
        target = home / Path(spec["cmd"]).name
        target.write_bytes(blob)
    exe = home / spec["cmd"]
    if exe.exists():
        exe.chmod(exe.stat().st_mode | 0o755)


async def _install(entry: dict) -> None:
    kind, spec = _kind(entry)
    home = _home(entry)
    home.mkdir(parents=True, exist_ok=True)
    if kind == "npx":
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm was not found on this machine")
        await _run(
            npm, "install", "--prefix", str(home), "--no-audit", "--no-fund", spec["package"]
        )
    elif kind == "bun":
        bun = shutil.which("bun")
        if not bun:
            raise RuntimeError("this harness needs bun (bun.sh) on this machine")
        await _run(bun, "install", "-g", spec["package"], env={"BUN_INSTALL": str(home)})
    elif kind == "uvx":
        if shutil.which("uvx"):
            (home / ".uvx").write_text(spec["package"])
            await _run(shutil.which("uvx"), spec["package"], "--help")
        else:
            python = shutil.which("python3") or "python3"
            await _run(python, "-m", "venv", str(home / "venv"))
            await _run(str(home / "venv" / "bin" / "pip"), "install", "--quiet", spec["package"])
    elif kind == "binary":
        await _download(spec, home)
    else:
        raise RuntimeError("install this one yourself, then check again")


def install(entry: dict) -> dict:
    """start installing in the background; the list shows progress."""
    job = _jobs.get(entry["id"])
    if job is None or job.done():
        _errors.pop(entry["id"], None)

        async def run():
            try:
                await _install(entry)
            except Exception as exc:
                _errors[entry["id"]] = str(exc)[:300] or "install failed"

        _jobs[entry["id"]] = asyncio.get_running_loop().create_task(run())
    return public(entry)
