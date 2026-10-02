"""Atomic Health CSV imports and replayable batch acknowledgments."""

import hashlib
import json
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError

from services.health_entries import HealthInputError, canonical_request_id
from services.imports import iter_health_csv


def _import_date(raw):
    if not raw:
        return date.today().isoformat()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        # A timestamp keeps its written calendar day, after validating its entire value.
        if len(raw) > 10 and raw[10] in {"T", " "}:
            return datetime.fromisoformat(raw).date().isoformat()
        raise


def import_entries(db, text: str, *, kinds, request_id: str = "", strict: bool = False):
    from core.database import HealthEntry, HealthImportReceipt

    identity = canonical_request_id(request_id) if request_id else ""
    digest = hashlib.sha256(
        json.dumps({"text": text, "strict": strict}, ensure_ascii=False).encode()
    ).hexdigest()

    def replay(receipt):
        if receipt.payload_hash != digest:
            raise HealthInputError("this import was already applied with different contents", 409)
        return {"imported": receipt.imported, "skipped": receipt.skipped, "replayed": True}

    if identity:
        existing = db.get(HealthImportReceipt, identity)
        if existing is not None:
            return replay(existing)

    entries, skipped = [], 0
    for line, row in iter_health_csv(text, strict=strict):
        if row is None:
            if strict:
                raise HealthInputError(
                    f"line {line} needs a finite numeric value; nothing imported"
                )
            skipped += 1
            continue
        try:
            day = _import_date(row["date"])
        except ValueError:
            raise HealthInputError(
                f"line {line} needs a valid date (YYYY-MM-DD); nothing imported"
            ) from None
        kind, label = row["kind"], ""
        if kind not in kinds:
            kind, label = "custom", kind
        entries.append(
            HealthEntry(kind=kind, label=label, value=row["value"], unit=row["unit"], date=day)
        )
    if strict and not entries:
        raise HealthInputError("no entries found; use date, kind, value and unit columns")
    if identity:
        receipt = HealthImportReceipt(
            id=identity, payload_hash=digest, imported=len(entries), skipped=skipped
        )
        db.add(receipt)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = db.get(HealthImportReceipt, identity)
            if existing is None:
                raise
            return replay(existing)
    db.add_all(entries)
    db.commit()
    return {"imported": len(entries), "skipped": skipped, "replayed": False}
