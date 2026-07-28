"""Preview-first, receipt-owned Phase 8 Finance imports."""

import hashlib
import json
import math
import threading
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.auth import require_auth, require_recent_owner
from core.database import (
    Account,
    FinanceImportBatch,
    FinanceImportRow,
    FinanceLedgerState,
    Transaction,
    get_db,
)
from services import actual_finance, finance_connectors, finance_currency, finance_imports

router = APIRouter(prefix="/api/finance/imports", dependencies=[Depends(require_auth)])
MAX_SOURCE_BYTES = 5 * 1024 * 1024
_IMPORT_APPLY_LOCK = threading.RLock()


class PreviewBody(BaseModel):
    account_id: str
    profile: str
    source_name: str
    content: str
    original_currency_code: str = ""


class ConversionEvidenceBody(BaseModel):
    base_amount_text: str
    rate_text: str
    rate_date: str
    source: str


class MatchResolutionBody(BaseModel):
    decision: str


class NotificationAccountConfirmationBody(BaseModel):
    account_id: str
    account_suffix: str


class RecoveryResolutionBody(BaseModel):
    decision: str


def _same(transaction: Transaction, parsed: dict, account_id: str) -> bool:
    return (
        transaction.account_id == account_id
        and transaction.date == parsed["date"]
        and Decimal(str(transaction.amount)) == Decimal(parsed["amount_text"])
        and Decimal(transaction.original_amount_text or str(transaction.amount))
        == Decimal(parsed["amount_text"])
        and " ".join((transaction.payee or "").casefold().split())
        == " ".join(parsed["payee"].casefold().split())
        and finance_currency.currency_code(transaction.original_currency_code)
        == finance_currency.currency_code(parsed["currency_code"])
    )


def _legacy_exact_float_amount(value: str) -> float:
    amount = Decimal(value)
    stored = float(amount)
    if not amount.is_finite() or not math.isfinite(stored) or Decimal(str(stored)) != amount:
        raise ValueError("amount cannot be represented exactly by the Alles ledger")
    return stored


def _same_actual(
    transaction: dict,
    parsed: dict,
    account_id: str,
    *,
    expected_base_amount=None,
) -> bool:
    current_base_amount = finance_currency.decimal_text(transaction["amount"])
    stored_base_matches = Decimal(current_base_amount) == Decimal(
        transaction.get("base_amount_text") or current_base_amount
    )
    reviewed_base_matches = expected_base_amount is None or Decimal(current_base_amount) == Decimal(
        str(expected_base_amount)
    )
    return (
        transaction["account_id"] == account_id
        and transaction["date"] == parsed["date"]
        and Decimal(transaction["original_amount_text"]) == Decimal(parsed["amount_text"])
        and stored_base_matches
        and reviewed_base_matches
        and " ".join(transaction["payee"].casefold().split())
        == " ".join(parsed["payee"].casefold().split())
        and finance_currency.currency_code(transaction["original_currency_code"])
        == finance_currency.currency_code(parsed["currency_code"])
    )


def _receipt_backend(batch: FinanceImportBatch, rows: list[FinanceImportRow], current: str) -> str:
    try:
        backend = str(json.loads(batch.receipt_json or "{}").get("ledger_backend") or "")
    except (TypeError, ValueError):
        backend = ""
    if backend in {"alles", "actual"}:
        return backend
    created = [row.created_transaction_id for row in rows if row.created_transaction_id]
    if any(value.startswith(f"finance-import:{batch.id}:") for value in created):
        return "actual"
    if created:
        return "alles"
    return current


def _same_parsed(left: dict, right: dict) -> bool:
    return (
        left["date"] == right["date"]
        and Decimal(left["amount_text"]) == Decimal(right["amount_text"])
        and " ".join(left["payee"].casefold().split())
        == " ".join(right["payee"].casefold().split())
        and finance_currency.currency_code(left["currency_code"])
        == finance_currency.currency_code(right["currency_code"])
    )


def _same_source_identity_was_applied(
    db: DbSession,
    *,
    account_id: str,
    profile: str,
    source_name: str,
    source_sha256: str,
    stable_identity: str,
) -> bool:
    return (
        db.query(FinanceImportRow.id)
        .join(FinanceImportBatch, FinanceImportRow.batch_id == FinanceImportBatch.id)
        .filter(
            FinanceImportBatch.account_id == account_id,
            FinanceImportBatch.profile == profile,
            FinanceImportBatch.source_name == source_name,
            FinanceImportBatch.source_sha256 == source_sha256,
            FinanceImportRow.stable_identity == stable_identity,
            FinanceImportRow.status == "applied",
        )
        .first()
        is not None
    )


_AMBIGUOUS_MATCH_REASON = (
    "matching row has no bank reference and came from a different statement; "
    "review it instead of assuming it is a duplicate"
)
_RECOVERY_CONFLICT_REASON = "incomplete Actual write no longer matches this receipt"


def _match_can_be_automatically_deduplicated(
    db: DbSession,
    *,
    batch: FinanceImportBatch,
    parsed: dict,
    stable_identity: str,
) -> bool:
    return bool(
        parsed.get("external_id")
        or _same_source_identity_was_applied(
            db,
            account_id=batch.account_id,
            profile=batch.profile,
            source_name=batch.source_name,
            source_sha256=batch.source_sha256,
            stable_identity=stable_identity,
        )
    )


def _matching_unreferenced_transaction(
    db: DbSession,
    *,
    batch: FinanceImportBatch,
    parsed: dict,
    canonical_transactions: list[dict],
    canonical: bool,
):
    if parsed.get("external_id"):
        return None
    if canonical:
        return next(
            (
                transaction
                for transaction in canonical_transactions
                if transaction.get("import_batch_id") != batch.id
                and _same_actual(transaction, parsed, batch.account_id)
            ),
            None,
        )
    candidates = (
        db.query(Transaction).filter_by(account_id=batch.account_id, date=parsed["date"]).all()
    )
    return next(
        (
            transaction
            for transaction in candidates
            if transaction.import_batch_id != batch.id
            and _same(transaction, parsed, batch.account_id)
        ),
        None,
    )


def _row_payload(row: FinanceImportRow) -> dict:
    return {
        "id": row.id,
        "row_number": row.row_number,
        "stable_identity": row.stable_identity,
        "raw": json.loads(row.raw_json or "{}"),
        "parsed": json.loads(row.parsed_json or "{}"),
        "conversion": json.loads(row.conversion_json or "{}"),
        "status": row.status,
        "existing_transaction_id": row.existing_transaction_id,
        "created_transaction_id": row.created_transaction_id,
        "conflict_reason": row.conflict_reason,
    }


def _counts(rows: list[FinanceImportRow]) -> dict:
    statuses = [row.status for row in rows]
    return {
        "rows": len(rows),
        "pending": statuses.count("pending"),
        "applying": statuses.count("applying"),
        "duplicates": statuses.count("duplicate"),
        "conflicts": statuses.count("conflict") + statuses.count("needs_review"),
        "applied": statuses.count("applied"),
        "undone": statuses.count("undone"),
    }


