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
        if cur is None or str(e.date) > str(cur.date):
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
@router.get("/health")
def list_entries(kind: str = "", db: DbSession = Depends(get_db)):
    q = db.query(HealthEntry)
    if kind:
        q = q.filter(HealthEntry.kind == kind)
    rows = q.order_by(HealthEntry.date.desc(), HealthEntry.id.desc()).all()
    return {"entries": [_fmt(e) for e in rows]}


@router.get("/health/overview")
def overview(days: int = 365, db: DbSession = Depends(get_db)):
    since = (date.today() - timedelta(days=max(1, days))).isoformat()
    rows = db.query(HealthEntry).filter(HealthEntry.date >= since).all()
    all_rows = db.query(HealthEntry).all()  # latest ignores the range window
    latest = latest_per_kind(all_rows)
    out = []
    seen = set()
    for e in all_rows:
        if e.kind in seen:
            continue
        seen.add(e.kind)
        lt = latest.get(e.kind)
        out.append(
            {
                "kind": e.kind,
                "label": e.label,
                "latest": {"date": lt.date, "value": lt.value, "unit": lt.unit} if lt else None,
                "series": series_for(rows, e.kind),
            }
        )
    return {"kinds": out, "days": days}


class EntryBody(BaseModel):
    kind: str
    value: float
    unit: str = ""
    note: str = ""
    label: str = ""
    date: str = ""


@router.post("/health")
def create_entry(body: EntryBody, db: DbSession = Depends(get_db)):
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")
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
