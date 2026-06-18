import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx

from core.database import ModelEndpoint
from core.settings import save_settings


OLLAMA_BASE_URL = os.environ.get("AIDE_OLLAMA_URL", "http://localhost:11434").rstrip("/")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$")

PRESETS = [
    {
        "id": "tiny",
        "label": "Tiny local",
        "model": "llama3.2:3b",
        "family": "Llama",
        "params_b": 3,
        "quant": "Q4",
        "vram_gb": 3,
        "ram_gb": 8,
        "notes": "Fast starter model for laptops and small GPUs.",
    },
    {
        "id": "coder-small",
        "label": "Coder small",
        "model": "qwen2.5-coder:7b",
        "family": "Qwen Coder",
        "params_b": 7,
        "quant": "Q4",
        "vram_gb": 6,
        "ram_gb": 12,
        "notes": "Good code assistant if your GPU is modest.",
    },
    {
        "id": "daily",
        "label": "Daily driver",
        "model": "llama3.1:8b",
        "family": "Llama",
        "params_b": 8,
        "quant": "Q4",
        "vram_gb": 7,
        "ram_gb": 16,
        "notes": "Balanced chat model for everyday local use.",
    },
    {
        "id": "reasoning",
        "label": "Reasoning local",
        "model": "deepseek-r1:8b",
        "family": "DeepSeek R1",
        "params_b": 8,
        "quant": "Q4",
        "vram_gb": 7,
        "ram_gb": 16,
        "notes": "Local reasoning preset with thinking output.",
    },
    {
        "id": "coder-mid",
        "label": "Coder mid",
        "model": "qwen2.5-coder:14b",
        "family": "Qwen Coder",
        "params_b": 14,
        "quant": "Q4",
        "vram_gb": 11,
        "ram_gb": 24,
        "notes": "Stronger local coding if you have a larger GPU.",
    },
    {
        "id": "large",
        "label": "Large local",
        "model": "llama3.3:70b",
        "family": "Llama",
        "params_b": 70,
        "quant": "Q4",
        "vram_gb": 42,
        "ram_gb": 64,
        "notes": "For high VRAM cards or CPU/RAM-heavy serving.",
    },
]

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_serve_proc: subprocess.Popen | None = None
_MAX_JOBS = 40


def _run(cmd: list[str], timeout: int = 8) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _ollama_http_client(**kw):
    # Localhost requests should not be routed through HTTP_PROXY/HTTPS_PROXY.
    return httpx.AsyncClient(trust_env=False, **kw)


def _ollama_http_client_sync(**kw):
    return httpx.Client(trust_env=False, **kw)


def _total_ram_gb() -> int:
    try:
        if platform.system().lower() == "windows":
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(MemoryStatusEx)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024**3))
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round(pages * page_size / (1024**3))
    except Exception:
        return 0


def _gpus() -> list[dict]:
    if not shutil.which("nvidia-smi"):
        return []
    try:
        r = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ]
        )
        if r.returncode != 0:
            return []
        out = []
        for line in r.stdout.splitlines():
            if "," not in line:
                continue
            name, mem = line.rsplit(",", 1)
            try:
                vram_gb = round(int(mem.strip()) / 1024)
            except ValueError:
                vram_gb = 0
            out.append({"name": name.strip(), "vram_gb": vram_gb})
        return out
    except Exception:
        return []


def hardware_profile() -> dict:
    gpus = _gpus()
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "ram_gb": _total_ram_gb(),
        "gpus": gpus,
        "best_vram_gb": max([g["vram_gb"] for g in gpus], default=0),
    }


