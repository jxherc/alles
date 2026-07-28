"""Managed Actual lifecycle, evidence, migration, and cutover API."""

import tempfile
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import (
    Account,
    ActualMigrationRun,
    FinanceLedgerState,
    MoneyFxEvidence,
    SubPayment,
    Subscription,
    Transaction,
    get_db,
)
from services import actual_finance, actual_migration, finance_currency, managed_actual

router = APIRouter(prefix="/api/finance/actual")


class StageBody(BaseModel):
    base_currency_code: str = "CAD"


class RestoreBody(BaseModel):
    backup_id: str


class EvidenceBody(BaseModel):
    target_kind: Literal["account", "transaction", "subscription", "subscription_payment"]
    target_id: str
    original_currency_code: str = ""
    base_currency_code: str
    rate_text: str
    rate_date: str
    source: Literal["owner_reviewed", "statement_rate"] = "owner_reviewed"


def _api_error(exc: Exception):
    if isinstance(exc, managed_actual.ManagedActualRollback):
        return ApiError(409, "actual_operation_rolled_back", str(exc))
    if isinstance(exc, managed_actual.ManagedActualError):
        return ApiError(409, "actual_manage_failed", str(exc))
    return ApiError(409, "actual_migration_failed", str(exc))


@router.get("")
def actual_status(db: DbSession = Depends(get_db)):
    return {"service": managed_actual.status(), "ledger": actual_migration.state_payload(db)}


@router.get("/runs")
def migration_runs(db: DbSession = Depends(get_db)):
    rows = (
        db.query(ActualMigrationRun).order_by(ActualMigrationRun.created_at.desc()).limit(20).all()
    )
    return [actual_migration.run_payload(db, row) for row in rows]


@router.post("/service/restore", dependencies=[Depends(require_recent_owner)])
@actual_finance.authority_guarded
def restore_service(body: RestoreBody, db: DbSession = Depends(get_db)):
    state = db.get(FinanceLedgerState, "primary")

    def readback():
        if not state or not state.active_run_id or not state.actual_sync_id:
            return {"ok": True, "note": "no canonical budget is linked"}
        with tempfile.TemporaryDirectory(prefix="alles-actual-readback-") as fresh:
            actual = managed_actual.bridge_request(
                {
                    "command": "readback",
                    "sync_id": state.actual_sync_id,
                    "fresh_data_dir": str(Path(fresh).resolve()),
                },
                timeout=180,
            )
        return actual_migration.validate_active_links(db, actual)

    try:
        return managed_actual.restore(body.backup_id, verify_fn=readback)
    except (managed_actual.ManagedActualError, managed_actual.ManagedActualRollback) as exc:
        raise _api_error(exc) from exc


@router.post("/service/{action}", dependencies=[Depends(require_recent_owner)])
@actual_finance.authority_guarded
def manage_service(
    action: Literal["install", "start", "stop", "restart", "update", "rollback", "backup"],
    request: Request,
    db: DbSession = Depends(get_db),
):
    del request, db
    try:
        if action == "install":
            return managed_actual.install()
        if action in {"start", "stop", "restart"}:
            return managed_actual.control(action)
        if action == "update":
            return managed_actual.update()
        if action == "rollback":
            return managed_actual.rollback()
        return managed_actual.backup()
    except (managed_actual.ManagedActualError, managed_actual.ManagedActualRollback) as exc:
        raise _api_error(exc) from exc


@router.post("/stage", dependencies=[Depends(require_recent_owner)])
@actual_finance.authority_guarded
def stage_actual(body: StageBody, db: DbSession = Depends(get_db)):
    try:
        return actual_migration.stage(db, base_currency_code=body.base_currency_code)
    except (actual_migration.ActualMigrationError, managed_actual.ManagedActualError) as exc:
        raise _api_error(exc) from exc


@router.post("/cutover/{run_id}", dependencies=[Depends(require_recent_owner)])
@actual_finance.authority_guarded
def cutover_actual(run_id: str, db: DbSession = Depends(get_db)):
    try:
        return actual_migration.cutover(db, run_id)
    except (actual_migration.ActualMigrationError, managed_actual.ManagedActualError) as exc:
        raise _api_error(exc) from exc


