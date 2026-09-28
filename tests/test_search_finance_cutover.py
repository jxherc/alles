from unittest import mock

from core.database import (
    Account,
    FinanceLedgerState,
    Subscription,
    Task,
    Transaction,
)
from services import actual_finance
from tests._client import ApiTest


class SearchFinanceCutoverTests(ApiTest):
    def _seed_frozen(self):
        db = self.db()
        account = Account(name="old account", opening=0)
        db.add_all([account, Task(title="current local task")])
        db.flush()
        db.add_all(
            [
                Transaction(
                    account_id=account.id,
                    date="2026-09-01",
                    amount=-9,
                    payee="old charge",
                    category="old category",
                ),
                Subscription(
                    name="old plan",
                    price=9,
                    currency="$",
                    cycle="monthly",
                    next_due="2026-10-01",
                    category="old category",
                ),
            ]
        )
        db.commit()
        db.close()

    def _cutover(self):
        db = self.db()
        db.add(
            FinanceLedgerState(
                id="primary",
                mode="actual",
                active_run_id="run-search",
                actual_budget_id="budget-search",
                actual_sync_id="sync-search",
                base_currency_code="CAD",
                legacy_read_only=True,
            )
        )
        db.commit()
        db.close()

    def test_local_results_do_not_wait_for_finance_and_legacy_stays_searchable(self):
        self._seed_frozen()
        local = self.client.get("/api/search", params={"q": "current"})
        self.assertEqual(local.status_code, 200, local.text)
        self.assertEqual([row["title"] for row in local.json()["tasks"]], ["current local task"])
        self.assertEqual(local.json()["money"], [])
        self.assertEqual(local.json()["subs"], [])
        self.assertEqual(local.json()["finance_status"], "pending")

        finance = self.client.get("/api/search/finance", params={"q": "old"})
        self.assertEqual(finance.status_code, 200, finance.text)
        self.assertEqual([row["payee"] for row in finance.json()["money"]], ["old charge"])
        self.assertEqual([row["name"] for row in finance.json()["subs"]], ["old plan"])

    def test_canonical_results_replace_frozen_rows_from_one_bounded_snapshot(self):
        self._seed_frozen()
        self._cutover()
        snapshot = {"transactions": [{"id": "current"}], "schedules": [{"id": "current"}]}
        transaction = {
            "id": "current-charge",
            "date": "2026-09-03",
            "amount": -12.5,
            "payee": "new charge",
            "category": "groceries",
            "notes": "fresh note",
        }
        schedule = {
            "id": "new-plan",
            "name": "new plan",
            "price": 12.5,
            "currency": "CAD",
            "cycle": "monthly",
            "metadata": {"category": "apps"},
        }
        with (
            mock.patch.object(actual_finance, "inspect", return_value=snapshot) as inspect,
            mock.patch.object(
                actual_finance, "transactions", return_value=[transaction]
            ) as transactions,
            mock.patch.object(
                actual_finance, "subscription_schedules", return_value=[schedule]
            ) as schedules,
        ):
            local = self.client.get("/api/search", params={"q": "charge"})
            self.assertEqual(local.status_code, 200, local.text)
            self.assertEqual(local.json()["money"], [])
            self.assertEqual(local.json()["subs"], [])
            self.assertEqual(local.json()["finance_status"], "pending")
            inspect.assert_not_called()

            current = self.client.get("/api/search/finance", params={"q": "new"})
            old = self.client.get("/api/search/finance", params={"q": "old"})

        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual([row["payee"] for row in current.json()["money"]], ["new charge"])
        self.assertEqual([row["name"] for row in current.json()["subs"]], ["new plan"])
        self.assertEqual(old.status_code, 200, old.text)
        self.assertEqual(old.json(), {"money": [], "subs": []})
        self.assertEqual(inspect.call_count, 2)
        self.assertEqual(inspect.call_args.kwargs, {"timeout": 8})
        transactions.assert_called_with(mock.ANY, actual=snapshot)
        schedules.assert_called_with(mock.ANY, actual=snapshot)

    def test_canonical_category_and_notes_match_literally(self):
        self._cutover()
        with (
            mock.patch.object(actual_finance, "inspect", return_value={}),
            mock.patch.object(
                actual_finance,
                "transactions",
                return_value=[
                    {
                        "id": "one",
                        "date": "2026-09-03",
                        "amount": -4,
                        "payee": "market",
                        "category": "node_modules",
                        "notes": "100% saved",
                    },
                    {
                        "id": "two",
                        "date": "2026-09-02",
                        "amount": -2,
                        "payee": "market",
                        "category": "nodeXmodules",
                        "notes": "100 dollars saved",
                    },
                ],
            ),
            mock.patch.object(
                actual_finance,
                "subscription_schedules",
                return_value=[
                    {
                        "id": "sub-one",
                        "name": "ordinary plan",
                        "price": 4,
                        "currency": "CAD",
                        "cycle": "monthly",
                        "metadata": {"category": "node_modules"},
                    }
                ],
            ),
        ):
            result = self.client.get("/api/search/finance", params={"q": "node_modules"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([row["id"] for row in result.json()["money"]], ["one"])
        self.assertEqual([row["id"] for row in result.json()["subs"]], ["sub-one"])

    def test_provider_outage_keeps_local_results_without_frozen_fallback(self):
        self._seed_frozen()
        self._cutover()
        with mock.patch.object(
            actual_finance,
            "inspect",
            side_effect=actual_finance.ActualFinanceUnavailable("offline"),
        ):
            finance = self.client.get("/api/search/finance", params={"q": "old"})
            local = self.client.get("/api/search", params={"q": "current"})
        self.assertEqual(finance.status_code, 503, finance.text)
        self.assertEqual(local.json()["finance_status"], "pending")
        self.assertEqual([row["title"] for row in local.json()["tasks"]], ["current local task"])

    def test_unreadable_authority_cannot_replay_frozen_rows(self):
        self._seed_frozen()
        with mock.patch.object(
            actual_finance,
            "is_canonical",
            side_effect=actual_finance.ActualFinanceError("authority unreadable"),
        ):
            finance = self.client.get("/api/search/finance", params={"q": "old"})
        self.assertEqual(finance.status_code, 503, finance.text)
