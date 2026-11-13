"""Retained Watch checks and the snapshot shared by private and public views."""

from datetime import timedelta
from urllib.parse import urlsplit

from core.database import MonitorCheck

KEEP = 2200  # about 7.6 days at the default five-minute interval


def monitor_address(url, kind="http") -> str:
    """The address a check can reach, or "" when no check could.

    "example.com" means https://example.com. A site or health check fetches a page, so it
    takes http or https; a certificate check only needs a host, and a port when it isn't 443.
    """
    text = (url or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return ""
    full = text if "://" in text else "https://" + text
    try:
        parts = urlsplit(full)
        parts.port  # a port that isn't a number raises here
    except ValueError:
        return ""
    if not parts.hostname or (kind != "cert" and parts.scheme not in ("http", "https")):
        return ""
    return full


def uptime_pct(checks):
    """Percent of successful checks, or None when there are no checks."""
    checks = list(checks)
    if not checks:
        return None
    ok = sum(1 for check in checks if (check.ok if hasattr(check, "ok") else check))
    return round(100 * ok / len(checks), 1)


def record_check(db, monitor_id, ok, status_code=0, latency_ms=0, error="", detail="", keep=KEEP):
    """Append a result and prune this monitor's oldest retained checks."""
    check = MonitorCheck(
        monitor_id=monitor_id,
        ok=bool(ok),
        status_code=int(status_code or 0),
        latency_ms=int(latency_ms or 0),
        error=error or "",
        detail=detail or "",
    )
    db.add(check)
    db.commit()
    rows = (
        db.query(MonitorCheck.id)
        .filter(MonitorCheck.monitor_id == monitor_id)
        .order_by(MonitorCheck.id.desc())
        .all()
    )
    if len(rows) > keep:
        stale = [row[0] for row in rows[keep:]]
        db.query(MonitorCheck).filter(MonitorCheck.id.in_(stale)).delete(synchronize_session=False)
        db.commit()
    return check


def monitor_snapshot(db, monitor_id, now):
    checks = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.monitor_id == monitor_id)
        .order_by(MonitorCheck.id.desc())
        .limit(KEEP)
        .all()
    )
    latest = checks[0] if checks else None
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)
    return {
        "status": ("up" if latest.ok else "down") if latest else "unknown",
        "uptime_24h": uptime_pct([check for check in checks if check.ts and check.ts >= day_ago]),
        "uptime_7d": uptime_pct([check for check in checks if check.ts and check.ts >= week_ago]),
        "latest": (
            {
                "ok": latest.ok,
                "status_code": latest.status_code,
                "latency_ms": latest.latency_ms,
                "error": latest.error,
                "detail": latest.detail,
                "ts": latest.ts.isoformat() if latest.ts else "",
            }
            if latest
            else None
        ),
        "spark": [check.latency_ms for check in reversed(checks[:30])],
    }
