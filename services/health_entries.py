"""Ordinary Health saves and the finite measurement rule shared with CSV import."""

import hashlib
import json
import math
import uuid
from datetime import date

from sqlalchemy.exc import IntegrityError


class HealthInputError(ValueError):
    """A health value or date cannot be saved."""

    def __init__(self, message, status_code=400, entry_id=None):
        super().__init__(message)
        self.status_code = status_code
        self.entry_id = entry_id


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


def canonical_date(raw: str) -> str:
    try:
        return date.fromisoformat(str(raw)[:10]).isoformat()
    except ValueError:
        raise HealthInputError("date must be ISO (YYYY-MM-DD)") from None


def canonical_request_id(raw: str) -> str:
    try:
        identity = str(uuid.UUID(raw))
        if raw.lower() != identity:
            raise ValueError
        return identity
    except (ValueError, TypeError, AttributeError):
        raise HealthInputError("request_id must be a canonical UUID") from None


def _find_receipt(db, identity):
    from core.database import HealthCreateReceipt, HealthEntry

    # One statement prevents a deletion and integer-ID reuse between these two reads.
    return (
        db.query(HealthCreateReceipt, HealthEntry)
        .outerjoin(HealthEntry, HealthEntry.id == HealthCreateReceipt.entry_id)
        .filter(HealthCreateReceipt.id == identity)
        .populate_existing()
        .one_or_none()
    )


def recover_entry(db, request_id: str):
    found = _find_receipt(db, canonical_request_id(request_id))
    if found is None:
        raise HealthInputError("this save could not be found", 404)
    if found[1] is None:
        raise HealthInputError("the entry from this save was deleted", 410)
    return found[1]


def save_entry(
    db,
    *,
    kind: str,
    value,
    unit: str = "",
    note: str = "",
    label: str = "",
    entry_date: str = "",
    request_id: str = "",
):
    from core.database import HealthCreateReceipt, HealthEntry

    value = finite_value(value)
    day = canonical_date(entry_date or date.today().isoformat())
    fields = dict(kind=kind, value=value, unit=unit.strip(), note=note.strip(), label=label.strip())
    receipt = None
    if request_id:
        identity = canonical_request_id(request_id)
        # An omitted date means today on the first attempt, even if its retry arrives tomorrow.
        payload = {**fields, "date": day if entry_date else ""}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()

        def replay(found):
            existing, entry = found
            if entry is None:
                raise HealthInputError("the entry from this save was deleted", 410)
            if existing.payload_hash != digest:
                raise HealthInputError(
                    "this entry was already saved with different values; open it to make a correction",
                    409,
                    entry.id,
                )
            return entry

        existing = _find_receipt(db, identity)
        if existing:
            return replay(existing)
        receipt = HealthCreateReceipt(id=identity, payload_hash=digest)
        db.add(receipt)
        try:
            # The unique receipt serializes retries before either connection can insert a reading.
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = _find_receipt(db, identity)
            if not existing:
                raise
            return replay(existing)
    entry = HealthEntry(
        date=day,
        **fields,
    )
    db.add(entry)
    if receipt is not None:
        db.flush()
        receipt.entry_id = entry.id
    db.commit()
    if receipt is not None:
        return recover_entry(db, identity)
    db.refresh(entry)
    return entry
