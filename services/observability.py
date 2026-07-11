"""Small, privacy-safe observability helpers for the single Alles process."""

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.settings import data_dir
from services.redaction import redact_mapping, redact_url

PROCESS_STARTED_AT = time.time()
_MAX_MESSAGE = 2000
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer\s+)[^\s,;]+"),
    re.compile(r"\b(?:alles|aide)_[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(
        r"(?i)\b(password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|secret)"
        r"(\s*[:=]\s*)([^\s,;]+)"
    ),
)
_SQL_PARAMETERS = re.compile(r"(?is)\[parameters:.*?(?=\n\(Background on this error:|\Z)")
_SAFE_EXTRA = ("event", "request_id", "method", "path", "status", "duration_ms")


def redact_text(value: object) -> str:
    """Remove common credentials and URL secrets from one log-safe string."""
    text = str(value or "")
    text = re.sub(r"https?://[^\s<>\"']+", lambda match: redact_url(match.group(0)), text)
    text = _SECRET_PATTERNS[0].sub(r"\1***", text)
    text = _SECRET_PATTERNS[1].sub("***", text)
    text = _SECRET_PATTERNS[2].sub("***", text)
    text = _SECRET_PATTERNS[3].sub(r"\1\2***", text)
    text = _SQL_PARAMETERS.sub("[parameters: ***]", text)
    if len(text) > _MAX_MESSAGE:
        return text[:_MAX_MESSAGE] + "…"
    return text


def redact_value(value):
    """Recursively mask named secrets and secret-like text in structured data."""
    value = redact_mapping(value)
    if isinstance(value, dict):
        return {str(key): redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    return redact_text(value) if isinstance(value, str) else value


class JsonFormatter(logging.Formatter):
    """One JSON object per line; only an explicit safe field list is copied."""

    def format(self, record: logging.LogRecord) -> str:
        row = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        for key in _SAFE_EXTRA:
            value = getattr(record, key, None)
            if value is not None:
                row[key] = redact_text(value) if isinstance(value, str) else value
        if record.exc_info:
            row["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": redact_text(record.exc_info[1]),
            }
        return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the process root logger without duplicating handlers on reload."""
    root = logging.getLogger()
    handler = next((h for h in root.handlers if getattr(h, "_alles_json", False)), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler._alles_json = True
        root.handlers.clear()
        root.addHandler(handler)
    handler.setFormatter(JsonFormatter())
    root.setLevel(level)


def new_request_id() -> str:
    return uuid.uuid4().hex


def actor_kind(headers: dict[bytes, bytes]) -> str:
    auth = headers.get(b"authorization", b"").decode("latin-1", "replace")
    if auth.startswith(("Bearer alles_", "Bearer aide_")):
        return "api_token"
    cookie = headers.get(b"cookie", b"").decode("latin-1", "replace")
    return "owner_session" if "aide_session=" in cookie else "local_owner"


def route_name(scope: dict) -> str:
    route = scope.get("route")
    path = getattr(route, "path", "") if route is not None else ""
    if path:
        return path
    raw = scope.get("path", "")
    if raw.startswith("/api/"):
        return "/api/[unmatched]"
    if raw.startswith("/v1/"):
        return "/v1/[unmatched]"
    return raw if raw in {"/", "/health", "/status"} else "/[unmatched]"


def runtime_health() -> dict:
    """Return process, database, and scheduler health without host-private details."""
    from sqlalchemy import text

    from core.database import SessionLocal
    from services import jobs

    now_wall = time.time()
    now_mono = time.monotonic()
    db_ok = True
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception:
        db_ok = False

    job_rows = []
    max_lag = 0.0
    for job in jobs.all_jobs():
        never_ran = job.last_run == float("-inf")
        lag = 0.0 if never_ran else max(0.0, now_mono - job.last_run - job.interval)
        max_lag = max(max_lag, lag)
        job_rows.append(
            {
                "name": job.name,
                "enabled": job.enabled,
                "runs": job.runs,
                "fails": job.fails,
                "interval_seconds": job.interval,
                "lag_seconds": round(lag, 3),
                "running": job.running,
                "last_error": job.last_error,
            }
        )
    return {
        "ok": db_ok,
        "process": {
            "pid": os.getpid(),
            "started_at": datetime.fromtimestamp(PROCESS_STARTED_AT, timezone.utc).isoformat(),
            "uptime_seconds": round(now_wall - PROCESS_STARTED_AT, 3),
        },
        "database": {"ok": db_ok},
        "scheduler": {
            "ok": all(not row["last_error"] for row in job_rows),
            "max_lag_seconds": round(max_lag, 3),
            "jobs": job_rows,
        },
    }


def read_recent_logs(limit: int = 100, path: Path | None = None) -> list[dict]:
    """Read only structured lines; old plain-text logs are never exposed by the API."""
    path = path or data_dir() / "alles-server.log"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text("utf-8", errors="replace").splitlines()[-max(limit * 4, limit) :]:
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(row, dict):
            rows.append(redact_value(row))
    return rows[-limit:]
