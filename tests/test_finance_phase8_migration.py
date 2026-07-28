import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from core.migrations import m0037_finance_currency_import_foundation as migration


class FinancePhase8MigrationTests(unittest.TestCase):
    def test_stored_conversion_rate_requires_valid_currencies_and_reconciled_amounts(self):
        valid = migration._conversion_evidence(
            "100", "USD", "135.00", "CAD", "1.35", "reviewed legacy rate"
        )
        self.assertEqual(valid, ("1.35", "reviewed legacy rate"))
        self.assertEqual(
            migration._conversion_evidence("100", "CAD", "100.00", "CAD", "", ""),
            ("1", "legacy_identity"),
        )

        invalid = (
            ("100", "XXX", "135.00", "CAD", "1.35"),
            ("100", "USD", "135.00", "CAD", "NaN"),
            ("100", "USD", "135.00", "CAD", "-1.35"),
            ("100", "USD", "135.00", "CAD", "1.25"),
            ("100", "USD", "135.001", "CAD", "1.35"),
            ("100", "CAD", "99.00", "CAD", "1"),
            ("100", "CAD", "100.00", "CAD", "2"),
        )
        for original, currency, base, base_currency, rate in invalid:
            with self.subTest(
                currency=currency,
                base=base,
                base_currency=base_currency,
                rate=rate,
            ):
                self.assertEqual(
                    migration._conversion_evidence(
                        original,
                        currency,
                        base,
                        base_currency,
                        rate,
                        "unverified legacy rate",
                    ),
                    ("", "unverified legacy rate"),
                )
        for original, base in (("100", "99.00"), ("NaN", "NaN"), ("Infinity", "Infinity")):
            with self.subTest(original=original, base=base, missing_rate=True):
                self.assertEqual(
                    migration._conversion_evidence(
                        original, "CAD", base, "CAD", "", "unverified legacy identity"
                    ),
                    ("", "unverified legacy identity"),
                )

    def test_stored_conversion_uses_the_base_currency_minor_unit(self):
        self.assertEqual(
            migration._conversion_evidence(
                "1", "USD", "0.307", "KWD", "0.307", "reviewed legacy rate"
            ),
            ("0.307", "reviewed legacy rate"),
        )
        self.assertEqual(
            migration._conversion_evidence(
                "1", "USD", "151", "JPY", "150.6", "reviewed legacy rate"
            ),
            ("150.6", "reviewed legacy rate"),
        )
        self.assertEqual(
            migration._conversion_evidence(
                "1", "USD", "0.3071", "KWD", "0.3071", "unverified legacy rate"
            ),
            ("", "unverified legacy rate"),
        )

    def test_derived_conversion_rejects_unbounded_or_fractional_minor_amounts(self):
        self.assertEqual(
            migration._conversion_evidence("100", "USD", "135.00", "CAD", "", ""),
            ("1.35", "legacy_derived_amounts"),
        )
        for original, base, base_currency in (
            ("100", "135.001", "CAD"),
            ("1", "1e19", "CAD"),
            ("1e-19", "1.00", "CAD"),
            ("1", "0.0001", "KWD"),
        ):
            with self.subTest(original=original, base=base, base_currency=base_currency):
                self.assertEqual(
                    migration._conversion_evidence(
                        original, "USD", base, base_currency, "", "legacy amounts"
                    ),
                    ("", "legacy amounts"),
                )

    def test_migration_trusts_only_reviewed_currency_codes_and_aliases(self):
        for value, expected in (
            ("CAD", "CAD"),
            ("usd", "USD"),
            ("RMB", "CNY"),
            ("TWD", "TWD"),
            ("krw", "KRW"),
            ("NZD", "NZD"),
            ("SEK", "SEK"),
            ("BTC", "XXX"),
            ("NAN", "XXX"),
            ("ABC", "XXX"),
        ):
            with self.subTest(value=value):
                self.assertEqual(migration._currency_code(value), expected)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "legacy.sqlite3"
        self.engine = create_engine(f"sqlite:///{self.path}")
        with self.engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(
                text(
                    "CREATE TABLE money_accounts (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, "
                    "kind VARCHAR, currency VARCHAR, opening FLOAT, color VARCHAR, archived BOOLEAN, "
                    "low_balance FLOAT, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE money_transactions (id VARCHAR PRIMARY KEY, account_id VARCHAR, "
                    "date VARCHAR NOT NULL, amount FLOAT, category VARCHAR, payee VARCHAR, notes TEXT, "
                    "transfer_id VARCHAR, tags TEXT, receipt_id VARCHAR, cleared BOOLEAN, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE subscriptions (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, price FLOAT, "
                    "currency VARCHAR, cycle VARCHAR, cycle_days INTEGER, next_due VARCHAR NOT NULL, "
                    "category VARCHAR, url VARCHAR, notes TEXT, active BOOLEAN, remind_days INTEGER, "
                    "last_notified_due VARCHAR, account_id VARCHAR, last_posted_due VARCHAR, trial_end VARCHAR, "
                    "cancel_url VARCHAR, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE sub_payments (id VARCHAR PRIMARY KEY, sub_id VARCHAR, date VARCHAR, "
                    "amount FLOAT, txn_id VARCHAR, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO money_accounts VALUES "
                    "('cad','chequing','checking','CAD',100.25,'accent',0,0,NULL),"
                    "('unknown','cash','cash','$',-3.1,'accent',0,0,NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO money_transactions VALUES "
                    "('t1','cad','2026-01-01',12.34,'income','pay','', '', '', '', 1, NULL),"
                    "('t2','cad','2026-01-02',-4.56,'food','shop','', '', '', '', 0, NULL),"
                    "('t3','unknown','2026-01-03',0.1,'','coin','', '', '', '', 0, NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO subscriptions VALUES "
                    "('s1','service',9.99,'CAD','monthly',30,'2026-08-01','','','',1,1,'','','','','',NULL),"
                    "('s2','ambiguous',4.25,'$','monthly',30,'2026-08-02','','','',1,1,'','','','','',NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO sub_payments VALUES "
                    "('p1','s1','2026-07-01',9.99,'t2',NULL),"
                    "('p2','s2','2026-07-02',4.25,'t3',NULL)"
                )
            )

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def _old_snapshot(self, conn):
        return {
            "accounts": [
                tuple(row)
                for row in conn.execute(
                    text("SELECT id,currency,opening FROM money_accounts ORDER BY id")
                )
            ],
            "transactions": [
                tuple(row)
                for row in conn.execute(
                    text(
                        "SELECT id,account_id,date,amount,category,payee,transfer_id,receipt_id,cleared "
                        "FROM money_transactions ORDER BY id"
                    )
                )
            ],
            "subscriptions": [
                tuple(row)
                for row in conn.execute(
                    text(
                        "SELECT id,price,currency,cycle,next_due,account_id,last_posted_due FROM subscriptions ORDER BY id"
                    )
                )
            ],
            "payments": [
                tuple(row)
                for row in conn.execute(
                    text("SELECT id,sub_id,date,amount,txn_id FROM sub_payments ORDER BY id")
                )
            ],
        }

    def _foundation_snapshot(self, conn):
        return {
            "accounts": [
                tuple(row)
                for row in conn.execute(
                    text(
                        "SELECT id,currency_code,base_currency_code,original_opening_text,base_opening_text "
                        "FROM money_accounts ORDER BY id"
                    )
                )
            ],
            "transactions": [
                tuple(row)
                for row in conn.execute(
                    text(
                        "SELECT id,original_amount_text,original_currency_code,base_amount_text,base_currency_code,"
                        "import_identity FROM money_transactions ORDER BY id"
                    )
                )
            ],
            "evidence": [
                tuple(row)
                for row in conn.execute(
                    text(
                        "SELECT transaction_id,original_amount_text,original_currency_code,base_amount_text,"
                        "base_currency_code,rate_text,source,source_hash FROM money_fx_evidence ORDER BY transaction_id"
                    )
                )
            ],
            "subscriptions": [
                tuple(row)
                for row in conn.execute(
                    text(
                        "SELECT id,original_price_text,original_currency_code,base_price_text,base_currency_code,"
                        "fx_rate_text,fx_source FROM subscriptions ORDER BY id"
                    )
                )
            ],
            "payments": [
                tuple(row)
                for row in conn.execute(
                    text(
                        "SELECT id,original_amount_text,original_currency_code,base_amount_text,base_currency_code "
                        "FROM sub_payments ORDER BY id"
                    )
                )
            ],
        }

    def test_additive_backfill_preserves_every_legacy_value_and_is_idempotent(self):
        with self.engine.begin() as conn:
            before = self._old_snapshot(conn)
            migration.up(conn)
            after = self._old_snapshot(conn)
            first_foundation = self._foundation_snapshot(conn)
            migration.up(conn)
            second_foundation = self._foundation_snapshot(conn)
            transaction_fx = {
                row.id: (row.fx_rate_text, row.fx_rate_date, row.fx_source)
                for row in conn.execute(
                    text(
                        "SELECT id,fx_rate_text,fx_rate_date,fx_source "
                        "FROM money_transactions ORDER BY id"
                    )
                ).mappings()
            }
            evidence_created_at = conn.execute(
                text("SELECT created_at FROM money_fx_evidence WHERE transaction_id='t1'")
            ).scalar_one()
        self.assertEqual(before, after)
        self.assertEqual(first_foundation, second_foundation)
        self.assertTrue(all(row[-1] == "" for row in first_foundation["transactions"]))
        self.assertEqual(len(first_foundation["evidence"]), 2)
        self.assertEqual(first_foundation["accounts"][0][1:3], ("CAD", "CAD"))
        self.assertEqual(first_foundation["accounts"][1][1:3], ("XXX", ""))
        unknown_transaction = next(
            row for row in first_foundation["transactions"] if row[0] == "t3"
        )
        self.assertEqual(unknown_transaction[2:5], ("XXX", "", ""))
        self.assertEqual(transaction_fx["t1"], ("1", "", "legacy_identity"))
        self.assertEqual(transaction_fx["t2"], ("1", "", "legacy_identity"))
        self.assertEqual(transaction_fx["t3"], ("", "", ""))
        self.assertIsNone(datetime.fromisoformat(evidence_created_at).tzinfo)
        unknown_subscription = next(
            row for row in first_foundation["subscriptions"] if row[0] == "s2"
        )
        self.assertEqual(unknown_subscription[2:7], ("XXX", "", "", "", ""))
        unknown_payment = next(row for row in first_foundation["payments"] if row[0] == "p2")
        self.assertEqual(unknown_payment[2:5], ("XXX", "", ""))

    def test_missing_ledger_state_row_uses_the_documented_default_base(self):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE finance_ledger_state ("
                    "id VARCHAR PRIMARY KEY, base_currency_code VARCHAR NOT NULL DEFAULT '')"
                )
            )
            migration.up(conn)
            account = conn.execute(
                text(
                    "SELECT base_currency_code,base_opening_text FROM money_accounts WHERE id='cad'"
                )
            ).one()
            transaction = conn.execute(
                text(
                    "SELECT base_currency_code,base_amount_text,fx_rate_text "
                    "FROM money_transactions WHERE id='t1'"
                )
            ).one()
        self.assertEqual(account, ("CAD", "100.25"))
        self.assertEqual(transaction, ("CAD", "12.34", "1"))

    def test_explicit_iso_codes_outside_the_old_rate_shortlist_are_preserved(self):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO money_accounts VALUES "
                    "('twd','taipei','checking','TWD',250,'accent',0,0,NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO money_transactions VALUES "
                    "('twd-t','twd','2026-01-04',-30,'food','market','', '', '', '', 0, NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO subscriptions VALUES "
                    "('twd-s','local service',90,'TWD','monthly',30,'2026-08-03','','','',1,1,'','','','','',NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO sub_payments VALUES ('twd-p','twd-s','2026-07-03',90,'twd-t',NULL)"
                )
            )
            migration.up(conn)
            account = conn.execute(
                text(
                    "SELECT currency_code,base_currency_code,base_opening_text "
                    "FROM money_accounts WHERE id='twd'"
                )
            ).one()
            transaction = conn.execute(
                text(
                    "SELECT original_currency_code,base_currency_code,base_amount_text "
                    "FROM money_transactions WHERE id='twd-t'"
                )
            ).one()
            subscription = conn.execute(
                text(
                    "SELECT original_currency_code,base_currency_code,base_price_text "
                    "FROM subscriptions WHERE id='twd-s'"
                )
            ).one()
            payment = conn.execute(
                text(
                    "SELECT original_currency_code,base_currency_code,base_amount_text "
                    "FROM sub_payments WHERE id='twd-p'"
                )
            ).one()
            evidence_count = conn.execute(
                text("SELECT COUNT(*) FROM money_fx_evidence WHERE transaction_id='twd-t'")
            ).scalar_one()
        self.assertEqual(account, ("TWD", "", ""))
        self.assertEqual(transaction, ("TWD", "", ""))
        self.assertEqual(subscription, ("TWD", "", ""))
        self.assertEqual(payment, ("TWD", "", ""))
        self.assertEqual(evidence_count, 0)

    def test_old_and_new_account_balances_and_aggregates_match_exactly(self):
        with self.engine.begin() as conn:
            old = {
                row.id: Decimal(str(row.opening)) + Decimal(str(row.txn_total))
                for row in conn.execute(
                    text(
                        "SELECT a.id,a.opening,COALESCE(SUM(t.amount),0) AS txn_total "
                        "FROM money_accounts a LEFT JOIN money_transactions t ON t.account_id=a.id "
                        "WHERE a.currency='CAD' GROUP BY a.id"
                    )
                ).mappings()
            }
            migration.up(conn)
            openings = {
                row.id: Decimal(row.base_opening_text)
                for row in conn.execute(
                    text(
                        "SELECT id,base_opening_text FROM money_accounts WHERE base_opening_text<>''"
                    )
                ).mappings()
            }
            new = dict(openings)
            for row in conn.execute(
                text(
                    "SELECT account_id,base_amount_text FROM money_transactions WHERE base_amount_text<>''"
                )
            ).mappings():
                new[row.account_id] += Decimal(row.base_amount_text)
            old_txn_total = sum(
                Decimal(str(row[0]))
                for row in conn.execute(
                    text("SELECT amount FROM money_transactions WHERE account_id='cad'")
                )
            )
            new_txn_total = sum(
                Decimal(row[0])
                for row in conn.execute(
                    text(
                        "SELECT base_amount_text FROM money_transactions WHERE base_amount_text<>''"
                    )
                )
            )
        self.assertEqual(old, new)
        self.assertEqual(old_txn_total, new_txn_total)

    def test_cross_currency_reviewed_amounts_never_receive_a_false_identity_rate(self):
        with self.engine.begin() as conn:
            migration.up(conn)
            conn.execute(
                text(
                    "UPDATE money_accounts SET original_opening_text='100',currency_code='USD',"
                    "base_opening_text='135',base_currency_code='CAD',opening_fx_rate_text='',opening_fx_source='' "
                    "WHERE id='cad'"
                )
            )
            conn.execute(
                text(
                    "UPDATE money_transactions SET original_amount_text='10',original_currency_code='USD',"
                    "base_amount_text='13.5',base_currency_code='CAD',fx_rate_text='',fx_source='' WHERE id='t1'"
                )
            )
            conn.execute(
                text(
                    "UPDATE subscriptions SET original_price_text='8',original_currency_code='USD',"
                    "base_price_text='10.8',base_currency_code='CAD',fx_rate_text='',fx_source='' WHERE id='s1'"
                )
            )
            conn.execute(
                text(
                    "UPDATE sub_payments SET original_amount_text='8',original_currency_code='USD',"
                    "base_amount_text='10.8',base_currency_code='CAD',fx_rate_text='',fx_source='' WHERE id='p1'"
                )
            )
            migration.up(conn)
            account = conn.execute(
                text(
                    "SELECT opening_fx_rate_text,opening_fx_source FROM money_accounts WHERE id='cad'"
                )
            ).one()
            transaction = conn.execute(
                text("SELECT fx_rate_text,fx_source FROM money_transactions WHERE id='t1'")
            ).one()
            subscription = conn.execute(
                text("SELECT fx_rate_text,fx_source FROM subscriptions WHERE id='s1'")
            ).one()
            payment = conn.execute(
                text("SELECT fx_rate_text,fx_source FROM sub_payments WHERE id='p1'")
            ).one()
            evidence = conn.execute(
                text("SELECT rate_text,source FROM money_fx_evidence WHERE transaction_id='t1'")
            ).one()
        self.assertEqual(account, ("1.35", "legacy_derived_amounts"))
        self.assertEqual(transaction, ("1.35", "legacy_derived_amounts"))
        self.assertEqual(subscription, ("1.35", "legacy_derived_amounts"))
        self.assertEqual(payment, ("1.35", "legacy_derived_amounts"))
        self.assertEqual(evidence, ("1.35", "legacy_derived_amounts"))

    def test_stored_nonidentity_rates_without_amount_evidence_are_cleared(self):
        with self.engine.begin() as conn:
            migration.up(conn)
            conn.execute(
                text(
                    "UPDATE money_accounts SET currency_code='USD',base_currency_code='',"
                    "base_opening_text='',opening_fx_rate_text='1.35',"
                    "opening_fx_source='legacy_review' WHERE id='cad'"
                )
            )
            conn.execute(
                text(
                    "UPDATE money_transactions SET original_currency_code='USD',"
                    "base_currency_code='',base_amount_text='',fx_rate_text='1.35',"
                    "fx_source='legacy_review' WHERE id='t1'"
                )
            )
            conn.execute(
                text(
                    "UPDATE subscriptions SET original_currency_code='USD',"
                    "base_currency_code='',base_price_text='',fx_rate_text='1.35',"
                    "fx_source='legacy_review' WHERE id='s1'"
                )
            )
            conn.execute(
                text(
                    "UPDATE sub_payments SET original_currency_code='USD',"
                    "base_currency_code='',base_amount_text='',fx_rate_text='1.35',"
                    "fx_source='legacy_review' WHERE id='p1'"
                )
            )
            migration.up(conn)
            account = conn.execute(
                text(
                    "SELECT base_opening_text,base_currency_code,opening_fx_rate_text "
                    "FROM money_accounts WHERE id='cad'"
                )
            ).one()
            transaction = conn.execute(
                text(
                    "SELECT base_amount_text,base_currency_code,fx_rate_text "
                    "FROM money_transactions WHERE id='t1'"
                )
            ).one()
            subscription = conn.execute(
                text(
                    "SELECT base_price_text,base_currency_code,fx_rate_text "
                    "FROM subscriptions WHERE id='s1'"
                )
            ).one()
            payment = conn.execute(
                text(
                    "SELECT base_amount_text,base_currency_code,fx_rate_text "
                    "FROM sub_payments WHERE id='p1'"
                )
            ).one()
            evidence_count = conn.execute(
                text("SELECT COUNT(*) FROM money_fx_evidence WHERE transaction_id='t1'")
            ).scalar_one()
        self.assertEqual(account, ("", "", ""))
        self.assertEqual(transaction, ("", "", ""))
        self.assertEqual(subscription, ("", "", ""))
        self.assertEqual(payment, ("", "", ""))
        self.assertEqual(evidence_count, 0)

    def test_nonempty_import_identity_is_unique_while_manual_rows_may_stay_blank(self):
        with self.engine.begin() as conn:
            migration.up(conn)
            common = {
                "account_id": "cad",
                "date": "2026-02-01",
                "amount": 1.0,
                "category": "",
                "payee": "",
                "notes": "",
                "transfer_id": "",
                "tags": "",
                "receipt_id": "",
                "cleared": 0,
            }
            statement = text(
                "INSERT INTO money_transactions "
                "(id,account_id,date,amount,category,payee,notes,transfer_id,tags,receipt_id,cleared,import_identity) "
                "VALUES (:id,:account_id,:date,:amount,:category,:payee,:notes,:transfer_id,:tags,:receipt_id,:cleared,:identity)"
            )
            conn.execute(statement, {**common, "id": "manual-1", "identity": ""})
            conn.execute(statement, {**common, "id": "manual-2", "identity": ""})
            conn.execute(statement, {**common, "id": "import-1", "identity": "sha256:same"})
            with self.assertRaises(IntegrityError):
                conn.execute(statement, {**common, "id": "import-2", "identity": "sha256:same"})


if __name__ == "__main__":
    unittest.main()
