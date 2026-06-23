"""
habits — a dedicated habit tracker (the journal has streaks, but no habit grid). a
HabitLog row = done on that day; toggling adds/removes it. streak + completion math is
pure (unit-tested); the overview feeds the contribution-grid UI.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Habit, HabitLog, get_db

router = APIRouter(prefix="/api")

CADENCES = ("daily", "weekly")


def _d(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


# ── pure logic ──────────────────────────────────────────────────────────────────
def daily_streak(dates: set, today: date) -> int:
    """consecutive done-days ending today (with a grace day so an as-yet-undone today
    doesn't zero a real run)."""
    s = 0
    d = today
    if today.isoformat() not in dates:
        d = today - timedelta(days=1)
    while d.isoformat() in dates:
        s += 1
        d -= timedelta(days=1)
    return s


def week_done_count(dates: set, today: date) -> int:
    """done-days within the trailing 7-day window ending today."""
    start = today - timedelta(days=6)
    return sum(1 for s in dates if start <= _d(s) <= today)


def completion_pct(cadence: str, target: int, dates: set, today: date) -> int:
    done = week_done_count(dates, today)
    if cadence == "weekly":
        return min(100, round(done / max(1, target) * 100))
    return round(done / 7 * 100)


def build_grid(dates: set, today: date, n: int) -> list:
    """oldest→newest list of {date, done} for the last n days."""
    out = []
    for i in range(n - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        out.append({"date": d, "done": d in dates})
    return out


# ── serialization ──────────────────────────────────────────────────────────────
def _dates_for(db, hid) -> set:
    return {r.date for r in db.query(HabitLog).filter(HabitLog.habit_id == hid).all()}


def _fmt(h: Habit, dates: set | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    dates = dates if dates is not None else set()
    return {
        "id": h.id,
        "name": h.name,
        "icon": h.icon,
        "color": h.color,
        "cadence": h.cadence,
        "target": h.target,
        "archived": h.archived,
        "streak": daily_streak(dates, today),
        "week_done": week_done_count(dates, today),
        "pct": completion_pct(h.cadence, h.target, dates, today),
        "done_today": today.isoformat() in dates,
        "grid": build_grid(dates, today, 119),  # ~17 weeks
    }


# ── endpoints ──────────────────────────────────────────────────────────────────
@router.get("/habits/{hid}/risk")
def habit_risk(hid: str, window: int = 14, db: DbSession = Depends(get_db)):
    """4b - failure risk today from the recent completion pattern."""
    from services import life_stats

    if not db.get(Habit, hid):
        raise HTTPException(404, "habit not found")
    done = [r.date for r in db.query(HabitLog).filter_by(habit_id=hid).all()]
    return life_stats.habit_failure_risk(done, date.today(), window=window)


@router.get("/habits/overview")
def overview(date_q: str = "", db: DbSession = Depends(get_db)):
    today = _d(date_q) if date_q else date.today()
    out = []
    for h in db.query(Habit).filter(Habit.archived == False).order_by(Habit.created_at).all():  # noqa: E712
        out.append(_fmt(h, _dates_for(db, h.id), today))
    return {"habits": out}


class HabitBody(BaseModel):
    name: str
    icon: str = ""
    color: str = ""
    cadence: str = "daily"
    target: int = 1


@router.post("/habits")
def create_habit(body: HabitBody, db: DbSession = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(400, "name required")
    if body.cadence not in CADENCES:
        raise HTTPException(400, f"cadence must be one of {', '.join(CADENCES)}")
    h = Habit(
        name=body.name.strip(),
        icon=body.icon.strip(),
        color=body.color.strip(),
        cadence=body.cadence,
        target=max(1, body.target),
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return _fmt(h, set())


class HabitPatch(BaseModel):
    name: str | None = None
    icon: str | None = None
    color: str | None = None
    cadence: str | None = None
    target: int | None = None
    archived: bool | None = None


@router.patch("/habits/{hid}")
def update_habit(hid: str, body: HabitPatch, db: DbSession = Depends(get_db)):
    h = db.get(Habit, hid)
    if not h:
        raise HTTPException(404)
    if body.cadence is not None and body.cadence not in CADENCES:
        raise HTTPException(400, f"cadence must be one of {', '.join(CADENCES)}")
    for f in ("name", "icon", "color", "cadence", "target", "archived"):
        v = getattr(body, f)
        if v is not None:
            if isinstance(v, str) and f in ("name", "icon", "color"):
                v = v.strip()
            setattr(h, f, v)
    db.commit()
    return _fmt(h, _dates_for(db, h.id))


@router.delete("/habits/{hid}")
def delete_habit(hid: str, db: DbSession = Depends(get_db)):
    h = db.get(Habit, hid)
    if not h:
        raise HTTPException(404)
    db.query(HabitLog).filter(HabitLog.habit_id == hid).delete(synchronize_session=False)
    db.delete(h)
    db.commit()
    return {"ok": True}


class ToggleBody(BaseModel):
    date: str = ""


@router.post("/habits/{hid}/toggle")
def toggle(hid: str, body: ToggleBody, db: DbSession = Depends(get_db)):
    h = db.get(Habit, hid)
    if not h:
        raise HTTPException(404)
    d = (body.date or date.today().isoformat())[:10]
    try:
        _d(d)  # don't let a junk date land in the log — it'd blow up the overview later
    except ValueError:
        raise HTTPException(400, "date must be ISO (YYYY-MM-DD)")
    existing = db.query(HabitLog).filter(HabitLog.habit_id == hid, HabitLog.date == d).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"done": False, "date": d}
    db.add(HabitLog(habit_id=hid, date=d))
    db.commit()
    return {"done": True, "date": d}
