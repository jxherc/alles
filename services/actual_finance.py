"""Canonical Finance reads and writes after the one-way Actual authority switch."""

from __future__ import annotations

import calendar
import functools
import hashlib
import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import Account, ActualEntityLink, FinanceLedgerState, FundingTarget
from services import finance_currency, managed_actual
from services.money_stats import networth_history as _networth_history


class ActualFinanceError(RuntimeError):
    pass


class ActualFinanceUnavailable(ActualFinanceError):
    """The canonical provider cannot currently serve an otherwise valid request."""

    pass


AUTHORITY_LOCK = threading.RLock()
MAX_CENT_SAFE_MINOR = (1 << 46) * 100
MAX_CUSTOM_RECURRENCE_DAYS = 1_000_000
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ISO_DATETIME = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?"
)


def authority_guarded(function):
    """Serialize canonical writes and authority transitions in this process."""

    @functools.wraps(function)
    def guarded(*args, **kwargs):
        with AUTHORITY_LOCK:
            return function(*args, **kwargs)

    return guarded


def _fresh_ledger_state(db: Session) -> FinanceLedgerState | None:
    """Read authority from the database, replacing any identity-map snapshot."""
    return db.query(FinanceLedgerState).populate_existing().filter_by(id="primary").one_or_none()


def is_canonical(db: Session) -> bool:
    try:
        if not sa_inspect(db.connection()).has_table(FinanceLedgerState.__tablename__):
            return False
        state = _fresh_ledger_state(db)
    except SQLAlchemyError as exc:
        raise ActualFinanceError(
            "Finance write authority could not be established; legacy writes are blocked"
        ) from exc
    return bool(state and state.mode == "actual" and state.legacy_read_only)


def require_legacy_writable(db: Session) -> None:
    if is_canonical(db):
        raise ActualFinanceError("the old Alles ledger is read-only while Actual is canonical")


def _state(db: Session) -> FinanceLedgerState:
    state = _fresh_ledger_state(db)
    if not state or state.mode != "actual" or not state.active_run_id:
        raise ActualFinanceError("Actual is not the canonical Finance ledger")
    if not state.actual_budget_id and not state.actual_sync_id:
        raise ActualFinanceError("the canonical Actual budget is not linked")
    return state


def _request(db: Session, payload: dict, *, timeout: int = 180, bridge_request=None) -> dict:
    state = _state(db)
    try:
        return (bridge_request or managed_actual.bridge_request)(
            {
                **payload,
                "budget_id": state.actual_budget_id,
                "sync_id": state.actual_sync_id,
            },
            timeout=timeout,
        )
    except managed_actual.ManagedActualError as exc:
        raise ActualFinanceUnavailable(str(exc)) from exc


@authority_guarded
def inspect(db: Session, *, timeout: int = 180, bridge_request=None) -> dict:
    return _request(db, {"command": "inspect"}, timeout=timeout, bridge_request=bridge_request)


def _links(db: Session, kind: str) -> list[ActualEntityLink]:
    state = _state(db)
    return db.query(ActualEntityLink).filter_by(run_id=state.active_run_id, entity_kind=kind).all()


def _budget_limit_link(
    db: Session,
    *,
    category_id: str = "",
    category_name: str = "",
) -> ActualEntityLink | None:
    name_key = str(category_name or "").strip().casefold()
    for row in _links(db, "budget_limit"):
        metadata = _link_metadata(row)
        target = _deletion_target(metadata)
        if category_id and category_id in {row.actual_id, target}:
            return row
        if metadata.get("_deleted"):
            continue
        if name_key and str(metadata.get("category") or "").strip().casefold() == name_key:
            return row
    return None


def _tag_budget_link(db: Session, tag: str) -> ActualEntityLink | None:
    key = str(tag or "").strip().casefold()
    for row in _links(db, "tag_budget"):
        metadata = _link_metadata(row)
        if metadata.get("_delete_intent") or metadata.get("_deleted"):
            continue
        if str(metadata.get("tag") or "").strip().casefold() == key:
            return row
    return None


def _maps(db: Session, kind: str) -> tuple[dict[str, str], dict[str, str], dict[str, dict]]:
    source_to_actual = {}
    actual_to_source = {}
    metadata = {}
    for row in _links(db, kind):
        row_metadata = _link_metadata(row)
        if not row.actual_id or row_metadata.get("_deleted"):
            continue
        source_to_actual[row.source_id] = row.actual_id
        actual_to_source[row.actual_id] = row.source_id
        metadata[row.actual_id] = row_metadata
    return source_to_actual, actual_to_source, metadata


def _assert_no_unresolved_creation_intents(db: Session, *kinds: str) -> None:
    """Fail closed while an external create may exist without its durable Actual ID."""
    for kind in kinds:
        for link in _links(db, kind):
            if link.actual_id:
                continue
            if _link_metadata(link).get("_intent"):
                raise ActualFinanceError(
                    f"a canonical {kind} creation is incomplete; retry that creation before reading Finance"
                )


def _native_transfer_public_id(left: str, right: str) -> str:
    return "actual-transfer:" + ":".join(sorted((left, right)))


def _resolve(
    db: Session,
    kind: str,
    public_id: str,
    *,
    bridge_request=None,
) -> str:
    pending_kinds = (kind, "transfer") if kind == "transaction" else (kind,)
    _assert_no_unresolved_creation_intents(db, *pending_kinds)
    source_to_actual, actual_to_source, metadata = _maps(db, kind)
    if public_id in source_to_actual:
        actual_id = source_to_actual[public_id]
        row_metadata = metadata.get(actual_id, {})
        if row_metadata.get("_intent"):
            raise ActualFinanceError(
                f"{kind} creation is incomplete; retry the creation before using it"
            )
        if row_metadata.get("_delete_intent"):
            raise ActualFinanceError(
                f"{kind} deletion is incomplete; retry the deletion before using it"
            )
        return actual_id
    if public_id in actual_to_source:
        row_metadata = metadata.get(public_id, {})
        if row_metadata.get("_intent"):
            raise ActualFinanceError(
                f"{kind} creation is incomplete; retry the creation before using it"
            )
        if row_metadata.get("_delete_intent"):
            raise ActualFinanceError(
                f"{kind} deletion is incomplete; retry the deletion before using it"
            )
        return public_id
    actual = inspect(db, bridge_request=bridge_request)
    if kind in {"account", "transaction"}:
        rows = actual.get(f"{kind}s") or []
        if any(row.get("id") == public_id for row in rows):
            return public_id
    if kind == "transfer" and public_id.startswith("actual-transfer:"):
        ids = public_id.removeprefix("actual-transfer:").split(":")
        if len(ids) == 2 and all(ids):
            rows = {row.get("id"): row for row in actual.get("transactions") or []}
            left, right = (rows.get(ids[0]), rows.get(ids[1]))
            if (
                left
                and right
                and left.get("transfer_id") == right.get("id")
                and right.get("transfer_id") == left.get("id")
            ):
                return f"{ids[0]}:{ids[1]}"
    raise ActualFinanceError(f"{kind} was not found in the canonical Actual ledger")


def _record_link(
    db: Session,
    kind: str,
    source_id: str,
    actual_id: str,
    metadata: dict | None = None,
) -> None:
    state = _state(db)
    existing = (
        db.query(ActualEntityLink)
        .filter_by(run_id=state.active_run_id, entity_kind=kind, source_id=source_id)
        .first()
    )
    if existing:
        if existing.actual_id and existing.actual_id != actual_id:
            raise ActualFinanceError(f"{kind} identity changed after cutover")
        existing.actual_id = actual_id
        existing.metadata_json = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))
    else:
        db.add(
            ActualEntityLink(
                run_id=state.active_run_id,
                entity_kind=kind,
                source_id=source_id,
                actual_id=actual_id,
                metadata_json=json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
            )
        )


def _link_metadata(row: ActualEntityLink) -> dict:
    try:
        value = json.loads(row.metadata_json or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _deletion_target(metadata: dict) -> str:
    marker = metadata.get("_delete_intent") or metadata.get("_deleted") or {}
    return str(marker.get("actual_id") or "") if isinstance(marker, dict) else ""


def _find_deletion_link(db: Session, kind: str, public_id: str) -> ActualEntityLink | None:
    native_target = (
        public_id.removeprefix("actual-transfer:")
        if kind == "transfer" and public_id.startswith("actual-transfer:")
        else public_id
    )
    for row in _links(db, kind):
        if public_id in {row.source_id, row.actual_id}:
            return row
        if _deletion_target(_link_metadata(row)) == native_target:
            return row
    return None


def _ensure_deletion_link(
    db: Session,
    kind: str,
    public_id: str,
    actual_id: str,
) -> ActualEntityLink:
    existing = _find_deletion_link(db, kind, public_id) or _find_deletion_link(db, kind, actual_id)
    if existing:
        return existing
    state = _state(db)
    row = ActualEntityLink(
        run_id=state.active_run_id,
        entity_kind=kind,
        source_id=f"actual-native:{kind}:{actual_id}",
        actual_id=actual_id,
        metadata_json='{"source":"actual_native"}',
    )
    db.add(row)
    db.flush()
    return row


def _begin_link_deletion(db: Session, row: ActualEntityLink) -> tuple[str, bool]:
    metadata = _link_metadata(row)
    if metadata.get("_deleted"):
        return _deletion_target(metadata), True
    target = _deletion_target(metadata) or str(row.actual_id or "")
    if not target:
        raise ActualFinanceError(f"{row.entity_kind} deletion target is missing")
    if not metadata.get("_delete_intent"):
        metadata["_delete_intent"] = {"version": 1, "actual_id": target}
        row.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        db.commit()
    return target, False


def _finish_link_deletion(row: ActualEntityLink, target: str) -> None:
    metadata = _link_metadata(row)
    metadata.pop("_delete_intent", None)
    metadata["_deleted"] = {"version": 1, "actual_id": target}
    row.actual_id = ""
    row.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))


