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
        "id": "generic-csv",
        "label": "CSV (date, payee, amount)",
        "kind": "statement",
        "default_currency_code": "",
    },
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
    {
        "id": "bank-email",
        "label": "Bank alert emails",
        "kind": "notification",
        "default_currency_code": "",
    },
    {
        "id": "rbc-csv",
        "label": "RBC statement CSV",
        "kind": "statement",
        "default_currency_code": "CAD",
    },
    {
        "id": "td-csv",
        "label": "TD Canada Trust statement CSV",
        "kind": "statement",
        "default_currency_code": "CAD",
    },
    {
        "id": "bmo-csv",
        "label": "BMO statement CSV",
        "kind": "statement",
        "default_currency_code": "CAD",
    },
    {
        "id": "scotiabank-csv",
        "label": "Scotiabank statement CSV",
        "kind": "statement",
        "default_currency_code": "CAD",
    },
    {
        "id": "icbc-csv",
        "label": "ICBC statement CSV",
        "kind": "statement",
        "default_currency_code": "CNY",
    },
    {
        "id": "ccb-csv",
        "label": "China Construction Bank statement CSV",
        "kind": "statement",
        "default_currency_code": "CNY",
    },
    {
        "id": "abc-csv",
        "label": "Agricultural Bank of China statement CSV",
        "kind": "statement",
        "default_currency_code": "CNY",
    },
    {
        "id": "boc-csv",
        "label": "Bank of China statement CSV",
        "kind": "statement",
        "default_currency_code": "CNY",
    },
    {
        "id": "bocom-csv",
        "label": "Bank of Communications statement CSV",
        "kind": "statement",
        "default_currency_code": "CNY",
    },
)
PROFILES = {item["id"]: item for item in PROFILE_DETAILS}
CANADIAN_PROFILES = frozenset({"cibc-csv", "rbc-csv", "td-csv", "bmo-csv", "scotiabank-csv"})
# rows from these name a card or account ending, which the owner confirms belongs to the account
NOTIFICATION_PROFILES = frozenset(
    item["id"] for item in PROFILE_DETAILS if item["kind"] == "notification"
)
# the layout reason the review shows for an email no parser shape fits; nothing is guessed
EMAIL_SHAPE_UNKNOWN = "this email's layout isn't one alles reads yet"
RAW_EMAIL_CHARS = 4000


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
    if profile in CANADIAN_PROFILES or profile == "generic-csv":
        date = _pick(row, "transaction date", "date", "posting date", "transaction_date")
        payee = _pick(row, "description", "transaction details", "details", "payee", "memo")
        debit = _pick(row, "debit", "withdrawal", "withdrawals", "funds out")
        credit = _pick(row, "credit", "deposit", "deposits", "funds in")
        amount_raw = _pick(row, "amount", "transaction amount")
        external = _pick(
            row, "transaction id", "reference", "confirmation number", "reference number"
        )
        currency = _pick(row, "currency", "currency code") or requested_currency
        if not currency and profile != "generic-csv":
            currency = "CAD"
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
    parsed = {
        "date": _date_text(date),
        "amount_text": amount_text,
        "payee": payee if profile == "generic-csv" else payee or "bank transaction",
        "currency_code": resolved_currency,
        "external_id": external,
    }
    if profile == "generic-csv":
        parsed.update({key: _pick(row, key) for key in ("category", "notes", "tags")})
    return parsed


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


_EMAIL_MONEY = re.compile(
    r"(?P<pre>US\$|USD\s?|CA\$|C\$|CAD\s?|EUR\s?|GBP\s?|€|£|\$)\s?(?P<num>\d[\d,]*(?:\.\d{1,2})?)"
    r"(?:\s?(?P<post>USD|CAD|EUR|GBP)\b)?"
)
_EMAIL_SYMBOLS = {"US$": "USD", "CA$": "CAD", "C$": "CAD", "€": "EUR", "£": "GBP"}
# lines about balances and limits name amounts that are not the transaction
_EMAIL_NOT_THE_AMOUNT = re.compile(
    r"(?i)balance|available|credit limit|minimum|statement|threshold|alerts? (?:over|above)|"
    r"more than|greater than|exceeds?"
)
_EMAIL_DEBIT = re.compile(
    r"(?i)\b(purchase[ds]?|spent|charged|charge|payment|paid|withdrawals?|withdrawn|"
    r"debit(?:ed)?|sent)\b"
)
_EMAIL_CREDIT = re.compile(r"(?i)\b(deposit(?:ed)?|refund(?:ed)?|credited|received)\b")
_EMAIL_SUFFIX = re.compile(
    r"(?i)(?:ending(?:\s+in)?|ends\s+(?:in|with)|last\s+(?:4|four)\s+digits?(?:\s+of)?|"
    r"[*x•]{2,}|\.{3})\s*#?\s*(\d{4})\b"
)
_EMAIL_LABELLED = re.compile(
    r"(?im)^\s*(merchant|payee|description|where|amount|date|transaction date|card|account)"
    r"\s*[:：]\s*(.+?)\s*$"
)
_EMAIL_MERCHANT = re.compile(
    r"(?:\bat|\bwith|\bto|\bfrom)\s+(?!your\b|you\b|the\s+account\b)"
    r"([A-Z0-9][A-Za-z0-9&'*#./ -]{1,60}?)"
    r"(?=\s+(?:on|using|with|for|was|from|to|at)\b|[.,;!\n]|$)"
)
_EMAIL_DATE = re.compile(
    r"(?i)\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b"
)


