"""Date rules shared by Day Event views, signals, and automations."""

import calendar
from datetime import date


def parse_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def _clamp(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_occurrence(original: date, today: date, repeat: str) -> tuple[date, int]:
    """Return the next repeat on/after today; one-shot dates keep their original date."""
    if original > today:
        return original, 0
    if repeat == "yearly":
        occurrence = _clamp(today.year, original.month, original.day)
        if occurrence < today:
            occurrence = _clamp(today.year + 1, original.month, original.day)
        return occurrence, occurrence.year - original.year
    if repeat == "monthly":
        occurrence = _clamp(today.year, today.month, original.day)
        if occurrence < today:
            year, month = (
                (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            )
            occurrence = _clamp(year, month, original.day)
        return occurrence, (occurrence.year - original.year) * 12 + (
            occurrence.month - original.month
        )
    return original, 0


def previous_occurrence(original: date, occurrence: date, repeat: str) -> date:
    if repeat == "yearly":
        return _clamp(occurrence.year - 1, original.month, original.day)
    if repeat == "monthly":
        year, month = (
            (occurrence.year - 1, 12)
            if occurrence.month == 1
            else (occurrence.year, occurrence.month - 1)
        )
        return _clamp(year, month, original.day)
    return original
