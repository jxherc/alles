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


def toggle(db: Session, habit_id: str, raw_date: str) -> tuple[bool, str]:
    day = canonical_day(raw_date)
    matches = _rows_on_day(db, habit_id, day)
    if matches:
        for row in matches:
            db.delete(row)
        db.commit()
        return False, day
    db.add(HabitLog(habit_id=habit_id, date=day))
    db.commit()
    return True, day


def mark(db: Session, habit_id: str, raw_date: str) -> bool:
    day = canonical_day(raw_date)
    if _rows_on_day(db, habit_id, day):
        return False
    db.add(HabitLog(habit_id=habit_id, date=day))
    db.commit()
    return True