def _email_date(text: str, sent: str) -> str:
    """the date the alert names, else the day the bank sent it (alerts go out as it happens)."""
    found = _EMAIL_DATE.search(text)
    if found:
        raw = found.group(1).replace(",", "")
        if raw[:1].isalpha():
            # "Nov 01 2026", "November 1 2026", "Sept. 3 2026": month by its first 3 letters
            short = raw[:3] + raw[raw.index(" ") :]
            try:
                return datetime.strptime(short, "%b %d %Y").date().isoformat()
            except ValueError:
                raise ValueError("date is missing or ambiguous") from None
        return _date_text(raw)
    if sent:
        from email.utils import parsedate_to_datetime

        try:
            when = parsedate_to_datetime(sent)
        except (TypeError, ValueError):
            when = None
        if when is not None:
            return (when.astimezone() if when.tzinfo else when).date().isoformat()
    raise ValueError("date is missing or ambiguous")


def _email_parts(item: dict) -> tuple[dict, str]:
    """the raw fields a review shows, and the text the shapes are read from."""
    subject = str(item.get("subject") or "").strip()
    body = str(item.get("text") or "")
    raw = {
        "email_from": str(item.get("from") or "").strip()[:200],
        "email_subject": subject[:300],
        "email_date": str(item.get("date") or "").strip()[:80],
        "email_text": body.strip()[:RAW_EMAIL_CHARS],
    }
    return raw, f"{subject}\n{body}"


def _bank_email_row(item: dict, requested_currency: str) -> dict:
    """read one alert email. every value comes from the email's own words; a shape that doesn't
    fit is a review row with the raw email, never a guess."""
    raw, text = _email_parts(item)
    labelled = {key.lower(): value for key, value in _EMAIL_LABELLED.findall(text)}
    lines = [line for line in text.splitlines() if not _EMAIL_NOT_THE_AMOUNT.search(line)]
    usable = "\n".join(lines)
    amounts = {}
    for match in _EMAIL_MONEY.finditer(labelled.get("amount", "") or usable):
        code = (match.group("post") or "").strip() or match.group("pre").strip()
        code = _EMAIL_SYMBOLS.get(code, code)
        amounts[(match.group("num").replace(",", ""), code)] = match
    if not amounts:
        raise ValueError(EMAIL_SHAPE_UNKNOWN)
    if len(amounts) > 1:
        raise ValueError("the email names more than one amount")
    (number, code), match = next(iter(amounts.items()))
    plain = re.sub(r"(?i)credit card|credit limit|available credit|debit card", " ", usable)
    debit = bool(_EMAIL_DEBIT.search(plain))
    credit = bool(_EMAIL_CREDIT.search(plain))
    if debit == credit:
        raise ValueError(EMAIL_SHAPE_UNKNOWN if not debit else "direction is missing or ambiguous")
    if code == "$":
        code = requested_currency
    currency = currency_code(code)
    if currency == "XXX":
        raise ValueError("currency is missing or ambiguous")
    amount = _money(number)
    amount = -abs(amount) if debit else abs(amount)
    amount_text = decimal_text(amount)
    suffix = _EMAIL_SUFFIX.search(
        " ".join(filter(None, [labelled.get("card"), labelled.get("account"), usable]))
    )
    if not suffix:
        raise ValueError("account suffix is missing")
    payee = (
        labelled.get("merchant")
        or labelled.get("payee")
        or labelled.get("description")
        or labelled.get("where")
        or ""
    )
    if not payee:
        after = _EMAIL_MERCHANT.search(usable[match.start() :]) or _EMAIL_MERCHANT.search(usable)
        payee = after.group(1).strip() if after else ""
    if not payee:
        payee = (_EMAIL_DEBIT.search(plain) or _EMAIL_CREDIT.search(plain)).group(1).lower()
    reference = re.search(
        r"(?i)(?:reference|confirmation|transaction)\s*(?:number|no\.?|id|#)\s*[:：#]?\s*"
        r"([A-Za-z0-9][A-Za-z0-9_-]{3,63})",
        text,
    )
    message_id = str(item.get("message_id") or "").strip()
    return {
        "date": _email_date(
            labelled.get("date") or labelled.get("transaction date") or text, raw["email_date"]
        ),
        "amount_text": amount_text,
        "payee": payee[:120],
        "currency_code": currency,
        "external_id": reference.group(1) if reference else message_id[:200],
        "account_suffix": suffix.group(1),
    }


