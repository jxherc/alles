"""Reviewed, local-only bank statement parsing for Phase 8 Finance imports."""

import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from services.finance_currency import (
    currency_code,
    decimal_text,
    fallback_import_match_fingerprint,
    stable_import_identity,
)

PROFILE_DETAILS = (
    {
        "id": "cibc-csv",
        "label": "CIBC statement CSV",
        "kind": "statement",
        "default_currency_code": "CAD",
    },
    {
        "id": "cmb-csv",
        "label": "China Merchants Bank statement CSV",
        "kind": "statement",
        "default_currency_code": "CNY",
    },
    {
        "id": "cmb-notification",
        "label": "China Merchants Bank notification text",
        "kind": "notification",
        "default_currency_code": "CNY",
    },
    {"id": "rbc-csv", "label": "RBC statement CSV", "kind": "statement", "default_currency_code": "CAD"},
    {"id": "td-csv", "label": "TD Canada Trust statement CSV", "kind": "statement", "default_currency_code": "CAD"},
    {"id": "bmo-csv", "label": "BMO statement CSV", "kind": "statement", "default_currency_code": "CAD"},
    {"id": "scotiabank-csv", "label": "Scotiabank statement CSV", "kind": "statement", "default_currency_code": "CAD"},
    {"id": "icbc-csv", "label": "ICBC statement CSV", "kind": "statement", "default_currency_code": "CNY"},
    {"id": "ccb-csv", "label": "China Construction Bank statement CSV", "kind": "statement", "default_currency_code": "CNY"},
    {"id": "abc-csv", "label": "Agricultural Bank of China statement CSV", "kind": "statement", "default_currency_code": "CNY"},
    {"id": "boc-csv", "label": "Bank of China statement CSV", "kind": "statement", "default_currency_code": "CNY"},
    {"id": "bocom-csv", "label": "Bank of Communications statement CSV", "kind": "statement", "default_currency_code": "CNY"},
)
PROFILES = {item["id"]: item for item in PROFILE_DETAILS}
CANADIAN_PROFILES = frozenset({"cibc-csv", "rbc-csv", "td-csv", "bmo-csv", "scotiabank-csv"})


def _pick(row: dict, *aliases: str) -> str:
    lookup = {
        str(key or "").strip().casefold().lstrip("\ufeff"): value for key, value in row.items()
    }
    for alias in aliases:
        value = lookup.get(alias.casefold())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _date_text(value: str) -> str:
    raw = str(value or "").strip()
    slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw[:10])
    if slash:
        first, second = (int(slash[1]), int(slash[2]))
        if 1 <= first <= 12 and 1 <= second <= 12 and first != second:
            raise ValueError("date is missing or ambiguous")
        pattern = "%d/%m/%Y" if first > 12 else "%m/%d/%Y"
        try:
            return datetime.strptime(raw[:10], pattern).date().isoformat()
        except ValueError:
            raise ValueError("date is missing or ambiguous") from None
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(raw[:10], pattern).date().isoformat()
        except ValueError:
            pass
    match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", raw)
    if match:
        try:
            return datetime(int(match[1]), int(match[2]), int(match[3])).date().isoformat()
        except ValueError:
            pass
    raise ValueError("date is missing or ambiguous")


def _money(value: str) -> Decimal:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("amount is missing")
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"(?i)(CAD|CNY|RMB|USD|EUR|GBP)", "", raw)
    cleaned = cleaned.replace(",", "").replace("$", "").replace("¥", "").replace("￥", "")
    cleaned = cleaned.replace("人民币", "").replace("元", "").strip(" ()+")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError("amount is not a decimal number") from error
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    if len(amount.as_tuple().digits) > 28 or not -18 <= amount.adjusted() <= 18:
        raise ValueError("amount precision or exponent is out of range")
    return -abs(amount) if negative else amount


