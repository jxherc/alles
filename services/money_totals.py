"""One currency for totals: the owner's choice, their saved rates, and what stays out.

The choice and the rates live in settings, not the ledger. They only change how totals are
added up, never a stored amount or its reviewed evidence. Actual keeps its own reviewed base.
"""

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from sqlalchemy import inspect as sa_inspect

from core.database import Account, FinanceLedgerState, Transaction, TxnSplit
from core.settings import load_settings, save_settings
from services import actual_finance
from services.finance_currency import amount_currency, currency_code
from services.money_stats import finite_amount

BASE_KEY = "money_base_currency"
RATES_KEY = "money_fx_rates"


# digits with one optional decimal point: Decimal would also take 1_000, 1e3 or "  +1"
_PLAIN_RATE = re.compile(r"\d{1,12}(\.\d{1,12})?")


def _rate(value) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            value = format(Decimal(str(value)), "f")
        except (InvalidOperation, ValueError):
            return None
    if not isinstance(value, str) or not _PLAIN_RATE.fullmatch(value.strip()):
        return None
    rate = Decimal(value.strip())
    return rate if rate > 0 else None


def parse_rate(value) -> Decimal:
    rate = _rate(value)
    if rate is None:
        raise ValueError("enter a rate above zero with a dot for decimals, like 1.37")
    return rate


def _exact(text) -> Decimal | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def ledger_base(db) -> str:
    # narrow fixtures make only the ledger tables; they read as the default, like is_canonical
    if not sa_inspect(db.connection()).has_table(FinanceLedgerState.__tablename__):
        return "CAD"
    state = db.get(FinanceLedgerState, "primary")
    code = currency_code(state.base_currency_code if state else "CAD")
    return "CAD" if code == "XXX" else code


def base_currency(db) -> dict:
    """the currency totals are shown in: the owner's pick, else the ledger's (CAD by default).
    never guessed from the data, so adding an account can't flip it. Actual's is fixed"""
    if actual_finance.is_canonical(db):
        return {"code": ledger_base(db), "fixed": True}
    chosen = currency_code(load_settings().get(BASE_KEY) or "")
    return {"code": ledger_base(db) if chosen == "XXX" else chosen, "fixed": False}


def saved_rates() -> dict:
    """{(from, to): {"rate": Decimal, "text": "1.37", "date": "2026-10-24"}}, bad rows skipped"""
    raw = load_settings().get(RATES_KEY)
    out = {}
    if not isinstance(raw, dict):
        return out
    for pair, row in raw.items():
        if not isinstance(pair, str) or not isinstance(row, dict) or pair.count(">") != 1:
            continue
        frm, to = (currency_code(part) for part in pair.split(">"))
        rate = _rate(row.get("rate"))
        if frm == "XXX" or to == "XXX" or frm == to or rate is None:
            continue
        out[(frm, to)] = {
            "rate": rate,
            "text": str(row.get("rate")).strip(),
            "date": str(row.get("date") or ""),
        }
    return out


def rate_row(frm: str, to: str, saved: dict) -> dict:
    return {"from": frm, "to": to, "rate": saved["text"], "date": saved["date"]}


def save_rate(frm, to, rate, on: date | None = None) -> dict:
    frm, to = currency_code(frm), currency_code(to)
    if frm == "XXX" or to == "XXX":
        raise ValueError("choose two currency codes, like USD and CAD")
    if frm == to:
        raise ValueError("a rate needs two different currencies")
    raw = load_settings().get(RATES_KEY)
    rates = dict(raw) if isinstance(raw, dict) else {}
    # one rate per pair: the reverse of this pair would disagree with it, so it goes
    rates.pop(f"{to}>{frm}", None)
    if rate in (None, ""):
        rates.pop(f"{frm}>{to}", None)
        save_settings({RATES_KEY: rates})
        return {}
    text = format(parse_rate(rate).normalize(), "f")
    row = {"rate": text, "date": (on or date.today()).isoformat()}
    rates[f"{frm}>{to}"] = row
    save_settings({RATES_KEY: rates})
    return {"from": frm, "to": to, **row}


