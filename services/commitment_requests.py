"""Create receipts shared by Plan's task and calendar owners."""

import hashlib
import json
from contextlib import contextmanager
from uuid import UUID

from fastapi import HTTPException

from core.database import CalendarEvent, CommitmentCreateReceipt, Task


@contextmanager
def create_request(db, kind: str, request_id: str, payload: dict):
    if not request_id:
        yield None, None
        return
    try:
        identity = str(UUID(request_id))
        if request_id.lower() != identity:
            raise ValueError
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError):
        raise HTTPException(400, "use a canonical request_id and finite values") from None
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    try:
        # Acquire SQLite's write reservation before looking up the receipt or target.
        db.query(CommitmentCreateReceipt).filter_by(id=identity).update(
            {CommitmentCreateReceipt.id: CommitmentCreateReceipt.id}, synchronize_session=False
        )
        db.expire_all()
        receipt = db.get(CommitmentCreateReceipt, identity)
        if receipt:
            if receipt.kind != kind or receipt.payload_hash != fingerprint:
                raise HTTPException(409, "this request_id was already used with different values")
            model = Task if kind == "task" else CalendarEvent
            target = db.get(model, receipt.resource_id) if receipt.resource_id else None
            if target is None:
                raise HTTPException(410, "the accepted item was deleted; discard this retry")
            yield None, target
            return
        receipt = CommitmentCreateReceipt(id=identity, kind=kind, payload_hash=fingerprint)
        db.add(receipt)
        db.flush()
        yield receipt, None
    finally:
        # Do not leave replay/error reservations waiting for API dependency cleanup.
        db.rollback()