def _csv_rows(content: str, profile: str) -> list[dict]:
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    clean_content = content.lstrip("\ufeff")
    positional = list(csv.reader(io.StringIO(clean_content), dialect=dialect))
    if profile in CANADIAN_PROFILES and positional:
        first_column = str(positional[0][0] if positional[0] else "").strip().casefold()
        if first_column not in {"transaction date", "date", "posting date", "transaction_date"}:
            rows = []
            fields = ("transaction date", "description", "debit", "credit", "account")
            for line_number, values in enumerate(positional, start=1):
                clean = {
                    field: str(values[index] if index < len(values) else "").strip()
                    for index, field in enumerate(fields)
                }
                if any(clean.values()):
                    rows.append({"line_number": line_number, "raw": clean})
            if not rows:
                raise ValueError("statement has no transaction rows")
            return rows
    reader = csv.DictReader(io.StringIO(clean_content), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("statement has no header row")
    rows = []
    for line_number, row in enumerate(reader, start=2):
        clean = {
            str(key or "").strip().lstrip("\ufeff"): str(value or "").strip()
            for key, value in row.items()
        }
        if any(clean.values()):
            rows.append({"line_number": line_number, "raw": clean})
    if not rows:
        raise ValueError("statement has no transaction rows")
    return rows


def _statement_row(profile: str, row: dict, requested_currency: str) -> dict:
    if profile in CANADIAN_PROFILES:
        date = _pick(row, "transaction date", "date", "posting date", "transaction_date")
        payee = _pick(row, "description", "transaction details", "details", "payee", "memo")
        debit = _pick(row, "debit", "withdrawal", "withdrawals", "funds out")
        credit = _pick(row, "credit", "deposit", "deposits", "funds in")
        amount_raw = _pick(row, "amount", "transaction amount")
        external = _pick(
            row, "transaction id", "reference", "confirmation number", "reference number"
        )
        currency = _pick(row, "currency", "currency code") or requested_currency or "CAD"
    else:
        date = _pick(row, "交易日期", "记账日期", "入账日期", "date")
        payee = _pick(row, "交易摘要", "摘要", "交易名称", "交易说明", "description", "payee")
        debit = _pick(row, "支出金额", "借方金额", "支出", "debit")
        credit = _pick(row, "收入金额", "贷方金额", "收入", "credit")
        amount_raw = _pick(row, "交易金额", "金额", "amount")
        external = _pick(row, "交易流水号", "流水号", "交易编号", "reference", "transaction id")
        currency = _pick(row, "交易币种", "币种", "currency") or requested_currency or "CNY"
    debit_amount = _money(debit) if debit else None
    credit_amount = _money(credit) if credit else None
    if debit_amount not in {None, Decimal(0)} and credit_amount not in {None, Decimal(0)}:
        raise ValueError("both debit and credit are populated")
    if debit_amount not in {None, Decimal(0)}:
        amount = -abs(debit_amount)
    elif credit_amount not in {None, Decimal(0)}:
        amount = abs(credit_amount)
    elif amount_raw:
        amount = _money(amount_raw)
    elif debit_amount is not None:
        amount = -abs(debit_amount)
    elif credit_amount is not None:
        amount = abs(credit_amount)
    else:
        raise ValueError("amount is missing")
    resolved_currency = currency_code(currency)
    if resolved_currency == "XXX":
        raise ValueError("currency is missing or ambiguous")
    amount_text = decimal_text(amount)
    if Decimal(amount_text) != Decimal(amount_text).quantize(Decimal("0.01")):
        raise ValueError("amount has more than two decimal places")
    return {
        "date": _date_text(date),
        "amount_text": amount_text,
        "payee": payee or "bank transaction",
        "currency_code": resolved_currency,
        "external_id": external,
    }


def _notification_row(line: str, requested_currency: str) -> dict:
    date = _date_text(line)
    amount_match = re.search(
        r"(?i)(人民币|RMB|CNY|[¥￥])\s*([0-9][0-9,]*(?:\.\d+)?)\s*元?",
        line,
    )
    if not amount_match:
        raise ValueError("amount is missing or ambiguous")
    debit = bool(re.search(r"支出|消费|支付|扣款|spent|debit|purchase", line, re.I))
    credit = bool(re.search(r"收入|入账|存入|退款|received|credit|deposit", line, re.I))
    if debit == credit:
        raise ValueError("direction is missing or ambiguous")
    suffix_match = re.search(r"(?:尾号|ending(?:\s+in)?|card\s+)(\d{3,6})", line, re.I)
    if not suffix_match:
        raise ValueError("account suffix is missing")
    amount = _money(amount_match.group(2))
    amount = -abs(amount) if debit else abs(amount)
    merchant = re.search(r"商户\s*[:：]?\s*([^，,。.;]+)", line)
    if merchant is None:
        merchant = re.search(r"(?:于|\bat\b)\s*([^，,。.;]+)", line[amount_match.end() :], re.I)
    reference = re.search(
        r"(?:交易流水号|流水号|交易编号|参考号|reference(?:\s+(?:number|id))?|transaction\s+id)"
        r"\s*[:：#]?\s*([A-Za-z0-9][A-Za-z0-9_-]{0,63})",
        line,
        re.I,
    )
    detected_currency = currency_code(amount_match.group(1))
    if detected_currency == "XXX" and amount_match.group(1) in {"¥", "￥"}:
        detected_currency = "CNY"
    requested_code = currency_code(requested_currency) if requested_currency else detected_currency
    if detected_currency == "XXX" or requested_code == "XXX":
        raise ValueError("currency is missing or ambiguous")
    if requested_code != detected_currency:
        raise ValueError("requested currency conflicts with the notification currency")
    amount_text = decimal_text(amount)
    if Decimal(amount_text) != Decimal(amount_text).quantize(Decimal("0.01")):
        raise ValueError("amount has more than two decimal places")
    return {
        "date": date,
        "amount_text": amount_text,
        "payee": (merchant.group(1).strip() if merchant else "CMB notification"),
        "currency_code": detected_currency,
        "external_id": reference.group(1) if reference else "",
        "account_suffix": suffix_match.group(1),
    }


def parse(
    profile: str,
    content: str,
    *,
    account_id: str,
    requested_currency: str = "",
    statement_identity: str = "",
) -> list[dict]:
    if profile not in PROFILES:
        raise ValueError("unsupported import profile")
    raw_rows = (
        [
            {"line_number": index, "raw": {"notification": line.strip()}}
            for index, line in enumerate(content.splitlines(), start=1)
            if line.strip()
        ]
        if profile == "cmb-notification"
        else _csv_rows(content, profile)
    )
    if not raw_rows:
        raise ValueError("source has no transaction rows")
    parsed_rows = []
    for item in raw_rows:
        try:
            parsed = (
                _notification_row(item["raw"]["notification"], requested_currency)
                if profile == "cmb-notification"
                else _statement_row(profile, item["raw"], requested_currency)
            )
            parsed_rows.append({**item, "parsed": parsed, "stable_identity": "", "error": ""})
        except ValueError as error:
            parsed_rows.append({**item, "parsed": {}, "stable_identity": "", "error": str(error)})

    for item in parsed_rows:
        parsed = item["parsed"]
        if item["error"]:
            continue
        if not parsed["external_id"]:
            if not str(statement_identity or "").strip():
                item["error"] = "statement identity is required when rows have no bank reference"
                continue
            parsed["match_fingerprint"] = fallback_import_match_fingerprint(
                profile,
                account_id,
                parsed["date"],
                parsed["amount_text"],
                parsed["payee"],
                currency=parsed["currency_code"],
            )
            occurrence_identity = f"{statement_identity}:{item['line_number']}"
            item["stable_identity"] = stable_import_identity(
                profile,
                account_id,
                occurrence_identity=occurrence_identity,
            )
        else:
            item["stable_identity"] = stable_import_identity(
                profile,
                account_id,
                external_id=parsed["external_id"],
            )
    return parsed_rows