def _request_fingerprint(action: str, payload: dict) -> str:
    canonical = json.dumps(
        {"action": action, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _request_source_id(request_id: str, kind: str) -> str:
    """Validate the caller-owned identity used to replay one manual create."""
    raw = str(request_id or "").strip()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ActualFinanceError(f"{kind} request_id must be a UUID") from exc
    canonical = str(parsed)
    if raw.lower() != canonical:
        raise ActualFinanceError(f"{kind} request_id must use canonical UUID form")
    return canonical


def _begin_intent(
    db: Session,
    kind: str,
    source_id: str,
    fingerprint: str,
    details: dict,
    evidence: dict,
    *,
    revive_deleted: bool = False,
) -> tuple[ActualEntityLink, bool]:
    state = _state(db)
    existing = (
        db.query(ActualEntityLink)
        .filter_by(run_id=state.active_run_id, entity_kind=kind, source_id=source_id)
        .first()
    )
    if existing:
        metadata = _link_metadata(existing)
        pending = metadata.get("_intent") or {}
        completed_fingerprint = metadata.get("_request_fingerprint")
        prior = pending.get("fingerprint") or completed_fingerprint
        if not prior:
            raise ActualFinanceError(
                f"{kind} request identity is already owned by a non-create link"
            )
        if prior != fingerprint:
            raise ActualFinanceError(f"{kind} retry does not match its durable intent")
        if metadata.get("_deleted") and revive_deleted:
            existing.actual_id = ""
            existing.metadata_json = json.dumps(
                {
                    **evidence,
                    "_intent": {"version": 1, "fingerprint": fingerprint, "details": details},
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            db.commit()
            return existing, False
        return existing, bool(completed_fingerprint and not pending)
    metadata = {
        **evidence,
        "_intent": {"version": 1, "fingerprint": fingerprint, "details": details},
    }
    row = ActualEntityLink(
        run_id=state.active_run_id,
        entity_kind=kind,
        source_id=source_id,
        actual_id="",
        metadata_json=json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    )
    db.add(row)
    db.commit()
    return row, False


def _finish_intent(
    row: ActualEntityLink,
    actual_id: str,
    fingerprint: str,
    evidence: dict,
) -> None:
    if row.actual_id and row.actual_id != actual_id:
        raise ActualFinanceError(f"{row.entity_kind} identity changed after cutover")
    row.actual_id = actual_id
    row.metadata_json = json.dumps(
        {**evidence, "_request_fingerprint": fingerprint},
        sort_keys=True,
        separators=(",", ":"),
    )


def _recover_imported_transaction(
    db: Session,
    transaction: dict,
    *,
    bridge_request=None,
) -> str:
    """Recover one externally committed transaction before replaying its pending intent."""
    imported_id = str(transaction.get("imported_id") or "")
    current = inspect(db, bridge_request=bridge_request)
    matches = [
        row
        for row in current.get("transactions") or []
        if str(row.get("imported_id") or "") == imported_id
    ]
    if len(matches) > 1:
        raise ActualFinanceError("pending Actual transaction import identity is not unique")
    if not matches:
        return ""
    row = matches[0]
    expected = {
        "account": str(transaction.get("account") or ""),
        "date": _date(transaction.get("date")),
        "amount": int(transaction.get("amount") or 0),
        "payee_name": str(transaction.get("payee_name") or ""),
        "category_name": str(transaction.get("category_name") or ""),
        "notes": str(transaction.get("notes") or ""),
        "cleared": bool(transaction.get("cleared")),
    }
    observed = {
        "account": str(row.get("account") or ""),
        "date": _date(row.get("date")),
        "amount": int(row.get("amount") or 0),
        "payee_name": str(row.get("payee_name") or row.get("imported_payee") or ""),
        "category_name": str(row.get("category_name") or ""),
        "notes": str(row.get("notes") or ""),
        "cleared": bool(row.get("cleared")),
    }
    if observed != expected:
        raise ActualFinanceError("pending Actual transaction does not match its durable intent")
    actual_id = str(row.get("id") or "")
    if not actual_id:
        raise ActualFinanceError("pending Actual transaction has no stable identity")
    return actual_id


def _transaction_fields_match(row: dict, fields: dict) -> bool:
    for key, expected in fields.items():
        actual = row.get(key)
        if key == "date":
            if _date(actual) != _date(expected):
                return False
        elif key == "cleared":
            if bool(actual) != bool(expected):
                return False
        elif key == "amount":
            if int(actual or 0) != int(expected):
                return False
        elif key == "payee_name":
            if str(actual or row.get("imported_payee") or "") != str(expected or ""):
                return False
        elif key in {"notes", "category_name"}:
            if str(actual or "") != str(expected or ""):
                return False
        elif actual != expected:
            return False
    return True


def _account_fields_match(row: dict, fields: dict) -> bool:
    for key, expected in fields.items():
        actual = row.get(key)
        if key in {"offbudget", "closed"}:
            if bool(actual) != bool(expected):
                return False
        elif str(actual or "") != str(expected or ""):
            return False
    return True


def _recover_imported_transfer(
    db: Session,
    transfer: dict,
    *,
    bridge_request=None,
) -> dict | None:
    """Recover one complete reciprocal transfer before replaying its pending intent."""
    imported_id = f"{transfer.get('imported_id')}:out"
    current = inspect(db, bridge_request=bridge_request)
    transactions = current.get("transactions") or []
    matches = [row for row in transactions if str(row.get("imported_id") or "") == imported_id]
    if len(matches) > 1:
        raise ActualFinanceError("pending Actual transfer import identity is not unique")
    if not matches:
        return None
    outgoing = matches[0]
    by_id = {str(row.get("id") or ""): row for row in transactions if row.get("id")}
    incoming = by_id.get(str(outgoing.get("transfer_id") or ""))
    outgoing_id = str(outgoing.get("id") or "")
    incoming_id = str(incoming.get("id") or "") if incoming else ""
    if not (
        outgoing_id
        and incoming_id
        and outgoing_id != incoming_id
        and str(incoming.get("transfer_id") or "") == outgoing_id
    ):
        raise ActualFinanceError("pending Actual transfer is not one complete reciprocal pair")
    expected_date = _date(transfer.get("date"))
    amount_minor = abs(int(transfer.get("amount_minor") or 0))
    expected_notes = str(transfer.get("notes") or "")
    if (
        str(outgoing.get("account") or "") != str(transfer.get("from_account") or "")
        or str(incoming.get("account") or "") != str(transfer.get("to_account") or "")
        or int(outgoing.get("amount") or 0) != -amount_minor
        or int(incoming.get("amount") or 0) != amount_minor
        or _date(outgoing.get("date")) != expected_date
        or _date(incoming.get("date")) != expected_date
        or str(outgoing.get("notes") or "") != expected_notes
        or str(incoming.get("notes") or "") != expected_notes
    ):
        raise ActualFinanceError("pending Actual transfer does not match its durable intent")
    return {"from_id": outgoing_id, "to_id": incoming_id}


@authority_guarded
def record_transaction_link(
    db: Session,
    source_id: str,
    actual_id: str,
    metadata: dict,
    *,
    values: dict | None = None,
    bridge_request=None,
    commit: bool = False,
) -> None:
    """Attach durable Alles ownership to an idempotently recovered Actual transaction."""
    state = _state(db)
    existing = (
        db.query(ActualEntityLink)
        .filter_by(
            run_id=state.active_run_id,
            entity_kind="transaction",
            source_id=source_id,
        )
        .first()
    )
    prior = _link_metadata(existing) if existing else {}
    intent = prior.pop("_intent", {})
    merged = {**prior, **metadata}
    if values is not None:
        canonical = _canonical_transaction(
            db,
            values,
            bridge_request=bridge_request,
            verified_existing=True,
        )
        merged["canonical_transaction"] = canonical
    fingerprint = intent.get("fingerprint") if isinstance(intent, dict) else ""
    if not fingerprint and values is not None and values.get("import_identity"):
        fingerprint = _request_fingerprint(
            "create_transaction",
            {**canonical, "imported_id": str(values["import_identity"])},
        )
    if fingerprint:
        merged["_request_fingerprint"] = fingerprint
    _record_link(db, "transaction", source_id, actual_id, merged)
    if commit:
        db.commit()


def _minor(value, label: str = "amount") -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ActualFinanceError(f"{label} must be an exact decimal") from exc
    scaled = amount * 100
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        raise ActualFinanceError(f"{label} cannot have more than two decimal places")
    minor = int(scaled)
    if abs(minor) > MAX_CENT_SAFE_MINOR:
        raise ActualFinanceError(f"{label} is outside Actual's exact numeric range")
    return minor


def _major_from_minor(minor: int, label: str = "amount") -> float:
    if abs(minor) > MAX_CENT_SAFE_MINOR:
        raise ActualFinanceError(f"{label} is outside Alles' cent-safe numeric range")
    exact = Decimal(minor) / 100
    rendered = float(exact)
    if Decimal(str(rendered)) != exact:
        raise ActualFinanceError(f"{label} cannot be represented with cent precision")
    return rendered


def _canonical_transaction(
    db: Session,
    values: dict,
    *,
    bridge_request=None,
    verified_existing: bool = False,
) -> dict:
    public_account = str(values.get("account_id") or "")
    if verified_existing:
        source_to_actual, _actual_to_source, account_metadata = _maps(db, "account")
        actual_account = source_to_actual.get(public_account, public_account)
        pending_account = account_metadata.get(actual_account, {})
        if pending_account.get("_intent"):
            raise ActualFinanceError(
                "account creation is incomplete; retry the creation before using it"
            )
        if pending_account.get("_delete_intent"):
            raise ActualFinanceError(
                "account deletion is incomplete; retry the deletion before using it"
            )
    else:
        actual_account = _resolve(
            db,
            "account",
            public_account,
            bridge_request=bridge_request,
        )
    return {
        "account": actual_account,
        "date": _required_date(values.get("date")),
        "amount": _minor(values.get("amount", 0)),
        "payee_name": str(values.get("payee") or "").strip(),
        "category_name": str(values.get("category") or "").strip(),
        "notes": str(values.get("notes") or "").strip(),
        "cleared": bool(values.get("cleared")),
    }


def _date(value) -> str:
    raw = str(value or "")
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw[:10]


def _required_date(value, label: str = "transaction date") -> str:
    raw = str(value or "").strip()
    try:
        if len(raw) == 8 and raw.isdigit():
            parsed = date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
        elif _ISO_DATE.fullmatch(raw):
            parsed = date.fromisoformat(raw)
        elif _ISO_DATETIME.fullmatch(raw):
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        else:
            raise ValueError
    except (TypeError, ValueError):
        raise ActualFinanceError(f"{label} must be a valid calendar date") from None
    return parsed.isoformat()


def _account_kind(row: dict) -> str:
    return "investment" if row.get("offbudget") else "checking"


def _account_currency(value, base: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return base
    code = finance_currency.currency_code(raw)
    if code == "XXX":
        raise ActualFinanceError("account currency must be a reviewed currency code")
    if code != base:
        raise ActualFinanceError(f"new Actual accounts must use the canonical base currency {base}")
    return code


@authority_guarded
def accounts(
    db: Session,
    *,
    actual: dict | None = None,
    bridge_request=None,
    _source_ids: set[str] | None = None,
) -> list[dict]:
    only_actual_ids = None
    if _source_ids:
        source_to_actual, _actual_to_source, _metadata = _maps(db, "account")
        only_actual_ids = {source_to_actual.get(source_id, "") for source_id in _source_ids}
        if "" in only_actual_ids:
            raise ActualFinanceError("created account did not finish its durable identity")
    else:
        _assert_no_unresolved_creation_intents(db, "account")
    actual = actual or inspect(db, bridge_request=bridge_request)
    state = _state(db)
    _source_to_actual, actual_to_source, metadata = _maps(db, "account")
    native_opening_minor = {}
    for transaction in actual.get("transactions") or []:
        if not transaction.get("starting_balance_flag"):
            continue
        account_id = str(transaction.get("account") or transaction.get("account_id") or "")
        if account_id:
            native_opening_minor[account_id] = native_opening_minor.get(account_id, 0) + int(
                transaction.get("amount") or 0
            )
    rows = []
    for row in actual.get("accounts") or []:
        if only_actual_ids is not None and row.get("id") not in only_actual_ids:
            continue
        evidence = metadata.get(row.get("id"), {})
        if evidence.get("_intent"):
            raise ActualFinanceError(
                "a canonical account creation is incomplete; retry that creation before reading Finance"
            )
        if evidence.get("_delete_intent"):
            raise ActualFinanceError(
                "a canonical account deletion is incomplete; retry that deletion before reading Finance"
            )
        if evidence.get("_update_intent"):
            raise ActualFinanceError(
                "a canonical account update is uncertain; retry that update before reading Finance"
            )
        balance_minor = int(row.get("balance") or 0)
        public_id = actual_to_source.get(row.get("id"), row.get("id"))
        native_opening_text = format(
            Decimal(native_opening_minor.get(str(row.get("id") or ""), 0)) / 100,
            "f",
        )
        original_opening_text = str(
            evidence.get("original_amount_text")
            if evidence.get("original_amount_text") not in {None, ""}
            else native_opening_text
        )
        base_opening_text = str(
            evidence.get("base_amount_text")
            if evidence.get("base_amount_text") not in {None, ""}
            else native_opening_text
        )
        # The linked text preserves migration evidence, but Actual's starting
        # balance is the live ledger value when the owner changes it there.
        actual_id = str(row.get("id") or "")
        opening_minor = (
            native_opening_minor[actual_id]
            if actual_id in native_opening_minor
            else _minor(base_opening_text, "opening balance")
        )
        opening_major = _major_from_minor(opening_minor, "opening balance")
        low_balance_major = _major_from_minor(
            _minor(evidence.get("low_balance") or 0, "low balance"), "low balance"
        )
        rows.append(
            {
                "id": public_id,
                "actual_id": row.get("id"),
                "name": row.get("name") or "account",
                "kind": evidence.get("account_kind") or _account_kind(row),
                "currency": state.base_currency_code,
                "opening": opening_major,
                "color": evidence.get("color") or "accent",
                "archived": bool(row.get("closed")),
                "low_balance": low_balance_major,
                "balance": _major_from_minor(balance_minor, "account balance"),
                "currency_code": evidence.get("original_currency_code") or state.base_currency_code,
                "base_currency_code": state.base_currency_code,
                "original_opening_text": original_opening_text,
                "base_opening_text": base_opening_text,
                "opening_fx_rate_text": evidence.get("rate_text") or "1",
                "opening_fx_rate_date": evidence.get("rate_date") or "",
                "opening_fx_source": evidence.get("source") or "actual_identity",
            }
        )
    return rows


@authority_guarded
def transactions(
    db: Session,
    *,
    actual: dict | None = None,
    bridge_request=None,
    _source_ids: set[str] | None = None,
) -> list[dict]:
    only_actual_ids = None
    if _source_ids:
        source_to_actual, _actual_to_source, _metadata = _maps(db, "transaction")
        only_actual_ids = {source_to_actual.get(source_id, "") for source_id in _source_ids}
        if "" in only_actual_ids:
            raise ActualFinanceError("created transaction did not finish its durable identity")
    else:
        _assert_no_unresolved_creation_intents(db, "account", "transaction", "transfer")
    actual = actual or inspect(db, bridge_request=bridge_request)
    state = _state(db)
    _account_sources, account_public, account_metadata = _maps(db, "account")
    _txn_sources, txn_public, metadata = _maps(db, "transaction")
    transfer_public = {}
    pending_transfer_ids = set()
    for link in _links(db, "transfer"):
        link_metadata = _link_metadata(link)
        if link_metadata.get("_deleted"):
            continue
        ids = str(link.actual_id or "").split(":")
        for actual_id in ids:
            if actual_id:
                transfer_public[actual_id] = link.source_id
                if link_metadata.get("_delete_intent"):
                    pending_transfer_ids.add(actual_id)
    rows = []
    for row in actual.get("transactions") or []:
        # Actual models an account's opening balance as an internal transaction.
        # Alles exposes it through the account balance/opening fields instead, so
        # returning it here would double-count income and pollute the ledger UI.
        if row.get("starting_balance_flag"):
            continue
        actual_id = row.get("id")
        if only_actual_ids is not None and actual_id not in only_actual_ids:
            continue
        evidence = metadata.get(actual_id, {})
        if evidence.get("_delete_intent") or actual_id in pending_transfer_ids:
            raise ActualFinanceError(
                "a canonical transaction deletion is incomplete; retry that deletion before reading the ledger"
            )
        pending_account = account_metadata.get(row.get("account"), {})
        if pending_account.get("_intent"):
            raise ActualFinanceError(
                "a canonical account creation is incomplete; retry that creation before reading the ledger"
            )
        if pending_account.get("_delete_intent"):
            raise ActualFinanceError(
                "a canonical account deletion is incomplete; retry that deletion before reading the ledger"
            )
        if evidence.get("_update_intent"):
            raise ActualFinanceError(
                "a canonical transaction update is uncertain; retry that update before reading the ledger"
            )
        amount_minor = int(row.get("amount") or 0)
        public_id = txn_public.get(actual_id, actual_id)
        native_partner = row.get("transfer_id") or ""
        transfer_id = transfer_public.get(actual_id) or (
            _native_transfer_public_id(actual_id, native_partner) if native_partner else ""
        )
        source_import_identity = (
            evidence.get("migration_source_import_identity")
            if "migration_source_import_identity" in evidence
            else row.get("imported_id")
        )
        rows.append(
            {
                "id": public_id,
                "actual_id": actual_id,
                "account_id": account_public.get(row.get("account"), row.get("account")),
                "date": _date(row.get("date")),
                "amount": _major_from_minor(amount_minor, "transaction amount"),
                "category": row.get("category_name") or "",
                "payee": row.get("payee_name") or row.get("imported_payee") or "",
                "notes": row.get("notes") or "",
                "transfer_id": transfer_id,
                "schedule_id": str(row.get("schedule") or ""),
                "tags": evidence.get("tags") or "",
                "receipt_id": evidence.get("receipt_id") or "",
                "cleared": bool(row.get("cleared")),
                "split": False,
                "original_amount_text": evidence.get("original_amount_text")
                or format(Decimal(amount_minor) / 100, "f"),
                "original_currency_code": evidence.get("original_currency_code")
                or state.base_currency_code,
                "base_amount_text": evidence.get("base_amount_text")
                or format(Decimal(amount_minor) / 100, "f"),
                "base_currency_code": state.base_currency_code,
                "import_identity": source_import_identity or "",
                "import_batch_id": evidence.get("import_batch_id") or "",
                "import_source": evidence.get("import_source") or "actual",
            }
        )
    return rows


def networth_rows(db: Session, actual: dict) -> tuple[list[dict], list[dict]]:
    """Mapped ledger rows with dated openings for new Actual accounts."""
    mapped_accounts = accounts(db, actual=actual)
    mapped_transactions = transactions(db, actual=actual)
    starting_rows = [
        row for row in actual.get("transactions") or [] if row.get("starting_balance_flag")
    ]
    if not starting_rows:
        return mapped_accounts, mapped_transactions
    legacy_ids = {account_id for (account_id,) in db.query(Account.id).all()}
    new_accounts = {
        str(row.get("actual_id") or ""): row
        for row in mapped_accounts
        if row["id"] not in legacy_ids
    }
    dated_openings = []
    dated_account_ids = set()
    for row in starting_rows:
        account = new_accounts.get(str(row.get("account") or row.get("account_id") or ""))
        if not account:
            continue
        dated_account_ids.add(account["id"])
        dated_openings.append(
            {
                "account_id": account["id"],
                "date": _required_date(row.get("date"), "opening balance date"),
                "amount": _major_from_minor(int(row.get("amount") or 0), "opening balance"),
            }
        )
    history_accounts = [
        {**row, "opening": 0.0} if row["id"] in dated_account_ids else row
        for row in mapped_accounts
    ]
    return history_accounts, mapped_transactions + dated_openings


@authority_guarded
def networth_history(
    db: Session,
    *,
    end_month: str,
    months: int,
    actual: dict | None = None,
    bridge_request=None,
) -> list[dict]:
    """Keep migrated openings as a baseline; date new Actual openings."""
    actual = actual or inspect(db, bridge_request=bridge_request)
    history_accounts, history_transactions = networth_rows(db, actual)
    return _networth_history(
        history_accounts, history_transactions, end_month=end_month, months=months
    )


@authority_guarded
def subscription_payments(
    db: Session,
    *,
    subscription_id: str | None = None,
    actual: dict | None = None,
    bridge_request=None,
) -> dict[str, list[dict]]:
    """Return Actual-posted transactions grouped by their durable subscription link."""
    actual = actual or inspect(db, bridge_request=bridge_request)
    source_to_schedule, _schedule_to_source, _metadata = _maps(db, "subscription")
    if subscription_id is not None:
        schedule_id = source_to_schedule.get(subscription_id)
        if not schedule_id:
            return {subscription_id: []}
        source_to_schedule = {subscription_id: schedule_id}
    schedule_to_source = {
        schedule_id: source_id for source_id, schedule_id in source_to_schedule.items()
    }
    payment_source_by_transaction = {}
    for link in _links(db, "subscription_payment"):
        transaction_id = str(_link_metadata(link).get("transaction_id") or "")
        if not transaction_id:
            continue
        if transaction_id in payment_source_by_transaction:
            raise ActualFinanceError("subscription payment transaction identity is not unique")
        payment_source_by_transaction[transaction_id] = link.source_id
    grouped = {source_id: [] for source_id in source_to_schedule}
    for transaction in transactions(db, actual=actual):
        source_id = schedule_to_source.get(str(transaction.get("schedule_id") or ""))
        if not source_id:
            continue
        grouped[source_id].append(
            {
                "id": f"actual-payment:{transaction['actual_id']}",
                "date": transaction["date"],
                "amount": abs(float(transaction["amount"])),
                "txn_id": transaction["id"],
                "source_payment_id": payment_source_by_transaction.get(transaction["id"], ""),
            }
        )
    for rows in grouped.values():
        rows.sort(key=lambda row: (row["date"], row["id"]), reverse=True)
    return grouped


def merge_payment_history(legacy: list[dict], canonical: list[dict]) -> list[dict]:
    """Keep historical sidecars only when Actual has no matching payment."""
    canonical_sources = {
        str(row.get("source_payment_id") or "") for row in canonical if row.get("source_payment_id")
    }
    canonical_transactions = {
        str(row.get("txn_id") or "") for row in canonical if row.get("txn_id")
    }
    if any(
        not str(row.get("source_payment_id") or "") and not str(row.get("txn_id") or "")
        for row in canonical
    ):
        raise ActualFinanceError("canonical subscription payment is missing its durable identity")
    remaining_legacy = [
        row
        for row in legacy
        if str(row.get("source_payment_id") or "") not in canonical_sources
        and (
            not str(row.get("txn_id") or "")
            or str(row.get("txn_id") or "") not in canonical_transactions
        )
    ]
    return [*remaining_legacy, *canonical]


def _schedule_cycle(value) -> tuple[str, int, str]:
    rule = value if isinstance(value, dict) else {}
    frequency = str(rule.get("frequency") or "monthly").strip().lower()
    try:
        interval = int(rule.get("interval") or 1)
    except (TypeError, ValueError):
        raise ActualFinanceError("the Actual subscription recurrence interval is invalid") from None
    if interval < 1:
        raise ActualFinanceError("the Actual subscription recurrence interval must be positive")
    if frequency == "daily" and interval == 1:
        cycle, cycle_days = "daily", 1
    elif frequency == "weekly" and interval == 1:
        cycle, cycle_days = "weekly", 7
    elif frequency == "monthly" and interval == 1:
        cycle, cycle_days = "monthly", 30
    elif frequency == "monthly" and interval == 3:
        cycle, cycle_days = "quarterly", 91
    elif frequency == "yearly" and interval == 1:
        cycle, cycle_days = "yearly", 365
    elif frequency == "daily":
        cycle, cycle_days = "custom", interval
    elif frequency == "weekly":
        cycle, cycle_days = "custom", interval * 7
    elif frequency in {"monthly", "yearly"}:
        raise ActualFinanceError(
            f"the Actual {frequency} recurrence interval {interval} cannot be represented exactly"
        )
    else:
        raise ActualFinanceError(
            f"the Actual recurrence frequency {frequency or '(empty)'} is unsupported"
        )
    if cycle == "custom" and cycle_days > MAX_CUSTOM_RECURRENCE_DAYS:
        raise ActualFinanceError("the Actual subscription recurrence interval is too large")
    return cycle, cycle_days, _date(rule.get("start"))


def _add_schedule_months(value: date, months: int, anchor: int) -> date:
    year_offset, month_index = divmod(value.month - 1 + months, 12)
    year, month = value.year + year_offset, month_index + 1
    return date(year, month, min(anchor, calendar.monthrange(year, month)[1]))


def _schedule_anchor(rule, start: date) -> int:
    patterns = rule.get("patterns") if isinstance(rule, dict) else None
    if not patterns:
        return start.day
    if not isinstance(patterns, list) or len(patterns) != 1:
        raise ActualFinanceError("the Actual schedule day pattern is unsupported")
    pattern = patterns[0]
    if not isinstance(pattern, dict) or pattern.get("type") != "day":
        raise ActualFinanceError("the Actual schedule day pattern is unsupported")
    value = pattern.get("value")
    if type(value) is not int or (value != -1 and not 1 <= value <= 31):
        raise ActualFinanceError("the Actual schedule day pattern is unsupported")
    return 31 if value == -1 else value


def _next_schedule_due(rule, provider_next="", *, today: date | None = None) -> str:
    """Prefer Actual's computed occurrence, otherwise advance its stable rule anchor."""
    if provider_next:
        try:
            return date.fromisoformat(_date(provider_next)).isoformat()
        except ValueError as exc:
            raise ActualFinanceError("the Actual schedule next occurrence is invalid") from exc
    cycle, cycle_days, start_text = _schedule_cycle(rule)
    try:
        current = date.fromisoformat(start_text)
    except ValueError as exc:
        raise ActualFinanceError("the Actual schedule start date is invalid") from exc
    target = today or date.today()
    anchor = _schedule_anchor(rule, current)
    if current >= target:
        return current.isoformat()
    if cycle in {"daily", "weekly", "custom"}:
        step_days = 7 if cycle == "weekly" else cycle_days
        elapsed_days = (target - current).days
        periods = (elapsed_days + step_days - 1) // step_days
        current += timedelta(days=periods * step_days)
    else:
        step_months = {"monthly": 1, "quarterly": 3, "yearly": 12}[cycle]
        elapsed_months = (target.year - current.year) * 12 + target.month - current.month
        periods = max(0, elapsed_months // step_months)
        candidate = _add_schedule_months(current, periods * step_months, anchor)
        if candidate < target:
            candidate = _add_schedule_months(current, (periods + 1) * step_months, anchor)
        current = candidate
    return current.isoformat()


def subscription_display_name(schedule: dict, legacy) -> str:
    name = str(schedule.get("name") or "subscription")
    if legacy and name == f"Alles subscription: {legacy.name} [{legacy.id[:8]}]":
        return legacy.name
    return name


def _recurring_edit_intent(link: ActualEntityLink, metadata: dict) -> dict:
    """Validate the one saved choice used by read, retry, and final readback."""
    from services import actual_migration

    pending = metadata.get("_update_intent")
    details = pending.get("details") if isinstance(pending, dict) else None
    overlay = metadata.get("canonical_schedule")
    if not isinstance(overlay, dict) or overlay.get("version") not in {1, 2, 3}:
        raise ActualFinanceError("the recurring edit checkpoint is invalid")
    if (
        not isinstance(pending, dict)
        or pending.get("version") != 1
        or pending.get("action") != "edit_recurring_schedule"
        or not isinstance(pending.get("backup_id"), str)
        or not pending["backup_id"]
        or not isinstance(details, dict)
        or set(details) - {"before", "target", "source", "created_source"}
        or not {"before", "target", "source"}.issubset(details)
    ):
        raise ActualFinanceError("the recurring edit intent is invalid")
    before, target, source = (details[key] for key in ("before", "target", "source"))
    state_keys = {
        "name",
        "rule",
        "account",
        "payee",
        "amount",
        "amountOp",
        "date",
        "category_id",
        "notes",
        "posts_transaction",
    }
    for state in (before, target):
        if (
            not isinstance(state, dict)
            or set(state) != state_keys
            or not all(
                isinstance(state[key], str)
                for key in ("name", "rule", "account", "payee", "amountOp", "category_id", "notes")
            )
            or not all(state[key] for key in ("name", "rule", "account", "payee"))
            or type(state["amount"]) is not int
            or state["amountOp"] != "is"
            or not isinstance(state["date"], dict)
            or type(state["posts_transaction"]) is not bool
        ):
            raise ActualFinanceError("the recurring edit intent is invalid")
    if (
        before["name"] != target["name"]
        or before["rule"] != target["rule"]
        or before["category_id"] != overlay.get("category_id")
        or before["notes"] != overlay.get("notes")
        or before["posts_transaction"] != overlay.get("posts_transaction")
        or (overlay.get("version") in {2, 3} and before["payee"] != overlay.get("payee_id"))
        or actual_migration._created_schedule_source(
            {"version": 2, "source": source}, link.source_id
        )
        is None
        or source["name"] != before["name"]
        or source["account_id"] != target["account"]
        or source["amount_minor"] != target["amount"]
        or actual_migration._schedule_date(source)
        != actual_migration._normalized_schedule_date(target["date"])
    ):
        raise ActualFinanceError("the recurring edit intent is invalid")
    created_source = (
        overlay.get("source") if overlay["version"] == 2 else overlay.get("created_source")
    )
    if details.get("created_source") != created_source or ("created_source" in details) != (
        created_source is not None
    ):
        raise ActualFinanceError("the recurring edit provenance is invalid")
    fingerprint = _request_fingerprint(
        "edit_recurring_schedule",
        {"source_id": link.source_id, "actual_id": link.actual_id, "details": details},
    )
    if pending.get("fingerprint") != fingerprint:
        raise ActualFinanceError("the recurring edit intent fingerprint changed")
    return details


def _recurring_edit_state(row: dict, details: dict, actual: dict) -> bool:
    """Report whether Actual is at a bridge-recognized step of the saved edit."""
    from services import actual_migration

    before, target = details["before"], details["target"]
    posting = row.get("posting") or {}
    if row.get("completed") or not posting.get("guarded"):
        return False
    if (
        not any(
            item.get("id") == target["account"] and not item.get("closed")
            for item in actual.get("accounts") or []
        )
        or not any(
            item.get("id") == target["payee"]
            and not item.get("transfer_acct")
            and str(item.get("name") or "").strip() == details["source"]["payee"]
            for item in actual.get("payees") or []
        )
        or (
            target["category_id"]
            and not any(
                item.get("id") == target["category_id"] and not item.get("is_income")
                for item in actual.get("categories") or []
            )
        )
    ):
        return False

    def schedule_matches(state: dict) -> bool:
        return (
            all(
                row.get(key) == state[key]
                for key in ("name", "rule", "account", "payee", "amount", "amountOp")
            )
            and isinstance(row.get("date"), dict)
            and row["date"].get("endMode", "never") == "never"
            and not row["date"].get("skipWeekend")
            and actual_migration._normalized_schedule_date(row["date"])
            == actual_migration._normalized_schedule_date(state["date"])
        )

    def rule_matches(state: dict) -> bool:
        return (
            str(posting.get("category") or "") == state["category_id"]
            and str(posting.get("notes") or "") == state["notes"]
        )

    prior_schedule, final_schedule = schedule_matches(before), schedule_matches(target)
    prior_rule, final_rule = rule_matches(before), rule_matches(target)
    active = row.get("posts_transaction")
    return bool(
        type(active) is bool
        and (prior_schedule or final_schedule)
        and (prior_rule or final_rule)
        and (not final_rule or prior_rule or final_schedule)
        and (
            not active
            or (prior_schedule and prior_rule and before["posts_transaction"])
            or (final_schedule and final_rule and target["posts_transaction"])
        )
    )


@authority_guarded
def recurring_schedules(
    db: Session,
    *,
    actual: dict | None = None,
    bridge_request=None,
) -> list[dict]:
    """Read Actual auto-post schedules without consulting the frozen recurring ledger."""
    actual = actual if actual is not None else inspect(db, bridge_request=bridge_request)
    _account_sources, account_public, _account_metadata = _maps(db, "account")
    _recurring_sources, recurring_public, recurring_metadata = _maps(db, "recurring")
    recurring_links = _links(db, "recurring")
    pending_links = [link for link in recurring_links if _link_metadata(link).get("_intent")]
    pending_markers = set()
    for link in pending_links:
        pending = _link_metadata(link)["_intent"]
        details = pending.get("details") if isinstance(pending, dict) else None
        source = details.get("source") if isinstance(details, dict) else None
        if isinstance(source, dict) and isinstance(source.get("name"), str):
            pending_markers.add(source["name"])
    subscription_ids = {link.actual_id for link in _links(db, "subscription")}
    payee_names = {row.get("id"): row.get("name") for row in actual.get("payees") or []}
    category_names = {
        str(row.get("id")): str(row.get("name") or "")
        for row in actual.get("categories") or []
        if row.get("id")
    }
    spending_category_ids = {
        str(row.get("id"))
        for row in actual.get("categories") or []
        if row.get("id") and not row.get("is_income")
    }
    spending_name_ids = {}
    for category_id in spending_category_ids:
        spending_name_ids.setdefault(category_names[category_id], set()).add(category_id)
    seen = set()
    rows = []
    for row in actual.get("schedules") or []:
        actual_id = str(row.get("id") or "")
        if not actual_id or actual_id in seen:
            raise ActualFinanceError("the Actual schedule identity is missing or duplicated")
        seen.add(actual_id)
        if row.get("name") in pending_markers:
            continue
        if actual_id in subscription_ids or (
            not row.get("posts_transaction") and actual_id not in recurring_public
        ):
            continue
        source_id = recurring_public.get(actual_id, actual_id)
        metadata = recurring_metadata.get(actual_id, {})
        pending = metadata.get("_update_intent")
        pending_action = pending.get("action") if isinstance(pending, dict) else None
        repair_pending = pending_action == "repair_recurring_schedule"
        posting_pending = pending_action == "set_recurring_posting"
        edit_pending = pending_action == "edit_recurring_schedule"
        edit_details = None
        if edit_pending:
            link = next((item for item in recurring_links if item.actual_id == actual_id), None)
            if link is None:
                raise ActualFinanceError("the recurring edit link is missing")
            edit_details = _recurring_edit_intent(link, metadata)
        elif pending is not None and (
            not isinstance(pending, dict)
            or pending.get("version") != 1
            or not (repair_pending or posting_pending)
            or not isinstance(pending.get("category_id"), str)
            or not isinstance(pending.get("backup_id"), str)
            or not pending.get("backup_id")
            or (repair_pending and type(pending.get("posts_transaction")) is not bool)
            or (
                posting_pending
                and (
                    type(pending.get("previous_posts_transaction")) is not bool
                    or type(pending.get("target_posts_transaction")) is not bool
                    or not isinstance(pending.get("notes"), str)
                )
            )
        ):
            raise ActualFinanceError("a recurring schedule write intent is invalid")
        category = str(metadata.get("category") or "")
        notes = str(metadata.get("notes") or "")
        overlay = metadata.get("canonical_schedule")
        if overlay is not None and (
            not isinstance(overlay, dict) or overlay.get("version") not in {1, 2, 3}
        ):
            raise ActualFinanceError("the recurring schedule repair record is invalid")
        if isinstance(overlay, dict) and overlay.get("version") in {2, 3} and not edit_pending:
            from services import actual_migration

            link = next(
                (
                    item
                    for item in _links(db, "recurring")
                    if item.source_id == source_id and item.actual_id == actual_id
                ),
                None,
            )
            if link is None:
                raise ActualFinanceError("the recurring schedule creation link is missing")
            try:
                actual_migration.schedule_repair_baseline(db, link, actual)
            except actual_migration.ActualMigrationError as exc:
                raise ActualFinanceError(str(exc)) from exc
        if edit_pending:
            posting = row.get("posting") or {}
            category_id = str(posting.get("category") or "")
            category = category_names.get(category_id, "")
            notes = str(posting.get("notes") or "")
        elif isinstance(overlay, dict) and overlay.get("version") in {1, 2, 3}:
            posting = row.get("posting") or {}
            category_id = overlay.get("category_id")
            expected_states = [overlay.get("posts_transaction")]
            if posting_pending and pending["previous_posts_transaction"] == overlay.get(
                "posts_transaction"
            ):
                expected_states.append(pending["target_posts_transaction"])
            if (
                not isinstance(category_id, str)
                or not isinstance(overlay.get("notes"), str)
                or type(overlay.get("posts_transaction")) is not bool
                or not posting.get("guarded")
                or str(posting.get("category") or "") != category_id
                or str(posting.get("notes") or "") != str(overlay.get("notes") or "")
                or (
                    posting_pending
                    and (
                        pending["previous_posts_transaction"] != overlay.get("posts_transaction")
                        or pending["category_id"] != category_id
                        or pending["notes"] != overlay["notes"]
                    )
                )
                or bool(row.get("posts_transaction")) not in expected_states
            ):
                raise ActualFinanceError("the repaired Actual schedule posting rule changed")
            if category_id and category_id not in category_names:
                raise ActualFinanceError("a repaired Actual schedule category is missing")
            category = category_names.get(category_id, "")
            notes = str(overlay.get("notes") or "")
        elif metadata.get("posting_rule_version") == 1:
            posting = row.get("posting") or {}
            if not posting.get("guarded"):
                raise ActualFinanceError("a managed Actual schedule posting rule is missing")
            category_id = str(posting.get("category") or "")
            if category_id and category_id not in category_names:
                raise ActualFinanceError("a managed Actual schedule category is missing")
            category = category_names.get(category_id, "")
            notes = str(posting.get("notes") or "")
        posting = row.get("posting") or {}
        managed_rule = bool(
            actual_id in recurring_public
            and not edit_pending
            and row.get("account")
            and not row.get("completed")
            and posting.get("guarded")
            and (not posting.get("category") or posting.get("category") in spending_category_ids)
            and (
                overlay
                or (
                    metadata.get("posting_rule_version") == 1
                    and category == str(metadata.get("category") or "")
                    and notes == str(metadata.get("notes") or "")
                    and (
                        not posting.get("category") or len(spending_name_ids.get(category, ())) == 1
                    )
                )
            )
        )
        name = str(row.get("name") or "").strip()
        migrated_name = "Alles recurring: "
        migrated_suffix = f" [{source_id[:8]}]"
        if (
            actual_id in recurring_public
            and name.startswith(migrated_name)
            and name.endswith(migrated_suffix)
        ):
            name = name[len(migrated_name) : -len(migrated_suffix)]
        payee = (
            str(overlay["source"]["payee"])
            if isinstance(overlay, dict) and overlay.get("version") in {2, 3} and not edit_pending
            else name or str(payee_names.get(row.get("payee")) or category or "recurring")
        )
        if edit_pending:
            payee = str(payee_names.get(row.get("payee")) or "")

        amount_op = str(row.get("amountOp") or "is")
        minor = row.get("amount")
        amount = (
            _major_from_minor(minor, "schedule amount")
            if amount_op in {"is", "isapprox"} and type(minor) is int
            else None
        )
        amount_kind = (
            "approx"
            if amount_op == "isapprox" and amount is not None
            else "exact"
            if amount_op == "is" and amount is not None
            else "range"
            if amount_op == "isbetween"
            else "variable"
        )
        rule = row.get("date")
        cycle, cycle_days = "actual", 0
        if (
            isinstance(rule, dict)
            and rule.get("endMode", "never") == "never"
            and not rule.get("skipWeekend")
        ):
            try:
                candidate, days, start = _schedule_cycle(rule)
                _schedule_anchor(rule, date.fromisoformat(start))
                cycle, cycle_days = candidate, days
            except (ActualFinanceError, ValueError):
                pass
        next_date = (
            _required_date(row["next_date"], "schedule next date") if row.get("next_date") else ""
        )
        rows.append(
            {
                "id": source_id,
                "account_id": account_public.get(row.get("account"), row.get("account") or ""),
                "amount": amount,
                "amount_kind": amount_kind,
                "category": category,
                "payee": payee,
                "notes": notes,
                "cycle": cycle,
                "cycle_days": cycle_days,
                "next_date": next_date,
                "active": bool(row.get("posts_transaction")) and not bool(row.get("completed")),
                "last_posted": "",
                "repair_needed": bool(
                    repair_pending
                    or (
                        actual_id in recurring_public
                        and row.get("account")
                        and not row.get("completed")
                        and metadata.get("posting_rule_version") != 1
                        and not overlay
                    )
                ),
                "repair_pending": repair_pending,
                "repair_category_id": pending["category_id"] if repair_pending else "",
                "manageable": managed_rule and not repair_pending,
                "posting_pending": posting_pending,
                "posting_target_active": pending["target_posts_transaction"]
                if posting_pending
                else None,
                "edit_pending": edit_pending,
                "edit_needs_review": edit_pending
                and not _recurring_edit_state(row, edit_details, actual),
            }
        )
    for actual_id, metadata in recurring_metadata.items():
        if metadata.get("_update_intent") and actual_id not in seen:
            pending = metadata["_update_intent"]
            if not isinstance(pending, dict) or pending.get("action") != "edit_recurring_schedule":
                raise ActualFinanceError("a recurring schedule repair lost its Actual schedule")
            link = next((item for item in recurring_links if item.actual_id == actual_id), None)
            if link is None:
                raise ActualFinanceError("the recurring edit link is missing")
            details = _recurring_edit_intent(link, metadata)
            source = details["source"]
            rows.append(
                {
                    "id": link.source_id,
                    "account_id": account_public.get(source["account_id"], source["account_id"]),
                    "amount": _major_from_minor(source["amount_minor"], "pending schedule amount"),
                    "amount_kind": "exact",
                    "category": category_names.get(details["before"]["category_id"], ""),
                    "payee": source["payee"],
                    "notes": details["before"]["notes"],
                    "cycle": source["cycle"],
                    "cycle_days": source["cycle_days"],
                    "next_date": source["next_date"],
                    "active": None,
                    "last_posted": "",
                    "repair_needed": False,
                    "repair_pending": False,
                    "repair_category_id": "",
                    "manageable": False,
                    "posting_pending": False,
                    "posting_target_active": None,
                    "edit_pending": True,
                    "edit_needs_review": True,
                }
            )
    if pending_links:
        from services import actual_migration

    for link in pending_links:
        metadata = _link_metadata(link)
        pending = metadata.get("_intent")
        details = pending.get("details") if isinstance(pending, dict) else None
        source = details.get("source") if isinstance(details, dict) else None
        if (
            not isinstance(pending, dict)
            or not isinstance(details, dict)
            or not isinstance(source, dict)
        ):
            raise ActualFinanceError("a recurring creation intent is invalid")
        if (
            link.actual_id
            or set(metadata) != {"_intent"}
            or pending.get("version") != 1
            or pending.get("fingerprint")
            != _request_fingerprint("create_recurring_schedule", details)
            or actual_migration._created_schedule_source(
                {"version": 2, "source": source}, link.source_id
            )
            is None
            or source.get("name") != f"Alles recurring {link.source_id}"
            or not isinstance(details.get("public_account_id"), str)
            or not isinstance(details.get("category_id"), str)
            or not isinstance(details.get("notes"), str)
            or type(details.get("active")) is not bool
            or type(pending.get("attempted", False)) is not bool
            or not isinstance(pending.get("backup_id", ""), str)
        ):
            raise ActualFinanceError("a recurring creation intent is invalid")
        marker_rows = [
            item for item in actual.get("schedules") or [] if item.get("name") == source["name"]
        ]
        if len(marker_rows) > 1:
            raise ActualFinanceError("a recurring creation marker is not unique")
        rows.append(
            {
                "id": link.source_id,
                "account_id": details["public_account_id"],
                "amount": _major_from_minor(source["amount_minor"], "pending recurring amount"),
                "amount_kind": "exact",
                "category": category_names.get(details["category_id"], ""),
                "payee": source["payee"],
                "notes": details["notes"],
                "cycle": source["cycle"],
                "cycle_days": source["cycle_days"],
                "next_date": source["next_date"],
                "active": bool(marker_rows and marker_rows[0].get("posts_transaction")),
                "last_posted": "",
                "repair_needed": False,
                "repair_pending": False,
                "repair_category_id": "",
                "manageable": False,
                "posting_pending": False,
                "posting_target_active": None,
                "create_pending": True,
                "create_needs_review": bool(pending.get("attempted") and not marker_rows),
            }
        )
    return sorted(rows, key=lambda row: (row["next_date"] or "9999-12-31", row["id"]))


def _recurring_create_details(
    db: Session, values: dict, request_id: str, *, bridge_request=None
) -> dict:
    from services import actual_migration

    source_id = _request_source_id(request_id, "recurring")
    if uuid.UUID(source_id).version != 4:
        raise ActualFinanceError("recurring request_id must be a version-4 UUID")
    _assert_no_unresolved_creation_intents(db, "account")
    current = inspect(db, bridge_request=bridge_request)
    public_account_id = str(values.get("account_id") or "").strip()
    source_to_actual, _actual_to_source, _metadata = _maps(db, "account")
    account_id = source_to_actual.get(public_account_id, public_account_id)
    account_rows = [
        row
        for row in current.get("accounts") or []
        if row.get("id") == account_id and not row.get("closed")
    ]
    if len(account_rows) != 1:
        raise ActualFinanceError("recurring creation requires one open Actual account")
    category_id = str(values.get("category_id") or "").strip()
    categories = (
        [
            row
            for row in current.get("categories") or []
            if row.get("id") == category_id and not row.get("is_income")
        ]
        if category_id
        else []
    )
    if category_id and len(categories) != 1:
        raise ActualFinanceError("recurring creation requires an existing spending category")
    category_name = str(categories[0].get("name") or "") if categories else ""
    legacy_category = str(values.get("category") or "").strip()
    if legacy_category and legacy_category != category_name:
        raise ActualFinanceError("recurring creation needs the exact Actual category id")
    payee = str(values.get("payee") or "").strip() or category_name or "recurring"
    cycle = str(values.get("cycle") or "monthly").strip().lower()
    raw_cycle_days = values.get("cycle_days", 30)
    if type(raw_cycle_days) is not int or raw_cycle_days < 1:
        raise ActualFinanceError("recurring cycle_days must be a positive integer")
    next_date = _required_date(values.get("next_date"), "recurring next date")
    if type(values.get("active", True)) is not bool:
        raise ActualFinanceError("recurring creation needs an explicit active choice")
    amount_minor = _minor(values.get("amount", 0), "recurring amount")
    _major_from_minor(amount_minor, "recurring amount")
    source = {
        "kind": "recurring",
        "id": source_id,
        "name": f"Alles recurring {source_id}",
        "account_id": account_id,
        "payee": payee,
        "amount_minor": amount_minor,
        "next_date": next_date,
        "cycle": cycle,
        "cycle_days": raw_cycle_days,
        "active": True,
        "posts_transaction": True,
    }
    if cycle in {"monthly", "quarterly"}:
        source["anchor_day"] = date.fromisoformat(next_date).day
    try:
        actual_migration._schedule_date(source)
    except actual_migration.ActualMigrationError as exc:
        raise ActualFinanceError(str(exc)) from exc
    return {
        "source": source,
        "public_account_id": public_account_id,
        "category_id": category_id,
        "notes": str(values.get("notes") or "").strip(),
        "active": values.get("active", True),
    }


def _continue_recurring_create(
    db: Session,
    link: ActualEntityLink,
    details: dict,
    fingerprint: str,
    *,
    bridge_request=None,
    backup_fn=managed_actual.backup,
) -> dict:
    from services import actual_migration

    source = details.get("source")
    if (
        not isinstance(source, dict)
        or source.get("id") != link.source_id
        or source.get("name") != f"Alles recurring {link.source_id}"
        or actual_migration._created_schedule_source(
            {"version": 2, "source": source}, link.source_id
        )
        is None
        or not isinstance(details.get("public_account_id"), str)
        or not isinstance(details.get("category_id"), str)
        or not isinstance(details.get("notes"), str)
        or type(details.get("active")) is not bool
        or fingerprint != _request_fingerprint("create_recurring_schedule", details)
    ):
        raise ActualFinanceError("the recurring creation intent is invalid")
    metadata = _link_metadata(link)
    pending = metadata.get("_intent")
    if (
        link.actual_id
        or not isinstance(pending, dict)
        or pending.get("version") != 1
        or pending.get("fingerprint") != fingerprint
        or pending.get("details") != details
        or type(pending.get("attempted", False)) is not bool
        or not isinstance(pending.get("backup_id", ""), str)
        or set(metadata) != {"_intent"}
    ):
        raise ActualFinanceError("the recurring creation intent is invalid")
    capabilities = _request(db, {"command": "capabilities"}, bridge_request=bridge_request)
    if not isinstance(capabilities, dict) or capabilities.get("create_recurring_schedule") != 1:
        raise ActualFinanceError("update managed Actual before creating recurring schedules")
    current = inspect(db, bridge_request=bridge_request)
    marker = source["name"]
    markers = [row for row in current.get("schedules") or [] if row.get("name") == marker]
    if len(markers) > 1:
        raise ActualFinanceError("the recurring creation marker is not unique")
    attempted = pending.get("attempted", False)
    if attempted and not markers:
        raise ActualFinanceError(
            "the attempted recurring creation marker is missing; review it first"
        )
    if not attempted and markers:
        raise ActualFinanceError("the recurring creation marker was already in Actual")
    if not pending.get("backup_id"):
        try:
            backup = backup_fn()
        except managed_actual.ManagedActualError as exc:
            raise ActualFinanceUnavailable(str(exc)) from exc
        backup_id = str(backup.get("backup_id") or "") if isinstance(backup, dict) else ""
        if not isinstance(backup, dict) or backup.get("ok") is not True or not backup_id:
            raise ActualFinanceError("recurring creation needs a verified Actual backup")
        pending["backup_id"] = backup_id
        link.metadata_json = json.dumps({"_intent": pending}, sort_keys=True, separators=(",", ":"))
        db.commit()
    if not attempted:
        pending["attempted"] = True
        link.metadata_json = json.dumps({"_intent": pending}, sort_keys=True, separators=(",", ":"))
        db.commit()
    result = _request(
        db,
        {
            "command": "write",
            "action": "create_recurring_schedule",
            "operation_marker": marker,
            "schedule": source,
            "category_id": details["category_id"],
            "notes": details["notes"],
            "active": details["active"],
            "allow_create": not attempted,
        },
        bridge_request=bridge_request,
    )
    actual_id = str(result.get("id") or "") if isinstance(result, dict) else ""
    payee_id = str(result.get("payee_id") or "") if isinstance(result, dict) else ""
    if not actual_id or not payee_id or result.get("posts_transaction") is not details["active"]:
        raise ActualFinanceError("Actual recurring creation did not return its confirmed identity")
    confirmed = inspect(db, bridge_request=bridge_request)
    matching = [row for row in confirmed.get("schedules") or [] if row.get("name") == marker]
    if len(matching) != 1 or matching[0].get("id") != actual_id:
        raise ActualFinanceError("Actual recurring creation marker changed; review it first")
    overlay = {
        "version": 2,
        "source": source,
        "payee_id": payee_id,
        "category_id": details["category_id"],
        "notes": details["notes"],
        "posts_transaction": details["active"],
    }
    _finish_intent(link, actual_id, fingerprint, {"canonical_schedule": overlay})
    db.flush()
    try:
        actual_migration.schedule_repair_baseline(db, link, confirmed)
        if not actual_migration._restored_schedule_matches(
            matching[0],
            source,
            account_actual_ids={source["account_id"]: source["account_id"]},
            payee_names={row.get("id"): row.get("name") for row in confirmed.get("payees") or []},
            categories={row.get("id"): row for row in confirmed.get("categories") or []},
            overlay=overlay,
        ):
            raise ActualFinanceError("Actual recurring creation could not be verified")
    except (ActualFinanceError, actual_migration.ActualMigrationError):
        db.rollback()
        raise
    db.commit()
    rows = [row for row in recurring_schedules(db, actual=confirmed) if row["id"] == link.source_id]
    if len(rows) != 1:
        raise ActualFinanceError("created recurring schedule could not be read back")
    return rows[0]


@authority_guarded
def create_recurring_schedule(
    db: Session,
    values: dict,
    *,
    request_id: str,
    bridge_request=None,
    backup_fn=managed_actual.backup,
) -> dict:
    details = _recurring_create_details(db, values, request_id, bridge_request=bridge_request)
    fingerprint = _request_fingerprint("create_recurring_schedule", details)
    link, completed = _begin_intent(
        db, "recurring", details["source"]["id"], fingerprint, details, {}
    )
    if completed:
        rows = [
            row
            for row in recurring_schedules(db, bridge_request=bridge_request)
            if row["id"] == link.source_id
        ]
        if len(rows) != 1:
            raise ActualFinanceError("completed recurring creation could not be read back")
        return rows[0]
    return _continue_recurring_create(
        db, link, details, fingerprint, bridge_request=bridge_request, backup_fn=backup_fn
    )


@authority_guarded
def retry_recurring_schedule(
    db: Session,
    source_id: str,
    *,
    bridge_request=None,
    backup_fn=managed_actual.backup,
) -> dict:
    links = [row for row in _links(db, "recurring") if row.source_id == source_id]
    if len(links) != 1:
        raise ActualFinanceError("recurring creation intent was not found")
    link = links[0]
    metadata = _link_metadata(link)
    if metadata.get("_request_fingerprint") and not metadata.get("_intent"):
        rows = [
            row
            for row in recurring_schedules(db, bridge_request=bridge_request)
            if row["id"] == source_id
        ]
        if len(rows) != 1:
            raise ActualFinanceError("completed recurring creation could not be read back")
        return rows[0]
    pending = metadata.get("_intent")
    if not isinstance(pending, dict) or not isinstance(pending.get("details"), dict):
        raise ActualFinanceError("recurring creation intent was not found")
    return _continue_recurring_create(
        db,
        link,
        pending["details"],
        pending.get("fingerprint"),
        bridge_request=bridge_request,
        backup_fn=backup_fn,
    )


def _continue_recurring_edit(db: Session, link: ActualEntityLink, *, bridge_request=None) -> dict:
    from services import actual_migration

    metadata = _link_metadata(link)
    details = _recurring_edit_intent(link, metadata)
    capabilities = _request(db, {"command": "capabilities"}, bridge_request=bridge_request)
    if not isinstance(capabilities, dict) or capabilities.get("edit_recurring_schedule") != 1:
        raise ActualFinanceError("update managed Actual before editing recurring schedules")
    current = inspect(db, bridge_request=bridge_request)
    existing = [row for row in current.get("schedules") or [] if row.get("id") == link.actual_id]
    if len(existing) != 1 or not _recurring_edit_state(existing[0], details, current):
        raise ActualFinanceError("the pending recurring edit needs provider review before retry")
    result = _request(
        db,
        {
            "command": "write",
            "action": "edit_recurring_schedule",
            "actual_id": link.actual_id,
            "before": details["before"],
            "target": details["target"],
        },
        bridge_request=bridge_request,
    )
    target = details["target"]
    if (
        not isinstance(result, dict)
        or result.get("id") != link.actual_id
        or result.get("payee_id") != target["payee"]
        or result.get("posts_transaction") is not target["posts_transaction"]
    ):
        raise ActualFinanceError("Actual recurring edit did not return its confirmed identity")
    confirmed = inspect(db, bridge_request=bridge_request)
    matches = [row for row in confirmed.get("schedules") or [] if row.get("id") == link.actual_id]
    if len(matches) != 1 or not _recurring_edit_state(matches[0], details, confirmed):
        raise ActualFinanceError("Actual recurring edit changed outside its saved states")
    source = details["source"]
    overlay = {
        "version": 3,
        "source": source,
        "payee_id": target["payee"],
        "category_id": target["category_id"],
        "notes": target["notes"],
        "posts_transaction": target["posts_transaction"],
    }
    if "created_source" in details:
        overlay["created_source"] = details["created_source"]
    updated = {**metadata, "canonical_schedule": overlay}
    updated.pop("_update_intent", None)
    link.metadata_json = json.dumps(updated, sort_keys=True, separators=(",", ":"))
    db.flush()
    try:
        actual_migration.schedule_repair_baseline(db, link, confirmed)
        if (
            not actual_migration._restored_schedule_matches(
                matches[0],
                source,
                account_actual_ids={source["account_id"]: source["account_id"]},
                payee_names={
                    row.get("id"): row.get("name") for row in confirmed.get("payees") or []
                },
                categories={row.get("id"): row for row in confirmed.get("categories") or []},
                overlay=overlay,
            )
            or matches[0].get("rule") != target["rule"]
        ):
            raise ActualFinanceError("Actual recurring edit could not be confirmed")
        readback = [
            row for row in recurring_schedules(db, actual=confirmed) if row["id"] == link.source_id
        ]
        if len(readback) != 1:
            raise ActualFinanceError("the edited recurring schedule could not be read back")
    except (ActualFinanceError, actual_migration.ActualMigrationError):
        db.rollback()
        raise
    db.commit()
    return readback[0]


@authority_guarded
def edit_recurring_schedule(
    db: Session,
    source_id: str,
    values: dict,
    *,
    bridge_request=None,
    backup_fn=managed_actual.backup,
) -> dict:
    """Edit one linked guarded schedule after saving the exact provider intent."""
    from services import actual_migration

    links = [row for row in _links(db, "recurring") if row.source_id == source_id]
    if len(links) != 1 or not links[0].actual_id:
        raise ActualFinanceError("only a linked Alles schedule can be edited in Finance")
    link = links[0]
    metadata = _link_metadata(link)
    overlay = metadata.get("canonical_schedule")
    if not isinstance(overlay, dict) or overlay.get("version") not in {1, 2, 3}:
        raise ActualFinanceError("repair this old schedule before editing it")
    if metadata.get("_intent") or metadata.get("_update_intent"):
        raise ActualFinanceError("finish the pending recurring write before editing again")
    required = {
        "account_id",
        "payee_id",
        "amount",
        "category_id",
        "notes",
        "cycle",
        "cycle_days",
        "next_date",
        "active",
    }
    if (
        not isinstance(values, dict)
        or set(values) != required
        or any(
            type(values[key]) is not str
            for key in ("account_id", "payee_id", "category_id", "notes", "cycle", "next_date")
        )
        or type(values["cycle_days"]) is not int
        or values["cycle_days"] < 1
        or type(values["active"]) is not bool
    ):
        raise ActualFinanceError("recurring edit requires one complete target")
    capabilities = _request(db, {"command": "capabilities"}, bridge_request=bridge_request)
    if not isinstance(capabilities, dict) or capabilities.get("edit_recurring_schedule") != 1:
        raise ActualFinanceError("update managed Actual before editing recurring schedules")
    actual = inspect(db, bridge_request=bridge_request)
    try:
        actual_migration.schedule_repair_baseline(
            db, link, actual, allow_overlay=overlay.get("version") == 1
        )
    except actual_migration.ActualMigrationError as exc:
        raise ActualFinanceError(str(exc)) from exc
    rows = [row for row in recurring_schedules(db, actual=actual) if row["id"] == source_id]
    schedules = [row for row in actual.get("schedules") or [] if row.get("id") == link.actual_id]
    if len(rows) != 1 or not rows[0]["manageable"] or len(schedules) != 1:
        raise ActualFinanceError("the linked recurring schedule needs review before editing")
    schedule = schedules[0]
    account_sources, _public_accounts, _metadata = _maps(db, "account")
    account_id = account_sources.get(values["account_id"].strip(), values["account_id"].strip())
    accounts = [
        row
        for row in actual.get("accounts") or []
        if row.get("id") == account_id and not row.get("closed")
    ]
    payee_id = values["payee_id"].strip()
    payees = [
        row
        for row in actual.get("payees") or []
        if row.get("id") == payee_id and not row.get("transfer_acct")
    ]
    category_id = values["category_id"].strip()
    categories = (
        [
            row
            for row in actual.get("categories") or []
            if row.get("id") == category_id and not row.get("is_income")
        ]
        if category_id
        else []
    )
    if len(accounts) != 1 or len(payees) != 1 or not str(payees[0].get("name") or "").strip():
        raise ActualFinanceError("recurring edit requires an open account and existing payee")
    if category_id and len(categories) != 1:
        raise ActualFinanceError("recurring edit requires an existing spending category")
    next_date = _required_date(values["next_date"], "recurring next date")
    amount_minor = _minor(values["amount"], "recurring amount")
    _major_from_minor(amount_minor, "recurring amount")
    source = {
        "kind": "recurring",
        "id": source_id,
        "name": schedule["name"],
        "account_id": account_id,
        "payee": str(payees[0]["name"]).strip(),
        "amount_minor": amount_minor,
        "next_date": next_date,
        "cycle": values["cycle"].strip().lower(),
        "cycle_days": values["cycle_days"],
        "active": True,
        "posts_transaction": True,
    }
    if source["cycle"] in {"monthly", "quarterly", "yearly"}:
        source["anchor_day"] = date.fromisoformat(next_date).day
    try:
        recurrence = actual_migration._schedule_date(source)
    except actual_migration.ActualMigrationError as exc:
        raise ActualFinanceError(str(exc)) from exc
    if (
        actual_migration._created_schedule_source({"version": 2, "source": source}, source_id)
        is None
    ):
        raise ActualFinanceError("the recurring edit target cannot be validated")
    raw_date = schedule.get("date")
    if (
        not isinstance(raw_date, dict)
        or raw_date.get("endMode", "never") != "never"
        or raw_date.get("skipWeekend")
    ):
        raise ActualFinanceError("the current Actual recurrence cannot be edited safely")
    before = {
        key: schedule.get(key) for key in ("name", "rule", "account", "payee", "amount", "amountOp")
    }
    before.update(
        {
            "date": {"endMode": "never", **raw_date},
            "category_id": overlay["category_id"],
            "notes": overlay["notes"],
            "posts_transaction": overlay["posts_transaction"],
        }
    )
    target = {
        **before,
        "account": account_id,
        "payee": payee_id,
        "amount": amount_minor,
        "date": {**recurrence, "endMode": "never"},
        "category_id": category_id,
        "notes": values["notes"].strip(),
        "posts_transaction": values["active"],
    }
    if all(
        before[key] == target[key]
        for key in (
            "name",
            "rule",
            "account",
            "payee",
            "amount",
            "amountOp",
            "category_id",
            "notes",
            "posts_transaction",
        )
    ) and actual_migration._normalized_schedule_date(
        before["date"]
    ) == actual_migration._normalized_schedule_date(target["date"]):
        return rows[0]
    details = {"before": before, "target": target, "source": source}
    created_source = (
        overlay.get("source") if overlay["version"] == 2 else overlay.get("created_source")
    )
    if created_source is not None:
        details["created_source"] = created_source
    fingerprint = _request_fingerprint(
        "edit_recurring_schedule",
        {"source_id": source_id, "actual_id": link.actual_id, "details": details},
    )
    try:
        backup = backup_fn()
    except managed_actual.ManagedActualError as exc:
        raise ActualFinanceUnavailable(str(exc)) from exc
    backup_id = str(backup.get("backup_id") or "") if isinstance(backup, dict) else ""
    if not isinstance(backup, dict) or backup.get("ok") is not True or not backup_id:
        raise ActualFinanceError("recurring edit needs a verified Actual backup")
    metadata["_update_intent"] = {
        "version": 1,
        "action": "edit_recurring_schedule",
        "fingerprint": fingerprint,
        "backup_id": backup_id,
        "details": details,
    }
    link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    db.commit()
    return _continue_recurring_edit(db, link, bridge_request=bridge_request)


@authority_guarded
def retry_recurring_edit(db: Session, source_id: str, *, bridge_request=None) -> dict:
    links = [row for row in _links(db, "recurring") if row.source_id == source_id]
    if len(links) != 1 or not links[0].actual_id:
        raise ActualFinanceError("the recurring edit intent was not found")
    _recurring_edit_intent(links[0], _link_metadata(links[0]))
    return _continue_recurring_edit(db, links[0], bridge_request=bridge_request)


@authority_guarded
def repair_recurring_schedule(
    db: Session,
    source_id: str,
    category_id: str,
    *,
    bridge_request=None,
    backup_fn=managed_actual.backup,
) -> dict:
    """Upgrade one old linked schedule without changing its Actual identity."""
    from services import actual_migration

    matches = [row for row in _links(db, "recurring") if row.source_id == source_id]
    if len(matches) != 1 or not matches[0].actual_id:
        raise ActualFinanceError("only a linked old recurring schedule can be repaired")
    link = matches[0]
    metadata = _link_metadata(link)
    category_id = str(category_id or "").strip()
    if metadata.get("posting_rule_version") == 1:
        raise ActualFinanceError("this recurring schedule already has its posting rule")
    overlay = metadata.get("canonical_schedule")
    if overlay is not None:
        if not isinstance(overlay, dict) or overlay.get("version") != 1:
            raise ActualFinanceError("the recurring schedule repair record is invalid")
        if overlay.get("category_id") != category_id:
            raise ActualFinanceError(
                "this recurring schedule is already repaired with another category"
            )
        rows = [
            row
            for row in recurring_schedules(db, bridge_request=bridge_request)
            if row["id"] == source_id
        ]
        if len(rows) != 1:
            raise ActualFinanceError("the repaired recurring schedule is missing")
        return rows[0]
    if metadata.get("category") and not category_id:
        raise ActualFinanceError("choose an existing Actual spending category for this schedule")
    fingerprint = _request_fingerprint(
        "repair_recurring_schedule",
        {
            "source_id": source_id,
            "actual_id": link.actual_id,
            "category_id": category_id,
            "notes": str(metadata.get("notes") or ""),
        },
    )
    pending = metadata.get("_update_intent")
    if pending is not None and (not isinstance(pending, dict) or not pending):
        raise ActualFinanceError("the recurring schedule repair intent is invalid")
    pending = pending or {}
    was_pending = bool(pending)
    if pending and (
        pending.get("version") != 1
        or pending.get("action") != "repair_recurring_schedule"
        or pending.get("fingerprint") != fingerprint
        or pending.get("category_id") != category_id
        or type(pending.get("posts_transaction")) is not bool
        or not isinstance(pending.get("backup_id"), str)
        or not pending["backup_id"]
    ):
        raise ActualFinanceError("schedule repair retry does not match its durable intent")

    try:
        capabilities = _request(db, {"command": "capabilities"}, bridge_request=bridge_request)
    except ActualFinanceUnavailable as exc:
        raise ActualFinanceUnavailable(
            "managed Actual is unavailable or needs its bridge update before schedule repair"
        ) from exc
    if not isinstance(capabilities, dict) or capabilities.get("repair_recurring_schedule") != 1:
        raise ActualFinanceError("update managed Actual before repairing recurring schedules")

    actual = inspect(db, bridge_request=bridge_request)
    try:
        baseline = actual_migration.schedule_repair_baseline(db, link, actual)
    except actual_migration.ActualMigrationError as exc:
        raise ActualFinanceError(str(exc)) from exc
    if pending and pending["posts_transaction"] != bool(baseline.get("posts_transaction")):
        raise ActualFinanceError("schedule repair retry does not match its original posting state")
    rows = [row for row in actual.get("schedules") or [] if row.get("id") == link.actual_id]
    schedule = rows[0]
    if schedule.get("completed") or not schedule.get("account"):
        raise ActualFinanceError("the Actual schedule cannot post and needs review")
    if type(schedule.get("amount")) is not int or not schedule["amount"]:
        raise ActualFinanceError("the Actual schedule amount needs review")
    category_matches = (
        [
            row
            for row in actual.get("categories") or []
            if row.get("id") == category_id and not row.get("is_income")
        ]
        if category_id
        else []
    )
    if category_id and len(category_matches) != 1:
        raise ActualFinanceError("choose an existing Actual spending category for this schedule")
    posting = schedule.get("posting") or {}
    configured = bool(
        posting.get("guarded")
        and str(posting.get("category") or "") == category_id
        and str(posting.get("notes") or "") == str(metadata.get("notes") or "")
    )
    if not posting.get("pristine") and not (pending and configured):
        raise ActualFinanceError("the Actual schedule rule changed; review it before repair")
    if not pending and bool(schedule.get("posts_transaction")) != bool(
        baseline.get("posts_transaction")
    ):
        raise ActualFinanceError(
            "the Actual schedule posting state changed; review it before repair"
        )

    if not pending:
        try:
            backup = backup_fn()
        except managed_actual.ManagedActualError as exc:
            raise ActualFinanceUnavailable(str(exc)) from exc
        backup_id = str(backup.get("backup_id") or "") if isinstance(backup, dict) else ""
        if not isinstance(backup, dict) or backup.get("ok") is not True or not backup_id:
            raise ActualFinanceError("schedule repair needs a verified Actual backup")
        metadata["_update_intent"] = {
            "version": 1,
            "action": "repair_recurring_schedule",
            "fingerprint": fingerprint,
            "category_id": category_id,
            "posts_transaction": bool(schedule.get("posts_transaction")),
            "backup_id": backup_id,
        }
        link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        db.commit()
        pending = metadata["_update_intent"]

    expected_schedule = {
        key: schedule.get(key) for key in ("name", "account", "payee", "amount", "amountOp", "date")
    }
    result = _request(
        db,
        {
            "command": "write",
            "action": "repair_recurring_schedule",
            "actual_id": link.actual_id,
            "category_id": category_id,
            "notes": str(metadata.get("notes") or ""),
            "expected_schedule": expected_schedule,
            "original_posts_transaction": pending["posts_transaction"],
            "allow_paused_retry": was_pending,
        },
        bridge_request=bridge_request,
    )
    if not isinstance(result, dict) or result.get("id") != link.actual_id:
        raise ActualFinanceError("Actual schedule repair result did not match its identity")
    confirmed = inspect(db, bridge_request=bridge_request)
    try:
        actual_migration.schedule_repair_baseline(db, link, confirmed)
    except actual_migration.ActualMigrationError as exc:
        raise ActualFinanceError(str(exc)) from exc
    confirmed_rows = [
        row for row in confirmed.get("schedules") or [] if row.get("id") == link.actual_id
    ]
    if len(confirmed_rows) != 1:
        raise ActualFinanceError("Actual schedule repair lost its identity")
    current = confirmed_rows[0]
    current_posting = current.get("posting") or {}
    if (
        bool(current.get("posts_transaction")) != pending["posts_transaction"]
        or not current_posting.get("guarded")
        or str(current_posting.get("category") or "") != category_id
        or str(current_posting.get("notes") or "") != str(metadata.get("notes") or "")
    ):
        raise ActualFinanceError("Actual schedule repair could not be confirmed")
    metadata.pop("_update_intent", None)
    metadata["canonical_schedule"] = {
        "version": 1,
        "category_id": category_id,
        "notes": str(metadata.get("notes") or ""),
        "posts_transaction": pending["posts_transaction"],
    }
    link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    db.commit()
    readback = [row for row in recurring_schedules(db, actual=confirmed) if row["id"] == source_id]
    if len(readback) != 1:
        raise ActualFinanceError("the repaired recurring schedule could not be read back")
    return readback[0]


@authority_guarded
def set_recurring_posting(
    db: Session,
    source_id: str,
    active: bool,
    *,
    bridge_request=None,
    backup_fn=managed_actual.backup,
) -> dict:
    """Pause or resume one linked, guarded Actual schedule by its posting flag."""
    from services import actual_migration

    if type(active) is not bool:
        raise ActualFinanceError("recurring posting needs an explicit active choice")
    matches = [row for row in _links(db, "recurring") if row.source_id == source_id]
    if len(matches) != 1 or not matches[0].actual_id:
        raise ActualFinanceError("only a linked Alles schedule can be paused in Finance")
    link = matches[0]
    metadata = _link_metadata(link)
    overlay = metadata.get("canonical_schedule")
    if overlay is not None and (
        not isinstance(overlay, dict) or overlay.get("version") not in {1, 2, 3}
    ):
        raise ActualFinanceError("the recurring schedule posting record is invalid")
    if not overlay and metadata.get("posting_rule_version") != 1:
        raise ActualFinanceError("repair this old schedule before changing its posting state")
    pending = metadata.get("_update_intent")
    if pending is not None and (not isinstance(pending, dict) or not pending):
        raise ActualFinanceError("the recurring posting intent is invalid")
    pending = pending or {}
    was_pending = bool(pending)
    if pending and pending.get("action") != "set_recurring_posting":
        raise ActualFinanceError("finish the pending schedule repair before changing posting")
    try:
        capabilities = _request(db, {"command": "capabilities"}, bridge_request=bridge_request)
    except ActualFinanceUnavailable as exc:
        raise ActualFinanceUnavailable(
            "managed Actual is unavailable or needs its bridge update before pausing schedules"
        ) from exc
    if not isinstance(capabilities, dict) or capabilities.get("set_recurring_posting") != 1:
        raise ActualFinanceError("update managed Actual before pausing recurring schedules")

    actual = inspect(db, bridge_request=bridge_request)
    try:
        baseline = actual_migration.schedule_repair_baseline(
            db, link, actual, allow_overlay=bool(overlay)
        )
    except actual_migration.ActualMigrationError as exc:
        raise ActualFinanceError(str(exc)) from exc
    rows = [row for row in actual.get("schedules") or [] if row.get("id") == link.actual_id]
    if len(rows) != 1:
        raise ActualFinanceError("the linked Actual schedule is missing")
    schedule = rows[0]
    posting = schedule.get("posting") or {}
    category_id = str(posting.get("category") or "")
    notes = str(posting.get("notes") or "")
    category = next(
        (
            row
            for row in actual.get("categories") or []
            if row.get("id") == category_id and not row.get("is_income")
        ),
        None,
    )
    if (
        schedule.get("completed")
        or not schedule.get("account")
        or type(schedule.get("posts_transaction")) is not bool
        or not posting.get("guarded")
        or (category_id and category is None)
    ):
        raise ActualFinanceError("the Actual schedule posting rule needs review")
    if overlay:
        if (
            overlay.get("category_id") != category_id
            or overlay.get("notes") != notes
            or type(overlay.get("posts_transaction")) is not bool
        ):
            raise ActualFinanceError("the Actual schedule posting rule changed; review it first")
        previous = overlay["posts_transaction"]
    else:
        if (str(category.get("name") or "") if category else "") != str(
            metadata.get("category") or ""
        ) or notes != str(metadata.get("notes") or ""):
            raise ActualFinanceError("the Actual schedule posting rule changed; review it first")
        if (
            category
            and sum(
                row.get("name") == category.get("name") and not row.get("is_income")
                for row in actual.get("categories") or []
            )
            != 1
        ):
            raise ActualFinanceError("the Actual schedule category is ambiguous; review it first")
        previous = bool(baseline.get("posts_transaction") and baseline.get("active"))
    fingerprint = _request_fingerprint(
        "set_recurring_posting",
        {
            "source_id": source_id,
            "actual_id": link.actual_id,
            "active": active,
            "previous": previous,
            "category_id": category_id,
            "notes": notes,
        },
    )
    if pending and (
        pending.get("version") != 1
        or pending.get("fingerprint") != fingerprint
        or pending.get("category_id") != category_id
        or pending.get("notes") != notes
        or pending.get("previous_posts_transaction") != previous
        or pending.get("target_posts_transaction") != active
        or not isinstance(pending.get("backup_id"), str)
        or not pending.get("backup_id")
    ):
        raise ActualFinanceError("recurring posting retry does not match its pending write")
    if not pending and schedule["posts_transaction"] != previous:
        raise ActualFinanceError("Actual schedule posting changed; review it before saving")
    if not pending and active == previous:
        rows = [row for row in recurring_schedules(db, actual=actual) if row["id"] == source_id]
        if len(rows) != 1:
            raise ActualFinanceError("the linked recurring schedule could not be read back")
        return rows[0]

    if not pending:
        try:
            backup = backup_fn()
        except managed_actual.ManagedActualError as exc:
            raise ActualFinanceUnavailable(str(exc)) from exc
        backup_id = str(backup.get("backup_id") or "") if isinstance(backup, dict) else ""
        if not isinstance(backup, dict) or backup.get("ok") is not True or not backup_id:
            raise ActualFinanceError("recurring posting needs a verified Actual backup")
        metadata["_update_intent"] = {
            "version": 1,
            "action": "set_recurring_posting",
            "fingerprint": fingerprint,
            "category_id": category_id,
            "notes": notes,
            "previous_posts_transaction": previous,
            "target_posts_transaction": active,
            "backup_id": backup_id,
        }
        link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        db.commit()
        pending = metadata["_update_intent"]

    expected_schedule = {
        key: schedule.get(key)
        for key in ("name", "account", "payee", "amount", "amountOp", "date", "rule")
    }
    result = _request(
        db,
        {
            "command": "write",
            "action": "set_recurring_posting",
            "actual_id": link.actual_id,
            "active": active,
            "category_id": category_id,
            "notes": notes,
            "previous_posts_transaction": pending["previous_posts_transaction"],
            "allow_retry": was_pending,
            "expected_schedule": expected_schedule,
        },
        bridge_request=bridge_request,
    )
    if (
        not isinstance(result, dict)
        or result.get("id") != link.actual_id
        or result.get("posts_transaction") is not active
    ):
        raise ActualFinanceError("Actual recurring posting result did not match the schedule")
    confirmed = inspect(db, bridge_request=bridge_request)
    try:
        actual_migration.schedule_repair_baseline(db, link, confirmed, allow_overlay=bool(overlay))
    except actual_migration.ActualMigrationError as exc:
        raise ActualFinanceError(str(exc)) from exc
    current = [row for row in confirmed.get("schedules") or [] if row.get("id") == link.actual_id]
    if len(current) != 1:
        raise ActualFinanceError("Actual recurring posting lost its schedule")
    current_posting = current[0].get("posting") or {}
    if (
        current[0].get("posts_transaction") is not active
        or not current_posting.get("guarded")
        or str(current_posting.get("category") or "") != category_id
        or str(current_posting.get("notes") or "") != notes
    ):
        raise ActualFinanceError("Actual recurring posting could not be confirmed")
    metadata.pop("_update_intent", None)
    metadata["canonical_schedule"] = (
        {**overlay, "posts_transaction": active}
        if isinstance(overlay, dict) and overlay.get("version") in {2, 3}
        else {
            "version": 1,
            "category_id": category_id,
            "notes": notes,
            "posts_transaction": active,
        }
    )
    link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    db.commit()
    readback = [row for row in recurring_schedules(db, actual=confirmed) if row["id"] == source_id]
    if len(readback) != 1:
        raise ActualFinanceError("the recurring posting state could not be read back")
    return readback[0]


def forecast_schedules(db: Session, actual: dict, *, as_of: date) -> list[dict]:
    """Active posting schedules, excluding subscriptions forecast elsewhere."""
    _recurring_sources, recurring_public, recurring_metadata = _maps(db, "recurring")
    subscription_ids = {link.actual_id for link in _links(db, "subscription")}
    payee_names = {row.get("id"): row.get("name") for row in actual.get("payees") or []}
    rows = []
    for row in actual.get("schedules") or []:
        actual_id = str(row.get("id") or "")
        if (
            actual_id in subscription_ids
            or not row.get("posts_transaction")
            or row.get("completed")
        ):
            continue
        rule = row.get("date")
        if isinstance(rule, dict) and rule.get("endMode", "never") != "never":
            raise ActualFinanceError("the Actual schedule end rule cannot be forecast exactly")
        if isinstance(rule, dict) and rule.get("skipWeekend"):
            raise ActualFinanceError("the Actual schedule weekend rule cannot be forecast exactly")
        cycle, cycle_days, start_text = _schedule_cycle(rule)
        try:
            anchor = _schedule_anchor(rule, date.fromisoformat(start_text))
        except ValueError as exc:
            raise ActualFinanceError("the Actual schedule start date is invalid") from exc
        provider_next = row.get("next_date")
        if provider_next:
            next_text = _required_date(provider_next, "schedule next occurrence")
            if date.fromisoformat(next_text) <= as_of:
                provider_next = ""
        next_date = _next_schedule_due(rule, provider_next, today=as_of + timedelta(days=1))
        metadata = recurring_metadata.get(actual_id, {})
        rows.append(
            {
                "id": recurring_public.get(actual_id, actual_id),
                "next_date": next_date,
                "anchor_day": anchor,
                "cycle": cycle,
                "cycle_days": cycle_days,
                "amount": _major_from_minor(int(row.get("amount") or 0), "schedule amount"),
                "payee": payee_names.get(row.get("payee"))
                or str(row.get("name") or metadata.get("category") or "recurring"),
                "active": True,
            }
        )
    return rows


@authority_guarded
def subscription_schedules(
    db: Session,
    *,
    actual: dict | None = None,
    bridge_request=None,
) -> list[dict]:
    """Read linked subscriptions from their canonical Actual schedules."""
    actual = actual or inspect(db, bridge_request=bridge_request)
    state = _state(db)
    _account_sources, account_public, _account_metadata = _maps(db, "account")
    _subscription_sources, schedule_public, metadata = _maps(db, "subscription")
    rows = []
    for row in actual.get("schedules") or []:
        actual_id = str(row.get("id") or "")
        source_id = schedule_public.get(actual_id)
        if not source_id:
            continue
        cycle, cycle_days, _start = _schedule_cycle(row.get("date"))
        next_due = _next_schedule_due(row.get("date"), row.get("next_date"))
        amount_minor = abs(int(row.get("amount") or 0))
        schedule_metadata = metadata.get(actual_id, {})
        if row.get("account") and schedule_metadata.get("posting_rule_version") == 1:
            active = bool(row.get("posts_transaction"))
        else:
            active = bool(schedule_metadata.get("active", True))
        active = active and not bool(row.get("completed"))
        rows.append(
            {
                "id": source_id,
                "actual_id": actual_id,
                "name": str(row.get("name") or "subscription"),
                "price": _major_from_minor(amount_minor, "subscription price"),
                "currency": state.base_currency_code,
                "cycle": cycle,
                "cycle_days": cycle_days,
                "next_due": next_due,
                "active": active,
                "account_id": account_public.get(row.get("account"), row.get("account") or ""),
                "metadata": schedule_metadata,
            }
        )
    return rows


@authority_guarded
def budgets(
    db: Session,
    month: str,
    *,
    actual: dict | None = None,
    bridge_request=None,
) -> list[dict]:
    """Read persistent spending caps, not Actual's monthly assignments."""
    actual = actual or inspect(db, bridge_request=bridge_request)
    category_names = {
        str(row["id"]): str(row.get("name") or "uncategorized")
        for row in actual.get("categories") or []
        if row.get("id") and not row.get("is_income")
    }
    rows = []
    for link in _links(db, "budget_limit"):
        metadata = _link_metadata(link)
        if metadata.get("_delete_intent") or metadata.get("_deleted"):
            continue
        if metadata.get("_update_intent"):
            raise ActualFinanceError(
                "a persistent budget update is uncertain; retry the same update before reading it"
            )
        category_id = link.actual_id
        limit_minor = metadata.get("limit_minor")
        if (
            category_id not in category_names
            or isinstance(limit_minor, bool)
            or not isinstance(limit_minor, int)
            or abs(limit_minor) > MAX_CENT_SAFE_MINOR
        ):
            raise ActualFinanceError("a persistent budget cap is not safely linked to Actual")
        rows.append(
            {
                "id": f"actual-budget-cap:{category_id}",
                "actual_id": category_id,
                "category": category_names[category_id],
                "tag": "",
                "limit_amt": _major_from_minor(limit_minor, "persistent budget cap"),
            }
        )
    for link in _links(db, "tag_budget"):
        metadata = _link_metadata(link)
        if metadata.get("_delete_intent") or metadata.get("_deleted"):
            continue
        tag = str(metadata.get("tag") or "").strip().lower()
        limit_minor = metadata.get("limit_minor")
        if (
            not tag
            or isinstance(limit_minor, bool)
            or not isinstance(limit_minor, int)
            or abs(limit_minor) > MAX_CENT_SAFE_MINOR
        ):
            raise ActualFinanceError("a canonical tag budget sidecar is invalid")
        rows.append(
            {
                "id": f"actual-tag-budget:{link.source_id}",
                "actual_id": link.actual_id,
                "category": "",
                "tag": tag,
                "limit_amt": _major_from_minor(limit_minor, "tag budget amount"),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("tag") or row.get("category") or "").casefold(),
            str(row.get("id") or ""),
        ),
    )


def _validated_budget_month(value) -> str:
    month = str(value or "")
    if len(month) != 7 or month[4] != "-" or not month.replace("-", "").isdigit():
        raise ActualFinanceError("budget month must be YYYY-MM")
    try:
        parsed = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise ActualFinanceError("budget month must be a valid calendar month") from None
    if parsed.strftime("%Y-%m") != month:
        raise ActualFinanceError("budget month must be a valid calendar month")
    return month


def _funding_target_data(db: Session, categories: list[dict]) -> list[dict]:
    """Attach ID-bound targets and expose old unbound rows for owner review."""
    by_id = {row["category_id"]: row for row in categories}
    claimed_sources = set()
    linked_categories = set()
    unbound = []
    for link in _links(db, "funding_target"):
        claimed_sources.add(link.source_id)
        metadata = _link_metadata(link)
        if metadata.get("_deleted"):
            continue
        amount_minor = metadata.get("amount_minor")
        target_date = metadata.get("target_date")
        if (
            type(amount_minor) is not int
            or amount_minor <= 0
            or amount_minor > MAX_CENT_SAFE_MINOR
            or not isinstance(target_date, str)
        ):
            raise ActualFinanceError("a funding target needs review")
        target = by_id.get(link.actual_id)
        if target is None:
            unbound.append(
                {
                    "id": link.source_id,
                    "category": str(metadata.get("category_name") or "missing category"),
                    "amount": _major_from_minor(amount_minor, "funding target"),
                    "date": target_date,
                    "reason": "linked category is missing",
                }
            )
            continue
        if link.actual_id in linked_categories:
            raise ActualFinanceError("more than one funding target is linked to a category")
        linked_categories.add(link.actual_id)
        amount = _major_from_minor(amount_minor, "funding target")
        target["target"] = {
            "id": link.source_id,
            "amount": amount,
            "date": target_date,
            "funded": round(max(0.0, target["available"]) / amount, 4),
        }
    for row in db.query(FundingTarget).order_by(FundingTarget.category, FundingTarget.id).all():
        if row.id in claimed_sources:
            continue
        amount_minor = _minor(row.amount, "old funding target")
        if amount_minor <= 0:
            raise ActualFinanceError("an old funding target needs review")
        unbound.append(
            {
                "id": row.id,
                "category": row.category,
                "amount": _major_from_minor(amount_minor, "old funding target"),
                "date": row.target_date or "",
                "reason": "choose an Actual category",
            }
        )
    return unbound


@authority_guarded
def envelope(db: Session, month: str, *, bridge_request=None) -> dict:
    """Read Actual's own budget-month totals and category balances."""
    month = _validated_budget_month(month)
    selected = _request(
        db,
        {"command": "budget_month", "month": month},
        bridge_request=bridge_request,
    )
    if (
        not isinstance(selected, dict)
        or selected.get("month") != month
        or not isinstance(selected.get("categoryGroups"), list)
    ):
        raise ActualFinanceError("Actual budget month is incomplete")

    def amount(row: dict, key: str) -> float:
        value = row.get(key)
        if type(value) is not int:
            raise ActualFinanceError("Actual budget month is incomplete")
        return _major_from_minor(value, f"budget {key}")

    rows = []
    seen_category_ids = set()
    for group in selected["categoryGroups"]:
        if not isinstance(group, dict) or not isinstance(group.get("categories"), list):
            raise ActualFinanceError("Actual budget month is incomplete")
        if group.get("is_income"):
            continue
        for category in group["categories"]:
            if not isinstance(category, dict):
                raise ActualFinanceError("Actual budget month is incomplete")
            if category.get("is_income"):
                continue
            name = str(category.get("name") or "").strip()
            category_id = str(category.get("id") or "").strip()
            if not name or not category_id or category_id in seen_category_ids:
                raise ActualFinanceError("Actual budget month is incomplete")
            seen_category_ids.add(category_id)
            rows.append(
                {
                    "category_id": category_id,
                    "category": name,
                    "group": str(group.get("name") or ""),
                    "assigned": amount(category, "budgeted"),
                    "spent": -amount(category, "spent"),
                    "available": amount(category, "balance"),
                    "target": None,
                }
            )
    rows.sort(
        key=lambda row: (row["group"].casefold(), row["category"].casefold(), row["category_id"])
    )
    unbound_targets = _funding_target_data(db, rows)
    pending_assignments = []
    for link in _links(db, "budget_assignment"):
        pending = _link_metadata(link).get("_update_intent") or {}
        if not pending or pending.get("month") != month:
            continue
        category_id = str(pending.get("category_id") or "")
        category = next((row for row in rows if row["category_id"] == category_id), None)
        if (
            category is None
            or type(pending.get("amount_minor")) is not int
            or type(pending.get("previous_minor")) is not int
        ):
            raise ActualFinanceError("a pending Actual assignment needs review")
        pending_assignments.append(
            {
                "category_id": category_id,
                "category": category["category"],
                "assigned": _major_from_minor(pending["amount_minor"], "pending assignment"),
                "expected_assigned": _major_from_minor(
                    pending["previous_minor"], "previous assignment"
                ),
            }
        )
    return {
        "month": month,
        "income": amount(selected, "totalIncome"),
        "assigned_total": -amount(selected, "totalBudgeted"),
        "to_be_budgeted": amount(selected, "toBudget"),
        "categories": rows,
        "unbound_targets": unbound_targets,
        "pending_assignments": pending_assignments,
    }


@authority_guarded
def set_funding_target(
    db: Session,
    category_id: str,
    amount,
    target_date: str = "",
    *,
    bridge_request=None,
) -> dict:
    """Write one local target; Actual's monthly assignment is never changed."""
    category_id = str(category_id or "").strip()
    amount_minor = _minor(amount, "funding target")
    if amount_minor < 0:
        raise ActualFinanceError("funding target cannot be negative; use zero to clear it")
    target_date = str(target_date or "").strip() if amount_minor else ""
    if target_date:
        if not _ISO_DATE.fullmatch(target_date):
            raise ActualFinanceError("funding target date must be YYYY-MM-DD")
        target_date = _required_date(target_date, "funding target date")
    if not category_id:
        raise ActualFinanceError("an existing spending category is required")
    current = envelope(db, date.today().strftime("%Y-%m"), bridge_request=bridge_request)
    category = next(
        (row for row in current["categories"] if row["category_id"] == category_id), None
    )
    if category is None:
        raise ActualFinanceError("funding target requires an existing spending category")
    links = _links(db, "funding_target")
    active = [row for row in links if row.actual_id == category_id]
    if len(active) > 1:
        raise ActualFinanceError("more than one funding target is linked to this category")
    retired = [
        row
        for row in links
        if not row.actual_id and _deletion_target(_link_metadata(row)) == category_id
    ]
    link = active[0] if active else retired[0] if retired else None
    if amount_minor == 0:
        if link is None:
            return {"category_id": category_id, "target": None}
        if link in active:
            metadata = _link_metadata(link)
            metadata["_deleted"] = {"version": 1, "actual_id": category_id}
            link.actual_id = ""
            link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
            db.commit()
        return {"category_id": category_id, "target": None}
    if link is None:
        link = ActualEntityLink(
            run_id=_state(db).active_run_id,
            entity_kind="funding_target",
            source_id=f"actual-native:funding_target:{category_id}",
            actual_id=category_id,
        )
        db.add(link)
    metadata = _link_metadata(link)
    metadata.pop("_deleted", None)
    metadata.update(
        {
            "category_name": category["category"],
            "amount_minor": amount_minor,
            "target_date": target_date,
            "source": metadata.get("source") or "alles_funding_target",
        }
    )
    link.actual_id = category_id
    link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    db.commit()
    return {
        "category_id": category_id,
        "target": {
            "amount": _major_from_minor(amount_minor, "funding target"),
            "date": metadata["target_date"],
        },
    }


@authority_guarded
def bind_funding_target(
    db: Session,
    target_id: str,
    category_id: str,
    *,
    bridge_request=None,
) -> dict:
    """Bind a preserved old target only after the owner picks an Actual ID."""
    target_id = str(target_id or "").strip()
    category_id = str(category_id or "").strip()
    if not target_id or not category_id:
        raise ActualFinanceError("target and spending category are required")
    current = envelope(db, date.today().strftime("%Y-%m"), bridge_request=bridge_request)
    category = next(
        (row for row in current["categories"] if row["category_id"] == category_id), None
    )
    if category is None:
        raise ActualFinanceError("funding target requires an existing spending category")
    links = _links(db, "funding_target")
    matches = [row for row in links if row.source_id == target_id]
    if len(matches) > 1:
        raise ActualFinanceError("funding target has more than one identity link")
    link = matches[0] if matches else None
    if (
        link is not None
        and link.actual_id == category_id
        and not _link_metadata(link).get("_deleted")
    ):
        metadata = _link_metadata(link)
        return {
            "category_id": category_id,
            "target": {
                "amount": _major_from_minor(metadata["amount_minor"], "funding target"),
                "date": metadata["target_date"],
            },
        }
    if category["target"]:
        raise ActualFinanceError("that category already has a funding target")
    if link is None:
        old = db.get(FundingTarget, target_id)
        if old is None:
            raise ActualFinanceError("old funding target no longer exists")
        amount_minor = _minor(old.amount, "old funding target")
        if amount_minor <= 0:
            raise ActualFinanceError("old funding target amount needs review")
        link = ActualEntityLink(
            run_id=_state(db).active_run_id,
            entity_kind="funding_target",
            source_id=old.id,
            actual_id=category_id,
            metadata_json=json.dumps(
                {
                    "category_name": old.category,
                    "amount_minor": amount_minor,
                    "target_date": old.target_date or "",
                    "source": "legacy_funding_target",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        db.add(link)
    else:
        metadata = _link_metadata(link)
        if metadata.get("_deleted"):
            raise ActualFinanceError("deleted funding target cannot be rebound")
        link.actual_id = category_id
    db.commit()
    metadata = _link_metadata(link)
    return {
        "category_id": category_id,
        "target": {
            "amount": _major_from_minor(metadata["amount_minor"], "funding target"),
            "date": metadata["target_date"],
        },
    }


@authority_guarded
def set_envelope_assignment(
    db: Session,
    month: str,
    category_id: str,
    amount,
    expected_amount,
    *,
    bridge_request=None,
) -> dict:
    """Set one Actual month slot, keeping the provider result recoverable."""
    month = _validated_budget_month(month)
    category_id = str(category_id or "").strip()
    if not category_id:
        raise ActualFinanceError("an existing spending category is required")
    if expected_amount is None:
        raise ActualFinanceError("the previous assigned amount is required; reload Finance")
    amount_minor = _minor(amount, "assigned amount")
    expected_minor = _minor(expected_amount, "previous assigned amount")
    for cap in _links(db, "budget_limit"):
        cap_metadata = _link_metadata(cap)
        if cap_metadata.get("_update_intent") or (
            cap_metadata.get("_delete_intent") and cap_metadata.get("managed_month")
        ):
            raise ActualFinanceError(
                "an older spending-cap write is uncertain; finish that cap retry before assigning money"
            )
    target = f"{month}:{category_id}"
    fingerprint = _request_fingerprint(
        "set_envelope_assignment",
        {"target": target, "amount_minor": amount_minor, "expected_minor": expected_minor},
    )

    current_month = envelope(db, month, bridge_request=bridge_request)
    category = next(
        (row for row in current_month["categories"] if row["category_id"] == category_id),
        None,
    )
    if category is None:
        raise ActualFinanceError("assignment requires one existing spending category in Actual")
    current_minor = _minor(category["assigned"], "current assigned amount")
    matches = [
        row
        for row in _links(db, "budget_assignment")
        if row.actual_id == target or _deletion_target(_link_metadata(row)) == target
    ]
    if len(matches) > 1:
        raise ActualFinanceError("Actual assignment has more than one identity link")
    if current_minor == amount_minor == 0 and (
        not matches or _link_metadata(matches[0]).get("_deleted")
    ):
        return {
            "category_id": category_id,
            "category": category["category"],
            "month": month,
            "assigned": 0.0,
        }
    link = (
        matches[0]
        if matches
        else _ensure_deletion_link(db, "budget_assignment", f"actual-budget:{target}", target)
    )
    metadata = _link_metadata(link)
    if metadata.get("_delete_intent"):
        raise ActualFinanceError("Actual assignment deletion is incomplete")
    pending = metadata.get("_update_intent") or {}
    if pending:
        if pending.get("fingerprint") != fingerprint:
            raise ActualFinanceError("assignment retry does not match its pending write")
        if current_minor not in {pending.get("previous_minor"), amount_minor}:
            raise ActualFinanceError("assignment changed during an uncertain write; review Actual")
    elif current_minor != amount_minor:
        if current_minor != expected_minor:
            raise ActualFinanceError("assignment changed; reload Finance before saving")
        metadata.pop("_deleted", None)
        metadata["_update_intent"] = {
            "version": 1,
            "fingerprint": fingerprint,
            "month": month,
            "category_id": category_id,
            "previous_minor": current_minor,
            "amount_minor": amount_minor,
        }
        link.actual_id = target
        link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        db.commit()

    if current_minor != amount_minor:
        result = _request(
            db,
            {
                "command": "write",
                "action": "set_budget_assignment",
                "month": month,
                "category_id": category_id,
                "amount_minor": amount_minor,
            },
            bridge_request=bridge_request,
        )
        if (
            not isinstance(result, dict)
            or result.get("category_id") != category_id
            or result.get("amount_minor") != amount_minor
        ):
            raise ActualFinanceError("Actual assignment write could not be confirmed")

    confirmed = envelope(db, month, bridge_request=bridge_request)
    confirmed_category = next(
        (row for row in confirmed["categories"] if row["category_id"] == category_id), None
    )
    if confirmed_category is None or _minor(confirmed_category["assigned"]) != amount_minor:
        raise ActualFinanceError("Actual assignment write could not be confirmed")
    metadata = _link_metadata(link)
    metadata.pop("_update_intent", None)
    metadata.pop("_deleted", None)
    metadata["canonical_assignment"] = {"amount_minor": amount_minor}
    link.actual_id = target
    link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    db.commit()
    return {
        "category_id": category_id,
        "category": confirmed_category["category"],
        "month": month,
        "assigned": confirmed_category["assigned"],
    }


@authority_guarded
def set_budget(
    db: Session,
    month: str,
    category: str,
    amount,
    *,
    bridge_request=None,
) -> dict:
    name = str(category or "").strip()
    if not name:
        raise ActualFinanceError("budget category is required")
    month = _validated_budget_month(month)
    amount_minor = _minor(amount, "budget amount")
    link = _budget_limit_link(db, category_name=name)
    prior_metadata = _link_metadata(link) if link else {}
    if prior_metadata.get("_delete_intent"):
        raise ActualFinanceError("the persistent budget cap is pending deletion")
    pending = prior_metadata.get("_update_intent") or {}
    if pending:
        # Finish a durable write started by the older cap/assignment contract.
        previous_month = str(prior_metadata.get("managed_month") or "")
        previous_category_id = str(link.actual_id or "")
        intent_details = {
            "category": name,
            "amount_minor": amount_minor,
            "month": month,
            "previous_category_id": previous_category_id,
            "previous_month": previous_month,
        }
        fingerprint = _request_fingerprint("set_budget", intent_details)
        if pending.get("fingerprint") != fingerprint:
            raise ActualFinanceError("budget retry does not match its durable update intent")
        result = _request(
            db,
            {
                "command": "write",
                "action": "set_budget",
                "month": month,
                "category_name": name,
                "amount_minor": amount_minor,
            },
            bridge_request=bridge_request,
        )
        category_id = str(result.get("category_id") or "")
        if not category_id:
            raise ActualFinanceError("Actual did not return the budget category")
        if previous_month and previous_month != month:
            _request(
                db,
                {
                    "command": "write",
                    "action": "clear_budget",
                    "month": previous_month,
                    "category_id": previous_category_id or category_id,
                },
                bridge_request=bridge_request,
            )
        link.actual_id = category_id
        link.metadata_json = json.dumps(
            {
                "category": name,
                "limit_minor": amount_minor,
                "source": str(prior_metadata.get("source") or "alles_persistent_cap"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        db.commit()
        return {
            "id": f"actual-budget-cap:{category_id}",
            "actual_id": category_id,
            "category": name,
            "tag": "",
            "limit_amt": _major_from_minor(amount_minor, "budget amount"),
        }

    actual = inspect(db, bridge_request=bridge_request)
    matches = [
        row
        for row in actual.get("categories") or []
        if str(row.get("id") or "")
        and not row.get("is_income")
        and str(row.get("name") or "").strip().casefold() == name.casefold()
    ]
    if len(matches) != 1:
        raise ActualFinanceError("budget cap requires one existing spending category in Actual")
    category_id = str(matches[0]["id"])
    category_name = str(matches[0]["name"]).strip()
    actual_ids = {str(row.get("id") or "") for row in actual.get("categories") or []}
    if link and link.actual_id not in actual_ids:
        raise ActualFinanceError("an existing budget cap is not safely linked to Actual")
    link = _budget_limit_link(db, category_id=category_id)
    if link and _link_metadata(link).get("_delete_intent"):
        raise ActualFinanceError("the persistent budget cap is pending deletion")
    metadata = {
        "category": category_name,
        "limit_minor": amount_minor,
        "source": str(
            (_link_metadata(link) if link else {}).get("source") or "alles_persistent_cap"
        ),
    }
    if link:
        link.actual_id = category_id
        link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    else:
        source_key = hashlib.sha256(category_id.encode()).hexdigest()
        _record_link(
            db,
            "budget_limit",
            f"actual-budget-cap:{source_key}",
            category_id,
            metadata,
        )
    db.commit()
    return {
        "id": f"actual-budget-cap:{category_id}",
        "actual_id": category_id,
        "category": category_name,
        "tag": "",
        "limit_amt": _major_from_minor(amount_minor, "budget amount"),
    }


@authority_guarded
def set_tag_budget(db: Session, tag: str, amount) -> dict:
    name = str(tag or "").strip().lower()
    if not name:
        raise ActualFinanceError("budget tag is required")
    amount_minor = _minor(amount, "tag budget amount")
    link = _tag_budget_link(db, name)
    if link is None:
        source_id = str(uuid.uuid4())
        actual_id = f"sidecar:tag_budget:{source_id}"
        _record_link(
            db,
            "tag_budget",
            source_id,
            actual_id,
            {"tag": name, "limit_minor": amount_minor},
        )
        db.flush()
        link = _tag_budget_link(db, name)
    else:
        link.metadata_json = json.dumps(
            {"tag": name, "limit_minor": amount_minor},
            sort_keys=True,
            separators=(",", ":"),
        )
    if link is None:
        raise ActualFinanceError("canonical tag budget link was not created")
    db.commit()
    return {
        "id": f"actual-tag-budget:{link.source_id}",
        "actual_id": link.actual_id,
        "category": "",
        "tag": name,
        "limit_amt": _major_from_minor(amount_minor, "tag budget amount"),
    }


@authority_guarded
def clear_budget(db: Session, public_id: str, *, bridge_request=None) -> dict:
    tag_prefix = "actual-tag-budget:"
    cap_prefix = "actual-budget-cap:"
    prefix = "actual-budget:"
    raw = str(public_id or "")
    if raw.startswith(tag_prefix):
        source_id = raw.removeprefix(tag_prefix)
        link = next((row for row in _links(db, "tag_budget") if row.source_id == source_id), None)
        if not link:
            raise ActualFinanceError("canonical tag budget was not found")
        target, already_deleted = _begin_link_deletion(db, link)
        if already_deleted:
            return {"ok": True}
        _finish_link_deletion(link, target)
        db.commit()
        return {"ok": True}
    if raw.startswith(cap_prefix):
        category_id = raw.removeprefix(cap_prefix)
        if not category_id:
            raise ActualFinanceError("canonical budget cap id is invalid")
        link = _budget_limit_link(db, category_id=category_id)
        if link is None:
            raise ActualFinanceError("canonical budget cap was not found")
        metadata = _link_metadata(link)
        if metadata.get("_update_intent"):
            raise ActualFinanceError(
                "a persistent budget update is uncertain; retry the same update before deleting it"
            )
        if metadata.get("_deleted"):
            return {"ok": True}
        if metadata.get("_delete_intent"):
            deletion_target = _deletion_target(metadata)
            managed_month = str(metadata.get("managed_month") or "")
            if not deletion_target:
                raise ActualFinanceError("canonical budget cap deletion target is missing")
            if managed_month:
                _request(
                    db,
                    {
                        "command": "write",
                        "action": "clear_budget",
                        "month": managed_month,
                        "category_id": deletion_target,
                    },
                    bridge_request=bridge_request,
                )
        else:
            deletion_target = str(link.actual_id or "")
            if not deletion_target:
                raise ActualFinanceError("canonical budget cap deletion target is missing")
        metadata.pop("managed_month", None)
        link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        _finish_link_deletion(link, deletion_target)
        db.commit()
        return {"ok": True}
    if not raw.startswith(prefix):
        raise ActualFinanceError("canonical budget id is invalid")
    remainder = raw.removeprefix(prefix)
    if len(remainder) < 9 or remainder[4] != "-" or remainder[7] != ":":
        raise ActualFinanceError("canonical budget id is invalid")
    month, category_id = remainder[:7], remainder[8:]
    if not category_id:
        raise ActualFinanceError("canonical budget id is invalid")
    assignment_target = f"{month}:{category_id}"
    assignment_link = _ensure_deletion_link(
        db,
        "budget_assignment",
        raw,
        assignment_target,
    )
    deletion_target, already_deleted = _begin_link_deletion(db, assignment_link)
    if already_deleted:
        current = inspect(db, bridge_request=bridge_request)
        selected = next(
            (row for row in current.get("budget_months") or [] if row.get("month") == month),
            None,
        )
        current_amount = 0
        for group in (
            (selected or {}).get("categoryGroups") or (selected or {}).get("category_groups") or []
        ):
            category = next(
                (
                    row
                    for row in group.get("categories") or []
                    if str(row.get("id") or "") == category_id
                ),
                None,
            )
            if category is not None:
                current_amount = int(category.get("budgeted") or 0)
                break
        if current_amount == 0:
            return {"ok": True}
        metadata = _link_metadata(assignment_link)
        metadata.pop("_deleted", None)
        assignment_link.actual_id = assignment_target
        assignment_link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        db.commit()
        deletion_target, already_deleted = _begin_link_deletion(db, assignment_link)
        if already_deleted:
            raise ActualFinanceError("canonical budget deletion could not be resumed")
    assignment_month, separator, assignment_category = deletion_target.partition(":")
    if not separator or not assignment_month or not assignment_category:
        raise ActualFinanceError("canonical budget deletion target is invalid")
    _request(
        db,
        {
            "command": "write",
            "action": "clear_budget",
            "month": assignment_month,
            "category_id": assignment_category,
        },
        bridge_request=bridge_request,
    )
    _finish_link_deletion(assignment_link, deletion_target)
    db.commit()
    return {"ok": True}


@authority_guarded
def create_account(
    db: Session,
    values: dict,
    *,
    request_id: str,
    bridge_request=None,
) -> dict:
    state = _state(db)
    opening = values.get("opening", 0)
    _account_currency(values.get("currency"), state.base_currency_code)
    kind = str(values.get("kind") or "checking")
    low_balance = _major_from_minor(
        _minor(values.get("low_balance", 0), "low balance"), "low balance"
    )
    name = str(values.get("name") or "account").strip() or "account"
    opening_minor = _minor(opening, "opening balance")
    request_details = {
        "name": name,
        "offbudget": kind == "investment",
        "initial_balance_minor": opening_minor,
        "color": str(values.get("color") or "accent"),
        "low_balance": low_balance,
    }
    fingerprint = _request_fingerprint("create_account", request_details)
    base_text = format(Decimal(opening_minor) / 100, "f")
    evidence = {
        "original_amount_text": base_text,
        "original_currency_code": state.base_currency_code,
        "base_amount_text": base_text,
        "base_currency_code": state.base_currency_code,
        "rate_text": "1",
        "rate_date": "",
        "source": "actual_identity",
        "account_kind": kind,
        "color": request_details["color"],
        "low_balance": low_balance,
        "canonical_account": {
            "name": name,
            "offbudget": kind == "investment",
            "closed": False,
            "opening_minor": opening_minor,
        },
    }
    source_id = _request_source_id(request_id, "account")
    intent, completed = _begin_intent(
        db,
        "account",
        source_id,
        fingerprint,
        request_details,
        evidence,
    )
    source_id = intent.source_id
    if completed:
        try:
            return next(
                row
                for row in accounts(db, bridge_request=bridge_request, _source_ids={source_id})
                if row["id"] == source_id
            )
        except StopIteration as exc:
            raise ActualFinanceError("completed account create target was not found") from exc
    actual_id = intent.actual_id
    if not actual_id:
        marker = f"Alles pending {source_id}"
        current = inspect(db, bridge_request=bridge_request)
        matches = [row for row in current.get("accounts") or [] if row.get("name") == marker]
        if len(matches) > 1:
            raise ActualFinanceError("pending Actual account marker is not unique")
        if matches:
            actual_id = str(matches[0].get("id") or "")
        else:
            result = _request(
                db,
                {
                    "command": "write",
                    "action": "create_account",
                    "account": {
                        "name": marker,
                        "offbudget": kind == "investment",
                        "closed": False,
                    },
                    "operation_marker": marker,
                    "initial_balance_minor": opening_minor,
                },
                bridge_request=bridge_request,
            )
            actual_id = str(result.get("id") or "")
        if not actual_id:
            raise ActualFinanceError("Actual did not return the created account")
        intent.actual_id = actual_id
        db.commit()
    _request(
        db,
        {
            "command": "write",
            "action": "update_account",
            "actual_id": actual_id,
            "fields": {"name": name, "offbudget": kind == "investment", "closed": False},
        },
        bridge_request=bridge_request,
    )
    _finish_intent(intent, actual_id, fingerprint, evidence)
    db.commit()
    return next(
        row
        for row in accounts(db, bridge_request=bridge_request, _source_ids={source_id})
        if row["id"] == source_id
    )


@authority_guarded
def update_account(db: Session, public_id: str, values: dict, *, bridge_request=None) -> dict:
    actual_id = _resolve(db, "account", public_id, bridge_request=bridge_request)
    state = _state(db)
    _source_to_actual, actual_to_source, metadata = _maps(db, "account")
    updated_metadata = dict(metadata.get(actual_id, {}))
    updated_metadata.pop("_update_intent", None)
    current = inspect(db, bridge_request=bridge_request)
    current_row = next(
        (row for row in current.get("accounts") or [] if row.get("id") == actual_id),
        None,
    )
    if current_row is None:
        raise ActualFinanceError("canonical account update target was not found")
    fields = {}
    if "name" in values:
        fields["name"] = str(values["name"] or "account").strip() or "account"
    if "kind" in values:
        kind = str(values["kind"] or "checking")
        fields["offbudget"] = kind == "investment"
        updated_metadata["account_kind"] = kind
    if "archived" in values:
        fields["closed"] = bool(values["archived"])
    if "opening" in values:
        raise ActualFinanceError(
            "opening balance cannot be edited after Actual cutover; add an adjustment transaction"
        )
    if "currency" in values:
        _account_currency(values["currency"], state.base_currency_code)
    if "color" in values:
        updated_metadata["color"] = str(values["color"] or "accent")
    if "low_balance" in values:
        updated_metadata["low_balance"] = _major_from_minor(
            _minor(values["low_balance"], "low balance"), "low balance"
        )
    previous_canonical = updated_metadata.get("canonical_account")
    opening_minor = (
        previous_canonical.get("opening_minor") if isinstance(previous_canonical, dict) else None
    )
    if opening_minor is None:
        opening_minor = _minor(
            updated_metadata.get("base_amount_text", 0),
            "opening balance",
        )
    canonical = {
        "name": str(current_row.get("name") or "account"),
        "offbudget": bool(current_row.get("offbudget")),
        "closed": bool(current_row.get("closed")),
        "opening_minor": opening_minor,
    }
    canonical.update(fields)
    updated_metadata["canonical_account"] = canonical
    source_id = actual_to_source.get(actual_id, public_id)
    fingerprint = _request_fingerprint(
        "update_account",
        {"actual_id": actual_id, "fields": fields, "metadata": updated_metadata},
    )
    link = (
        db.query(ActualEntityLink)
        .filter_by(
            run_id=_state(db).active_run_id,
            entity_kind="account",
            source_id=source_id,
        )
        .first()
    )
    if link is None:
        _record_link(db, "account", source_id, actual_id, updated_metadata)
        db.flush()
        link = (
            db.query(ActualEntityLink)
            .filter_by(
                run_id=_state(db).active_run_id,
                entity_kind="account",
                source_id=source_id,
            )
            .one()
        )
    prior_metadata = _link_metadata(link)
    pending = prior_metadata.get("_update_intent") or {}
    if pending:
        if pending.get("fingerprint") != fingerprint:
            raise ActualFinanceError("account retry does not match its durable update intent")
    elif fields:
        link.metadata_json = json.dumps(
            {
                **prior_metadata,
                "_update_intent": {
                    "version": 1,
                    "fingerprint": fingerprint,
                    "fields": fields,
                    "metadata": updated_metadata,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        db.commit()
    if fields and not _account_fields_match(current_row, fields):
        _request(
            db,
            {
                "command": "write",
                "action": "update_account",
                "actual_id": actual_id,
                "fields": fields,
            },
            bridge_request=bridge_request,
        )
        current = inspect(db, bridge_request=bridge_request)
        current_row = next(
            (row for row in current.get("accounts") or [] if row.get("id") == actual_id),
            None,
        )
        if current_row is None or not _account_fields_match(current_row, fields):
            raise ActualFinanceError("canonical account update did not verify")
    _record_link(db, "account", source_id, actual_id, updated_metadata)
    db.commit()
    return next(
        row for row in accounts(db, bridge_request=bridge_request) if row["actual_id"] == actual_id
    )


@authority_guarded
def close_account(db: Session, public_id: str, *, bridge_request=None) -> dict:
    update_account(db, public_id, {"archived": True}, bridge_request=bridge_request)
    return {"ok": True, "closed": True}


@authority_guarded
def create_transaction(
    db: Session,
    values: dict,
    *,
    source_id: str | None = None,
    request_id: str = "",
    import_identity: str = "",
    evidence: dict | None = None,
    bridge_request=None,
    commit_link: bool = True,
    reimport_deleted: bool = False,
) -> dict:
    state = _state(db)
    amount = values.get("amount", 0)
    amount_minor = _minor(amount)
    base_text = format(Decimal(amount_minor) / 100, "f")
    metadata = {
        "original_amount_text": base_text,
        "original_currency_code": state.base_currency_code,
        "base_amount_text": base_text,
        "base_currency_code": state.base_currency_code,
        "rate_text": "1",
        "rate_date": "",
        "source": "actual_identity",
        "tags": str(values.get("tags") or ""),
        "receipt_id": str(values.get("receipt_id") or ""),
        **(evidence or {}),
    }
    transaction = _canonical_transaction(db, values, bridge_request=bridge_request)
    if source_id and request_id:
        raise ActualFinanceError("transaction create must use one request identity")
    source_id = source_id or _request_source_id(request_id, "transaction")
    metadata["canonical_transaction"] = dict(transaction)
    fingerprint = _request_fingerprint(
        "create_transaction",
        {**transaction, "imported_id": import_identity or "<generated>"},
    )
    intent, completed = _begin_intent(
        db,
        "transaction",
        source_id,
        fingerprint,
        transaction,
        metadata,
        revive_deleted=reimport_deleted is True,
    )
    source_id = intent.source_id
    if completed:
        try:
            return next(
                row
                for row in transactions(db, bridge_request=bridge_request, _source_ids={source_id})
                if row["id"] == source_id
            )
        except StopIteration as exc:
            raise ActualFinanceError("completed transaction create target was not found") from exc
    transaction["imported_id"] = import_identity or f"alles:actual:{source_id}"
    actual_id = intent.actual_id
    if not actual_id:
        actual_id = _recover_imported_transaction(db, transaction, bridge_request=bridge_request)
        if not actual_id:
            result = _request(
                db,
                {
                    "command": "write",
                    "action": "create_transaction",
                    "transaction": transaction,
                    "reimport_deleted": reimport_deleted is True,
                },
                bridge_request=bridge_request,
            )
            if not result or not result.get("id"):
                raise ActualFinanceError("Actual did not return the created transaction")
            actual_id = str(result["id"])
    _finish_intent(intent, actual_id, fingerprint, metadata)
    if commit_link:
        db.commit()
    return next(
        row
        for row in transactions(db, bridge_request=bridge_request, _source_ids={source_id})
        if row["id"] == source_id
    )


@authority_guarded
def update_transaction(db: Session, public_id: str, values: dict, *, bridge_request=None) -> dict:
    actual_id = _resolve(db, "transaction", public_id, bridge_request=bridge_request)
    fields = {}
    mapping = {
        "date": "date",
        "amount": "amount",
        "notes": "notes",
        "cleared": "cleared",
        "payee": "payee_name",
        "category": "category_name",
    }
    for source, target in mapping.items():
        if source in values:
            if source == "amount":
                fields[target] = _minor(values[source])
            elif source == "date":
                fields[target] = _required_date(values[source])
            elif source == "cleared":
                fields[target] = bool(values[source])
            else:
                fields[target] = str(values[source] or "")
    if "account_id" in values:
        fields["account"] = _resolve(
            db, "account", str(values["account_id"]), bridge_request=bridge_request
        )
    _source_to_actual, actual_to_source, metadata = _maps(db, "transaction")
    updated_metadata = dict(metadata.get(actual_id, {}))
    updated_metadata.pop("_update_intent", None)
    current = inspect(db, bridge_request=bridge_request)
    current_row = next(
        (row for row in current.get("transactions") or [] if row.get("id") == actual_id),
        None,
    )
    if current_row is None:
        raise ActualFinanceError("canonical transaction update target was not found")
    if current_row.get("transfer_id"):
        raise ActualFinanceError("transfer component transactions cannot be edited directly")
    for key in ("tags", "receipt_id"):
        if key in values:
            updated_metadata[key] = str(values[key] or "")
    if "amount" in values:
        text = format(Decimal(_minor(values["amount"])) / 100, "f")
        base_currency_code = _state(db).base_currency_code
        updated_metadata.update(
            {
                "original_amount_text": text,
                "original_currency_code": base_currency_code,
                "base_amount_text": text,
                "base_currency_code": base_currency_code,
                "rate_text": "1",
                "rate_date": "",
                "source": "actual_identity",
            }
        )
    canonical = {
        "account": str(current_row.get("account") or ""),
        "date": _date(current_row.get("date")),
        "amount": int(current_row.get("amount") or 0),
        "payee_name": str(current_row.get("payee_name") or current_row.get("imported_payee") or ""),
        "category_name": str(current_row.get("category_name") or ""),
        "notes": str(current_row.get("notes") or ""),
        "cleared": bool(current_row.get("cleared")),
    }
    canonical.update(fields)
    updated_metadata["canonical_transaction"] = canonical
    source_id = actual_to_source.get(actual_id, public_id)
    fingerprint = _request_fingerprint(
        "update_transaction",
        {"actual_id": actual_id, "fields": fields, "metadata": updated_metadata},
    )
    link = (
        db.query(ActualEntityLink)
        .filter_by(
            run_id=_state(db).active_run_id,
            entity_kind="transaction",
            source_id=source_id,
        )
        .first()
    )
    if link is None:
        _record_link(db, "transaction", source_id, actual_id, updated_metadata)
        db.flush()
        link = (
            db.query(ActualEntityLink)
            .filter_by(
                run_id=_state(db).active_run_id,
                entity_kind="transaction",
                source_id=source_id,
            )
            .one()
        )
    prior_metadata = _link_metadata(link)
    pending = prior_metadata.get("_update_intent") or {}
    if pending:
        if pending.get("fingerprint") != fingerprint:
            raise ActualFinanceError("transaction retry does not match its durable update intent")
    elif fields:
        link.metadata_json = json.dumps(
            {
                **prior_metadata,
                "_update_intent": {
                    "version": 1,
                    "fingerprint": fingerprint,
                    "fields": fields,
                    "metadata": updated_metadata,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        db.commit()
    if fields:
        if not _transaction_fields_match(current_row, fields):
            _request(
                db,
                {
                    "command": "write",
                    "action": "update_transaction",
                    "actual_id": actual_id,
                    "fields": fields,
                },
                bridge_request=bridge_request,
            )
            current = inspect(db, bridge_request=bridge_request)
            current_row = next(
                (row for row in current.get("transactions") or [] if row.get("id") == actual_id),
                None,
            )
            if current_row is None or not _transaction_fields_match(current_row, fields):
                raise ActualFinanceError("canonical transaction update did not verify")
    _record_link(
        db,
        "transaction",
        source_id,
        actual_id,
        updated_metadata,
    )
    db.commit()
    return next(
        row
        for row in transactions(db, bridge_request=bridge_request)
        if row["actual_id"] == actual_id
    )


@authority_guarded
def delete_transaction(db: Session, public_id: str, *, bridge_request=None) -> dict:
    link = _find_deletion_link(db, "transaction", public_id)
    if link is None:
        actual_id = _resolve(db, "transaction", public_id, bridge_request=bridge_request)
        link = _ensure_deletion_link(db, "transaction", public_id, actual_id)
    metadata = _link_metadata(link)
    if metadata.get("_deleted"):
        return {"ok": True}
    actual = inspect(db, bridge_request=bridge_request)
    pending = metadata.get("_delete_intent") or {}
    actual_id = str(pending.get("actual_id") or link.actual_id or "")
    current = next(
        (row for row in actual.get("transactions") or [] if row.get("id") == actual_id),
        None,
    )
    if current and current.get("transfer_id"):
        raise ActualFinanceError("transfer component transactions cannot be deleted directly")
    actual_id, deleted = _begin_link_deletion(db, link)
    if deleted:
        return {"ok": True}
    if current:
        _request(
            db,
            {"command": "write", "action": "delete_transaction", "actual_id": actual_id},
            bridge_request=bridge_request,
        )
    _finish_link_deletion(link, actual_id)
    db.commit()
    return {"ok": True}


@authority_guarded
def create_transfer(
    db: Session,
    values: dict,
    *,
    request_id: str,
    bridge_request=None,
) -> dict:
    amount_minor = abs(_minor(values.get("amount", 0)))
    if amount_minor == 0:
        raise ActualFinanceError("transfer amount must be greater than zero")
    transfer_date = _required_date(values.get("date"), "transfer date")
    actual_from = _resolve(
        db,
        "account",
        str(values.get("from_account") or ""),
        bridge_request=bridge_request,
    )
    actual_to = _resolve(
        db,
        "account",
        str(values.get("to_account") or ""),
        bridge_request=bridge_request,
    )
    if actual_from == actual_to:
        raise ActualFinanceError("transfer accounts must be different")
    transfer = {
        "from_account": actual_from,
        "to_account": actual_to,
        "amount_minor": amount_minor,
        "date": transfer_date,
        "notes": str(values.get("notes") or "").strip(),
    }
    transfer_id = _request_source_id(request_id, "transfer")
    source_out = f"{transfer_id}:out"
    source_in = f"{transfer_id}:in"
    fingerprint = _request_fingerprint("create_transfer", transfer)
    intent, completed = _begin_intent(
        db,
        "transfer",
        transfer_id,
        fingerprint,
        transfer,
        {},
    )
    transfer_id = intent.source_id
    source_out = f"{transfer_id}:out"
    source_in = f"{transfer_id}:in"
    if completed:
        rows = {
            row["id"]: row
            for row in transactions(
                db,
                bridge_request=bridge_request,
                _source_ids={source_out, source_in},
            )
        }
        if source_out not in rows or source_in not in rows:
            raise ActualFinanceError("completed transfer create target was not found")
        return {"transfer_id": transfer_id, "from": rows[source_out], "to": rows[source_in]}
    transfer["imported_id"] = f"alles:transfer:{transfer_id}"
    if intent.actual_id:
        pair = intent.actual_id.split(":", 1)
        result = {"from_id": pair[0], "to_id": pair[1]}
    else:
        result = _recover_imported_transfer(db, transfer, bridge_request=bridge_request)
        if result is None:
            result = _request(
                db,
                {"command": "write", "action": "create_transfer", "transfer": transfer},
                bridge_request=bridge_request,
            )
    _record_link(
        db,
        "transaction",
        source_out,
        result["from_id"],
        {
            "canonical_transaction": {
                "account": actual_from,
                "date": transfer["date"],
                "amount": -transfer["amount_minor"],
                "notes": transfer["notes"],
                "cleared": False,
            }
        },
    )
    _record_link(
        db,
        "transaction",
        source_in,
        result["to_id"],
        {
            "canonical_transaction": {
                "account": actual_to,
                "date": transfer["date"],
                "amount": transfer["amount_minor"],
                "notes": transfer["notes"],
                "cleared": False,
            }
        },
    )
    actual_pair = f"{result['from_id']}:{result['to_id']}"
    _finish_intent(
        intent,
        actual_pair,
        fingerprint,
        {
            "canonical_transfer": {
                "from_account": actual_from,
                "to_account": actual_to,
                "amount_minor": transfer["amount_minor"],
                "date": transfer["date"],
                "notes": transfer["notes"],
            }
        },
    )
    db.commit()
    rows = {
        row["id"]: row
        for row in transactions(
            db,
            bridge_request=bridge_request,
            _source_ids={source_out, source_in},
        )
    }
    return {"transfer_id": transfer_id, "from": rows[source_out], "to": rows[source_in]}


@authority_guarded
def delete_transfer(db: Session, public_id: str, *, bridge_request=None) -> dict:
    transfer_link = _find_deletion_link(db, "transfer", public_id)
    if transfer_link is None:
        actual_pair = _resolve(db, "transfer", public_id, bridge_request=bridge_request)
        transfer_link = _ensure_deletion_link(db, "transfer", public_id, actual_pair)
    actual_pair, deleted = _begin_link_deletion(db, transfer_link)
    if deleted:
        return {"ok": True, "removed": 0}
    ids = [value for value in actual_pair.split(":") if value]
    if len(ids) != 2 or ids[0] == ids[1]:
        raise ActualFinanceError("canonical transfer link is not one complete pair")
    transaction_links = []
    for actual_id in ids:
        # Alles-created transfers already have component links whose source IDs
        # are `<transfer>:out` and `<transfer>:in`. Resolve those links by their
        # Actual IDs before falling back to a native-Actual deletion sidecar.
        link = _find_deletion_link(db, "transaction", actual_id)
        if link is None:
            link = _ensure_deletion_link(db, "transaction", actual_id, actual_id)
        transaction_links.append(link)
    for row in transaction_links:
        _begin_link_deletion(db, row)
    actual = inspect(db, bridge_request=bridge_request)
    by_id = {row.get("id"): row for row in actual.get("transactions") or []}
    left, right = by_id.get(ids[0]), by_id.get(ids[1])
    removed = 0
    if left or right:
        if not (
            left
            and right
            and left.get("transfer_id") == right.get("id")
            and right.get("transfer_id") == left.get("id")
        ):
            raise ActualFinanceError("canonical transfer deletion target is not reciprocal")
        result = _request(
            db,
            {"command": "write", "action": "delete_transfer", "actual_ids": ids},
            bridge_request=bridge_request,
        )
        removed = int(result.get("deleted") or 0)
    _finish_link_deletion(transfer_link, actual_pair)
    for row, actual_id in zip(transaction_links, ids, strict=True):
        _finish_link_deletion(row, actual_id)
    db.commit()
    return {"ok": True, "removed": removed}
