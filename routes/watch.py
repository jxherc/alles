"""
watch — uptime / status monitoring for EXTERNAL things (sites, /health endpoints,
TLS certs). distinct from the `system` app, which watches this machine. checks run
on the background job loop; we keep a rolling per-monitor history and compute uptime
% + a latency sparkline for the dashboard. the AI token/cost card on the same board
just reuses /api/usage/summary on the client — no new tracking here.
"""

import asyncio
import logging
import time as _time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Monitor, MonitorCheck, SessionLocal, _now, get_db

router = APIRouter(prefix="/api")
log = logging.getLogger("alles.watch")

KINDS = ("http", "health", "cert")
KEEP = 2200  # checks kept per monitor (~7.6 days at the 300s default, so the 7d uptime is real)


# ── pure logic (unit-tested without any network) ───────────────────────────────
def check_passes(
    kind, expect_status, expect_keyword, latency_ceiling_ms, status_code, body, latency_ms
):
    """did an http/health probe pass? returns (ok, reason-if-not)."""
    if expect_status:
        if status_code != expect_status:
            return False, f"status {status_code} != {expect_status}"
    elif not (200 <= status_code < 400):
        return False, f"status {status_code}"
    if expect_keyword and expect_keyword.lower() not in (body or "").lower():
        return False, "keyword missing"
    if latency_ceiling_ms and latency_ms > latency_ceiling_ms:
        return False, f"slow {latency_ms}ms > {latency_ceiling_ms}ms"
    return True, ""


def cert_days_left(not_after, now=None):
    return (not_after - (now or datetime.utcnow())).days


def uptime_pct(checks):
    """percent of ok checks in the given list, or None when there's nothing yet."""
    checks = list(checks)
    if not checks:
        return None
    ok = sum(1 for c in checks if (c.ok if hasattr(c, "ok") else c))
    return round(100 * ok / len(checks), 1)


def record_check(db, monitor_id, ok, status_code=0, latency_ms=0, error="", detail="", keep=KEEP):
    """append a check result, then prune the monitor's history down to `keep` rows."""
    c = MonitorCheck(
        monitor_id=monitor_id,
        ok=bool(ok),
        status_code=int(status_code or 0),
        latency_ms=int(latency_ms or 0),
        error=error or "",
        detail=detail or "",
    )
    db.add(c)
    db.commit()
    rows = (
        db.query(MonitorCheck.id)
        .filter(MonitorCheck.monitor_id == monitor_id)
        .order_by(MonitorCheck.id.desc())
        .all()
    )
    if len(rows) > keep:
        stale = [r[0] for r in rows[keep:]]
        db.query(MonitorCheck).filter(MonitorCheck.id.in_(stale)).delete(synchronize_session=False)
        db.commit()
    return c


# ── network probes (best-effort; never raise) ──────────────────────────────────
def _check_cert(monitor):
    import socket
    import ssl

    parsed = urlparse(monitor.url if "://" in monitor.url else "https://" + monitor.url)
    host = parsed.hostname or monitor.url
    port = parsed.port or 443
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                cert = ss.getpeercert()
        not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
        days = cert_days_left(not_after)
        ok = days > 0
        return {
            "ok": ok,
            "status_code": 0,
            "latency_ms": 0,
            "error": "" if ok else "certificate expired",
            "detail": f"{days}d",
        }
    except Exception as e:  # dns/timeout/handshake — all just "down"
        return {"ok": False, "status_code": 0, "latency_ms": 0, "error": str(e)[:200], "detail": ""}


def perform_check(monitor):
    """run the right probe for this monitor; returns a check dict, never raises."""
    if monitor.kind == "cert":
        return _check_cert(monitor)
    t0 = _time.monotonic()
    try:
        import httpx

        r = httpx.get(monitor.url, timeout=10, follow_redirects=True)
        latency = int((_time.monotonic() - t0) * 1000)
        body = r.text if (monitor.expect_keyword or monitor.kind == "health") else ""
        ok, err = check_passes(
            monitor.kind,
            monitor.expect_status,
            monitor.expect_keyword,
            monitor.latency_ceiling_ms,
            r.status_code,
            body,
            latency,
        )
        return {
            "ok": ok,
            "status_code": r.status_code,
            "latency_ms": latency,
            "error": err,
            "detail": "",
        }
    except Exception as e:
        latency = int((_time.monotonic() - t0) * 1000)
        return {
            "ok": False,
            "status_code": 0,
            "latency_ms": latency,
            "error": str(e)[:200],
            "detail": "",
        }


# ── background job (registered in app.py) ──────────────────────────────────────
async def run_checks():
    """probe every enabled monitor whose interval has elapsed; emit watch.down on a
    fresh failure so push/automations can react."""
    db = SessionLocal()
    try:
        now = _now()
        for m in db.query(Monitor).filter(Monitor.enabled == True).all():  # noqa: E712
            last = (
                db.query(MonitorCheck)
                .filter(MonitorCheck.monitor_id == m.id)
                .order_by(MonitorCheck.id.desc())
                .first()
            )
            if last and last.ts and (now - last.ts).total_seconds() < m.interval_secs:
                continue
            res = await asyncio.to_thread(perform_check, m)
            was_ok = last.ok if last else True
            record_check(db, m.id, **res)
            if was_ok and not res["ok"]:
                try:
                    from services import jobs

                    await jobs.emit(
                        "watch.down", monitor=m.name, url=m.url, error=res.get("error", "")
                    )
                except Exception as e:
                    log.warning(f"watch.down emit failed: {e}")
    finally:
        db.close()


