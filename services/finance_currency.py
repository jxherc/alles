"""Exact text currency evidence for the additive Phase 8 Finance foundation."""

import hashlib
import json
import uuid
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from sqlalchemy import inspect

from core.database import Account, MoneyFxEvidence

# Frozen active ISO 4217 legal-tender codes. Explicit codes are unambiguous;
# shared symbols such as $ and yen/yuan remain review-only below.
SUPPORTED_CURRENCY_CODES = frozenset(
    """AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD
    BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB
    EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR
    ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD
    MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR
    PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE
    SOS SRD SSP STN SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS
    VES VND VUV WST XAF XCD XCG XOF XPF YER ZAR ZMW ZWG""".split()
)


def currency_code(value) -> str:
    raw = str(value or "").strip().upper()
    if raw in {"RMB", "人民币", "人民币元"}:
        return "CNY"
    if raw in SUPPORTED_CURRENCY_CODES:
        return raw
    return {"€": "EUR", "£": "GBP", "$": "XXX", "¥": "XXX", "￥": "XXX"}.get(raw, "XXX")


def decimal_text(value) -> str:
    try:
        amount = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("amount must be a decimal number") from error
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    if len(amount.as_tuple().digits) > 28 or not -18 <= amount.adjusted() <= 18:
        raise ValueError("amount precision or exponent is out of range")
    return format(amount, "f")


def canonical_decimal_text(value) -> str:
    """Return one stable, non-exponent representation for an exact decimal."""
    amount = Decimal(decimal_text(value))
    if amount == 0:
        return "0"
    return format(amount.normalize(), "f")


def minor_unit_decimal_text(value) -> str:
    """Return an exact decimal amount only when it is representable in cents."""
    rendered = decimal_text(value)
    amount = Decimal(rendered)
    if amount != amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN):
        raise ValueError("amount must use no more than two decimal places")
    return rendered


def evidence_fingerprint(
    transaction_id: str,
    original_amount: str,
    original_currency: str,
    base_amount: str,
    base_currency: str,
    rate: str,
    rate_date: str,
    source: str,
) -> str:
    value = "|".join(
        (
            transaction_id,
            original_amount,
            original_currency,
            base_amount,
            base_currency,
            rate,
            rate_date,
            source,
        )
    )
    return hashlib.sha256(value.encode()).hexdigest()


def fallback_import_match_fingerprint(
    profile: str,
    account_id: str,
    date: str,
    amount,
    payee: str,
    *,
    currency: str = "",
) -> str:
    """Return a non-unique comparison key, never a durable transaction identity."""
    fields = {
        "profile": str(profile or "").strip().lower(),
        "account_id": str(account_id or "").strip(),
        "date": str(date or "")[:10],
        "amount": canonical_decimal_text(amount),
        "currency": currency_code(currency),
        "payee": " ".join(str(payee or "").casefold().split()),
    }
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def stable_import_identity(
    profile: str,
    account_id: str,
    *,
    external_id: str = "",
    occurrence_identity: str = "",
) -> str:
    """Build a durable identity only from a bank reference or statement occurrence."""
    external = str(external_id or "").strip()
    occurrence = str(occurrence_identity or "").strip()
    if not external and not occurrence:
        raise ValueError("a bank reference or statement occurrence identity is required")
    fields = {
        "profile": str(profile or "").strip().lower(),
        "account_id": str(account_id or "").strip(),
        "bank_reference": external,
        "statement_occurrence": "" if external else occurrence,
    }
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def prepare_account(account) -> None:
    code = currency_code(account.currency)
    opening = decimal_text(account.opening)
    account.currency_code = code
    known = code != "XXX"
    account.base_currency_code = code if known else ""
    account.original_opening_text = opening
    account.base_opening_text = opening if known else ""
    account.opening_fx_rate_text = "1" if known else ""
    account.opening_fx_rate_date = ""
    account.opening_fx_source = "manual_identity" if known else ""


def refresh_account_opening(account) -> None:
    """Update an opening amount without discarding already reviewed conversion evidence."""
    opening = decimal_text(account.opening)
    try:
        rate = Decimal(str(account.opening_fx_rate_text or ""))
    except (InvalidOperation, ValueError):
        rate = Decimal(0)
    if not (
        rate.is_finite()
        and rate > 0
        and account.currency_code
        and account.base_currency_code
        and account.opening_fx_source
    ):
        prepare_account(account)
        return
    account.original_opening_text = opening
    account.base_opening_text = format(
        (Decimal(opening) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN),
        "f",
    )


