"""
habits — a dedicated habit tracker (the journal has streaks, but no habit grid). a
HabitLog row = done on that day; toggling adds/removes it. streak + completion math is
pure (unit-tested); the overview feeds the contribution-grid UI.
"""

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from core.database import Habit, HabitCreateReceipt, HabitLog, get_db
from core.schema.base import local_date
from services import habit_kinds, habit_logs

router = APIRouter(prefix="/api")

CADENCES = ("daily", "weekly")
# loggers that pick up that day's body weight (bodyweight and assisted movements)
WEIGHT_KINDS = ("workout", "pushups", "squats", "pullups")


def _d(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


# ── pure logic ──────────────────────────────────────────────────────────────────
def daily_streak(
    dates: set, today: date, skips: set = frozenset(), slips: set = frozenset()
) -> int:
    """consecutive done-days ending today (with a grace day so an as-yet-undone today
    doesn't zero a real run). a planned skip day carries the run over without counting;
    a slip today ends it."""
    if today.isoformat() in slips:
        return 0
    s = 0
    d = today
    if today.isoformat() not in dates:
        d = today - timedelta(days=1)
    while d.isoformat() in dates or d.isoformat() in skips:
        s += d.isoformat() in dates
        d -= timedelta(days=1)
    return s


def best_streak(dates: set, skips: set = frozenset()) -> int:
    """the longest run ever. a slip ends the current run but never this record."""
    best = run = 0
    last = None
    for day in sorted(dates | skips):
        current = _d(day)
        if last is None or (current - last).days != 1:
            run = 0
        run += day in dates
        best = max(best, run)
        last = current
    return best


def recent_count(dates: set, today: date, days: int = 30) -> int:
    """done days in the last `days` days, today included ("27 of the last 30")."""
    start = today - timedelta(days=days - 1)
    return sum(1 for s in dates if start <= _d(s) <= today)


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
LOG_DAYS = 14  # details sent for the last two weeks; the week strip opens any of them


class Days:
    """one habit's stored days: done (counts), skip (planned, bridges a streak), slip (a quit
    habit's slip: recorded, never clean) and each day's details."""

    def __init__(self, rows=()):
        self.done, self.skips, self.slips, self.logs = set(), set(), set(), {}
        for raw_day, raw_data in rows:
            try:
                day = habit_logs.canonical_day(raw_day)
            except ValueError:
                continue  # an invalid old row stays stored but never counts
            data = habit_kinds.load(raw_data)
            state = habit_kinds.day_state(data) if data is not None else "done"
            {"done": self.done, "skip": self.skips, "slip": self.slips}[state].add(day)
            if data is not None:
                self.logs[day] = data


def _history(db, hid) -> Days:
    return Days(db.query(HabitLog.date, HabitLog.data).filter(HabitLog.habit_id == hid).all())


def _fmt(h: Habit, days: Days | None = None, today: date | None = None, log_day: str = "") -> dict:
    today = today or date.today()
    days = days or Days()
    dates, logs = days.done, days.logs
    kind = h.kind or "check"
    first = (today - timedelta(days=LOG_DAYS - 1)).isoformat()
    # an older day the screen paged back to comes along with the last two weeks
    recent = {d: v for d, v in logs.items() if first <= d <= today.isoformat() or d == log_day}
    return {
        "id": h.id,
        "name": h.name,
        "icon": h.icon,
        "color": h.color,
        "cadence": h.cadence,
        "target": h.target,
        "archived": h.archived,
        "kind": kind,
        "unit": h.unit or "",
        "fields": habit_kinds.load_fields(h.fields),
        "streak": daily_streak(dates, today, days.skips, days.slips),
        "best_streak": best_streak(dates, days.skips),
        "total_days": len(dates),
        "last_30": recent_count(dates, today),
        "week_done": week_done_count(dates, today),
        "pct": completion_pct(h.cadence, h.target, dates, today),
        "done_today": today.isoformat() in dates,
        "grid": build_grid(dates, today, 119),  # ~17 weeks
        # the old screens read v1 (logs); the v2 screens read every detail (days)
        "logs": {
            d: view
            for d, v in recent.items()
            if (view := habit_kinds.legacy_view(kind, v)) is not None
        },
        "days": {d: v for d, v in recent.items() if habit_kinds.is_v2(v)},
        "skips": sorted(d for d in days.skips if d >= first),
        "slips": sorted(d for d in days.slips if d >= first),
        "exercises": habit_kinds.exercise_names(logs.items()) if kind == "workout" else [],
    }


def _fmt_db(db, h: Habit) -> dict:
    return _fmt(h, _history(db, h.id))


# ── endpoints ──────────────────────────────────────────────────────────────────
@router.get("/habits/{hid}/risk")
def habit_risk(hid: str, window: int = 14, db: DbSession = Depends(get_db)):
    """4b - failure risk today from the recent completion pattern."""
    from services import life_stats

    if not db.get(Habit, hid):
        raise HTTPException(404, "habit not found")
    done = habit_logs.canonical_days(
        r.date for r in db.query(HabitLog).filter_by(habit_id=hid).all()
    )
    return life_stats.habit_failure_risk(done, date.today(), window=window)


@router.get("/habits/kinds")
def habit_kinds_list():
    """every habit type's fields, so the screens build each logger from one source."""
    return {"kinds": habit_kinds.kinds()}


@router.get("/habits/overview")
def overview(
    date_q: str = "",
    db: DbSession = Depends(get_db),
    archived: bool = False,
    log_day: str = "",
):
    from services import life_stats

    if log_day:
        try:
            log_day = _d(log_day).isoformat()
        except ValueError:
            raise HTTPException(400, "log_day must be ISO (YYYY-MM-DD)")
    if date_q:
        try:
            today = _d(date_q)  # same junk-date guard as toggle, else 500 on bad input
        except ValueError:
            raise HTTPException(400, "date_q must be ISO (YYYY-MM-DD)")
    else:
        today = date.today()
    habits = db.query(Habit).filter(Habit.archived == archived).order_by(Habit.created_at).all()
    # one query for all logs instead of one per habit (was H+1 round-trips on every overview load)
    by_habit: dict[str, list[tuple]] = {}
    if habits:
        for hid, d, data in (
            db.query(HabitLog.habit_id, HabitLog.date, HabitLog.data)
            .filter(HabitLog.habit_id.in_([h.id for h in habits]))
            .all()
        ):
            by_habit.setdefault(hid, []).append((d, data))
    out = []
    for h in habits:
        days = Days(by_habit.get(h.id, []))
        done = days.done
        card = _fmt(h, days, today, log_day)
        if card["kind"] in WEIGHT_KINDS:
            card["body_weight"] = habit_logs.body_weight(db, today.isoformat())
        risk = life_stats.habit_failure_risk(done, today)
        # only nudge once there's enough history to judge (>= a week old) and you've actually
        # let it slide (low recent rate + no current streak) - never flag a brand-new habit
        age = (today - local_date(h.created_at)).days if h.created_at else 999
        risk["slipping"] = bool(age >= 7 and risk["recent_rate"] < 0.4 and card["streak"] == 0)
        card["risk"] = risk
        out.append(card)
    return {"habits": out}


class HabitBody(BaseModel):
    name: str
    icon: str = ""
    color: str = ""
    cadence: str = "daily"
    target: int = 1
    kind: str = "check"
    unit: str = ""
    fields: dict | None = None
    request_id: str = ""


def _create_identity(value: str) -> str:
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise HTTPException(400, "request_id must be a canonical UUID")


def _find_receipt(db, identity):
    return (
        db.query(HabitCreateReceipt, Habit)
        .outerjoin(Habit, Habit.id == HabitCreateReceipt.habit_id)
        .filter(HabitCreateReceipt.id == identity)
        .populate_existing()
        .first()
    )


def _receipt_habit(found):
    if found is None:
        raise HTTPException(404, "saved habit not found")
    if found[1] is None:
        raise HTTPException(410, "the saved habit was deleted; close this draft to start another")
    return found[1]


@router.get("/habits/requests/{request_id}")
def recover_habit(request_id: str, db: DbSession = Depends(get_db)):
    habit = _receipt_habit(_find_receipt(db, _create_identity(request_id)))
    return _fmt_db(db, habit)


@router.post("/habits")
def create_habit(body: HabitBody, db: DbSession = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(400, "name required")
    if body.cadence not in CADENCES:
        raise HTTPException(400, f"cadence must be one of {', '.join(CADENCES)}")
    try:
        kind, unit = habit_kinds.check_kind(body.kind), habit_kinds.check_unit(body.unit)
        fields = habit_kinds.dump(habit_kinds.check_fields(kind, body.fields))
    except habit_kinds.HabitLogError as error:
        raise HTTPException(400, str(error)) from None
    values = {
        "name": body.name.strip(),
        "icon": body.icon.strip(),
        "color": body.color.strip(),
        "cadence": body.cadence,
        "target": max(1, body.target),
        "kind": kind,
        "unit": unit,
        "fields": fields,
    }
    receipt = None
    if body.request_id:
        identity = _create_identity(body.request_id)

        def replay(found):
            h = _receipt_habit(found)
            if h.archived or any(getattr(h, key) != value for key, value in values.items()):
                raise HTTPException(
                    409, "this request already saved a habit; open it to review changes"
                )
            return _fmt_db(db, h)

        found = _find_receipt(db, identity)
        if found is not None:
            return replay(found)
        receipt = HabitCreateReceipt(id=identity)
        db.add(receipt)
        try:
            # Reserve the unique identity before creating either of two competing habits.
            db.flush()
        except IntegrityError:
            db.rollback()
            found = _find_receipt(db, identity)
            if found is None:
                raise
            return replay(found)
    h = Habit(**values)
    db.add(h)
    if receipt is not None:
        db.flush()
        receipt.habit_id = h.id
    db.commit()
    if receipt is not None:
        return recover_habit(identity, db)
    db.refresh(h)
    return _fmt(h)


class HabitPatch(BaseModel):
    name: str | None = None
    icon: str | None = None
    color: str | None = None
    cadence: str | None = None
    target: int | None = None
    archived: bool | None = None
    kind: str | None = None
    unit: str | None = None
    fields: dict | None = None


def _rekind(db, h: Habit, kind: str, fields) -> list:
    """every stored log, checked again under the new kind. one that doesn't fit refuses the
    change, so a kind change never loses a logged detail."""
    out = []
    for log in db.query(HabitLog).filter(HabitLog.habit_id == h.id).all():
        data = habit_kinds.load(log.data)
        if data is None:
            continue
        if not habit_kinds.is_v2(data):
            data = habit_kinds.clean_log(h.kind or "check", data)
        out.append((log, habit_kinds.dump(habit_kinds.clean_log(kind, data, fields))))
    return out


@router.patch("/habits/{hid}")
def update_habit(hid: str, body: HabitPatch, db: DbSession = Depends(get_db)):
    h = db.get(Habit, hid)
    if not h:
        raise HTTPException(404)
    if body.cadence is not None and body.cadence not in CADENCES:
        raise HTTPException(400, f"cadence must be one of {', '.join(CADENCES)}")
    kind = h.kind or "check"
    try:
        if body.kind is not None:
            kind = habit_kinds.check_kind(body.kind)
        if body.unit is not None:
            h.unit = habit_kinds.check_unit(body.unit)
        fields = habit_kinds.load_fields(h.fields)
        if body.fields is not None:
            fields = habit_kinds.check_fields(kind, body.fields)
        elif kind != (h.kind or "check"):
            fields = habit_kinds.check_fields(kind, fields)
    except habit_kinds.HabitLogError as error:
        raise HTTPException(400, str(error)) from None
    if kind != (h.kind or "check"):
        try:
            changed = _rekind(db, h, kind, fields)
        except habit_kinds.HabitLogError:
            raise HTTPException(409, "some logs don't fit the new habit type") from None
        for log, data in changed:
            log.data = data
    h.kind = kind
    h.fields = habit_kinds.dump(fields)
    for f in ("name", "icon", "color", "cadence", "target", "archived"):
        v = getattr(body, f)
        if v is not None:
            if isinstance(v, str) and f in ("name", "icon", "color"):
                v = v.strip()
            if (
                f == "target"
            ):  # clamp like create_habit, or a 0/negative target renders "3/0 this week"
                v = max(1, int(v))
            setattr(h, f, v)
    db.commit()
    return _fmt_db(db, h)


@router.delete("/habits/{hid}")
def delete_habit(hid: str, db: DbSession = Depends(get_db)):
    h = db.get(Habit, hid)
    if not h:
        raise HTTPException(404)
    db.query(HabitLog).filter(HabitLog.habit_id == hid).delete(synchronize_session=False)
    db.query(HabitCreateReceipt).filter_by(habit_id=hid).update(
        {"habit_id": None}, synchronize_session=False
    )
    db.delete(h)
    db.commit()
    return {"ok": True}


class ToggleBody(BaseModel):
    date: str = ""
    done: bool | None = None
    data: dict | None = None  # the day's details; sending them marks the day done


@router.post("/habits/{hid}/toggle")
def toggle(hid: str, body: ToggleBody, db: DbSession = Depends(get_db)):
    h = db.get(Habit, hid)
    if not h:
        raise HTTPException(404)
    raw_date = body.date or date.today().isoformat()
    try:
        day = habit_logs.canonical_day(raw_date)
    except ValueError:
        raise HTTPException(400, "date must be ISO (YYYY-MM-DD)")
    if body.data is not None:
        kind = h.kind or "check"
        try:
            data = habit_kinds.clean_log(kind, body.data, habit_kinds.load_fields(h.fields))
        except habit_kinds.HabitLogError as error:
            raise HTTPException(400, str(error)) from None
        if not habit_kinds.is_v2(body.data):
            data = habit_kinds.merge_v1(kind, habit_logs.stored(db, hid, day), data)
        day = habit_logs.save_log(db, hid, day, habit_kinds.dump(data))
        return {"done": True, "date": day, "data": data}
    done, day = habit_logs.toggle(db, hid, day, done=body.done)
    return {"done": done, "date": day}


@router.get("/habits/{hid}/exercise")
def exercise_history(
    hid: str, name: str, setup: str = "", date_q: str = "", db: DbSession = Depends(get_db)
):
    """one exercise's last time, records and next step hint, matched by exact name and setup
    (setup is json, for example {"basis": "per_side", "grip": "overhand"})."""
    import json

    h = db.get(Habit, hid)
    if not h:
        raise HTTPException(404)
    try:
        today = _d(date_q).isoformat() if date_q else date.today().isoformat()
        wanted = json.loads(setup) if setup else {}
    except ValueError:
        raise HTTPException(400, "date_q must be ISO and setup json") from None
    if not isinstance(wanted, dict):
        raise HTTPException(400, "date_q must be ISO and setup json")
    logs = Days(db.query(HabitLog.date, HabitLog.data).filter(HabitLog.habit_id == hid).all())
    return habit_logs.exercise_history(
        logs.logs.items(), name, wanted, today, habit_kinds.load_fields(h.fields)
    )


# ── workout log import (preview, apply, undo) ──────────────────────────────────
class ImportBody(BaseModel):
    text: str = ""
    year: int | None = None  # the owner's answer for sessions whose heading has no year


def _workout_habit(db, hid) -> Habit:
    h = db.get(Habit, hid)
    if not h:
        raise HTTPException(404)
    if (h.kind or "check") != "workout":
        raise HTTPException(400, "a workout log imports into a workout habit")
    return h


def _parsed(text):
    from services import workout_import

    try:
        return workout_import.parse(text)
    except workout_import.WorkoutImportError as error:
        raise HTTPException(400, str(error)) from None


def _ids_on(db, hid, day) -> set:
    data = habit_logs.stored(db, hid, day)
    return {e.get("id") for e in (data or {}).get("entries") or []} if data else set()


@router.post("/habits/{hid}/import/preview")
def import_preview(hid: str, body: ImportBody, db: DbSession = Depends(get_db)):
    """every session the import would write, nothing saved. sessions with no year in their
    heading wait for the owner to pick one; sessions already imported are marked."""
    _workout_habit(db, hid)
    parsed = _parsed(body.text)
    for session in parsed["sessions"]:
        day = session["date"]
        if day is None and body.year:
            day = f"{body.year:04d}-{session['month']:02d}-{session['day']:02d}"
        session["already"] = bool(day) and session["key"] in _ids_on(db, hid, day)
    return {
        "sessions": parsed["sessions"],
        "problems": parsed["problems"],
        "needs_year": any(s["needs_year"] for s in parsed["sessions"]),
        "sets": sum(len(e["sets"]) for s in parsed["sessions"] for e in s["exercises"]),
    }


@router.post("/habits/{hid}/import")
def import_apply(hid: str, body: ImportBody, db: DbSession = Depends(get_db)):
    """write every session as one entry on its day. checked in full before anything is saved;
    a session already imported is skipped. undo removes exactly what this wrote."""
    from services import workout_import

    h = _workout_habit(db, hid)
    fields = habit_kinds.load_fields(h.fields)
    batch = workout_import.new_batch()
    plan, skipped = {}, 0
    try:
        for session in _parsed(body.text)["sessions"]:
            day = workout_import.session_date(session, body.year)
            if day not in plan:
                stored = habit_logs.stored(db, hid, day)
                exists = habit_logs.is_done(db, hid, day)
                if stored is not None and not habit_kinds.is_v2(stored):
                    stored = habit_kinds.clean_log("workout", stored)
                doc = stored or {"v": 2, "entries": []}
                if not exists:
                    doc["created_by"] = batch
                plan[day] = doc
            doc = plan[day]
            if session["key"] in {e.get("id") for e in doc["entries"]}:
                skipped += 1
                continue
            doc["entries"].append(workout_import.entry(session, batch))
        cleaned = {day: habit_kinds.clean_log("workout", doc, fields) for day, doc in plan.items()}
    except workout_import.WorkoutImportError as error:
        raise HTTPException(400, str(error)) from None
    except habit_kinds.HabitLogError as error:
        raise HTTPException(
            400, f"this workout log has a session that doesn't fit: {error}"
        ) from None
    written = 0
    for day, doc in cleaned.items():
        if doc and any(e.get("import") == batch for e in doc["entries"]):
            habit_logs.save_log(db, hid, day, habit_kinds.dump(doc))
            written += sum(e.get("import") == batch for e in doc["entries"])
    return {"batch": batch, "sessions": written, "skipped": skipped}


@router.post("/habits/{hid}/import/{batch}/undo")
def import_undo(hid: str, batch: str, db: DbSession = Depends(get_db)):
    """take back one import: its entries go, a day it created goes, every other detail stays."""
    _workout_habit(db, hid)
    removed = 0
    for log in db.query(HabitLog).filter(HabitLog.habit_id == hid).all():
        data = habit_kinds.load(log.data)
        if not habit_kinds.is_v2(data):
            continue
        keep = [e for e in data["entries"] if e.get("import") != batch]
        if len(keep) == len(data["entries"]):
            continue
        removed += len(data["entries"]) - len(keep)
        if keep:
            log.data = habit_kinds.dump({**data, "entries": keep})
        elif data.get("created_by") == batch:
            db.delete(log)
        else:
            log.data = None
    db.commit()
    return {"removed": removed}
