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
    def setUp(self):
        super().setUp()
        from core.settings import save_settings

        self.addCleanup(save_settings, {"money_base_currency": "", "money_fx_rates": {}})

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
        budget = self.client.post(
            "/api/money/budgets", json={"category": "uncategorized", "limit_amt": 50}
        )
        summary = self.client.get("/api/money/summary?month=2026-10").json()
        groups = {row["currency"]: row for row in summary["totals_by_currency"]}
        self.assertEqual(set(groups), {"CAD", "USD"})
        for group in groups.values():
            self.assertEqual((group["net_worth"], group["expense"], group["net"]), (90, 10, -10))
        # totals stay in the base currency: USD has no rate yet, so it's out and said so
        self.assertEqual((summary["currency"], summary["currency_status"]), ("CAD", "partial"))
        self.assertEqual((summary["net_worth"], summary["expense"]), (90, 10))
        self.assertEqual(
            summary["excluded"],
            [
                {
                    "currency": "USD",
                    "accounts": 1,
                    "transactions": 1,
                    "net_worth": 90,
                    "income": 0,
                    "expense": 10,
                }
            ],
        )
        # a foreign account no longer turns budgets off: its spending waits for a rate
        self.assertEqual(budget.status_code, 200, budget.text)
        self.assertEqual(
            [(b["category"], b["spent"]) for b in summary["budgets"]], [("uncategorized", 10)]
        )
        self.client.patch(
            "/api/money/totals-currency", json={"rate": {"from": "USD", "to": "CAD", "rate": "1.5"}}
        )
        summary = self.client.get("/api/money/summary?month=2026-10").json()
        self.assertEqual(summary["currency_status"], "converted")
        self.assertEqual((summary["net_worth"], summary["expense"]), (225, 25))
        self.assertEqual(summary["by_category"], [["uncategorized", 25]])
        self.assertEqual([b["spent"] for b in summary["budgets"]], [25])
        self.assertEqual(summary["excluded"], [])
        self.assertEqual([row["rate"] for row in summary["rates"]], ["1.5"])
        accounts = self.client.get("/api/money/accounts").json()
        for account in accounts:
            self.assertEqual(
                account["balance_by_currency"],
                [{"currency": account["currency_code"], "balance": 90}],
            )

    def test_forecast_history_envelope_age_alerts_and_report_share_the_base_rule(self):
        cad, usd = self.account("CAD", 100), self.account("USD", 100)
        for account, amount in ((cad, 500), (cad, -300), (usd, 400), (usd, -250)):
            self.transaction(account, amount)
        self.client.post("/api/money/watches", json={"kind": "payee", "value": "owned"})

        def read():
            return {
                "forecast": self.client.get(
                    "/api/money/forecast?month=2026-10&as_of=2026-10-31"
                ).json(),
                "history": self.client.get(
                    "/api/money/networth-history?months=1&as_of=2026-10-31"
                ).json(),
                "envelope": self.client.get("/api/money/envelope?month=2026-10").json(),
                "age": self.client.get("/api/money/age-of-money").json(),
                "alerts": self.client.get(
                    "/api/money/alerts?month=2026-10&big=200&as_of=2026-10-31"
                ).json(),
                "report": self.client.get(
                    "/api/money/report?start=2026-10-01&end=2026-10-31"
                ).json(),
            }

        before = read()
        # USD has no rate: none of these mix it in as if it were CAD
        self.assertEqual(before["forecast"]["start_balance"], 300)
        self.assertEqual(before["forecast"]["excluded"][0]["currency"], "USD")
        self.assertEqual(before["history"], [{"month": "2026-10", "net_worth": 300}])
        self.assertEqual(
            (before["envelope"]["income"], before["envelope"]["currency"]), (500, "CAD")
        )
        self.assertEqual((before["report"]["income"], before["report"]["expense"]), (500, 300))
        self.assertEqual(before["age"]["sample"], 1)
        # `big` is in the totals currency: an amount with no rate can't be judged against it
        large = {row["amount"]: row.get("currency") for row in before["alerts"]["large_purchases"]}
        self.assertEqual(large, {-300: None})

        self.client.patch(
            "/api/money/totals-currency", json={"rate": {"from": "USD", "to": "CAD", "rate": "2"}}
        )
        after = read()
        self.assertEqual(after["forecast"]["start_balance"], 800)
        self.assertTrue(after["forecast"]["complete"])
        self.assertEqual(after["history"], [{"month": "2026-10", "net_worth": 800}])
        self.assertEqual(after["envelope"]["income"], 1300)
        self.assertEqual((after["report"]["income"], after["report"]["expense"]), (1300, 800))
        self.assertGreater(after["age"]["sample"], before["age"]["sample"])
        large = {row["amount"]: row.get("currency") for row in after["alerts"]["large_purchases"]}
        self.assertEqual(large, {-300: None, -500: None})

    def reviewed_renewal(self):
        """a USD 10 subscription renews into a CAD account at a reviewed 1.5: the posted row is
        CAD -15, while its original_* keep the USD -10 price"""
        from datetime import date, timedelta

        from core.database import Subscription

        cad = self.account("CAD", 100)
        created = self.client.post(
            "/api/subscriptions",
            json={
                "name": "owned us renewal",
                "price": 10,
                "currency": "USD",
                "account_id": cad["id"],
                "next_due": (date.today() - timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        with self.db() as db:
            sub = db.get(Subscription, created.json()["id"])
            sub.base_price_text, sub.base_currency_code = "15.00", "CAD"
            sub.fx_rate_text, sub.fx_rate_date, sub.fx_source = (
                "1.5",
                "2026-10-01",
                "owner_reviewed",
            )
            db.commit()
        self.assertEqual(self.client.get("/api/subscriptions").status_code, 200)
        posted = [
            t
            for t in self.client.get("/api/money/transactions").json()
            if t["payee"] == "owned us renewal"
        ]
        self.assertEqual(len(posted), 1)
        return cad, posted[0]

    def test_a_reviewed_renewal_counts_once_in_either_totals_currency(self):
        cad, row = self.reviewed_renewal()
        self.assertEqual((row["amount"], row["original_amount_text"]), (-15, "-10.0"))
        # the row's amount is in CAD, whatever its source price was in
        self.assertEqual(row["amount_currency_code"], "CAD")
        month = row["date"][:7]
        summary = self.client.get(f"/api/money/summary?month={month}").json()
        self.assertEqual((summary["expense"], summary["net_worth"]), (15, 85))
        self.assertEqual([g["currency"] for g in summary["totals_by_currency"]], ["CAD"])
        listed = next(
            a for a in self.client.get("/api/money/accounts").json() if a["id"] == cad["id"]
        )
        self.assertEqual(listed["balance_by_currency"], [{"currency": "CAD", "balance": 85}])
        # in USD totals the reviewed source price counts exactly: USD 10, not USD 15
        self.client.patch("/api/money/totals-currency", json={"base": "USD"})
        self.client.patch(
            "/api/money/totals-currency",
            json={"rate": {"from": "USD", "to": "CAD", "rate": "1.25"}},
        )
        summary = self.client.get(f"/api/money/summary?month={month}").json()
        self.assertEqual((summary["currency"], summary["expense"]), ("USD", 10))
        self.assertEqual(summary["net_worth"], 70)  # 100 / 1.25 - 10

    def test_report_names_what_it_left_out_and_its_csv_names_each_currency(self):
        cad, usd = self.account("CAD", 0), self.account("USD", 0)
        self.transaction(cad, -30)
        self.transaction(usd, -20)
        self.transaction(usd, 50)
        report = self.client.get("/api/money/report?start=2026-10-01&end=2026-10-31").json()
        self.assertEqual((report["currency"], report["expense"], report["income"]), ("CAD", 30, 0))
        self.assertEqual(
            [(r["currency"], r["expense"], r["income"]) for r in report["excluded"]],
            [("USD", 20, 50)],
        )
        outside = self.client.get("/api/money/report?start=2026-11-01&end=2026-11-30").json()
        self.assertEqual([(r["expense"], r["income"]) for r in outside["excluded"]], [(0, 0)])
        csv = self.client.get("/api/money/report/export.csv?start=2026-10-01&end=2026-10-31").text
        lines = csv.strip().splitlines()
        self.assertEqual(lines[0], "date,amount,currency,category,payee,notes")
        self.assertEqual(sorted(line.split(",")[2] for line in lines[1:]), ["CAD", "USD", "USD"])

    def test_caps_envelope_and_goals_are_saved_in_the_ledger_currency_and_shown_converted(self):
        cad = self.account("CAD", 0)
        self.client.post(
            "/api/money/transactions",
            json={"account_id": cad["id"], "amount": -40, "date": "2026-10-02", "category": "food"},
        )
        self.client.post(
            "/api/money/transactions",
            json={"account_id": cad["id"], "amount": 500, "date": "2026-10-01", "category": "pay"},
        )
        self.client.post("/api/money/budgets", json={"category": "food", "limit_amt": 100})
        self.client.put(
            "/api/money/envelope/assign",
            json={"month": "2026-10", "category": "food", "amount": 200},
        )
        self.client.post("/api/money/goals", json={"name": "trip", "target": 1000, "current": 250})
        # totals in USD with no CAD rate: saved amounts stay in CAD, said so
        self.client.patch("/api/money/totals-currency", json={"base": "USD"})
        summary = self.client.get("/api/money/summary?month=2026-10").json()
        self.assertEqual(summary["budgets_currency"], "CAD")
        self.assertEqual([(b["limit"], b["spent"]) for b in summary["budgets"]], [(100, 40)])
        envelope = self.client.get("/api/money/envelope?month=2026-10").json()
        self.assertEqual((envelope["currency"], envelope["income"]), ("CAD", 500))
        goals = self.client.get("/api/money/goals").json()
        self.assertEqual((goals["currency"], goals["goals"][0]["target"]), ("CAD", 1000))
        # with a rate they're shown in USD; the editor still gets the saved number
        self.client.patch(
            "/api/money/totals-currency",
            json={"rate": {"from": "USD", "to": "CAD", "rate": "1.25"}},
        )
        summary = self.client.get("/api/money/summary?month=2026-10").json()
        self.assertEqual(summary["budgets_currency"], "USD")
        self.assertEqual([(b["limit"], b["spent"]) for b in summary["budgets"]], [(80, 32)])
        envelope = self.client.get("/api/money/envelope?month=2026-10").json()
        food = next(c for c in envelope["categories"] if c["category"] == "food")
        self.assertEqual((envelope["currency"], envelope["income"]), ("USD", 400))
        self.assertEqual((food["assigned"], food["assigned_saved"], food["spent"]), (160, 200, 32))
        goals = self.client.get("/api/money/goals").json()
        self.assertEqual((goals["currency"], goals["goals"][0]["target"]), ("USD", 800))
        self.assertEqual(goals["goals"][0]["progress"], 0.25)

    def test_envelope_names_income_it_left_out(self):
        cad, eur = self.account("CAD", 0), self.account("EUR", 0)
        self.transaction(cad, 300)
        self.transaction(eur, 1000)
        envelope = self.client.get("/api/money/envelope?month=2026-10").json()
        self.assertEqual(envelope["income"], 300)
        self.assertEqual(
            [(r["currency"], r["income"]) for r in envelope["excluded"]], [("EUR", 1000)]
        )
        self.assertEqual(envelope["excluded_currency"], "CAD")

    def test_new_subscription_without_a_currency_is_in_the_ledger_currency(self):
        self.client.patch("/api/money/totals-currency", json={"base": "USD"})
        created = self.client.post(
            "/api/subscriptions",
            json={"name": "owned default", "price": 5, "next_due": "2099-01-01"},
        ).json()
        self.assertEqual(created["original_currency_code"], "CAD")
        summary = self.client.get("/api/subscriptions?advance=false").json()["summary"]
        self.assertEqual((summary["currency"], summary["ledger_currency"]), ("USD", "CAD"))

    def test_rates_take_plain_decimals_and_numbers_only(self):
        for value in ("1_000", "1e3", "-1", "1,085", " ", True, {"x": 1}):
            response = self.client.patch(
                "/api/money/totals-currency",
                json={"rate": {"from": "USD", "to": "CAD", "rate": value}},
            )
            self.assertEqual(response.status_code, 400, (value, response.text))
            self.assertIsInstance(response.json()["detail"], str)
        for body in ([1], {"base": 5}, {"rate": "USD"}, {"rate": {"from": "USD", "to": 3}}):
            response = self.client.patch("/api/money/totals-currency", json=body)
            self.assertEqual(response.status_code, 400 if isinstance(body, dict) else 422, body)
        saved = self.client.patch(
            "/api/money/totals-currency", json={"rate": {"from": "USD", "to": "CAD", "rate": 1.37}}
        ).json()
        self.assertEqual(saved["rates"][0]["rate"], "1.37")

    def test_an_unknown_currency_account_can_be_told_its_currency(self):
        legacy = self.account("$", 100)
        self.account("CAD", 50)
        self.transaction(legacy, -40)
        listed = next(
            a for a in self.client.get("/api/money/accounts").json() if a["id"] == legacy["id"]
        )
        self.assertEqual(listed["currency_edit_reason"], "")
        summary = self.client.get("/api/money/summary?month=2026-10").json()
        self.assertEqual(
            [(r["currency"], r["net_worth"]) for r in summary["excluded"]], [("XXX", 60)]
        )
        named = self.client.patch(f"/api/money/accounts/{legacy['id']}", json={"currency": "CAD"})
        self.assertEqual(named.status_code, 200, named.text)
        rows = self.client.get("/api/money/transactions").json()
        self.assertEqual({t["original_currency_code"] for t in rows}, {"CAD"})
        summary = self.client.get("/api/money/summary?month=2026-10").json()
        self.assertEqual((summary["net_worth"], summary["excluded"]), (110, []))
        # a known currency still can't be swapped under saved amounts
        denied = self.client.patch(f"/api/money/accounts/{legacy['id']}", json={"currency": "USD"})
        self.assertEqual(denied.status_code, 409, denied.text)

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
        self.assertEqual(summary["currency_status"], "partial")
        groups = {
            (row["currency"], row["account_id"]): row for row in summary["totals_by_currency"]
        }
        self.assertEqual(groups[("USD", "")]["net_worth"], 90)
        self.assertEqual(groups[("XXX", a["id"])]["net_worth"], -7)
        self.assertEqual(groups[("XXX", b["id"])]["net_worth"], 90)
        self.client.patch("/api/money/totals-currency", json={"base": "USD"})
        summary = self.client.get("/api/money/summary?month=2026-10").json()
        # an amount with no currency can't take a rate: it stays out under its own label
        self.assertEqual((summary["currency"], summary["net_worth"]), ("USD", 90))
        unknown = summary["excluded"]
        self.assertEqual([row["currency"] for row in unknown], ["XXX"])
        self.assertEqual((unknown[0]["accounts"], unknown[0]["net_worth"]), (2, 83))
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
        other = self.client.get("/api/money/networth-base?base=USD")
        self.assertEqual(other.status_code, 200, other.text)
        self.assertEqual((other.json()["net_worth"], other.json()["accounts"]), (0, []))
        self.assertEqual(other.json()["excluded"][0]["currency"], "SGD")
        self.assertEqual(self.client.get("/api/money/networth-base?base=$").status_code, 400)

    def test_totals_currency_rejects_bad_input_and_stays_fixed_after_cutover(self):
        for body in (
            {},
            {"base": "$"},
            {"rate": {"from": "USD", "to": "USD", "rate": "1"}},
            {"rate": {"from": "USD", "to": "CAD", "rate": "0"}},
            {"rate": {"from": "USD", "to": "CAD", "rate": "1.2.3"}},
        ):
            response = self.client.patch("/api/money/totals-currency", json=body)
            self.assertEqual(response.status_code, 400, (body, response.text))
        saved = self.client.patch(
            "/api/money/totals-currency",
            json={"rate": {"from": "usd", "to": "cad", "rate": "1.37"}},
        ).json()
        self.assertEqual(
            [(r["from"], r["to"], r["rate"]) for r in saved["rates"]], [("USD", "CAD", "1.37")]
        )
        # entering the pair the other way replaces it rather than keeping two that disagree
        saved = self.client.patch(
            "/api/money/totals-currency",
            json={"rate": {"from": "CAD", "to": "USD", "rate": "0.73"}},
        ).json()
        self.assertEqual([(r["from"], r["to"]) for r in saved["rates"]], [("CAD", "USD")])
        saved = self.client.patch(
            "/api/money/totals-currency", json={"rate": {"from": "CAD", "to": "USD", "rate": ""}}
        ).json()
        self.assertEqual(saved["rates"], [])
        with self.db() as db:
            db.add(
                FinanceLedgerState(
                    id="primary", mode="actual", base_currency_code="SGD", legacy_read_only=True
                )
            )
            db.commit()
        fixed = self.client.patch("/api/money/totals-currency", json={"base": "USD"})
        self.assertEqual(fixed.status_code, 409, fixed.text)

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