_ALERT_SUBJECT = re.compile(
    r"(?i)\b(alert|transaction|purchase|payment|deposit|withdrawal|spent|charged?|refund|"
    r"e-?transfer)\b"
)
_ALERT_SENDER = re.compile(
    r"(?i)\b(bank|card|alerts?|notifications?|notify|visa|mastercard|amex)\b"
)
MAIL_ALERT_LIMIT = 50


def mail_alert_emails(db, days: int = 60, limit: int = MAIL_ALERT_LIMIT) -> list[dict]:
    """bank alert emails from the saved inbox of every mail account, newest first: a subject
    about a transaction from a sender (or subject) that names a bank, card or alert. bodies come
    from the stored copies, else one read from the mail server, which is then kept."""
    import time

    from core.database import CachedMessage, MailAccount
    from services import mail as mailsvc
    from services import mail_cache

    since = time.time() - max(1, min(int(days), 366)) * 86400
    rows = (
        db.query(CachedMessage)
        .filter(CachedMessage.folder == "INBOX", CachedMessage.date_ts >= since)
        .order_by(CachedMessage.date_ts.desc())
        .all()
    )
    picked = [
        row
        for row in rows
        if _ALERT_SUBJECT.search(row.subject or "")
        and (_ALERT_SENDER.search(row.sender or "") or _ALERT_SENDER.search(row.subject or ""))
    ][:limit]
    accounts = {}
    out = []
    for row in picked:
        body = mail_cache.stored_body(db, row.account_id, "INBOX", row.uid)
        if body is None:
            if row.account_id not in accounts:
                account = db.get(MailAccount, row.account_id)
                accounts[row.account_id] = account
            account = accounts[row.account_id]
            if account is None:
                continue
            from routes.mail import _acct_dict

            try:
                body = mailsvc.fetch_message(_acct_dict(account), row.uid, "INBOX")
            except Exception:
                body = {"error": "unreachable"}
            if body.get("error"):
                # the review still shows the email, from its saved headers, with nothing guessed
                body = {"text": "", "from": row.sender, "subject": row.subject, "date": row.date}
            else:
                mail_cache.keep_body(db, row.account_id, "INBOX", body | {"uid": row.uid})
        text = body.get("text") or re.sub(r"<[^>]+>", " ", body.get("html") or "")
        out.append(
            {
                "from": body.get("from") or row.sender or "",
                "subject": body.get("subject") or row.subject or "",
                "date": body.get("date") or row.date or "",
                "message_id": body.get("message_id") or row.message_id or "",
                "text": text,
            }
        )
    return out


def bank_emails(content: str) -> list[dict]:
    """the emails in a bank-email source: the json list mail hands over, a saved .eml file, or
    one pasted email."""
    stripped = content.lstrip("﻿").strip()
    if stripped.startswith("["):
        import json

        try:
            items = json.loads(stripped)
        except ValueError as error:
            raise ValueError("the email list could not be read") from error
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError("the email list could not be read")
        return items
    import email
    from email import policy

    message = email.message_from_string(stripped, policy=policy.default)
    if message.get("From") or message.get("Subject"):
        part = message.get_body(preferencelist=("plain", "html"))
        body = part.get_content() if part is not None else ""
        if part is not None and part.get_content_type() == "text/html":
            body = re.sub(r"<[^>]+>", " ", body)
        return [
            {
                "from": str(message.get("From") or ""),
                "subject": str(message.get("Subject") or ""),
                "date": str(message.get("Date") or ""),
                "message_id": str(message.get("Message-ID") or ""),
                "text": body,
            }
        ]
    return [{"text": stripped}]


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
    emails = bank_emails(content) if profile == "bank-email" else []
    if profile == "bank-email":
        raw_rows = [
            {"line_number": index, "raw": _email_parts(item)[0], "email": item}
            for index, item in enumerate(emails, start=1)
        ]
    elif profile == "cmb-notification":
        raw_rows = [
            {"line_number": index, "raw": {"notification": line.strip()}}
            for index, line in enumerate(content.splitlines(), start=1)
            if line.strip()
        ]
    else:
        raw_rows = _csv_rows(content, profile)
    if not raw_rows:
        raise ValueError("source has no transaction rows")
    parsed_rows = []
    for item in raw_rows:
        email_item = item.pop("email", None)
        try:
            if email_item is not None:
                parsed = _bank_email_row(email_item, requested_currency)
            elif profile == "cmb-notification":
                parsed = _notification_row(item["raw"]["notification"], requested_currency)
            else:
                parsed = _statement_row(profile, item["raw"], requested_currency)
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
