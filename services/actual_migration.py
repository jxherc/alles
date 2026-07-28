"""Reversible Alles-to-Actual staging, parity, cutover, and rollback gate."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session

from core.database import (
    Account,
    ActualEntityLink,
    ActualMigrationRun,
    Budget,
    BudgetAssignment,
    FinanceLedgerState,
    MoneyFxEvidence,
    RecurringTxn,
    SubPayment,
    Subscription,
    Transaction,
    TxnSplit,
)
from services import actual_finance, finance_currency, managed_actual


class ActualMigrationError(RuntimeError):
    pass


def _minor(value, label: str) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ActualMigrationError(f"{label} is not an exact decimal") from exc
    scaled = amount * 100
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        raise ActualMigrationError(f"{label} has precision Actual cannot preserve")
    minor = int(scaled)
    if abs(minor) > actual_finance.MAX_CENT_SAFE_MINOR:
        raise ActualMigrationError(f"{label} is outside Actual's exact numeric range")
    return minor


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def snapshot_sha256(snapshot: dict) -> str:
    return hashlib.sha256(_canonical(snapshot).encode()).hexdigest()


def _stable_actual(value):
    if isinstance(value, dict):
        return {key: _stable_actual(item) for key, item in value.items()}
    if isinstance(value, list):
        normalized = [_stable_actual(item) for item in value]
        return sorted(normalized, key=_canonical)
    return value


def actual_checkpoint_sha256(actual: dict) -> str:
    checkpoint = deepcopy(actual)
    if isinstance(checkpoint, dict):
        for schedule in checkpoint.get("schedules") or []:
            if isinstance(schedule, dict):
                # Actual computes this occurrence from the durable schedule rule
                # and today's date. Time passing is not a canonical ledger edit.
                schedule.pop("next_date", None)
    stable = _stable_actual(checkpoint)
    return hashlib.sha256(_canonical(stable).encode()).hexdigest()


def link_checkpoint_sha256(db: Session, run_id: str) -> str:
    """Hash the SQL sidecars that canonical Actual alone cannot preserve."""
    rows = (
        db.query(ActualEntityLink)
        .filter_by(run_id=run_id)
        .order_by(
            ActualEntityLink.entity_kind,
            ActualEntityLink.source_id,
            ActualEntityLink.actual_id,
        )
        .all()
    )
    payload = [
        {
            "kind": row.entity_kind,
            "source_id": row.source_id,
            "actual_id": row.actual_id,
            "metadata_json": row.metadata_json or "{}",
        }
        for row in rows
    ]
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def _state(db: Session) -> FinanceLedgerState:
    state = db.get(FinanceLedgerState, "primary")
    if state is None:
        state = FinanceLedgerState(id="primary", mode="alles", base_currency_code="CAD")
        db.add(state)
        db.flush()
    return state


def state_payload(db: Session) -> dict:
    state = _state(db)
    run = db.get(ActualMigrationRun, state.active_run_id) if state.active_run_id else None
    return {
        "mode": state.mode,
        "base_currency_code": state.base_currency_code,
        "active_run_id": state.active_run_id,
        "actual_budget_id": state.actual_budget_id,
        "actual_sync_id": state.actual_sync_id,
        "legacy_read_only": bool(state.legacy_read_only),
        "cutover_at": state.cutover_at.isoformat() if state.cutover_at else None,
        "rollback_at": state.rollback_at.isoformat() if state.rollback_at else None,
        "run": run_payload(db, run) if run else None,
    }


def run_payload(db: Session, run: ActualMigrationRun | None) -> dict | None:
    if run is None:
        return None
    links = db.query(ActualEntityLink).filter_by(run_id=run.id).count()
    return {
        "id": run.id,
        "status": run.status,
        "base_currency_code": run.base_currency_code,
        "snapshot_sha256": run.snapshot_sha256,
        "actual_budget_id": run.actual_budget_id,
        "actual_sync_id": run.actual_sync_id,
        "report": json.loads(run.report_json or "{}"),
        "error": run.error,
        "links": links,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "verified_at": run.verified_at.isoformat() if run.verified_at else None,
    }


def _currency(value: str) -> str:
    code = finance_currency.currency_code(value)
    if code == "XXX":
        raise ActualMigrationError("every Finance value needs an explicit reviewed currency code")
    return code


def _reviewed_conversion_evidence(
    label: str,
    *,
    original_amount_text,
    original_currency_code,
    base_amount_text,
    base_currency_code,
    rate_text,
    rate_date,
    source,
    expected_base: str,
) -> tuple[str, str]:
    original_currency = _currency(original_currency_code)
    base_currency = _currency(base_currency_code)
    if base_currency != expected_base:
        raise ActualMigrationError(f"{label} has no base amount evidence in {expected_base}")
    if not str(rate_text or "").strip() or not str(source or "").strip():
        raise ActualMigrationError(f"{label} has incomplete conversion evidence")
    base_minor = _minor(base_amount_text, f"{label} base amount")
    try:
        rate = Decimal(str(rate_text))
        original = Decimal(str(original_amount_text))
    except (InvalidOperation, ValueError) as exc:
        raise ActualMigrationError(f"{label} has invalid conversion evidence") from exc
    if (
        not rate.is_finite()
        or rate <= 0
        or len(rate.as_tuple().digits) > 28
        or not -18 <= rate.adjusted() <= 18
    ):
        raise ActualMigrationError(f"{label} has invalid conversion evidence")
    if (
        not original.is_finite()
        or len(original.as_tuple().digits) > 28
        or not -18 <= original.adjusted() <= 18
    ):
        raise ActualMigrationError(f"{label} has invalid conversion evidence")
    if original_currency == base_currency:
        original_minor = _minor(original_amount_text, f"{label} original amount")
        if rate != 1 or original_minor != base_minor:
            raise ActualMigrationError(f"{label} has contradictory identity conversion evidence")
    else:
        try:
            date.fromisoformat(str(rate_date or ""))
        except ValueError as exc:
            raise ActualMigrationError(f"{label} has incomplete conversion evidence") from exc
        cents = Decimal("0.01")
        recorded_base = Decimal(str(base_amount_text))
        try:
            expected_base_amount = (original * rate).quantize(cents, rounding=ROUND_HALF_EVEN)
        except (InvalidOperation, ValueError, OverflowError) as exc:
            raise ActualMigrationError(f"{label} has invalid conversion evidence") from exc
        if recorded_base != expected_base_amount:
            raise ActualMigrationError(f"{label} has contradictory conversion evidence")
    return original_currency, base_currency


def build_snapshot(
    db: Session,
    *,
    base_currency_code: str = "CAD",
    today: date | None = None,
    migration_run_id: str = "preview",
) -> dict:
    base = _currency(base_currency_code)
    today = today or date.today()
    migration_scope = str(migration_run_id or "preview").strip() or "preview"
    split = db.query(TxnSplit.txn_id).order_by(TxnSplit.txn_id).first()
    if split:
        raise ActualMigrationError(
            f"transaction {split[0]} has legacy splits; merge or remove them before staging Actual"
        )
    evidence = {row.transaction_id: row for row in db.query(MoneyFxEvidence).all()}
    accounts = []
    account_currency_codes = {}
    for row in db.query(Account).order_by(Account.id).all():
        original_currency, _base_currency = _reviewed_conversion_evidence(
            f"account {row.id}",
            original_amount_text=row.original_opening_text,
            original_currency_code=row.currency_code or row.currency,
            base_amount_text=row.base_opening_text,
            base_currency_code=row.base_currency_code,
            rate_text=row.opening_fx_rate_text,
            rate_date=row.opening_fx_rate_date,
            source=row.opening_fx_source,
            expected_base=base,
        )
        account_currency_codes[row.id] = original_currency
        accounts.append(
            {
                "id": row.id,
                "name": row.name,
                "kind": row.kind,
                "archived": bool(row.archived),
                "opening_minor": _minor(row.base_opening_text, f"account {row.id} opening balance"),
                "evidence": {
                    "original_amount_text": row.original_opening_text,
                    "original_currency_code": original_currency,
                    "base_amount_text": row.base_opening_text,
                    "base_currency_code": base,
                    "rate_text": row.opening_fx_rate_text,
                    "rate_date": row.opening_fx_rate_date,
                    "source": row.opening_fx_source,
                    "account_kind": row.kind or "checking",
                    "color": row.color or "accent",
                    "low_balance": row.low_balance or 0.0,
                },
            }
        )
    transactions = []
    transfers = defaultdict(list)
    for row in db.query(Transaction).order_by(Transaction.id).all():
        proof = evidence.get(row.id)
        if proof is None:
            raise ActualMigrationError(f"transaction {row.id} has no currency evidence")
        if (
            row.original_amount_text != proof.original_amount_text
            or row.original_currency_code != proof.original_currency_code
            or row.base_amount_text != proof.base_amount_text
            or row.base_currency_code != proof.base_currency_code
        ):
            raise ActualMigrationError(
                f"transaction {row.id} columns disagree with its currency evidence"
            )
        _reviewed_conversion_evidence(
            f"transaction {row.id}",
            original_amount_text=proof.original_amount_text,
            original_currency_code=proof.original_currency_code,
            base_amount_text=proof.base_amount_text,
            base_currency_code=proof.base_currency_code,
            rate_text=proof.rate_text,
            rate_date=proof.rate_date,
            source=proof.source,
            expected_base=base,
        )
        item = {
            "id": row.id,
            "account_id": row.account_id,
            "date": row.date,
            "amount_minor": _minor(proof.base_amount_text, f"transaction {row.id}"),
            "category": row.category or "",
            "payee": row.payee or "",
            "notes": row.notes or "",
            "cleared": bool(row.cleared),
            "transfer_id": row.transfer_id or "",
            # Actual remembers deleted imported IDs. A migration-attempt identity
            # must therefore never be reused by a later stage/rollback/restage.
            "import_identity": f"alles:migration:{migration_scope}:{row.id}",
            "evidence": {
                "original_amount_text": proof.original_amount_text,
                "original_currency_code": _currency(proof.original_currency_code),
                "base_amount_text": proof.base_amount_text,
                "base_currency_code": base,
                "rate_text": proof.rate_text,
                "rate_date": proof.rate_date,
                "source": proof.source,
                "source_hash": proof.source_hash,
                "tags": row.tags or "",
                "receipt_id": row.receipt_id or "",
                "import_batch_id": row.import_batch_id or "",
                "import_source": row.import_source or "",
                "import_row_number": row.import_row_number or 0,
                "import_receipt_json": row.import_receipt_json or "{}",
                "migration_source_import_identity": row.import_identity or "",
                "migration_source_account_id": row.account_id or "",
                "migration_source_date": row.date or "",
                "migration_source_category": row.category or "",
                "migration_source_payee": row.payee or "",
                "migration_source_notes": row.notes or "",
                "migration_source_cleared": bool(row.cleared),
                "migration_source_transfer_id": row.transfer_id or "",
            },
        }
        transactions.append(item)
        if row.transfer_id:
            transfers[row.transfer_id].append(item)
    transfer_pairs = []
    for transfer_id, rows in sorted(transfers.items()):
        if len(rows) != 2 or rows[0]["account_id"] == rows[1]["account_id"]:
            raise ActualMigrationError(
                f"transfer {transfer_id} is not one complete two-account pair"
            )
        if (
            rows[0]["amount_minor"] == 0
            or rows[1]["amount_minor"] == 0
            or rows[0]["amount_minor"] + rows[1]["amount_minor"] != 0
        ):
            raise ActualMigrationError(
                f"transfer {transfer_id} does not have equal and opposite base amounts"
            )
        transfer_pairs.append({"id": transfer_id, "left": rows[0], "right": rows[1]})

    # Legacy Finance has no category or payee entity tables: these values are
    # deliberately plain display strings. Actual receives the same unique name
    # set in one Alles-managed category group, so no source identity is merged.
    category_names = sorted(
        {
            value
            for value in [
                *(row["category"] for row in transactions),
                *(row.category for row in db.query(Budget).all()),
                *(row.category for row in db.query(BudgetAssignment).all()),
                *(row.category for row in db.query(RecurringTxn).all()),
                *(row.category for row in db.query(Subscription).all()),
            ]
            if value
        }
    )
    payee_names = sorted(
        {
            value
            for value in [
                *(row["payee"] for row in transactions),
                *(row.payee for row in db.query(RecurringTxn).all()),
                *(row.name for row in db.query(Subscription).all()),
            ]
            if value
        }
    )

    assignments = []
    explicit_keys = set()
    for row in db.query(BudgetAssignment).order_by(BudgetAssignment.id).all():
        explicit_keys.add((row.month, row.category))
        assignments.append(
            {
                "id": f"assignment:{row.id}",
                "category": row.category,
                "month": row.month,
                "amount_minor": _minor(row.assigned, f"budget assignment {row.id}"),
                "metadata": {"source_kind": "assignment", "source_id": row.id},
            }
        )
    sidecar_links = []
    current_month = today.strftime("%Y-%m")
    for row in db.query(Budget).order_by(Budget.id).all():
        if (row.tag or "").strip():
            sidecar_links.append(
                {
                    "kind": "tag_budget",
                    "source_id": row.id,
                    "actual_id": f"sidecar:tag_budget:{row.id}",
                    "metadata": {
                        "tag": row.tag.strip().lower(),
                        "limit_minor": _minor(row.limit_amt, f"tag budget {row.id}"),
                    },
                }
            )
            continue
        limit_minor = _minor(row.limit_amt, f"budget limit {row.id}")
        managed_month = "" if (current_month, row.category) in explicit_keys else current_month
        sidecar_links.append(
            {
                "kind": "budget_limit",
                "source_id": row.id,
                "actual_id": f"sidecar:budget_limit:{row.id}",
                "metadata": {
                    "category": row.category,
                    "limit_minor": limit_minor,
                    "managed_month": managed_month,
                    "source": "legacy_persistent_cap",
                },
            }
        )
        if managed_month:
            assignments.append(
                {
                    "id": f"limit:{row.id}",
                    "category": row.category,
                    "month": current_month,
                    "amount_minor": limit_minor,
                    "metadata": {"source_kind": "legacy_monthly_limit", "source_id": row.id},
                }
            )

    schedules = []
    for row in db.query(RecurringTxn).order_by(RecurringTxn.id).all():
        if row.account_id and account_currency_codes.get(row.account_id) != base:
            raise ActualMigrationError(
                f"recurring transaction {row.id} is denominated outside the canonical base "
                f"currency {base}; review and convert it before staging"
            )
        item = {
            "kind": "recurring",
            "id": row.id,
            "name": f"Alles recurring: {row.payee or row.category or row.id[:8]} [{row.id[:8]}]",
            "account_id": row.account_id,
            "payee": row.payee or row.category,
            "amount_minor": _minor(row.amount, f"recurring transaction {row.id}"),
            "next_date": row.next_date,
            "anchor_day": row.anchor_day,
            "cycle": row.cycle,
            "cycle_days": row.cycle_days,
            "active": bool(row.active),
            "posts_transaction": bool(row.account_id),
            "metadata": {
                "category": row.category,
                "notes": row.notes,
                "last_posted": row.last_posted,
            },
        }
        _schedule_date(item)
        schedules.append(item)
    subscriptions = []
    for row in db.query(Subscription).order_by(Subscription.id).all():
        original_currency, _base_currency = _reviewed_conversion_evidence(
            f"subscription {row.id}",
            original_amount_text=row.original_price_text,
            original_currency_code=row.original_currency_code,
            base_amount_text=row.base_price_text,
            base_currency_code=row.base_currency_code,
            rate_text=row.fx_rate_text,
            rate_date=row.fx_rate_date,
            source=row.fx_source,
            expected_base=base,
        )
        item = {
            "kind": "subscription",
            "id": row.id,
            "name": f"Alles subscription: {row.name} [{row.id[:8]}]",
            "account_id": row.account_id,
            "payee": row.name,
            "amount_minor": -abs(_minor(row.base_price_text, f"subscription {row.id}")),
            "next_date": row.next_due,
            "cycle": row.cycle,
            "cycle_days": row.cycle_days,
            "active": bool(row.active),
            "posts_transaction": bool(row.account_id),
            "metadata": {
                "category": row.category,
                "original_price_text": row.original_price_text,
                "original_currency_code": original_currency,
                "base_price_text": row.base_price_text,
                "base_currency_code": base,
                "rate_text": row.fx_rate_text,
                "rate_date": row.fx_rate_date,
                "source": row.fx_source,
                "url": row.url,
                "cancel_url": row.cancel_url,
            },
        }
        _schedule_date(item)
        schedules.append(item)
        subscriptions.append(
            {"id": row.id, "schedule_source_id": row.id, "metadata": item["metadata"]}
        )
    payments = []
    subscription_ids = {row["id"] for row in subscriptions}
    transaction_ids = {row["id"] for row in transactions}
    for row in db.query(SubPayment).order_by(SubPayment.id).all():
        if row.sub_id not in subscription_ids:
            raise ActualMigrationError(
                f"subscription payment {row.id} references a missing subscription"
            )
        if row.txn_id and row.txn_id not in transaction_ids:
            raise ActualMigrationError(
                f"subscription payment {row.id} references a missing transaction"
            )
        original_currency, _base_currency = _reviewed_conversion_evidence(
            f"subscription payment {row.id}",
            original_amount_text=row.original_amount_text,
            original_currency_code=row.original_currency_code,
            base_amount_text=row.base_amount_text,
            base_currency_code=row.base_currency_code,
            rate_text=row.fx_rate_text,
            rate_date=row.fx_rate_date,
            source=row.fx_source,
            expected_base=base,
        )
        payment = {
            "id": row.id,
            "subscription_id": row.sub_id,
            "transaction_id": row.txn_id,
            "date": row.date,
            "base_amount_minor": _minor(row.base_amount_text, f"subscription payment {row.id}"),
            "original_amount_text": row.original_amount_text,
            "original_currency_code": original_currency,
            "rate_text": row.fx_rate_text,
            "rate_date": row.fx_rate_date,
            "source": row.fx_source,
        }
        payments.append(payment)
        sidecar_links.append(
            {
                "kind": "subscription_payment",
                "source_id": row.id,
                "actual_id": f"sidecar:subscription_payment:{row.id}",
                "metadata": payment,
            }
        )

    return {
        "version": 3,
        "base_currency_code": base,
        "budget_effective_month": current_month,
        "accounts": accounts,
        "transactions": transactions,
        "transfer_pairs": transfer_pairs,
        "category_names": category_names,
        "payee_names": payee_names,
        "budget_assignments": assignments,
        "sidecar_links": sidecar_links,
        "schedules": schedules,
        "subscriptions": subscriptions,
        "subscription_payments": payments,
    }


def _check(name: str, expected, actual) -> dict:
    return {"name": name, "expected": expected, "actual": actual, "pass": expected == actual}


def _date_key(value) -> str:
    raw = str(value or "").replace("-", "")
    return raw if len(raw) == 8 and raw.isdigit() else str(value or "")


def _schedule_date(row: dict) -> dict:
    cycle = str(row.get("cycle") or "").strip().lower()
    supported = {"daily", "weekly", "monthly", "quarterly", "yearly", "custom"}
    if cycle not in supported:
        raise ActualMigrationError(
            f"schedule recurrence {cycle or '(empty)'} cannot be represented exactly in Actual"
        )
    frequency = cycle
    interval = 1
    if cycle == "quarterly":
        frequency, interval = "monthly", 3
    elif cycle == "custom":
        raw_interval = row.get("cycle_days")
        if isinstance(raw_interval, bool):
            raise ActualMigrationError(
                "custom schedule recurrence interval cannot be represented exactly in Actual"
            )
        try:
            decimal_interval = Decimal(str(raw_interval))
        except (InvalidOperation, ValueError):
            raise ActualMigrationError(
                "custom schedule recurrence interval cannot be represented exactly in Actual"
            ) from None
        if (
            not decimal_interval.is_finite()
            or decimal_interval != decimal_interval.to_integral_value()
            or decimal_interval < 1
            or decimal_interval > actual_finance.MAX_CUSTOM_RECURRENCE_DAYS
        ):
            raise ActualMigrationError(
                "custom schedule recurrence interval cannot be represented exactly in Actual"
            )
        frequency, interval = "daily", int(decimal_interval)
    rule = {
        "start": _date_key(row.get("next_date")),
        "frequency": frequency,
        "interval": interval,
    }
    anchor = row.get("anchor_day")
    if cycle in {"monthly", "quarterly"} and anchor is not None:
        try:
            anchor = int(anchor)
        except (TypeError, ValueError):
            anchor = 0
        if anchor in {29, 30}:
            raise ActualMigrationError(
                f"schedule day {anchor} cannot be represented exactly in Actual across short months"
            )
        if not 1 <= anchor <= 31:
            raise ActualMigrationError(
                "schedule anchor day cannot be represented exactly in Actual"
            )
        rule["patterns"] = [{"type": "day", "value": -1 if anchor == 31 else anchor}]
    if cycle == "yearly" and int(row.get("anchor_day") or 0) == 29:
        try:
            starts_on_february = date.fromisoformat(str(row.get("next_date") or "")[:10]).month == 2
        except ValueError:
            starts_on_february = False
        if starts_on_february:
            raise ActualMigrationError(
                "yearly February 29 recurrence cannot be represented exactly in Actual"
            )
    return rule


def _normalized_schedule_date(value) -> dict:
    if not isinstance(value, dict):
        return {"start": _date_key(value), "frequency": "", "interval": 0}
    try:
        interval = int(value.get("interval") or 1)
    except (TypeError, ValueError):
        interval = 0
    patterns = []
    for item in value.get("patterns") or []:
        if isinstance(item, dict):
            patterns.append({"type": str(item.get("type") or ""), "value": item.get("value")})
    return {
        "start": _date_key(value.get("start")),
        "frequency": str(value.get("frequency") or ""),
        "interval": interval,
        **({"patterns": patterns} if patterns else {}),
    }


def _nullable_id(value):
    return None if value in {None, "", "null", "undefined"} else value


def _link_bijection(rows: list[dict], expected_sources, actual_ids) -> bool:
    sources = [str(row.get("source_id") or "") for row in rows]
    linked_ids = [str(row.get("actual_id") or "") for row in rows]
    expected = [str(value or "") for value in expected_sources]
    canonical_ids = [str(value or "") for value in actual_ids]
    return bool(
        all(sources)
        and all(linked_ids)
        and len(sources) == len(set(sources)) == len(expected) == len(set(expected))
        and set(sources) == set(expected)
        and len(linked_ids) == len(set(linked_ids)) == len(canonical_ids) == len(set(canonical_ids))
        and set(linked_ids) == set(canonical_ids)
    ) or not (rows or expected or canonical_ids)


def reconcile(snapshot: dict, result: dict) -> dict:
    actual = result.get("actual") or {}
    links = result.get("links") or []
    link_by_kind = defaultdict(list)
    for row in links:
        link_by_kind[row["kind"]].append(row)
    account_link_rows = {row["source_id"]: row for row in link_by_kind["account"]}
    account_links = {source_id: row["actual_id"] for source_id, row in account_link_rows.items()}
    txn_link_rows = {row["source_id"]: row for row in link_by_kind["transaction"]}
    txn_links = {source_id: row["actual_id"] for source_id, row in txn_link_rows.items()}
    actual_account_rows = actual.get("accounts") or []
    actual_transaction_rows = actual.get("transactions") or []
    actual_accounts = {row["id"]: row for row in actual_account_rows}
    actual_txns = {row["id"]: row for row in actual_transaction_rows}
    actual_payee_rows = {row.get("id"): row for row in actual.get("payees") or []}
    transfer_target_accounts = {}
    for pair in snapshot["transfer_pairs"]:
        transfer_target_accounts[pair["left"]["id"]] = pair["right"]["account_id"]
        transfer_target_accounts[pair["right"]["id"]] = pair["left"]["account_id"]
    imported = {
        row.get("imported_id"): row for row in actual_txns.values() if row.get("imported_id")
    }
    account_identity_ok = _link_bijection(
        link_by_kind["account"],
        (row["id"] for row in snapshot["accounts"]),
        (row.get("id") for row in actual_account_rows),
    )
    canonical_transaction_rows = [
        row for row in actual_transaction_rows if not row.get("starting_balance_flag")
    ]
    expected_import_ids = [row["import_identity"] for row in snapshot["transactions"]]
    observed_import_ids = [str(row.get("imported_id") or "") for row in canonical_transaction_rows]
    transaction_identity_ok = _link_bijection(
        link_by_kind["transaction"],
        (row["id"] for row in snapshot["transactions"]),
        (row.get("id") for row in canonical_transaction_rows),
    ) and (
        all(expected_import_ids)
        and all(observed_import_ids)
        and len(expected_import_ids) == len(set(expected_import_ids))
        and len(observed_import_ids) == len(set(observed_import_ids))
        and set(expected_import_ids) == set(observed_import_ids)
    )
    expected_balances = defaultdict(int)
    for row in snapshot["accounts"]:
        expected_balances[row["id"]] += row["opening_minor"]
    for row in snapshot["transactions"]:
        expected_balances[row["account_id"]] += row["amount_minor"]
    actual_balances = {
        source_id: actual_accounts.get(actual_id, {}).get("balance")
        for source_id, actual_id in account_links.items()
    }
    transaction_fields_ok = 0
    for row in snapshot["transactions"]:
        link = txn_link_rows.get(row["id"], {})
        actual_row = actual_txns.get(link.get("actual_id", ""), {})
        # Actual's transfer representation intentionally has no category. The complete
        # source category remains in the immutable snapshot and transaction-link evidence,
        # while the mutual transfer ids prove the canonical semantic representation below.
        expected_actual_category = "" if row.get("transfer_id") else row["category"]
        if row.get("transfer_id"):
            payee = actual_payee_rows.get(actual_row.get("payee"), {})
            expected_target = account_links.get(transfer_target_accounts.get(row["id"], ""))
            payee_matches = bool(expected_target) and payee.get("transfer_acct") == expected_target
        else:
            payee_matches = (actual_row.get("payee_name") or "") == row["payee"]
        if (
            actual_row.get("account") == account_links.get(row["account_id"])
            and _date_key(actual_row.get("date")) == _date_key(row["date"])
            and actual_row.get("amount") == row["amount_minor"]
            and payee_matches
            and (actual_row.get("category_name") or "") == expected_actual_category
            and (actual_row.get("notes") or "") == row["notes"]
            and bool(actual_row.get("cleared")) == row["cleared"]
            and (actual_row.get("imported_id") or "") == row["import_identity"]
            and (link.get("metadata") or {}) == row["evidence"]
        ):
            transaction_fields_ok += 1
    account_metadata_ok = sum(
        1
        for row in snapshot["accounts"]
        if (account_link_rows.get(row["id"], {}).get("metadata") or {}) == row["evidence"]
    )
    account_state_ok = sum(
        1
        for row in snapshot["accounts"]
        if (
            (actual_accounts.get(account_links.get(row["id"], ""), {}).get("name") or "")
            == row["name"]
            and bool(actual_accounts.get(account_links.get(row["id"], ""), {}).get("offbudget"))
            == (row["kind"] == "investment")
            and bool(actual_accounts.get(account_links.get(row["id"], ""), {}).get("closed"))
            == bool(row["archived"])
        )
    )
    expected_txn_total = sum(row["amount_minor"] for row in snapshot["transactions"])
    actual_txn_total = sum(
        imported.get(row["import_identity"], {}).get("amount", 0)
        for row in snapshot["transactions"]
    )
    transfer_ok = 0
    expected_transfer_links = {}
    for pair in snapshot["transfer_pairs"]:
        left_id = txn_links.get(pair["left"]["id"], "")
        right_id = txn_links.get(pair["right"]["id"], "")
        expected_transfer_links[pair["id"]] = f"{left_id}:{right_id}"
        left = actual_txns.get(left_id, {})
        right = actual_txns.get(right_id, {})
        if left.get("transfer_id") == right.get("id") and right.get("transfer_id") == left.get(
            "id"
        ):
            transfer_ok += 1
    transfer_link_rows = link_by_kind["transfer"]
    transfer_link_map = {
        str(row.get("source_id") or ""): str(row.get("actual_id") or "")
        for row in transfer_link_rows
    }
    transfer_link_identity_ok = (
        len(transfer_link_rows) == len(transfer_link_map) == len(expected_transfer_links)
        and transfer_link_map == expected_transfer_links
        and len(set(transfer_link_map.values())) == len(transfer_link_map)
    )
    actual_category_rows = {
        str(row.get("id") or ""): row for row in actual.get("categories") or [] if row.get("id")
    }
    actual_categories = {row.get("name") for row in actual_category_rows.values()}
    actual_payees = {row.get("name") for row in actual_payee_rows.values()}
    payee_names_by_id = {row.get("id"): row.get("name") or "" for row in actual_payee_rows.values()}
    budget_values = {}
    for month in actual.get("budget_months") or []:
        for group in month.get("categoryGroups") or []:
            for category in group.get("categories") or []:
                budget_values[(month.get("month"), category.get("id"))] = category.get("budgeted")
    budget_ok = 0
    budget_links = link_by_kind["budget_assignment"]
    expected_budget = {row["id"]: row for row in snapshot["budget_assignments"]}
    budget_sources = [str(row.get("source_id") or "") for row in budget_links]
    budget_targets = [str(row.get("actual_id") or "") for row in budget_links]
    expected_budget_targets = [
        (str(row.get("month") or ""), str(row.get("category") or "").casefold())
        for row in snapshot["budget_assignments"]
    ]
    observed_budget_targets = []
    for target in budget_targets:
        month, separator, category_id = target.partition(":")
        category_name = str(actual_category_rows.get(category_id, {}).get("name") or "")
        observed_budget_targets.append((month if separator else "", category_name.casefold()))
    budget_link_identity_ok = bool(
        all(budget_sources)
        and all(budget_targets)
        and len(budget_sources)
        == len(set(budget_sources))
        == len(expected_budget)
        == len(snapshot["budget_assignments"])
        and set(budget_sources) == set(expected_budget)
        and len(budget_targets) == len(set(budget_targets))
        and len(expected_budget_targets) == len(set(expected_budget_targets))
        and len(observed_budget_targets) == len(set(observed_budget_targets))
        and set(observed_budget_targets) == set(expected_budget_targets)
    ) or not (budget_links or expected_budget)
    for link in budget_links:
        month, separator, category_id = str(link.get("actual_id") or "").partition(":")
        expected = expected_budget.get(link["source_id"])
        category = actual_category_rows.get(category_id, {})
        if (
            separator
            and expected
            and month == expected["month"]
            and str(category.get("name") or "") == expected["category"]
            and budget_values.get((month, category_id)) == expected["amount_minor"]
        ):
            budget_ok += 1
    schedule_map = {row.get("id"): row for row in actual.get("schedules") or []}
    schedule_link_rows = [
        {
            **row,
            "source_id": f"{row['kind']}:{row['source_id']}",
        }
        for kind in ("recurring", "subscription")
        for row in link_by_kind[kind]
    ]
    schedule_identity_ok = _link_bijection(
        schedule_link_rows,
        (f"{row['kind']}:{row['id']}" for row in snapshot["schedules"]),
        schedule_map,
    )
    schedule_ok = 0
    expected_schedules = {(row["kind"], row["id"]): row for row in snapshot["schedules"]}
    for kind in ("recurring", "subscription"):
        for link in link_by_kind[kind]:
            expected = expected_schedules.get((kind, link["source_id"]))
            actual_schedule = schedule_map.get(link["actual_id"])
            if (
                expected
                and actual_schedule
                and actual_schedule.get("amount") == expected["amount_minor"]
                and (actual_schedule.get("name") or "") == expected["name"]
                and _nullable_id(actual_schedule.get("account"))
                == _nullable_id(account_links.get(expected["account_id"]))
                and payee_names_by_id.get(actual_schedule.get("payee"), "")
                == (expected["payee"] or expected["name"])
                and _normalized_schedule_date(actual_schedule.get("date"))
                == _schedule_date(expected)
                and bool(actual_schedule.get("completed")) == (not expected["active"])
                and bool(actual_schedule.get("posts_transaction")) == expected["posts_transaction"]
                and (actual_schedule.get("amountOp") or "") == "is"
                and (link.get("metadata") or {}) == expected["metadata"]
            ):
                schedule_ok += 1
    evidence_links = sum(
        1
        for row in links
        if row["kind"] in {"account", "transaction", "subscription"} and row.get("metadata")
    )
    expected_evidence = (
        len(snapshot["accounts"]) + len(snapshot["transactions"]) + len(snapshot["subscriptions"])
    )
    payment_links = {row["source_id"]: row for row in link_by_kind["subscription_payment"]}
    subscription_payments_ok = sum(
        1
        for row in snapshot["subscription_payments"]
        if (payment_links.get(row["id"], {}).get("metadata") or {}) == row
    )
    sidecar_links = {
        (row["kind"], row["source_id"]): row
        for row in links
        if row["kind"].startswith("tag_")
        or row["kind"].startswith("budget_")
        or row["kind"] == "subscription_payment"
    }
    sidecar_evidence_ok = sum(
        1
        for row in snapshot.get("sidecar_links") or []
        if (sidecar_links.get((row["kind"], row["source_id"]), {}).get("metadata") or {})
        == row["metadata"]
    )
    expected_budget_limits = [
        row for row in snapshot.get("sidecar_links") or [] if row["kind"] == "budget_limit"
    ]
    budget_limit_binding_ok = sum(
        1
        for row in expected_budget_limits
        if (sidecar_links.get((row["kind"], row["source_id"]), {}).get("metadata") or {})
        == row["metadata"]
        and actual_category_rows.get(
            sidecar_links.get((row["kind"], row["source_id"]), {}).get("actual_id", ""),
            {},
        ).get("name")
        == row["metadata"]["category"]
    )
    checks = [
        _check("accounts", len(snapshot["accounts"]), len(account_links)),
        _check("account identity bijection", True, account_identity_ok),
        _check("transactions", len(snapshot["transactions"]), len(txn_links)),
        _check("transaction identity bijection", True, transaction_identity_ok),
        _check("account balances", dict(expected_balances), actual_balances),
        _check(
            "account name, kind, and archive state",
            len(snapshot["accounts"]),
            account_state_ok,
        ),
        _check(
            "account currency and display evidence",
            len(snapshot["accounts"]),
            account_metadata_ok,
        ),
        _check("transaction aggregate minor units", expected_txn_total, actual_txn_total),
        _check("transaction field parity", len(snapshot["transactions"]), transaction_fields_ok),
        _check("transfer pairs", len(snapshot["transfer_pairs"]), transfer_ok),
        _check("transfer link identity bijection", True, transfer_link_identity_ok),
        _check(
            "categories",
            sorted(snapshot["category_names"]),
            sorted(name for name in snapshot["category_names"] if name in actual_categories),
        ),
        _check(
            "payees",
            sorted(snapshot["payee_names"]),
            sorted(name for name in snapshot["payee_names"] if name in actual_payees),
        ),
        _check("budget assignments", len(snapshot["budget_assignments"]), budget_ok),
        _check("budget assignment identity bijection", True, budget_link_identity_ok),
        _check("schedules", len(snapshot["schedules"]), schedule_ok),
        _check("schedule identity bijection", True, schedule_identity_ok),
        _check("currency evidence links", expected_evidence, evidence_links),
        _check(
            "subscription links", len(snapshot["subscriptions"]), len(link_by_kind["subscription"])
        ),
        _check(
            "subscription payment evidence",
            len(snapshot["subscription_payments"]),
            subscription_payments_ok,
        ),
        _check(
            "sidecar evidence",
            len(snapshot.get("sidecar_links") or []),
            sidecar_evidence_ok,
        ),
        _check(
            "persistent budget cap bindings",
            len(expected_budget_limits),
            budget_limit_binding_ok,
        ),
    ]
    return {"pass": all(row["pass"] for row in checks), "checks": checks}


def _write_snapshot(run_id: str, snapshot: dict) -> Path:
    try:
        managed_actual._ensure_managed_data_directories()
    except managed_actual.ManagedActualError as exc:
        raise ActualMigrationError(str(exc)) from exc
    root = managed_actual.migration_exports_dir()
    if root.is_symlink() or not root.is_dir():
        raise ActualMigrationError("managed Actual migration export directory is unsafe")
    target = root / f"{run_id}.json"
    temp = root / f".{run_id}.{uuid.uuid4().hex}.partial"
    try:
        with temp.open("x", encoding="utf-8") as handle:
            handle.write(_canonical(snapshot))
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(0o600)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def _load_snapshot(run: ActualMigrationRun) -> dict:
    path = Path(run.snapshot_path)
    if not path.is_file() or path.is_symlink():
        raise ActualMigrationError("Actual migration snapshot is missing")
    try:
        snapshot = json.loads(path.read_text("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise ActualMigrationError("Actual migration snapshot is unreadable") from exc
    if snapshot_sha256(snapshot) != run.snapshot_sha256:
        raise ActualMigrationError("Actual migration snapshot hash changed")
    return snapshot


def _bind_sidecar_links(snapshot: dict, result: dict) -> list[dict]:
    """Return every SQL-only link, resolving only the budget-limit target identity."""
    categories: dict[str, list[str]] = defaultdict(list)
    for row in (result.get("actual") or {}).get("categories") or []:
        category_id = str(row.get("id") or "")
        name = str(row.get("name") or "")
        if category_id and name:
            categories[name.casefold()].append(category_id)
    bound = []
    for row in snapshot.get("sidecar_links") or []:
        item = {**row, "metadata": dict(row.get("metadata") or {})}
        if item["kind"] == "budget_limit":
            name = str(item["metadata"].get("category") or "").strip()
            matches = categories.get(name.casefold(), [])
            if len(matches) != 1:
                raise ActualMigrationError(
                    f"persistent budget cap category {name or '(blank)'} is not uniquely bound in Actual"
                )
            item["actual_id"] = matches[0]
        bound.append(item)
    return bound


def _delete_staged_budget(run: ActualMigrationRun, bridge_request) -> None:
    budget_id = str(run.actual_budget_id or "").strip()
    sync_id = str(run.actual_sync_id or "").strip()
    if not budget_id and not sync_id:
        raise ActualMigrationError("failed Actual staging run has no budget identity to clean up")
    result = bridge_request(
        {
            "command": "delete_staged_budget",
            "budget_id": budget_id,
            "sync_id": sync_id,
        },
        timeout=120,
    )
    if (
        result.get("verified_absent") is not True
        or (budget_id and result.get("budget_id") != budget_id)
        or (not budget_id and sync_id and result.get("sync_id") != sync_id)
    ):
        raise ActualMigrationError("Actual staged budget cleanup was not verified")


def _retry_required_stage_cleanup(db: Session, bridge_request) -> None:
    pending = (
        db.query(ActualMigrationRun)
        .filter(ActualMigrationRun.status.in_(("cleanup_required", "staging", "ready")))
        .order_by(ActualMigrationRun.created_at.asc())
        .all()
    )
    for run in pending:
        interrupted = run.status == "staging"
        verified_candidate = run.status == "ready"
        if interrupted:
            raise ActualMigrationError(
                "a previous Actual staging run may have completed without returning its result; "
                "manual reconciliation is required"
            )
        try:
            _delete_staged_budget(run, bridge_request)
        except Exception as exc:
            db.rollback()
            run = db.get(ActualMigrationRun, run.id)
            run.status = "cleanup_required"
            previous_error = str(run.error or "")[:420]
            run.error = (
                f"{previous_error}; interrupted staged Actual budget cleanup must be retried"
            )[:600]
            db.commit()
            raise ActualMigrationError(
                "a previous Actual staging budget still requires cleanup before another migration"
            ) from exc
        run.status = "superseded" if verified_candidate else "failed"
        previous_error = str(run.error or "")[:480]
        if verified_candidate:
            note = "previous verified Actual candidate cleanup verified before restaging"
        elif interrupted:
            note = "interrupted staged Actual budget cleanup verified"
        else:
            note = "staged Actual budget cleanup retry verified"
        run.error = f"{previous_error}; {note}"[:600]
        state = _state(db)
        if state.active_run_id == run.id:
            state.active_run_id = ""
            state.actual_budget_id = ""
            state.actual_sync_id = ""
        db.commit()


def _staged_budget_identity_from_error(exc: BaseException) -> dict:
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        details = getattr(current, "details", {})
        staged = details.get("staged_budget") if isinstance(details, dict) else None
        if isinstance(staged, dict):
            budget_id = str(staged.get("budget_id") or "").strip()
            sync_id = str(staged.get("sync_id") or "").strip()
            if budget_id or sync_id:
                return {"budget_id": budget_id, "sync_id": sync_id}
        current = current.__cause__ or current.__context__
    return {}


def _failure_could_have_staged_budget(exc: BaseException) -> bool:
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "staging_possible", None) is False:
            return False
        if getattr(current, "code", "") in {
            "actual_bridge_unavailable",
            "actual_bridge_invalid",
            "actual_bridge_too_large",
            "actual_stage_cleanup_verified",
        }:
            return False
        current = current.__cause__ or current.__context__
    return True


def _failure_code(exc: BaseException) -> str:
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = str(getattr(current, "code", "") or "")
        if code:
            return code
        current = current.__cause__ or current.__context__
    return ""


def stage(
    db: Session,
    *,
    base_currency_code: str = "CAD",
    bridge_request=managed_actual.bridge_request,
    today: date | None = None,
) -> dict:
    state = _state(db)
    if state.mode != "alles":
        raise ActualMigrationError("rollback to the Alles ledger before staging another migration")
    _retry_required_stage_cleanup(db, bridge_request)
    run_id = str(uuid.uuid4())
    snapshot = build_snapshot(
        db,
        base_currency_code=base_currency_code,
        today=today,
        migration_run_id=run_id,
    )
    path = _write_snapshot(run_id, snapshot)
    run = ActualMigrationRun(
        id=run_id,
        status="staging",
        base_currency_code=snapshot["base_currency_code"],
        snapshot_sha256=snapshot_sha256(snapshot),
        snapshot_path=str(path),
    )
    db.add(run)
    db.commit()
    result = None
    try:
        result = bridge_request(
            {
                "command": "migrate",
                "budget_name": f"Alles staged {run_id}",
                "operation_marker": f"Alles staged {run_id}",
                "replace_existing_staging": True,
                "snapshot": snapshot,
            },
            timeout=300,
        )
        run.actual_budget_id = str(result.get("budget_id") or "").strip()
        run.actual_sync_id = str(result.get("sync_id") or "").strip()
        if not run.actual_budget_id:
            raise ActualMigrationError("Actual staging did not return its budget identity")
        db.commit()
        result["links"] = [
            *(result.get("links") or []),
            *_bind_sidecar_links(snapshot, result),
        ]
        report = reconcile(snapshot, result)
        if not report["pass"]:
            raise ActualMigrationError("Actual staging parity check failed")
        run.report_json = _canonical({**report, "backup": None})
        run.status = "ready"
        run.verified_at = datetime.now(UTC)
        for link in result["links"]:
            db.add(
                ActualEntityLink(
                    run_id=run.id,
                    entity_kind=link["kind"],
                    source_id=link["source_id"],
                    actual_id=link["actual_id"],
                    metadata_json=_canonical(link.get("metadata") or {}),
                )
            )
        state.active_run_id = run.id
        state.base_currency_code = run.base_currency_code
        state.actual_budget_id = run.actual_budget_id
        state.actual_sync_id = run.actual_sync_id
        db.commit()
    except Exception as exc:
        db.rollback()
        failed = db.get(ActualMigrationRun, run_id)
        if result is not None:
            failed.actual_budget_id = str(result.get("budget_id") or "").strip()
            failed.actual_sync_id = str(result.get("sync_id") or "").strip()
        else:
            staged_identity = _staged_budget_identity_from_error(exc)
            failed.actual_budget_id = staged_identity.get("budget_id", "")
            failed.actual_sync_id = staged_identity.get("sync_id", "")
        cleanup_error = None
        failure_code = _failure_code(exc)
        reconciliation_required = failure_code == "actual_stage_reconciliation_required"
        cleanup_verified_by_bridge = failure_code == "actual_stage_cleanup_verified"
        if failed.actual_budget_id and not reconciliation_required:
            try:
                _delete_staged_budget(failed, bridge_request)
            except Exception as cleanup_exc:
                cleanup_error = cleanup_exc
        if reconciliation_required:
            failed.status = "staging"
            cleanup_note = "; existing staged budget requires manual reconciliation"
        elif cleanup_verified_by_bridge:
            failed.status = "failed"
            cleanup_note = "; staged Actual budget cleanup verified by the bridge"
        elif not failed.actual_budget_id and not _failure_could_have_staged_budget(exc):
            failed.status = "failed"
            cleanup_note = "; failure occurred before Actual staging could begin"
        elif not failed.actual_budget_id:
            failed.status = "staging"
            cleanup_note = "; staging result is indeterminate and manual reconciliation is required"
        elif cleanup_error is None:
            failed.status = "failed"
            cleanup_note = "; staged Actual budget cleanup verified"
        else:
            failed.status = "cleanup_required"
            cleanup_note = "; automatic staged-budget cleanup failed and must be retried"
        failed.error = f"{exc}{cleanup_note}"[:600]
        db.commit()
        if cleanup_error is not None:
            raise ActualMigrationError(f"{exc}{cleanup_note}") from cleanup_error
        raise
    return run_payload(db, run)


def _saved_result(db: Session, run: ActualMigrationRun, actual: dict) -> dict:
    links = db.query(ActualEntityLink).filter_by(run_id=run.id).all()
    return {
        "actual": actual,
        "links": [
            {
                "kind": row.entity_kind,
                "source_id": row.source_id,
                "actual_id": row.actual_id,
                "metadata": json.loads(row.metadata_json or "{}"),
            }
            for row in links
        ],
    }


def verify_run_readback(db: Session, run_id: str, actual: dict) -> dict:
    run = db.get(ActualMigrationRun, run_id)
    if not run:
        raise ActualMigrationError("Actual migration run was not found")
    snapshot = _load_snapshot(run)
    report = reconcile(snapshot, _saved_result(db, run, actual))
    return {"ok": report["pass"], "report": report}


def validate_fresh_readback(actual: dict) -> dict:
    required_lists = (
        "accounts",
        "transactions",
        "payees",
        "categories",
        "category_groups",
        "schedules",
        "budget_months",
    )
    if not isinstance(actual, dict) or any(
        not isinstance(actual.get(key), list) for key in required_lists
    ):
        return {"ok": False, "error": "restored Actual budget has an invalid read-back shape"}
    accounts = {row.get("id"): row for row in actual["accounts"] if row.get("id")}
    transactions = {row.get("id"): row for row in actual["transactions"] if row.get("id")}
    if len(accounts) != len(actual["accounts"]) or len(transactions) != len(actual["transactions"]):
        return {"ok": False, "error": "restored Actual budget has duplicate or missing ids"}
    for row in transactions.values():
        if row.get("account") not in accounts:
            return {"ok": False, "error": "restored transaction references a missing account"}
        partner_id = row.get("transfer_id")
        if partner_id:
            partner = transactions.get(partner_id)
            if not partner or partner.get("transfer_id") != row.get("id"):
                return {"ok": False, "error": "restored transfer linkage is incomplete"}
    return {
        "ok": True,
        "accounts": len(accounts),
        "transactions": len(transactions),
        "checkpoint_sha256": actual_checkpoint_sha256(actual),
    }


def _restored_account_matches(row: dict, expected: dict, restored_opening_minor) -> bool:
    try:
        opening_matches = int(restored_opening_minor) == int(expected["opening_minor"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        opening_matches
        and str(row.get("name") or "") == str(expected.get("name") or "")
        and bool(row.get("offbudget")) == bool(expected.get("offbudget"))
        and bool(row.get("closed")) == bool(expected.get("closed"))
    )


def _restored_transaction_matches(row: dict, expected: dict) -> bool:
    for key, value in expected.items():
        if key == "date":
            if _date_key(row.get(key)) != _date_key(value):
                return False
        elif key == "amount":
            try:
                if int(row.get(key) or 0) != int(value):
                    return False
            except (TypeError, ValueError):
                return False
        elif key == "cleared":
            if bool(row.get(key)) != bool(value):
                return False
        elif key == "payee_name":
            if str(row.get("payee_name") or row.get("imported_payee") or "") != str(value or ""):
                return False
        elif key in {"account", "category_name", "notes"}:
            if str(row.get(key) or "") != str(value or ""):
                return False
    return True


def _restored_schedule_matches(
    row: dict,
    expected: dict,
    *,
    account_actual_ids: dict[str, str],
    payee_names: dict[str, str],
) -> bool:
    return (
        row.get("amount") == expected.get("amount_minor")
        and str(row.get("name") or "") == str(expected.get("name") or "")
        and _nullable_id(row.get("account"))
        == _nullable_id(account_actual_ids.get(expected.get("account_id")))
        and payee_names.get(row.get("payee"), str(row.get("payee_name") or ""))
        == str(expected.get("payee") or expected.get("name") or "")
        and _normalized_schedule_date(row.get("date")) == _schedule_date(expected)
        and bool(row.get("completed")) == (not bool(expected.get("active")))
        and bool(row.get("posts_transaction")) == bool(expected.get("posts_transaction"))
        and str(row.get("amountOp") or "") == "is"
    )


def validate_active_links(db: Session, actual: dict) -> dict:
    """Prove a restored budget preserves the identity and content of every canonical link."""
    structural = validate_fresh_readback(actual)
    if not structural["ok"]:
        return structural
    state = db.get(FinanceLedgerState, "primary")
    if not state or state.mode != "actual" or not state.active_run_id:
        return structural

    links = db.query(ActualEntityLink).filter_by(run_id=state.active_run_id).all()
    run = db.get(ActualMigrationRun, state.active_run_id)
    try:
        snapshot = _load_snapshot(run) if run else {}
    except ActualMigrationError:
        snapshot = {}
    snapshot_accounts = {row["id"]: row for row in snapshot.get("accounts") or []}
    snapshot_transactions = {row["id"]: row for row in snapshot.get("transactions") or []}
    snapshot_schedules = {(row["kind"], row["id"]): row for row in snapshot.get("schedules") or []}
    snapshot_budgets = {row["id"]: row for row in snapshot.get("budget_assignments") or []}
    account_actual_ids = {
        row.source_id: str(row.actual_id or "")
        for row in links
        if row.entity_kind == "account" and row.actual_id
    }
    accounts = {row["id"]: row for row in actual["accounts"]}
    categories = {row["id"]: row for row in actual["categories"] if row.get("id")}
    transactions = {row["id"]: row for row in actual["transactions"]}
    starting_balances = defaultdict(int)
    invalid_starting_balance_accounts = set()
    for row in actual["transactions"]:
        if not row.get("starting_balance_flag"):
            continue
        account_id = str(row.get("account") or "")
        try:
            starting_balances[account_id] += int(row.get("amount"))
        except (TypeError, ValueError):
            invalid_starting_balance_accounts.add(account_id)
    schedules = {row.get("id"): row for row in actual["schedules"] if row.get("id")}
    payee_names = {
        row.get("id"): str(row.get("name") or "") for row in actual["payees"] if row.get("id")
    }
    budget_slots = {
        (month.get("month"), category.get("id")): category.get("budgeted")
        for month in actual["budget_months"]
        for group in month.get("categoryGroups") or []
        for category in group.get("categories") or []
        if month.get("month") and category.get("id")
    }
    missing = []
    claimed = defaultdict(set)
    for link in links:
        try:
            metadata = json.loads(link.metadata_json or "{}")
        except (TypeError, ValueError):
            metadata = {}
        deletion = metadata.get("_delete_intent") or metadata.get("_deleted") or {}
        if isinstance(deletion, dict) and deletion.get("actual_id"):
            deleted_target = str(deletion["actual_id"])
            if link.entity_kind == "account":
                restored_deleted_entity = deleted_target in accounts
            elif link.entity_kind == "transaction":
                restored_deleted_entity = deleted_target in transactions
            elif link.entity_kind == "transfer":
                restored_deleted_entity = any(
                    actual_id in transactions for actual_id in deleted_target.split(":")
                )
            elif link.entity_kind == "budget_limit":
                managed_month = str(metadata.get("managed_month") or "")
                restored_deleted_entity = bool(managed_month) and budget_slots.get(
                    (managed_month, deleted_target)
                ) not in {None, 0}
            elif link.entity_kind == "budget_assignment":
                assignment_month, separator, assignment_category = deleted_target.partition(":")
                restored_deleted_entity = (
                    not separator
                    or not assignment_month
                    or not assignment_category
                    or budget_slots.get((assignment_month, assignment_category)) not in {None, 0}
                )
            else:
                restored_deleted_entity = False
            if restored_deleted_entity:
                missing.append(
                    {
                        "kind": link.entity_kind,
                        "source_id": link.source_id,
                        "deleted_entity_restored": True,
                    }
                )
            continue
        actual_id = str(link.actual_id or "")
        kind = link.entity_kind
        if metadata.get("_intent") or metadata.get("_update_intent"):
            missing.append(
                {
                    "kind": kind,
                    "source_id": link.source_id,
                    "pending_creation": bool(metadata.get("_intent")),
                    "pending_update": bool(metadata.get("_update_intent")),
                }
            )
            continue
        if not actual_id:
            continue  # a durable pre-write intent does not claim an Actual entity yet
        if kind == "account":
            present = actual_id in accounts
            group = "account"
            if present:
                source = snapshot_accounts.get(link.source_id) or {}
                expected = (
                    {
                        "name": source.get("name"),
                        "offbudget": source.get("kind") == "investment",
                        "closed": bool(source.get("archived")),
                        "opening_minor": source.get("opening_minor"),
                    }
                    if source
                    else {}
                )
                canonical = metadata.get("canonical_account") or {}
                if isinstance(canonical, dict):
                    expected.update(canonical)
                if "opening_minor" not in expected and "base_amount_text" in metadata:
                    try:
                        expected["opening_minor"] = _minor(
                            metadata["base_amount_text"],
                            "restored account opening balance",
                        )
                    except ActualMigrationError:
                        pass
                complete = bool(source) or {
                    "name",
                    "offbudget",
                    "closed",
                    "opening_minor",
                }.issubset(expected)
                if not complete:
                    missing.append(
                        {
                            "kind": kind,
                            "source_id": link.source_id,
                            "content_checkpoint_missing": True,
                        }
                    )
                elif not _restored_account_matches(
                    accounts[actual_id],
                    expected,
                    (
                        None
                        if actual_id in invalid_starting_balance_accounts
                        else starting_balances.get(actual_id, 0)
                    ),
                ):
                    missing.append(
                        {"kind": kind, "source_id": link.source_id, "content_mismatch": True}
                    )
        elif kind == "transaction":
            present = actual_id in transactions
            group = "transaction"
            if present:
                source = snapshot_transactions.get(link.source_id) or {}
                expected = {}
                if source:
                    expected = {
                        "account": account_actual_ids.get(source.get("account_id"), ""),
                        "date": source.get("date"),
                        "amount": source.get("amount_minor"),
                        "notes": source.get("notes") or "",
                        "cleared": bool(source.get("cleared")),
                    }
                    if not source.get("transfer_id"):
                        expected.update(
                            {
                                "payee_name": source.get("payee") or "",
                                "category_name": source.get("category") or "",
                            }
                        )
                canonical = metadata.get("canonical_transaction") or {}
                if isinstance(canonical, dict):
                    expected.update(canonical)
                complete = bool(source) or {
                    "account",
                    "date",
                    "amount",
                    "notes",
                    "cleared",
                }.issubset(canonical)
                if not complete:
                    missing.append(
                        {
                            "kind": kind,
                            "source_id": link.source_id,
                            "content_checkpoint_missing": True,
                        }
                    )
                elif not _restored_transaction_matches(transactions[actual_id], expected):
                    missing.append(
                        {"kind": kind, "source_id": link.source_id, "content_mismatch": True}
                    )
        elif kind in {"recurring", "subscription"}:
            present = actual_id in schedules
            group = "schedule"
            expected = snapshot_schedules.get((kind, link.source_id))
            if present and expected is None:
                missing.append(
                    {
                        "kind": kind,
                        "source_id": link.source_id,
                        "content_checkpoint_missing": True,
                    }
                )
            elif present and (
                metadata != (expected.get("metadata") or {})
                or not _restored_schedule_matches(
                    schedules[actual_id],
                    expected,
                    account_actual_ids=account_actual_ids,
                    payee_names=payee_names,
                )
            ):
                missing.append(
                    {"kind": kind, "source_id": link.source_id, "content_mismatch": True}
                )
        elif kind == "budget_assignment":
            month, separator, category_id = actual_id.partition(":")
            present = bool(separator) and (month, category_id) in budget_slots
            group = "budget_assignment"
            expected = snapshot_budgets.get(link.source_id)
            if present and expected is None:
                missing.append(
                    {
                        "kind": kind,
                        "source_id": link.source_id,
                        "content_checkpoint_missing": True,
                    }
                )
            elif present and budget_slots.get((month, category_id)) != expected.get("amount_minor"):
                missing.append(
                    {"kind": kind, "source_id": link.source_id, "content_mismatch": True}
                )
        elif kind == "budget_limit":
            present = actual_id in categories
            group = "budget_limit"
            managed_month = str(metadata.get("managed_month") or "")
            limit_minor = metadata.get("limit_minor")
            if (
                present
                and managed_month
                and budget_slots.get((managed_month, actual_id)) != limit_minor
            ):
                missing.append(
                    {"kind": kind, "source_id": link.source_id, "content_mismatch": True}
                )
        elif kind == "transfer":
            left_id, separator, right_id = actual_id.partition(":")
            left = transactions.get(left_id)
            right = transactions.get(right_id)
            present = bool(separator) and bool(
                left
                and right
                and left.get("transfer_id") == right_id
                and right.get("transfer_id") == left_id
            )
            group = "transfer"
            canonical = metadata.get("canonical_transfer") or {}
            if present and isinstance(canonical, dict) and canonical:
                expected_left = {
                    "account": canonical.get("from_account"),
                    "date": canonical.get("date"),
                    "amount": -abs(int(canonical.get("amount_minor") or 0)),
                    "notes": canonical.get("notes") or "",
                }
                expected_right = {
                    "account": canonical.get("to_account"),
                    "date": canonical.get("date"),
                    "amount": abs(int(canonical.get("amount_minor") or 0)),
                    "notes": canonical.get("notes") or "",
                }
                if not _restored_transaction_matches(
                    left, expected_left
                ) or not _restored_transaction_matches(right, expected_right):
                    missing.append(
                        {"kind": kind, "source_id": link.source_id, "content_mismatch": True}
                    )
        elif kind in {"tag_budget", "subscription_payment"}:
            continue  # SQL-only evidence sidecars do not identify Actual entities
        else:
            missing.append({"kind": kind, "source_id": link.source_id, "unsupported": True})
            continue
        if not present:
            missing.append({"kind": kind, "source_id": link.source_id})
        if actual_id in claimed[group]:
            missing.append({"kind": kind, "source_id": link.source_id, "duplicate": True})
        claimed[group].add(actual_id)
    if missing:
        return {
            "ok": False,
            "error": (
                "restored Actual budget is older than or inconsistent with "
                "the active canonical link set"
            ),
            "invalid_links": missing[:20],
            "invalid_link_count": len(missing),
        }
    return {**structural, "active_links": sum(len(values) for values in claimed.values())}


@actual_finance.authority_guarded
def cutover(
    db: Session,
    run_id: str,
    *,
    bridge_request=managed_actual.bridge_request,
    backup_fn=managed_actual.backup,
) -> dict:
    state = _state(db)
    run = db.get(ActualMigrationRun, run_id)
    if not run or run.status != "ready":
        raise ActualMigrationError("only a freshly verified Actual staging run can cut over")
    if state.active_run_id != run.id:
        raise ActualMigrationError("only the active verified Actual staging run can cut over")
    if state.mode != "alles":
        raise ActualMigrationError("Finance write authority is already Actual")
    snapshot = _load_snapshot(run)
    current = build_snapshot(
        db,
        base_currency_code=run.base_currency_code,
        today=date.fromisoformat(f"{snapshot['budget_effective_month']}-01"),
        migration_run_id=run.id,
    )
    if snapshot_sha256(current) != run.snapshot_sha256:
        raise ActualMigrationError("Alles ledger changed after staging; stage and verify again")
    actual = bridge_request(
        {
            "command": "inspect",
            "budget_id": run.actual_budget_id,
            "sync_id": run.actual_sync_id,
        },
        timeout=180,
    )
    report = reconcile(snapshot, _saved_result(db, run, actual))
    if not report["pass"]:
        raise ActualMigrationError(
            "Actual changed after staging; write authority stayed with Alles"
        )
    backup = backup_fn()
    now = datetime.now(UTC)
    report["backup"] = backup
    report["actual_checkpoint_sha256"] = actual_checkpoint_sha256(actual)
    report["link_checkpoint_sha256"] = link_checkpoint_sha256(db, run.id)
    run.report_json = _canonical(report)
    run.status = "canonical"
    run.cutover_at = now
    state.mode = "actual"
    state.active_run_id = run.id
    state.base_currency_code = run.base_currency_code
    state.actual_budget_id = run.actual_budget_id
    state.actual_sync_id = run.actual_sync_id
    state.legacy_read_only = True
    state.cutover_at = now
    state.rollback_at = None
    db.commit()
    return state_payload(db)


@actual_finance.authority_guarded
def rollback(db: Session, *, bridge_request=managed_actual.bridge_request) -> dict:
    state = _state(db)
    if state.mode != "actual" or not state.active_run_id:
        raise ActualMigrationError("Finance write authority is already Alles")
    run = db.get(ActualMigrationRun, state.active_run_id)
    snapshot = _load_snapshot(run)
    current = build_snapshot(
        db,
        base_currency_code=run.base_currency_code,
        today=date.fromisoformat(f"{snapshot['budget_effective_month']}-01"),
        migration_run_id=run.id,
    )
    if snapshot_sha256(current) != run.snapshot_sha256:
        raise ActualMigrationError(
            "legacy Alles ledger changed during Actual authority; rollback stopped"
        )
    report = json.loads(run.report_json or "{}")
    checkpoint = report.get("actual_checkpoint_sha256")
    if not checkpoint:
        raise ActualMigrationError("canonical Actual checkpoint is missing; rollback stopped")
    link_checkpoint = report.get("link_checkpoint_sha256")
    if not link_checkpoint:
        raise ActualMigrationError("canonical link checkpoint is missing; rollback stopped")
    if link_checkpoint_sha256(db, run.id) != link_checkpoint:
        raise ActualMigrationError(
            "canonical link evidence changed after cutover; rollback stopped"
        )
    actual = bridge_request(
        {
            "command": "inspect",
            "budget_id": state.actual_budget_id,
            "sync_id": state.actual_sync_id,
        },
        timeout=180,
    )
    if actual_checkpoint_sha256(actual) != checkpoint:
        raise ActualMigrationError(
            "canonical Actual ledger changed after cutover; rollback stopped"
        )
    now = datetime.now(UTC)
    state.mode = "alles"
    state.legacy_read_only = False
    state.rollback_at = now
    run.status = "rolled_back"
    run.rolled_back_at = now
    db.commit()
    return state_payload(db)


def actual_config(db: Session) -> dict | None:
    state = _state(db)
    if state.mode != "actual":
        return None
    return {
        "budget_id": state.actual_budget_id,
        "sync_id": state.actual_sync_id,
        "base_currency_code": state.base_currency_code,
    }