def _batch_payload(db: DbSession, batch: FinanceImportBatch) -> dict:
    rows = (
        db.query(FinanceImportRow)
        .filter_by(batch_id=batch.id)
        .order_by(FinanceImportRow.row_number)
        .all()
    )
    state = db.get(FinanceLedgerState, "primary")
    return {
        "id": batch.id,
        "account_id": batch.account_id,
        "profile": batch.profile,
        "source_name": batch.source_name,
        "source_sha256": batch.source_sha256,
        "original_currency_code": batch.original_currency_code,
        "canonical_base_currency_code": (
            state.base_currency_code if state and state.mode == "actual" else ""
        ),
        "status": batch.status,
        "counts": _counts(rows),
        "receipt": json.loads(batch.receipt_json or "{}"),
        "rows": [_row_payload(row) for row in rows],
    }


def _update_batch_counts(batch: FinanceImportBatch, rows: list[FinanceImportRow]) -> None:
    counts = _counts(rows)
    batch.row_count = counts["rows"]
    batch.applied_count = counts["applied"]
    batch.duplicate_count = counts["duplicates"]
    batch.conflict_count = counts["conflicts"]


def _notification_confirmation_reason(batch: FinanceImportBatch, parsed: dict) -> str:
    suffix = str(parsed.get("account_suffix") or "").strip()
    try:
        receipt = json.loads(batch.receipt_json or "{}")
    except (TypeError, ValueError):
        receipt = {}
    account_name = str(receipt.get("account_name") or "the selected account").strip()
    return f"confirm account ending {suffix} belongs to {account_name}"


def _notification_account_confirmed(batch: FinanceImportBatch, parsed: dict) -> bool:
    if batch.profile != "cmb-notification":
        return True
    suffix = str(parsed.get("account_suffix") or "").strip()
    if not suffix:
        return False
    try:
        receipt = json.loads(batch.receipt_json or "{}")
    except (TypeError, ValueError):
        return False
    confirmations = receipt.get("confirmed_account_suffixes")
    confirmation = confirmations.get(suffix) if isinstance(confirmations, dict) else None
    return bool(
        isinstance(confirmation, dict)
        and str(confirmation.get("account_id") or "") == batch.account_id
    )


