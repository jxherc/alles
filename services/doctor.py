"""
readiness checks for a fresh install — surfaced via `alles doctor`, the boot
log, and GET /health. each check is cheap and import-light: dependency checks
use find_spec (no import), and the DB check is lazy, so this module loads even
when the app's own deps aren't installed yet (that's the whole point of doctor).
"""

import sys
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# import-name → why it matters. python-multipart imports as `multipart`,
# python-dotenv as `dotenv`, beautifulsoup4 as `bs4`, pillow as `PIL`.
_REQUIRED = [
    ("fastapi", "web framework"),
    ("uvicorn", "server"),
    ("sqlalchemy", "database"),
    ("pydantic", "request/response models"),
    ("httpx", "outbound http"),
    ("cryptography", "vault + push encryption"),
    ("bcrypt", "password hashing"),
    ("multipart", "file uploads"),
    ("dotenv", ".env loading"),
]
_OPTIONAL = [
    ("fastembed", "semantic memory search (else keyword fallback)"),
    ("docx", "vault .docx export"),
    ("PIL", "photo thumbnails + EXIF"),
    ("bs4", "research html parsing"),
    ("trafilatura", "research article extraction"),
    ("ddgs", "keyless web search"),
    ("pyautogui", "agent computer-use (opt-in)"),
    ("faster_whisper", "offline voice STT (opt-in)"),
    ("caldav", "calendar CalDAV sync (opt-in)"),
]

# checks whose failure means the server genuinely can't run
_HARD = {"python", "required dependencies", "data directory"}


def _have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def check_python():
    v = sys.version_info
    ok = v >= (3, 10)
    detail = f"{v.major}.{v.minor}.{v.micro}" + ("" if ok else " — need >= 3.10")
    return ok, "python", detail


def check_required_deps():
    missing = [f"{m} ({why})" for m, why in _REQUIRED if not _have(m)]
    detail = "all present" if not missing else "MISSING: " + ", ".join(missing)
    return (not missing), "required dependencies", detail


def check_optional_deps():
    present = [m for m, _ in _OPTIONAL if _have(m)]
    missing = [m for m, _ in _OPTIONAL if not _have(m)]
    detail = f"{len(present)}/{len(_OPTIONAL)} installed"
    if missing:
        detail += " — not installed: " + ", ".join(missing)
    return True, "optional dependencies", detail  # always ok — these degrade gracefully


def check_data_dir():
    d = ROOT / "data"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".doctor-write-test"
        probe.write_text("ok")
        probe.unlink()
        return True, "data directory", f"writable ({d})"
    except Exception as e:
        return False, "data directory", f"NOT writable: {e}"


def check_secret_key():
    exists = (ROOT / "data" / "secret.key").exists()
    return True, "at-rest encryption key", "present" if exists else "will be generated on first run"


def check_endpoint_configured():
    # lazy import — the DB layer needs sqlalchemy, which may be the very thing missing
    try:
        from core.database import SessionLocal, ModelEndpoint

        db = SessionLocal()
        try:
            eps = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
            usable = [e for e in eps if e.models_list()]
        finally:
            db.close()
        if usable:
            return True, "ai provider", f"{len(usable)} usable endpoint(s)"
        return (
            True,
            "ai provider",
            "none yet — add one in settings → models (this is normal on a fresh install)",
        )
    except Exception as e:
        return False, "ai provider", f"check skipped: {e}"


_CHECKS = [
    check_python,
    check_required_deps,
    check_optional_deps,
    check_data_dir,
    check_secret_key,
    check_endpoint_configured,
]


def run_all() -> list[dict]:
    out = []
    for fn in _CHECKS:
        try:
            ok, label, detail = fn()
        except Exception as e:  # a check must never crash the doctor
            ok, label, detail = False, fn.__name__, f"errored: {e}"
        out.append({"ok": ok, "label": label, "detail": detail})
    return out


def healthy() -> bool:
    """True when every HARD requirement passes (optional/provider gaps don't count)."""
    return all(c["ok"] for c in run_all() if c["label"] in _HARD)
