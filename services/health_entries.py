"""Ordinary Health saves and the finite measurement rule shared with CSV import."""

import math
from datetime import date


class HealthInputError(ValueError):
    """A health value or date cannot be saved."""


def finite_value(raw) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise HealthInputError("value must be a number") from None
    except OverflowError:
        raise HealthInputError("value must be a finite number") from None
    if not math.isfinite(value):
        raise HealthInputError("value must be a finite number")
    return value


def save_entry(
    db,
    *,
    kind: str,
    value,
    unit: str = "",
    note: str = "",
    label: str = "",
    entry_date: str = "",
):
    from core.database import HealthEntry

    value = finite_value(value)
    day = (entry_date or date.today().isoformat())[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HealthInputError("date must be ISO (YYYY-MM-DD)") from None
    entry = HealthEntry(
        kind=kind,
        date=day,
        value=value,
        unit=unit.strip(),
        note=note.strip(),
        label=label.strip(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