async def installed_models() -> list[str]:
    try:
        async with _ollama_http_client(timeout=4) as c:
            r = await c.get(f"{OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
            data = r.json()
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


async def ollama_status() -> dict:
    exe = shutil.which("ollama")
    running = False
    models = []
    try:
        async with _ollama_http_client(timeout=3) as c:
            r = await c.get(f"{OLLAMA_BASE_URL}/api/tags")
            running = r.status_code == 200
            if running:
                models = [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
    except Exception:
        running = False

    version = ""
    if exe:
        try:
            r = _run([exe, "--version"])
            version = (r.stdout or r.stderr).strip()
        except Exception:
            version = ""

    return {
        "installed": bool(exe),
        "path": exe or "",
        "running": running,
        "base_url": OLLAMA_BASE_URL,
        "version": version,
        "models": models,
    }


def _fit(preset: dict, hw: dict, installed: set[str]) -> dict:
    best_vram = hw.get("best_vram_gb") or 0
    ram = hw.get("ram_gb") or 0
    if best_vram >= preset["vram_gb"]:
        status = "fits_gpu"
        reason = f"GPU fit: needs about {preset['vram_gb']} GB VRAM."
        score = 100 - preset["vram_gb"]
    elif ram >= preset["ram_gb"]:
        status = "fits_cpu"
        reason = f"CPU/RAM fallback: needs about {preset['ram_gb']} GB RAM."
        score = 50 - preset["ram_gb"]
    else:
        status = "too_large"
        reason = f"Likely too large: needs about {preset['vram_gb']} GB VRAM or {preset['ram_gb']} GB RAM."
        score = 0 - preset["ram_gb"]
    out = dict(preset)
    out.update(
        {
            "fit": status,
            "fit_reason": reason,
            "installed": preset["model"] in installed,
            "score": score + (10 if preset["model"] in installed else 0),
        }
    )
    return out


async def hwfit() -> dict:
    hw = hardware_profile()
    installed = set(await installed_models())
    presets = [_fit(p, hw, installed) for p in PRESETS]
    presets.sort(key=lambda p: (p["score"], p["params_b"]), reverse=True)
    return {"hardware": hw, "presets": presets}


# ── real hardware-aware catalog (hwfit / llmfit engine) ────────────────────────
# the 6 PRESETS above are the legacy fallback; this is the 900+ model catalog
# scored against detected hardware (bandwidth/VRAM/quant/MoE aware).

# the hardware probe shells out (nvidia-smi / wmi / rocminfo) — cache it briefly
# so the cookbook's rapid search/sort/filter calls don't re-probe every keystroke.
# hardware barely changes; a short TTL still picks up a plugged-in GPU eventually.
_sys_cache: dict | None = None
_sys_cache_at: float = 0.0
_SYS_TTL = 60


def detect_system_info(refresh: bool = False) -> dict:
    global _sys_cache, _sys_cache_at
    now = time.time()
    if refresh or _sys_cache is None or now - _sys_cache_at > _SYS_TTL:
        from services.hwfit import hardware

        _sys_cache = hardware.detect_system()
        _sys_cache_at = now
    return _sys_cache


def _short_name(name: str) -> str:
    return (name or "").split("/")[-1].lower()


async def model_catalog(
    use_case=None,
    search=None,
    sort="score",
    quant=None,
    target_context=None,
    fit_only=False,
    limit=60,
) -> dict:
    from services.hwfit import fit

    sysinfo = detect_system_info()
    rows = fit.rank_models(
        sysinfo,
        use_case=use_case,
        limit=limit,
        search=search,
        sort=sort,
        quant=quant,
        target_context=target_context,
        fit_only=fit_only,
    )
    # flag rows we've already pulled in ollama (best-effort name match)
    installed = set(await installed_models())
    inst_short = {_short_name(m) for m in installed}
    for r in rows:
        r["installed"] = (
            _short_name(r.get("name", "")) in inst_short or r.get("name", "").lower() in installed
        )
    return {"system": sysinfo, "models": rows, "count": len(rows)}


def _validate_model(model: str) -> str:
    model = (model or "").strip()
    preset_models = {p["model"] for p in PRESETS}
    if model not in preset_models and not MODEL_RE.match(model):
        raise ValueError("invalid model name")
    return model


def start_ollama() -> dict:
    global _serve_proc
    exe = shutil.which("ollama")
    if not exe:
        return {"ok": False, "error": "ollama is not installed or not on PATH"}
    if _ollama_running_sync():
        return {"ok": True, "started": False, "external": True}
    if _serve_proc and _serve_proc.poll() is None:
        return {"ok": True, "started": False, "pid": _serve_proc.pid}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(DATA_DIR / "ollama.log", "a", encoding="utf-8")
    kwargs = {"stdout": log, "stderr": log}
    if platform.system().lower() == "windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _serve_proc = subprocess.Popen([exe, "serve"], **kwargs)
    return {"ok": True, "started": True, "pid": _serve_proc.pid}


def _ollama_running_sync() -> bool:
    try:
        with _ollama_http_client_sync(timeout=2) as c:
            return c.get(f"{OLLAMA_BASE_URL}/api/tags").status_code == 200
    except Exception:
        return False


async def _wait_for_ollama(timeout_s: float = 5.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if (await ollama_status()).get("running"):
            return True
        await asyncio.sleep(0.35)
    return False


def _set_job(job_id: str, **patch):
    with _jobs_lock:
        job = _jobs.setdefault(job_id, {})
        job.update(patch)
        job["updated_at"] = time.time()
        _prune_jobs_locked()


def _prune_jobs_locked():
    if len(_jobs) <= _MAX_JOBS:
        return
    finished = [
        (jid, job.get("finished_at") or job.get("updated_at") or 0)
        for jid, job in _jobs.items()
        if job.get("status") in ("done", "error")
    ]
    for jid, _ in sorted(finished, key=lambda item: item[1])[: len(_jobs) - _MAX_JOBS]:
        _jobs.pop(jid, None)


def _download_worker(job_id: str, model: str):
    exe = shutil.which("ollama")
    if not exe:
        _set_job(job_id, status="error", error="ollama is not installed or not on PATH")
        return
    try:
        _set_job(job_id, status="running", output="")
        proc = subprocess.Popen(
            [exe, "pull", model],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        chunks = []
        assert proc.stdout is not None
        for line in proc.stdout:
            chunks.append(line)
            if len(chunks) > 80:
                chunks = chunks[-80:]
            _set_job(job_id, output="".join(chunks))
        rc = proc.wait()
        if rc == 0:
            _set_job(job_id, status="done", output="".join(chunks), finished_at=time.time())
        else:
            _set_job(
                job_id,
                status="error",
                output="".join(chunks),
                error=f"ollama pull exited {rc}",
                finished_at=time.time(),
            )
    except Exception as e:
        _set_job(job_id, status="error", error=str(e), finished_at=time.time())


def download_model(model: str) -> dict:
    model = _validate_model(model)
    active = find_active_download(model)
    if active:
        return active
    job_id = str(uuid.uuid4())
    _set_job(
        job_id,
        id=job_id,
        type="download_model",
        model=model,
        status="queued",
        created_at=time.time(),
    )
    t = threading.Thread(target=_download_worker, args=(job_id, model), daemon=True)
    t.start()
    return get_job(job_id)


def delete_model(model: str) -> dict:
    model = _validate_model(model)
    exe = shutil.which("ollama")
    if not exe:
        return {"ok": False, "error": "ollama is not installed or not on PATH"}
    try:
        r = _run([exe, "rm", model], timeout=30)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if r.returncode == 0:
        return {"ok": True, "model": model}
    return {"ok": False, "error": (r.stderr or r.stdout or "ollama rm failed").strip()}


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def list_jobs() -> list[dict]:
    with _jobs_lock:
        return sorted(
            (dict(job) for job in _jobs.values()),
            key=lambda j: j.get("created_at", 0),
            reverse=True,
        )


def find_active_download(model: str) -> dict | None:
    with _jobs_lock:
        for job in _jobs.values():
            if (
                job.get("type") == "download_model"
                and job.get("model") == model
                and job.get("status") in ("queued", "running")
            ):
                return dict(job)
    return None


def ensure_ollama_endpoint(db) -> ModelEndpoint:
    eps = db.query(ModelEndpoint).all()
    for ep in eps:
        if ep.base_url.rstrip("/") == OLLAMA_BASE_URL:
            ep.enabled = True
            return ep
    ep = ModelEndpoint(name="Ollama", base_url=OLLAMA_BASE_URL, api_key="", enabled=True)
    db.add(ep)
    db.flush()
    return ep


async def serve_model(model: str, db, autostart: bool = True, set_default: bool = True) -> dict:
    model = _validate_model(model)
    status = await ollama_status()
    started = {"ok": True, "started": False}
    if not status["running"] and autostart:
        started = start_ollama()
        await _wait_for_ollama()
        status = await ollama_status()

    if not status["running"]:
        return {"ok": False, "error": "ollama is not running", "start": started}

    models = set(status.get("models") or await installed_models())
    if model not in models:
        return {"ok": False, "error": f"{model} is not downloaded", "download_required": True}

    ep = ensure_ollama_endpoint(db)
    ep.cached_models = json.dumps(sorted(models))
    db.commit()
    db.refresh(ep)
    if set_default:
        save_settings({"default_endpoint_id": ep.id, "default_model": model})
    return {
        "ok": True,
        "endpoint_id": ep.id,
        "base_url": ep.base_url,
        "model": model,
        "start": started,
    }
