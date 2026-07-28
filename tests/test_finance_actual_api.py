from decimal import Decimal
from unittest import mock

from core.database import (
    Account,
    FinanceLedgerState,
    MoneyFxEvidence,
    SubPayment,
    Subscription,
    Transaction,
)
from services import actual_migration
from tests._client import ApiTest


class FinanceActualApiTests(ApiTest):
    def test_stage_holds_the_finance_authority_lock_through_publication(self):
        class TrackingLock:
            held = False

            def __enter__(self):
                self.held = True

            def __exit__(self, *_args):
                self.held = False

        lock = TrackingLock()

        def stage(_db, *, base_currency_code):
            self.assertTrue(lock.held)
            self.assertEqual(base_currency_code, "CAD")
            return {"status": "ready"}

        with (
            mock.patch("services.actual_finance.AUTHORITY_LOCK", lock),
            mock.patch("routes.finance_actual.actual_migration.stage", side_effect=stage),
        ):
            response = self.client.post(
                "/api/finance/actual/stage",
                json={"base_currency_code": "CAD"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"status": "ready"})

    def test_service_lifecycle_action_holds_the_finance_authority_lock(self):
        class TrackingLock:
            held = False

            def __enter__(self):
                self.held = True

            def __exit__(self, *_args):
                self.held = False

        lock = TrackingLock()

        def control(action):
            self.assertTrue(lock.held)
            self.assertEqual(action, "stop")
            return {"ok": True, "action": action}

        with (
            mock.patch("services.actual_finance.AUTHORITY_LOCK", lock),
            mock.patch("routes.finance_actual.managed_actual.control", side_effect=control),
        ):
            response = self.client.post("/api/finance/actual/service/stop")
        self.assertEqual(response.status_code, 200, response.text)

    def test_status_starts_with_alles_authority_and_loopback_service_boundary(self):
        response = self.client.get("/api/finance/actual")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["ledger"]["mode"], "alles")
        self.assertFalse(payload["ledger"]["legacy_read_only"])
        self.assertEqual(payload["service"]["bind"].split(":")[0], "127.0.0.1")
        self.assertEqual(payload["service"]["version"], "26.7.0")

    def test_owner_reviewed_rate_converts_exactly_with_recorded_rounding_evidence(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "CMB debit", "kind": "checking", "currency": "CNY", "opening": 100},
        ).json()
        transaction = self.client.post(
            "/api/money/transactions",
            json={
                "account_id": account["id"],
                "date": "2026-07-18",
                "amount": -4,
                "payee": "metro",
            },
        ).json()
        opening = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "account",
                "target_id": account["id"],
                "base_currency_code": "CAD",
                "rate_text": "0.19",
                "rate_date": "2026-07-18",
                "source": "owner_reviewed",
            },
        )
        self.assertEqual(opening.status_code, 200, opening.text)
        self.assertEqual(opening.json()["base_amount_text"], "19.00")
        converted = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "transaction",
                "target_id": transaction["id"],
                "base_currency_code": "CAD",
                "rate_text": "0.19",
                "rate_date": "2026-07-18",
                "source": "statement_rate",
            },
        )
        self.assertEqual(converted.status_code, 200, converted.text)
        self.assertEqual(converted.json()["base_amount_text"], "-0.76")
        db = self.db()
        row = db.get(Transaction, transaction["id"])
        proof = db.query(MoneyFxEvidence).filter_by(transaction_id=row.id).one()
        self.assertEqual(Decimal(row.base_amount_text), Decimal("-0.76"))
        self.assertEqual(row.fx_rate_text, "0.19")
        self.assertEqual(row.fx_rate_date, "2026-07-18")
        self.assertEqual(row.fx_source, "statement_rate:half_even_2dp")
        self.assertEqual(proof.rate_text, "0.19")
        self.assertEqual(proof.rate_date, "2026-07-18")
        self.assertEqual(proof.source, "statement_rate:half_even_2dp")
        self.assertEqual(db.get(FinanceLedgerState, "primary").base_currency_code, "CAD")
        db.close()

    def test_owner_review_can_rebuild_missing_foreign_transaction_evidence(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "legacy travel", "kind": "cash", "currency": "EUR", "opening": 0},
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
        db = self.db()
        db.query(MoneyFxEvidence).filter_by(transaction_id=transaction["id"]).delete()
        db.commit()
        db.close()

        reviewed = self.client.post(
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

        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["base_amount_text"], "-3.00")
        db = self.db()
        evidence = db.query(MoneyFxEvidence).filter_by(transaction_id=transaction["id"]).one()
        row = db.get(Transaction, transaction["id"])
        self.assertEqual(row.original_amount_text, "-2.0")
        self.assertEqual(evidence.original_amount_text, "-2.0")
        self.assertEqual(evidence.original_currency_code, "EUR")
        self.assertEqual(evidence.base_amount_text, "-3.00")
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        self.assertEqual(snapshot["transactions"][0]["evidence"]["original_amount_text"], "-2.0")
        db.close()

    def test_evidence_write_holds_the_actual_authority_lock(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "CNY locked", "kind": "cash", "currency": "CNY", "opening": 1},
        ).json()

        class TrackingLock:
            held = False

            def __enter__(self):
                self.held = True

            def __exit__(self, *_args):
                self.held = False

        lock = TrackingLock()

        def checked_rate(value):
            self.assertTrue(lock.held)
            return Decimal(value)

        with (
            mock.patch("services.actual_finance.AUTHORITY_LOCK", lock),
            mock.patch("routes.finance_actual._rate", side_effect=checked_rate),
        ):
            response = self.client.post(
                "/api/finance/actual/evidence",
                json={
                    "target_kind": "account",
                    "target_id": account["id"],
                    "base_currency_code": "CAD",
                    "rate_text": "0.19",
                    "rate_date": "2026-07-18",
                    "source": "owner_reviewed",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)

    def test_row_evidence_cannot_change_the_ledger_wide_base_currency(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "CNY", "kind": "cash", "currency": "CNY", "opening": 1},
        ).json()
        db = self.db()
        db.add(FinanceLedgerState(id="primary", mode="alles", base_currency_code="CAD"))
        db.commit()
        db.close()
        response = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "account",
                "target_id": account["id"],
                "base_currency_code": "USD",
                "rate_text": "0.14",
                "rate_date": "2026-07-18",
                "source": "owner_reviewed",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("configured ledger base CAD", response.text)
        db = self.db()
        self.assertEqual(db.get(FinanceLedgerState, "primary").base_currency_code, "CAD")
        self.assertEqual(db.get(Account, account["id"]).base_currency_code, "CNY")
        db.close()

    def test_rate_precision_and_exponent_are_bounded_before_quantization(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "CNY", "kind": "cash", "currency": "CNY", "opening": 1},
        ).json()
        for rate in ("1e999999", "0." + ("1" * 29)):
            with self.subTest(rate=rate):
                response = self.client.post(
                    "/api/finance/actual/evidence",
                    json={
                        "target_kind": "account",
                        "target_id": account["id"],
                        "base_currency_code": "CAD",
                        "rate_text": rate,
                        "rate_date": "2026-07-18",
                        "source": "owner_reviewed",
                    },
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn("rate", response.text)

    def test_nonfinite_stored_original_amount_is_rejected(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "poisoned", "kind": "cash", "currency": "CNY", "opening": 1},
        ).json()
        db = self.db()
        db.get(Account, account["id"]).original_opening_text = "NaN"
        db.commit()
        db.close()
        response = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "account",
                "target_id": account["id"],
                "base_currency_code": "CAD",
                "rate_text": "0.19",
                "rate_date": "2026-07-18",
                "source": "owner_reviewed",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "invalid_original_amount")

    def test_same_currency_rejects_non_identity_rate(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "CAD", "kind": "cash", "currency": "CAD", "opening": 1},
        ).json()
        response = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "account",
                "target_id": account["id"],
                "base_currency_code": "CAD",
                "rate_text": "1.1",
                "rate_date": "2026-07-18",
                "source": "owner_reviewed",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_non_identity_evidence_requires_a_valid_rate_date(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "CNY", "kind": "cash", "currency": "CNY", "opening": 1},
        ).json()
        for rate_date in ("", "not-a-date"):
            with self.subTest(rate_date=rate_date):
                response = self.client.post(
                    "/api/finance/actual/evidence",
                    json={
                        "target_kind": "account",
                        "target_id": account["id"],
                        "base_currency_code": "CAD",
                        "rate_text": "0.19",
                        "rate_date": rate_date,
                        "source": "owner_reviewed",
                    },
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn("YYYY-MM-DD", response.text)

    def test_unknown_original_currencies_require_explicit_owner_resolution(self):
        account = self.client.post(
            "/api/money/accounts",
            json={"name": "unknown cash", "kind": "cash", "currency": "$", "opening": 1},
        ).json()
        transaction = self.client.post(
            "/api/money/transactions",
            json={"account_id": account["id"], "date": "2026-07-19", "amount": -2},
        ).json()
        subscription = self.client.post(
            "/api/subscriptions",
            json={
                "name": "unknown subscription",
                "price": 3,
                "currency": "CAD",
                "next_due": "2026-08-01",
            },
        ).json()
        db = self.db()
        legacy_subscription = db.get(Subscription, subscription["id"])
        legacy_subscription.currency = "$"
        legacy_subscription.original_currency_code = "XXX"
        legacy_subscription.base_currency_code = ""
        legacy_subscription.base_price_text = ""
        legacy_subscription.fx_rate_text = ""
        legacy_subscription.fx_source = ""
        payment = SubPayment(
            sub_id=subscription["id"],
            date="2026-07-01",
            amount=3,
            original_amount_text="3",
            original_currency_code="XXX",
        )
        db.add(payment)
        db.commit()
        payment_id = payment.id
        db.close()
        targets = (
            ("account", account["id"]),
            ("transaction", transaction["id"]),
            ("subscription", subscription["id"]),
            ("subscription_payment", payment_id),
        )
        for target_kind, target_id in targets:
            with self.subTest(target_kind=target_kind):
                payload = {
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "base_currency_code": "CAD",
                    "rate_text": "1",
                    "rate_date": "",
                    "source": "owner_reviewed",
                }
                blocked = self.client.post("/api/finance/actual/evidence", json=payload)
                self.assertEqual(blocked.status_code, 409, blocked.text)
                self.assertEqual(blocked.json()["code"], f"{target_kind}_currency_unknown")
                reviewed = self.client.post(
                    "/api/finance/actual/evidence",
                    json={**payload, "original_currency_code": "CAD"},
                )
                self.assertEqual(reviewed.status_code, 200, reviewed.text)
                self.assertEqual(reviewed.json()["original_currency_code"], "CAD")
        db = self.db()
        self.assertEqual(db.get(Account, account["id"]).currency_code, "CAD")
        self.assertEqual(db.get(Transaction, transaction["id"]).original_currency_code, "CAD")
        self.assertEqual(
            db.query(MoneyFxEvidence)
            .filter_by(transaction_id=transaction["id"])
            .one()
            .original_currency_code,
            "CAD",
        )
        self.assertEqual(db.get(Subscription, subscription["id"]).original_currency_code, "CAD")
        self.assertEqual(db.get(SubPayment, payment_id).original_currency_code, "CAD")
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        self.assertEqual(len(snapshot["accounts"]), 1)
        self.assertEqual(len(snapshot["transactions"]), 1)
        self.assertEqual(len(snapshot["schedules"]), 1)
        db.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
