"""m0037 - additive Finance currency evidence and stable import foundation."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, InvalidOperation

from sqlalchemy import text

from .runner import add_column

VERSION = 37
NAME = "finance_currency_import_foundation"
DEFAULT_BASE_CURRENCY_CODE = "CAD"
# Frozen active ISO 4217 legal-tender codes. The migration must preserve an
# explicit valid code even when the old offline FX table had no rate for it.
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
ZERO_DECIMAL_CURRENCY_CODES = frozenset(
    "BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX VND VUV XAF XOF XPF".split()
)
THREE_DECIMAL_CURRENCY_CODES = frozenset("BHD IQD JOD KWD LYD OMR TND".split())


def _minor_unit_quantum(currency) -> Decimal:
    code = _currency_code(currency)
    if code in ZERO_DECIMAL_CURRENCY_CODES:
        return Decimal("1")
    if code in THREE_DECIMAL_CURRENCY_CODES:
        return Decimal("0.001")
    return Decimal("0.01")


def _tables(conn) -> set[str]:
    return {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }


def _currency_code(value) -> str:
    raw = str(value or "").strip().upper()
    if raw == "RMB":
        return "CNY"
    if raw in SUPPORTED_CURRENCY_CODES:
        return raw
    return {
        "€": "EUR",
        "£": "GBP",
        "¥": "XXX",  # yuan and yen share this glyph; do not invent certainty
        "￥": "XXX",
        "$": "XXX",  # could be CAD, USD, AUD, and others
    }.get(raw, "XXX")


def _decimal_text(value) -> str:
    try:
        return format(Decimal(str(value if value is not None else 0)), "f")
    except (InvalidOperation, ValueError):
        return "0"


def _known_currency(value) -> bool:
    return bool(str(value or "").strip()) and _currency_code(value) != "XXX"


def _can_infer_identity_base(currency, stored_rate, ledger_base) -> bool:
    """Infer same-currency base fields only when stored evidence does not contradict them."""
    if not (_known_currency(currency) and _known_currency(ledger_base)):
        return False
    if _currency_code(currency) != _currency_code(ledger_base):
        return False
    raw_rate = str(stored_rate or "").strip()
    if not raw_rate:
        return True
    try:
        rate = Decimal(raw_rate)
    except (InvalidOperation, ValueError):
        return False
    return rate.is_finite() and rate == 1


def _configured_base_currency(conn, tables: set[str]) -> str:
    if "finance_ledger_state" not in tables:
        return DEFAULT_BASE_CURRENCY_CODE
    value = conn.execute(
        text("SELECT base_currency_code FROM finance_ledger_state WHERE id='primary'")
    ).scalar_one_or_none()
    return _currency_code(value) if _known_currency(value) else DEFAULT_BASE_CURRENCY_CODE


def _conversion_evidence(
    original_amount,
    original_currency,
    base_amount,
    base_currency,
    stored_rate,
    stored_source,
) -> tuple[str, str]:
    """Backfill only identity rates or rates proven by both stored amounts."""
    rate = str(stored_rate or "").strip()
    source = str(stored_source or "").strip()
    if rate:
        if not (_known_currency(original_currency) and _known_currency(base_currency)):
            return "", source
        try:
            original = Decimal(str(original_amount))
            base = Decimal(str(base_amount))
            stored = Decimal(rate)
            values = (original, base, stored)
            if (
                any(
                    not value.is_finite()
                    or len(value.as_tuple().digits) > 28
                    or not -18 <= value.adjusted() <= 18
                    for value in values
                )
                or stored <= 0
            ):
                return "", source
            if _currency_code(original_currency) == _currency_code(base_currency):
                if stored != 1 or original != base:
                    return "", source
            else:
                quantum = _minor_unit_quantum(base_currency)
                normalized_base = base.quantize(quantum)
                expected_base = (original * stored).quantize(quantum, rounding=ROUND_HALF_EVEN)
                if base != normalized_base or base != expected_base:
                    return "", source
        except (DecimalException, ValueError, OverflowError):
            return "", source
        return rate, source
    if not (_known_currency(original_currency) and _known_currency(base_currency)):
        return "", source
    if _currency_code(original_currency) == _currency_code(base_currency):
        try:
            original = Decimal(str(original_amount))
            base = Decimal(str(base_amount))
            if (
                any(
                    not value.is_finite()
                    or len(value.as_tuple().digits) > 28
                    or not -18 <= value.adjusted() <= 18
                    for value in (original, base)
                )
                or original != base
            ):
                return "", source
        except (DecimalException, ValueError, OverflowError):
            return "", source
        return "1", source or "legacy_identity"
    try:
        original = Decimal(str(original_amount))
        base = Decimal(str(base_amount))
        values = (original, base)
        if any(
            not value.is_finite()
            or len(value.as_tuple().digits) > 28
            or not -18 <= value.adjusted() <= 18
            for value in values
        ):
            return "", source
        quantum = _minor_unit_quantum(base_currency)
        if base != base.quantize(quantum):
            return "", source
        derived = base / original
        if (
            not derived.is_finite()
            or len(derived.as_tuple().digits) > 28
            or not -18 <= derived.adjusted() <= 18
            or derived <= 0
        ):
            return "", source
    except (DecimalException, ValueError, OverflowError):
        return "", source
    return format(derived, "f"), "legacy_derived_amounts"


def _add_columns(conn, table: str, columns: dict[str, str]) -> None:
    for name, kind in columns.items():
        add_column(conn, table, name, kind)


def _create_foundation_tables(conn) -> None:
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS money_fx_evidence ("
            "id VARCHAR NOT NULL PRIMARY KEY, transaction_id VARCHAR NOT NULL UNIQUE, "
            "original_amount_text VARCHAR NOT NULL, original_currency_code VARCHAR NOT NULL, "
            "base_amount_text VARCHAR NOT NULL, base_currency_code VARCHAR NOT NULL, "
            "rate_text VARCHAR NOT NULL, rate_date VARCHAR NOT NULL DEFAULT '', "
            "source VARCHAR NOT NULL, source_hash VARCHAR NOT NULL, created_at DATETIME, "
            "FOREIGN KEY(transaction_id) REFERENCES money_transactions(id) ON DELETE CASCADE)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_money_fx_evidence_transaction_id "
            "ON money_fx_evidence(transaction_id)"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS finance_import_batches ("
            # This is a durable receipt owner ID, not a legacy SQL foreign key.
            # After Actual cutover it can identify an Actual-native account that
            # intentionally has no row in money_accounts.
            "id VARCHAR NOT NULL PRIMARY KEY, account_id VARCHAR NOT NULL DEFAULT '', "
            "profile VARCHAR NOT NULL, source_name VARCHAR NOT NULL, "
            "source_sha256 VARCHAR NOT NULL, original_currency_code VARCHAR NOT NULL DEFAULT '', "
            "status VARCHAR NOT NULL DEFAULT 'preview', row_count INTEGER NOT NULL DEFAULT 0, "
            "applied_count INTEGER NOT NULL DEFAULT 0, duplicate_count INTEGER NOT NULL DEFAULT 0, "
            "conflict_count INTEGER NOT NULL DEFAULT 0, receipt_json TEXT NOT NULL DEFAULT '{}', "
            "created_at DATETIME, applied_at DATETIME, undone_at DATETIME)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_finance_import_batches_source_sha256 "
            "ON finance_import_batches(source_sha256)"
        )
    )
    add_column(conn, "finance_import_batches", "account_id", "VARCHAR DEFAULT ''")
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS finance_import_rows ("
            "id VARCHAR NOT NULL PRIMARY KEY, batch_id VARCHAR NOT NULL, row_number INTEGER NOT NULL, "
            "stable_identity VARCHAR NOT NULL, raw_json TEXT NOT NULL, parsed_json TEXT NOT NULL, "
            "status VARCHAR NOT NULL DEFAULT 'pending', existing_transaction_id VARCHAR NOT NULL DEFAULT '', "
            "created_transaction_id VARCHAR NOT NULL DEFAULT '', conflict_reason VARCHAR NOT NULL DEFAULT '', "
            "created_at DATETIME, CONSTRAINT uq_finance_import_batch_row UNIQUE(batch_id,row_number), "
            "FOREIGN KEY(batch_id) REFERENCES finance_import_batches(id) ON DELETE CASCADE)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_finance_import_rows_stable_identity "
            "ON finance_import_rows(stable_identity)"
        )
    )


def _backfill_accounts(conn, ledger_base: str) -> dict[str, str]:
    rows = conn.execute(
        text(
            "SELECT id,currency,opening,currency_code,base_currency_code,"
            "original_opening_text,base_opening_text,opening_fx_rate_text,opening_fx_source "
            "FROM money_accounts"
        )
    ).mappings()
    currencies = {}
    for row in rows:
        code = row.currency_code or _currency_code(row.currency)
        has_reviewed_base = _known_currency(row.base_currency_code) and bool(
            str(row.base_opening_text or "").strip()
        )
        identity_known = _can_infer_identity_base(code, row.opening_fx_rate_text, ledger_base)
        base = row.base_currency_code if has_reviewed_base else (code if identity_known else "")
        base_amount = (
            row.base_opening_text
            if has_reviewed_base
            else (_decimal_text(row.opening) if identity_known else "")
        )
        original_amount = row.original_opening_text or _decimal_text(row.opening)
        rate, source = _conversion_evidence(
            original_amount,
            code,
            base_amount,
            base,
            row.opening_fx_rate_text,
            row.opening_fx_source,
        )
        currencies[row.id] = code
        conn.execute(
            text(
                "UPDATE money_accounts SET currency_code=:code,base_currency_code=:base,"
                "original_opening_text=:original,base_opening_text=:base_amount,"
                "opening_fx_rate_text=:rate,opening_fx_source=:source WHERE id=:id"
            ),
            {
                "id": row.id,
                "code": code,
                "base": base,
                "original": original_amount,
                "base_amount": base_amount,
                "rate": rate,
                "source": source,
            },
        )
    return currencies


def _backfill_transactions(conn, currencies: dict[str, str], ledger_base: str) -> None:
    # SQLite's DateTime adapter and the ORM defaults use naive UTC. Keep migrated
    # rows comparable with evidence created after the migration.
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    rows = conn.execute(
        text(
            "SELECT id,account_id,amount,original_amount_text,original_currency_code,"
            "base_amount_text,base_currency_code,fx_rate_text,fx_rate_date,fx_source "
            "FROM money_transactions"
        )
    ).mappings()
    for row in rows:
        amount = row.original_amount_text or _decimal_text(row.amount)
        currency = row.original_currency_code or currencies.get(row.account_id, "XXX")
        has_reviewed_base = _known_currency(row.base_currency_code) and bool(
            str(row.base_amount_text or "").strip()
        )
        identity_known = _can_infer_identity_base(currency, row.fx_rate_text, ledger_base)
        base_amount = (
            row.base_amount_text if has_reviewed_base else (amount if identity_known else "")
        )
        base_currency = (
            row.base_currency_code if has_reviewed_base else (currency if identity_known else "")
        )
        rate_text, evidence_source = _conversion_evidence(
            amount,
            currency,
            base_amount,
            base_currency,
            row.fx_rate_text,
            row.fx_source,
        )
        conn.execute(
            text(
                "UPDATE money_transactions SET original_amount_text=:amount,"
                "original_currency_code=:currency,base_amount_text=:base_amount,"
                "base_currency_code=:base_currency,fx_rate_text=:rate,"
                "fx_rate_date=:rate_date,fx_source=:source,"
                "import_source=CASE WHEN import_source='' OR import_source IS NULL THEN 'legacy' ELSE import_source END "
                "WHERE id=:id"
            ),
            {
                "id": row.id,
                "amount": amount,
                "currency": currency,
                "base_amount": base_amount,
                "base_currency": base_currency,
                "rate": rate_text,
                "rate_date": row.fx_rate_date or "",
                "source": evidence_source,
            },
        )
        if not base_amount or not base_currency or not rate_text or not evidence_source:
            conn.execute(
                text(
                    "DELETE FROM money_fx_evidence "
                    "WHERE transaction_id=:transaction_id AND source_hash=:source_hash"
                ),
                {"transaction_id": row.id, "source_hash": f"legacy:{row.id}"},
            )
            continue
        conn.execute(
            text(
                "UPDATE money_fx_evidence SET original_amount_text=:amount,"
                "original_currency_code=:currency,base_amount_text=:base_amount,"
                "base_currency_code=:base_currency,rate_text=:rate,rate_date=:rate_date,"
                "source=:source WHERE transaction_id=:transaction_id AND source_hash=:source_hash"
            ),
            {
                "transaction_id": row.id,
                "amount": amount,
                "currency": currency,
                "base_amount": base_amount,
                "base_currency": base_currency,
                "rate": rate_text,
                "rate_date": row.fx_rate_date or "",
                "source": evidence_source,
                "source_hash": f"legacy:{row.id}",
            },
        )
        conn.execute(
            text(
                "INSERT OR IGNORE INTO money_fx_evidence "
                "(id,transaction_id,original_amount_text,original_currency_code,base_amount_text,"
                "base_currency_code,rate_text,rate_date,source,source_hash,created_at) "
                "VALUES (:evidence_id,:transaction_id,:amount,:currency,:base_amount,:base_currency,"
                ":rate,:rate_date,:source,:source_hash,:created_at)"
            ),
            {
                "evidence_id": f"fx:{row.id}",
                "transaction_id": row.id,
                "amount": amount,
                "currency": currency,
                "base_amount": base_amount,
                "base_currency": base_currency,
                "rate": rate_text,
                "rate_date": row.fx_rate_date or "",
                "source": evidence_source,
                "source_hash": f"legacy:{row.id}",
                "created_at": now,
            },
        )


def _backfill_subscriptions(conn, ledger_base: str) -> dict[str, str]:
    currencies = {}
    rows = conn.execute(
        text(
            "SELECT id,price,currency,original_price_text,original_currency_code,"
            "base_price_text,base_currency_code,fx_rate_text,fx_source FROM subscriptions"
        )
    ).mappings()
    for row in rows:
        code = row.original_currency_code or _currency_code(row.currency)
        has_reviewed_base = _known_currency(row.base_currency_code) and bool(
            str(row.base_price_text or "").strip()
        )
        identity_known = _can_infer_identity_base(code, row.fx_rate_text, ledger_base)
        base_code = (
            row.base_currency_code if has_reviewed_base else (code if identity_known else "")
        )
        price = row.original_price_text or _decimal_text(row.price)
        base_price = row.base_price_text if has_reviewed_base else (price if identity_known else "")
        rate, source = _conversion_evidence(
            price,
            code,
            base_price,
            base_code,
            row.fx_rate_text,
            row.fx_source,
        )
        currencies[row.id] = code
        conn.execute(
            text(
                "UPDATE subscriptions SET original_price_text=:price,original_currency_code=:code,"
                "base_price_text=:base_price,base_currency_code=:base_code,"
                "fx_rate_text=:rate,fx_source=:source WHERE id=:id"
            ),
            {
                "id": row.id,
                "price": price,
                "code": code,
                "base_price": base_price,
                "base_code": base_code,
                "rate": rate,
                "source": source,
            },
        )
    return currencies


def _backfill_payments(conn, sub_currencies: dict[str, str], ledger_base: str) -> None:
    rows = conn.execute(
        text(
            "SELECT id,sub_id,amount,original_amount_text,original_currency_code,"
            "base_amount_text,base_currency_code,fx_rate_text,fx_source FROM sub_payments"
        )
    ).mappings()
    for row in rows:
        amount = row.original_amount_text or _decimal_text(row.amount)
        code = row.original_currency_code or sub_currencies.get(row.sub_id, "XXX")
        has_reviewed_base = _known_currency(row.base_currency_code) and bool(
            str(row.base_amount_text or "").strip()
        )
        identity_known = _can_infer_identity_base(code, row.fx_rate_text, ledger_base)
        base_amount = (
            row.base_amount_text if has_reviewed_base else (amount if identity_known else "")
        )
        base_code = (
            row.base_currency_code if has_reviewed_base else (code if identity_known else "")
        )
        rate, source = _conversion_evidence(
            amount,
            code,
            base_amount,
            base_code,
            row.fx_rate_text,
            row.fx_source,
        )
        conn.execute(
            text(
                "UPDATE sub_payments SET original_amount_text=:amount,original_currency_code=:code,"
                "base_amount_text=:base_amount,base_currency_code=:base_code,"
                "fx_rate_text=:rate,fx_source=:source WHERE id=:id"
            ),
            {
                "id": row.id,
                "amount": amount,
                "code": code,
                "base_amount": base_amount,
                "base_code": base_code,
                "rate": rate,
                "source": source,
            },
        )


def up(conn):
    tables = _tables(conn)
    ledger_base = _configured_base_currency(conn, tables)
    if "money_accounts" in tables:
        _add_columns(
            conn,
            "money_accounts",
            {
                "currency_code": "VARCHAR DEFAULT ''",
                "base_currency_code": "VARCHAR DEFAULT ''",
                "original_opening_text": "VARCHAR DEFAULT ''",
                "base_opening_text": "VARCHAR DEFAULT ''",
                "opening_fx_rate_text": "VARCHAR DEFAULT ''",
                "opening_fx_rate_date": "VARCHAR DEFAULT ''",
                "opening_fx_source": "VARCHAR DEFAULT ''",
            },
        )
    if "money_transactions" in tables:
        _add_columns(
            conn,
            "money_transactions",
            {
                "original_amount_text": "VARCHAR DEFAULT ''",
                "original_currency_code": "VARCHAR DEFAULT ''",
                "base_amount_text": "VARCHAR DEFAULT ''",
                "base_currency_code": "VARCHAR DEFAULT ''",
                "fx_rate_text": "VARCHAR DEFAULT ''",
                "fx_rate_date": "VARCHAR DEFAULT ''",
                "fx_source": "VARCHAR DEFAULT ''",
                "import_identity": "VARCHAR DEFAULT ''",
                "import_batch_id": "VARCHAR DEFAULT ''",
                "import_source": "VARCHAR DEFAULT ''",
                "import_row_number": "INTEGER DEFAULT 0",
                "import_receipt_json": "TEXT DEFAULT '{}'",
            },
        )
    if "subscriptions" in tables:
        _add_columns(
            conn,
            "subscriptions",
            {
                "original_price_text": "VARCHAR DEFAULT ''",
                "original_currency_code": "VARCHAR DEFAULT ''",
                "base_price_text": "VARCHAR DEFAULT ''",
                "base_currency_code": "VARCHAR DEFAULT ''",
                "fx_rate_text": "VARCHAR DEFAULT ''",
                "fx_rate_date": "VARCHAR DEFAULT ''",
                "fx_source": "VARCHAR DEFAULT ''",
            },
        )
    if "sub_payments" in tables:
        _add_columns(
            conn,
            "sub_payments",
            {
                "original_amount_text": "VARCHAR DEFAULT ''",
                "original_currency_code": "VARCHAR DEFAULT ''",
                "base_amount_text": "VARCHAR DEFAULT ''",
                "base_currency_code": "VARCHAR DEFAULT ''",
                "fx_rate_text": "VARCHAR DEFAULT ''",
                "fx_rate_date": "VARCHAR DEFAULT ''",
                "fx_source": "VARCHAR DEFAULT ''",
            },
        )

    _create_foundation_tables(conn)
    currencies = _backfill_accounts(conn, ledger_base) if "money_accounts" in tables else {}
    if "money_transactions" in tables:
        _backfill_transactions(conn, currencies, ledger_base)
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_money_transactions_import_identity "
                "ON money_transactions(import_identity) WHERE import_identity <> ''"
            )
        )
    sub_currencies = _backfill_subscriptions(conn, ledger_base) if "subscriptions" in tables else {}
    if "sub_payments" in tables:
        _backfill_payments(conn, sub_currencies, ledger_base)
