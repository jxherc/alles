import asyncio
import json
from datetime import date
from unittest import mock

from core.database import Account, FinanceLedgerState, Transaction
from services import actual_finance, agent_tools
from tests._client import ApiTest


class AgentFinanceCutoverTests(ApiTest):
    def _seed_frozen(self):
        db = self.db()
        account = Account(name="old bank", kind="checking", currency="CAD", opening=50)
        db.add(account)
        db.flush()
        db.add(
            Transaction(
                account_id=account.id,
                date=date.today().isoformat(),
                amount=-9,
                payee="old cafe",
                category="coffee",
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
                active_run_id="run-aide",
                actual_budget_id="budget-aide",
                actual_sync_id="sync-aide",
                base_currency_code="CAD",
                legacy_read_only=True,
            )
        )
        db.commit()
        db.close()

    @staticmethod
    def _execute(name, args=None):
        return asyncio.run(agent_tools.execute(name, args or {}))

    def test_canonical_tools_use_current_accounts_and_transactions(self):
        self._seed_frozen()
        self._cutover()
        snapshot = {"accounts": [{"id": "current"}], "transactions": [{"id": "current"}]}
        account = {
            "id": "current-account",
            "name": "new bank",
            "kind": "checking",
            "currency": "CAD",
            "balance": 100,
            "archived": False,
        }
        closed = {
            **account,
            "id": "closed-account",
            "name": "closed bank",
            "balance": 40,
            "archived": True,
        }
        current = {
            "id": "current-txn",
            "account_id": account["id"],
            "date": date.today().isoformat(),
            "payee": "new cafe",
            "category": "coffee",
            "notes": "fresh receipt",
            "amount": -12,
            "original_currency_code": "CAD",
            "base_currency_code": "CAD",
            "transfer_id": "",
        }
        transfer = {
            **current,
            "id": "current-transfer",
            "payee": "internal transfer",
            "notes": "internal",
            "amount": -20,
            "transfer_id": "transfer-1",
        }
        closed_charge = {
            **current,
            "id": "closed-charge",
            "account_id": closed["id"],
            "payee": "closed account market",
            "notes": "archived receipt",
            "amount": -3,
        }
        with (
            mock.patch.object(actual_finance, "inspect", return_value=snapshot) as inspect,
            mock.patch.object(
                actual_finance, "accounts", return_value=[account, closed]
            ) as accounts,
            mock.patch.object(
                actual_finance, "transactions", return_value=[current, transfer, closed_charge]
            ) as transactions,
        ):
            listed_accounts = self._execute("finance_accounts_list")
            listed_transactions = self._execute(
                "finance_transactions_list", {"query": "fresh receipt"}
            )
            spending = self._execute("money_query", {"query": "this month"})

        self.assertFalse(listed_accounts.get("error"), listed_accounts)
        self.assertEqual(json.loads(listed_accounts["output"])["accounts"][0]["name"], "new bank")
        self.assertEqual(listed_accounts["accounts"][0]["balance"], 100)
        self.assertFalse(listed_transactions.get("error"), listed_transactions)
        self.assertEqual(
            [row["payee"] for row in listed_transactions["transactions"]], ["new cafe"]
        )
        self.assertFalse(spending.get("error"), spending)
        self.assertIn("new bank", spending["output"])
        self.assertIn("spent 15.00", spending["output"])
        self.assertNotIn("closed bank", spending["output"])
        self.assertNotIn("old bank", spending["output"])
        self.assertNotIn("old cafe", spending["output"])
        self.assertEqual(inspect.call_count, 3)
        self.assertEqual(accounts.call_count, 2)
        self.assertEqual(transactions.call_count, 2)
        accounts.assert_called_with(mock.ANY, actual=snapshot)
        transactions.assert_called_with(mock.ANY, actual=snapshot)

    def test_provider_outage_returns_tool_errors_without_frozen_fallback(self):
        self._seed_frozen()
        self._cutover()
        with mock.patch.object(
            actual_finance,
            "inspect",
            side_effect=actual_finance.ActualFinanceUnavailable("offline"),
        ):
            for name in ("finance_accounts_list", "finance_transactions_list", "money_query"):
                with self.subTest(name=name):
                    result = self._execute(name, {"query": "coffee"})
                    self.assertTrue(result.get("error"), result)
                    self.assertIn("unavailable", result["output"])
                    self.assertNotIn("old bank", result["output"])

    def test_unreadable_authority_cannot_return_old_balance(self):
        self._seed_frozen()
        with mock.patch.object(
            actual_finance,
            "is_canonical",
            side_effect=actual_finance.ActualFinanceError("authority unreadable"),
        ):
            result = self._execute("finance_accounts_list")
        self.assertTrue(result.get("error"), result)
        self.assertNotIn("old bank", result["output"])

    def test_legacy_transaction_notes_query_still_works(self):
        self._seed_frozen()
        result = self._execute("finance_transactions_list", {"query": "old receipt"})
        self.assertFalse(result.get("error"), result)
        self.assertEqual([row["payee"] for row in result["transactions"]], ["old cafe"])