def _conversion_evidence(
    row: FinanceImportRow,
    parsed: dict,
    batch: FinanceImportBatch,
    state: FinanceLedgerState,
) -> tuple[str, dict] | None:
    original_currency = finance_currency.currency_code(parsed["currency_code"])
    base_currency = finance_currency.currency_code(state.base_currency_code)
    if original_currency == base_currency:
        base_amount = parsed["amount_text"]
        try:
            actual_finance._minor(base_amount, "base amount")
        except actual_finance.ActualFinanceError:
            return None
        rate_text = "1"
        rate_date = ""
        source = f"finance_import:{batch.profile}"
    else:
        try:
            conversion = json.loads(row.conversion_json or "{}")
            original_amount = Decimal(str(parsed["amount_text"]))
            stored_original = Decimal(str(conversion["original_amount_text"]))
            base_amount_value = Decimal(str(conversion["base_amount_text"]))
            rate = Decimal(str(conversion["rate_text"]))
            stored_rate_date = date.fromisoformat(str(conversion["rate_date"])).isoformat()
            expected_base = (original_amount * rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
            valid = (
                conversion.get("version") == 1
                and stored_original == original_amount
                and finance_currency.currency_code(conversion["original_currency_code"])
                == original_currency
                and finance_currency.currency_code(conversion["base_currency_code"])
                == base_currency
                and conversion.get("source_hash") == batch.source_sha256
                and str(conversion.get("source") or "").startswith("owner_review:")
                and rate.is_finite()
                and rate > 0
                and base_amount_value.is_finite()
                and base_amount_value == base_amount_value.quantize(Decimal("0.01"))
                and base_amount_value == expected_base
            )
            actual_finance._minor(base_amount_value, "base amount")
        except (
            actual_finance.ActualFinanceError,
            InvalidOperation,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ):
            return None
        if not valid:
            return None
        base_amount = format(base_amount_value, "f")
        rate_text = format(rate, "f")
        rate_date = stored_rate_date
        source = str(conversion["source"])
    return base_amount, {
        "original_amount_text": parsed["amount_text"],
        "original_currency_code": original_currency,
        "base_amount_text": base_amount,
        "base_currency_code": base_currency,
        "rate_text": rate_text,
        "rate_date": rate_date,
        "source": source,
        "source_hash": batch.source_sha256,
        "import_batch_id": batch.id,
        "import_source": f"finance_import:{batch.profile}",
        "import_row_number": row.row_number,
    }


def _same_recovered_actual(
    transaction: dict,
    parsed: dict,
    base_amount: str,
    batch: FinanceImportBatch,
    stable_identity: str,
) -> bool:
    return (
        transaction["account_id"] == batch.account_id
        and transaction["date"] == parsed["date"]
        and Decimal(str(transaction["amount"])) == Decimal(base_amount)
        and str(transaction.get("payee") or "") == str(parsed["payee"]).strip()
        and str(transaction.get("category") or "") == ""
        and str(transaction.get("notes") or "") == f"imported from {batch.source_name}"
        and not bool(transaction.get("cleared"))
        and transaction["import_identity"] == stable_identity
    )


def _owner_approved_identity(batch: FinanceImportBatch, row: FinanceImportRow) -> str:
    evidence = json.dumps(
        {
            "kind": "owner-approved-import-row",
            "account_id": batch.account_id,
            "profile": batch.profile,
            "source_name": batch.source_name,
            "source_sha256": batch.source_sha256,
            "row_number": row.row_number,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{hashlib.sha256(evidence.encode()).hexdigest()}"


def _owner_approved_new(batch: FinanceImportBatch, row: FinanceImportRow) -> bool:
    try:
        receipt = json.loads(batch.receipt_json or "{}")
    except (TypeError, ValueError):
        return False
    decisions = receipt.get("row_match_decisions")
    decision = decisions.get(row.id) if isinstance(decisions, dict) else None
    return bool(
        isinstance(decision, dict)
        and decision.get("decision") == "new"
        and decision.get("resolved_stable_identity") == row.stable_identity
    )


def _owner_approved_deleted_reimport(batch: FinanceImportBatch, row: FinanceImportRow) -> bool:
    try:
        receipt = json.loads(batch.receipt_json or "{}")
    except (TypeError, ValueError):
        return False
    decisions = receipt.get("row_recovery_decisions")
    decision = decisions.get(row.id) if isinstance(decisions, dict) else None
    return bool(
        isinstance(decision, dict)
        and decision.get("decision") == "delete"
        and decision.get("stable_identity") == row.stable_identity
        and decision.get("source_id") == f"finance-import:{batch.id}:{row.row_number}"
    )


def _owner_accepted_replacement(batch: FinanceImportBatch, row: FinanceImportRow) -> dict | None:
    try:
        receipt = json.loads(batch.receipt_json or "{}")
    except (TypeError, ValueError):
        return None
    decisions = receipt.get("row_recovery_decisions")
    decision = decisions.get(row.id) if isinstance(decisions, dict) else None
    replacement = decision.get("accepted_replacement") if isinstance(decision, dict) else None
    if not (
        isinstance(decision, dict)
        and decision.get("decision") == "keep"
        and decision.get("stable_identity") == row.stable_identity
        and decision.get("source_id") == f"finance-import:{batch.id}:{row.row_number}"
        and isinstance(replacement, dict)
        and replacement.get("import_identity") == row.stable_identity
    ):
        return None
    return replacement


@router.get("/profiles")
def profiles():
    return {
        "profiles": list(finance_imports.PROFILE_DETAILS),
        "providers": list(finance_connectors.PROVIDERS),
        "direct_sync_supported": True,
        "provider_note": "SimpleFIN and Plaid are read-only. Statement and notification imports remain available when direct access is unavailable.",
    }


@router.post("/preview", dependencies=[Depends(require_recent_owner)])
def preview(body: PreviewBody, db: DbSession = Depends(get_db)):
    with actual_finance.AUTHORITY_LOCK:
        return _preview_locked(body, db)


def _preview_locked(body: PreviewBody, db: DbSession):
    canonical = actual_finance.is_canonical(db)
    canonical_state = db.get(FinanceLedgerState, "primary") if canonical else None
    canonical_base_currency = (
        finance_currency.currency_code(canonical_state.base_currency_code)
        if canonical_state
        else "XXX"
    )
    account = db.get(Account, body.account_id) if not canonical else None
    actual_accounts = actual_finance.accounts(db) if canonical else []
    actual_account = next((row for row in actual_accounts if row["id"] == body.account_id), None)
    if not account and not actual_account:
        raise HTTPException(400, "unknown account")
    if body.profile not in finance_imports.PROFILES:
        raise HTTPException(400, "unsupported import profile")
    source = body.content.encode("utf-8")
    if not source or len(source) > MAX_SOURCE_BYTES:
        raise HTTPException(400, "source must be between 1 byte and 5 MiB")
    source_name = body.source_name.strip()
    if not source_name:
        raise HTTPException(400, "source name is required")
    source_sha = hashlib.sha256(source).hexdigest()
    # Banks commonly reuse generic download names. Bind fallback row positions to the exact source
    # bytes so an unrelated later ``statement.csv`` cannot collide with an earlier statement. Exact
    # replays remain stable, while cross-statement overlap is handled by the reviewed match fingerprint.
    statement_identity = f"{source_name.casefold()}:{source_sha}"
    currency = finance_currency.currency_code(
        body.original_currency_code
        or finance_imports.PROFILES[body.profile]["default_currency_code"]
    )
    batch_id = str(uuid.uuid4())
    try:
        parsed_rows = finance_imports.parse(
            body.profile,
            body.content,
            account_id=body.account_id,
            requested_currency=currency,
            statement_identity=statement_identity,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    account_name = (actual_account or {}).get("name") if canonical else account.name
    account_currency = (
        ""
        if canonical
        else finance_currency.currency_code(account.currency_code or account.currency)
    )
    # In the legacy ledger every row allowed to remain pending has already
    # matched this account currency. Persist that reviewed target currency,
    # rather than a profile default that an explicit CSV currency overrode.
    receipt_currency = currency if canonical else account_currency
    batch = FinanceImportBatch(
        id=batch_id,
        account_id=body.account_id,
        profile=body.profile,
        source_name=source_name,
        source_sha256=source_sha,
        original_currency_code=receipt_currency,
        status="preview",
    )
    db.add(batch)
    db.flush()
    canonical_transactions = actual_finance.transactions(db) if canonical else []
    actual_by_identity = {
        row["import_identity"]: row for row in canonical_transactions if row["import_identity"]
    }
    rows = []
    seen: dict[str, list[tuple[FinanceImportRow, dict]]] = {}
    for item in parsed_rows:
        status = "pending"
        existing_id = ""
        reason = ""
        if item["error"]:
            status = "needs_review"
            reason = item["error"]
        else:
            imported_currency = finance_currency.currency_code(item["parsed"].get("currency_code"))
            conversion_required = canonical and imported_currency != canonical_base_currency
            if not canonical and account_currency == "XXX":
                status = "needs_review"
                reason = "selected account requires a reviewed currency code before import"
            elif not canonical and imported_currency != account_currency:
                status = "needs_review"
                reason = (
                    f"import currency {imported_currency} does not match selected "
                    f"account currency {account_currency}"
                )
            elif body.profile == "cmb-notification":
                suffix = item["parsed"].get("account_suffix", "")
                status = "needs_review"
                reason = (
                    f"confirm account ending {suffix} belongs to "
                    f"{account_name or 'the selected account'}"
                )
            prior = seen.get(item["stable_identity"], [])
            if prior:
                prior_existing_ids = {
                    row.existing_transaction_id
                    for row, _parsed in prior
                    if row.existing_transaction_id
                }
                if len(prior_existing_ids) == 1:
                    existing_id = prior_existing_ids.pop()
                if all(_same_parsed(parsed, item["parsed"]) for _row, parsed in prior) and not any(
                    row.status == "conflict" for row, _parsed in prior
                ):
                    if conversion_required and status == "pending":
                        status = "needs_review"
                        reason = f"conversion evidence to {canonical_base_currency} is required before apply"
                    elif status == "pending":
                        status = "duplicate"
                        reason = "same source row identity is repeated in this receipt"
                else:
                    status = "conflict"
                    reason = "same source identity has conflicting rows in this receipt"
                    for previous, _parsed in prior:
                        previous.status = "conflict"
                        previous.conflict_reason = reason
            else:
                existing = (
                    actual_by_identity.get(item["stable_identity"])
                    if canonical
                    else db.query(Transaction)
                    .filter_by(import_identity=item["stable_identity"])
                    .first()
                )
                if existing:
                    existing_id = existing["id"] if canonical else existing.id
                    if (
                        _same_actual(
                            existing,
                            item["parsed"],
                            body.account_id,
                            expected_base_amount=(
                                item["parsed"]["amount_text"] if not conversion_required else None
                            ),
                        )
                        if canonical
                        else _same(existing, item["parsed"], body.account_id)
                    ):
                        if conversion_required and status == "pending":
                            status = "needs_review"
                            reason = (
                                f"conversion evidence to {canonical_base_currency} "
                                "is required before apply"
                            )
                        elif status != "pending":
                            pass
                        elif _match_can_be_automatically_deduplicated(
                            db,
                            batch=batch,
                            parsed=item["parsed"],
                            stable_identity=item["stable_identity"],
                        ):
                            status = "duplicate"
                        else:
                            status = "needs_review"
                            reason = _AMBIGUOUS_MATCH_REASON
                    else:
                        status = "conflict"
                        reason = "same source identity has changed account, date, amount, payee, or currency"
                elif status == "pending":
                    ambiguous = _matching_unreferenced_transaction(
                        db,
                        batch=batch,
                        parsed=item["parsed"],
                        canonical_transactions=canonical_transactions,
                        canonical=canonical,
                    )
                    if ambiguous:
                        existing_id = ambiguous["id"] if canonical else ambiguous.id
                        status = "needs_review"
                        reason = _AMBIGUOUS_MATCH_REASON
            if conversion_required and status == "pending":
                status = "needs_review"
                reason = (
                    f"conversion evidence to {canonical_base_currency} is required before apply"
                )
        row = FinanceImportRow(
            batch_id=batch.id,
            row_number=item["line_number"],
            stable_identity=item["stable_identity"],
            raw_json=json.dumps(item["raw"], ensure_ascii=False, sort_keys=True),
            parsed_json=json.dumps(item["parsed"], ensure_ascii=False, sort_keys=True),
            status=status,
            existing_transaction_id=existing_id,
            conflict_reason=reason,
        )
        db.add(row)
        rows.append(row)
        if not item["error"]:
            seen.setdefault(item["stable_identity"], []).append((row, item["parsed"]))
    db.flush()
    _update_batch_counts(batch, rows)
    receipt = {
        "version": 1,
        "ledger_backend": "actual" if canonical else "alles",
        "account_id": body.account_id,
        "profile": body.profile,
        "source_name": source_name,
        "source_sha256": source_sha,
        "original_currency_code": receipt_currency,
    }
    if body.profile == "cmb-notification":
        receipt.update(
            {
                "account_name": account_name or "account",
                "confirmed_account_suffixes": {},
            }
        )
    batch.receipt_json = json.dumps(receipt, sort_keys=True)
    db.commit()
    return _batch_payload(db, batch)


@router.get("")
def list_batches(db: DbSession = Depends(get_db)):
    batches = (
        db.query(FinanceImportBatch).order_by(FinanceImportBatch.created_at.desc()).limit(20).all()
    )
    return [_batch_payload(db, batch) for batch in batches]


@router.get("/{batch_id}")
def get_batch(batch_id: str, db: DbSession = Depends(get_db)):
    batch = db.get(FinanceImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "import receipt not found")
    return _batch_payload(db, batch)


@router.post(
    "/{batch_id}/rows/{row_id}/confirm-account",
    dependencies=[Depends(require_recent_owner)],
)
def confirm_notification_account(
    batch_id: str,
    row_id: str,
    body: NotificationAccountConfirmationBody,
    db: DbSession = Depends(get_db),
):
    with _IMPORT_APPLY_LOCK, actual_finance.AUTHORITY_LOCK:
        batch = db.get(FinanceImportBatch, batch_id)
        row = db.get(FinanceImportRow, row_id)
        if not batch or not row or row.batch_id != batch.id:
            raise HTTPException(404, "import row not found")
        if batch.profile != "cmb-notification" or batch.status != "preview":
            raise HTTPException(
                409, "account confirmation is available only during notification preview"
            )
        try:
            parsed = json.loads(row.parsed_json or "{}")
        except (TypeError, ValueError) as exc:
            raise HTTPException(409, "notification account suffix is unavailable") from exc
        suffix = str(parsed.get("account_suffix") or "").strip()
        if (
            not suffix
            or row.status != "needs_review"
            or not row.conflict_reason.startswith(f"confirm account ending {suffix} ")
        ):
            raise HTTPException(409, "notification account suffix is not awaiting confirmation")
        if body.account_id.strip() != batch.account_id or body.account_suffix.strip() != suffix:
            raise HTTPException(409, "notification account confirmation does not match this row")

        receipt = json.loads(batch.receipt_json or "{}")
        confirmations = receipt.get("confirmed_account_suffixes")
        if not isinstance(confirmations, dict):
            confirmations = {}
        confirmations[suffix] = {
            "account_id": batch.account_id,
            "confirmed_at": datetime.now(UTC).isoformat(),
        }
        receipt["confirmed_account_suffixes"] = confirmations
        batch.receipt_json = json.dumps(receipt, sort_keys=True)

        rows = db.query(FinanceImportRow).filter_by(batch_id=batch.id).all()
        for candidate in rows:
            if candidate.status != "needs_review":
                continue
            try:
                candidate_parsed = json.loads(candidate.parsed_json or "{}")
            except (TypeError, ValueError):
                continue
            if str(
                candidate_parsed.get("account_suffix") or ""
            ).strip() == suffix and candidate.conflict_reason.startswith(
                f"confirm account ending {suffix} "
            ):
                candidate.status = "pending"
                candidate.conflict_reason = ""
        _update_batch_counts(batch, rows)
        db.commit()
        return _batch_payload(db, batch)


@router.post(
    "/{batch_id}/rows/{row_id}/resolve-match",
    dependencies=[Depends(require_recent_owner)],
)
def resolve_ambiguous_match(
    batch_id: str,
    row_id: str,
    body: MatchResolutionBody,
    db: DbSession = Depends(get_db),
):
    with _IMPORT_APPLY_LOCK, actual_finance.AUTHORITY_LOCK:
        batch = db.get(FinanceImportBatch, batch_id)
        row = db.get(FinanceImportRow, row_id)
        if not batch or not row or row.batch_id != batch.id:
            raise HTTPException(404, "import row not found")
        if batch.status != "preview" or row.status != "needs_review":
            raise HTTPException(409, "this import row is not awaiting a match decision")
        if not row.conflict_reason.startswith("matching row has no bank reference "):
            raise HTTPException(409, "this review row is not an ambiguous statement match")
        decision = body.decision.strip().casefold()
        if decision not in {"duplicate", "new"}:
            raise HTTPException(400, "decision must be duplicate or new")
        try:
            parsed = json.loads(row.parsed_json or "{}")
        except (TypeError, ValueError) as exc:
            raise HTTPException(409, "row parsing must be resolved before match review") from exc

        original_identity = row.stable_identity
        resolved_identity = original_identity
        if decision == "duplicate":
            row.status = "duplicate"
            row.conflict_reason = ""
        else:
            approved_identity = _owner_approved_identity(batch, row)
            resolved_identity = approved_identity
            canonical = actual_finance.is_canonical(db)
            existing = (
                next(
                    (
                        candidate
                        for candidate in actual_finance.transactions(db)
                        if candidate["import_identity"] == approved_identity
                    ),
                    None,
                )
                if canonical
                else db.query(Transaction).filter_by(import_identity=approved_identity).first()
            )
            if existing:
                row.existing_transaction_id = existing["id"] if canonical else existing.id
                if (
                    _same_actual(existing, parsed, batch.account_id)
                    if canonical
                    else _same(existing, parsed, batch.account_id)
                ):
                    row.status = "duplicate"
                    row.conflict_reason = ""
                else:
                    row.status = "conflict"
                    row.conflict_reason = "the prior owner-approved import identity has changed"
            else:
                row.stable_identity = approved_identity
                row.existing_transaction_id = ""
                row.status = "pending"
                row.conflict_reason = ""

        try:
            receipt = json.loads(batch.receipt_json or "{}")
        except (TypeError, ValueError):
            receipt = {}
        decisions = receipt.get("row_match_decisions")
        if not isinstance(decisions, dict):
            decisions = {}
        decisions[row.id] = {
            "decision": decision,
            "original_stable_identity": original_identity,
            "resolved_stable_identity": resolved_identity,
            "decided_at": datetime.now(UTC).isoformat(),
        }
        receipt["row_match_decisions"] = decisions
        batch.receipt_json = json.dumps(receipt, sort_keys=True)
        rows = db.query(FinanceImportRow).filter_by(batch_id=batch.id).all()
        _update_batch_counts(batch, rows)
        db.commit()
        return _batch_payload(db, batch)


@router.post(
    "/{batch_id}/rows/{row_id}/resolve-recovery",
    dependencies=[Depends(require_recent_owner)],
)
def resolve_incomplete_actual_write(
    batch_id: str,
    row_id: str,
    body: RecoveryResolutionBody,
    db: DbSession = Depends(get_db),
):
    with _IMPORT_APPLY_LOCK, actual_finance.AUTHORITY_LOCK:
        batch = db.get(FinanceImportBatch, batch_id)
        row = db.get(FinanceImportRow, row_id)
        if not batch or not row or row.batch_id != batch.id:
            raise HTTPException(404, "import row not found")
        source_id = f"finance-import:{batch.id}:{row.row_number}"
        if (
            batch.status != "preview"
            or row.status != "conflict"
            or row.conflict_reason != _RECOVERY_CONFLICT_REASON
            or row.created_transaction_id != source_id
        ):
            raise HTTPException(409, "this row is not awaiting interrupted-write recovery")
        if not actual_finance.is_canonical(db):
            raise HTTPException(409, "interrupted-write recovery requires canonical Actual")
        decision = body.decision.strip().casefold()
        if decision not in {"keep", "delete"}:
            raise HTTPException(400, "decision must be keep or delete")
        matches = [
            candidate
            for candidate in actual_finance.transactions(db)
            if candidate["import_identity"] == row.stable_identity
        ]
        if len(matches) > 1:
            raise HTTPException(409, "the interrupted import identity is not unique in Actual")
        existing = matches[0] if matches else None
        if existing and row.existing_transaction_id not in {"", existing["id"]}:
            raise HTTPException(409, "the interrupted Actual transaction identity changed")
        if decision == "keep":
            if not existing:
                raise HTTPException(409, "the edited Actual transaction is no longer present")
            state = db.get(FinanceLedgerState, "primary")
            if not state:
                raise HTTPException(409, "canonical ledger state is unavailable")
            base_currency = finance_currency.currency_code(state.base_currency_code)
            if base_currency == "XXX":
                raise HTTPException(409, "canonical ledger base currency is invalid")
            amount_text = finance_currency.decimal_text(existing["amount"])
            replacement = {
                "account_id": existing["account_id"],
                "date": existing["date"],
                "amount": amount_text,
                "payee": existing.get("payee", ""),
                "category": existing.get("category", ""),
                "notes": existing.get("notes", ""),
                "cleared": bool(existing.get("cleared")),
                "import_identity": row.stable_identity,
            }
            recovery_evidence = {
                "original_amount_text": amount_text,
                "original_currency_code": base_currency,
                "base_amount_text": amount_text,
                "base_currency_code": base_currency,
                "rate_text": "1",
                "rate_date": "",
                "source": "owner_recovery_replacement",
                "source_hash": batch.source_sha256,
                "import_batch_id": batch.id,
                "import_source": f"finance_import:{batch.profile}",
                "import_row_number": row.row_number,
            }
            actual_finance.record_transaction_link(
                db,
                source_id,
                existing["actual_id"],
                recovery_evidence,
                values=replacement,
            )
            row.status = "applied"
            row.created_transaction_id = source_id
        else:
            if existing:
                actual_finance.delete_transaction(db, existing["id"])
                remaining = [
                    candidate
                    for candidate in actual_finance.transactions(db)
                    if candidate["import_identity"] == row.stable_identity
                ]
                if remaining:
                    raise HTTPException(409, "the interrupted Actual transaction was not deleted")
            row.status = "pending"
            row.created_transaction_id = ""
            row.existing_transaction_id = ""
        row.conflict_reason = ""

        try:
            receipt = json.loads(batch.receipt_json or "{}")
        except (TypeError, ValueError):
            receipt = {}
        decisions = receipt.get("row_recovery_decisions")
        if not isinstance(decisions, dict):
            decisions = {}
        decisions[row.id] = {
            "decision": decision,
            "stable_identity": row.stable_identity,
            "source_id": source_id,
            "actual_transaction_id": existing["id"] if existing else "",
            "actual_native_id": existing["actual_id"] if existing else "",
            "accepted_replacement": replacement if decision == "keep" else None,
            "decided_at": datetime.now(UTC).isoformat(),
        }
        receipt["row_recovery_decisions"] = decisions
        batch.receipt_json = json.dumps(receipt, sort_keys=True)
        rows = db.query(FinanceImportRow).filter_by(batch_id=batch.id).all()
        _update_batch_counts(batch, rows)
        still_reviewable = any(
            candidate.status in {"pending", "needs_review", "applying", "conflict"}
            for candidate in rows
        )
        finished = bool(rows) and not still_reviewable
        batch.status = "applied" if finished else "preview"
        batch.applied_at = datetime.now(UTC) if finished else None
        db.commit()
        return _batch_payload(db, batch)


@router.patch(
    "/{batch_id}/rows/{row_id}/conversion",
    dependencies=[Depends(require_recent_owner)],
)
def review_conversion(
    batch_id: str,
    row_id: str,
    body: ConversionEvidenceBody,
    db: DbSession = Depends(get_db),
):
    with _IMPORT_APPLY_LOCK, actual_finance.AUTHORITY_LOCK:
        return _review_conversion_locked(batch_id, row_id, body, db)


def _review_conversion_locked(
    batch_id: str,
    row_id: str,
    body: ConversionEvidenceBody,
    db: DbSession,
):
    batch = db.get(FinanceImportBatch, batch_id)
    row = db.get(FinanceImportRow, row_id)
    if not batch or not row or row.batch_id != batch.id:
        raise HTTPException(404, "import row not found")
    if row.status not in {"pending", "needs_review"} or row.created_transaction_id:
        raise HTTPException(409, "conversion evidence can be changed only before apply")
    state = db.get(FinanceLedgerState, "primary")
    if not state or state.mode != "actual":
        raise HTTPException(
            409, "reviewed row conversion is required only for canonical Actual imports"
        )
    try:
        parsed = json.loads(row.parsed_json or "{}")
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, "row parsing must be resolved before conversion review") from exc
    if not isinstance(parsed, dict) or not all(
        key in parsed for key in ("currency_code", "amount_text")
    ):
        raise HTTPException(409, "row parsing must be resolved before conversion review")
    original_currency = finance_currency.currency_code(parsed["currency_code"])
    base_currency = finance_currency.currency_code(state.base_currency_code)
    if "XXX" in {original_currency, base_currency}:
        raise HTTPException(
            409, "conversion evidence requires reviewed original and base currency codes"
        )
    if original_currency == base_currency:
        raise HTTPException(409, "this row is already in the canonical base currency")
    try:
        original = Decimal(parsed["amount_text"])
        base_amount = Decimal(body.base_amount_text)
        rate = Decimal(body.rate_text)
        values = (original, base_amount, rate)
        if (
            any(
                not value.is_finite()
                or len(value.as_tuple().digits) > 28
                or not -18 <= value.adjusted() <= 18
                for value in values
            )
            or rate <= 0
        ):
            raise InvalidOperation
        cents = Decimal("0.01")
        normalized_base = base_amount.quantize(cents)
        expected_base = (original * rate).quantize(cents, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(400, "amount and rate must be exact supported decimals") from exc
    if base_amount != normalized_base or base_amount != expected_base:
        raise HTTPException(400, "base amount must equal original amount times the positive rate")
    try:
        actual_finance._minor(base_amount, "base amount")
    except actual_finance.ActualFinanceError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        rate_date = date.fromisoformat(body.rate_date).isoformat()
    except ValueError as exc:
        raise HTTPException(400, "rate date must be YYYY-MM-DD") from exc
    source = " ".join(body.source.strip().split())
    if not source or len(source) > 120:
        raise HTTPException(400, "conversion source must be between 1 and 120 characters")
    prior_review_reason = row.conflict_reason if row.status == "needs_review" else ""
    row.conversion_json = json.dumps(
        {
            "version": 1,
            "original_amount_text": parsed["amount_text"],
            "original_currency_code": original_currency,
            "base_amount_text": format(base_amount, "f"),
            "base_currency_code": base_currency,
            "rate_text": format(rate, "f"),
            "rate_date": rate_date,
            "source": f"owner_review:{source}",
            "source_hash": batch.source_sha256,
        },
        sort_keys=True,
    )
    if prior_review_reason and not prior_review_reason.startswith("conversion evidence to "):
        row.status = "needs_review"
        row.conflict_reason = prior_review_reason
    elif _notification_account_confirmed(batch, parsed):
        row.status = "pending"
        row.conflict_reason = ""
    else:
        row.status = "needs_review"
        row.conflict_reason = _notification_confirmation_reason(batch, parsed)
    batch.status = "preview"
    rows = db.query(FinanceImportRow).filter_by(batch_id=batch.id).all()
    _update_batch_counts(batch, rows)
    db.commit()
    return _batch_payload(db, batch)


@router.post("/{batch_id}/apply", dependencies=[Depends(require_recent_owner)])
def apply_batch(batch_id: str, db: DbSession = Depends(get_db)):
    # Alles runs one application process. Hold the claim across inspect + external
    # write so two submits cannot race between those bridge operations. Actual's
    # stable imported_id remains the durable idempotency key across crash retries.
    with _IMPORT_APPLY_LOCK, actual_finance.AUTHORITY_LOCK:
        return _apply_batch_locked(batch_id, db)


def _apply_batch_locked(batch_id: str, db: DbSession):
    batch = db.get(FinanceImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "import receipt not found")
    if batch.status == "undone":
        raise HTTPException(409, "an undone import cannot be reapplied")
    rows = (
        db.query(FinanceImportRow)
        .filter_by(batch_id=batch.id)
        .order_by(FinanceImportRow.row_number)
        .all()
    )
    unresolved = [row for row in rows if row.status in {"conflict", "needs_review"}]
    if unresolved:
        raise HTTPException(
            409,
            "resolve every import conflict and review row before applying this receipt",
        )
    canonical = actual_finance.is_canonical(db)
    current_backend = "actual" if canonical else "alles"
    if _receipt_backend(batch, rows, current_backend) != current_backend:
        raise HTTPException(409, "ledger mode changed after preview; create a new import preview")
    state = db.get(FinanceLedgerState, "primary")
    if not canonical:
        # The account is mutable between preview and apply. Revalidate the
        # reviewed target inside the same lock as the eventual transaction
        # writes so a deleted or re-denominated account cannot receive stale
        # statement rows.
        account = db.get(Account, batch.account_id)
        reviewed_currency = finance_currency.currency_code(batch.original_currency_code)
        current_currency = (
            finance_currency.currency_code(account.currency_code or account.currency)
            if account
            else ""
        )
        target_problem = ""
        if not account:
            target_problem = "selected account was deleted after preview; create a new preview"
        elif current_currency == "XXX":
            target_problem = (
                "selected account no longer has a reviewed currency code; create a new preview"
            )
        elif reviewed_currency == "XXX" or current_currency != reviewed_currency:
            target_problem = "selected account currency changed after preview; create a new preview"
        if target_problem:
            for row in rows:
                if row.status == "pending":
                    row.status = "needs_review"
                    row.conflict_reason = target_problem
            batch.status = "preview"
            _update_batch_counts(batch, rows)
            db.commit()
            return _batch_payload(db, batch)
    if canonical:
        missing_conversion = False
        for row in rows:
            if row.status not in {"pending", "duplicate"}:
                continue
            parsed = json.loads(row.parsed_json)
            if _conversion_evidence(row, parsed, batch, state) is None:
                row.conversion_json = ""
                row.status = "needs_review"
                row.conflict_reason = (
                    f"conversion evidence to {state.base_currency_code} is required before apply"
                )
                missing_conversion = True
        if missing_conversion:
            batch.status = "preview"
            _update_batch_counts(batch, rows)
            db.commit()
            return _batch_payload(db, batch)
        grouped_rows: dict[str, list[FinanceImportRow]] = {}
        for row in rows:
            if row.status in {"pending", "duplicate"}:
                grouped_rows.setdefault(row.stable_identity, []).append(row)
        reviewed_identity_conflict = False
        for repeated in grouped_rows.values():
            if len(repeated) < 2:
                continue
            parsed_rows = [json.loads(row.parsed_json) for row in repeated]
            conversions = [
                _conversion_evidence(row, parsed, batch, state)
                for row, parsed in zip(repeated, parsed_rows, strict=True)
            ]
            if any(conversion is None for conversion in conversions):
                for row in repeated:
                    row.status = "needs_review"
                    row.conflict_reason = f"conversion evidence to {state.base_currency_code} is required before apply"
                reviewed_identity_conflict = True
                continue
            if (
                not all(_same_parsed(parsed_rows[0], parsed) for parsed in parsed_rows[1:])
                or len({conversion[0] for conversion in conversions}) != 1
            ):
                for row in repeated:
                    row.status = "conflict"
                    row.conflict_reason = (
                        "same source identity has conflicting reviewed conversion amounts"
                    )
                reviewed_identity_conflict = True
            else:
                for duplicate in repeated[1:]:
                    duplicate.status = "duplicate"
                    duplicate.conflict_reason = (
                        "same source row identity is repeated in this receipt"
                    )
        if reviewed_identity_conflict:
            batch.status = "preview"
            _update_batch_counts(batch, rows)
            db.commit()
            return _batch_payload(db, batch)
    actual_rows = actual_finance.transactions(db) if canonical else []
    actual_by_identity = {
        row["import_identity"]: row for row in actual_rows if row["import_identity"]
    }
    actual_by_public_id = {str(row.get("id") or ""): row for row in actual_rows if row.get("id")}
    duplicate_match_blocked = False
    for row in rows:
        if row.status != "duplicate":
            continue
        parsed = json.loads(row.parsed_json)
        conversion = _conversion_evidence(row, parsed, batch, state) if canonical else None
        if canonical and conversion is None:
            row.conversion_json = ""
            row.status = "needs_review"
            row.conflict_reason = (
                f"conversion evidence to {state.base_currency_code} is required before apply"
            )
            duplicate_match_blocked = True
            continue
        if row.existing_transaction_id:
            existing = (
                actual_by_public_id.get(row.existing_transaction_id)
                if canonical
                else db.get(Transaction, row.existing_transaction_id)
            )
            matches = bool(existing) and (
                _same_actual(
                    existing,
                    parsed,
                    batch.account_id,
                    expected_base_amount=conversion[0],
                )
                if canonical
                else _same(existing, parsed, batch.account_id)
            )
        else:
            matches = False
            for candidate in rows:
                if (
                    candidate.id == row.id
                    or candidate.stable_identity != row.stable_identity
                    or candidate.status not in {"pending", "applying", "applied"}
                ):
                    continue
                candidate_parsed = json.loads(candidate.parsed_json)
                if not _same_parsed(candidate_parsed, parsed):
                    continue
                if not canonical:
                    matches = True
                    break
                candidate_conversion = _conversion_evidence(
                    candidate, candidate_parsed, batch, state
                )
                if candidate_conversion and candidate_conversion[0] == conversion[0]:
                    matches = True
                    break
        if not matches:
            row.status = "needs_review"
            row.conflict_reason = (
                (
                    "previously matched transaction changed or was deleted after preview; "
                    "create a new preview"
                )
                if row.existing_transaction_id
                else "repeated source identity no longer matches a reviewed row in this receipt"
            )
            duplicate_match_blocked = True
    if duplicate_match_blocked:
        batch.status = "preview"
        _update_batch_counts(batch, rows)
        db.commit()
        return _batch_payload(db, batch)
    # Resolve every interrupted Actual write before starting any new write. If
    # one no longer matches its receipt, the whole batch must stop while every
    # still-pending row remains undoable and untouched.
    recovery_conflict = False
    if canonical:
        for row in rows:
            if row.status != "applying":
                continue
            parsed = json.loads(row.parsed_json)
            conversion = _conversion_evidence(row, parsed, batch, state)
            existing = actual_by_identity.get(row.stable_identity)
            if not existing:
                continue
            row.existing_transaction_id = existing["id"]
            if conversion and _same_recovered_actual(
                existing, parsed, conversion[0], batch, row.stable_identity
            ):
                source_id = f"finance-import:{batch.id}:{row.row_number}"
                actual_finance.record_transaction_link(
                    db,
                    source_id,
                    existing["actual_id"],
                    conversion[1],
                    values={
                        "account_id": batch.account_id,
                        "date": parsed["date"],
                        "amount": conversion[0],
                        "payee": parsed["payee"],
                        "notes": f"imported from {batch.source_name}",
                        "import_identity": row.stable_identity,
                    },
                )
                row.created_transaction_id = source_id
                row.status = "applied"
                row.conflict_reason = ""
            else:
                row.status = "conflict"
                row.conflict_reason = _RECOVERY_CONFLICT_REASON
                recovery_conflict = True
    if recovery_conflict:
        batch.status = "preview"
        _update_batch_counts(batch, rows)
        db.commit()
        return _batch_payload(db, batch)
    # Recheck every pending identity against one current ledger snapshot before
    # the first write. A transaction can be added after preview; discovering it
    # row-by-row during mutation could otherwise leave an earlier row applied
    # while the receipt returns to preview and cannot be undone.
    preflight_blocked = False
    for row in rows:
        if row.status != "pending":
            continue
        parsed = json.loads(row.parsed_json)
        if not canonical:
            try:
                _legacy_exact_float_amount(parsed["amount_text"])
            except (InvalidOperation, ValueError):
                row.status = "needs_review"
                row.conflict_reason = (
                    "amount cannot be represented exactly by the Alles ledger; "
                    "use a smaller exact decimal amount"
                )
                preflight_blocked = True
                continue
        conversion = _conversion_evidence(row, parsed, batch, state) if canonical else None
        existing = (
            actual_by_identity.get(row.stable_identity)
            if canonical
            else db.query(Transaction).filter_by(import_identity=row.stable_identity).first()
        )
        if not existing and not _owner_approved_new(batch, row):
            existing = _matching_unreferenced_transaction(
                db,
                batch=batch,
                parsed=parsed,
                canonical_transactions=actual_rows,
                canonical=canonical,
            )
            if existing:
                row.existing_transaction_id = existing["id"] if canonical else existing.id
                row.status = "needs_review"
                row.conflict_reason = _AMBIGUOUS_MATCH_REASON
                preflight_blocked = True
                continue
        if not existing:
            continue
        row.existing_transaction_id = existing["id"] if canonical else existing.id
        if (
            _same_actual(
                existing,
                parsed,
                batch.account_id,
                expected_base_amount=conversion[0],
            )
            if canonical
            else _same(existing, parsed, batch.account_id)
        ):
            if _match_can_be_automatically_deduplicated(
                db,
                batch=batch,
                parsed=parsed,
                stable_identity=row.stable_identity,
            ):
                row.status = "duplicate"
                row.conflict_reason = ""
            else:
                row.status = "needs_review"
                row.conflict_reason = _AMBIGUOUS_MATCH_REASON
                preflight_blocked = True
        else:
            row.status = "conflict"
            row.conflict_reason = "same source identity or account changed before apply"
            preflight_blocked = True
    if preflight_blocked:
        batch.status = "preview"
        _update_batch_counts(batch, rows)
        db.commit()
        return _batch_payload(db, batch)
    for row in rows:
        if row.status not in {"pending", "applying"}:
            continue
        parsed = json.loads(row.parsed_json)
        source_id = f"finance-import:{batch.id}:{row.row_number}"
        conversion = _conversion_evidence(row, parsed, batch, state) if canonical else None
        existing = (
            actual_by_identity.get(row.stable_identity)
            if canonical
            else db.query(Transaction).filter_by(import_identity=row.stable_identity).first()
        )
        if existing:
            row.existing_transaction_id = existing["id"] if canonical else existing.id
            if (
                _same_actual(
                    existing,
                    parsed,
                    batch.account_id,
                    expected_base_amount=conversion[0],
                )
                if canonical
                else _same(existing, parsed, batch.account_id)
            ):
                if _match_can_be_automatically_deduplicated(
                    db,
                    batch=batch,
                    parsed=parsed,
                    stable_identity=row.stable_identity,
                ):
                    row.status = "duplicate"
                    row.conflict_reason = ""
                else:
                    row.status = "needs_review"
                    row.conflict_reason = _AMBIGUOUS_MATCH_REASON
            else:
                row.status = "conflict"
                row.conflict_reason = "same source identity or account changed before apply"
            continue
        if canonical and not conversion:
            row.status = "needs_review"
            row.conflict_reason = (
                f"conversion evidence to {state.base_currency_code} is required before apply"
            )
            continue
        receipt = {
            "version": 1,
            "batch_id": batch.id,
            "row_number": row.row_number,
            "source_sha256": batch.source_sha256,
            "stable_identity": row.stable_identity,
        }
        if canonical:
            if row.status == "pending":
                claimed = (
                    db.query(FinanceImportRow)
                    .filter_by(id=row.id, status="pending", created_transaction_id="")
                    .update(
                        {
                            FinanceImportRow.status: "applying",
                            FinanceImportRow.created_transaction_id: source_id,
                        },
                        synchronize_session=False,
                    )
                )
                if claimed != 1:
                    db.rollback()
                    continue
                batch.status = "applying"
                db.commit()
                db.refresh(row)
            transaction = actual_finance.create_transaction(
                db,
                {
                    "account_id": batch.account_id,
                    "date": parsed["date"],
                    "amount": conversion[0],
                    "payee": parsed["payee"],
                    "notes": f"imported from {batch.source_name}",
                },
                source_id=source_id,
                import_identity=row.stable_identity,
                evidence=conversion[1],
                commit_link=False,
                reimport_deleted=_owner_approved_deleted_reimport(batch, row),
            )
            row.created_transaction_id = source_id
            actual_by_identity[row.stable_identity] = transaction
            row.status = "applied"
            continue
        transaction = Transaction(
            account_id=batch.account_id,
            date=parsed["date"],
            amount=_legacy_exact_float_amount(parsed["amount_text"]),
            payee=parsed["payee"],
            notes=f"imported from {batch.source_name}",
            import_identity=row.stable_identity,
            import_batch_id=batch.id,
            import_source=f"finance_import:{batch.profile}",
            import_row_number=row.row_number,
            import_receipt_json=json.dumps(receipt, sort_keys=True),
        )
        db.add(transaction)
        finance_currency.prepare_transaction(
            db,
            transaction,
            source=f"finance_import:{batch.profile}",
            original_amount=parsed["amount_text"],
            original_currency_code=parsed["currency_code"],
            base_amount=parsed["amount_text"],
            base_currency_code=parsed["currency_code"],
            rate="1",
            source_hash=batch.source_sha256,
        )
        db.flush()
        row.created_transaction_id = transaction.id
        row.status = "applied"
    _update_batch_counts(batch, rows)
    still_reviewable = any(
        row.status in {"pending", "needs_review", "applying", "conflict"} for row in rows
    )
    finished = bool(rows) and not still_reviewable
    batch.status = "applied" if finished else "preview"
    batch.applied_at = datetime.now(UTC) if finished else None
    db.commit()
    return _batch_payload(db, batch)


@router.post("/{batch_id}/undo", dependencies=[Depends(require_recent_owner)])
def undo_batch(batch_id: str, db: DbSession = Depends(get_db)):
    with _IMPORT_APPLY_LOCK, actual_finance.AUTHORITY_LOCK:
        return _undo_batch_locked(batch_id, db)


def _undo_batch_locked(batch_id: str, db: DbSession):
    batch = db.get(FinanceImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "import receipt not found")
    rows = (
        db.query(FinanceImportRow)
        .filter_by(batch_id=batch.id)
        .order_by(FinanceImportRow.row_number)
        .all()
    )
    if batch.status == "undone":
        return _batch_payload(db, batch)
    partial = batch.status != "applied" and any(row.status == "applied" for row in rows)
    unresolved_claim = any(
        row.status == "applying" or (row.status == "conflict" and bool(row.created_transaction_id))
        for row in rows
    )
    if batch.status != "applied" and (not partial or unresolved_claim):
        raise HTTPException(
            409,
            "only an applied import or a recovered partial import can be undone",
        )
    current_backend = "actual" if actual_finance.is_canonical(db) else "alles"
    canonical = _receipt_backend(batch, rows, current_backend) == "actual"
    if canonical:
        # Validate the complete Actual receipt before issuing its first deletion.
        # A changed imported transaction is owner data, just like a changed
        # legacy row, and an interrupted earlier undo may already have removed it.
        current = actual_finance.transactions(db)
        current_by_id = {str(transaction.get("id") or ""): transaction for transaction in current}
        if len(current_by_id) != len(current):
            raise HTTPException(409, "import receipt transaction ownership is ambiguous")
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            raise HTTPException(409, "canonical Finance state is unavailable")
        for row in rows:
            if row.status != "applied" or not row.created_transaction_id:
                continue
            source_id = f"finance-import:{batch.id}:{row.row_number}"
            if row.created_transaction_id != source_id:
                raise HTTPException(409, "import receipt transaction ownership is invalid")
            transaction = current_by_id.get(source_id)
            if transaction is None:
                continue
            try:
                accepted = _owner_accepted_replacement(batch, row)
                if accepted is not None:
                    unchanged = bool(
                        transaction.get("import_identity") == row.stable_identity
                        and transaction.get("import_batch_id") == batch.id
                        and transaction.get("import_source") == f"finance_import:{batch.profile}"
                        and transaction.get("account_id") == accepted.get("account_id")
                        and transaction.get("date") == accepted.get("date")
                        and finance_currency.decimal_text(transaction.get("amount"))
                        == finance_currency.decimal_text(accepted.get("amount"))
                        and transaction.get("payee", "") == accepted.get("payee", "")
                        and transaction.get("category", "") == accepted.get("category", "")
                        and transaction.get("notes", "") == accepted.get("notes", "")
                        and bool(transaction.get("cleared")) == bool(accepted.get("cleared"))
                    )
                else:
                    parsed = json.loads(row.parsed_json or "{}")
                    conversion = _conversion_evidence(row, parsed, batch, state)
                    unchanged = bool(
                        conversion
                        and transaction.get("import_identity") == row.stable_identity
                        and transaction.get("import_batch_id") == batch.id
                        and transaction.get("import_source") == f"finance_import:{batch.profile}"
                        and transaction.get("notes") == f"imported from {batch.source_name}"
                        and transaction.get("category", "") == ""
                        and not bool(transaction.get("cleared"))
                        and _same_actual(
                            transaction,
                            parsed,
                            batch.account_id,
                            expected_base_amount=conversion[0],
                        )
                    )
            except (InvalidOperation, KeyError, TypeError, ValueError):
                unchanged = False
            if not unchanged:
                raise HTTPException(
                    409,
                    "an imported transaction changed after apply; undo was not performed",
                )
    else:
        # Validate the whole receipt before deleting its first row. An imported
        # transaction becomes owner data as soon as any editable field changes.
        for row in rows:
            if row.status != "applied" or not row.created_transaction_id:
                continue
            transaction = db.get(Transaction, row.created_transaction_id)
            if transaction is None:
                continue  # an interrupted earlier undo already removed it
            parsed = json.loads(row.parsed_json or "{}")
            unchanged = (
                transaction.import_batch_id == batch.id
                and transaction.import_identity == row.stable_identity
                and transaction.import_source == f"finance_import:{batch.profile}"
                and transaction.import_row_number == row.row_number
                and transaction.notes == f"imported from {batch.source_name}"
                and (transaction.category or "") == ""
                and not bool(transaction.cleared)
                and _same(transaction, parsed, batch.account_id)
            )
            if not unchanged:
                raise HTTPException(
                    409,
                    "an imported transaction changed after apply; undo was not performed",
                )
    for row in rows:
        if row.status != "applied" or not row.created_transaction_id:
            continue
        if canonical:
            source_id = f"finance-import:{batch.id}:{row.row_number}"
            if row.created_transaction_id != source_id:
                raise HTTPException(409, "import receipt transaction ownership is invalid")
            # The idempotent deletion intent is the recovery mechanism. Call it
            # even if the current projection no longer shows the external row:
            # a prior interrupted delete may already have removed it from Actual.
            actual_finance.delete_transaction(db, source_id)
            row.status = "undone"
            continue
        transaction = db.get(Transaction, row.created_transaction_id)
        if transaction:
            db.delete(transaction)
        row.status = "undone"
    for row in rows:
        if row.status in {"pending", "needs_review", "conflict"}:
            row.status = "undone"
            row.conflict_reason = ""
    db.flush()
    _update_batch_counts(batch, rows)
    batch.status = "undone"
    batch.undone_at = datetime.now(UTC)
    db.commit()
    return _batch_payload(db, batch)