def save_base(code) -> str:
    code = currency_code(code)
    if code == "XXX":
        raise ValueError("choose a currency code, like CAD or USD")
    save_settings({BASE_KEY: code})
    return code


class Totals:
    """turns amounts into the base currency and remembers which rates it leaned on"""

    def __init__(self, base: str, rates: dict | None = None):
        self.base = base
        self.rates = saved_rates() if rates is None else rates
        self.used: dict[tuple[str, str], dict] = {}

    def factor(self, code) -> Decimal | None:
        code = currency_code(code)
        if code == "XXX":
            return None
        if code == self.base:
            return Decimal(1)
        if (code, self.base) in self.rates:
            saved = self.rates[(code, self.base)]
            self.used[(code, self.base)] = rate_row(code, self.base, saved)
            return saved["rate"]
        if (self.base, code) in self.rates:
            saved = self.rates[(self.base, code)]
            self.used[(self.base, code)] = rate_row(self.base, code, saved)
            return 1 / saved["rate"]
        return None

    def convert(self, amount, code) -> float | None:
        factor = self.factor(code)
        if factor is None:
            return None
        return float(Decimal(str(finite_amount(amount or 0.0))) * factor)

    def rates_used(self) -> list[dict]:
        return sorted(self.used.values(), key=lambda row: (row["from"], row["to"]))


def payload(
    totals: Totals, base: dict, left_out: list, *, ledger: str = "", included: bool = True
) -> dict:
    """the fields every total shares: its currency, the rates it used, what it left out, the
    ledger currency saved amounts are in, and whether anything at all made it in"""
    return {
        "currency": totals.base,
        "base_currency": base,
        "ledger_currency": ledger or totals.base,
        "rates": totals.rates_used(),
        "excluded": left_out,
        "complete": not left_out,
        "included": included,
    }


def ledger_amount(totals: Totals, ledger: str, amount) -> tuple[float, str]:
    """a plain saved number (a cap, an assignment, a goal) is in the ledger currency. shown in
    the totals currency when a rate allows, else as it is, in the ledger currency"""
    factor = totals.factor(ledger)
    value = Decimal(str(finite_amount(amount or 0.0)))
    if factor is None:
        return float(value), ledger
    return float(value * factor), totals.base


