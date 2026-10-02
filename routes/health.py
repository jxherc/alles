"""
health — a simple health/fitness log. one row per measurement (weight, sleep hours,
workout minutes, meds, or a custom metric). the overview gives the latest reading plus
a trend series per metric over a range, for the hand-drawn SVG charts.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import HealthCreateReceipt, HealthEntry, get_db
from services.health_entries import (
    HealthInputError,
    canonical_date,
    canonical_request_id,
    finite_value,
    recover_entry,
    recover_record,
    save_entry,
)

router = APIRouter(prefix="/api")

KINDS = ("weight", "sleep", "workout", "med", "custom")


# ── pure logic ──────────────────────────────────────────────────────────────────
def latest_per_kind(entries, key=None) -> dict:
    """most-recent entry per kind/key (by date, then insertion)."""
    key = key or (lambda e: e.kind)
    out = {}
    for e in entries:
        k = key(e)
        cur = out.get(k)
        # >= so a same-day correction (later-inserted row) replaces the earlier one —
        # entries arrive in insertion order, matching the "by date, then insertion" contract
        if cur is None or str(e.date) >= str(cur.date):
            out[k] = e
    return out


def series_for(entries, kind: str) -> list:
    pts = [{"date": e.date, "value": e.value, "unit": e.unit} for e in entries if e.kind == kind]
    pts.sort(key=lambda p: p["date"])
    return pts


# ── serialization ──────────────────────────────────────────────────────────────
def _fmt(e: HealthEntry) -> dict:
    return {
        "id": e.id,
        "record_id": e.record_id,
        "kind": e.kind,
        "date": e.date,
        "value": e.value,
        "unit": e.unit,
        "note": e.note,
        "label": e.label,
    }


# ── endpoints ──────────────────────────────────────────────────────────────────
@router.get("/health/requests/{request_id}")
def recover_saved_entry(request_id: str, db: DbSession = Depends(get_db)):
    try:
        return _fmt(recover_entry(db, request_id))
    except HealthInputError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


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
    from services import life_stats

    targets = load_settings().get("health_targets") or {}
    since = (date.today() - timedelta(days=max(1, days))).isoformat()
    rows = db.query(HealthEntry).filter(HealthEntry.date >= since).all()
    # bucket the in-range rows by (kind, label) once, tracking the latest per key by DATE (ties
    # broken by insertion via id-asc + >=) so a backfilled older-dated row can't beat a newer one.
    # a metric only gets a card if it has an entry in range, and for any such metric its globally
    # latest entry is necessarily in range too — so the in-range rows are all we need (no full scan).
    by_key: dict = {}
    rows = sorted(rows, key=lambda r: r.id)
    latest_kl = latest_per_kind(rows, key=lambda e: (e.kind, e.label or ""))
    for e in rows:
        key = (e.kind, e.label or "")
        by_key.setdefault(key, []).append(e)
    out = []
    for key, ser in by_key.items():
        rep = ser[0]  # representative entry for the card's kind/label
        lt = latest_kl.get(key)
        t = targets.get(rep.kind)
        # 4b - baseline + flag whether the latest value sits outside the usual range (robust MAD)
        raw = sorted(((r.date, r.value or 0.0) for r in ser), key=lambda p: p[0])
        anoms = {a["date"]: a for a in life_stats.health_anomalies(raw)}
        latest_anom = anoms.get(lt.date) if lt else None
        out.append(
            {
                "kind": rep.kind,
                "label": rep.label,
                "latest": {"date": lt.date, "value": lt.value, "unit": lt.unit} if lt else None,
                "series": series_for(ser, rep.kind),
                "target": t if isinstance(t, (int, float)) and t > 0 else None,
                "baseline": life_stats.health_baseline([v for _, v in raw]),
                "anomaly": (
                    {"z": latest_anom["z"], "dir": "high" if latest_anom["z"] > 0 else "low"}
                    if latest_anom
                    else None
                ),
            }
        )
    return {"kinds": out, "days": days}


class TargetBody(BaseModel):
    kind: str
    value: float = 0


@router.put("/health/target")
def set_target(body: TargetBody):
    from core.settings import load_settings, save_settings

    try:
        value = finite_value(body.value)
    except HealthInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    targets = dict(load_settings().get("health_targets") or {})
    if value > 0:
        targets[body.kind] = value
    else:
        targets.pop(body.kind, None)  # 0 / negative clears it
    save_settings({"health_targets": targets})
    return {"kind": body.kind, "target": targets.get(body.kind)}


class ImportBody(BaseModel):
    text: str = ""
    request_id: str = ""
    strict: bool = False


@router.post("/health/import")
def import_health(body: ImportBody, db: DbSession = Depends(get_db)):
    from services.health_imports import import_entries

    try:
        return import_entries(
            db, body.text, kinds=KINDS, request_id=body.request_id, strict=body.strict
        )
    except HealthInputError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


class EntryBody(BaseModel):
    kind: str
    value: float
    unit: str = ""
    note: str = ""
    label: str = ""
    date: str = ""
    request_id: str = ""


@router.post("/health")
def create_entry(body: EntryBody, db: DbSession = Depends(get_db)):
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(KINDS)}")
    try:
        e = save_entry(
            db,
            kind=body.kind,
            value=body.value,
            unit=body.unit,
            note=body.note,
            label=body.label,
            entry_date=body.date,
            request_id=body.request_id,
        )
    except HealthInputError as exc:
        detail = {"message": str(exc), "entry_id": exc.entry_id} if exc.entry_id else str(exc)
        raise HTTPException(exc.status_code, detail) from exc
    return _fmt(e)


class EntryPatch(BaseModel):
    value: float | None = None
    unit: str | None = None
    note: str | None = None
    date: str | None = None
    create_request_id: str = ""
    record_id: str = ""


@router.patch("/health/{eid}")
def update_entry(eid: int, body: EntryPatch, db: DbSession = Depends(get_db)):
    try:
        identity = canonical_request_id(body.create_request_id) if body.create_request_id else ""
        e = recover_entry(db, identity) if identity else db.get(HealthEntry, eid)
    except HealthInputError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if not e:
        raise HTTPException(404)
    if e.id != eid:
        raise HTTPException(409, "this save belongs to a different entry")
    if not e.record_id or (body.record_id and body.record_id != e.record_id):
        raise HTTPException(409, "this is a different entry; reload before editing")
    record_id = e.record_id
    changes = {}
    if body.value is not None:
        try:
            finite_value(body.value)
        except HealthInputError as exc:
            raise HTTPException(400, str(exc)) from exc
    if body.date is not None:
        try:
            changes["date"] = canonical_date(body.date)
        except HealthInputError as exc:
            raise HTTPException(400, str(exc)) from exc
    for f in ("value", "unit", "note"):
        v = getattr(body, f)
        if v is not None:
            changes[f] = v.strip() if isinstance(v, str) else v
    target = db.query(HealthEntry).filter_by(id=eid, record_id=record_id)
    if identity:
        target = target.filter(
            HealthEntry.id.in_(db.query(HealthCreateReceipt.entry_id).filter_by(id=identity))
        )
    if changes:
        # Bind the actual write to the displayed record, even when SQLite reuses its integer ID.
        if not target.update(changes, synchronize_session=False):
            db.rollback()
            raise HTTPException(410, "the original entry no longer exists; reload recent entries")
        db.commit()
    try:
        return _fmt(recover_record(db, eid, record_id))
    except HealthInputError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.delete("/health/{eid}")
def delete_entry(eid: int, db: DbSession = Depends(get_db), record_id: str = ""):
    e = db.get(HealthEntry, eid)
    if not e:
        raise HTTPException(404)
    if not e.record_id or (record_id and record_id != e.record_id):
        raise HTTPException(409, "this is a different entry; reload before deleting")
    if (
        not db.query(HealthEntry)
        .filter_by(id=eid, record_id=e.record_id)
        .delete(synchronize_session=False)
    ):
        db.rollback()
        raise HTTPException(410, "the original entry no longer exists; reload recent entries")
    # DELETE holds the write transaction before any receipt is changed or an ID can be reused.
    db.query(HealthCreateReceipt).filter_by(entry_id=eid).update(
        {HealthCreateReceipt.entry_id: None, HealthCreateReceipt.payload_hash: ""},
        synchronize_session=False,
    )
    db.commit()
    return {"ok": True}