# ── serialization ──────────────────────────────────────────────────────────────
def _fmt(m: Monitor) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "url": m.url,
        "kind": m.kind,
        "interval_secs": m.interval_secs,
        "expect_status": m.expect_status,
        "expect_keyword": m.expect_keyword,
        "latency_ceiling_ms": m.latency_ceiling_ms,
        "enabled": m.enabled,
        "created_at": m.created_at.isoformat() if m.created_at else "",
    }


# ── endpoints ──────────────────────────────────────────────────────────────────
@router.get("/watch")
def list_monitors(db: DbSession = Depends(get_db)):
    rows = db.query(Monitor).order_by(Monitor.created_at).all()
    return {"monitors": [_fmt(m) for m in rows]}


@router.get("/watch/overview")
def overview(db: DbSession = Depends(get_db)):
    now = _now()
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)
    out = []
    for m in db.query(Monitor).order_by(Monitor.created_at).all():
        checks = (
            db.query(MonitorCheck)
            .filter(MonitorCheck.monitor_id == m.id)
            .order_by(MonitorCheck.id.desc())
            .limit(KEEP)
            .all()
        )
        latest = checks[0] if checks else None
        d = _fmt(m)
        d["status"] = ("up" if latest.ok else "down") if latest else "unknown"
        d["uptime_24h"] = uptime_pct([c for c in checks if c.ts and c.ts >= day_ago])
        d["uptime_7d"] = uptime_pct([c for c in checks if c.ts and c.ts >= week_ago])
        d["latest"] = (
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
        )
        # oldest→newest latency series for the sparkline
        d["spark"] = [c.latency_ms for c in reversed(checks[:30])]
        out.append(d)
    return {"monitors": out}


@router.get("/watch/{mid}/history")
def history(mid: str, limit: int = 100, db: DbSession = Depends(get_db)):
    if not db.get(Monitor, mid):
        raise HTTPException(404)
    rows = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.monitor_id == mid)
        .order_by(MonitorCheck.id.desc())
        .limit(max(1, min(limit, KEEP)))
        .all()
    )
    return {
        "checks": [
            {
                "ok": c.ok,
                "status_code": c.status_code,
                "latency_ms": c.latency_ms,
                "error": c.error,
                "detail": c.detail,
                "ts": c.ts.isoformat() if c.ts else "",
            }
            for c in rows
        ]
    }


class MonitorBody(BaseModel):
    name: str
    url: str
    kind: str = "http"
    interval_secs: int = 300
    expect_status: int = 0
    expect_keyword: str = ""
    latency_ceiling_ms: int = 0
    enabled: bool = True


def _validate(name, url, kind):
    if not (name or "").strip():
        raise HTTPException(400, "name required")
    if not (url or "").strip():
        raise HTTPException(400, "url required")
    if kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")


@router.post("/watch")
def create_monitor(body: MonitorBody, db: DbSession = Depends(get_db)):
    _validate(body.name, body.url, body.kind)
    m = Monitor(
        name=body.name.strip(),
        url=body.url.strip(),
        kind=body.kind,
        interval_secs=max(10, body.interval_secs),
        expect_status=body.expect_status,
        expect_keyword=body.expect_keyword.strip(),
        latency_ceiling_ms=max(0, body.latency_ceiling_ms),
        enabled=body.enabled,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _fmt(m)


class MonitorPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    kind: str | None = None
    interval_secs: int | None = None
    expect_status: int | None = None
    expect_keyword: str | None = None
    latency_ceiling_ms: int | None = None
    enabled: bool | None = None


@router.patch("/watch/{mid}")
def update_monitor(mid: str, body: MonitorPatch, db: DbSession = Depends(get_db)):
    m = db.get(Monitor, mid)
    if not m:
        raise HTTPException(404)
    if body.kind is not None and body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")
    for field in (
        "name",
        "url",
        "kind",
        "interval_secs",
        "expect_status",
        "expect_keyword",
        "latency_ceiling_ms",
        "enabled",
    ):
        v = getattr(body, field)
        if v is not None:
            setattr(m, field, v)
    db.commit()
    return _fmt(m)


@router.delete("/watch/{mid}")
def delete_monitor(mid: str, db: DbSession = Depends(get_db)):
    m = db.get(Monitor, mid)
    if not m:
        raise HTTPException(404)
    db.query(MonitorCheck).filter(MonitorCheck.monitor_id == mid).delete(synchronize_session=False)
    db.delete(m)
    db.commit()
    return {"ok": True}


@router.post("/watch/{mid}/check")
def check_now(mid: str, db: DbSession = Depends(get_db)):
    """probe a monitor right now (manual refresh button)."""
    m = db.get(Monitor, mid)
    if not m:
        raise HTTPException(404)
    res = perform_check(m)
    record_check(db, m.id, **res)
    return res