@router.post("/rollback-ledger", dependencies=[Depends(require_recent_owner)])
@actual_finance.authority_guarded
def rollback_ledger(db: DbSession = Depends(get_db)):
    try:
        return actual_migration.rollback(db)
    except (actual_migration.ActualMigrationError, managed_actual.ManagedActualError) as exc:
        raise _api_error(exc) from exc


def _code(value: str) -> str:
    code = finance_currency.currency_code(value)
    if code == "XXX":
        raise ApiError(400, "invalid_currency", "base currency must be a reviewed currency code")
    return code


def _original_code(value: str, stored: str, target: str) -> str:
    raw = str(value or "").strip()
    code = finance_currency.currency_code(raw or stored)
    if code == "XXX":
        raise ApiError(
            409,
            f"{target}_currency_unknown",
            f"{target.replace('_', ' ')} original currency must be reviewed before conversion evidence can be added",
        )
    return code


def _rate(value: str) -> Decimal:
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ApiError(400, "invalid_rate", "rate must be an exact decimal") from exc
    if not rate.is_finite() or rate <= 0:
        raise ApiError(400, "invalid_rate", "rate must be greater than zero")
    if len(rate.as_tuple().digits) > 28 or not -18 <= rate.adjusted() <= 18:
        raise ApiError(400, "invalid_rate", "rate precision or exponent is out of range")
    return rate


def _converted(original: str, rate: Decimal) -> str:
    try:
        original_value = Decimal(original)
    except (InvalidOperation, ValueError) as exc:
        raise ApiError(409, "invalid_original_amount", "stored original amount is invalid") from exc
    if not original_value.is_finite():
        raise ApiError(409, "invalid_original_amount", "stored original amount is invalid")
    try:
        value = original_value * rate
        return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), "f")
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ApiError(
            400, "invalid_rate", "rate produces an amount outside the supported range"
        ) from exc


def _evidence_date(value: str, *, original_currency: str, base_currency: str) -> str:
    raw = str(value or "").strip()
    if not raw and original_currency == base_currency:
        return ""
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ApiError(
            400,
            "invalid_rate_date",
            "non-identity currency evidence requires a YYYY-MM-DD rate date",
        ) from exc


