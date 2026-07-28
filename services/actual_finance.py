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

from core.database import ActualEntityLink, FinanceLedgerState
from services import finance_currency, managed_actual


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
def inspect(db: Session, *, bridge_request=None) -> dict:
    return _request(db, {"command": "inspect"}, bridge_request=bridge_request)


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
        opening_major = _major_from_minor(
            _minor(base_opening_text, "opening balance"), "opening balance"
        )
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
    anchor = current.day
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
                "active": not bool(row.get("completed")),
                "account_id": account_public.get(row.get("account"), row.get("account") or ""),
                "metadata": metadata.get(actual_id, {}),
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
    """Read canonical category budgets from the selected Actual budget month."""
    actual = actual or inspect(db, bridge_request=bridge_request)
    category_names = {
        row.get("id"): row.get("name") or "uncategorized" for row in actual.get("categories") or []
    }
    selected = next(
        (row for row in actual.get("budget_months") or [] if row.get("month") == month),
        None,
    )
    rows_by_category = {}
    for group in (
        (selected or {}).get("categoryGroups") or (selected or {}).get("category_groups") or []
    ):
        for category in group.get("categories") or []:
            category_id = str(category.get("id") or "")
            budgeted_minor = int(category.get("budgeted") or 0)
            if not category_id or budgeted_minor == 0:
                continue
            rows_by_category[category_id] = {
                "id": f"actual-budget:{month}:{category_id}",
                "actual_id": category_id,
                "category": category.get("name")
                or category_names.get(category_id, "uncategorized"),
                "tag": "",
                "limit_amt": _major_from_minor(budgeted_minor, "budget amount"),
            }
    category_ids_by_name: dict[str, list[str]] = {}
    for category_id, name in category_names.items():
        category_ids_by_name.setdefault(str(name).casefold(), []).append(category_id)
    assignment_links = _links(db, "budget_assignment")
    if any(_link_metadata(link).get("_delete_intent") for link in assignment_links):
        raise ActualFinanceError(
            "a budget assignment deletion is uncertain; retry the same deletion before reading it"
        )
    explicit_assignments = {
        link.actual_id for link in assignment_links if not _link_metadata(link).get("_deleted")
    }
    for link in _links(db, "budget_limit"):
        metadata = _link_metadata(link)
        if metadata.get("_delete_intent") or metadata.get("_deleted"):
            continue
        if metadata.get("_update_intent"):
            raise ActualFinanceError(
                "a persistent budget update is uncertain; retry the same update before reading it"
            )
        category_name = str(metadata.get("category") or "").strip()
        category_id = link.actual_id if link.actual_id in category_names else ""
        if not category_id:
            matches = category_ids_by_name.get(category_name.casefold(), [])
            if len(matches) == 1:
                category_id = matches[0]
        limit_minor = metadata.get("limit_minor")
        if (
            not category_id
            or isinstance(limit_minor, bool)
            or not isinstance(limit_minor, int)
            or abs(limit_minor) > MAX_CENT_SAFE_MINOR
        ):
            raise ActualFinanceError("a persistent budget cap is not safely linked to Actual")
        cap_row = {
            "id": f"actual-budget-cap:{category_id}",
            "actual_id": category_id,
            "category": category_names.get(category_id) or category_name,
            "tag": "",
            "limit_amt": _major_from_minor(limit_minor, "persistent budget cap"),
        }
        managed_month = str(metadata.get("managed_month") or "")
        if managed_month == month and f"{month}:{category_id}" not in explicit_assignments:
            native_row = rows_by_category.get(category_id)
            if native_row:
                cap_row["limit_amt"] = native_row["limit_amt"]
            rows_by_category[category_id] = cap_row
        elif f"{month}:{category_id}" not in explicit_assignments:
            rows_by_category.setdefault(category_id, cap_row)
    rows = list(rows_by_category.values())
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
    month = str(month or "")
    if len(month) != 7 or month[4] != "-" or not month.replace("-", "").isdigit():
        raise ActualFinanceError("budget month must be YYYY-MM")
    try:
        parsed_month = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise ActualFinanceError("budget month must be a valid calendar month") from None
    if parsed_month.strftime("%Y-%m") != month:
        raise ActualFinanceError("budget month must be a valid calendar month")
    amount_minor = _minor(amount, "budget amount")
    link = _budget_limit_link(db, category_name=name)
    prior_metadata = _link_metadata(link) if link else {}
    if prior_metadata.get("_delete_intent") or prior_metadata.get("_deleted"):
        raise ActualFinanceError("the persistent budget cap is pending deletion")
    previous_month = str(prior_metadata.get("managed_month") or "")
    previous_category_id = str(link.actual_id or "") if link else ""
    intent_details = {
        "category": name,
        "amount_minor": amount_minor,
        "month": month,
        "previous_category_id": previous_category_id,
        "previous_month": previous_month,
    }
    fingerprint = _request_fingerprint("set_budget", intent_details)
    pending = prior_metadata.get("_update_intent") or {}
    if pending:
        if pending.get("fingerprint") != fingerprint:
            raise ActualFinanceError("budget retry does not match its durable update intent")
    else:
        intent_metadata = {
            **prior_metadata,
            "category": str(prior_metadata.get("category") or name),
            "source": str(prior_metadata.get("source") or "alles_persistent_cap"),
            "_update_intent": {
                "version": 1,
                "fingerprint": fingerprint,
                **intent_details,
            },
        }
        if link:
            link.metadata_json = json.dumps(intent_metadata, sort_keys=True, separators=(",", ":"))
        else:
            source_key = hashlib.sha256(name.casefold().encode()).hexdigest()
            _record_link(
                db,
                "budget_limit",
                f"actual-budget-cap-pending:{source_key}",
                "",
                intent_metadata,
            )
            db.flush()
            link = _budget_limit_link(db, category_name=name)
            if link is None:
                raise ActualFinanceError("the durable budget update intent could not be created")
        db.commit()
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
    metadata = {
        "category": name,
        "limit_minor": amount_minor,
        "managed_month": month,
        "source": "alles_persistent_cap",
    }
    link.actual_id = category_id
    link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    db.commit()
    return {
        "id": f"actual-budget-cap:{category_id}",
        "actual_id": category_id,
        "category": name,
        "tag": "",
        "limit_amt": _major_from_minor(int(result.get("amount_minor") or 0), "budget amount"),
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
        managed_month = str(_link_metadata(link).get("managed_month") or "")
        deletion_target, already_deleted = _begin_link_deletion(db, link)
        if already_deleted:
            return {"ok": True}
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
