"""Owned synthetic currency choices, distinct units and immutable historical evidence."""

import uuid
from unittest.mock import patch

from core.database import (
    Account,
    FinanceCreateReceipt,
    FinanceLedgerState,
    MoneyFxEvidence,
    Transaction,
)
from tests._client import ApiTest


class FinanceCurrencyWorkflowTests(ApiTest):
    def account(self, code, opening=0):
        response = self.client.post(
            "/api/money/accounts",
            json={"name": f"owned {code}", "currency": code, "opening": opening},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def transaction(self, account, amount=-10):
        response = self.client.post(
            "/api/money/transactions",
            json={
                "account_id": account["id"],
                "amount": amount,
                "date": "2026-10-01",
                "payee": "owned",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def proof(self, account_id):
        with self.db() as db:
            account = db.get(Account, account_id)
            opening = {
                column.name: getattr(account, column.name)
                for column in Account.__table__.columns
                if column.name not in {"name", "currency"}
            }
            rows = [
                {column.name: getattr(row, column.name) for column in model.__table__.columns}
                for model in (Transaction, MoneyFxEvidence)
                for row in db.query(model).all()
            ]
            return opening, rows

    def test_mixed_totals_and_account_balances_keep_distinct_units(self):
        cad, usd = self.account("CAD", 100), self.account("USD", 100)
        self.transaction(cad)
        self.transaction(usd)
        summary = self.client.get("/api/money/summary?month=2026-10").json()
        self.assertEqual(summary["currency_status"], "mixed")
        groups = {row["currency"]: row for row in summary["totals_by_currency"]}
        self.assertEqual(set(groups), {"CAD", "USD"})
        for group in groups.values():
            self.assertEqual((group["net_worth"], group["expense"], group["net"]), (90, 10, -10))
        accounts = self.client.get("/api/money/accounts").json()
        for account in accounts:
            self.assertEqual(
                account["balance_by_currency"],
                [{"currency": account["currency_code"], "balance": 90}],
            )

    def test_blank_historical_evidence_is_not_inferred_from_account_and_unknowns_stay_separate(
        self,
    ):
        a, b = self.account("USD", 100), self.account("$", 100)
        self.transaction(a)
        self.transaction(b)
        with self.db() as db:
            db.add(
                Transaction(
                    account_id=a["id"], date="2026-10-01", amount=-7, original_currency_code=""
                )
            )
            db.commit()
        summary = self.client.get("/api/money/summary?month=2026-10").json()
        self.assertEqual(summary["currency_status"], "unknown")
        groups = {
            (row["currency"], row["account_id"]): row for row in summary["totals_by_currency"]
        }
        self.assertEqual(groups[("USD", "")]["net_worth"], 90)
        self.assertEqual(groups[("XXX", a["id"])]["net_worth"], -7)
        self.assertEqual(groups[("XXX", b["id"])]["net_worth"], 90)
        accounts = self.client.get("/api/money/accounts").json()
        own = next(row for row in accounts if row["id"] == a["id"])
        self.assertEqual(
            own["balance_by_currency"],
            [{"currency": "USD", "balance": 90}, {"currency": "XXX", "balance": -7}],
        )

    def test_same_currency_and_metadata_edits_preserve_reviewed_exact_opening_and_transaction_proof(
        self,
    ):
        account = self.account("$", 10)
        reviewed = self.client.post(
            "/api/finance/actual/evidence",
            json={
                "target_kind": "account",
                "target_id": account["id"],
                "original_currency_code": "USD",
                "base_currency_code": "CAD",
                "rate_text": "1.35",
                "rate_date": "2026-10-01",
                "source": "owner_reviewed",
            },
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        transaction = self.transaction(account)
        with self.db() as db:
            db.get(Account, account["id"]).original_opening_text = "10.0000"
            db.commit()
        before = self.proof(account["id"])
        for values in ({"name": "renamed"}, {"currency": "$", "opening": 10}, {"currency": "USD"}):
            response = self.client.patch(f"/api/money/accounts/{account['id']}", json=values)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.proof(account["id"]), before)
        response = self.client.patch(
            f"/api/money/transactions/{transaction['id']}",
            json={"amount": -10, "account_id": account["id"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.proof(account["id"]), before)
        denied = self.client.patch(f"/api/money/accounts/{account['id']}", json={"currency": "EUR"})
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(self.proof(account["id"]), before)

    def test_empty_account_can_change_currency_without_rewriting_zero_text(self):
        account = self.account("CAD")
        with self.db() as db:
            db.get(Account, account["id"]).original_opening_text = "0.0000"
            db.commit()
        response = self.client.patch(
            f"/api/money/accounts/{account['id']}", json={"currency": "SGD"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["original_opening_text"], "0.0000")
        self.assertEqual(response.json()["base_opening_text"], "0.0000")
        self.assertEqual(self.transaction(account)["original_currency_code"], "SGD")
        denied = self.client.patch(f"/api/money/accounts/{account['id']}", json={"currency": "USD"})
        self.assertEqual(denied.status_code, 409, denied.text)

    def test_saved_future_and_paused_schedules_prevent_currency_reinterpretation(self):
        for active in (True, False):
            with self.subTest(active=active):
                account = self.account("CAD")
                scheduled = self.client.post(
                    "/api/money/recurring",
                    json={
                        "account_id": account["id"],
                        "amount": -10,
                        "payee": "owned future CAD bill",
                        "next_date": "2099-10-01",
                        "cycle": "monthly",
                        "active": active,
                    },
                )
                self.assertEqual(scheduled.status_code, 200, scheduled.text)
                before = self.client.get("/api/money/recurring").json()
                proof = self.proof(account["id"])
                listed = next(
                    row
                    for row in self.client.get("/api/money/accounts").json()
                    if row["id"] == account["id"]
                )
                self.assertTrue(listed["currency_edit_reason"])
                denied = self.client.patch(
                    f"/api/money/accounts/{account['id']}", json={"currency": "USD"}
                )
                self.assertEqual(denied.status_code, 409, denied.text)
                self.assertEqual(self.client.get("/api/money/recurring").json(), before)
                self.assertEqual(self.proof(account["id"]), proof)

    def test_linked_subscription_and_alert_threshold_keep_their_saved_currency(self):
        account = self.account("CAD")
        subscribed = self.client.post(
            "/api/subscriptions",
            json={
                "account_id": account["id"],
                "name": "owned future subscription",
                "currency": "CAD",
                "price": 10,
                "next_due": "2099-10-01",
                "active": False,
            },
        )
        self.assertEqual(subscribed.status_code, 200, subscribed.text)
        before = self.client.get("/api/subscriptions?advance=false").json()
        denied = self.client.patch(f"/api/money/accounts/{account['id']}", json={"currency": "USD"})
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(self.client.get("/api/subscriptions?advance=false").json(), before)
        alert_account = self.account("CAD")
        saved = self.client.patch(
            f"/api/money/accounts/{alert_account['id']}", json={"low_balance": 10}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        proof = self.proof(alert_account["id"])
        denied = self.client.patch(
            f"/api/money/accounts/{alert_account['id']}", json={"currency": "USD"}
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(self.proof(alert_account["id"]), proof)

    def test_cross_currency_transfer_is_refused_without_receipt_or_transactions(self):
        a, b = self.account("CAD", 10), self.account("USD", 10)
        before = self.proof(a["id"])
        response = self.client.post(
            "/api/money/transfer",
            json={
                "from_account": a["id"],
                "to_account": b["id"],
                "amount": 5,
                "date": "2026-10-01",
                "request_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.proof(a["id"]), before)
        self.assertEqual(self.client.get("/api/money/transactions").json(), [])

    def test_two_unknown_account_units_do_not_establish_a_transfer_rate(self):
        a, b = self.account("$", 10), self.account("$", 10)
        before = self.proof(a["id"])
        response = self.client.post(
            "/api/money/transfer",
            json={
                "from_account": a["id"],
                "to_account": b["id"],
                "amount": 5,
                "date": "2026-10-01",
                "request_id": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.proof(a["id"]), before)
        self.assertEqual(self.client.get("/api/money/transactions").json(), [])
        with self.db() as db:
            self.assertEqual(db.query(FinanceCreateReceipt).count(), 0)

    def test_currency_specific_create_retries_do_not_change_later_account_or_recreate_deleted_one(
        self,
    ):
        values = {"name": "owned retry", "currency": "USD", "request_id": str(uuid.uuid4())}
        first = self.client.post("/api/money/accounts", json=values).json()
        self.client.patch(f"/api/money/accounts/{first['id']}", json={"name": "renamed"})
        self.assertEqual(self.client.post("/api/money/accounts", json=values).json(), first)
        conflict = self.client.post("/api/money/accounts", json=values | {"currency": "CAD"})
        self.assertEqual(conflict.status_code, 409)
        rows = self.client.get("/api/money/accounts").json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "renamed")
        self.client.delete(f"/api/money/accounts/{first['id']}")
        self.assertEqual(self.client.post("/api/money/accounts", json=values).status_code, 410)

    def test_native_converter_does_not_silently_treat_sgd_or_unknown_as_usd(self):
        self.account("SGD", 10)
        same = self.client.get("/api/money/networth-base?base=SGD")
        self.assertEqual(same.status_code, 200, same.text)
        self.assertEqual((same.json()["base"], same.json()["net_worth"]), ("SGD", 10))
        self.assertEqual(self.client.get("/api/money/networth-base?base=USD").status_code, 409)
        self.assertEqual(self.client.get("/api/money/networth-base?base=$").status_code, 400)

    def test_canonical_sgd_labels_choices_and_base_guard_use_reviewed_currency(self):
        with self.db() as db:
            db.add(
                FinanceLedgerState(
                    id="primary",
                    mode="actual",
                    base_currency_code="SGD",
                    legacy_read_only=True,
                    active_run_id="owned",
                )
            )
            db.commit()
        canonical = [{"id": "owned", "name": "owned", "balance": 12.5, "archived": False}]
        with (
            patch("routes.money.actual_finance.inspect", return_value={}),
            patch("routes.money.actual_finance.accounts", return_value=canonical),
            patch("routes.money.actual_finance.transactions", return_value=[]),
            patch("routes.money.actual_finance.budgets", return_value=[]),
        ):
            summary = self.client.get("/api/money/summary?month=2026-10")
            self.assertEqual(summary.status_code, 200, summary.text)
            self.assertEqual(summary.json()["currency"], "SGD")
            self.assertEqual(self.client.get("/api/money/networth-base").json()["base"], "SGD")
            self.assertEqual(self.client.get("/api/money/networth-base?base=USD").status_code, 409)
            self.assertEqual(self.client.get("/api/money/currencies").json(), {"codes": ["SGD"]})
