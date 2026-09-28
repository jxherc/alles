import json
from unittest import mock

from core.database import Account, FinanceLedgerState, Task, Transaction
from services import actual_finance
from tests._client import ApiTest


class ExportFinanceCutoverTests(ApiTest):
    def _seed_frozen(self):
        db = self.db()
        account = Account(name="old bank", opening=0)
        db.add_all([account, Task(title="current task")])
        db.flush()
        db.add(
            Transaction(
                account_id=account.id,
                date="2026-09-01",
                amount=-9,
                payee="old charge",
                category="groceries",
                notes="old receipt",
            )
        )
        db.commit()
        db.close()

    def _cutover(self):
        db = self.db()
        db.add(
            FinanceLedgerState(
                id="primary",
                mode="actual",
                active_run_id="run-export",
                actual_budget_id="budget-export",
                actual_sync_id="sync-export",
                base_currency_code="CAD",
                legacy_read_only=True,
            )
        )
        db.commit()
        db.close()

    def test_legacy_transaction_export_keeps_its_columns(self):
        self._seed_frozen()
        response = self.client.get("/api/export/transactions", params={"format": "json"})
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        self.assertEqual([row["payee"] for row in rows], ["old charge"])
        self.assertEqual(
            set(rows[0]), {"id", "date", "amount", "payee", "category", "tags", "notes"}
        )

    def test_canonical_transaction_exports_replace_frozen_rows(self):
        self._seed_frozen()
        self._cutover()
        snapshot = {"transactions": [{"id": "current"}]}
        row = {
            "id": "current-charge",
            "date": "2026-09-03",
            "amount": -12.5,
            "payee": "new charge",
            "category": "food",
            "tags": "shopping",
            "notes": "fresh receipt",
        }
        with (
            mock.patch.object(actual_finance, "inspect", return_value=snapshot) as inspect,
            mock.patch.object(actual_finance, "transactions", return_value=[row]) as transactions,
        ):
            json_response = self.client.get("/api/export/transactions", params={"format": "json"})
            csv_response = self.client.get("/api/export/transactions", params={"format": "csv"})

        self.assertEqual(json_response.status_code, 200, json_response.text)
        self.assertEqual([item["payee"] for item in json_response.json()], ["new charge"])
        self.assertEqual(
            set(json_response.json()[0]),
            {"id", "date", "amount", "payee", "category", "tags", "notes"},
        )
        self.assertEqual(csv_response.status_code, 200, csv_response.text)
        self.assertIn("new charge", csv_response.text)
        self.assertNotIn("old charge", csv_response.text)
        self.assertIn(
            'filename="alles-transactions.csv"', csv_response.headers["content-disposition"]
        )
        self.assertEqual(inspect.call_count, 2)
        transactions.assert_called_with(mock.ANY, actual=snapshot)

    def test_outage_never_serves_frozen_export_or_blocks_other_kinds(self):
        self._seed_frozen()
        self._cutover()
        with mock.patch.object(
            actual_finance,
            "inspect",
            side_effect=actual_finance.ActualFinanceUnavailable("offline"),
        ):
            transaction = self.client.get("/api/export/transactions", params={"format": "json"})
            tasks = self.client.get("/api/export/tasks", params={"format": "json"})
        self.assertEqual(transaction.status_code, 503, transaction.text)
        self.assertNotIn("old charge", transaction.text)
        self.assertEqual(tasks.status_code, 200, tasks.text)
        self.assertEqual([row["title"] for row in json.loads(tasks.text)], ["current task"])

    def test_unreadable_authority_does_not_export_old_rows(self):
        self._seed_frozen()
        with mock.patch.object(
            actual_finance,
            "is_canonical",
            side_effect=actual_finance.ActualFinanceError("authority unreadable"),
        ):
            response = self.client.get("/api/export/transactions")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("old charge", response.text)
