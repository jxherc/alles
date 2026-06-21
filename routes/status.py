"""public status page for watch monitors. served at /status (a non-/api path, so the
auth middleware doesn't gate it) and only when the user has switched it on. config is
set from the watch view via /api/status/config (that one IS behind auth)."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Monitor, MonitorCheck, _now, get_db
from core.settings import load_settings, save_settings

router = APIRouter()


def _status_data(db) -> list[dict]:
    from routes.watch import uptime_pct

    now = _now()
    day_ago = now - timedelta(hours=24)
    out = []
    for m in db.query(Monitor).order_by(Monitor.created_at).all():
        checks = (
            db.query(MonitorCheck)
            .filter(MonitorCheck.monitor_id == m.id)
            .order_by(MonitorCheck.id.desc())
            .limit(200)
            .all()
        )
        latest = checks[0] if checks else None
        out.append(
            {
                "name": m.name,
                "url": m.url,
                "status": ("up" if latest.ok else "down") if latest else "unknown",
                "uptime": uptime_pct([c for c in checks if c.ts and c.ts >= day_ago]),
                "latency": latest.latency_ms if latest else None,
            }
        )
    return out


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_DOT = {"up": "#4ade80", "down": "#f87171", "unknown": "#6e6e6e"}


def _row(m) -> str:
    meta = m["status"]
    if m["uptime"] is not None:
        meta += " · {}% 24h".format(m["uptime"])
    if m["latency"]:
        meta += " · {}ms".format(m["latency"])
    dot = _DOT[m["status"]]
    return (
        '<li><span class="dot" style="background:{dot}"></span>'
        '<span class="nm">{nm}</span><span class="st">{meta}</span></li>'
    ).format(dot=dot, nm=_esc(m["name"]), meta=meta)


def _render(title, mons) -> str:
    if mons:
        up = sum(1 for m in mons if m["status"] == "up")
        head = "{}/{} operational".format(up, len(mons))
        rows = "".join(_row(m) for m in mons)
    else:
        head = "no monitors yet"
        rows = ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root{{color-scheme:dark}}
  body{{margin:0;background:#0a0a0a;color:#e8e6e3;font:14px/1.5 'Inter',-apple-system,sans-serif;
    display:flex;justify-content:center;padding:8vh 1rem}}
  main{{width:100%;max-width:560px}}
  h1{{font-size:1.4rem;font-weight:300;letter-spacing:-0.02em;margin:0 0 0.2rem}}
  .sub{{color:#6e6e6e;font-size:0.8rem;margin-bottom:1.6rem;text-transform:lowercase;letter-spacing:0.04em}}
  ul{{list-style:none;margin:0;padding:0}}
  li{{display:flex;align-items:center;gap:0.7rem;padding:0.7rem 0;border-top:1px solid #2e2e2e}}
  .dot{{width:9px;height:9px;border-radius:50%;flex:0 0 auto}}
  .nm{{flex:1;font-weight:500}}
  .st{{color:#6e6e6e;font-size:0.74rem;font-variant-numeric:tabular-nums}}
  footer{{margin-top:2rem;color:#2e2e2e;font-size:0.66rem;letter-spacing:0.05em}}
</style></head><body><main>
  <h1>{_esc(title)}</h1>
  <div class="sub">{_esc(head)}</div>
  <ul>{rows}</ul>
  <footer>powered by alles · watch</footer>
</main></body></html>"""


@router.get("/status", response_class=HTMLResponse)
def status_page(db: DbSession = Depends(get_db)):
    s = load_settings()
    if not s.get("status_page_enabled"):
        raise HTTPException(404)
    return HTMLResponse(_render(s.get("status_page_title") or "status", _status_data(db)))


class StatusConfig(BaseModel):
    enabled: bool | None = None
    title: str | None = None


@router.get("/api/status/config")
def get_config():
    s = load_settings()
    return {"enabled": bool(s.get("status_page_enabled")), "title": s.get("status_page_title") or "status"}


@router.put("/api/status/config")
def set_config(body: StatusConfig):
    patch = {}
    if body.enabled is not None:
        patch["status_page_enabled"] = bool(body.enabled)
    if body.title is not None:
        patch["status_page_title"] = body.title.strip()[:60] or "status"
    if patch:
        save_settings(patch)
    s = load_settings()
    return {"enabled": bool(s.get("status_page_enabled")), "title": s.get("status_page_title") or "status"}
