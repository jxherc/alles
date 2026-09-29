import copy
import inspect
import json
import threading
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

from core.database import (
    Account,
    ActualEntityLink,
    ActualMigrationRun,
    Budget,
    BudgetAssignment,
    CategoryRule,
    FinanceImportBatch,
    FinanceImportRow,
    FinanceLedgerState,
    FundingTarget,
    RecurringTxn,
    SubPayment,
    Subscription,
    TagRule,
    Transaction,
)
from routes import finance_imports as finance_import_routes
from services import actual_finance, actual_migration, managed_actual
from tests._client import ApiTest


class _ThreadOwnedTrackingLock:
    def __init__(self):
        self._lock = threading.RLock()
        self.owner = None
        self.depth = 0
        self.completed_threads = []

    def __enter__(self):
        current = threading.get_ident()
        self._lock.acquire()
        if self.depth and self.owner != current:
            raise AssertionError("authority lock was re-entered from another worker thread")
        self.owner = current
        self.depth += 1
        return self

    def __exit__(self, *_args):
        current = threading.get_ident()
        if self.owner != current:
            raise AssertionError("authority lock was released from another worker thread")
        self.depth -= 1
        if not self.depth:
            self.completed_threads.append(current)
            self.owner = None
        self._lock.release()


class ActualFinanceServiceTests(ApiTest):
    @staticmethod
    def request_id(value: int) -> str:
        return f"00000000-0000-4000-8000-{value:012d}"

    def setUp(self):
        super().setUp()
        db = self.db()
        db.add(
            FinanceLedgerState(
                id="primary",
                mode="actual",
                base_currency_code="CAD",
                active_run_id="run-1",
                actual_budget_id="budget-1",
                actual_sync_id="sync-1",
                legacy_read_only=True,
            )
        )
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="account",
                source_id="legacy-account",
                actual_id="actual-account",
                metadata_json='{"account_kind":"savings","base_amount_text":"100.00","base_currency_code":"CAD","color":"mint","low_balance":25.0,"original_amount_text":"100.00","original_currency_code":"CAD","rate_text":"1","source":"legacy_identity"}',
            )
        )
        db.commit()
        db.close()
        self.actual = {
            "accounts": [
                {
                    "id": "actual-account",
                    "name": "CIBC",
                    "offbudget": False,
                    "closed": False,
                    "balance": 10000,
                }
            ],
            "transactions": [],
            "payees": [],
            "categories": [],
            "category_groups": [],
            "schedules": [],
            "budget_months": [],
        }

    def test_account_currency_rejects_an_ambiguous_dollar_symbol(self):
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "reviewed currency code"):
            actual_finance._account_currency("$", "CAD")
        self.assertEqual(actual_finance._account_currency("", "CAD"), "CAD")

    def test_envelope_uses_actual_budget_month_balances_and_rollover(self):
        calls = []

        def bridge(payload, *, timeout):
            calls.append(payload)
            return {
                "month": "2026-09",
                "toBudget": 9000,
                "totalIncome": 20000,
                "totalBudgeted": -6000,
                "categoryGroups": [
                    {
                        "name": "living",
                        "categories": [
                            {
                                "id": "food-id",
                                "name": "food",
                                "is_income": False,
                                "budgeted": 6000,
                                "spent": -1000,
                                "balance": 10000,
                            },
                            {
                                "id": "salary-id",
                                "name": "salary",
                                "is_income": True,
                                "budgeted": 0,
                                "spent": 20000,
                                "balance": 0,
                            },
                        ],
                    }
                ],
            }

        db = self.db()
        result = actual_finance.envelope(db, "2026-09", bridge_request=bridge)
        db.close()
        self.assertEqual(calls[0]["command"], "budget_month")
        self.assertEqual(calls[0]["month"], "2026-09")
        self.assertEqual(result["to_be_budgeted"], 90.0)
        self.assertEqual(result["income"], 200.0)
        self.assertEqual(result["assigned_total"], 60.0)
        self.assertEqual(
            result["categories"],
            [
                {
                    "category_id": "food-id",
                    "category": "food",
                    "group": "living",
                    "assigned": 60.0,
                    "spent": 10.0,
                    "available": 100.0,
                    "target": None,
                }
            ],
        )

    def test_envelope_rejects_incomplete_actual_month_instead_of_showing_zero(self):
        db = self.db()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "budget month"):
            actual_finance.envelope(
                db,
                "2026-09",
                bridge_request=lambda *_args, **_kwargs: {"month": "2026-09"},
            )
        db.close()

    def test_old_target_stays_unbound_until_owner_picks_an_id(self):
        month = {
            "month": date.today().strftime("%Y-%m"),
            "toBudget": 0,
            "totalIncome": 0,
            "totalBudgeted": 0,
            "categoryGroups": [
                {
                    "name": "living",
                    "categories": [
                        {"id": "food-1", "name": "food", "budgeted": 0, "spent": 0, "balance": 2500}
                    ],
                },
                {
                    "name": "other",
                    "categories": [
                        {"id": "food-2", "name": "food", "budgeted": 0, "spent": 0, "balance": 0}
                    ],
                },
            ],
        }
        calls = []

        def bridge(payload, *, timeout):
            calls.append(payload["command"])
            self.assertEqual(payload["command"], "budget_month")
            return month

        db = self.db()
        old = FundingTarget(category="food", amount=100, target_date="2026-12-01")
        db.add(old)
        db.commit()
        old_id = old.id
        before = actual_finance.envelope(db, month["month"], bridge_request=bridge)
        self.assertEqual([row["target"] for row in before["categories"]], [None, None])
        self.assertEqual(before["unbound_targets"][0]["id"], old_id)

        actual_finance.bind_funding_target(db, old_id, "food-2", bridge_request=bridge)
        month["categoryGroups"][1]["categories"][0]["name"] = "groceries"
        bound = actual_finance.envelope(db, month["month"], bridge_request=bridge)
        self.assertEqual(bound["unbound_targets"], [])
        self.assertIsNone(bound["categories"][0]["target"])
        self.assertEqual(bound["categories"][1]["category"], "groceries")
        self.assertEqual(bound["categories"][1]["target"]["amount"], 100.0)
        self.assertEqual(bound["categories"][1]["target"]["funded"], 0.0)

        actual_finance.set_funding_target(
            db, "food-2", "150.00", "2027-01-01", bridge_request=bridge
        )
        edited = actual_finance.envelope(db, month["month"], bridge_request=bridge)
        self.assertEqual(edited["categories"][1]["target"]["amount"], 150.0)
        self.assertEqual(edited["categories"][1]["target"]["date"], "2027-01-01")
        self.assertEqual(edited["categories"][1]["target"]["id"], old_id)
        self.assertEqual(db.get(FundingTarget, old_id).amount, 100.0)
        actual_finance.bind_funding_target(db, old_id, "food-1", bridge_request=bridge)
        moved = actual_finance.envelope(db, month["month"], bridge_request=bridge)
        self.assertEqual(moved["categories"][0]["target"]["amount"], 150.0)
        self.assertIsNone(moved["categories"][1]["target"])
        actual_finance.set_funding_target(db, "food-1", 0, bridge_request=bridge)
        cleared = actual_finance.envelope(db, month["month"], bridge_request=bridge)
        self.assertIsNone(cleared["categories"][0]["target"])
        self.assertEqual(cleared["unbound_targets"], [])
        self.assertTrue(all(command == "budget_month" for command in calls))
        db.close()

    def test_missing_linked_target_category_is_reviewable_not_name_rebound(self):
        month = {
            "month": date.today().strftime("%Y-%m"),
            "toBudget": 0,
            "totalIncome": 0,
            "totalBudgeted": 0,
            "categoryGroups": [
                {
                    "name": "new group",
                    "categories": [
                        {
                            "id": "replacement",
                            "name": "food",
                            "budgeted": 0,
                            "spent": 0,
                            "balance": 0,
                        }
                    ],
                }
            ],
        }
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="funding_target",
                source_id="old-target",
                actual_id="missing-original",
                metadata_json=json.dumps(
                    {
                        "category_name": "food",
                        "amount_minor": 5000,
                        "target_date": "2026-12-01",
                    }
                ),
            )
        )
        db.commit()

        def bridge(*_args, **_kwargs):
            return month

        current = actual_finance.envelope(db, month["month"], bridge_request=bridge)
        self.assertIsNone(current["categories"][0]["target"])
        self.assertEqual(current["unbound_targets"][0]["reason"], "linked category is missing")
        actual_finance.bind_funding_target(db, "old-target", "replacement", bridge_request=bridge)
        self.assertEqual(
            actual_finance.envelope(db, month["month"], bridge_request=bridge)["categories"][0][
                "target"
            ]["amount"],
            50.0,
        )
        db.close()

    def test_target_route_writes_local_sidecar_and_rejects_income_id(self):
        month = {
            "month": date.today().strftime("%Y-%m"),
            "toBudget": 0,
            "totalIncome": 0,
            "totalBudgeted": 0,
            "categoryGroups": [
                {
                    "name": "living",
                    "categories": [
                        {
                            "id": "food-id",
                            "name": "food",
                            "budgeted": 0,
                            "spent": 0,
                            "balance": 5000,
                        },
                        {
                            "id": "salary-id",
                            "name": "salary",
                            "is_income": True,
                            "budgeted": 0,
                            "spent": 0,
                            "balance": 0,
                        },
                    ],
                }
            ],
        }
        with patch("services.actual_finance._request", return_value=month) as provider:
            saved = self.client.put(
                "/api/money/envelope/target",
                json={"category_id": "food-id", "amount": 100, "target_date": "2026-12-01"},
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            current = self.client.get("/api/money/envelope", params={"month": month["month"]})
            self.assertEqual(current.status_code, 200, current.text)
            self.assertEqual(current.json()["categories"][0]["target"]["funded"], 0.5)
            bad_date = self.client.put(
                "/api/money/envelope/target",
                json={"category_id": "food-id", "amount": 200, "target_date": "2026-02-30"},
            )
            self.assertEqual(bad_date.status_code, 409, bad_date.text)
            self.assertEqual(
                self.client.get("/api/money/envelope", params={"month": month["month"]}).json()[
                    "categories"
                ][0]["target"]["amount"],
                100,
            )
            income = self.client.put(
                "/api/money/envelope/target", json={"category_id": "salary-id", "amount": 1}
            )
            self.assertEqual(income.status_code, 409, income.text)
        self.assertTrue(
            all(call.args[1]["command"] == "budget_month" for call in provider.call_args_list)
        )

    def test_assignment_uses_category_id_and_retries_a_lost_response(self):
        month = {
            "month": "2026-09",
            "toBudget": 10000,
            "totalIncome": 10000,
            "totalBudgeted": 0,
            "categoryGroups": [
                {
                    "name": "living",
                    "categories": [
                        {"id": "food-id", "name": "food", "budgeted": 0, "spent": 0, "balance": 0},
                    ],
                },
                {
                    "name": "other",
                    "categories": [
                        {
                            "id": "other-food",
                            "name": "food",
                            "budgeted": 0,
                            "spent": 0,
                            "balance": 0,
                        },
                    ],
                },
            ],
        }
        writes = []

        def bridge(payload, *, timeout):
            if payload["command"] == "budget_month":
                return month
            self.assertEqual(payload["action"], "set_budget_assignment")
            writes.append(payload)
            month["categoryGroups"][0]["categories"][0]["budgeted"] = payload["amount_minor"]
            if len(writes) == 1:
                raise managed_actual.ManagedActualError("response lost after sync")
            return {"category_id": "food-id", "amount_minor": payload["amount_minor"]}

        db = self.db()
        with self.assertRaises(actual_finance.ActualFinanceUnavailable):
            actual_finance.set_envelope_assignment(
                db, "2026-09", "food-id", "50.00", "0.00", bridge_request=bridge
            )
        pending = actual_finance.envelope(db, "2026-09", bridge_request=bridge)
        self.assertEqual(len(pending["pending_assignments"]), 1)
        self.assertEqual(pending["pending_assignments"][0]["category_id"], "food-id")
        month["categoryGroups"][0]["categories"][0]["name"] = "groceries"
        result = actual_finance.set_envelope_assignment(
            db, "2026-09", "food-id", "50.00", "0.00", bridge_request=bridge
        )
        self.assertEqual(result["assigned"], 50.0)
        self.assertEqual(result["category"], "groceries")
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["category_id"], "food-id")
        self.assertEqual(month["categoryGroups"][1]["categories"][0]["budgeted"], 0)
        link = db.query(ActualEntityLink).filter_by(entity_kind="budget_assignment").one()
        self.assertEqual(
            json.loads(link.metadata_json)["canonical_assignment"]["amount_minor"], 5000
        )
        self.assertNotIn("_update_intent", json.loads(link.metadata_json))
        db.close()

    def test_assignment_rejects_a_stale_amount_and_missing_category(self):
        month = {
            "month": "2026-09",
            "toBudget": 0,
            "totalIncome": 0,
            "totalBudgeted": 0,
            "categoryGroups": [
                {
                    "name": "living",
                    "categories": [
                        {
                            "id": "food-id",
                            "name": "food",
                            "budgeted": 1500,
                            "spent": 0,
                            "balance": 1500,
                        },
                    ],
                }
            ],
        }
        writes = []

        def bridge(payload, *, timeout):
            if payload["command"] == "budget_month":
                return month
            writes.append(payload)
            return {}

        db = self.db()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "changed; reload"):
            actual_finance.set_envelope_assignment(
                db, "2026-09", "food-id", 20, 0, bridge_request=bridge
            )
        with self.assertRaisesRegex(
            actual_finance.ActualFinanceError, "existing spending category"
        ):
            actual_finance.set_envelope_assignment(
                db, "2026-09", "missing-id", 20, 0, bridge_request=bridge
            )
        self.assertEqual(writes, [])
        db.close()

    def test_assignment_waits_for_an_older_cap_write_that_could_clear_it(self):
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="budget_limit",
                source_id="legacy-cap",
                actual_id="food-id",
                metadata_json='{"category":"food","managed_month":"2026-09","_update_intent":{"fingerprint":"old"}}',
            )
        )
        db.commit()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "cap retry"):
            actual_finance.set_envelope_assignment(
                db,
                "2026-09",
                "food-id",
                20,
                0,
                bridge_request=lambda *_args, **_kwargs: self.fail("provider write was reached"),
            )
        db.close()

    def test_zero_assignment_does_not_claim_an_untouched_actual_month(self):
        month = {
            "month": "2026-09",
            "toBudget": 0,
            "totalIncome": 0,
            "totalBudgeted": 0,
            "categoryGroups": [
                {
                    "name": "living",
                    "categories": [
                        {
                            "id": "food-id",
                            "name": "food",
                            "budgeted": 0,
                            "spent": 0,
                            "balance": 0,
                        }
                    ],
                }
            ],
        }

        def bridge(payload, *, timeout):
            self.assertEqual(payload["command"], "budget_month")
            return month

        db = self.db()
        result = actual_finance.set_envelope_assignment(
            db, "2026-09", "food-id", 0, 0, bridge_request=bridge
        )
        self.assertEqual(result["assigned"], 0)
        self.assertEqual(
            db.query(ActualEntityLink).filter_by(entity_kind="budget_assignment").count(), 0
        )
        db.close()

    def test_fake_bridge_preserves_the_requested_transaction_date(self):
        created = self.bridge(
            {
                "budget_id": "budget-1",
                "command": "write",
                "action": "create_transaction",
                "transaction": {
                    "account": "actual-chequing",
                    "date": "20260719",
                    "amount": -100,
                    "payee_name": "Market",
                    "category_name": "",
                    "notes": "",
                    "imported_id": "date-proof",
                    "cleared": False,
                },
            },
            180,
        )

        self.assertEqual(created["date"], "20260719")

    def bridge(self, payload, timeout):
        self.assertIn(timeout, {180, 300})
        self.assertEqual(payload["budget_id"], "budget-1")
        if payload["command"] == "inspect":
            return self.actual
        if payload["command"] != "write":
            self.fail(payload)
        if payload["action"] == "create_transaction":
            row = payload["transaction"]
            created = {
                "id": "actual-new",
                "account": row["account"],
                "date": row["date"],
                "amount": row["amount"],
                "payee_name": row["payee_name"],
                "category_name": row["category_name"],
                "notes": row["notes"],
                "imported_id": row["imported_id"],
                "cleared": row["cleared"],
            }
            self.actual["transactions"].append(created)
            return created
        if payload["action"] == "create_account":
            row = {
                "id": "actual-created-account",
                **payload["account"],
                "balance": payload["initial_balance_minor"],
            }
            self.actual["accounts"].append(row)
            return row
        if payload["action"] == "update_account":
            row = next(
                item for item in self.actual["accounts"] if item["id"] == payload["actual_id"]
            )
            row.update(payload["fields"])
            return row
        if payload["action"] == "update_transaction":
            row = next(
                item for item in self.actual["transactions"] if item["id"] == payload["actual_id"]
            )
            row.update(payload["fields"])
            return row
        if payload["action"] == "delete_transaction":
            self.actual["transactions"] = [
                item for item in self.actual["transactions"] if item["id"] != payload["actual_id"]
            ]
            return {"id": payload["actual_id"], "deleted": True}
        if payload["action"] == "set_budget":
            category = next(
                (
                    item
                    for item in self.actual["categories"]
                    if item["name"] == payload["category_name"]
                ),
                None,
            )
            if not category:
                category = {"id": "category-food", "name": payload["category_name"]}
                self.actual["categories"].append(category)
            month = next(
                (
                    item
                    for item in self.actual["budget_months"]
                    if item["month"] == payload["month"]
                ),
                None,
            )
            if not month:
                month = {"month": payload["month"], "categoryGroups": [{"categories": []}]}
                self.actual["budget_months"].append(month)
            rows = month["categoryGroups"][0]["categories"]
            existing = next((item for item in rows if item["id"] == category["id"]), None)
            if existing:
                existing["budgeted"] = payload["amount_minor"]
            else:
                rows.append(
                    {
                        "id": category["id"],
                        "name": category["name"],
                        "budgeted": payload["amount_minor"],
                    }
                )
            return {
                "month": payload["month"],
                "category_id": category["id"],
                "category_name": category["name"],
                "amount_minor": payload["amount_minor"],
            }
        if payload["action"] == "clear_budget":
            for month in self.actual["budget_months"]:
                if month["month"] != payload["month"]:
                    continue
                for group in month["categoryGroups"]:
                    for category in group["categories"]:
                        if category["id"] == payload["category_id"]:
                            category["budgeted"] = 0
            return {"amount_minor": 0}
        self.fail(payload)

    def test_canonical_create_records_only_actual_link_and_preserves_legacy_table(self):
        db = self.db()
        created = actual_finance.create_transaction(
            db,
            {
                "account_id": "legacy-account",
                "date": "2026-07-18",
                "amount": "-12.34",
                "payee": "market",
                "category": "food",
                "notes": "actual only",
            },
            source_id="post-cutover-1",
            bridge_request=self.bridge,
        )
        self.assertEqual(created["id"], "post-cutover-1")
        self.assertEqual(created["amount"], -12.34)
        self.assertEqual(db.query(Transaction).count(), 0)
        link = db.query(ActualEntityLink).filter_by(source_id="post-cutover-1").one()
        self.assertEqual(link.actual_id, "actual-new")
        self.assertEqual(link.entity_kind, "transaction")
        db.close()

    def test_completed_identical_transactions_remain_distinct_user_actions(self):
        db = self.db()
        writes = 0

        def bridge(payload, timeout):
            nonlocal writes
            if payload["command"] == "inspect":
                return self.actual
            self.assertEqual(payload["action"], "create_transaction")
            writes += 1
            transaction = payload["transaction"]
            row = {"id": f"actual-identical-{writes}", **transaction}
            self.actual["transactions"].append(row)
            return row

        values = {
            "account_id": "legacy-account",
            "date": "2026-07-19",
            "amount": "2.50",
            "payee": "same coffee",
            "category": "food",
        }
        first = actual_finance.create_transaction(
            db, values, request_id=self.request_id(1), bridge_request=bridge
        )
        second = actual_finance.create_transaction(
            db, values, request_id=self.request_id(2), bridge_request=bridge
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["actual_id"], second["actual_id"])
        self.assertEqual(writes, 2)
        self.assertEqual(db.query(ActualEntityLink).filter_by(entity_kind="transaction").count(), 2)
        db.close()

    def test_request_identity_separates_pending_twins_and_replays_completed_create(self):
        db = self.db()
        writes = 0
        lose_first_response = True

        def bridge(payload, timeout):
            nonlocal lose_first_response, writes
            if payload["command"] == "inspect":
                return self.actual
            self.assertEqual(payload["action"], "create_transaction")
            writes += 1
            transaction = payload["transaction"]
            row = {"id": f"actual-request-{writes}", **transaction}
            self.actual["transactions"].append(row)
            if lose_first_response:
                lose_first_response = False
                raise actual_finance.managed_actual.ManagedActualError("bridge result lost")
            return row

        values = {
            "account_id": "legacy-account",
            "date": "2026-07-19",
            "amount": "2.50",
            "payee": "same pending coffee",
            "category": "food",
        }
        first_request = self.request_id(11)
        second_request = self.request_id(12)
        with self.assertRaises(actual_finance.ActualFinanceError):
            actual_finance.create_transaction(
                db, values, request_id=first_request, bridge_request=bridge
            )

        second = actual_finance.create_transaction(
            db, values, request_id=second_request, bridge_request=bridge
        )
        first = actual_finance.create_transaction(
            db, values, request_id=first_request, bridge_request=bridge
        )
        replayed_second = actual_finance.create_transaction(
            db, values, request_id=second_request, bridge_request=bridge
        )

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(replayed_second["id"], second["id"])
        self.assertEqual(writes, 2)
        self.assertEqual(len(self.actual["transactions"]), 2)
        self.assertEqual(db.query(ActualEntityLink).filter_by(entity_kind="transaction").count(), 2)
        db.close()

    def test_completed_account_create_retry_preserves_later_updates(self):
        db = self.db()
        writes = []

        def bridge(payload, timeout):
            if payload["command"] == "write":
                writes.append(payload["action"])
            return self.bridge(payload, timeout)

        request_id = self.request_id(13)
        original = {"name": "trip fund", "currency": "CAD", "opening": "5.00"}
        created = actual_finance.create_account(
            db, original, request_id=request_id, bridge_request=bridge
        )
        updated = actual_finance.update_account(
            db,
            created["id"],
            {"name": "rainy day", "archived": True, "color": "clay"},
            bridge_request=bridge,
        )
        writes_before_replay = list(writes)

        replayed = actual_finance.create_account(
            db, original, request_id=request_id, bridge_request=bridge
        )

        self.assertEqual(replayed["id"], created["id"])
        self.assertEqual(replayed["name"], "rainy day")
        self.assertTrue(replayed["archived"])
        self.assertEqual(replayed["color"], "clay")
        self.assertEqual(replayed, updated)
        self.assertEqual(writes, writes_before_replay)
        db.close()

    def test_completed_transaction_create_retry_preserves_later_updates(self):
        db = self.db()
        writes = []

        def bridge(payload, timeout):
            if payload["command"] == "write":
                writes.append(payload["action"])
            return self.bridge(payload, timeout)

        request_id = self.request_id(14)
        original = {
            "account_id": "legacy-account",
            "date": "2026-07-19",
            "amount": "2.50",
            "payee": "coffee",
            "category": "food",
            "notes": "original",
        }
        created = actual_finance.create_transaction(
            db, original, request_id=request_id, bridge_request=bridge
        )
        updated = actual_finance.update_transaction(
            db,
            created["id"],
            {"notes": "corrected", "tags": "reviewed", "receipt_id": "receipt-1"},
            bridge_request=bridge,
        )
        writes_before_replay = list(writes)

        replayed = actual_finance.create_transaction(
            db, original, request_id=request_id, bridge_request=bridge
        )

        self.assertEqual(replayed["id"], created["id"])
        self.assertEqual(replayed["notes"], "corrected")
        self.assertEqual(replayed["tags"], "reviewed")
        self.assertEqual(replayed["receipt_id"], "receipt-1")
        self.assertEqual(replayed, updated)
        self.assertEqual(writes, writes_before_replay)
        db.close()

    def test_create_request_id_cannot_claim_a_non_create_link(self):
        db = self.db()
        request_id = self.request_id(15)
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="account",
                source_id=request_id,
                actual_id="actual-account",
                metadata_json="{}",
            )
        )
        db.commit()

        with self.assertRaisesRegex(
            actual_finance.ActualFinanceError,
            "request identity is already owned by a non-create link",
        ):
            actual_finance.create_account(
                db,
                {"name": "must not overwrite", "currency": "CAD"},
                request_id=request_id,
                bridge_request=lambda *_args: self.fail("bridge must not be called"),
            )
        self.assertEqual(self.actual["accounts"][0]["name"], "CIBC")
        db.close()

    def test_unresolved_external_create_intents_block_native_identity_reads(self):
        db = self.db()
        checks = {
            "account": lambda: actual_finance.accounts(db, actual=self.actual),
            "transaction": lambda: actual_finance.transactions(db, actual=self.actual),
            "transfer": lambda: actual_finance.transactions(db, actual=self.actual),
        }
        for index, (kind, read) in enumerate(checks.items(), start=20):
            with self.subTest(kind=kind):
                link = ActualEntityLink(
                    run_id="run-1",
                    entity_kind=kind,
                    source_id=self.request_id(index),
                    actual_id="",
                    metadata_json=json.dumps(
                        {"_intent": {"version": 1, "fingerprint": f"pending-{kind}"}}
                    ),
                )
                db.add(link)
                db.commit()
                with self.assertRaisesRegex(
                    actual_finance.ActualFinanceError,
                    rf"canonical {kind} creation is incomplete",
                ):
                    read()
                db.delete(link)
                db.commit()
        db.close()

    def test_completed_identical_accounts_remain_distinct_user_actions(self):
        db = self.db()
        writes = 0

        def bridge(payload, timeout):
            nonlocal writes
            if payload["command"] == "inspect":
                return self.actual
            if payload["action"] == "create_account":
                writes += 1
                row = {
                    "id": f"actual-account-{writes}",
                    **payload["account"],
                    "balance": payload["initial_balance_minor"],
                }
                self.actual["accounts"].append(row)
                return row
            if payload["action"] == "update_account":
                row = next(
                    item for item in self.actual["accounts"] if item["id"] == payload["actual_id"]
                )
                row.update(payload["fields"])
                return row
            self.fail(payload)

        values = {"name": "same savings", "currency": "CAD", "opening": "5.00"}
        first = actual_finance.create_account(
            db, values, request_id=self.request_id(1), bridge_request=bridge
        )
        second = actual_finance.create_account(
            db, values, request_id=self.request_id(2), bridge_request=bridge
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["actual_id"], second["actual_id"])
        self.assertEqual(writes, 2)
        db.close()

    def test_canonical_spending_cap_changes_do_not_write_actual_assignments(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": "2026-07",
                "categoryGroups": [{"categories": [{"id": "food-id", "budgeted": 2500}]}],
            }
        ]
        db = self.db()
        created = actual_finance.set_budget(
            db, "2026-07", "food", "12.34", bridge_request=self.bridge
        )
        self.assertEqual(created["limit_amt"], 12.34)
        self.assertEqual(
            actual_finance.budgets(db, "2026-07", bridge_request=self.bridge)[0]["category"],
            "food",
        )
        cap = db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").one()
        self.assertEqual(cap.actual_id, created["actual_id"])
        self.assertIn('"limit_minor":1234', cap.metadata_json)
        self.assertNotIn("managed_month", cap.metadata_json)
        self.assertEqual(
            self.actual["budget_months"][0]["categoryGroups"][0]["categories"][0]["budgeted"],
            2500,
        )
        august = actual_finance.budgets(db, "2026-08", bridge_request=self.bridge)[0]
        self.assertEqual(august["limit_amt"], 12.34)
        self.assertEqual(august["id"], f"actual-budget-cap:{created['actual_id']}")
        self.assertTrue(
            actual_finance.clear_budget(db, august["id"], bridge_request=self.bridge)["ok"]
        )
        self.assertEqual(actual_finance.budgets(db, "2026-07", bridge_request=self.bridge), [])
        self.assertEqual(actual_finance.budgets(db, "2026-08", bridge_request=self.bridge), [])
        self.assertEqual(
            self.actual["budget_months"][0]["categoryGroups"][0]["categories"][0]["budgeted"],
            2500,
        )
        db.close()

    def test_persistent_cap_identity_survives_reload_and_deletion(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        db = self.db()
        created = actual_finance.set_budget(
            db, "2026-07", "food", "12.34", bridge_request=self.bridge
        )

        listed = actual_finance.budgets(db, "2026-07", bridge_request=self.bridge)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], created["id"])
        self.assertTrue(
            actual_finance.clear_budget(db, listed[0]["id"], bridge_request=self.bridge)["ok"]
        )
        self.assertEqual(actual_finance.budgets(db, "2026-07", bridge_request=self.bridge), [])
        deleted = db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").one()
        self.assertEqual(deleted.actual_id, "")
        self.assertTrue(json.loads(deleted.metadata_json)["_deleted"])
        db.close()

    def test_explicit_assignment_and_legacy_managed_cap_remain_separate(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": "2026-07",
                "categoryGroups": [
                    {"categories": [{"id": "food-id", "name": "food", "budgeted": 2500}]}
                ],
            }
        ]
        db = self.db()
        db.add_all(
            [
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="budget_assignment",
                    source_id="assignment:legacy-assignment",
                    actual_id="2026-07:food-id",
                    metadata_json='{"source_kind":"assignment"}',
                ),
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="budget_limit",
                    source_id="legacy-cap",
                    actual_id="food-id",
                    metadata_json=(
                        '{"category":"food","limit_minor":4000,"managed_month":"2026-07",'
                        '"source":"legacy_persistent_cap"}'
                    ),
                ),
            ]
        )
        db.commit()

        listed = actual_finance.budgets(db, "2026-07", bridge_request=self.bridge)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], "actual-budget-cap:food-id")
        self.assertEqual(listed[0]["limit_amt"], 40.0)
        db.close()

    def test_explicit_zero_assignment_does_not_hide_a_spending_cap(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": "2026-07",
                "categoryGroups": [
                    {"categories": [{"id": "food-id", "name": "food", "budgeted": 0}]}
                ],
            }
        ]
        db = self.db()
        db.add_all(
            [
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="budget_assignment",
                    source_id="assignment:zero-override",
                    actual_id="2026-07:food-id",
                    metadata_json='{"source_kind":"assignment"}',
                ),
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="budget_limit",
                    source_id="legacy-cap",
                    actual_id="food-id",
                    metadata_json=(
                        '{"category":"food","limit_minor":4000,"managed_month":"",'
                        '"source":"legacy_persistent_cap"}'
                    ),
                ),
            ]
        )
        db.commit()

        listed = actual_finance.budgets(db, "2026-07", bridge_request=self.bridge)
        self.assertEqual(
            [(row["id"], row["limit_amt"]) for row in listed], [("actual-budget-cap:food-id", 40.0)]
        )
        db.close()

    def test_changing_a_persistent_cap_leaves_both_actual_months_untouched(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": month,
                "categoryGroups": [{"categories": [{"id": "food-id", "budgeted": value}]}],
            }
            for month, value in (("2026-07", 1200), ("2026-08", 3000))
        ]
        db = self.db()
        created = actual_finance.set_budget(
            db, "2026-07", "food", "12.34", bridge_request=self.bridge
        )
        updated = actual_finance.set_budget(
            db, "2026-08", "food", "23.45", bridge_request=self.bridge
        )

        self.assertEqual(updated["id"], created["id"])
        assignments = {
            month["month"]: month["categoryGroups"][0]["categories"][0]["budgeted"]
            for month in self.actual["budget_months"]
        }
        self.assertEqual(assignments, {"2026-07": 1200, "2026-08": 3000})
        cap = db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").one()
        self.assertIn('"limit_minor":2345', cap.metadata_json)
        self.assertNotIn("managed_month", cap.metadata_json)
        db.close()

    def test_invalid_budget_month_is_rejected_before_a_durable_intent(self):
        db = self.db()
        bridge_calls = []

        def bridge(payload, timeout):
            bridge_calls.append((payload, timeout))
            return self.bridge(payload, timeout)

        for invalid in ("2026-00", "2026-13", "not-a-month"):
            with self.subTest(month=invalid), self.assertRaises(actual_finance.ActualFinanceError):
                actual_finance.set_budget(db, invalid, "food", "12.34", bridge_request=bridge)
        self.assertEqual(bridge_calls, [])
        self.assertEqual(
            db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").count(), 0
        )
        db.close()

    def test_spending_cap_requires_one_existing_actual_category(self):
        db = self.db()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "one existing spending"):
            actual_finance.set_budget(db, "2026-07", "food", "12.34", bridge_request=self.bridge)
        self.actual["categories"] = [
            {"id": "food-1", "name": "Food"},
            {"id": "food-2", "name": "food"},
        ]
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "one existing spending"):
            actual_finance.set_budget(db, "2026-07", "food", "12.34", bridge_request=self.bridge)
        self.actual["categories"] = [{"id": "income-id", "name": "food", "is_income": True}]
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "one existing spending"):
            actual_finance.set_budget(db, "2026-07", "food", "12.34", bridge_request=self.bridge)
        self.assertEqual(
            db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").count(), 0
        )
        self.assertEqual(self.actual["budget_months"], [])
        db.close()

    def test_spending_cap_follows_actual_category_identity_after_rename(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        db = self.db()
        created = actual_finance.set_budget(
            db, "2026-07", "food", "12.34", bridge_request=self.bridge
        )
        self.actual["categories"][0]["name"] = "groceries"
        updated = actual_finance.set_budget(
            db, "2026-08", "groceries", "23.45", bridge_request=self.bridge
        )
        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(
            db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").count(), 1
        )
        listed = actual_finance.budgets(db, "2026-08", bridge_request=self.bridge)
        self.assertEqual(
            [(row["category"], row["limit_amt"]) for row in listed], [("groceries", 23.45)]
        )
        db.close()

    def test_spending_cap_does_not_silently_rebind_a_replaced_category(self):
        self.actual["categories"] = [{"id": "replacement-id", "name": "food"}]
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="budget_limit",
                source_id="legacy-cap",
                actual_id="old-id",
                metadata_json='{"category":"food","limit_minor":1234}',
            )
        )
        db.commit()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "not safely linked"):
            actual_finance.budgets(db, "2026-07", bridge_request=self.bridge)
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "not safely linked"):
            actual_finance.set_budget(db, "2026-07", "food", "23.45", bridge_request=self.bridge)
        self.assertEqual(
            db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").count(), 1
        )
        db.close()

    def test_old_budget_update_intent_can_be_retried_after_a_lost_response(self):
        db = self.db()
        intent = {
            "category": "food",
            "amount_minor": 1234,
            "month": "2026-07",
            "previous_category_id": "",
            "previous_month": "",
        }
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="budget_limit",
                source_id="actual-budget-cap-pending:food",
                actual_id="",
                metadata_json=json.dumps(
                    {
                        "category": "food",
                        "source": "alles_persistent_cap",
                        "_update_intent": {
                            "version": 1,
                            "fingerprint": actual_finance._request_fingerprint(
                                "set_budget", intent
                            ),
                            **intent,
                        },
                    }
                ),
            )
        )
        db.commit()
        lose_response = True
        writes = 0

        def bridge(payload, timeout):
            nonlocal lose_response, writes
            if payload["command"] == "inspect":
                return self.bridge(payload, timeout)
            self.assertEqual(payload["action"], "set_budget")
            writes += 1
            pending = db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").one()
            self.assertIn("_update_intent", json.loads(pending.metadata_json))
            result = self.bridge(payload, timeout)
            if lose_response:
                lose_response = False
                raise managed_actual.ManagedActualError("set response lost")
            return result

        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "set response lost"):
            actual_finance.set_budget(db, "2026-07", "food", "12.34", bridge_request=bridge)
        pending = db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").one()
        self.assertIn("_update_intent", json.loads(pending.metadata_json))
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "update is uncertain"):
            actual_finance.budgets(db, "2026-07", bridge_request=bridge)

        completed = actual_finance.set_budget(db, "2026-07", "food", "12.34", bridge_request=bridge)

        self.assertEqual(completed["limit_amt"], 12.34)
        self.assertEqual(writes, 2)
        self.assertNotIn("_update_intent", json.loads(pending.metadata_json))
        self.assertNotIn("managed_month", json.loads(pending.metadata_json))
        db.close()

    def test_native_budget_delete_persists_an_intent_before_external_mutation(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": "2026-07",
                "categoryGroups": [
                    {"categories": [{"id": "food-id", "name": "food", "budgeted": 2500}]}
                ],
            }
        ]
        lose_response = True

        def bridge(payload, timeout):
            nonlocal lose_response
            if payload["command"] == "inspect":
                return self.actual
            self.assertEqual(payload["action"], "clear_budget")
            row = self.actual["budget_months"][0]["categoryGroups"][0]["categories"][0]
            row["budgeted"] = 0
            if lose_response:
                lose_response = False
                raise managed_actual.ManagedActualError("clear response lost")
            return {"amount_minor": 0}

        db = self.db()
        public_id = "actual-budget:2026-07:food-id"
        with self.assertRaises(actual_finance.ActualFinanceError):
            actual_finance.clear_budget(db, public_id, bridge_request=bridge)
        link = db.query(ActualEntityLink).filter_by(entity_kind="budget_assignment").one()
        self.assertEqual(link.actual_id, "2026-07:food-id")
        self.assertIn("_delete_intent", json.loads(link.metadata_json))
        self.assertEqual(actual_finance.budgets(db, "2026-07", bridge_request=bridge), [])
        self.assertTrue(actual_finance.clear_budget(db, public_id, bridge_request=bridge)["ok"])
        self.assertEqual(link.actual_id, "")
        self.assertIn("_deleted", json.loads(link.metadata_json))
        db.close()

    def test_completed_budget_assignment_delete_clears_a_recreated_assignment(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        row = {"id": "food-id", "name": "food", "budgeted": 2500}
        self.actual["budget_months"] = [
            {"month": "2026-07", "categoryGroups": [{"categories": [row]}]}
        ]
        writes = 0

        def bridge(payload, timeout):
            nonlocal writes
            if payload["command"] == "write" and payload["action"] == "clear_budget":
                writes += 1
            return self.bridge(payload, timeout)

        db = self.db()
        public_id = "actual-budget:2026-07:food-id"
        self.assertTrue(actual_finance.clear_budget(db, public_id, bridge_request=bridge)["ok"])
        row["budgeted"] = 1900
        self.assertTrue(actual_finance.clear_budget(db, public_id, bridge_request=bridge)["ok"])

        self.assertEqual(writes, 2)
        self.assertEqual(row["budgeted"], 0)
        link = db.query(ActualEntityLink).filter_by(entity_kind="budget_assignment").one()
        self.assertEqual(link.actual_id, "")
        self.assertIn("_deleted", json.loads(link.metadata_json))
        db.close()

    def test_owner_approved_deleted_transaction_can_reuse_its_import_identity(self):
        db = self.db()
        bridge_flags = []

        def bridge(payload, timeout):
            if payload.get("action") == "create_transaction":
                bridge_flags.append(payload.get("reimport_deleted"))
            return self.bridge(payload, timeout)

        values = {
            "account_id": "legacy-account",
            "date": "2026-07-18",
            "amount": "-12.34",
            "payee": "market",
        }
        created = actual_finance.create_transaction(
            db,
            values,
            source_id="finance-import:receipt-1:1",
            import_identity="stable-import-row",
            bridge_request=bridge,
        )
        self.assertTrue(
            actual_finance.delete_transaction(db, created["id"], bridge_request=bridge)["ok"]
        )

        recreated = actual_finance.create_transaction(
            db,
            values,
            source_id="finance-import:receipt-1:1",
            import_identity="stable-import-row",
            bridge_request=bridge,
            reimport_deleted=True,
        )

        self.assertEqual(recreated["import_identity"], "stable-import-row")
        self.assertEqual(bridge_flags, [False, True])
        link = (
            db.query(ActualEntityLink)
            .filter_by(entity_kind="transaction", source_id="finance-import:receipt-1:1")
            .one()
        )
        self.assertNotIn("_deleted", json.loads(link.metadata_json))
        db.close()

    def test_cleared_persistent_budget_cap_can_be_created_again(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        db = self.db()
        created = actual_finance.set_budget(
            db, "2026-07", "food", "12.34", bridge_request=self.bridge
        )
        self.assertTrue(
            actual_finance.clear_budget(db, created["id"], bridge_request=self.bridge)["ok"]
        )

        recreated = actual_finance.set_budget(
            db, "2026-08", "food", "23.45", bridge_request=self.bridge
        )

        self.assertEqual(recreated["limit_amt"], 23.45)
        links = db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").all()
        self.assertEqual(len(links), 1)
        self.assertNotIn("_deleted", json.loads(links[0].metadata_json))
        self.assertEqual(links[0].actual_id, recreated["actual_id"])
        db.close()

    def test_canonical_routes_fail_closed_when_the_ledger_state_is_missing(self):
        db = self.db()
        db.delete(db.get(FinanceLedgerState, "primary"))
        db.commit()
        db.close()
        with patch("routes.money.actual_finance.is_canonical", return_value=True):
            for path in ("/api/money/networth-base", "/api/money/summary"):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 409, (path, response.text))
                self.assertIn("canonical ledger state", response.text)

    def test_canonical_tag_budget_sidecar_remains_readable_writable_and_deletable(self):
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="tag_budget",
                source_id="legacy-tag-budget",
                actual_id="sidecar:tag_budget:legacy-tag-budget",
                metadata_json='{"limit_minor":2500,"tag":"coffee"}',
            )
        )
        db.commit()
        listed = actual_finance.budgets(db, "2026-07", actual=self.actual)
        self.assertEqual(
            listed,
            [
                {
                    "id": "actual-tag-budget:legacy-tag-budget",
                    "actual_id": "sidecar:tag_budget:legacy-tag-budget",
                    "category": "",
                    "tag": "coffee",
                    "limit_amt": 25.0,
                }
            ],
        )
        updated = actual_finance.set_tag_budget(db, " Coffee ", "30.00")
        self.assertEqual(updated["limit_amt"], 30.0)
        self.assertEqual(
            actual_finance.budgets(db, "2026-07", actual=self.actual)[0]["limit_amt"],
            30.0,
        )
        self.assertTrue(actual_finance.clear_budget(db, updated["id"])["ok"])
        self.assertEqual(actual_finance.budgets(db, "2026-07", actual=self.actual), [])
        db.close()

    def test_explicit_actual_assignment_does_not_replace_persistent_cap(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": "2026-07",
                "categoryGroups": [{"categories": [{"id": "food-id", "budgeted": 2500}]}],
            }
        ]
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="budget_limit",
                source_id="legacy-cap",
                actual_id="food-id",
                metadata_json=(
                    '{"category":"food","limit_minor":4000,"source":"legacy_persistent_cap"}'
                ),
            )
        )
        db.commit()
        rows = actual_finance.budgets(db, "2026-07", bridge_request=self.bridge)
        self.assertEqual(rows[0]["id"], "actual-budget-cap:food-id")
        self.assertEqual(rows[0]["limit_amt"], 40.0)
        db.close()

    def test_clearing_cap_preserves_an_explicit_actual_budget_assignment(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": "2026-07",
                "categoryGroups": [
                    {"categories": [{"id": "food-id", "name": "food", "budgeted": 2500}]}
                ],
            }
        ]
        db = self.db()
        db.add_all(
            [
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="budget_assignment",
                    source_id="assignment:legacy-assignment",
                    actual_id="2026-07:food-id",
                    metadata_json='{"source_kind":"assignment"}',
                ),
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="budget_limit",
                    source_id="legacy-cap",
                    actual_id="food-id",
                    metadata_json=(
                        '{"category":"food","limit_minor":4000,"managed_month":"",'
                        '"source":"legacy_persistent_cap"}'
                    ),
                ),
            ]
        )
        db.commit()

        self.assertEqual(
            actual_finance.budgets(db, "2026-07", bridge_request=self.bridge)[0]["id"],
            "actual-budget-cap:food-id",
        )
        self.assertTrue(
            actual_finance.clear_budget(
                db,
                "actual-budget-cap:food-id",
                bridge_request=self.bridge,
            )["ok"]
        )
        actual_row = self.actual["budget_months"][0]["categoryGroups"][0]["categories"][0]
        self.assertEqual(actual_row["budgeted"], 2500)
        remaining = actual_finance.budgets(db, "2026-07", bridge_request=self.bridge)
        self.assertEqual(remaining, [])
        db.close()

    def test_clearing_an_old_managed_cap_keeps_its_actual_assignment(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": "2026-07",
                "categoryGroups": [{"categories": [{"id": "food-id", "budgeted": 4000}]}],
            }
        ]
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="budget_limit",
                source_id="legacy-cap",
                actual_id="food-id",
                metadata_json=(
                    '{"category":"food","limit_minor":4000,"managed_month":"2026-07",'
                    '"source":"legacy_persistent_cap"}'
                ),
            )
        )
        db.commit()
        self.assertTrue(
            actual_finance.clear_budget(
                db, "actual-budget-cap:food-id", bridge_request=self.bridge
            )["ok"]
        )
        self.assertEqual(
            self.actual["budget_months"][0]["categoryGroups"][0]["categories"][0]["budgeted"],
            4000,
        )
        cap = db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").one()
        self.assertNotIn("managed_month", cap.metadata_json)
        self.assertIn("_deleted", cap.metadata_json)
        db.close()

    def test_clearing_explicit_assignment_preserves_the_persistent_cap(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": "2026-07",
                "categoryGroups": [
                    {"categories": [{"id": "food-id", "name": "food", "budgeted": 2500}]}
                ],
            }
        ]
        db = self.db()
        db.add_all(
            [
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="budget_assignment",
                    source_id="assignment:legacy-assignment",
                    actual_id="2026-07:food-id",
                    metadata_json='{"source_kind":"assignment"}',
                ),
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="budget_limit",
                    source_id="legacy-cap",
                    actual_id="food-id",
                    metadata_json=(
                        '{"category":"food","limit_minor":4000,"managed_month":"",'
                        '"source":"legacy_persistent_cap"}'
                    ),
                ),
            ]
        )
        db.commit()

        self.assertTrue(
            actual_finance.clear_budget(
                db,
                "actual-budget:2026-07:food-id",
                bridge_request=self.bridge,
            )["ok"]
        )

        actual_row = self.actual["budget_months"][0]["categoryGroups"][0]["categories"][0]
        self.assertEqual(actual_row["budgeted"], 0)
        remaining = actual_finance.budgets(db, "2026-07", bridge_request=self.bridge)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], "actual-budget-cap:food-id")
        self.assertEqual(remaining[0]["limit_amt"], 40.0)
        cap = db.query(ActualEntityLink).filter_by(entity_kind="budget_limit").one()
        assignment = db.query(ActualEntityLink).filter_by(entity_kind="budget_assignment").one()
        self.assertEqual(cap.actual_id, "food-id")
        self.assertIn("_deleted", json.loads(assignment.metadata_json))
        db.close()

    def test_transaction_retry_recovers_from_durable_prewrite_intent(self):
        db = self.db()
        first = True
        writes = 0

        def bridge(payload, timeout):
            nonlocal first, writes
            if payload["command"] == "inspect":
                return self.actual
            writes += 1
            transaction = payload["transaction"]
            existing = next(
                (
                    row
                    for row in self.actual["transactions"]
                    if row.get("imported_id") == transaction["imported_id"]
                ),
                None,
            )
            if not existing:
                existing = {
                    "id": "durable-transaction",
                    **transaction,
                    "payee_name": transaction["payee_name"],
                    "category_name": transaction["category_name"],
                }
                self.actual["transactions"].append(existing)
            if first:
                first = False
                raise actual_finance.managed_actual.ManagedActualError("bridge result lost")
            return existing

        values = {
            "account_id": "legacy-account",
            "date": "2026-07-19",
            "amount": "1.25",
            "payee": "coffee",
        }
        with self.assertRaises(actual_finance.ActualFinanceError):
            actual_finance.create_transaction(
                db,
                values,
                source_id="durable-source",
                import_identity="durable-import",
                bridge_request=bridge,
            )
        pending = db.query(ActualEntityLink).filter_by(source_id="durable-source").one()
        self.assertEqual(pending.actual_id, "")
        self.assertIn("_intent", json.loads(pending.metadata_json))
        recovered = actual_finance.create_transaction(
            db,
            values,
            source_id="durable-source",
            import_identity="durable-import",
            bridge_request=bridge,
        )
        self.assertEqual(recovered["actual_id"], "durable-transaction")
        self.assertEqual(len(self.actual["transactions"]), 1)
        self.assertEqual(writes, 1)
        self.assertNotIn("_intent", json.loads(pending.metadata_json))
        db.close()

    def test_migrated_transactions_expose_their_source_import_identity(self):
        db = self.db()
        db.add_all(
            [
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="transaction",
                    source_id="legacy-imported",
                    actual_id="actual-imported",
                    metadata_json=json.dumps(
                        {"migration_source_import_identity": "bank:statement:row-7"}
                    ),
                ),
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="transaction",
                    source_id="legacy-manual",
                    actual_id="actual-manual",
                    metadata_json=json.dumps({"migration_source_import_identity": ""}),
                ),
            ]
        )
        db.commit()
        actual = {
            **self.actual,
            "transactions": [
                {
                    "id": "actual-imported",
                    "account": "actual-account",
                    "date": "20260701",
                    "amount": -100,
                    "imported_id": "alles:migration:run-1:legacy-imported",
                },
                {
                    "id": "actual-manual",
                    "account": "actual-account",
                    "date": "20260702",
                    "amount": -200,
                    "imported_id": "alles:migration:run-1:legacy-manual",
                },
            ],
        }
        rows = actual_finance.transactions(db, actual=actual)
        self.assertEqual(
            {row["id"]: row["import_identity"] for row in rows},
            {
                "legacy-imported": "bank:statement:row-7",
                "legacy-manual": "",
            },
        )
        db.close()

    def test_account_retry_recovers_marker_without_duplicate_external_create(self):
        db = self.db()
        first = True

        def bridge(payload, timeout):
            nonlocal first
            if payload["command"] == "inspect":
                return self.actual
            if payload["action"] == "create_account":
                self.assertEqual(payload["operation_marker"], payload["account"]["name"])
                self.assertRegex(
                    payload["operation_marker"],
                    r"^Alles pending [0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
                )
                row = {
                    "id": "durable-account",
                    **payload["account"],
                    "balance": payload["initial_balance_minor"],
                }
                self.actual["accounts"].append(row)
                if first:
                    first = False
                    raise actual_finance.managed_actual.ManagedActualError("bridge result lost")
                return row
            if payload["action"] == "update_account":
                row = next(
                    item for item in self.actual["accounts"] if item["id"] == payload["actual_id"]
                )
                row.update(payload["fields"])
                return row
            self.fail(payload)

        values = {"name": "recovered savings", "currency": "CAD", "opening": "4.50"}
        with self.assertRaises(actual_finance.ActualFinanceError):
            actual_finance.create_account(
                db, values, request_id=self.request_id(3), bridge_request=bridge
            )
        recovered = actual_finance.create_account(
            db, values, request_id=self.request_id(3), bridge_request=bridge
        )
        self.assertEqual(recovered["actual_id"], "durable-account")
        self.assertEqual(
            [row["name"] for row in self.actual["accounts"]].count("recovered savings"), 1
        )
        link = db.query(ActualEntityLink).filter_by(actual_id="durable-account").one()
        self.assertNotIn("_intent", json.loads(link.metadata_json))
        db.close()

    def test_account_retry_recovers_an_intent_after_actual_id_is_persisted(self):
        db = self.db()
        fail_update = True

        def bridge(payload, timeout):
            nonlocal fail_update
            if payload["command"] == "inspect":
                return self.actual
            if payload["action"] == "create_account":
                row = {
                    "id": "persisted-before-rename",
                    **payload["account"],
                    "balance": payload["initial_balance_minor"],
                }
                self.actual["accounts"].append(row)
                return row
            if payload["action"] == "update_account":
                if fail_update:
                    fail_update = False
                    raise actual_finance.managed_actual.ManagedActualError("rename response lost")
                row = next(
                    item for item in self.actual["accounts"] if item["id"] == payload["actual_id"]
                )
                row.update(payload["fields"])
                return row
            self.fail(payload)

        values = {"name": "durable chequing", "currency": "CAD", "opening": "2.00"}
        with self.assertRaises(actual_finance.ActualFinanceError):
            actual_finance.create_account(
                db, values, request_id=self.request_id(4), bridge_request=bridge
            )
        pending = db.query(ActualEntityLink).filter_by(actual_id="persisted-before-rename").one()
        self.assertIn("_intent", json.loads(pending.metadata_json))
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "creation is incomplete"):
            actual_finance.accounts(db, bridge_request=bridge)
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "creation is incomplete"):
            actual_finance.update_account(
                db,
                pending.source_id,
                {"name": "must not use the marker"},
                bridge_request=bridge,
            )
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "creation is incomplete"):
            actual_finance.create_transaction(
                db,
                {
                    "account_id": pending.source_id,
                    "date": "2026-07-19",
                    "amount": "1.00",
                },
                bridge_request=bridge,
            )
        recovered = actual_finance.create_account(
            db, values, request_id=self.request_id(4), bridge_request=bridge
        )
        self.assertEqual(recovered["actual_id"], "persisted-before-rename")
        self.assertEqual(len(self.actual["accounts"]), 2)
        self.assertNotIn("_intent", json.loads(pending.metadata_json))
        db.close()

    def test_account_update_retry_recovers_after_a_lost_external_response(self):
        db = self.db()
        writes = 0
        lose_response = True

        def bridge(payload, timeout):
            nonlocal lose_response, writes
            if payload["command"] == "inspect":
                return self.actual
            if payload["action"] == "update_account":
                writes += 1
                row = next(
                    item for item in self.actual["accounts"] if item["id"] == payload["actual_id"]
                )
                row.update(payload["fields"])
                if lose_response:
                    lose_response = False
                    raise actual_finance.managed_actual.ManagedActualError("update response lost")
                return row
            self.fail(payload)

        values = {"name": "renamed after loss", "archived": True}
        with self.assertRaises(actual_finance.ActualFinanceError):
            actual_finance.update_account(
                db,
                "legacy-account",
                values,
                bridge_request=bridge,
            )
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "update is uncertain"):
            actual_finance.accounts(db, bridge_request=bridge)
        recovered = actual_finance.update_account(
            db,
            "legacy-account",
            values,
            bridge_request=bridge,
        )
        self.assertEqual(recovered["name"], "renamed after loss")
        self.assertTrue(recovered["archived"])
        self.assertEqual(writes, 1)
        link = db.query(ActualEntityLink).filter_by(source_id="legacy-account").one()
        metadata = json.loads(link.metadata_json)
        self.assertNotIn("_update_intent", metadata)
        self.assertEqual(
            metadata["canonical_account"],
            {
                "name": "renamed after loss",
                "offbudget": False,
                "closed": True,
                "opening_minor": 10000,
            },
        )
        db.close()

    def test_account_checkpoint_uses_live_actual_fields_before_local_metadata_updates(self):
        db = self.db()
        link = db.query(ActualEntityLink).filter_by(source_id="legacy-account").one()
        metadata = json.loads(link.metadata_json)
        metadata["canonical_account"] = {
            "name": "stale checkpoint",
            "offbudget": True,
            "closed": True,
        }
        link.metadata_json = json.dumps(metadata)
        db.commit()
        self.actual["accounts"][0].update(
            {"name": "renamed in Actual", "offbudget": False, "closed": False}
        )

        actual_finance.update_account(
            db,
            "legacy-account",
            {"color": "clay"},
            bridge_request=self.bridge,
        )

        checkpoint = json.loads(link.metadata_json)["canonical_account"]
        self.assertEqual(
            checkpoint,
            {
                "name": "renamed in Actual",
                "offbudget": False,
                "closed": False,
                "opening_minor": 10000,
            },
        )
        db.close()

    def test_transfer_retry_reuses_durable_import_identity(self):
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="account",
                source_id="legacy-second",
                actual_id="actual-second",
                metadata_json="{}",
            )
        )
        db.commit()
        self.actual["accounts"].append(
            {
                "id": "actual-second",
                "name": "second",
                "offbudget": False,
                "closed": False,
                "balance": 0,
            }
        )
        first = True
        writes = 0

        def bridge(payload, timeout):
            nonlocal first, writes
            if payload["command"] == "inspect":
                return self.actual
            writes += 1
            transfer = payload["transfer"]
            imported_id = f"{transfer['imported_id']}:out"
            out = next(
                (
                    row
                    for row in self.actual["transactions"]
                    if row.get("imported_id") == imported_id
                ),
                None,
            )
            if not out:
                out = {
                    "id": "durable-out",
                    "account": transfer["from_account"],
                    "date": transfer["date"],
                    "amount": -transfer["amount_minor"],
                    "notes": transfer["notes"],
                    "imported_id": imported_id,
                    "transfer_id": "durable-in",
                }
                incoming = {
                    "id": "durable-in",
                    "account": transfer["to_account"],
                    "date": transfer["date"],
                    "amount": transfer["amount_minor"],
                    "notes": transfer["notes"],
                    "imported_id": "",
                    "transfer_id": "durable-out",
                }
                self.actual["transactions"].extend((out, incoming))
            if first:
                first = False
                raise actual_finance.managed_actual.ManagedActualError("bridge result lost")
            return {"from_id": "durable-out", "to_id": "durable-in"}

        values = {
            "from_account": "legacy-account",
            "to_account": "legacy-second",
            "amount": "3.00",
            "date": "2026-07-19",
            "notes": "save",
        }
        with self.assertRaises(actual_finance.ActualFinanceError):
            actual_finance.create_transfer(
                db, values, request_id=self.request_id(5), bridge_request=bridge
            )
        outgoing = next(row for row in self.actual["transactions"] if row["id"] == "durable-out")
        incoming = next(row for row in self.actual["transactions"] if row["id"] == "durable-in")
        outgoing["notes"] = "changed after commit"
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "durable intent"):
            actual_finance.create_transfer(
                db, values, request_id=self.request_id(5), bridge_request=bridge
            )
        outgoing["notes"] = values["notes"]
        incoming["notes"] = "changed after commit"
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "durable intent"):
            actual_finance.create_transfer(
                db, values, request_id=self.request_id(5), bridge_request=bridge
            )
        incoming["notes"] = values["notes"]
        recovered = actual_finance.create_transfer(
            db, values, request_id=self.request_id(5), bridge_request=bridge
        )
        self.assertEqual(recovered["from"]["actual_id"], "durable-out")
        self.assertEqual(recovered["to"]["actual_id"], "durable-in")
        self.assertEqual(len(self.actual["transactions"]), 2)
        self.assertEqual(writes, 1)
        self.assertEqual(writes, 1)
        transfer_link = db.query(ActualEntityLink).filter_by(entity_kind="transfer").one()
        self.assertNotIn("_intent", json.loads(transfer_link.metadata_json))
        db.close()

    def test_transaction_delete_response_loss_reconciles_without_a_second_delete(self):
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="transaction",
                source_id="legacy-transaction",
                actual_id="actual-transaction",
                metadata_json="{}",
            )
        )
        db.commit()
        self.actual["transactions"] = [
            {
                "id": "actual-transaction",
                "account": "actual-account",
                "date": "20260719",
                "amount": -125,
            }
        ]
        delete_calls = 0

        def bridge(payload, timeout):
            nonlocal delete_calls
            if payload["command"] == "inspect":
                return self.actual
            self.assertEqual(payload["action"], "delete_transaction")
            delete_calls += 1
            self.actual["transactions"] = []
            raise managed_actual.ManagedActualError("delete response lost")

        with self.assertRaises(actual_finance.ActualFinanceUnavailable):
            actual_finance.delete_transaction(db, "legacy-transaction", bridge_request=bridge)
        pending = db.query(ActualEntityLink).filter_by(source_id="legacy-transaction").one()
        self.assertEqual(
            json.loads(pending.metadata_json)["_delete_intent"]["actual_id"],
            "actual-transaction",
        )
        self.assertTrue(
            actual_finance.delete_transaction(db, "legacy-transaction", bridge_request=bridge)["ok"]
        )
        db.refresh(pending)
        self.assertEqual(delete_calls, 1)
        self.assertEqual(pending.actual_id, "")
        self.assertEqual(
            json.loads(pending.metadata_json)["_deleted"]["actual_id"],
            "actual-transaction",
        )
        db.close()

    def test_pending_transaction_deletion_blocks_reads_and_updates_until_retry(self):
        db = self.db()
        link = ActualEntityLink(
            run_id="run-1",
            entity_kind="transaction",
            source_id="legacy-transaction",
            actual_id="actual-transaction",
            metadata_json="{}",
        )
        db.add(link)
        db.commit()
        self.actual["transactions"] = [
            {
                "id": "actual-transaction",
                "account": "actual-account",
                "date": "20260719",
                "amount": -125,
            }
        ]
        actual_finance._begin_link_deletion(db, link)

        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "deletion is incomplete"):
            actual_finance.transactions(db, actual=self.actual)
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "deletion is incomplete"):
            actual_finance.update_transaction(
                db,
                "actual-transaction",
                {"notes": "must not survive"},
                bridge_request=self.bridge,
            )

        def bridge(payload, timeout):
            if payload["command"] == "inspect":
                return self.actual
            self.assertEqual(payload["action"], "delete_transaction")
            self.actual["transactions"] = []
            return {"ok": True}

        self.assertTrue(
            actual_finance.delete_transaction(db, "legacy-transaction", bridge_request=bridge)["ok"]
        )
        db.close()

    def test_transfer_delete_tombstones_the_pair_and_both_transaction_links(self):
        db = self.db()
        for kind, source_id, actual_id in (
            ("transfer", "legacy-transfer", "actual-out:actual-in"),
            ("transaction", "legacy-out", "actual-out"),
            ("transaction", "legacy-in", "actual-in"),
        ):
            db.add(
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind=kind,
                    source_id=source_id,
                    actual_id=actual_id,
                    metadata_json="{}",
                )
            )
        db.commit()
        self.actual["transactions"] = [
            {"id": "actual-out", "account": "actual-account", "transfer_id": "actual-in"},
            {"id": "actual-in", "account": "actual-account", "transfer_id": "actual-out"},
        ]

        def bridge(payload, timeout):
            if payload["command"] == "inspect":
                return self.actual
            self.assertEqual(payload["action"], "delete_transfer")
            self.assertEqual(payload["actual_ids"], ["actual-out", "actual-in"])
            self.actual["transactions"] = []
            return {"deleted": 2}

        result = actual_finance.delete_transfer(db, "legacy-transfer", bridge_request=bridge)
        self.assertEqual(result, {"ok": True, "removed": 2})
        links = (
            db.query(ActualEntityLink)
            .filter(ActualEntityLink.source_id.in_(["legacy-transfer", "legacy-out", "legacy-in"]))
            .all()
        )
        self.assertEqual(len(links), 3)
        self.assertTrue(all(link.actual_id == "" for link in links))
        self.assertTrue(all("_deleted" in json.loads(link.metadata_json) for link in links))
        transaction_links = db.query(ActualEntityLink).filter_by(entity_kind="transaction").all()
        self.assertEqual(
            {link.source_id for link in transaction_links}, {"legacy-out", "legacy-in"}
        )
        db.close()

    def test_transfer_components_cannot_be_edited_as_independent_transactions(self):
        db = self.db()
        for source_id, actual_id in (
            ("legacy-out", "actual-out"),
            ("legacy-in", "actual-in"),
        ):
            db.add(
                ActualEntityLink(
                    run_id="run-1",
                    entity_kind="transaction",
                    source_id=source_id,
                    actual_id=actual_id,
                    metadata_json="{}",
                )
            )
        db.commit()
        self.actual["transactions"] = [
            {
                "id": "actual-out",
                "account": "actual-account",
                "date": "20260719",
                "amount": -500,
                "transfer_id": "actual-in",
            },
            {
                "id": "actual-in",
                "account": "actual-account",
                "date": "20260719",
                "amount": 500,
                "transfer_id": "actual-out",
            },
        ]
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "cannot be edited directly"):
            actual_finance.update_transaction(
                db, "legacy-out", {"amount": -600}, bridge_request=self.bridge
            )
        self.assertEqual(self.actual["transactions"][0]["amount"], -500)
        with self.assertRaisesRegex(
            actual_finance.ActualFinanceError, "cannot be deleted directly"
        ):
            actual_finance.delete_transaction(
                db,
                "legacy-out",
                bridge_request=self.bridge,
            )
        links = db.query(ActualEntityLink).filter_by(entity_kind="transaction").all()
        self.assertTrue(all(json.loads(link.metadata_json) == {} for link in links))
        self.assertEqual(len(self.actual["transactions"]), 2)
        db.close()

    def test_more_than_two_decimal_places_fail_before_bridge_write(self):
        db = self.db()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "two decimal places"):
            actual_finance.create_transaction(
                db,
                {"account_id": "legacy-account", "date": "2026-07-18", "amount": "1.001"},
                bridge_request=self.bridge,
            )
        self.assertEqual(db.query(ActualEntityLink).filter_by(entity_kind="transaction").count(), 0)
        db.close()

    def test_minor_units_preserve_cent_precision_through_float_responses(self):
        amount = "70368744177663.99"
        minor = actual_finance._minor(amount)
        self.assertEqual(minor, 7_036_874_417_766_399)
        self.assertEqual(Decimal(str(actual_finance._major_from_minor(minor))), Decimal(amount))
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "exact numeric range"):
            actual_finance._minor("70368744177664.01")
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "cent-safe numeric range"):
            actual_finance._major_from_minor(7_036_874_417_766_401)

    def test_linked_actual_subscription_schedule_is_readable_after_cutover(self):
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="subscription",
                source_id="legacy-subscription",
                actual_id="actual-schedule",
                metadata_json=('{"category":"software","url":"https://billing.example.test"}'),
            )
        )
        db.commit()
        self.actual["schedules"] = [
            {
                "id": "actual-schedule",
                "name": "Alles subscription: mail [legacy-s]",
                "account": "actual-account",
                "amount": -899,
                "completed": False,
                "date": {"start": "2026-08-05", "frequency": "monthly", "interval": 1},
                "next_date": "2026-08-05",
            }
        ]
        rows = actual_finance.subscription_schedules(db, bridge_request=self.bridge)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "legacy-subscription")
        self.assertEqual(rows[0]["price"], 8.99)
        self.assertEqual(rows[0]["cycle"], "monthly")
        self.assertEqual(rows[0]["next_due"], "2026-08-05")
        self.assertEqual(rows[0]["account_id"], "legacy-account")
        self.assertEqual(rows[0]["metadata"]["category"], "software")
        self.assertTrue(rows[0]["active"])
        link = db.query(ActualEntityLink).filter_by(entity_kind="subscription").one()
        link.metadata_json = '{"active":false,"category":"software","posting_rule_version":1}'
        db.commit()
        self.assertFalse(
            actual_finance.subscription_schedules(db, bridge_request=self.bridge)[0]["active"]
        )
        self.actual["schedules"][0]["posts_transaction"] = True
        self.assertTrue(
            actual_finance.subscription_schedules(db, bridge_request=self.bridge)[0]["active"]
        )
        db.close()

    def test_actual_subscription_recurrence_is_exact_or_fails_closed(self):
        self.assertEqual(
            actual_finance._schedule_cycle(
                {"start": "2026-08-05", "frequency": "daily", "interval": 1}
            ),
            ("daily", 1, "2026-08-05"),
        )
        self.assertEqual(
            actual_finance._schedule_cycle(
                {"start": "2026-08-05", "frequency": "weekly", "interval": 2}
            ),
            ("custom", 14, "2026-08-05"),
        )
        self.assertEqual(
            actual_finance._schedule_cycle(
                {"start": "2026-08-05", "frequency": "daily", "interval": 10}
            ),
            ("custom", 10, "2026-08-05"),
        )
        with self.assertRaisesRegex(
            actual_finance.ActualFinanceError, "cannot be represented exactly"
        ):
            actual_finance._schedule_cycle(
                {"start": "2026-08-05", "frequency": "monthly", "interval": 2}
            )
        with self.assertRaisesRegex(
            actual_finance.ActualFinanceError, "cannot be represented exactly"
        ):
            actual_finance._schedule_cycle(
                {"start": "2026-08-05", "frequency": "yearly", "interval": 2}
            )
        with self.assertRaisesRegex(
            actual_finance.ActualFinanceError, "frequency fortnightly is unsupported"
        ):
            actual_finance._schedule_cycle(
                {"start": "2026-08-05", "frequency": "fortnightly", "interval": 1}
            )

    def test_subscription_schedule_advances_the_anchor_to_the_next_occurrence(self):
        rule = {"start": "2026-08-05", "frequency": "monthly", "interval": 1}
        self.assertEqual(
            actual_finance._next_schedule_due(rule, today=date(2026, 10, 6)),
            "2026-11-05",
        )
        self.assertEqual(
            actual_finance._next_schedule_due(rule, "2026-12-05", today=date(2026, 10, 6)),
            "2026-12-05",
        )

    def test_subscription_schedule_handles_more_than_ten_thousand_daily_occurrences(self):
        rule = {"start": "1980-01-01", "frequency": "daily", "interval": 1}

        self.assertEqual(
            actual_finance._next_schedule_due(rule, today=date(2026, 7, 22)),
            "2026-07-22",
        )

    def test_actual_opening_balance_transaction_is_not_exposed_or_double_counted(self):
        self.actual["transactions"] = [
            {
                "id": "actual-opening",
                "account": "actual-account",
                "date": "20260718",
                "amount": 10000,
                "starting_balance_flag": True,
                "notes": "Starting Balance",
            },
            {
                "id": "actual-visible",
                "account": "actual-account",
                "date": "20260718",
                "amount": -125,
                "starting_balance_flag": False,
                "payee_name": "coffee",
            },
        ]
        db = self.db()
        rows = actual_finance.transactions(db, bridge_request=self.bridge)
        self.assertEqual([row["actual_id"] for row in rows], ["actual-visible"])
        self.assertEqual(rows[0]["amount"], -1.25)
        db.close()

    def test_native_actual_account_derives_its_hidden_opening_balance(self):
        self.actual["accounts"].append(
            {
                "id": "actual-native-opening",
                "name": "native savings",
                "offbudget": False,
                "closed": False,
                "balance": 2375,
            }
        )
        self.actual["transactions"].append(
            {
                "id": "actual-native-opening-transaction",
                "account": "actual-native-opening",
                "date": "20260701",
                "amount": 2375,
                "starting_balance_flag": True,
            }
        )
        db = self.db()

        row = next(
            item
            for item in actual_finance.accounts(db, bridge_request=self.bridge)
            if item["actual_id"] == "actual-native-opening"
        )

        self.assertEqual(row["opening"], 23.75)
        self.assertEqual(row["original_opening_text"], "23.75")
        self.assertEqual(row["base_opening_text"], "23.75")
        db.close()

    def test_networth_history_uses_actual_opening_once(self):
        db = self.db()
        db.add(Account(id="legacy-account", name="CIBC", opening=100.0))
        db.commit()
        db.close()
        self.actual["accounts"][0]["balance"] = 9875
        self.actual["transactions"] = [
            {
                "id": "actual-opening",
                "account": "actual-account",
                "date": "20260701",
                "amount": 10000,
                "starting_balance_flag": True,
            },
            {
                "id": "actual-spend",
                "account": "actual-account",
                "date": "20260712",
                "amount": -125,
                "starting_balance_flag": False,
            },
        ]
        with patch("services.managed_actual.bridge_request", side_effect=self.bridge) as bridge:
            response = self.client.get("/api/money/networth-history?months=2&as_of=2026-07-15")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [
                {"month": "2026-06", "net_worth": 100.0},
                {"month": "2026-07", "net_worth": 98.75},
            ],
        )
        self.assertEqual(bridge.call_count, 1)

    def test_networth_history_follows_a_changed_migrated_opening_balance(self):
        db = self.db()
        db.add(Account(id="legacy-account", name="CIBC", opening=100.0))
        db.commit()
        db.close()
        self.actual["accounts"][0]["balance"] = 14875
        self.actual["transactions"] = [
            {
                "id": "actual-opening",
                "account": "actual-account",
                "date": "20260701",
                "amount": 15000,
                "starting_balance_flag": True,
            },
            {
                "id": "actual-spend",
                "account": "actual-account",
                "date": "20260712",
                "amount": -125,
                "starting_balance_flag": False,
            },
        ]
        with patch("services.managed_actual.bridge_request", side_effect=self.bridge):
            response = self.client.get("/api/money/networth-history?months=2&as_of=2026-07-15")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [
                {"month": "2026-06", "net_worth": 150.0},
                {"month": "2026-07", "net_worth": 148.75},
            ],
        )

    def test_networth_history_dates_new_actual_openings_without_redating_legacy(self):
        db = self.db()
        db.add(Account(id="legacy-account", name="CIBC", opening=100.0))
        db.commit()
        db.close()
        self.actual["accounts"].append(
            {
                "id": "actual-native-opening",
                "name": "new account",
                "offbudget": False,
                "closed": False,
                "balance": 3500,
            }
        )
        self.actual["transactions"] = [
            {
                "id": "legacy-opening",
                "account": "actual-account",
                "date": "20260808",
                "amount": 10000,
                "starting_balance_flag": True,
            },
            {
                "id": "native-opening",
                "account": "actual-native-opening",
                "date": "20260808",
                "amount": 4000,
                "starting_balance_flag": True,
            },
            {
                "id": "native-spend",
                "account": "actual-native-opening",
                "date": "20260912",
                "amount": -500,
                "starting_balance_flag": False,
            },
        ]
        with patch("services.managed_actual.bridge_request", side_effect=self.bridge) as bridge:
            response = self.client.get("/api/money/networth-history?months=3&as_of=2026-09-15")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [
                {"month": "2026-07", "net_worth": 100.0},
                {"month": "2026-08", "net_worth": 140.0},
                {"month": "2026-09", "net_worth": 135.0},
            ],
        )
        self.assertEqual(bridge.call_count, 1)

    def test_networth_history_dates_post_cutover_linked_opening_entries(self):
        db = self.db()
        db.add(Account(id="legacy-account", name="CIBC", opening=100.0))
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="account",
                source_id="new-account",
                actual_id="actual-new-account",
                metadata_json='{"base_amount_text":"30.00","source":"actual_identity"}',
            )
        )
        db.commit()
        db.close()
        self.actual["accounts"].append(
            {
                "id": "actual-new-account",
                "name": "new savings",
                "offbudget": False,
                "closed": False,
                "balance": 2500,
            }
        )
        self.actual["transactions"] = [
            {
                "id": "new-opening",
                "account": "actual-new-account",
                "date": "20260831",
                "amount": 3000,
                "starting_balance_flag": True,
            },
            {
                "id": "new-opening-adjustment",
                "account": "actual-new-account",
                "date": "20260902",
                "amount": -500,
                "starting_balance_flag": True,
            },
        ]
        with patch("services.managed_actual.bridge_request", side_effect=self.bridge) as bridge:
            response = self.client.get("/api/money/networth-history?months=3&as_of=2026-09-15")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [
                {"month": "2026-07", "net_worth": 100.0},
                {"month": "2026-08", "net_worth": 130.0},
                {"month": "2026-09", "net_worth": 125.0},
            ],
        )
        self.assertEqual(bridge.call_count, 1)

    def test_native_actual_entities_remain_resolvable_and_transfers_stay_paired(self):
        self.actual["accounts"].append(
            {
                "id": "native-account",
                "name": "native cash",
                "offbudget": False,
                "closed": False,
                "balance": 0,
            }
        )
        self.actual["transactions"] = [
            {
                "id": "native-out",
                "account": "actual-account",
                "date": "20260718",
                "amount": -500,
                "transfer_id": "native-in",
            },
            {
                "id": "native-in",
                "account": "native-account",
                "date": "20260718",
                "amount": 500,
                "transfer_id": "native-out",
            },
        ]
        db = self.db()
        rows = actual_finance.transactions(db, bridge_request=self.bridge)
        self.assertEqual(rows[0]["transfer_id"], rows[1]["transfer_id"])
        self.assertTrue(rows[0]["transfer_id"].startswith("actual-transfer:"))
        self.assertEqual(
            actual_finance._resolve(db, "account", "native-account", bridge_request=self.bridge),
            "native-account",
        )
        created = actual_finance.create_transaction(
            db,
            {
                "account_id": "native-account",
                "date": "2026-07-19",
                "amount": "-1.00",
                "payee": "native purchase",
            },
            source_id="native-account-write",
            bridge_request=self.bridge,
        )
        self.assertEqual(created["account_id"], "native-account")
        self.assertEqual(
            actual_finance._resolve(db, "transaction", "native-out", bridge_request=self.bridge),
            "native-out",
        )
        pair = actual_finance._resolve(
            db, "transfer", rows[0]["transfer_id"], bridge_request=self.bridge
        ).split(":")
        self.assertEqual(set(pair), {"native-out", "native-in"})
        db.close()

    def test_actual_budget_month_is_not_a_spending_cap_source(self):
        self.actual["categories"] = [{"id": "food-id", "name": "food"}]
        self.actual["budget_months"] = [
            {
                "month": "2026-07",
                "categoryGroups": [{"categories": [{"id": "food-id", "budgeted": 2500}]}],
            }
        ]
        db = self.db()
        self.assertEqual(actual_finance.budgets(db, "2026-07", bridge_request=self.bridge), [])
        db.close()

    def test_account_display_metadata_survives_the_actual_boundary(self):
        db = self.db()
        row = actual_finance.accounts(db, bridge_request=self.bridge)[0]
        self.assertEqual(row["kind"], "savings")
        self.assertEqual(row["color"], "mint")
        self.assertEqual(row["low_balance"], 25.0)
        db.close()

    def test_amount_edit_resets_foreign_evidence_to_canonical_identity(self):
        self.actual["transactions"].append(
            {
                "id": "actual-foreign",
                "account": "actual-account",
                "date": "20260718",
                "amount": -200,
                "payee_name": "tea",
                "category_name": "food",
                "notes": "",
                "imported_id": "foreign-row",
                "cleared": False,
            }
        )
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="transaction",
                source_id="legacy-foreign",
                actual_id="actual-foreign",
                metadata_json='{"original_amount_text":"-10.00","original_currency_code":"CNY","base_amount_text":"-2.00","base_currency_code":"CAD","rate_text":"0.2","rate_date":"2026-07-18","source":"owner_review"}',
            )
        )
        db.commit()
        updated = actual_finance.update_transaction(
            db,
            "legacy-foreign",
            {"amount": "-3.00"},
            bridge_request=self.bridge,
        )
        self.assertEqual(updated["original_currency_code"], "CAD")
        self.assertEqual(updated["base_currency_code"], "CAD")
        self.assertEqual(updated["original_amount_text"], "-3")
        self.assertEqual(updated["base_amount_text"], "-3")
        link = db.query(ActualEntityLink).filter_by(source_id="legacy-foreign").one()
        self.assertIn('"original_currency_code":"CAD"', link.metadata_json)
        self.assertIn('"rate_date":""', link.metadata_json)
        db.close()

    def test_transaction_update_by_actual_id_preserves_the_existing_public_id(self):
        self.actual["transactions"].append(
            {
                "id": "actual-linked",
                "account": "actual-account",
                "date": "20260718",
                "amount": -100,
                "payee_name": "old",
                "category_name": "food",
                "notes": "",
                "imported_id": "linked-row",
                "cleared": False,
            }
        )
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="transaction",
                source_id="legacy-linked",
                actual_id="actual-linked",
                metadata_json='{"original_amount_text":"-1","original_currency_code":"CAD","base_amount_text":"-1","base_currency_code":"CAD","rate_text":"1","source":"legacy_identity"}',
            )
        )
        db.commit()
        updated = actual_finance.update_transaction(
            db,
            "actual-linked",
            {"payee": "new"},
            bridge_request=self.bridge,
        )
        self.assertEqual(updated["id"], "legacy-linked")
        links = db.query(ActualEntityLink).filter_by(entity_kind="transaction").all()
        self.assertEqual(
            [(row.source_id, row.actual_id) for row in links], [("legacy-linked", "actual-linked")]
        )
        db.close()

    def test_transaction_update_retry_recovers_after_a_lost_external_response(self):
        self.actual["transactions"].append(
            {
                "id": "actual-update-retry",
                "account": "actual-account",
                "date": "20260718",
                "amount": -100,
                "payee_name": "before",
                "category_name": "food",
                "notes": "",
                "imported_id": "update-retry",
                "cleared": False,
            }
        )
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="transaction",
                source_id="legacy-update-retry",
                actual_id="actual-update-retry",
                metadata_json='{"original_amount_text":"-1","original_currency_code":"CAD","base_amount_text":"-1","base_currency_code":"CAD","rate_text":"1","source":"legacy_identity"}',
            )
        )
        db.commit()
        writes = 0

        def lost_response(payload, timeout):
            nonlocal writes
            result = self.bridge(payload, timeout)
            if payload.get("action") == "update_transaction":
                writes += 1
                if writes == 1:
                    raise managed_actual.ManagedActualError("response was lost")
            return result

        with self.assertRaises(actual_finance.ActualFinanceUnavailable):
            actual_finance.update_transaction(
                db,
                "legacy-update-retry",
                {"amount": "-2.00", "payee": "after"},
                bridge_request=lost_response,
            )
        pending = db.query(ActualEntityLink).filter_by(source_id="legacy-update-retry").one()
        self.assertIn('"_update_intent"', pending.metadata_json)
        recovered = actual_finance.update_transaction(
            db,
            "legacy-update-retry",
            {"amount": "-2.00", "payee": "after"},
            bridge_request=lost_response,
        )
        self.assertEqual(writes, 1)
        self.assertEqual(recovered["amount"], -2.0)
        self.assertEqual(recovered["payee"], "after")
        completed = db.query(ActualEntityLink).filter_by(source_id="legacy-update-retry").one()
        self.assertNotIn('"_update_intent"', completed.metadata_json)
        self.assertIn('"base_amount_text":"-2"', completed.metadata_json)
        db.close()

    def test_transaction_update_clears_an_imported_payee(self):
        self.actual["transactions"].append(
            {
                "id": "actual-imported-payee",
                "account": "actual-account",
                "date": "20260718",
                "amount": -100,
                "payee_name": "",
                "imported_payee": "bank description",
                "category_name": "food",
                "notes": "",
                "cleared": False,
            }
        )
        writes = 0

        def bridge(payload, timeout):
            nonlocal writes
            if payload.get("action") == "update_transaction":
                writes += 1
                row = self.actual["transactions"][-1]
                row["payee_name"] = ""
                row["imported_payee"] = ""
                return row
            return self.bridge(payload, timeout)

        db = self.db()
        updated = actual_finance.update_transaction(
            db,
            "actual-imported-payee",
            {"payee": ""},
            bridge_request=bridge,
        )

        self.assertEqual(writes, 1)
        self.assertEqual(updated["payee"], "")
        db.close()

    def test_invalid_transaction_date_is_rejected_before_an_update_intent(self):
        db = self.db()
        link = ActualEntityLink(
            run_id="run-1",
            entity_kind="transaction",
            source_id="legacy-invalid-date",
            actual_id="actual-invalid-date",
            metadata_json='{"source":"legacy_identity"}',
        )
        db.add(link)
        db.commit()
        bridge_calls = []

        def bridge(payload, timeout):
            bridge_calls.append((payload, timeout))
            return self.bridge(payload, timeout)

        for invalid in ("", "2026-02-30", "2026-99-99", "2026-07-20garbage"):
            with (
                self.subTest(date=invalid),
                self.assertRaisesRegex(actual_finance.ActualFinanceError, "valid calendar date"),
            ):
                actual_finance.update_transaction(
                    db,
                    "legacy-invalid-date",
                    {"date": invalid},
                    bridge_request=bridge,
                )
        self.assertEqual(bridge_calls, [])
        self.assertNotIn("_update_intent", json.loads(link.metadata_json))
        db.close()

    def test_invalid_transfer_date_is_rejected_before_a_creation_intent(self):
        db = self.db()
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="account",
                source_id="second-account",
                actual_id="actual-second-account",
                metadata_json='{"source":"legacy_identity"}',
            )
        )
        db.commit()
        bridge_calls = []

        def bridge(payload, timeout):
            bridge_calls.append((payload, timeout))
            return self.bridge(payload, timeout)

        for invalid in ("", "2026-02-30", "2026-99-99", "2026-07-20garbage"):
            with (
                self.subTest(date=invalid),
                self.assertRaisesRegex(
                    actual_finance.ActualFinanceError, "transfer date must be a valid calendar date"
                ),
            ):
                actual_finance.create_transfer(
                    db,
                    {
                        "from_account": "legacy-account",
                        "to_account": "second-account",
                        "amount": "10.00",
                        "date": invalid,
                        "notes": "invalid date",
                    },
                    request_id=self.request_id(6),
                    bridge_request=bridge,
                )
        self.assertEqual(bridge_calls, [])
        self.assertEqual(db.query(ActualEntityLink).filter_by(entity_kind="transfer").count(), 0)
        db.close()

    def test_required_dates_accept_only_explicit_complete_date_formats(self):
        self.assertEqual(actual_finance._required_date("20260720"), "2026-07-20")
        self.assertEqual(actual_finance._required_date("2026-07-20"), "2026-07-20")
        self.assertEqual(
            actual_finance._required_date("2026-07-20T23:59:58.123456-04:00"),
            "2026-07-20",
        )
        for invalid in (
            "2026-07-20T23:59:58Zgarbage",
            "2026-07-20 23:59:58",
            "2026-07-20T25:00:00",
        ):
            with (
                self.subTest(date=invalid),
                self.assertRaisesRegex(actual_finance.ActualFinanceError, "valid calendar date"),
            ):
                actual_finance._required_date(invalid)

    def test_zero_and_same_account_transfers_fail_before_creation_intent(self):
        db = self.db()
        bridge_calls = []

        def bridge(payload, timeout):
            bridge_calls.append((payload, timeout))
            return self.bridge(payload, timeout)

        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "greater than zero"):
            actual_finance.create_transfer(
                db,
                {
                    "from_account": "legacy-account",
                    "to_account": "legacy-account",
                    "amount": "0",
                    "date": "2026-07-19",
                },
                request_id=self.request_id(7),
                bridge_request=bridge,
            )
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "must be different"):
            actual_finance.create_transfer(
                db,
                {
                    "from_account": "legacy-account",
                    "to_account": "legacy-account",
                    "amount": "1.00",
                    "date": "2026-07-19",
                },
                request_id=self.request_id(8),
                bridge_request=bridge,
            )
        self.assertEqual(bridge_calls, [])
        self.assertEqual(db.query(ActualEntityLink).filter_by(entity_kind="transfer").count(), 0)
        db.close()

    def test_partial_native_transaction_edit_records_a_complete_restore_checkpoint(self):
        db = self.db()
        self.actual["transactions"].append(
            {
                "id": "actual-native-edit",
                "account": "actual-account",
                "date": "20260703",
                "amount": -725,
                "payee_name": "before",
                "category_name": "food",
                "notes": "native note",
                "cleared": False,
            }
        )

        updated = actual_finance.update_transaction(
            db,
            "actual-native-edit",
            {"payee": "after"},
            bridge_request=self.bridge,
        )
        self.assertEqual(updated["payee"], "after")
        link = db.query(ActualEntityLink).filter_by(actual_id="actual-native-edit").one()
        checkpoint = json.loads(link.metadata_json)["canonical_transaction"]
        self.assertEqual(
            checkpoint,
            {
                "account": "actual-account",
                "date": "2026-07-03",
                "amount": -725,
                "payee_name": "after",
                "category_name": "food",
                "notes": "native note",
                "cleared": False,
            },
        )
        db.close()

    def test_transaction_checkpoint_does_not_override_live_actual_fields(self):
        db = self.db()
        self.actual["transactions"].append(
            {
                "id": "actual-live-edit",
                "account": "actual-account",
                "date": "20260704",
                "amount": -925,
                "payee_name": "live merchant",
                "category_name": "live category",
                "notes": "live note",
                "cleared": True,
            }
        )
        db.add(
            ActualEntityLink(
                run_id="run-1",
                entity_kind="transaction",
                source_id="legacy-live-edit",
                actual_id="actual-live-edit",
                metadata_json=json.dumps(
                    {
                        "canonical_transaction": {
                            "account": "actual-account",
                            "date": "2026-01-01",
                            "amount": -100,
                            "payee_name": "stale merchant",
                            "category_name": "stale category",
                            "notes": "stale note",
                            "cleared": False,
                        }
                    }
                ),
            )
        )
        db.commit()

        actual_finance.update_transaction(
            db,
            "legacy-live-edit",
            {"tags": "reviewed"},
            bridge_request=self.bridge,
        )

        link = db.query(ActualEntityLink).filter_by(source_id="legacy-live-edit").one()
        checkpoint = json.loads(link.metadata_json)["canonical_transaction"]
        self.assertEqual(
            checkpoint,
            {
                "account": "actual-account",
                "date": "2026-07-04",
                "amount": -925,
                "payee_name": "live merchant",
                "category_name": "live category",
                "notes": "live note",
                "cleared": True,
            },
        )
        db.close()

    def test_new_account_rejects_foreign_currency_and_keeps_display_metadata(self):
        db = self.db()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "base currency CAD"):
            actual_finance.create_account(
                db,
                {"name": "foreign", "currency": "USD"},
                request_id=self.request_id(9),
                bridge_request=self.bridge,
            )
        self.assertEqual(len(self.actual["accounts"]), 1)

        created = actual_finance.create_account(
            db,
            {
                "name": "cash tin",
                "currency": "CAD",
                "kind": "cash",
                "opening": "12.50",
                "color": "ochre",
                "low_balance": "3.25",
            },
            request_id=self.request_id(10),
            bridge_request=self.bridge,
        )
        self.assertEqual(created["kind"], "cash")
        self.assertEqual(created["color"], "ochre")
        self.assertEqual(created["low_balance"], 3.25)
        self.assertEqual(created["balance"], 12.5)

        updated = actual_finance.update_account(
            db,
            created["id"],
            {"kind": "savings", "color": "clay", "low_balance": "4.75"},
            bridge_request=self.bridge,
        )
        self.assertEqual(updated["kind"], "savings")
        self.assertEqual(updated["color"], "clay")
        self.assertEqual(updated["low_balance"], 4.75)
        db.close()


class ActualFinanceRouteAuthorityTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        db.add(
            FinanceLedgerState(
                id="primary",
                mode="actual",
                base_currency_code="CAD",
                active_run_id="run-route",
                actual_budget_id="budget-route",
                actual_sync_id="sync-route",
                legacy_read_only=True,
            )
        )
        db.add(Account(id="legacy-account", name="legacy", kind="checking", currency="CAD"))
        db.add(
            RecurringTxn(
                account_id="legacy-account",
                amount=-5,
                payee="legacy recurring",
                cycle="monthly",
                next_date="2020-01-01",
                active=True,
            )
        )
        db.add(
            Subscription(
                name="legacy sub",
                price=5,
                currency="CAD",
                cycle="monthly",
                next_due="2026-08-01",
                active=True,
                original_price_text="5",
                original_currency_code="CAD",
                base_price_text="5",
                base_currency_code="CAD",
                fx_rate_text="1",
                fx_source="legacy_identity",
            )
        )
        db.commit()
        db.close()

    def test_supported_transaction_write_routes_to_actual_without_dual_write(self):
        canonical = {
            "id": "actual-public",
            "account_id": "legacy-account",
            "date": "2026-07-18",
            "amount": -4.0,
            "category": "food",
            "payee": "market",
            "notes": "",
            "transfer_id": "",
            "tags": "",
            "receipt_id": "",
            "cleared": False,
            "split": False,
            "original_amount_text": "-4",
            "original_currency_code": "CAD",
            "base_amount_text": "-4",
            "base_currency_code": "CAD",
            "import_identity": "alles:actual:test",
            "import_batch_id": "",
            "import_source": "actual",
        }
        with patch(
            "routes.money.actual_finance.create_transaction", return_value=canonical
        ) as write:
            response = self.client.post(
                "/api/money/transactions",
                json={
                    "account_id": "legacy-account",
                    "date": "2026-07-18",
                    "amount": -4,
                    "category": "food",
                    "payee": "market",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        write.assert_called_once()
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        self.assertEqual(db.query(RecurringTxn).one().next_date, "2020-01-01")
        db.close()

    def test_canonical_transaction_creation_ignores_frozen_legacy_rules(self):
        db = self.db()
        db.add(CategoryRule(match="market", category="groceries"))
        db.add(TagRule(match="market", tags="weekly,coffee"))
        db.commit()
        db.close()
        canonical = {
            "id": "actual-public",
            "actual_id": "actual-row",
            "account_id": "legacy-account",
            "date": "2026-07-18",
            "amount": -4.0,
            "category": "dining",
            "payee": "Market Hall",
            "notes": "",
            "transfer_id": "",
            "tags": "manual,weekly",
            "receipt_id": "",
            "cleared": False,
            "split": False,
            "original_amount_text": "-4",
            "original_currency_code": "CAD",
            "base_amount_text": "-4",
            "base_currency_code": "CAD",
            "import_identity": "alles:actual:test",
            "import_batch_id": "",
            "import_source": "actual",
        }
        with patch(
            "routes.money.actual_finance.create_transaction", return_value=canonical
        ) as write:
            response = self.client.post(
                "/api/money/transactions",
                json={
                    "account_id": "legacy-account",
                    "date": "2026-07-18",
                    "amount": -4,
                    "category": " dining ",
                    "payee": " Market Hall ",
                    "tags": "Manual,weekly",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        values = write.call_args.args[1]
        self.assertEqual(values["category"], "dining")
        self.assertEqual(values["payee"], "Market Hall")
        self.assertEqual(values["tags"], "manual,weekly")
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_route_authority_guards_never_span_a_fastapi_dependency_yield(self):
        from routes import money as money_routes
        from routes import subscriptions as subscription_routes

        self.assertFalse(inspect.isgeneratorfunction(money_routes._money_authority))
        self.assertFalse(inspect.isgeneratorfunction(money_routes._money_preflight))
        self.assertFalse(
            inspect.isgeneratorfunction(subscription_routes._subscription_write_authority)
        )
        self.assertFalse(
            inspect.isgeneratorfunction(subscription_routes._subscription_write_preflight)
        )
        self.assertTrue(money_routes.router.routes)
        self.assertTrue(
            all(
                getattr(route.endpoint, "_alles_authority_same_thread", False)
                for route in money_routes.router.routes
            )
        )
        guarded_subscription_paths = {
            "/subscriptions",
            "/subscriptions/{sid}",
            "/subscriptions/{sid}/paid",
            "/subscriptions/{sid}/payments/undo",
        }
        for route in subscription_routes.router.routes:
            if route.path in guarded_subscription_paths and route.methods & {
                "POST",
                "PATCH",
                "DELETE",
            }:
                self.assertTrue(
                    getattr(route.endpoint, "_alles_authority_same_thread", False),
                    (route.path, route.methods),
                )

    def test_authority_checks_refresh_a_cached_ledger_state(self):
        setup = self.db()
        state = setup.get(FinanceLedgerState, "primary")
        state.mode = "alles"
        state.legacy_read_only = False
        setup.commit()
        setup.close()

        stale = self.db()
        self.assertFalse(actual_finance.is_canonical(stale))
        cutover = self.db()
        state = cutover.get(FinanceLedgerState, "primary")
        state.mode = "actual"
        state.legacy_read_only = True
        cutover.commit()
        cutover.close()

        self.assertTrue(actual_finance.is_canonical(stale))
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "read-only"):
            actual_finance.require_legacy_writable(stale)
        stale.close()

    def test_money_route_acquires_and_releases_the_rlock_in_one_worker_thread(self):
        canonical = {
            "id": "actual-thread-guard",
            "account_id": "legacy-account",
            "date": "2026-07-18",
            "amount": -1.0,
            "category": "food",
            "payee": "market",
            "notes": "",
            "transfer_id": "",
            "tags": "",
            "receipt_id": "",
            "cleared": False,
            "split": False,
            "original_amount_text": "-1",
            "original_currency_code": "CAD",
            "base_amount_text": "-1",
            "base_currency_code": "CAD",
            "import_identity": "alles:actual:thread-guard",
            "import_batch_id": "",
            "import_source": "actual",
        }
        lock = _ThreadOwnedTrackingLock()
        with (
            patch("services.actual_finance.AUTHORITY_LOCK", lock),
            patch("routes.money.actual_finance.create_transaction", return_value=canonical),
        ):
            response = self.client.post(
                "/api/money/transactions",
                json={
                    "account_id": "legacy-account",
                    "date": "2026-07-18",
                    "amount": -1,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(lock.depth, 0)
        self.assertEqual(len(lock.completed_threads), 2)

    def test_subscription_guard_releases_the_rlock_in_its_worker_thread(self):
        lock = _ThreadOwnedTrackingLock()
        with patch("services.actual_finance.AUTHORITY_LOCK", lock):
            response = self.client.post("/api/subscriptions", json={})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(lock.depth, 0)
        self.assertEqual(len(lock.completed_threads), 1)

    def test_canonical_account_default_uses_base_without_accepting_explicit_dollar(self):
        canonical = {
            "id": "actual-account",
            "name": "Checking",
            "kind": "checking",
            "currency": "CAD",
            "opening": 0,
            "color": "accent",
            "archived": False,
            "low_balance": 0,
            "balance": 0,
        }
        with patch("routes.money.actual_finance.create_account", return_value=canonical) as write:
            response = self.client.post("/api/money/accounts", json={"name": "Checking"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("currency", write.call_args.args[1])

        ambiguous = self.client.post(
            "/api/money/accounts",
            json={"name": "Ambiguous", "currency": "$"},
        )
        self.assertEqual(ambiguous.status_code, 409, ambiguous.text)
        self.assertIn("reviewed currency code", ambiguous.text)

    def test_legacy_only_money_and_subscription_mutations_fail_closed(self):
        budget = self.client.post("/api/money/budgets", json={"category": "food", "limit_amt": 10})
        subscription = self.client.post(
            "/api/subscriptions",
            json={
                "name": "new sub",
                "price": 10,
                "currency": "CAD",
                "cycle": "monthly",
                "next_due": "2026-08-01",
            },
        )
        self.assertEqual(budget.status_code, 503, budget.text)
        self.assertEqual(subscription.status_code, 409, subscription.text)
        db = self.db()
        self.assertEqual(db.query(Subscription).count(), 1)
        db.close()

    def test_canonical_budget_routes_delegate_to_actual(self):
        canonical = {
            "id": "actual-budget:2026-07:food-id",
            "actual_id": "food-id",
            "category": "food",
            "tag": "",
            "limit_amt": 10.0,
        }
        with patch("routes.money.actual_finance.set_budget", return_value=canonical) as write:
            created = self.client.post(
                "/api/money/budgets", json={"category": "food", "limit_amt": 10}
            )
        self.assertEqual(created.status_code, 200, created.text)
        write.assert_called_once()
        tag_budget = {
            "id": "actual-tag-budget:coffee",
            "actual_id": "sidecar:tag_budget:coffee",
            "category": "",
            "tag": "coffee",
            "limit_amt": 8.0,
        }
        with patch(
            "routes.money.actual_finance.set_tag_budget", return_value=tag_budget
        ) as write_tag:
            created_tag = self.client.post(
                "/api/money/budgets", json={"tag": "Coffee", "limit_amt": 8}
            )
        self.assertEqual(created_tag.status_code, 200, created_tag.text)
        write_tag.assert_called_once()
        with patch("routes.money.actual_finance.clear_budget", return_value={"ok": True}) as clear:
            deleted = self.client.delete("/api/money/budgets/actual-budget-cap:food-id")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        clear.assert_called_once()
        with patch("routes.money.actual_finance.clear_budget", return_value={"ok": True}) as clear:
            rejected = self.client.delete("/api/money/budgets/actual-budget:2026-07:food-id")
        self.assertEqual(rejected.status_code, 409, rejected.text)
        clear.assert_not_called()
        db = self.db()
        self.assertEqual(db.query(Budget).count(), 0)
        db.close()

    def test_canonical_envelope_assignment_route_uses_actual_without_legacy_write(self):
        canonical = {
            "category_id": "food-id",
            "category": "food",
            "month": "2026-09",
            "assigned": 25.0,
        }
        with patch(
            "routes.money.actual_finance.set_envelope_assignment", return_value=canonical
        ) as write:
            response = self.client.put(
                "/api/money/envelope/assign",
                json={
                    "category_id": "food-id",
                    "month": "2026-09",
                    "amount": 25,
                    "expected_amount": 0,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), canonical)
        self.assertEqual(write.call_args.args[1:5], ("2026-09", "food-id", 25.0, 0.0))
        db = self.db()
        self.assertEqual(db.query(BudgetAssignment).count(), 0)
        db.close()

    def test_authority_lookup_errors_block_legacy_writes(self):
        db = self.db()
        with patch(
            "services.actual_finance.sa_inspect",
            side_effect=SQLAlchemyError("authority unavailable"),
        ):
            with self.assertRaisesRegex(actual_finance.ActualFinanceError, "writes are blocked"):
                actual_finance.require_legacy_writable(db)
        db.close()

    def test_managed_actual_failures_are_typed_as_retryable_outages(self):
        def unavailable(_payload, timeout):
            self.assertEqual(timeout, 180)
            raise managed_actual.ManagedActualError("Actual is unavailable")

        db = self.db()
        with self.assertRaisesRegex(actual_finance.ActualFinanceUnavailable, "unavailable"):
            actual_finance.inspect(db, bridge_request=unavailable)
        db.close()

    def test_subscription_history_remains_readable_while_schedule_writes_fail_closed(self):
        db = self.db()
        sub = Subscription(
            name="frozen subscription",
            price=5,
            currency="CAD",
            cycle="monthly",
            next_due="2026-08-01",
            active=True,
            category="legacy category",
            original_price_text="5",
            original_currency_code="CAD",
            base_price_text="5",
            base_currency_code="CAD",
            fx_rate_text="1",
            fx_source="legacy_identity",
        )
        db.add(sub)
        db.commit()
        sid = sub.id
        db.close()
        canonical = {
            "id": sid,
            "actual_id": "actual-subscription",
            "name": f"Alles subscription: frozen subscription [{sid[:8]}]",
            "price": 6,
            "currency": "CAD",
            "cycle": "monthly",
            "cycle_days": 30,
            "next_due": "2026-08-01",
            "active": True,
            "account_id": "",
            "metadata": {
                "original_price_text": "25",
                "original_currency_code": "CNY",
                "base_price_text": "5",
                "base_currency_code": "CAD",
                "rate_text": "0.2",
                "rate_date": "2026-07-18",
                "source": "owner_review",
                "category": "software",
            },
        }
        with (
            patch(
                "routes.subscriptions.actual_finance.subscription_schedules",
                return_value=[canonical],
            ),
            patch(
                "routes.subscriptions.actual_finance.subscription_payments",
                return_value={sid: []},
            ),
            patch("routes.subscriptions.actual_finance.transactions", return_value=[]),
        ):
            listed = self.client.get("/api/subscriptions")
            self.assertEqual(listed.status_code, 200, listed.text)
            evidence = listed.json()["subscriptions"][0]
            self.assertEqual(evidence["original_price_text"], "25")
            self.assertEqual(evidence["original_currency_code"], "CNY")
            self.assertEqual(evidence["base_price_text"], "5")
            self.assertEqual(evidence["base_currency_code"], "CAD")
            self.assertEqual(evidence["canonical_base_price_text"], "6")
            self.assertEqual(evidence["canonical_base_currency_code"], "CAD")
            self.assertEqual(evidence["fx_rate_text"], "0.2")
            self.assertEqual(evidence["fx_rate_date"], "2026-07-18")
            self.assertEqual(evidence["fx_source"], "owner_review")
            self.assertEqual(evidence["category"], "software")
            self.assertEqual(evidence["price"], 6)
            self.assertEqual(evidence["monthly_cost"], 6)
            self.assertEqual(listed.json()["summary"]["monthly_total"], 6)
            analytics = self.client.get("/api/subscriptions/analytics")
            self.assertEqual(analytics.status_code, 200, analytics.text)
            self.assertEqual(analytics.json()["monthly_total"], 6)
            for path in (
                "/api/subscriptions",
                "/api/subscriptions/unused",
                "/api/subscriptions/trials",
                "/api/subscriptions/duplicates",
                "/api/subscriptions/analytics",
                "/api/subscriptions/upcoming",
                "/api/subscriptions/forecast",
                "/api/subscriptions/detect",
                f"/api/subscriptions/{sid}/payments",
                f"/api/subscriptions/{sid}/price-history",
            ):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200, response.text)
        for method, path, payload in (
            ("post", "/api/subscriptions", {"name": "new", "next_due": "2026-08-01"}),
            ("patch", f"/api/subscriptions/{sid}", {"name": "changed"}),
            ("post", f"/api/subscriptions/{sid}/paid", None),
            ("post", f"/api/subscriptions/{sid}/payments/undo", None),
            ("delete", f"/api/subscriptions/{sid}", None),
        ):
            with self.subTest(method=method, path=path):
                response = self.client.request(method.upper(), path, json=payload)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("read-only", response.text)

    def test_canonical_only_subscription_reads_exact_schedule_history(self):
        canonical = {
            "id": "actual-only-subscription",
            "actual_id": "actual-only-schedule",
            "name": "actual only",
            "price": 6,
            "currency": "CAD",
            "cycle": "monthly",
            "cycle_days": 30,
            "next_due": "2026-08-01",
            "active": True,
            "account_id": "",
            "metadata": {},
        }
        canonical_payment = {
            "id": "actual-payment:actual-transaction",
            "date": "2026-07-01",
            "amount": 6.0,
            "txn_id": "actual-transaction",
        }
        with (
            patch(
                "routes.subscriptions.actual_finance.subscription_schedules",
                return_value=[canonical],
            ),
            patch(
                "routes.subscriptions.actual_finance.subscription_payments",
                return_value={"actual-only-subscription": [canonical_payment]},
            ),
        ):
            payments = self.client.get("/api/subscriptions/actual-only-subscription/payments")
            prices = self.client.get("/api/subscriptions/actual-only-subscription/price-history")
            missing = self.client.get("/api/subscriptions/missing/payments")
        self.assertEqual(payments.status_code, 200, payments.text)
        self.assertEqual(payments.json(), [{**canonical_payment, "currency": "CAD"}])
        self.assertEqual(prices.status_code, 200, prices.text)
        self.assertEqual(prices.json(), [])
        self.assertEqual(missing.status_code, 404, missing.text)

    def test_legacy_payment_history_uses_reviewed_base_currency_after_cutover(self):
        sid = "legacy-fx-subscription"
        db = self.db()
        db.add(
            Subscription(
                id=sid,
                name="foreign plan",
                price=10,
                currency="USD",
                next_due="2026-08-01",
            )
        )
        db.add(
            SubPayment(
                id="legacy-fx-payment",
                sub_id=sid,
                date="2026-07-01",
                amount=10,
                original_amount_text="10.00",
                original_currency_code="USD",
                base_amount_text="13.50",
                base_currency_code="CAD",
                fx_rate_text="1.35",
                fx_source="owner_review",
            )
        )
        db.commit()
        db.close()
        with (
            patch(
                "routes.subscriptions._subscription_exists",
                return_value=True,
            ),
            patch(
                "routes.subscriptions.actual_finance.subscription_payments",
                return_value={sid: []},
            ),
        ):
            response = self.client.get(f"/api/subscriptions/{sid}/payments")

        self.assertEqual(response.status_code, 200, response.text)
        payment = response.json()[0]
        self.assertEqual(payment["amount"], 13.5)
        self.assertEqual(payment["currency"], "CAD")
        self.assertEqual(payment["original_amount_text"], "10.00")
        self.assertEqual(payment["original_currency_code"], "USD")

    def test_migrated_subscription_payment_is_not_counted_twice_after_cutover(self):
        sid = "merged-payment-subscription"
        db = self.db()
        db.add(
            Subscription(
                id=sid,
                name="merged plan",
                price=6,
                currency="CAD",
                next_due="2026-08-01",
                active=True,
            )
        )
        db.add(
            SubPayment(
                id="legacy-payment",
                sub_id=sid,
                date="2026-07-01",
                amount=6,
                txn_id="legacy-transaction",
                base_amount_text="6",
                base_currency_code="CAD",
            )
        )
        db.commit()
        db.close()
        schedule = {
            "id": sid,
            "actual_id": "actual-schedule",
            "name": "merged plan",
            "price": 6,
            "currency": "CAD",
            "cycle": "monthly",
            "cycle_days": 30,
            "next_due": "2026-08-01",
            "active": True,
            "account_id": "",
            "metadata": {},
        }
        canonical_payment = {
            "id": "actual-payment:actual-transaction",
            "date": "2026-07-01",
            "amount": 6.0,
            "txn_id": "legacy-transaction",
            "source_payment_id": "legacy-payment",
        }
        with (
            patch(
                "routes.subscriptions.actual_finance.subscription_schedules",
                return_value=[schedule],
            ),
            patch(
                "routes.subscriptions.actual_finance.subscription_payments",
                return_value={sid: [canonical_payment]},
            ),
            patch("routes.subscriptions._subscription_exists", return_value=True),
        ):
            overview = self.client.get("/api/subscriptions?advance=false")
            history = self.client.get(f"/api/subscriptions/{sid}/payments")

        self.assertEqual(overview.status_code, 200, overview.text)
        listed = next(item for item in overview.json()["subscriptions"] if item["id"] == sid)
        self.assertEqual(listed["paid_count"], 1)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(len(history.json()), 1)
        self.assertEqual(history.json()[0]["id"], canonical_payment["id"])
        self.assertNotIn("source_payment_id", history.json()[0])

    def test_actual_transaction_read_does_not_auto_post_legacy_recurring(self):
        with patch("routes.money.actual_finance.transactions", return_value=[]):
            response = self.client.get("/api/money/transactions")
        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        self.assertEqual(db.query(RecurringTxn).one().next_date, "2020-01-01")
        db.close()

    def test_canonical_reporting_reads_translate_actual_outages_to_service_unavailable(self):
        transaction_paths = (
            "/api/money/transactions/export.csv",
            "/api/money/transactions/recurring-detect",
            "/api/money/report",
            "/api/money/report/export.csv",
        )
        for path in transaction_paths:
            with (
                self.subTest(path=path),
                patch(
                    "routes.money.actual_finance.transactions",
                    side_effect=actual_finance.ActualFinanceUnavailable("Actual is unavailable"),
                ),
            ):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertIn("Actual is unavailable", response.text)
        with patch(
            "routes.money.actual_finance.accounts",
            side_effect=actual_finance.ActualFinanceUnavailable("Actual is unavailable"),
        ):
            response = self.client.get("/api/money/networth-base?base=CAD")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("Actual is unavailable", response.text)

    def test_canonical_networth_defaults_to_the_reviewed_base(self):
        canonical = [
            {
                "id": "account-1",
                "name": "Checking",
                "balance": 12.5,
                "archived": False,
            }
        ]
        with patch("routes.money.actual_finance.accounts", return_value=canonical) as read:
            response = self.client.get("/api/money/networth-base")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["base"], "CAD")
        self.assertEqual(response.json()["net_worth"], 12.5)
        read.assert_called_once()

        rejected = self.client.get("/api/money/networth-base?base=USD")
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertIn("reviewed base currency", rejected.text)

    def test_canonical_networth_history_uses_one_snapshot_and_month_end_values(self):
        db = self.db()
        db.add(
            Transaction(
                account_id="legacy-account",
                date="2026-04-01",
                amount=999,
                payee="frozen legacy row",
            )
        )
        db.commit()
        db.close()
        actual = {"source": "one snapshot"}
        accounts = [
            {"id": "open-a", "opening": 100.0, "archived": False},
            {"id": "open-b", "opening": 25.0, "archived": False},
            {"id": "closed", "opening": 300.0, "archived": True},
        ]
        transactions = [
            {"account_id": "open-a", "date": "2026-03-30", "amount": -10.0},
            {"account_id": "open-a", "date": "2026-04-15", "amount": 50.0},
            {"account_id": "open-b", "date": "2026-04-18", "amount": -5.0},
            {"account_id": "closed", "date": "2026-04-18", "amount": 5.0},
            {"account_id": "closed", "date": "2026-04-19", "amount": 90.0},
            {"account_id": "open-a", "date": "2026-05-01", "amount": -3.0},
        ]
        with (
            patch("routes.money.actual_finance.inspect", return_value=actual) as inspect,
            patch("routes.money.actual_finance.accounts", return_value=accounts) as read_accounts,
            patch(
                "routes.money.actual_finance.transactions", return_value=transactions
            ) as read_transactions,
        ):
            response = self.client.get("/api/money/networth-history?months=3&as_of=2026-05-12")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            [
                {"month": "2026-03", "net_worth": 115.0},
                {"month": "2026-04", "net_worth": 160.0},
                {"month": "2026-05", "net_worth": 157.0},
            ],
        )
        inspect.assert_called_once()
        self.assertIs(read_accounts.call_args.kwargs["actual"], actual)
        self.assertIs(read_transactions.call_args.kwargs["actual"], actual)

    def test_canonical_networth_history_reports_an_actual_outage(self):
        with patch(
            "routes.money.actual_finance.inspect",
            side_effect=actual_finance.ActualFinanceUnavailable("Actual is unavailable"),
        ):
            response = self.client.get("/api/money/networth-history?months=6")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("Actual is unavailable", response.text)

    def test_non_ledger_finance_records_remain_writable_after_cutover(self):
        requests = (
            ("/api/money/holdings", {"symbol": "ALLES", "qty": 1, "price": 2}),
            ("/api/money/goals", {"name": "rainy day", "target": 100}),
            ("/api/money/watches", {"kind": "payee", "value": "market"}),
            ("/api/money/rules", {"match": "market", "category": "food"}),
            ("/api/money/tag-rules", {"match": "market", "tags": "weekly"}),
        )
        for path, payload in requests:
            with self.subTest(path=path):
                response = self.client.post(path, json=payload)
                self.assertEqual(response.status_code, 200, response.text)
        for path in (
            "/api/money/rules/apply",
            "/api/money/tag-rules/apply",
            "/api/money/transactions/import.csv",
            "/api/money/transactions/import-ofx",
        ):
            with self.subTest(path=path):
                response = self.client.post(path, json={})
                self.assertEqual(response.status_code, 409, response.text)
        recurring = self.client.post(
            "/api/money/recurring",
            json={"account_id": "legacy-account", "next_date": "2026-10-01"},
        )
        self.assertEqual(recurring.status_code, 409, recurring.text)
        self.assertIn("request_id", recurring.text)
        for method, path in (
            ("put", "/api/money/transactions/legacy/splits"),
            ("put", "/api/money/envelope/target"),
            ("patch", "/api/money/recurring/legacy"),
            ("delete", "/api/money/recurring/legacy"),
        ):
            with self.subTest(method=method, path=path):
                response = (
                    self.client.delete(path)
                    if method == "delete"
                    else getattr(self.client, method)(path, json={})
                )
                self.assertEqual(response.status_code, 409, response.text)

    def test_canonical_budget_reads_and_summary_use_actual_only(self):
        transactions = [
            {
                "date": "2026-07-18",
                "amount": -12.5,
                "category": "food",
                "tags": "coffee,weekly",
                "transfer_id": "",
            },
            {
                "date": "2026-07-19",
                "amount": -3.0,
                "category": "transport",
                "tags": "weekly",
                "transfer_id": "",
            },
        ]
        actual_budget = {
            "id": "actual-budget:2026-07:food-id",
            "actual_id": "food-id",
            "category": "food",
            "tag": "",
            "limit_amt": 40.0,
        }
        tag_budget = {
            "id": "actual-tag-budget:coffee",
            "actual_id": "sidecar:tag_budget:coffee",
            "category": "",
            "tag": "coffee",
            "limit_amt": 20.0,
        }
        with (
            patch("routes.money.actual_finance.inspect", return_value={}),
            patch("routes.money.actual_finance.accounts", return_value=[]),
            patch("routes.money.actual_finance.transactions", return_value=transactions),
            patch("routes.money.actual_finance.budgets", return_value=[actual_budget, tag_budget]),
        ):
            response = self.client.get("/api/money/summary?month=2026-07")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["ledger"], "actual")
        budgets = {row["category"]: row for row in response.json()["budgets"]}
        self.assertEqual(budgets["food"]["spent"], 12.5)
        self.assertEqual(budgets["food"]["limit"], 40.0)
        self.assertEqual(budgets["coffee"]["spent"], 12.5)
        self.assertEqual(budgets["coffee"]["limit"], 20.0)
        with patch("routes.money.actual_finance.budgets", return_value=[actual_budget, tag_budget]):
            listed = self.client.get("/api/money/budgets")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json(), [actual_budget, tag_budget])

    def test_canonical_recurring_reads_current_actual_schedules_without_legacy_posting(self):
        db = self.db()
        legacy_id = db.query(RecurringTxn.id).one()[0]
        db.add_all(
            [
                ActualEntityLink(
                    run_id="run-route",
                    entity_kind="account",
                    source_id="legacy-account",
                    actual_id="actual-account",
                    metadata_json="{}",
                ),
                ActualEntityLink(
                    run_id="run-route",
                    entity_kind="recurring",
                    source_id=legacy_id,
                    actual_id="actual-rent",
                    metadata_json='{"category":"housing","notes":"first of month"}',
                ),
                ActualEntityLink(
                    run_id="run-route",
                    entity_kind="subscription",
                    source_id="legacy-subscription",
                    actual_id="actual-subscription",
                    metadata_json="{}",
                ),
            ]
        )
        db.commit()
        db.close()
        actual = {
            "payees": [{"id": "rent-payee", "name": "rent"}],
            "schedules": [
                {
                    "id": "actual-rent",
                    "name": f"Alles recurring: rent [{legacy_id[:8]}]",
                    "account": "actual-account",
                    "payee": "rent-payee",
                    "amount": -25000,
                    "amountOp": "is",
                    "posts_transaction": True,
                    "next_date": "2026-10-01",
                    "date": {"start": "2026-09-01", "frequency": "monthly", "interval": 1},
                },
                {
                    "id": "native-range",
                    "name": "variable utilities",
                    "account": "actual-account",
                    "amount": {"num1": -8000, "num2": -12000},
                    "amountOp": "isbetween",
                    "posts_transaction": True,
                    "next_date": "2026-10-15",
                    "date": {"start": "2026-09-15", "frequency": "monthly", "interval": 2},
                },
                {
                    "id": "paused-native",
                    "name": "paused salary",
                    "account": "actual-account",
                    "amount": 90000,
                    "posts_transaction": True,
                    "completed": True,
                    "date": {"start": "2026-09-15", "frequency": "weekly", "interval": 1},
                },
                {
                    "id": "actual-subscription",
                    "name": "subscription",
                    "amount": -999,
                    "posts_transaction": True,
                },
                {
                    "id": "manual",
                    "name": "manual reminder",
                    "posts_transaction": False,
                },
            ],
        }
        with patch("routes.money.actual_finance.inspect", return_value=actual) as inspect:
            response = self.client.get("/api/money/recurring")
        self.assertEqual(response.status_code, 200, response.text)
        inspect.assert_called_once()
        rows = {row["id"]: row for row in response.json()}
        self.assertEqual(set(rows), {legacy_id, "native-range", "paused-native"})
        self.assertEqual(rows[legacy_id]["account_id"], "legacy-account")
        self.assertEqual(rows[legacy_id]["payee"], "rent")
        self.assertEqual(rows[legacy_id]["amount"], -250.0)
        self.assertEqual(rows[legacy_id]["category"], "housing")
        self.assertEqual(rows[legacy_id]["next_date"], "2026-10-01")
        self.assertEqual(rows["native-range"]["amount"], None)
        self.assertEqual(rows["native-range"]["amount_kind"], "range")
        self.assertEqual(rows["native-range"]["cycle"], "actual")
        self.assertFalse(rows["paused-native"]["active"])
        self.assertEqual(rows["paused-native"]["next_date"], "")
        db = self.db()
        self.assertEqual(db.query(RecurringTxn).one().next_date, "2020-01-01")
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_canonical_recurring_read_reports_actual_outage(self):
        with patch(
            "routes.money.actual_finance.inspect",
            side_effect=actual_finance.ActualFinanceUnavailable("Actual is unavailable"),
        ):
            response = self.client.get("/api/money/recurring")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("Actual is unavailable", response.text)

    def test_canonical_recurring_keeps_managed_paused_schedule_and_reads_its_posting_rule(self):
        db = self.db()
        legacy_id = db.query(RecurringTxn.id).one()[0]
        db.add(
            ActualEntityLink(
                run_id="run-route",
                entity_kind="recurring",
                source_id=legacy_id,
                actual_id="paused-schedule",
                metadata_json='{"category":"old housing","notes":"old note","posting_rule_version":1}',
            )
        )
        db.commit()
        db.close()
        actual = {
            "categories": [{"id": "housing-id", "name": "housing"}],
            "schedules": [
                {
                    "id": "paused-schedule",
                    "name": f"Alles recurring: rent [{legacy_id[:8]}]",
                    "account": "actual-account",
                    "amount": -2000,
                    "amountOp": "is",
                    "date": {"start": "2026-10-01", "frequency": "monthly", "interval": 1},
                    "next_date": "2026-10-01",
                    "completed": False,
                    "posts_transaction": False,
                    "posting": {"guarded": True, "category": "housing-id", "notes": "new note"},
                }
            ],
        }
        with patch("routes.money.actual_finance.inspect", return_value=actual):
            response = self.client.get("/api/money/recurring")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)
        row = response.json()[0]
        self.assertEqual(row["id"], legacy_id)
        self.assertFalse(row["active"])
        self.assertEqual(row["category"], "housing")
        self.assertEqual(row["notes"], "new note")

        actual["schedules"][0]["posting"]["guarded"] = False
        with patch("routes.money.actual_finance.inspect", return_value=actual):
            unsafe = self.client.get("/api/money/recurring")
        self.assertEqual(unsafe.status_code, 409, unsafe.text)
        self.assertIn("posting rule is missing", unsafe.text)

    def test_old_recurring_schedule_repair_retries_a_lost_provider_response(self):
        db = self.db()
        snapshot = {
            "schedules": [
                {
                    "kind": "recurring",
                    "id": "legacy-rent",
                    "name": "old rent",
                    "account_id": "legacy-account",
                    "payee": "landlord",
                    "amount_minor": -500,
                    "next_date": "2026-10-01",
                    "cycle": "monthly",
                    "cycle_days": 30,
                    "active": True,
                    "posts_transaction": True,
                    "metadata": {"category": "housing", "notes": "lease"},
                }
            ]
        }
        path = actual_migration._write_snapshot("run-route", snapshot)
        db.add(
            ActualMigrationRun(
                id="run-route",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256=actual_migration.snapshot_sha256(snapshot),
                snapshot_path=str(path),
            )
        )
        link = ActualEntityLink(
            run_id="run-route",
            entity_kind="recurring",
            source_id="legacy-rent",
            actual_id="actual-rent",
            metadata_json='{"category":"housing","notes":"lease"}',
        )
        db.add(link)
        db.add(
            ActualEntityLink(
                run_id="run-route",
                entity_kind="account",
                source_id="legacy-account",
                actual_id="actual-account",
                metadata_json="{}",
            )
        )
        db.commit()
        actual = {
            "accounts": [{"id": "actual-account", "name": "checking"}],
            "transactions": [],
            "payees": [{"id": "landlord-id", "name": "landlord"}],
            "categories": [{"id": "housing-id", "name": "housing", "is_income": False}],
            "category_groups": [],
            "schedules": [
                {
                    "id": "actual-rent",
                    "name": "old rent",
                    "account": "actual-account",
                    "payee": "landlord-id",
                    "amount": -500,
                    "amountOp": "is",
                    "date": {"start": "2026-10-01", "frequency": "monthly", "interval": 1},
                    "next_date": "2026-10-01",
                    "completed": False,
                    "posts_transaction": True,
                    "posting": {"pristine": True, "guarded": False},
                }
            ],
            "budget_months": [],
        }
        backups = []
        writes = []
        supported = {"repair_recurring_schedule": 1}

        def backup():
            backups.append(True)
            return {"ok": True, "backup_id": "pre-repair"}

        def bridge(payload, *, timeout):
            if payload["command"] == "capabilities":
                return supported
            if payload["command"] == "inspect":
                return actual
            self.assertEqual(payload["action"], "repair_recurring_schedule")
            writes.append(payload)
            self.assertEqual(
                json.loads(link.metadata_json)["_update_intent"]["backup_id"], "pre-repair"
            )
            row = actual["schedules"][0]
            row["posting"] = {
                "pristine": False,
                "guarded": True,
                "category": "housing-id",
                "notes": "lease",
            }
            if len(writes) == 1:
                row["posts_transaction"] = False
                raise managed_actual.ManagedActualError("response lost")
            row["posts_transaction"] = True
            return {"id": "actual-rent"}

        supported.clear()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "update managed Actual"):
            actual_finance.repair_recurring_schedule(
                db, "legacy-rent", "housing-id", bridge_request=bridge, backup_fn=backup
            )
        self.assertFalse(backups)
        supported["repair_recurring_schedule"] = 1
        actual["schedules"][0]["posting"]["pristine"] = False
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "rule changed"):
            actual_finance.repair_recurring_schedule(
                db, "legacy-rent", "housing-id", bridge_request=bridge, backup_fn=backup
            )
        actual["schedules"][0]["posting"]["pristine"] = True
        actual["schedules"][0]["amount"] = -501
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "changed since cutover"):
            actual_finance.repair_recurring_schedule(
                db, "legacy-rent", "housing-id", bridge_request=bridge, backup_fn=backup
            )
        actual["schedules"][0]["amount"] = -500
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "spending category"):
            actual_finance.repair_recurring_schedule(
                db, "legacy-rent", "missing-id", bridge_request=bridge, backup_fn=backup
            )
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "verified Actual backup"):
            actual_finance.repair_recurring_schedule(
                db, "legacy-rent", "housing-id", bridge_request=bridge, backup_fn=lambda: None
            )
        self.assertFalse(backups)
        self.assertFalse(writes)

        with self.assertRaises(actual_finance.ActualFinanceUnavailable):
            actual_finance.repair_recurring_schedule(
                db, "legacy-rent", "housing-id", bridge_request=bridge, backup_fn=backup
            )
        self.assertEqual(len(backups), 1)
        pending = actual_finance.recurring_schedules(db, actual=actual)
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0]["repair_needed"])
        self.assertTrue(pending[0]["repair_pending"])
        self.assertEqual(pending[0]["repair_category_id"], "housing-id")
        self.assertFalse(pending[0]["active"])
        saved_pending = json.loads(link.metadata_json)
        for key, value in (("version", 2), ("posts_transaction", False)):
            altered = json.loads(json.dumps(saved_pending))
            altered["_update_intent"][key] = value
            link.metadata_json = json.dumps(altered)
            db.flush()
            with self.assertRaisesRegex(actual_finance.ActualFinanceError, "retry does not match"):
                actual_finance.repair_recurring_schedule(
                    db, "legacy-rent", "housing-id", bridge_request=bridge, backup_fn=backup
                )
        link.metadata_json = json.dumps(saved_pending)
        db.flush()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "retry does not match"):
            actual_finance.repair_recurring_schedule(
                db, "legacy-rent", "other-id", bridge_request=bridge, backup_fn=backup
            )
        result = actual_finance.repair_recurring_schedule(
            db, "legacy-rent", "housing-id", bridge_request=bridge, backup_fn=backup
        )
        self.assertEqual(len(backups), 1)
        self.assertFalse(writes[0]["allow_paused_retry"])
        self.assertTrue(writes[1]["allow_paused_retry"])
        self.assertEqual(result["id"], "legacy-rent")
        self.assertEqual(result["category"], "housing")
        self.assertEqual(result["notes"], "lease")
        self.assertFalse(result["repair_needed"])
        self.assertFalse(result["repair_pending"])
        saved = json.loads(link.metadata_json)
        self.assertNotIn("_update_intent", saved)
        self.assertEqual(saved["canonical_schedule"]["category_id"], "housing-id")
        self.assertEqual(link.actual_id, "actual-rent")
        link.metadata_json = json.dumps({**saved, "canonical_schedule": {"version": 2}})
        db.flush()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "repair record is invalid"):
            actual_finance.recurring_schedules(db, actual=actual)
        db.close()

    def test_canonical_recurring_repair_route_is_explicit(self):
        with patch(
            "routes.money.actual_finance.repair_recurring_schedule",
            return_value={"id": "legacy-rent"},
        ) as repair:
            response = self.client.post(
                "/api/money/recurring/legacy-rent/repair",
                json={"category_id": "housing-id"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"id": "legacy-rent"})
        self.assertEqual(repair.call_args.args[1:], ("legacy-rent", "housing-id"))

    def test_linked_recurring_pause_recovers_lost_response_without_new_schedule(self):
        db = self.db()
        snapshot = {
            "schedules": [
                {
                    "kind": "recurring",
                    "id": "legacy-rent",
                    "name": "Alles recurring: rent [legacy-r]",
                    "account_id": "legacy-account",
                    "payee": "landlord",
                    "amount_minor": -500,
                    "next_date": "2026-10-01",
                    "cycle": "monthly",
                    "cycle_days": 30,
                    "active": True,
                    "posts_transaction": True,
                    "metadata": {
                        "category": "housing",
                        "notes": "lease",
                        "posting_rule_version": 1,
                    },
                }
            ]
        }
        path = actual_migration._write_snapshot("run-route", snapshot)
        db.add(
            ActualMigrationRun(
                id="run-route",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256=actual_migration.snapshot_sha256(snapshot),
                snapshot_path=str(path),
            )
        )
        link = ActualEntityLink(
            run_id="run-route",
            entity_kind="recurring",
            source_id="legacy-rent",
            actual_id="actual-rent",
            metadata_json=json.dumps(snapshot["schedules"][0]["metadata"]),
        )
        db.add(link)
        db.add(
            ActualEntityLink(
                run_id="run-route",
                entity_kind="account",
                source_id="legacy-account",
                actual_id="actual-account",
                metadata_json="{}",
            )
        )
        db.commit()
        actual = {
            "accounts": [{"id": "actual-account", "name": "checking"}],
            "transactions": [],
            "payees": [{"id": "landlord-id", "name": "landlord"}],
            "categories": [{"id": "housing-id", "name": "housing", "is_income": False}],
            "category_groups": [],
            "schedules": [
                {
                    "id": "actual-rent",
                    "name": "Alles recurring: rent [legacy-r]",
                    "account": "actual-account",
                    "payee": "landlord-id",
                    "amount": -500,
                    "amountOp": "is",
                    "date": {"start": "2026-10-01", "frequency": "monthly", "interval": 1},
                    "next_date": "2026-10-01",
                    "completed": False,
                    "posts_transaction": True,
                    "posting": {"guarded": True, "category": "housing-id", "notes": "lease"},
                }
            ],
            "budget_months": [],
        }
        backups = []
        writes = []

        def backup():
            backups.append(True)
            return {"ok": True, "backup_id": f"pre-toggle-{len(backups)}"}

        def bridge(payload, *, timeout):
            if payload["command"] == "capabilities":
                return {"set_recurring_posting": 1}
            if payload["command"] == "inspect":
                return actual
            self.assertEqual(payload["action"], "set_recurring_posting")
            writes.append(payload)
            actual["schedules"][0]["posts_transaction"] = payload["active"]
            if len(writes) == 1:
                raise managed_actual.ManagedActualError("response lost")
            return {"id": "actual-rent", "posts_transaction": payload["active"]}

        actual["categories"].append(
            {"id": "another-housing", "name": "housing", "is_income": False}
        )
        self.assertFalse(actual_finance.recurring_schedules(db, actual=actual)[0]["manageable"])
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "ambiguous"):
            actual_finance.set_recurring_posting(
                db, "legacy-rent", False, bridge_request=bridge, backup_fn=backup
            )
        actual["categories"].pop()
        self.assertTrue(actual_finance.recurring_schedules(db, actual=actual)[0]["manageable"])
        with self.assertRaises(actual_finance.ActualFinanceUnavailable):
            actual_finance.set_recurring_posting(
                db, "legacy-rent", False, bridge_request=bridge, backup_fn=backup
            )
        pending = actual_finance.recurring_schedules(db, actual=actual)[0]
        self.assertTrue(pending["posting_pending"])
        self.assertFalse(pending["posting_target_active"])
        self.assertFalse(pending["active"])
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "pending"):
            actual_finance.set_recurring_posting(
                db, "legacy-rent", True, bridge_request=bridge, backup_fn=backup
            )
        paused = actual_finance.set_recurring_posting(
            db, "legacy-rent", False, bridge_request=bridge, backup_fn=backup
        )
        self.assertFalse(paused["active"])
        self.assertFalse(paused["posting_pending"])
        self.assertEqual(len(backups), 1)
        self.assertEqual(len(writes), 2)
        self.assertEqual(link.actual_id, "actual-rent")
        self.assertEqual(actual["schedules"][0]["next_date"], "2026-10-01")
        self.assertFalse(json.loads(link.metadata_json)["canonical_schedule"]["posts_transaction"])
        resumed = actual_finance.set_recurring_posting(
            db, "legacy-rent", True, bridge_request=bridge, backup_fn=backup
        )
        self.assertTrue(resumed["active"])
        self.assertEqual(len(backups), 2)
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "linked Alles schedule"):
            actual_finance.set_recurring_posting(
                db, "native-schedule", False, bridge_request=bridge, backup_fn=backup
            )
        saved_metadata = link.metadata_json
        malformed = json.loads(saved_metadata)
        malformed["canonical_schedule"]["posts_transaction"] = {}
        link.metadata_json = json.dumps(malformed)
        db.flush()
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "posting rule changed"):
            actual_finance.recurring_schedules(db, actual=actual)
        link.metadata_json = saved_metadata
        db.flush()
        actual["schedules"][0]["posting"]["guarded"] = False
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "posting rule"):
            actual_finance.set_recurring_posting(
                db, "legacy-rent", False, bridge_request=bridge, backup_fn=backup
            )
        self.assertEqual(len(backups), 2)
        db.close()

    def test_created_recurring_pause_preserves_its_restore_checkpoint(self):
        db = self.db()
        snapshot = {"schedules": []}
        path = actual_migration._write_snapshot("run-route", snapshot)
        db.add(
            ActualMigrationRun(
                id="run-route",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256=actual_migration.snapshot_sha256(snapshot),
                snapshot_path=str(path),
            )
        )
        db.add(
            ActualEntityLink(
                run_id="run-route",
                entity_kind="account",
                source_id="legacy-account",
                actual_id="actual-account",
                metadata_json="{}",
            )
        )
        source = {
            "kind": "recurring",
            "id": "created-rent",
            "name": "Alles recurring: rent [created-rent]",
            "account_id": "actual-account",
            "payee": "landlord",
            "amount_minor": -500,
            "next_date": "2026-10-01",
            "cycle": "monthly",
            "cycle_days": 30,
            "active": True,
            "posts_transaction": True,
        }
        link = ActualEntityLink(
            run_id="run-route",
            entity_kind="recurring",
            source_id="created-rent",
            actual_id="actual-rent",
            metadata_json=json.dumps(
                {
                    "canonical_schedule": {
                        "version": 2,
                        "source": source,
                        "payee_id": "landlord-id",
                        "category_id": "housing-id",
                        "notes": "lease",
                        "posts_transaction": True,
                    },
                    "_request_fingerprint": "a" * 64,
                }
            ),
        )
        db.add(link)
        db.commit()
        actual = {
            "accounts": [{"id": "actual-account", "name": "checking"}],
            "transactions": [],
            "payees": [{"id": "landlord-id", "name": "landlord"}],
            "categories": [{"id": "housing-id", "name": "housing", "is_income": False}],
            "category_groups": [],
            "schedules": [
                {
                    "id": "actual-rent",
                    "name": source["name"],
                    "account": "actual-account",
                    "payee": "landlord-id",
                    "amount": -500,
                    "amountOp": "is",
                    "date": {"start": "2026-10-01", "frequency": "monthly", "interval": 1},
                    "next_date": "2026-10-01",
                    "completed": False,
                    "posts_transaction": True,
                    "posting": {"guarded": True, "category": "housing-id", "notes": "lease"},
                }
            ],
            "budget_months": [],
        }
        writes = []

        def bridge(payload, *, timeout):
            if payload["command"] == "capabilities":
                return {"set_recurring_posting": 1}
            if payload["command"] == "inspect":
                return actual
            writes.append(payload)
            actual["schedules"][0]["posts_transaction"] = payload["active"]
            return {"id": "actual-rent", "posts_transaction": payload["active"]}

        rows = actual_finance.recurring_schedules(db, actual=actual)
        self.assertEqual(rows[0]["payee"], "landlord")
        self.assertTrue(rows[0]["manageable"])
        same_name = copy.deepcopy(actual)
        same_name["payees"].append({"id": "other-landlord", "name": "landlord"})
        same_name["schedules"][0]["payee"] = "other-landlord"
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "payee changed"):
            actual_finance.recurring_schedules(db, actual=same_name)
        paused = actual_finance.set_recurring_posting(
            db,
            "created-rent",
            False,
            bridge_request=bridge,
            backup_fn=lambda: {"ok": True, "backup_id": "before-created-pause"},
        )
        self.assertFalse(paused["active"])
        self.assertEqual(len(writes), 1)
        checkpoint = json.loads(link.metadata_json)["canonical_schedule"]
        self.assertEqual(checkpoint["version"], 2)
        self.assertEqual(checkpoint["source"], source)
        self.assertFalse(checkpoint["posts_transaction"])
        self.assertEqual(link.actual_id, "actual-rent")
        edited_source = {
            **source,
            "payee": "new landlord",
            "amount_minor": -600,
            "next_date": "2026-11-01",
            "cycle": "weekly",
            "cycle_days": 7,
        }
        actual["payees"].append({"id": "new-landlord-id", "name": "new landlord"})
        actual["schedules"][0].update(
            payee="new-landlord-id",
            amount=-600,
            date={"start": "2026-11-01", "frequency": "weekly", "interval": 1},
            next_date="2026-11-01",
        )
        link.metadata_json = json.dumps(
            {
                "canonical_schedule": {
                    "version": 3,
                    "source": edited_source,
                    "created_source": source,
                    "payee_id": "new-landlord-id",
                    "category_id": "housing-id",
                    "notes": "lease",
                    "posts_transaction": False,
                },
                "_request_fingerprint": "a" * 64,
            }
        )
        db.commit()
        edited = actual_finance.recurring_schedules(db, actual=actual)
        self.assertEqual(edited[0]["payee"], "new landlord")
        self.assertEqual(edited[0]["amount"], -6.0)
        resumed = actual_finance.set_recurring_posting(
            db,
            "created-rent",
            True,
            bridge_request=bridge,
            backup_fn=lambda: {"ok": True, "backup_id": "before-edited-resume"},
        )
        self.assertTrue(resumed["active"])
        edited_checkpoint = json.loads(link.metadata_json)["canonical_schedule"]
        self.assertEqual(edited_checkpoint["version"], 3)
        self.assertEqual(edited_checkpoint["source"], edited_source)
        self.assertEqual(edited_checkpoint["created_source"], source)
        db.close()

    def _recurring_edit_fixture(self):
        db = self.db()
        source_id = "00000000-0000-4000-8000-000000000042"
        snapshot = {"schedules": []}
        path = actual_migration._write_snapshot("run-route", snapshot)
        db.add(
            ActualMigrationRun(
                id="run-route",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256=actual_migration.snapshot_sha256(snapshot),
                snapshot_path=str(path),
            )
        )
        db.add(
            ActualEntityLink(
                run_id="run-route",
                entity_kind="account",
                source_id="legacy-account",
                actual_id="actual-account",
                metadata_json="{}",
            )
        )
        source = {
            "kind": "recurring",
            "id": source_id,
            "name": f"Alles recurring {source_id}",
            "account_id": "actual-account",
            "payee": "landlord",
            "amount_minor": -500,
            "next_date": "2026-10-01",
            "cycle": "monthly",
            "cycle_days": 30,
            "active": True,
            "posts_transaction": True,
        }
        link = ActualEntityLink(
            run_id="run-route",
            entity_kind="recurring",
            source_id=source_id,
            actual_id="actual-rent",
            metadata_json=json.dumps(
                {
                    "canonical_schedule": {
                        "version": 2,
                        "source": source,
                        "payee_id": "landlord-id",
                        "category_id": "housing-id",
                        "notes": "lease",
                        "posts_transaction": True,
                    },
                    "_request_fingerprint": "a" * 64,
                }
            ),
        )
        db.add(link)
        db.commit()
        actual = {
            "accounts": [
                {"id": "actual-account", "name": "checking", "closed": False},
                {"id": "new-account", "name": "savings", "closed": False},
            ],
            "transactions": [],
            "payees": [
                {"id": "landlord-id", "name": "landlord"},
                {"id": "new-payee-id", "name": "new landlord"},
            ],
            "categories": [
                {"id": "housing-id", "name": "housing", "is_income": False},
                {"id": "new-category-id", "name": "rent", "is_income": False},
            ],
            "category_groups": [],
            "schedules": [
                {
                    "id": "actual-rent",
                    "name": source["name"],
                    "rule": "rent-rule",
                    "account": "actual-account",
                    "payee": "landlord-id",
                    "amount": -500,
                    "amountOp": "is",
                    "date": {
                        "start": "2026-10-01",
                        "frequency": "monthly",
                        "interval": 1,
                        "endMode": "never",
                    },
                    "next_date": "2026-10-01",
                    "completed": False,
                    "posts_transaction": True,
                    "posting": {"guarded": True, "category": "housing-id", "notes": "lease"},
                }
            ],
            "budget_months": [],
        }
        values = {
            "account_id": "new-account",
            "payee_id": "new-payee-id",
            "amount": -6,
            "category_id": "new-category-id",
            "notes": "new lease",
            "cycle": "weekly",
            "cycle_days": 7,
            "next_date": "2026-11-05",
            "active": True,
        }
        return db, link, actual, values

    def test_recurring_edit_retries_partial_write_and_keeps_created_origin(self):
        db, link, actual, values = self._recurring_edit_fixture()
        original = copy.deepcopy(json.loads(link.metadata_json)["canonical_schedule"]["source"])
        writes = []

        def bridge(payload, *, timeout):
            if payload["command"] == "capabilities":
                return {"edit_recurring_schedule": 1}
            if payload["command"] == "inspect":
                return actual
            self.assertEqual(payload["action"], "edit_recurring_schedule")
            writes.append(payload)
            row = actual["schedules"][0]
            target = payload["target"]
            if len(writes) == 1:
                row.update(
                    account=target["account"],
                    payee=target["payee"],
                    amount=target["amount"],
                    date=target["date"],
                    next_date=values["next_date"],
                    posts_transaction=False,
                )
                raise managed_actual.ManagedActualError("lost provider response")
            row["posting"] = {
                "guarded": True,
                "category": target["category_id"],
                "notes": target["notes"],
            }
            row["posts_transaction"] = target["posts_transaction"]
            return {
                "id": row["id"],
                "payee_id": row["payee"],
                "posts_transaction": row["posts_transaction"],
            }

        with self.assertRaises(actual_finance.ActualFinanceUnavailable):
            actual_finance.edit_recurring_schedule(
                db,
                link.source_id,
                values,
                bridge_request=bridge,
                backup_fn=lambda: {"ok": True, "backup_id": "before-edit"},
            )
        pending = json.loads(link.metadata_json)["_update_intent"]
        self.assertEqual(pending["backup_id"], "before-edit")
        self.assertEqual(len(writes), 1)
        partial = actual_finance.recurring_schedules(db, actual=actual)
        self.assertTrue(partial[0]["edit_pending"])
        self.assertFalse(partial[0]["edit_needs_review"])
        self.assertFalse(partial[0]["manageable"])
        drift = copy.deepcopy(actual)
        drift["schedules"][0]["amount"] = -999
        self.assertTrue(
            actual_finance.recurring_schedules(db, actual=drift)[0]["edit_needs_review"]
        )
        missing = copy.deepcopy(actual)
        missing["schedules"] = []
        self.assertTrue(
            actual_finance.recurring_schedules(db, actual=missing)[0]["edit_needs_review"]
        )
        saved = actual["schedules"][0]
        actual["schedules"] = drift["schedules"]
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "provider review"):
            actual_finance.retry_recurring_edit(db, link.source_id, bridge_request=bridge)
        self.assertEqual(len(writes), 1)
        actual["schedules"] = [saved]
        edited = actual_finance.retry_recurring_edit(db, link.source_id, bridge_request=bridge)
        self.assertEqual(len(writes), 2)
        self.assertFalse(edited["edit_pending"])
        self.assertTrue(edited["manageable"])
        self.assertEqual(edited["amount"], -6.0)
        self.assertEqual(edited["account_id"], "new-account")
        self.assertEqual(edited["payee"], "new landlord")
        checkpoint = json.loads(link.metadata_json)["canonical_schedule"]
        self.assertEqual(checkpoint["version"], 3)
        self.assertEqual(checkpoint["created_source"], original)
        self.assertEqual(checkpoint["payee_id"], "new-payee-id")
        self.assertEqual(link.actual_id, "actual-rent")
        self.assertNotIn("_update_intent", json.loads(link.metadata_json))
        next_values = {**values, "amount": -7, "notes": "third lease", "next_date": "2026-11-12"}

        def second_bridge(payload, *, timeout):
            if payload["command"] == "capabilities":
                return {"edit_recurring_schedule": 1}
            if payload["command"] == "inspect":
                return actual
            target = payload["target"]
            actual["schedules"][0].update(
                amount=target["amount"],
                date=target["date"],
                next_date=next_values["next_date"],
                posting={
                    "guarded": True,
                    "category": target["category_id"],
                    "notes": target["notes"],
                },
            )
            return {
                "id": "actual-rent",
                "payee_id": target["payee"],
                "posts_transaction": target["posts_transaction"],
            }

        again = actual_finance.edit_recurring_schedule(
            db,
            link.source_id,
            next_values,
            bridge_request=second_bridge,
            backup_fn=lambda: {"ok": True, "backup_id": "before-second-edit"},
        )
        self.assertEqual(again["amount"], -7.0)
        second_checkpoint = json.loads(link.metadata_json)["canonical_schedule"]
        self.assertEqual(second_checkpoint["created_source"], original)
        self.assertEqual(second_checkpoint["source"]["amount_minor"], -700)
        db.close()

    def test_recurring_edit_invalid_target_never_takes_backup_or_writes(self):
        db, link, actual, values = self._recurring_edit_fixture()
        writes = []
        backups = []

        def bridge(payload, *, timeout):
            if payload["command"] == "capabilities":
                return {"edit_recurring_schedule": 1}
            if payload["command"] == "inspect":
                return actual
            writes.append(payload)
            raise AssertionError("unexpected provider write")

        for bad in (
            {**values, "payee_id": "missing"},
            {**values, "category_id": "missing"},
            {**values, "next_date": "2026-02-30"},
            {**values, "cycle": "monthly", "next_date": "2026-11-29"},
            {**values, "cycle": "yearly", "next_date": "2028-02-29"},
        ):
            with self.assertRaises(actual_finance.ActualFinanceError):
                actual_finance.edit_recurring_schedule(
                    db,
                    link.source_id,
                    bad,
                    bridge_request=bridge,
                    backup_fn=lambda: backups.append(True),
                )
        self.assertEqual(writes, [])
        self.assertEqual(backups, [])
        self.assertNotIn("_update_intent", json.loads(link.metadata_json))
        db.close()

    def test_repaired_cutover_recurring_edit_preserves_snapshot_origin(self):
        db, link, actual, values = self._recurring_edit_fixture()
        created = json.loads(link.metadata_json)["canonical_schedule"]["source"]
        snapshot = {
            "schedules": [
                {
                    **created,
                    "account_id": "legacy-account",
                    "metadata": {},
                }
            ]
        }
        path = actual_migration._write_snapshot("run-route", snapshot)
        run = db.get(ActualMigrationRun, "run-route")
        run.snapshot_path = str(path)
        run.snapshot_sha256 = actual_migration.snapshot_sha256(snapshot)
        link.metadata_json = json.dumps(
            {
                "canonical_schedule": {
                    "version": 1,
                    "category_id": "housing-id",
                    "notes": "lease",
                    "posts_transaction": True,
                }
            }
        )
        db.commit()

        def bridge(payload, *, timeout):
            if payload["command"] == "capabilities":
                return {"edit_recurring_schedule": 1}
            if payload["command"] == "inspect":
                return actual
            self.assertEqual(payload["action"], "edit_recurring_schedule")
            row = actual["schedules"][0]
            target = payload["target"]
            row.update(
                account=target["account"],
                payee=target["payee"],
                amount=target["amount"],
                date=target["date"],
                next_date=values["next_date"],
                posts_transaction=target["posts_transaction"],
                posting={
                    "guarded": True,
                    "category": target["category_id"],
                    "notes": target["notes"],
                },
            )
            return {
                "id": row["id"],
                "payee_id": row["payee"],
                "posts_transaction": row["posts_transaction"],
            }

        edited = actual_finance.edit_recurring_schedule(
            db,
            link.source_id,
            values,
            bridge_request=bridge,
            backup_fn=lambda: {"ok": True, "backup_id": "before-old-edit"},
        )
        self.assertEqual(edited["payee"], "new landlord")
        checkpoint = json.loads(link.metadata_json)["canonical_schedule"]
        self.assertEqual(checkpoint["version"], 3)
        self.assertNotIn("created_source", checkpoint)
        self.assertEqual(checkpoint["source"]["account_id"], "new-account")
        actual_migration.schedule_repair_baseline(db, link, actual)
        db.close()

    def test_canonical_recurring_edit_routes_use_one_provider_owner(self):
        target = {
            "account_id": "actual-account",
            "payee_id": "landlord-id",
            "amount": -6,
            "category_id": "housing-id",
            "notes": "lease",
            "cycle": "weekly",
            "cycle_days": 7,
            "next_date": "2026-11-05",
            "active": True,
        }
        with patch(
            "routes.money.actual_finance.edit_recurring_schedule",
            return_value={"id": "created-rent", "edit_pending": False},
        ) as edit:
            response = self.client.post("/api/money/recurring/created-rent/edit", json=target)
        self.assertEqual(response.status_code, 200, response.text)
        edit.assert_called_once()
        self.assertEqual(edit.call_args.args[1:], ("created-rent", target))
        with patch(
            "routes.money.actual_finance.retry_recurring_edit",
            return_value={"id": "created-rent", "edit_pending": False},
        ) as retry:
            response = self.client.post("/api/money/recurring/created-rent/edit/retry")
        self.assertEqual(response.status_code, 200, response.text)
        retry.assert_called_once()
        self.assertEqual(retry.call_args.args[1], "created-rent")

    def test_recurring_create_recovers_lost_response_from_one_marker(self):
        db = self.db()
        snapshot = {"schedules": []}
        path = actual_migration._write_snapshot("run-route", snapshot)
        db.add(
            ActualMigrationRun(
                id="run-route",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256=actual_migration.snapshot_sha256(snapshot),
                snapshot_path=str(path),
            )
        )
        db.commit()
        actual = {
            "accounts": [{"id": "native-account", "name": "native checking", "closed": False}],
            "transactions": [],
            "payees": [{"id": "landlord-id", "name": "landlord"}],
            "categories": [{"id": "housing-id", "name": "housing", "is_income": False}],
            "category_groups": [],
            "schedules": [],
            "budget_months": [],
        }
        request_id = "11111111-1111-4111-8111-111111111111"
        values = {
            "account_id": "native-account",
            "amount": -5,
            "category_id": "housing-id",
            "category": "housing",
            "payee": "landlord",
            "notes": "lease",
            "cycle": "monthly",
            "cycle_days": 30,
            "next_date": "2026-10-01",
            "active": True,
        }
        backups = []
        writes = []

        def backup():
            backups.append(True)
            return {"ok": True, "backup_id": "before-created-rent"}

        def bridge(payload, *, timeout):
            if payload["command"] == "capabilities":
                return {"create_recurring_schedule": 1}
            if payload["command"] == "inspect":
                return actual
            self.assertEqual(payload["action"], "create_recurring_schedule")
            writes.append(payload)
            source = payload["schedule"]
            if len(writes) == 1:
                self.assertTrue(payload["allow_create"])
                actual["schedules"].append(
                    {
                        "id": "actual-created-rent",
                        "name": source["name"],
                        "account": "native-account",
                        "payee": "landlord-id",
                        "amount": -500,
                        "amountOp": "is",
                        "date": {
                            "start": "20261001",
                            "frequency": "monthly",
                            "interval": 1,
                            "patterns": [{"type": "day", "value": 1}],
                        },
                        "next_date": "2026-10-01",
                        "completed": False,
                        "posts_transaction": True,
                        "posting": {"guarded": True, "category": "housing-id", "notes": "lease"},
                    }
                )
                raise managed_actual.ManagedActualError("response lost")
            self.assertFalse(payload["allow_create"])
            return {
                "id": "actual-created-rent",
                "payee_id": "landlord-id",
                "posts_transaction": True,
            }

        with self.assertRaises(actual_finance.ActualFinanceUnavailable):
            actual_finance.create_recurring_schedule(
                db, values, request_id=request_id, bridge_request=bridge, backup_fn=backup
            )
        link = (
            db.query(ActualEntityLink)
            .filter_by(run_id="run-route", entity_kind="recurring", source_id=request_id)
            .one()
        )
        pending = json.loads(link.metadata_json)["_intent"]
        self.assertTrue(pending["attempted"])
        self.assertEqual(pending["backup_id"], "before-created-rent")
        visible = actual_finance.recurring_schedules(db, actual=actual)
        self.assertEqual(len(visible), 1)
        self.assertTrue(visible[0]["create_pending"])
        self.assertFalse(visible[0]["create_needs_review"])
        self.assertFalse(actual_migration.validate_active_links(db, actual)["ok"])
        created = actual_finance.retry_recurring_schedule(
            db, request_id, bridge_request=bridge, backup_fn=backup
        )
        self.assertEqual(created["id"], request_id)
        self.assertTrue(created["active"])
        self.assertFalse(created.get("create_pending", False))
        self.assertEqual(len(backups), 1)
        self.assertEqual(len(writes), 2)
        self.assertEqual(len(actual["schedules"]), 1)
        checkpoint = json.loads(link.metadata_json)["canonical_schedule"]
        self.assertEqual(checkpoint["source"]["account_id"], "native-account")
        self.assertEqual(checkpoint["payee_id"], "landlord-id")
        self.assertTrue(actual_migration.validate_active_links(db, actual)["ok"])
        replay = actual_finance.create_recurring_schedule(
            db, values, request_id=request_id, bridge_request=bridge, backup_fn=backup
        )
        self.assertEqual(replay["id"], request_id)
        self.assertEqual(len(writes), 2)
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "retry does not match"):
            actual_finance.create_recurring_schedule(
                db,
                {**values, "amount": -6},
                request_id=request_id,
                bridge_request=bridge,
                backup_fn=backup,
            )
        db.close()

    def test_attempted_recurring_create_never_recreates_a_missing_marker(self):
        db = self.db()
        snapshot = {"schedules": []}
        path = actual_migration._write_snapshot("run-route", snapshot)
        db.add(
            ActualMigrationRun(
                id="run-route",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256=actual_migration.snapshot_sha256(snapshot),
                snapshot_path=str(path),
            )
        )
        db.commit()
        actual = {
            "accounts": [{"id": "native-account", "closed": False}],
            "transactions": [],
            "payees": [],
            "categories": [],
            "category_groups": [],
            "schedules": [],
            "budget_months": [],
        }
        writes = []

        def bridge(payload, *, timeout):
            if payload["command"] == "capabilities":
                return {"create_recurring_schedule": 1}
            if payload["command"] == "inspect":
                return actual
            writes.append(payload)
            raise managed_actual.ManagedActualError("response lost before create")

        request_id = "22222222-2222-4222-8222-222222222222"
        with self.assertRaises(actual_finance.ActualFinanceUnavailable):
            actual_finance.create_recurring_schedule(
                db,
                {
                    "account_id": "native-account",
                    "amount": -5,
                    "payee": "landlord",
                    "next_date": "2026-10-01",
                },
                request_id=request_id,
                bridge_request=bridge,
                backup_fn=lambda: {"ok": True, "backup_id": "before-missing"},
            )
        visible = actual_finance.recurring_schedules(db, actual=actual)
        self.assertTrue(visible[0]["create_needs_review"])
        with self.assertRaisesRegex(actual_finance.ActualFinanceError, "marker is missing"):
            actual_finance.retry_recurring_schedule(db, request_id, bridge_request=bridge)
        self.assertEqual(len(writes), 1)
        db.close()

    def test_canonical_recurring_create_and_retry_routes_use_one_owner(self):
        request_id = "33333333-3333-4333-8333-333333333333"
        with (
            patch(
                "routes.money.actual_finance.create_recurring_schedule",
                return_value={"id": request_id, "create_pending": False},
            ) as create,
            patch(
                "routes.money.actual_finance.retry_recurring_schedule",
                return_value={"id": request_id, "create_pending": False},
            ) as retry,
        ):
            response = self.client.post(
                "/api/money/recurring",
                json={
                    "account_id": "legacy-account",
                    "next_date": "2026-10-01",
                    "request_id": request_id,
                    "category_id": "housing-id",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(create.call_args.kwargs["request_id"], request_id)
            self.assertEqual(create.call_args.args[1]["category_id"], "housing-id")
            recovered = self.client.post(f"/api/money/recurring/{request_id}/retry")
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(retry.call_args.args[1], request_id)

    def test_canonical_recurring_patch_allows_only_posting_switch(self):
        with patch(
            "routes.money.actual_finance.set_recurring_posting",
            return_value={"id": "legacy-rent", "active": False},
        ) as update:
            response = self.client.patch("/api/money/recurring/legacy-rent", json={"active": False})
            extra = self.client.patch(
                "/api/money/recurring/legacy-rent",
                json={"active": False, "amount": 1},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(extra.status_code, 409, extra.text)
        self.assertEqual(update.call_args.args[1:], ("legacy-rent", False))

    def test_canonical_alerts_use_one_actual_snapshot_and_local_watches(self):
        db = self.db()
        db.query(RecurringTxn).one().next_date = "2026-07-19"
        db.add(
            Transaction(
                account_id="legacy-account",
                date="2026-07-18",
                amount=-999,
                payee="frozen purchase",
                category="groceries",
            )
        )
        db.add_all(
            [
                ActualEntityLink(
                    run_id="run-route",
                    entity_kind="account",
                    source_id="legacy-account",
                    actual_id="actual-account",
                    metadata_json='{"low_balance":"80"}',
                ),
                ActualEntityLink(
                    run_id="run-route",
                    entity_kind="subscription",
                    source_id="legacy-subscription",
                    actual_id="actual-subscription",
                    metadata_json="{}",
                ),
            ]
        )
        db.commit()
        db.close()
        watch = self.client.post(
            "/api/money/watches", json={"kind": "category", "value": "groceries"}
        )
        self.assertEqual(watch.status_code, 200, watch.text)
        actual = {
            "accounts": [
                {
                    "id": "actual-account",
                    "name": "current checking",
                    "balance": 500,
                    "closed": False,
                }
            ],
            "transactions": [
                {
                    "id": "current-purchase",
                    "account": "actual-account",
                    "date": "2026-07-18",
                    "amount": -25000,
                    "payee_name": "market",
                    "category_name": "groceries",
                },
                {
                    "id": "current-transfer",
                    "account": "actual-account",
                    "date": "2026-07-18",
                    "amount": -50000,
                    "transfer_id": "partner-transfer",
                },
            ],
            "schedules": [
                {
                    "id": "current-bill",
                    "name": "utilities",
                    "amount": -6000,
                    "posts_transaction": True,
                    "next_date": "2026-07-21",
                },
                {
                    "id": "range-bill",
                    "name": "variable bill",
                    "amount": {"num1": -4000, "num2": -7000},
                    "amountOp": "isbetween",
                    "posts_transaction": True,
                    "next_date": "2026-07-20",
                },
                {
                    "id": "approx-bill",
                    "name": "approximate bill",
                    "amount": -5000,
                    "amountOp": "isapprox",
                    "posts_transaction": True,
                    "next_date": "2026-07-22",
                },
                {
                    "id": "actual-subscription",
                    "name": "subscription",
                    "amount": -1000,
                    "posts_transaction": True,
                    "next_date": "2026-07-20",
                },
            ],
        }
        with patch("routes.money.actual_finance.inspect", return_value=actual) as inspect:
            response = self.client.get("/api/money/alerts?month=2026-07&big=200&as_of=2026-07-18")
        self.assertEqual(response.status_code, 200, response.text)
        inspect.assert_called_once()
        data = response.json()
        self.assertEqual([row["id"] for row in data["large_purchases"]], ["current-purchase"])
        self.assertEqual([row["id"] for row in data["watch_hits"]], ["current-purchase"])
        self.assertEqual(
            {row["id"] for row in data["upcoming_bills"]},
            {"current-bill", "range-bill", "approx-bill"},
        )
        self.assertEqual(
            next(row for row in data["upcoming_bills"] if row["id"] == "range-bill")["amount"], None
        )
        self.assertEqual(
            next(row for row in data["upcoming_bills"] if row["id"] == "approx-bill")[
                "amount_kind"
            ],
            "approx",
        )
        self.assertEqual(
            data["low_balance"],
            [
                {
                    "id": "legacy-account",
                    "name": "current checking",
                    "balance": 5.0,
                    "threshold": 80.0,
                }
            ],
        )

    def test_canonical_alerts_report_actual_outage_without_frozen_fallback(self):
        with patch(
            "routes.money.actual_finance.inspect",
            side_effect=actual_finance.ActualFinanceUnavailable("Actual is unavailable"),
        ):
            response = self.client.get("/api/money/alerts?month=2026-07")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("Actual is unavailable", response.text)

    def test_canonical_age_of_money_uses_current_transactions_not_frozen_rows(self):
        db = self.db()
        db.add_all(
            [
                Transaction(
                    account_id="legacy-account",
                    date="2026-07-01",
                    amount=100,
                    payee="frozen income",
                ),
                Transaction(
                    account_id="legacy-account",
                    date="2026-07-02",
                    amount=-100,
                    payee="frozen expense",
                ),
            ]
        )
        db.commit()
        db.close()
        actual = {
            "accounts": [{"id": "current-account", "name": "current checking", "balance": 0}],
            "transactions": [
                {
                    "id": "opening",
                    "account": "current-account",
                    "date": "20260701",
                    "amount": 100000,
                    "starting_balance_flag": True,
                },
                {
                    "id": "income",
                    "account": "current-account",
                    "date": "20260701",
                    "amount": 10000,
                },
                {
                    "id": "expense-1",
                    "account": "current-account",
                    "date": "20260711",
                    "amount": -2500,
                },
                {
                    "id": "transfer",
                    "account": "current-account",
                    "date": "20260712",
                    "amount": -5000,
                    "transfer_id": "transfer-partner",
                },
                {
                    "id": "expense-2",
                    "account": "current-account",
                    "date": "20260721",
                    "amount": -2500,
                },
            ],
        }
        with patch("routes.money.actual_finance.inspect", return_value=actual) as inspect:
            response = self.client.get("/api/money/age-of-money")
        self.assertEqual(response.status_code, 200, response.text)
        inspect.assert_called_once()
        self.assertEqual(response.json(), {"age": 15, "sample": 2})

    def test_canonical_age_of_money_distinguishes_empty_from_provider_outage(self):
        actual = {
            "accounts": [],
            "transactions": [
                {"id": "expense", "date": "20260711", "amount": -2500},
                {"id": "later-income", "date": "20260721", "amount": 10000},
            ],
        }
        with patch("routes.money.actual_finance.inspect", return_value=actual):
            response = self.client.get("/api/money/age-of-money")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"age": None, "sample": 0})
        with patch(
            "routes.money.actual_finance.inspect",
            side_effect=actual_finance.ActualFinanceUnavailable("Actual is unavailable"),
        ):
            unavailable = self.client.get("/api/money/age-of-money")
        self.assertEqual(unavailable.status_code, 503, unavailable.text)
        self.assertIn("Actual is unavailable", unavailable.text)

    def test_stale_legacy_analytics_fail_closed_after_actual_cutover(self):
        for path in ("/api/money/income/summary",):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("canonical ledger", response.text)

    def test_canonical_envelope_routes_to_actual_and_reports_outage(self):
        expected = {
            "month": "2026-09",
            "income": 200.0,
            "assigned_total": 60.0,
            "to_be_budgeted": 90.0,
            "categories": [],
        }
        with patch("routes.money.actual_finance.envelope", return_value=expected) as read:
            response = self.client.get("/api/money/envelope?month=2026-09")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), expected)
        read.assert_called_once()
        self.assertEqual(read.call_args.args[1], "2026-09")

        with patch(
            "routes.money.actual_finance.envelope",
            side_effect=actual_finance.ActualFinanceUnavailable("Actual is unavailable"),
        ):
            unavailable = self.client.get("/api/money/envelope?month=2026-09")
        self.assertEqual(unavailable.status_code, 503, unavailable.text)

    def test_forecast_uses_one_actual_snapshot_and_posting_schedules(self):
        db = self.db()
        recurring_id = db.query(RecurringTxn.id).one()[0]
        db.add_all(
            [
                ActualEntityLink(
                    run_id="run-route",
                    entity_kind="account",
                    source_id="legacy-account",
                    actual_id="actual-account",
                    metadata_json='{"base_amount_text":"100","original_amount_text":"100"}',
                ),
                ActualEntityLink(
                    run_id="run-route",
                    entity_kind="recurring",
                    source_id=recurring_id,
                    actual_id="rent-schedule",
                    metadata_json='{"category":"housing"}',
                ),
                ActualEntityLink(
                    run_id="run-route",
                    entity_kind="subscription",
                    source_id="legacy-subscription",
                    actual_id="subscription-schedule",
                    metadata_json="{}",
                ),
            ]
        )
        db.commit()
        db.close()
        actual = {
            "accounts": [
                {"id": "actual-account", "name": "checking", "balance": 7000},
                {"id": "native-account", "name": "cash", "balance": 5000},
            ],
            "transactions": [
                {
                    "id": "expense",
                    "account": "actual-account",
                    "date": "20260510",
                    "amount": -3000,
                    "category_name": "groceries",
                },
                {
                    "id": "opening-native",
                    "account": "native-account",
                    "date": "20260615",
                    "amount": 5000,
                    "starting_balance_flag": True,
                },
            ],
            "payees": [{"id": "rent-payee", "name": "rent"}],
            "schedules": [
                {
                    "id": "rent-schedule",
                    "name": "Alles recurring: rent",
                    "account": "actual-account",
                    "payee": "rent-payee",
                    "amount": -3000,
                    "posts_transaction": True,
                    "date": {
                        "start": "2026-05-31",
                        "frequency": "monthly",
                        "interval": 1,
                        "patterns": [{"type": "day", "value": -1}],
                    },
                    "next_date": "2026-06-30",
                },
                {
                    "id": "subscription-schedule",
                    "name": "subscription",
                    "account": "actual-account",
                    "amount": -700,
                    "posts_transaction": True,
                    "date": {"start": "2026-06-10", "frequency": "monthly", "interval": 1},
                },
                {
                    "id": "native-schedule",
                    "name": "salary",
                    "account": "actual-account",
                    "amount": 1000,
                    "posts_transaction": True,
                    "date": {"start": "2026-06-25", "frequency": "monthly", "interval": 1},
                },
                {
                    "id": "paused-schedule",
                    "name": "paused",
                    "account": "actual-account",
                    "amount": -900,
                    "posts_transaction": True,
                    "completed": True,
                    "date": {"start": "2026-06-05", "frequency": "monthly", "interval": 1},
                },
            ],
        }
        with patch("routes.money.actual_finance.inspect", return_value=actual) as inspect:
            response = self.client.get("/api/money/forecast?month=2026-06&as_of=2026-06-01")
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(payload["start_balance"], 70.0)
            self.assertEqual(payload["projected"], 50.0)
            self.assertEqual(payload["categories"], {"groceries": 10.0})
            self.assertEqual(
                [(row["payee"], row["date"]) for row in payload["recurring"]],
                [("salary", "2026-06-25"), ("rent", "2026-06-30")],
            )
            inspect.assert_called_once()
            later = self.client.get(
                "/api/money/forecast?month=2026-06&as_of=2026-06-20&skip=rent&income_delta=5"
            )
            self.assertEqual(later.status_code, 200, later.text)
            self.assertEqual(later.json()["start_balance"], 120.0)
            self.assertEqual(later.json()["projected"], 135.0)
            actual["schedules"][0]["next_date"] = "2026-05-31"
            stale_next = self.client.get("/api/money/forecast?month=2026-06&as_of=2026-06-01")
            self.assertEqual(stale_next.status_code, 200, stale_next.text)
            self.assertEqual(stale_next.json()["projected"], 50.0)
            self.assertEqual(stale_next.json()["recurring"][-1]["date"], "2026-06-30")
            self.assertEqual(inspect.call_count, 3)
        db = self.db()
        self.assertEqual(db.query(RecurringTxn).one().next_date, "2020-01-01")
        db.close()

    def test_forecast_reports_actual_outage_or_unknown_recurrence(self):
        with patch(
            "routes.money.actual_finance.inspect",
            side_effect=actual_finance.ActualFinanceUnavailable("Actual is unavailable"),
        ):
            unavailable = self.client.get("/api/money/forecast?month=2026-06")
        self.assertEqual(unavailable.status_code, 503, unavailable.text)
        actual = {
            "accounts": [],
            "transactions": [],
            "payees": [],
            "schedules": [
                {
                    "id": "unknown",
                    "name": "bill",
                    "account": "account",
                    "posts_transaction": True,
                    "amount": -100,
                    "date": {"start": "2026-06-10", "frequency": "monthly", "interval": 2},
                }
            ],
        }
        with patch("routes.money.actual_finance.inspect", return_value=actual):
            unknown = self.client.get("/api/money/forecast?month=2026-06&as_of=2026-06-01")
        self.assertEqual(unknown.status_code, 409, unknown.text)
        self.assertIn("cannot be represented exactly", unknown.text)
        actual["schedules"][0]["date"] = {
            "start": "2026-06-10",
            "frequency": "monthly",
            "interval": 1,
            "endMode": "on_date",
            "endDate": "2026-06-10",
        }
        with patch("routes.money.actual_finance.inspect", return_value=actual):
            ended = self.client.get("/api/money/forecast?month=2026-06&as_of=2026-06-01")
        self.assertEqual(ended.status_code, 409, ended.text)
        self.assertIn("end rule cannot be forecast exactly", ended.text)
        actual["schedules"][0]["date"] = {
            "start": "2026-06-10",
            "frequency": "monthly",
            "interval": 1,
            "endMode": "never",
            "skipWeekend": True,
        }
        with patch("routes.money.actual_finance.inspect", return_value=actual):
            shifted = self.client.get("/api/money/forecast?month=2026-06&as_of=2026-06-01")
        self.assertEqual(shifted.status_code, 409, shifted.text)
        self.assertIn("weekend rule cannot be forecast exactly", shifted.text)

    def test_canonical_reconcile_includes_the_opening_balance(self):
        actual = {"accounts": [], "transactions": []}
        with (
            patch("routes.money.actual_finance.inspect", return_value=actual),
            patch(
                "routes.money.actual_finance.accounts",
                return_value=[{"id": "legacy-account", "opening": 100.0, "balance": 92.0}],
            ) as accounts,
            patch(
                "routes.money.actual_finance.transactions",
                return_value=[
                    {"account_id": "legacy-account", "amount": -5.0, "cleared": True},
                    {"account_id": "legacy-account", "amount": -3.0, "cleared": False},
                ],
            ) as transactions,
        ):
            response = self.client.get("/api/money/accounts/legacy-account/reconcile?statement=95")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["cleared_balance"], 95.0)
        self.assertTrue(response.json()["reconciled"])
        self.assertIs(accounts.call_args.kwargs["actual"], actual)
        self.assertIs(transactions.call_args.kwargs["actual"], actual)

    def test_canonical_reconcile_uses_actual_balance_for_a_native_account(self):
        with (
            patch(
                "routes.money.actual_finance.inspect",
                return_value={"accounts": [], "transactions": []},
            ),
            patch(
                "routes.money.actual_finance.accounts",
                return_value=[{"id": "native-account", "opening": 0.0, "balance": 47.0}],
            ),
            patch(
                "routes.money.actual_finance.transactions",
                return_value=[{"account_id": "native-account", "amount": -3.0, "cleared": False}],
            ),
        ):
            response = self.client.get("/api/money/accounts/native-account/reconcile?statement=50")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["cleared_balance"], 50.0)
        self.assertTrue(response.json()["reconciled"])

    def test_reviewed_import_apply_and_undo_are_actual_only_and_receipt_owned(self):
        actual_rows = []

        def create(_db, values, **kwargs):
            row = {
                "id": kwargs["source_id"],
                "account_id": values["account_id"],
                "date": values["date"],
                "amount": float(values["amount"]),
                "category": "",
                "payee": values["payee"],
                "notes": values["notes"],
                "transfer_id": "",
                "tags": "",
                "receipt_id": "",
                "cleared": False,
                "split": False,
                "original_amount_text": values["amount"],
                "original_currency_code": "CAD",
                "base_amount_text": values["amount"],
                "base_currency_code": "CAD",
                "import_identity": kwargs["import_identity"],
                "import_batch_id": kwargs["evidence"]["import_batch_id"],
                "import_source": kwargs["evidence"]["import_source"],
            }
            actual_rows.append(row)
            return row

        def remove(_db, public_id):
            actual_rows[:] = [row for row in actual_rows if row["id"] != public_id]
            return {"ok": True}

        with (
            patch(
                "routes.finance_imports.actual_finance.accounts",
                return_value=[{"id": "legacy-account"}],
            ),
            patch(
                "routes.finance_imports.actual_finance.transactions",
                side_effect=lambda _db: list(actual_rows),
            ),
            patch(
                "routes.finance_imports.actual_finance.create_transaction", side_effect=create
            ) as create_mock,
            patch(
                "routes.finance_imports.actual_finance.delete_transaction", side_effect=remove
            ) as delete_mock,
        ):
            preview = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cibc-csv",
                    "source_name": "statement.csv",
                    "content": "Date,Description,Debit,Credit,Reference\n2026-07-18,Market,12.34,,abc-1\n",
                    "original_currency_code": "CAD",
                },
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            batch_id = preview.json()["id"]
            applied = self.client.post(f"/api/finance/imports/{batch_id}/apply")
            self.assertEqual(applied.status_code, 200, applied.text)
            self.assertEqual(applied.json()["counts"]["applied"], 1)
            created_transaction_id = applied.json()["rows"][0]["created_transaction_id"]
            duplicate = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cibc-csv",
                    "source_name": "statement-again.csv",
                    "content": "Date,Description,Debit,Credit,Reference\n2026-07-18,Market,12.34,,abc-1\n",
                    "original_currency_code": "CAD",
                },
            )
            self.assertEqual(duplicate.json()["counts"]["duplicates"], 1)
            actual_rows[0]["amount"] = -99.0
            edited = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cibc-csv",
                    "source_name": "statement-after-actual-edit.csv",
                    "content": "Date,Description,Debit,Credit,Reference\n2026-07-18,Market,12.34,,abc-1\n",
                    "original_currency_code": "CAD",
                },
            )
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(edited.json()["counts"]["conflicts"], 1)
            # An interrupted idempotent delete can remove the row before its
            # receipt state is finalized. Undo must resume the deletion intent
            # even when the current projection no longer includes the row.
            actual_rows.clear()
            state_db = self.db()
            state = state_db.get(FinanceLedgerState, "primary")
            state.mode = "alles"
            state.legacy_read_only = False
            state_db.commit()
            state_db.close()
            undone = self.client.post(f"/api/finance/imports/{batch_id}/undo")
            self.assertEqual(undone.status_code, 200, undone.text)
            self.assertEqual(undone.json()["counts"]["undone"], 1)
        create_mock.assert_called_once()
        delete_mock.assert_called_once()
        self.assertEqual(
            delete_mock.call_args.args[1],
            created_transaction_id,
        )
        self.assertTrue(created_transaction_id.startswith(f"finance-import:{batch_id}:"))
        db = self.db()
        self.assertEqual(db.query(Transaction).count(), 0)
        db.close()

    def test_canonical_import_undo_preflights_every_row_before_deleting_any(self):
        actual_rows = []

        def create(_db, values, **kwargs):
            row = {
                "id": kwargs["source_id"],
                "account_id": values["account_id"],
                "date": values["date"],
                "amount": float(values["amount"]),
                "category": "",
                "payee": values["payee"],
                "notes": values["notes"],
                "transfer_id": "",
                "tags": "",
                "receipt_id": "",
                "cleared": False,
                "split": False,
                "original_amount_text": values["amount"],
                "original_currency_code": "CAD",
                "base_amount_text": values["amount"],
                "base_currency_code": "CAD",
                "import_identity": kwargs["import_identity"],
                "import_batch_id": kwargs["evidence"]["import_batch_id"],
                "import_source": kwargs["evidence"]["import_source"],
            }
            actual_rows.append(row)
            return row

        with (
            patch(
                "routes.finance_imports.actual_finance.accounts",
                return_value=[{"id": "legacy-account"}],
            ),
            patch(
                "routes.finance_imports.actual_finance.transactions",
                side_effect=lambda _db: list(actual_rows),
            ),
            patch("routes.finance_imports.actual_finance.create_transaction", side_effect=create),
            patch("routes.finance_imports.actual_finance.delete_transaction") as delete_mock,
        ):
            preview = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cibc-csv",
                    "source_name": "two-rows.csv",
                    "content": (
                        "Date,Description,Debit,Credit,Reference\n"
                        "2026-07-18,Market,12.34,,undo-1\n"
                        "2026-07-19,Transit,3.25,,undo-2\n"
                    ),
                    "original_currency_code": "CAD",
                },
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            batch_id = preview.json()["id"]
            applied = self.client.post(f"/api/finance/imports/{batch_id}/apply")
            self.assertEqual(applied.status_code, 200, applied.text)
            self.assertEqual(applied.json()["counts"]["applied"], 2)

            actual_rows[1]["cleared"] = True
            undone = self.client.post(f"/api/finance/imports/{batch_id}/undo")

        self.assertEqual(undone.status_code, 409, undone.text)
        self.assertIn("changed after apply", undone.text)
        delete_mock.assert_not_called()
        db = self.db()
        self.assertEqual(
            [
                row.status
                for row in db.query(FinanceImportRow).order_by(FinanceImportRow.row_number)
            ],
            ["applied", "applied"],
        )
        db.close()

    def test_foreign_currency_import_accepts_reviewed_row_conversion(self):
        created = []

        def create(_db, values, **kwargs):
            self.assertEqual(values["amount"], "-2.00")
            self.assertEqual(kwargs["evidence"]["original_currency_code"], "CNY")
            self.assertEqual(kwargs["evidence"]["base_currency_code"], "CAD")
            self.assertEqual(kwargs["evidence"]["rate_text"], "0.2")
            row = {
                "id": kwargs["source_id"],
                "actual_id": "actual-cny-row",
                "account_id": values["account_id"],
                "date": values["date"],
                "amount": float(values["amount"]),
                "category": "",
                "payee": values["payee"],
                "notes": values["notes"],
                "transfer_id": "",
                "tags": "",
                "receipt_id": "",
                "cleared": False,
                "split": False,
                "original_amount_text": "-10.00",
                "original_currency_code": "CNY",
                "base_amount_text": "-2.00",
                "base_currency_code": "CAD",
                "import_identity": kwargs["import_identity"],
                "import_batch_id": kwargs["evidence"]["import_batch_id"],
                "import_source": kwargs["evidence"]["import_source"],
            }
            created.append(row)
            return row

        with (
            patch(
                "routes.finance_imports.actual_finance.accounts",
                return_value=[{"id": "legacy-account"}],
            ),
            patch(
                "routes.finance_imports.actual_finance.transactions",
                side_effect=lambda _db: list(created),
            ),
            patch("routes.finance_imports.actual_finance.create_transaction", side_effect=create),
        ):
            preview = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cmb-csv",
                    "source_name": "cmb.csv",
                    "content": "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n2026-07-18,茶馆,10.00,,CNY,cmb-fx-1\n",
                    "original_currency_code": "CNY",
                },
            ).json()
            self.assertEqual(preview["rows"][0]["status"], "needs_review")
            self.assertEqual(preview["status"], "preview")
            row_id = preview["rows"][0]["id"]
            reviewed = self.client.patch(
                f"/api/finance/imports/{preview['id']}/rows/{row_id}/conversion",
                json={
                    "base_amount_text": "-2.00",
                    "rate_text": "0.2",
                    "rate_date": "2026-07-18",
                    "source": "bank of canada daily rate",
                },
            )
            self.assertEqual(reviewed.status_code, 200, reviewed.text)
            self.assertEqual(reviewed.json()["rows"][0]["status"], "pending")
            self.assertEqual(reviewed.json()["status"], "preview")
            applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
            self.assertEqual(applied.status_code, 200, applied.text)
            self.assertEqual(applied.json()["counts"]["applied"], 1)
            self.assertEqual(applied.json()["status"], "applied")

            repeated = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cmb-csv",
                    "source_name": "cmb.csv",
                    "content": "交易日期,交易摘要,支出金额,收入金额,交易币种,交易流水号\n2026-07-18,茶馆,10.00,,CNY,cmb-fx-1\n",
                    "original_currency_code": "CNY",
                },
            ).json()
            self.assertEqual(repeated["rows"][0]["status"], "needs_review")
            repeated_row_id = repeated["rows"][0]["id"]
            changed_rate = self.client.patch(
                f"/api/finance/imports/{repeated['id']}/rows/{repeated_row_id}/conversion",
                json={
                    "base_amount_text": "-3.00",
                    "rate_text": "0.3",
                    "rate_date": "2026-07-18",
                    "source": "owner reviewed replacement rate",
                },
            )
            self.assertEqual(changed_rate.status_code, 200, changed_rate.text)
            conflict = self.client.post(f"/api/finance/imports/{repeated['id']}/apply")
            self.assertEqual(conflict.status_code, 200, conflict.text)
            self.assertEqual(conflict.json()["rows"][0]["status"], "conflict")
            self.assertEqual(len(created), 1)

    def test_canonical_import_preflights_every_conversion_before_any_external_write(self):
        with (
            patch(
                "routes.finance_imports.actual_finance.accounts",
                return_value=[{"id": "legacy-account"}],
            ),
            patch("routes.finance_imports.actual_finance.transactions", return_value=[]),
            patch("routes.finance_imports.actual_finance.create_transaction") as create,
        ):
            preview_response = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cibc-csv",
                    "source_name": "mixed.csv",
                    "content": (
                        "Date,Description,Amount,Currency,Reference\n"
                        "2026-07-18,Ready,10.00,CAD,ready-1\n"
                        "2026-07-19,Foreign,20.00,CNY,foreign-1\n"
                    ),
                    "original_currency_code": "CAD",
                },
            )
            self.assertEqual(preview_response.status_code, 200, preview_response.text)
            payload = preview_response.json()
            applied = self.client.post(f"/api/finance/imports/{payload['id']}/apply")
        self.assertEqual(applied.status_code, 409, applied.text)
        apply_payload = applied.json()
        self.assertIn("resolve every import conflict", apply_payload["detail"])
        receipt = self.client.get(f"/api/finance/imports/{payload['id']}").json()
        self.assertEqual(receipt["counts"]["applied"], 0)
        self.assertEqual(receipt["counts"]["pending"], 1)
        self.assertEqual(receipt["counts"]["conflicts"], 1)
        self.assertEqual(receipt["rows"][1]["status"], "needs_review")
        create.assert_not_called()

    def test_canonical_import_rejects_unsafe_same_currency_amount_before_claim(self):
        with (
            patch(
                "routes.finance_imports.actual_finance.accounts",
                return_value=[{"id": "legacy-account"}],
            ),
            patch("routes.finance_imports.actual_finance.transactions", return_value=[]),
            patch("routes.finance_imports.actual_finance.create_transaction") as create,
        ):
            preview = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cibc-csv",
                    "source_name": "unsafe.csv",
                    "content": (
                        "Date,Description,Amount,Currency,Reference\n"
                        "2026-07-18,Unsafe,90071992547410.00,CAD,unsafe-1\n"
                    ),
                    "original_currency_code": "CAD",
                },
            ).json()
            applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        payload = applied.json()
        self.assertEqual(payload["status"], "preview")
        self.assertEqual(payload["rows"][0]["status"], "needs_review")
        self.assertEqual(payload["counts"]["applying"], 0)
        create.assert_not_called()

    def test_canonical_import_preflights_new_conflicts_before_any_external_write(self):
        actual_rows = []
        with (
            patch(
                "routes.finance_imports.actual_finance.accounts",
                return_value=[{"id": "legacy-account"}],
            ),
            patch(
                "routes.finance_imports.actual_finance.transactions",
                side_effect=lambda _db: list(actual_rows),
            ),
            patch("routes.finance_imports.actual_finance.create_transaction") as create,
        ):
            preview = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cibc-csv",
                    "source_name": "raced.csv",
                    "content": (
                        "Date,Description,Amount,Currency,Reference\n"
                        "2026-07-18,Safe,10.00,CAD,ready-first\n"
                        "2026-07-19,Changed,20.00,CAD,conflict-second\n"
                    ),
                    "original_currency_code": "CAD",
                },
            ).json()
            actual_rows.append(
                {
                    "id": "actual-conflict",
                    "actual_id": "actual-conflict",
                    "account_id": "legacy-account",
                    "date": "2026-07-19",
                    "amount": 99.0,
                    "payee": "different row",
                    "original_amount_text": "99.00",
                    "original_currency_code": "CAD",
                    "import_identity": preview["rows"][1]["stable_identity"],
                }
            )
            applied = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        payload = applied.json()
        self.assertEqual(payload["counts"]["applied"], 0)
        self.assertEqual(payload["counts"]["conflicts"], 1)
        self.assertEqual(payload["rows"][0]["status"], "pending")
        self.assertEqual(payload["rows"][1]["status"], "conflict")
        create.assert_not_called()

    def test_conversion_review_rejects_a_row_that_failed_parsing(self):
        db = self.db()
        batch = FinanceImportBatch(
            account_id="legacy-account",
            profile="cmb-notification",
            source_name="messages.txt",
            source_sha256="a" * 64,
            original_currency_code="CNY",
            status="preview",
        )
        db.add(batch)
        db.flush()
        row = FinanceImportRow(
            batch_id=batch.id,
            row_number=1,
            stable_identity="parse-error-row",
            parsed_json="{}",
            raw_json="{}",
            status="needs_review",
            conflict_reason="notification is missing a transaction date",
        )
        db.add(row)
        db.commit()
        batch_id, row_id = batch.id, row.id
        db.close()
        response = self.client.patch(
            f"/api/finance/imports/{batch_id}/rows/{row_id}/conversion",
            json={
                "base_amount_text": "1.00",
                "rate_text": "0.2",
                "rate_date": "2026-07-18",
                "source": "owner note",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("parsing must be resolved", response.text)

    def test_conversion_review_rejects_unbounded_decimals_without_server_error(self):
        db = self.db()
        batch = FinanceImportBatch(
            account_id="legacy-account",
            profile="cmb-csv",
            source_name="huge.csv",
            source_sha256="b" * 64,
            original_currency_code="CNY",
            status="preview",
        )
        db.add(batch)
        db.flush()
        row = FinanceImportRow(
            batch_id=batch.id,
            row_number=1,
            stable_identity="huge-decimal-row",
            parsed_json=json.dumps(
                {"date": "2026-07-18", "amount_text": "1E+999999", "currency_code": "CNY"}
            ),
            raw_json="{}",
            status="pending",
        )
        db.add(row)
        db.commit()
        batch_id, row_id = batch.id, row.id
        db.close()
        response = self.client.patch(
            f"/api/finance/imports/{batch_id}/rows/{row_id}/conversion",
            json={
                "base_amount_text": "1.00",
                "rate_text": "1",
                "rate_date": "2026-07-18",
                "source": "owner note",
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("supported decimals", response.text)

    def test_notification_conversion_does_not_bypass_account_confirmation(self):
        db = self.db()
        batch = FinanceImportBatch(
            account_id="legacy-account",
            profile="cmb-notification",
            source_name="message.txt",
            source_sha256="c" * 64,
            original_currency_code="CNY",
            status="preview",
            receipt_json=json.dumps(
                {
                    "version": 1,
                    "account_id": "legacy-account",
                    "account_name": "CMB ending 1234",
                    "confirmed_account_suffixes": {},
                }
            ),
        )
        db.add(batch)
        db.flush()
        row = FinanceImportRow(
            batch_id=batch.id,
            row_number=1,
            stable_identity="notification-fx-row",
            parsed_json=json.dumps(
                {
                    "date": "2026-07-18",
                    "amount_text": "-10.00",
                    "currency_code": "CNY",
                    "account_suffix": "1234",
                }
            ),
            raw_json="{}",
            status="needs_review",
            conflict_reason="confirm account ending 1234 belongs to CMB ending 1234",
        )
        db.add(row)
        db.commit()
        batch_id, row_id = batch.id, row.id
        db.close()

        reviewed = self.client.patch(
            f"/api/finance/imports/{batch_id}/rows/{row_id}/conversion",
            json={
                "base_amount_text": "-2.00",
                "rate_text": "0.2",
                "rate_date": "2026-07-18",
                "source": "owner statement",
            },
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        reviewed_row = reviewed.json()["rows"][0]
        self.assertEqual(reviewed_row["status"], "needs_review")
        self.assertIn("confirm account ending 1234", reviewed_row["conflict_reason"])
        blocked = self.client.post(f"/api/finance/imports/{batch_id}/apply")
        self.assertEqual(blocked.status_code, 409, blocked.text)

        confirmed = self.client.post(
            f"/api/finance/imports/{batch_id}/rows/{row_id}/confirm-account",
            json={"account_id": "legacy-account", "account_suffix": "1234"},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["rows"][0]["status"], "pending")

    def test_conversion_review_does_not_bypass_an_ambiguous_match_decision(self):
        reason = (
            "matching row has no bank reference and came from a different statement; "
            "review it instead of assuming it is a duplicate"
        )
        db = self.db()
        batch = FinanceImportBatch(
            account_id="legacy-account",
            profile="cmb-csv",
            source_name="statement.csv",
            source_sha256="d" * 64,
            original_currency_code="CNY",
            status="preview",
        )
        db.add(batch)
        db.flush()
        row = FinanceImportRow(
            batch_id=batch.id,
            row_number=1,
            stable_identity="ambiguous-fx-row",
            parsed_json=json.dumps(
                {
                    "date": "2026-07-18",
                    "amount_text": "-10.00",
                    "currency_code": "CNY",
                    "payee": "Tea shop",
                }
            ),
            raw_json="{}",
            status="needs_review",
            conflict_reason=reason,
        )
        db.add(row)
        db.commit()
        batch_id, row_id = batch.id, row.id
        db.close()

        reviewed = self.client.patch(
            f"/api/finance/imports/{batch_id}/rows/{row_id}/conversion",
            json={
                "base_amount_text": "-2.00",
                "rate_text": "0.2",
                "rate_date": "2026-07-18",
                "source": "owner statement",
            },
        )

        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        reviewed_row = reviewed.json()["rows"][0]
        self.assertEqual(reviewed_row["status"], "needs_review")
        self.assertEqual(reviewed_row["conflict_reason"], reason)
        self.assertEqual(reviewed_row["conversion"]["base_amount_text"], "-2.00")

    def test_interrupted_actual_import_recovers_receipt_ownership_idempotently(self):
        actual_rows = []
        first = True

        def create(_db, values, **kwargs):
            nonlocal first
            row = {
                "id": "actual-orphan",
                "actual_id": "actual-orphan",
                "account_id": values["account_id"],
                "date": values["date"],
                "amount": float(values["amount"]),
                "payee": values["payee"],
                "category": values.get("category", ""),
                "notes": values.get("notes", ""),
                "cleared": bool(values.get("cleared")),
                "import_identity": kwargs["import_identity"],
            }
            if first:
                first = False
                actual_rows.append(row)
                raise RuntimeError("readback interrupted after Actual accepted the row")
            self.fail("the idempotent recovery must not create a second Actual row")

        with (
            patch(
                "routes.finance_imports.actual_finance.accounts",
                return_value=[{"id": "legacy-account"}],
            ),
            patch(
                "routes.finance_imports.actual_finance.transactions",
                side_effect=lambda _db: list(actual_rows),
            ),
            patch("routes.finance_imports.actual_finance.create_transaction", side_effect=create),
        ):
            preview = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cibc-csv",
                    "source_name": "receipt.csv",
                    "content": "Date,Description,Debit,Credit,Reference\n2026-07-18,Market,12.34,,recover-1\n",
                    "original_currency_code": "CAD",
                },
            ).json()
            with self.assertRaisesRegex(RuntimeError, "readback interrupted"):
                self.client.post(f"/api/finance/imports/{preview['id']}/apply")
            db = self.db()
            self.assertEqual(db.query(FinanceImportRow).one().status, "applying")
            db.close()
            recovered = self.client.post(f"/api/finance/imports/{preview['id']}/apply")
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json()["counts"]["applied"], 1)
        db = self.db()
        link = db.query(ActualEntityLink).filter_by(entity_kind="transaction").one()
        self.assertEqual(link.actual_id, "actual-orphan")
        metadata = json.loads(link.metadata_json)
        self.assertIn("canonical_transaction", metadata)
        self.assertNotIn("_intent", metadata)
        self.assertIn("_request_fingerprint", metadata)
        self.assertEqual(len(actual_rows), 1)
        db.close()

    def test_recovery_conflict_stops_before_pending_actual_writes(self):
        actual_rows = []

        with (
            patch(
                "routes.finance_imports.actual_finance.accounts",
                return_value=[{"id": "legacy-account"}],
            ),
            patch(
                "routes.finance_imports.actual_finance.transactions",
                side_effect=lambda _db: list(actual_rows),
            ),
            patch("routes.finance_imports.actual_finance.create_transaction") as create_mock,
        ):
            preview = self.client.post(
                "/api/finance/imports/preview",
                json={
                    "account_id": "legacy-account",
                    "profile": "cibc-csv",
                    "source_name": "receipt.csv",
                    "content": (
                        "Date,Description,Debit,Credit,Reference\n"
                        "2026-07-18,Market,12.34,,recover-conflict\n"
                        "2026-07-19,Transit,3.25,,still-pending\n"
                    ),
                    "original_currency_code": "CAD",
                },
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            payload = preview.json()
            first = payload["rows"][0]
            db = self.db()
            row = db.get(FinanceImportRow, first["id"])
            row.status = "applying"
            row.created_transaction_id = f"finance-import:{payload['id']}:{row.row_number}"
            db.commit()
            db.close()
            actual_rows.append(
                {
                    "id": "foreign-public-id",
                    "actual_id": "foreign-actual-id",
                    "account_id": "legacy-account",
                    "date": "2026-07-18",
                    "amount": -12.34,
                    "payee": "Market",
                    "category": "",
                    "notes": "changed after the interrupted import",
                    "cleared": False,
                    "import_identity": first["stable_identity"],
                }
            )

            recovered = self.client.post(f"/api/finance/imports/{payload['id']}/apply")
            kept = self.client.post(
                f"/api/finance/imports/{payload['id']}/rows/{first['id']}/resolve-recovery",
                json={"decision": "keep"},
            )

        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()["status"], "preview")
        self.assertEqual(recovered.json()["counts"]["conflicts"], 1)
        self.assertEqual(recovered.json()["counts"]["pending"], 1)
        self.assertEqual(
            [row["status"] for row in recovered.json()["rows"]],
            ["conflict", "pending"],
        )
        self.assertEqual(kept.status_code, 200, kept.text)
        self.assertEqual([row["status"] for row in kept.json()["rows"]], ["applied", "pending"])
        kept_row = next(row for row in kept.json()["rows"] if row["id"] == first["id"])
        self.assertEqual(
            kept_row["created_transaction_id"],
            f"finance-import:{payload['id']}:{first['row_number']}",
        )
        self.assertEqual(
            kept.json()["receipt"]["row_recovery_decisions"][first["id"]]["decision"],
            "keep",
        )
        replacement = kept.json()["receipt"]["row_recovery_decisions"][first["id"]][
            "accepted_replacement"
        ]
        self.assertEqual(replacement["notes"], "changed after the interrupted import")
        self.assertEqual(replacement["import_identity"], first["stable_identity"])
        create_mock.assert_not_called()

        source_id = f"finance-import:{payload['id']}:{first['row_number']}"
        projected = {
            **replacement,
            "id": source_id,
            "actual_id": "foreign-actual-id",
            "import_batch_id": payload["id"],
            "import_source": "finance_import:cibc-csv",
        }
        deleted = []
        with (
            patch(
                "routes.finance_imports.actual_finance.transactions",
                return_value=[projected],
            ),
            patch(
                "routes.finance_imports.actual_finance.delete_transaction",
                side_effect=lambda _db, transaction_id: deleted.append(transaction_id),
            ),
        ):
            undone = self.client.post(f"/api/finance/imports/{payload['id']}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["status"], "undone")
        self.assertEqual(deleted, [source_id])

    def test_owner_can_delete_a_conflicted_claim_and_undo_the_partial_receipt(self):
        reason = "incomplete Actual write no longer matches this receipt"
        db = self.db()
        batch = FinanceImportBatch(
            account_id="legacy-account",
            profile="cibc-csv",
            source_name="partial.csv",
            source_sha256="e" * 64,
            original_currency_code="CAD",
            status="preview",
        )
        db.add(batch)
        db.flush()
        first = FinanceImportRow(
            batch_id=batch.id,
            row_number=1,
            stable_identity="already-applied",
            raw_json="{}",
            parsed_json="{}",
            status="applied",
            created_transaction_id=f"finance-import:{batch.id}:1",
        )
        second = FinanceImportRow(
            batch_id=batch.id,
            row_number=2,
            stable_identity="conflicted-claim",
            raw_json="{}",
            parsed_json="{}",
            status="conflict",
            conflict_reason=reason,
            created_transaction_id=f"finance-import:{batch.id}:2",
            existing_transaction_id="conflicted-public",
        )
        db.add_all([first, second])
        db.commit()
        batch_id, second_id = batch.id, second.id
        db.close()
        actual_rows = [
            {
                "id": "conflicted-public",
                "actual_id": "conflicted-actual",
                "import_identity": "conflicted-claim",
            }
        ]
        deleted = []

        def remove(_db, public_id):
            deleted.append(public_id)
            actual_rows[:] = [row for row in actual_rows if row["id"] != public_id]
            return {"ok": True}

        with (
            patch(
                "routes.finance_imports.actual_finance.transactions",
                side_effect=lambda _db: list(actual_rows),
            ),
            patch("routes.finance_imports.actual_finance.delete_transaction", side_effect=remove),
        ):
            resolved = self.client.post(
                f"/api/finance/imports/{batch_id}/rows/{second_id}/resolve-recovery",
                json={"decision": "delete"},
            )
            undone = self.client.post(f"/api/finance/imports/{batch_id}/undo")

        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual([row["status"] for row in resolved.json()["rows"]], ["applied", "pending"])
        self.assertEqual(
            resolved.json()["receipt"]["row_recovery_decisions"][second_id]["decision"],
            "delete",
        )
        db = self.db()
        recovered_batch = db.get(FinanceImportBatch, batch_id)
        recovered_row = db.get(FinanceImportRow, second_id)
        self.assertTrue(
            finance_import_routes._owner_approved_deleted_reimport(recovered_batch, recovered_row)
        )
        db.close()
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["status"], "undone")
        self.assertEqual([row["status"] for row in undone.json()["rows"]], ["undone", "undone"])
        self.assertEqual(deleted, ["conflicted-public", f"finance-import:{batch_id}:1"])


if __name__ == "__main__":
    unittest.main()
