"""One calendar-day identity for habit logs across the API and Aide."""

from datetime import date

from sqlalchemy.orm import Session

from core.database import HabitLog


def canonical_day(raw: str) -> str:
    return date.fromisoformat(str(raw)[:10]).isoformat()


def canonical_days(raw_dates) -> set[str]:
    days = set()
    for raw in raw_dates:
        try:
            days.add(canonical_day(raw))
        except ValueError:
            continue  # keep an invalid old row stored, but don't count it as a day
    return days


def _rows_on_day(db: Session, habit_id: str, day: str) -> list[HabitLog]:
    matches = []
    for row in db.query(HabitLog).filter(HabitLog.habit_id == habit_id).all():
        try:
            if canonical_day(row.date) == day:
                matches.append(row)
        except ValueError:
            continue
    return matches


def is_done(db: Session, habit_id: str, raw_date: str) -> bool:
    return bool(_rows_on_day(db, habit_id, canonical_day(raw_date)))


def toggle(
    db: Session, habit_id: str, raw_date: str, *, done: bool | None = None
) -> tuple[bool, str]:
    day = canonical_day(raw_date)
    matches = _rows_on_day(db, habit_id, day)
    if done is not None and bool(matches) == done:
        return done, day
    if matches:
        for row in matches:
            db.delete(row)
        db.commit()
        return False, day
    db.add(HabitLog(habit_id=habit_id, date=day))
    db.commit()
    return True, day


def body_weight(db: Session, day: str):
    """the body weight logged in health on or before the day, for bodyweight and assisted
    movements: {date, value, unit} as entered, or None."""
    from core.database import HealthEntry

    entry = (
        db.query(HealthEntry)
        .filter(HealthEntry.kind == "weight", HealthEntry.date <= day)
        .order_by(HealthEntry.date.desc(), HealthEntry.id.desc())
        .first()
    )
    return {"date": entry.date, "value": entry.value, "unit": entry.unit} if entry else None


def stored(db: Session, habit_id: str, raw_date: str):
    """the day's stored details as json data, or None."""
    from services.habit_kinds import load

    matches = _rows_on_day(db, habit_id, canonical_day(raw_date))
    return load(matches[0].data) if matches else None


def save_log(db: Session, habit_id: str, raw_date: str, data: str | None) -> str:
    """mark the day done and store its details (json text, or None for none). one row stays."""
    day = canonical_day(raw_date)
    matches = _rows_on_day(db, habit_id, day)
    for extra in matches[1:]:
        db.delete(extra)
    if matches:
        matches[0].data = data
    else:
        db.add(HabitLog(habit_id=habit_id, date=day, data=data))
    db.commit()
    return day


def mark(db: Session, habit_id: str, raw_date: str) -> bool:
    day = canonical_day(raw_date)
    if _rows_on_day(db, habit_id, day):
        return False
    db.add(HabitLog(habit_id=habit_id, date=day))
    db.commit()
    return True


# ── one exercise's history: last time, records and the next step hint ──────────
HINT_DAYS = 8  # "the same setup within about a week" (the owner's rule)
STEP = {"lb": 5, "kg": 2.5}
_DONE = (None, "done")


def _same_exercise(exercise, name, setup) -> bool:
    """history matches the exact name and setup, never a similar movement."""
    own = {k: v for k, v in (exercise.get("setup") or {}).items() if v}
    return str(exercise.get("name") or "").strip().lower() == name and own == setup


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _lb(value, unit):
    from services import units

    try:
        return units.change(value, unit or "lb", "lb")
    except units.UnitError:
        return None


def _counts(one, warmups) -> bool:
    if one.get("status") not in _DONE:
        return False
    return warmups or one.get("type") != "warmup"


def _sets_by_day(logs, name, setup):
    from services.habit_kinds import is_v2

    days = []
    for day, data in logs:
        if not is_v2(data):
            continue
        sets = []
        for entry in data.get("entries") or []:
            for exercise in (entry.get("values") or {}).get("exercises") or []:
                if _same_exercise(exercise, name, setup):
                    sets += exercise.get("sets") or []
        if sets:
            days.append((day, sets))
    return sorted(days, key=lambda item: item[0])