def prepare_transaction(
    db,
    transaction,
    *,
    source: str = "manual",
    original_amount=None,
    original_currency_code: str = "",
    base_amount=None,
    base_currency_code: str = "",
    rate=None,
    rate_date: str = "",
    source_hash: str = "",
) -> MoneyFxEvidence | None:
    account = db.get(Account, transaction.account_id)
    if not account:
        raise ValueError("unknown account")
    if not transaction.id:
        transaction.id = str(uuid.uuid4())
    original = decimal_text(transaction.amount if original_amount is None else original_amount)
    original_code = currency_code(
        original_currency_code or account.currency_code or account.currency
    )
    base_code = currency_code(base_currency_code or account.base_currency_code or original_code)
    known_identity = original_code != "XXX" and original_code == base_code
    normalized_rate_date = ""
    if original_code == "XXX" or base_code == "XXX" or (base_amount is None and not known_identity):
        base = ""
        base_code = ""
        rate_text = ""
    else:
        base = decimal_text(transaction.amount if base_amount is None else base_amount)
        if base_amount is None:
            rate_text = "1"
        else:
            if rate is None and not known_identity:
                raise ValueError("cross-currency base evidence requires an explicit rate")
            rate_text = decimal_text("1" if rate is None else rate)
            rate_value = Decimal(rate_text)
            original_value = Decimal(original)
            base_value = Decimal(base)
            if (
                rate_value <= 0
                or len(rate_value.as_tuple().digits) > 28
                or not -18 <= rate_value.adjusted() <= 18
            ):
                raise ValueError("conversion rate must be a supported positive decimal")
            if known_identity:
                if rate_value != 1 or base_value != original_value:
                    raise ValueError("same-currency base evidence must preserve the exact amount")
            else:
                try:
                    normalized_rate_date = date.fromisoformat(str(rate_date or "")).isoformat()
                except ValueError:
                    raise ValueError(
                        "cross-currency base evidence requires a valid rate date"
                    ) from None
                try:
                    cents = Decimal("0.01")
                    normalized_base = base_value.quantize(cents)
                    expected_base = (original_value * rate_value).quantize(
                        cents, rounding=ROUND_HALF_EVEN
                    )
                except (InvalidOperation, ValueError, OverflowError) as exc:
                    raise ValueError("conversion evidence is outside the supported range") from exc
                if base_value != normalized_base or base_value != expected_base:
                    raise ValueError(
                        "base amount must equal original amount times the positive rate"
                    )
    transaction.original_amount_text = original
    transaction.original_currency_code = original_code
    transaction.base_amount_text = base
    transaction.base_currency_code = base_code
    transaction.fx_rate_text = rate_text
    transaction.fx_rate_date = normalized_rate_date if rate_text else ""
    transaction.fx_source = source if rate_text else ""
    transaction.import_source = transaction.import_source or source
    db.add(transaction)
    db.flush()

    # Some narrow unit tests intentionally create only the legacy account and
    # transaction tables. Production init always creates the evidence table;
    # keep those bounded fixtures valid without weakening the stored columns.
    # Inspect through this session's active connection. Using the Engine here
    # briefly checks out and closes a second connection; with SQLite StaticPool
    # that can be the same DB-API connection and roll back this flush.
    if not inspect(db.connection()).has_table("money_fx_evidence"):
        return None
    evidence = db.query(MoneyFxEvidence).filter_by(transaction_id=transaction.id).first()
    if original_code == "XXX":
        if evidence:
            db.delete(evidence)
        return None
    if not evidence:
        evidence = MoneyFxEvidence(id=f"fx:{transaction.id}", transaction_id=transaction.id)
        db.add(evidence)
    evidence.original_amount_text = original
    evidence.original_currency_code = original_code
    evidence.base_amount_text = base
    evidence.base_currency_code = base_code
    evidence.rate_text = rate_text
    evidence.rate_date = normalized_rate_date if rate_text else ""
    evidence.source = source
    evidence.source_hash = source_hash or evidence_fingerprint(
        transaction.id,
        original,
        original_code,
        base,
        base_code,
        rate_text,
        evidence.rate_date,
        source,
    )
    return evidence


def prepare_subscription(subscription) -> None:
    price = minor_unit_decimal_text(subscription.price)
    code = currency_code(subscription.currency)
    subscription.original_price_text = price
    subscription.original_currency_code = code
    known = code != "XXX"
    subscription.base_price_text = price if known else ""
    subscription.base_currency_code = code if known else ""
    subscription.fx_rate_text = "1" if known else ""
    subscription.fx_rate_date = ""
    subscription.fx_source = "manual_identity" if known else ""


def prepare_payment(payment, subscription) -> None:
    amount = decimal_text(payment.amount)
    code = currency_code(subscription.original_currency_code or subscription.currency)
    payment.original_amount_text = amount
    payment.original_currency_code = code
    base_code = (
        currency_code(subscription.base_currency_code) if subscription.base_currency_code else ""
    )
    rate_text = subscription.fx_rate_text or ""
    try:
        rate = Decimal(rate_text)
        valid_rate = rate.is_finite() and rate > 0
    except (InvalidOperation, ValueError):
        rate = Decimal(0)
        valid_rate = False
    known = code != "XXX" and base_code != "XXX" and bool(base_code) and valid_rate
    payment.base_amount_text = (
        format(
            (Decimal(amount) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN),
            "f",
        )
        if known
        else ""
    )
    payment.base_currency_code = base_code if known else ""
    payment.fx_rate_text = rate_text if known else ""
    payment.fx_rate_date = subscription.fx_rate_date or ""
    payment.fx_source = (subscription.fx_source or "manual_identity") if known else ""