@router.post("/evidence", dependencies=[Depends(require_recent_owner)])
@actual_finance.authority_guarded
def set_currency_evidence(body: EvidenceBody, db: DbSession = Depends(get_db)):
    state = db.get(FinanceLedgerState, "primary")
    if state is None:
        state = FinanceLedgerState(id="primary", mode="alles", base_currency_code="CAD")
        db.add(state)
    if state and state.mode != "alles":
        raise ApiError(
            409, "legacy_ledger_read_only", "currency evidence is read-only after Actual cutover"
        )
    base = _code(body.base_currency_code)
    configured_base = _code(state.base_currency_code)
    if base != configured_base:
        raise ApiError(
            409,
            "base_currency_mismatch",
            f"currency evidence must use the configured ledger base {configured_base}",
        )
    rate = _rate(body.rate_text)
    source = f"{body.source}:half_even_2dp"
    if body.target_kind == "account":
        row = db.get(Account, body.target_id)
        if not row:
            raise ApiError(404, "finance_value_not_found", "account was not found")
        original_currency = _original_code(
            body.original_currency_code,
            row.currency_code,
            "account",
        )
        if original_currency == base and rate != 1:
            raise ApiError(400, "invalid_identity_rate", "same-currency evidence must use rate 1")
        rate_date = _evidence_date(
            body.rate_date, original_currency=original_currency, base_currency=base
        )
        row.currency_code = original_currency
        row.base_opening_text = _converted(row.original_opening_text, rate)
        row.base_currency_code = base
        row.opening_fx_rate_text = format(rate, "f")
        row.opening_fx_rate_date = rate_date
        row.opening_fx_source = source
        payload = {
            "original_currency_code": original_currency,
            "base_amount_text": row.base_opening_text,
            "base_currency_code": base,
            "rate_text": row.opening_fx_rate_text,
        }
    elif body.target_kind == "transaction":
        row = db.get(Transaction, body.target_id)
        proof = db.query(MoneyFxEvidence).filter_by(transaction_id=body.target_id).first()
        if not row:
            raise ApiError(404, "finance_value_not_found", "transaction was not found")
        original_currency = _original_code(
            body.original_currency_code,
            proof.original_currency_code if proof else row.original_currency_code,
            "transaction",
        )
        if not proof:
            original_amount = row.original_amount_text or finance_currency.decimal_text(row.amount)
            row.original_amount_text = original_amount
            proof = MoneyFxEvidence(
                id=f"fx:{row.id}",
                transaction_id=row.id,
                original_amount_text=original_amount,
                original_currency_code=original_currency,
                base_amount_text="",
                base_currency_code="",
                rate_text="",
                rate_date="",
                source="owner_review_pending",
                source_hash=finance_currency.evidence_fingerprint(
                    row.id,
                    original_amount,
                    original_currency,
                    "",
                    "",
                    "",
                    "",
                    "owner_review_pending",
                ),
            )
            db.add(proof)
        proof.original_currency_code = original_currency
        row.original_currency_code = original_currency
        if original_currency == base and rate != 1:
            raise ApiError(400, "invalid_identity_rate", "same-currency evidence must use rate 1")
        rate_date = _evidence_date(
            body.rate_date,
            original_currency=original_currency,
            base_currency=base,
        )
        converted = _converted(proof.original_amount_text, rate)
        proof.base_amount_text = converted
        proof.base_currency_code = base
        proof.rate_text = format(rate, "f")
        proof.rate_date = rate_date
        proof.source = source
        proof.source_hash = finance_currency.evidence_fingerprint(
            row.id,
            proof.original_amount_text,
            proof.original_currency_code,
            converted,
            base,
            proof.rate_text,
            rate_date,
            source,
        )
        row.base_amount_text = converted
        row.base_currency_code = base
        row.fx_rate_text = proof.rate_text
        row.fx_rate_date = proof.rate_date
        row.fx_source = proof.source
        payload = {
            "original_currency_code": original_currency,
            "base_amount_text": converted,
            "base_currency_code": base,
            "rate_text": proof.rate_text,
        }
    elif body.target_kind == "subscription":
        row = db.get(Subscription, body.target_id)
        if not row:
            raise ApiError(404, "finance_value_not_found", "subscription was not found")
        original_currency = _original_code(
            body.original_currency_code,
            row.original_currency_code,
            "subscription",
        )
        if original_currency == base and rate != 1:
            raise ApiError(400, "invalid_identity_rate", "same-currency evidence must use rate 1")
        rate_date = _evidence_date(
            body.rate_date,
            original_currency=original_currency,
            base_currency=base,
        )
        row.original_currency_code = original_currency
        row.base_price_text = _converted(row.original_price_text, rate)
        row.base_currency_code = base
        row.fx_rate_text = format(rate, "f")
        row.fx_rate_date = rate_date
        row.fx_source = source
        payload = {
            "original_currency_code": original_currency,
            "base_amount_text": row.base_price_text,
            "base_currency_code": base,
            "rate_text": row.fx_rate_text,
        }
    else:
        row = db.get(SubPayment, body.target_id)
        if not row:
            raise ApiError(404, "finance_value_not_found", "subscription payment was not found")
        original_currency = _original_code(
            body.original_currency_code,
            row.original_currency_code,
            "subscription_payment",
        )
        if original_currency == base and rate != 1:
            raise ApiError(400, "invalid_identity_rate", "same-currency evidence must use rate 1")
        rate_date = _evidence_date(
            body.rate_date,
            original_currency=original_currency,
            base_currency=base,
        )
        row.original_currency_code = original_currency
        row.base_amount_text = _converted(row.original_amount_text, rate)
        row.base_currency_code = base
        row.fx_rate_text = format(rate, "f")
        row.fx_rate_date = rate_date
        row.fx_source = source
        payload = {
            "original_currency_code": original_currency,
            "base_amount_text": row.base_amount_text,
            "base_currency_code": base,
            "rate_text": row.fx_rate_text,
        }
    db.commit()
    return {"ok": True, "target_kind": body.target_kind, "target_id": body.target_id, **payload}
