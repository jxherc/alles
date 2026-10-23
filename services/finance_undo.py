"""Reverse an unchanged local transaction using its durable creation acknowledgment."""

import hashlib
import json
import uuid
from datetime import date, datetime

from fastapi import HTTPException

from core.database import FinanceCreateReceipt, MoneyFxEvidence, Transaction, TxnSplit
from services import finance_requests


def _row_values(row):
    return {
        column.name: value.isoformat() if isinstance(value, (date, datetime)) else value
        for column in row.__table__.columns
        for value in [getattr(row, column.name)]
    }


def _fingerprint(db, transaction):
    proof = db.query(MoneyFxEvidence).filter_by(transaction_id=transaction.id).all()
    values = {
        "transaction": _row_values(transaction),
        "fx": [_row_values(row) for row in sorted(proof, key=lambda row: row.id)],
    }
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def acknowledgment(db, transaction, request_id):
    db.flush()  # Include assigned IDs, timestamps and the exact stored FX evidence.
    return {"request_id": request_id, "snapshot": _fingerprint(db, transaction)}


def _request_key(request_id):
    try:
        identity = str(uuid.UUID(request_id))
        if request_id.lower() != identity:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400, "undo requires the original save request") from exc
    return f"transaction:{identity}", identity


def saved_result(db, transaction_id, request_id):
    key, _ = _request_key(request_id)
    receipt = db.get(FinanceCreateReceipt, key)
    if not receipt or receipt.resource_id != transaction_id:
        raise HTTPException(409, "this transaction has no matching saved undo")
    response = json.loads(receipt.response_json or "{}")
    if response is None:
        if db.get(Transaction, transaction_id):
            raise HTTPException(409, "this transaction no longer matches its saved undo")
        return {"id": transaction_id, "removed": True}
    return response


def reverse(db, transaction_id, request_id):
    key, identity = _request_key(request_id)
    # SQLite holds this write reservation through compare/delete/commit, across
    # connections and processes. An in-process authority lock alone is insufficient.
    claimed = (
        db.query(FinanceCreateReceipt)
        .filter_by(id=key, resource_id=transaction_id)
        .update(
            {FinanceCreateReceipt.payload_hash: FinanceCreateReceipt.payload_hash},
            synchronize_session=False,
        )
    )
    if not claimed:
        raise HTTPException(409, "this transaction has no matching saved undo")
    db.expire_all()
    receipt = db.get(FinanceCreateReceipt, key)
    transaction = db.get(Transaction, transaction_id)
    if receipt.response_json == "null":
        if transaction:
            raise HTTPException(409, "this transaction no longer matches its saved undo")
        db.commit()
        return {"ok": True, "outcome": "already_removed"}
    response = json.loads(receipt.response_json or "{}")
    undo = response.get("undo", {})
    if (
        not transaction
        or response.get("id") != transaction_id
        or undo.get("request_id") != identity
    ):
        raise HTTPException(409, "this transaction has no protected saved undo")
    if transaction.transfer_id or db.query(TxnSplit).filter_by(txn_id=transaction_id).first():
        raise HTTPException(409, "this transaction changed since saving; review it before deleting")
    try:
        matches = undo.get("snapshot") == _fingerprint(db, transaction)
    except (ValueError, TypeError):
        matches = False
    if not matches:
        raise HTTPException(409, "this transaction changed since saving; review it before deleting")
    finance_requests.forget(db, [transaction_id])
    db.query(MoneyFxEvidence).filter_by(transaction_id=transaction_id).delete()
    db.delete(transaction)
    db.commit()
    return {"ok": True, "outcome": "undone"}
