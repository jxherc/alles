"""
health — a simple health/fitness log. one row per measurement (weight, sleep hours,
workout minutes, meds, or a custom metric). the overview gives the latest reading plus
a trend series per metric over a range, for the hand-drawn SVG charts.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import HealthEntry, get_db

router = APIRouter(prefix="/api")

KINDS = ("weight", "sleep", "workout", "med", "custom")


def _d(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


# ── pure logic ──────────────────────────────────────────────────────────────────
def latest_per_kind(entries) -> dict:
    """most-recent entry per kind (by date, then insertion)."""
    out = {}
    for e in entries:
        cur = out.get(e.kind)
        # >= so a same-day correction (later-inserted row) replaces the earlier one —
        # entries arrive in insertion order, matching the "by date, then insertion" contract
        if cur is None or str(e.date) >= str(cur.date):
            out[e.kind] = e
    return out


def series_for(entries, kind: str) -> list:
    pts = [{"date": e.date, "value": e.value, "unit": e.unit} for e in entries if e.kind == kind]
    pts.sort(key=lambda p: p["date"])
    return pts


# ── serialization ──────────────────────────────────────────────────────────────
def _fmt(e: HealthEntry) -> dict:
    return {
        "id": e.id,
        "kind": e.kind,
        "date": e.date,
        "value": e.value,
        "unit": e.unit,
        "note": e.note,
        "label": e.label,
    }


# ── endpoints ──────────────────────────────────────────────────────────────────
@router.get("/health/{kind}/anomalies")
def health_anomalies(kind: str, k: float = 2.0, db: DbSession = Depends(get_db)):
    """4b - robust (MAD) anomaly flags + baseline for a health metric."""
    from services import life_stats

    rows = db.query(HealthEntry).filter_by(kind=kind).order_by(HealthEntry.date.asc()).all()
    series = [(r.date, r.value or 0.0) for r in rows]
    return {
        "kind": kind,
        "baseline": life_stats.health_baseline([v for _, v in series]),
        "anomalies": life_stats.health_anomalies(series, k=k),
    }


@router.get("/health")
def list_entries(kind: str = "", db: DbSession = Depends(get_db)):
    q = db.query(HealthEntry)
    if kind:
        q = q.filter(HealthEntry.kind == kind)
    rows = q.order_by(HealthEntry.date.desc(), HealthEntry.id.desc()).all()
    return {"entries": [_fmt(e) for e in rows]}


@router.get("/health/overview")
def overview(days: int = 365, db: DbSession = Depends(get_db)):
    from core.settings import load_settings

    targets = load_settings().get("health_targets") or {}
    since = (date.today() - timedelta(days=max(1, days))).isoformat()
    rows = db.query(HealthEntry).filter(HealthEntry.date >= since).all()
    # order by id so latest_per_kind sees insertion order (same-day correction wins)
    all_rows = db.query(HealthEntry).order_by(HealthEntry.id.asc()).all()  # latest ignores the range window
    latest = latest_per_kind(all_rows)
    out = []
    seen = set()
    for e in all_rows:
        if e.kind in seen:
            continue
        seen.add(e.kind)
        lt = latest.get(e.kind)
        t = targets.get(e.kind)
        out.append(
            {
                "kind": e.kind,
                "label": e.label,
                "latest": {"date": lt.date, "value": lt.value, "unit": lt.unit} if lt else None,
                "series": series_for(rows, e.kind),
                "target": t if isinstance(t, (int, float)) and t > 0 else None,
            }
        )
    return {"kinds": out, "days": days}


class TargetBody(BaseModel):
    kind: str
    value: float = 0


@router.put("/health/target")
def set_target(body: TargetBody):
    from core.settings import load_settings, save_settings

    targets = dict(load_settings().get("health_targets") or {})
    if body.value and body.value > 0:
        targets[body.kind] = body.value
    else:
        targets.pop(body.kind, None)  # 0 / negative clears it
    save_settings({"health_targets": targets})
    return {"kind": body.kind, "target": targets.get(body.kind)}


class ImportBody(BaseModel):
    text: str = ""


@router.post("/health/import")
def import_health(body: ImportBody, db: DbSession = Depends(get_db)):
    """import a simple date/kind/value/unit csv. returns how many rows were added."""
    from services.imports import parse_health_csv

    rows = parse_health_csv(body.text or "")
    n = 0
    for r in rows:
        d = (r["date"] or date.today().isoformat())[:10]
        try:
            _d(d)
        except ValueError:
            d = date.today().isoformat()
        db.add(HealthEntry(kind=r["kind"], value=r["value"], unit=r["unit"], date=d))
        n += 1
    db.commit()
    return {"imported": n}


class EntryBody(BaseModel):
    kind: str
    value: float
    unit: str = ""
    note: str = ""
    label: str = ""
    date: str = ""


@router.post("/health")
def create_entry(body: EntryBody, db: DbSession = Depends(get_db)):
    import math

    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")
    if not math.isfinite(body.value):
        raise HTTPException(400, "value must be a finite number")
    d = (body.date or date.today().isoformat())[:10]
    try:
        _d(d)
    except ValueError:
        raise HTTPException(400, "date must be ISO (YYYY-MM-DD)")
    e = HealthEntry(
        kind=body.kind,
        date=d,
        value=body.value,
        unit=body.unit.strip(),
        note=body.note.strip(),
        label=body.label.strip(),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return _fmt(e)


class EntryPatch(BaseModel):
    value: float | None = None
    unit: str | None = None
    note: str | None = None
    date: str | None = None


@router.patch("/health/{eid}")
def update_entry(eid: int, body: EntryPatch, db: DbSession = Depends(get_db)):
    e = db.get(HealthEntry, eid)
    if not e:
        raise HTTPException(404)
    if body.date is not None:
        try:
            _d(body.date)
        except ValueError:
            raise HTTPException(400, "date must be ISO (YYYY-MM-DD)")
        e.date = body.date[:10]
    for f in ("value", "unit", "note"):
        v = getattr(body, f)
        if v is not None:
            setattr(e, f, v.strip() if isinstance(v, str) else v)
    db.commit()
    return _fmt(e)


@router.delete("/health/{eid}")
def delete_entry(eid: int, db: DbSession = Depends(get_db)):
    e = db.get(HealthEntry, eid)
    if not e:
        raise HTTPException(404)
    db.delete(e)
    db.commit()
    return {"ok": True}