class BaseLedger:
    """the local ledger with each amount in the base currency.

    an amount with no rate stays out and is counted per currency, so a total can say what it
    left out. a ledger with no known currency at all (old "$" accounts) has nothing to convert
    from: it keeps adding raw amounts, as it always did, and says so with unit=None.
    """

    def __init__(self, db, totals: Totals, accounts=None, transactions=None):
        self.totals = totals
        accounts = db.query(Account).all() if accounts is None else accounts
        transactions = db.query(Transaction).all() if transactions is None else transactions
        self.account_rows = accounts
        codes = {currency_code(a.currency_code or a.currency) for a in accounts}
        codes |= {currency_code(t.original_currency_code) for t in transactions}
        codes.discard("XXX")
        self.unit = totals.base if codes else None
        self.accounts = []
        self.transactions = []
        self.factors: dict[str, Decimal] = {}  # transaction id -> factor, for its splits
        self.left_accounts = []  # (account, code)
        self.left_transactions = []  # (transaction, code its amount is in)
        self.included = False
        by_id = {a.id: a for a in accounts}
        for a in accounts:
            code = currency_code(a.currency_code or a.currency)
            opening = Decimal(str(finite_amount(a.opening or 0.0)))
            value = opening if self.unit is None else None
            # reviewed evidence into this same base counts exactly, then a saved pair rate
            if value is None and code != "XXX" and code != totals.base:
                if currency_code(a.base_currency_code or "") == totals.base:
                    value = _exact(a.base_opening_text)
            if value is None:
                factor = totals.factor(code)
                value = None if factor is None else opening * factor
            if value is None:
                self.left_accounts.append((a, code))
                opening_base = 0.0
            else:
                self.included = True
                opening_base = float(value)
            self.accounts.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "opening": opening_base,
                    "archived": a.archived,
                    "low_balance": a.low_balance,
                }
            )
        for t in transactions:
            account = by_id.get(t.account_id)
            # the currency the amount is really in: a reviewed renewal posts its converted
            # price into the account. blank historical evidence stays unknown
            own = amount_currency(t, (account.currency_code or account.currency) if account else "")
            original = currency_code(t.original_currency_code)
            amount = Decimal(str(finite_amount(t.amount or 0.0)))
            value = amount if self.unit is None else None
            if value is None and original != "XXX":
                # reviewed evidence counts exactly: its base amount, or the original price
                if currency_code(t.base_currency_code or "") == totals.base:
                    value = _exact(t.base_amount_text)
                if value is None and original == totals.base:
                    value = _exact(t.original_amount_text)
            if value is None:
                factor = totals.factor(own)
                value = None if factor is None else amount * factor
            if value is None:
                self.left_transactions.append((t, own))
                continue
            self.included = True
            # a split divides the posted amount, so it takes the same share
            self.factors[t.id] = value / amount if amount else Decimal(0)
            self.transactions.append(
                SimpleNamespace(
                    id=t.id,
                    account_id=t.account_id,
                    date=t.date,
                    amount=float(value),
                    category=t.category,
                    payee=t.payee,
                    notes=t.notes,
                    tags=t.tags,
                    transfer_id=t.transfer_id,
                    archived=bool(by_id.get(t.account_id) and by_id[t.account_id].archived),
                )
            )

    def splits(self, db) -> dict:
        by_txn = defaultdict(list)
        for split in db.query(TxnSplit).all():
            factor = self.factors.get(split.txn_id)
            if factor is None:
                continue
            by_txn[split.txn_id].append(
                SimpleNamespace(
                    txn_id=split.txn_id,
                    category=split.category,
                    amount=float(Decimal(str(finite_amount(split.amount or 0.0))) * factor),
                )
            )
        return by_txn

    def rows(self) -> tuple[list[dict], list[dict]]:
        """plain account and transaction rows for the forecast and history helpers"""
        return self.accounts, [
            {
                "account_id": t.account_id,
                "date": t.date,
                "amount": t.amount,
                "category": t.category,
                "transfer_id": t.transfer_id,
            }
            for t in self.transactions
        ]

    def balances(self) -> dict:
        out = defaultdict(float)
        for t in self.transactions:
            out[t.account_id] += t.amount
        return out

    def account_factor(self, account_id) -> Decimal | None:
        if self.unit is None:
            return Decimal(1)
        account = next((a for a in self.account_rows if a.id == account_id), None)
        if account is None:
            return None
        code = currency_code(account.currency_code or account.currency)
        return self.totals.factor(code)

    def left_out(self, month: str = "", within=None) -> list[dict]:
        """per currency: how many accounts and entries stay out, and their own-currency sums.
        income and expense count the month's entries, or those within(t) for a date range"""
        if within is None:
            within = lambda t: bool(month) and (t.date or "")[:7] == month  # noqa: E731
        groups = {}

        def group(code):
            if code not in groups:
                groups[code] = {
                    "currency": code,
                    "accounts": set(),
                    "transactions": 0,
                    "net_worth": 0.0,
                    "income": 0.0,
                    "expense": 0.0,
                }
            return groups[code]

        archived = {a.id for a in self.account_rows if a.archived}
        for a, code in self.left_accounts:
            row = group(code)
            row["accounts"].add(a.id)
            if a.id not in archived:
                row["net_worth"] += finite_amount(a.opening or 0.0)
        for t, code in self.left_transactions:
            row = group(code)
            row["transactions"] += 1
            if t.account_id:
                row["accounts"].add(t.account_id)
            amount = finite_amount(t.amount or 0.0)
            if t.account_id not in archived:
                row["net_worth"] += amount
            if not t.transfer_id and within(t):
                row["income" if amount >= 0 else "expense"] += abs(amount)
        return [
            {
                **row,
                "accounts": len(row["accounts"]),
                "net_worth": round(row["net_worth"], 2),
                "income": round(row["income"], 2),
                "expense": round(row["expense"], 2),
            }
            for row in sorted(groups.values(), key=lambda row: row["currency"])
        ]
