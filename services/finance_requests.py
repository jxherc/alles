"""Durable acknowledgments for local Finance creates; never commit separately from the ledger."""

import hashlib
import json
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from core.database import FinanceCreateReceipt


def begin(db, operation: str, request_id: str, payload: dict):
    """Reserve a request in the caller's transaction, or return its committed response.

    Flushing the unique receipt before the ledger write serializes matching requests
    across database connections/processes, including ones beyond the API's local lock.
    A rollback removes both the reservation and the ledger change.
    """
    if not request_id:
        return None, None
    try:
        identity = str(uuid.UUID(request_id))
        if request_id.lower() != identity:
            raise ValueError
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            400, "request_id must be a canonical UUID and values must be finite"
        ) from exc
    key = f"{operation}:{identity}"
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()

    def replay(receipt):
        if receipt.payload_hash != fingerprint:
            raise HTTPException(409, "this request_id was already used with different values")
        if not receipt.response_json:
            # A correctly committed receipt always has a response; do not risk another write.
            raise HTTPException(409, "this create request has no recoverable acknowledgment")
        response = json.loads(receipt.response_json)
        if response is None:
            raise HTTPException(410, "the entry created by this request was deleted")
        return None, response

    existing = db.get(FinanceCreateReceipt, key)
    if existing:
        return replay(existing)
    receipt = FinanceCreateReceipt(id=key, payload_hash=fingerprint)
    db.add(receipt)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.get(FinanceCreateReceipt, key)
        if not existing:
            raise
        return replay(existing)
    return receipt, None


def finish(receipt, response: dict):
    if receipt is not None:
        receipt.resource_id = response.get("id") or response["transfer_id"]
        receipt.response_json = json.dumps(response, separators=(",", ":"), allow_nan=False)
    return response


def forget(db, resource_ids):
    """Remove deleted content, retaining a tombstone to prevent delayed retry resurrection."""
    identities = set(resource_ids) - {"", None}
    if identities:
        db.query(FinanceCreateReceipt).filter(
            FinanceCreateReceipt.resource_id.in_(identities)
        ).update({FinanceCreateReceipt.response_json: "null"}, synchronize_session=False)
