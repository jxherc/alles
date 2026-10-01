from decimal import Decimal
from types import SimpleNamespace

from core.database import MoneyFxEvidence, Subscription, Transaction
from services import finance_currency
from tests._client import ApiTest


class FinanceCurrencyFoundationTests(ApiTest):
    def test_decimal_text_rejects_unbounded_precision_before_fixed_point_formatting(self):
        for value in ("1e1000000000", "1e-1000000000", "12345678901234567890123456789"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "precision or exponent is out of range"),
            ):
                finance_currency.decimal_text(value)

    def test_api_rejects_exact_money_values_outside_supported_range(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "unsafe", "currency": "CAD", "opening": 1e19},
        )
        self.assertEqual(account.status_code, 400)

        valid = self.client.post(
            "/api/money/accounts",
            json={"name": "safe", "currency": "CAD", "opening": 0},
        ).json()
        transaction = self.client.post(
            "/api/money/transactions",
            json={"account_id": valid["id"], "date": "2026-07-22", "amount": 1e19},
        )
        self.assertEqual(transaction.status_code, 400)

        second = self.client.post(
            "/api/money/accounts",
            json={"name": "second", "currency": "CAD", "opening": 0},
        ).json()
        transfer = self.client.post(
            "/api/money/transfer",
            json={
                "from_account": valid["id"],
                "to_account": second["id"],
                "amount": 1e19,
                "date": "2026-07-22",
            },
        )
        self.assertEqual(transfer.status_code, 400)

        recurring = self.client.post(
            "/api/money/recurring",
            json={
                "account_id": valid["id"],
                "amount": 1e19,
                "next_date": "2027-07-22",
            },
        )
        self.assertEqual(recurring.status_code, 400)

        subscription = self.client.post(
            "/api/subscriptions",
            json={
                "name": "unsafe subscription",
                "price": 1e19,
                "currency": "CAD",
                "next_due": "2027-07-22",
            },
        )
        self.assertEqual(subscription.status_code, 400)

        safe_subscription = self.client.post(
            "/api/subscriptions",
            json={
                "name": "safe subscription",
                "price": 10,
                "currency": "CAD",
                "next_due": "2027-07-22",
            },
        ).json()
        updated = self.client.patch(
            f"/api/subscriptions/{safe_subscription['id']}", json={"price": 1e19}
        )
        self.assertEqual(updated.status_code, 400)

    def test_only_reviewed_currency_codes_receive_identity_evidence(self):
        self.assertEqual(finance_currency.currency_code("RMB"), "CNY")
        self.assertEqual(finance_currency.currency_code("元"), "XXX")
        self.assertEqual(finance_currency.currency_code("BTC"), "XXX")
        self.assertEqual(finance_currency.currency_code("NAN"), "XXX")

    def test_manual_account_and_transaction_get_identity_currency_evidence(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "chequing", "kind": "checking", "currency": "CAD", "opening": 12.34},
        ).json()
        self.assertEqual(account["currency_code"], "CAD")
        self.assertEqual(account["base_currency_code"], "CAD")
        self.assertEqual(Decimal(account["original_opening_text"]), Decimal("12.34"))

        transaction = self.client.post(
            "/api/money/transactions",
            json={
                "account_id": account["id"],
                "date": "2026-07-18",
                "amount": -1.25,
                "payee": "tea",
            },
        ).json()
        self.assertEqual(transaction["original_amount_text"], "-1.25")
        self.assertEqual(transaction["base_amount_text"], "-1.25")
        self.assertEqual(transaction["original_currency_code"], "CAD")
        self.assertEqual(transaction["base_currency_code"], "CAD")
        self.assertEqual(transaction["import_identity"], "")

        db = self.db()
        evidence = db.query(MoneyFxEvidence).filter_by(transaction_id=transaction["id"]).one()
        self.assertEqual(evidence.rate_text, "1")
        self.assertEqual(evidence.source, "manual_identity")
        db.close()

    def test_cross_currency_transaction_evidence_requires_a_consistent_positive_rate(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "base", "kind": "checking", "currency": "CAD", "opening": 0},
        ).json()
        db = self.db()
        for rate, base_amount in (
            (None, "20.00"),
            ("0", "20.00"),
            ("-0.2", "20.00"),
            ("1", "20.00"),
            ("0.19", "20.00"),
        ):
            with self.subTest(rate=rate, base_amount=base_amount):
                with self.assertRaises(ValueError):
                    finance_currency.prepare_transaction(
                        db,
                        Transaction(account_id=account["id"], date="2026-07-19", amount=20),
                        source="owner_reviewed",
                        original_amount="100",
                        original_currency_code="CNY",
                        base_amount=base_amount,
                        base_currency_code="CAD",
                        rate=rate,
                    )
        for invalid_rate_date in ("", "2026-02-30", "not-a-date"):
            with self.subTest(rate_date=invalid_rate_date):
                with self.assertRaisesRegex(ValueError, "valid rate date"):
                    finance_currency.prepare_transaction(
                        db,
                        Transaction(account_id=account["id"], date="2026-07-19", amount=20),
                        source="owner_reviewed",
                        original_amount="100",
                        original_currency_code="CNY",
                        base_amount="20.00",
                        base_currency_code="CAD",
                        rate="0.2",
                        rate_date=invalid_rate_date,
                    )
        transaction = Transaction(account_id=account["id"], date="2026-07-19", amount=20)
        evidence = finance_currency.prepare_transaction(
            db,
            transaction,
            source="owner_reviewed",
            original_amount="100",
            original_currency_code="CNY",
            base_amount="20.00",
            base_currency_code="CAD",
            rate="0.2",
            rate_date="2026-07-19",
        )
        self.assertEqual(transaction.base_amount_text, "20.00")
        self.assertEqual(transaction.fx_rate_text, "0.2")
        self.assertEqual(transaction.fx_rate_date, "2026-07-19")
        self.assertEqual(evidence.base_amount_text, "20.00")
        db.rollback()
        db.close()

    def test_amount_edit_updates_evidence_without_creating_a_second_row(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "wallet", "kind": "cash", "currency": "EUR", "opening": 0},
        ).json()
        transaction = self.client.post(
            "/api/money/transactions",
            json={"account_id": account["id"], "date": "2026-07-18", "amount": -2, "payee": "tram"},
        ).json()
        updated = self.client.patch(
            f"/api/money/transactions/{transaction['id']}", json={"amount": -2.5}
        ).json()
        self.assertEqual(updated["original_amount_text"], "-2.5")
        db = self.db()
        rows = db.query(MoneyFxEvidence).filter_by(transaction_id=transaction["id"]).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].base_amount_text, "-2.5")
        self.assertEqual(rows[0].source, "manual_update_identity")
        db.close()

    def test_foreign_account_base_keeps_original_side_evidence_pending_owner_conversion(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "travel", "kind": "cash", "currency": "EUR", "opening": 10},
        ).json()
        reviewed = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "account",
                "target_id": account["id"],
                "base_currency_code": "CAD",
                "rate_text": "1.5",
                "rate_date": "2026-07-18",
                "source": "owner_reviewed",
            },
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        transaction = self.client.post(
            "/api/money/transactions",
            json={"account_id": account["id"], "date": "2026-07-19", "amount": -2},
        ).json()
        self.assertEqual(transaction["original_currency_code"], "EUR")
        self.assertEqual(transaction["base_currency_code"], "")
        self.assertEqual(transaction["base_amount_text"], "")
        db = self.db()
        evidence = db.query(MoneyFxEvidence).filter_by(transaction_id=transaction["id"]).one()
        self.assertEqual(evidence.original_amount_text, "-2.0")
        self.assertEqual(evidence.original_currency_code, "EUR")
        self.assertEqual(evidence.base_amount_text, "")
        self.assertEqual(evidence.base_currency_code, "")
        self.assertEqual(evidence.rate_text, "")
        db.close()

    def test_opening_only_edit_preserves_reviewed_account_conversion(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "travel", "kind": "cash", "currency": "$", "opening": 10},
        ).json()
        reviewed = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "account",
                "target_id": account["id"],
                "original_currency_code": "USD",
                "base_currency_code": "CAD",
                "rate_text": "1.35",
                "rate_date": "2026-07-18",
                "source": "owner_reviewed",
            },
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)

        updated = self.client.patch(f"/api/money/accounts/{account['id']}", json={"opening": 20})

        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["currency_code"], "USD")
        self.assertEqual(updated.json()["base_currency_code"], "CAD")
        self.assertEqual(updated.json()["base_opening_text"], "27.00")
        self.assertEqual(updated.json()["opening_fx_rate_text"], "1.35")
        self.assertIn("owner_reviewed", updated.json()["opening_fx_source"])

    def test_foreign_amount_edit_clears_stale_conversion_and_synchronizes_original_evidence(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "travel", "kind": "cash", "currency": "EUR", "opening": 10},
        ).json()
        self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "account",
                "target_id": account["id"],
                "base_currency_code": "CAD",
                "rate_text": "1.5",
                "rate_date": "2026-07-18",
                "source": "owner_reviewed",
            },
        )
        transaction = self.client.post(
            "/api/money/transactions",
            json={"account_id": account["id"], "date": "2026-07-19", "amount": -2},
        ).json()
        converted = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "transaction",
                "target_id": transaction["id"],
                "base_currency_code": "CAD",
                "rate_text": "1.5",
                "rate_date": "2026-07-19",
                "source": "owner_reviewed",
            },
        )
        self.assertEqual(converted.status_code, 200, converted.text)
        self.assertEqual(converted.json()["base_amount_text"], "-3.00")

        updated = self.client.patch(
            f"/api/money/transactions/{transaction['id']}",
            json={"amount": -4},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["base_amount_text"], "")
        db = self.db()
        evidence = db.query(MoneyFxEvidence).filter_by(transaction_id=transaction["id"]).one()
        self.assertEqual(evidence.original_amount_text, "-4.0")
        self.assertEqual(evidence.base_amount_text, "")
        self.assertEqual(evidence.rate_text, "")
        db.close()

        reviewed_again = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "transaction",
                "target_id": transaction["id"],
                "base_currency_code": "CAD",
                "rate_text": "2",
                "rate_date": "2026-07-20",
                "source": "statement_rate",
            },
        )
        self.assertEqual(reviewed_again.status_code, 200, reviewed_again.text)
        self.assertEqual(reviewed_again.json()["base_amount_text"], "-8.00")

    def test_ambiguous_currency_symbol_is_recorded_as_unknown_not_invented(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "cash", "kind": "cash", "currency": "$", "opening": 1},
        ).json()
        self.assertEqual(account["currency_code"], "XXX")
        self.assertEqual(account["base_currency_code"], "")
        self.assertEqual(account["base_opening_text"], "")
        transaction = self.client.post(
            "/api/money/transactions",
            json={"account_id": account["id"], "date": "2026-07-18", "amount": 1},
        ).json()
        self.assertEqual(transaction["original_currency_code"], "XXX")
        self.assertEqual(transaction["base_currency_code"], "")
        self.assertEqual(transaction["base_amount_text"], "")
        db = self.db()
        self.assertEqual(db.query(MoneyFxEvidence).count(), 0)
        db.close()

    def test_ambiguous_subscription_is_rejected_without_fabricated_evidence(self):
        response = self.client.post(
            "/api/subscriptions",
            json={
                "name": "ambiguous",
                "price": 8.75,
                "currency": "$",
                "cycle": "monthly",
                "cycle_days": 30,
                "next_due": "2026-08-18",
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("unambiguous ISO currency code", response.json()["detail"])
        db = self.db()
        self.assertEqual(db.query(Subscription).count(), 0)
        db.close()

    def test_subscription_price_gets_additive_identity_evidence(self):
        subscription = self.client.post(
            "/api/subscriptions",
            json={
                "name": "service",
                "price": 8.75,
                "currency": "CAD",
                "cycle": "monthly",
                "cycle_days": 30,
                "next_due": "2026-08-18",
            },
        ).json()
        self.assertEqual(subscription["original_price_text"], "8.75")
        self.assertEqual(subscription["base_price_text"], "8.75")
        self.assertEqual(subscription["original_currency_code"], "CAD")
        self.assertEqual(subscription["fx_rate_text"], "1")

    def test_foreign_currency_payment_uses_the_subscription_conversion_rate(self):
        subscription = SimpleNamespace(
            currency="CNY",
            original_currency_code="CNY",
            base_currency_code="CAD",
            fx_rate_text="0.19",
            fx_rate_date="2026-07-18",
            fx_source="owner_review:bank",
        )
        payment = SimpleNamespace(amount=10)
        finance_currency.prepare_payment(payment, subscription)
        self.assertEqual(payment.original_amount_text, "10")
        self.assertEqual(payment.base_amount_text, "1.90")
        self.assertEqual(payment.base_currency_code, "CAD")
        self.assertEqual(payment.fx_rate_text, "0.19")

    def test_manual_transactions_keep_blank_import_identity(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "cash", "kind": "cash", "currency": "CAD", "opening": 0},
        ).json()
        self.client.post(
            "/api/money/transactions",
            json={"account_id": account["id"], "date": "2026-07-18", "amount": 1},
        )
        db = self.db()
        self.assertEqual(db.query(Transaction).one().import_identity, "")
        db.close()