def _records(days, warmups) -> dict:
    records = {}
    for day, sets in days:
        volume = {}
        for one in sets:
            weight, reps = _num(one.get("weight")), _num(one.get("reps"))
            if weight is None or reps is None or not _counts(one, warmups):
                continue
            unit = one.get("unit") or "lb"
            pounds = _lb(weight, unit)
            if pounds is None:
                continue
            side = one.get("side") or ""
            mine = records.setdefault(side, {"reps_at": {}})
            mark_ = {"weight": weight, "unit": unit, "reps": reps, "date": day}
            if "heaviest" not in mine or pounds > mine["heaviest"]["lb"]:
                mine["heaviest"] = {**mark_, "lb": pounds}
            e1rm = pounds * (1 + reps / 30)
            if reps > 0 and ("e1rm" not in mine or e1rm > mine["e1rm"]["lb"]):
                mine["e1rm"] = {**mark_, "lb": e1rm, "value": round(weight * (1 + reps / 30), 1)}
            key = f"{weight:g} {unit}"
            if reps > mine["reps_at"].get(key, {}).get("reps", -1):
                mine["reps_at"][key] = mark_
            volume[side] = volume.get(side, 0) + pounds * reps * (one.get("count") or 1)
        for side, total in volume.items():
            if "volume" not in records[side] or total > records[side]["volume"]["lb"]:
                records[side]["volume"] = {"lb": round(total, 1), "date": day}
    for mine in records.values():
        mine["reps_at"] = sorted(
            mine["reps_at"].values(), key=lambda r: -(_lb(r["weight"], r["unit"]) or 0)
        )
        for key in ("heaviest", "e1rm"):
            mine.get(key, {}).pop("lb", None)
    return records


def _hint(last, today, config):
    if not last or (date.fromisoformat(today) - date.fromisoformat(last["date"])).days > HINT_DAYS:
        return None
    work = [one for one in last["sets"] if one.get("type") != "warmup"]
    whole = all(
        one.get("status") in _DONE
        and _num(one.get("weight")) is not None
        and _num(one.get("reps")) is not None
        and not one.get("bad")
        for one in work
    )
    if not work or not whole:
        return None
    hint = []
    for side in dict.fromkeys(one.get("side") or "" for one in work):
        mine = [one for one in work if (one.get("side") or "") == side]
        top = max(mine, key=lambda one: _lb(one["weight"], one.get("unit") or "lb") or 0)
        unit = top.get("unit") or "lb"
        step = config.get("weight_step") or STEP.get(unit, 5)
        hint.append(
            {"side": side, "from": top["weight"], "to": top["weight"] + step, "unit": unit,
             "reps": top["reps"]}
        )  # fmt: skip
    return hint


def exercise_history(logs, name, setup=None, today=None, config=None) -> dict:
    """{last, records, hint} for one exercise from a workout habit's day logs ((day, data) pairs).

    last: the newest day before today with that exact name and setup, and its sets.
    records per side ("" both, "L", "R"), from days up to and including today (a past day
    never counts a later session): heaviest, best estimated 1rm (epley), most reps at
    each weight, and the best session volume (in lb). only done sets count; warm ups only when
    the habit says so (warmups_count). weights stay in the unit they were entered in.
    hint: one tier up per side (weight_step, else 5 lb or 2.5 kg), when the last time was within
    about a week and every rep was done (all done, none bad, nothing unknown). a hint only.
    """
    config = config or {}
    name = str(name or "").strip().lower()
    setup = {k: v for k, v in (setup or {}).items() if v}
    today = today or date.today().isoformat()
    days = _sets_by_day(logs, name, setup)
    before = [item for item in days if item[0] < today]
    last = {"date": before[-1][0], "sets": before[-1][1]} if before else None
    return {
        "last": last,
        "records": _records(
            [item for item in days if item[0] <= today], bool(config.get("warmups_count"))
        ),
        "hint": _hint(last, today, config),
    }
