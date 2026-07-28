import copy
import json
import tempfile
import threading
from datetime import date
from pathlib import Path
from unittest import mock

from core.database import (
    Account,
    ActualEntityLink,
    ActualMigrationRun,
    Budget,
    BudgetAssignment,
    FinanceLedgerState,
    MoneyFxEvidence,
    RecurringTxn,
    SubPayment,
    Subscription,
    Transaction,
    TxnSplit,
)
from services import actual_bridge, actual_finance, actual_migration, managed_actual
from tests._client import ApiTest


class ActualMigrationTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.left = self.client.post(
            "/api/money/accounts",
            json={"name": "chequing", "kind": "checking", "currency": "CAD", "opening": 100},
        ).json()
        self.right = self.client.post(
            "/api/money/accounts",
            json={"name": "savings", "kind": "savings", "currency": "CAD", "opening": 20},
        ).json()
        self.client.post(
            "/api/money/transactions",
            json={
                "account_id": self.left["id"],
                "date": "2026-07-01",
                "amount": -5.25,
                "payee": "grocer",
                "category": "food",
            },
        )
        response = self.client.post(
            "/api/money/transfer",
            json={
                "from_account": self.left["id"],
                "to_account": self.right["id"],
                "date": "2026-07-02",
                "amount": 10,
                "notes": "save",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.client.post(
            "/api/money/recurring",
            json={
                "account_id": self.left["id"],
                "amount": -20,
                "category": "housing",
                "payee": "rent",
                "cycle": "monthly",
                "cycle_days": 30,
                "next_date": "2026-08-01",
                "active": True,
            },
        )
        self.client.post(
            "/api/subscriptions",
            json={
                "name": "mail",
                "price": 8,
                "currency": "CAD",
                "cycle": "monthly",
                "cycle_days": 30,
                "next_due": "2026-08-05",
                "category": "software",
                "account_id": self.left["id"],
            },
        )
        db = self.db()
        db.add(BudgetAssignment(category="food", month="2026-07", assigned=50))
        db.add(Budget(category="", tag="coffee", limit_amt=25))
        imported = db.query(Transaction).filter_by(transfer_id="").one()
        imported.tags = "groceries,weekly"
        imported.receipt_id = "receipt-1"
        imported.import_batch_id = "batch-1"
        imported.import_source = "finance_import:cibc_csv"
        imported.import_identity = "bank:cibc:statement-row-7"
        imported.import_row_number = 7
        imported.import_receipt_json = '{"version":1}'
        subscription = db.query(Subscription).one()
        db.add(
            SubPayment(
                sub_id=subscription.id,
                date="2026-07-05",
                amount=8,
                original_amount_text="8",
                original_currency_code="CAD",
                base_amount_text="8",
                base_currency_code="CAD",
                fx_rate_text="1",
                fx_source="legacy_identity",
            )
        )
        db.commit()
        db.close()

    def _bridge_result(self, snapshot):
        account_ids = {
            row["id"]: f"actual-account-{index}" for index, row in enumerate(snapshot["accounts"])
        }
        txn_ids = {
            row["id"]: f"actual-txn-{index}" for index, row in enumerate(snapshot["transactions"])
        }
        expected_balances = {row["id"]: row["opening_minor"] for row in snapshot["accounts"]}
        for row in snapshot["transactions"]:
            expected_balances[row["account_id"]] += row["amount_minor"]
        transactions = []
        transfer_lookup = {}
        transfer_target = {}
        for pair in snapshot["transfer_pairs"]:
            transfer_lookup[pair["left"]["id"]] = txn_ids[pair["right"]["id"]]
            transfer_lookup[pair["right"]["id"]] = txn_ids[pair["left"]["id"]]
            transfer_target[pair["left"]["id"]] = pair["right"]["account_id"]
            transfer_target[pair["right"]["id"]] = pair["left"]["account_id"]
        named_payee_ids = {
            name: f"payee-{index}" for index, name in enumerate(snapshot["payee_names"])
        }
        transfer_payee_ids = {source_id: f"transfer-payee-{source_id}" for source_id in account_ids}
        for row in snapshot["transactions"]:
            transactions.append(
                {
                    "id": txn_ids[row["id"]],
                    "account": account_ids[row["account_id"]],
                    "date": row["date"],
                    "amount": row["amount_minor"],
                    "payee": (
                        transfer_payee_ids[transfer_target[row["id"]]]
                        if row["transfer_id"]
                        else named_payee_ids.get(row["payee"])
                    ),
                    "payee_name": "transfer account" if row["transfer_id"] else row["payee"],
                    "category_name": "" if row["transfer_id"] else row["category"],
                    "notes": row["notes"],
                    "cleared": row["cleared"],
                    "imported_id": row["import_identity"],
                    "transfer_id": transfer_lookup.get(row["id"]),
                }
            )
        category_ids = {
            name: f"category-{index}" for index, name in enumerate(snapshot["category_names"])
        }
        budget_links = []
        month_groups = {}
        for row in snapshot["budget_assignments"]:
            category_id = category_ids[row["category"]]
            budget_links.append(
                {
                    "kind": "budget_assignment",
                    "source_id": row["id"],
                    "actual_id": f"{row['month']}:{category_id}",
                    "metadata": row["metadata"],
                }
            )
            month_groups.setdefault(row["month"], []).append(
                {"id": category_id, "budgeted": row["amount_minor"]}
            )
        schedule_links = []
        schedules = []
        for index, row in enumerate(snapshot["schedules"]):
            actual_id = f"schedule-{index}"
            schedule_links.append(
                {
                    "kind": row["kind"],
                    "source_id": row["id"],
                    "actual_id": actual_id,
                    "metadata": row["metadata"],
                }
            )
            schedules.append(
                {
                    "id": actual_id,
                    "amount": row["amount_minor"],
                    "name": row["name"],
                    "account": account_ids.get(row["account_id"]),
                    "payee": named_payee_ids[row["payee"] or row["name"]],
                    "date": actual_migration._schedule_date(row),
                    "next_date": row["next_date"],
                    "completed": not row["active"],
                    "posts_transaction": row["posts_transaction"],
                    "amountOp": "is",
                }
            )
        links = [
            *(
                {
                    "kind": "account",
                    "source_id": row["id"],
                    "actual_id": account_ids[row["id"]],
                    "metadata": row["evidence"],
                }
                for row in snapshot["accounts"]
            ),
            *(
                {
                    "kind": "transaction",
                    "source_id": row["id"],
                    "actual_id": txn_ids[row["id"]],
                    "metadata": row["evidence"],
                }
                for row in snapshot["transactions"]
            ),
            *(
                {
                    "kind": "transfer",
                    "source_id": row["id"],
                    "actual_id": (f"{txn_ids[row['left']['id']]}:{txn_ids[row['right']['id']]}"),
                    "metadata": {},
                }
                for row in snapshot["transfer_pairs"]
            ),
            *budget_links,
            *schedule_links,
        ]
        return {
            "budget_id": "actual-budget",
            "sync_id": "actual-sync",
            "links": links,
            "actual": {
                "accounts": [
                    {
                        "id": account_ids[row["id"]],
                        "name": row["name"],
                        "balance": expected_balances[row["id"]],
                        "offbudget": row["kind"] == "investment",
                        "closed": row["archived"],
                    }
                    for row in snapshot["accounts"]
                ],
                "transactions": transactions,
                "categories": [
                    {"id": category_ids[name], "name": name} for name in snapshot["category_names"]
                ],
                "payees": [
                    {"id": named_payee_ids[name], "name": name, "transfer_acct": None}
                    for name in snapshot["payee_names"]
                ]
                + [
                    {
                        "id": transfer_payee_ids[source_id],
                        "name": f"Transfer: {source_id}",
                        "transfer_acct": actual_id,
                    }
                    for source_id, actual_id in account_ids.items()
                ],
                "budget_months": [
                    {"month": month, "categoryGroups": [{"categories": categories}]}
                    for month, categories in month_groups.items()
                ],
                "schedules": schedules,
            },
        }

    def test_snapshot_maps_every_required_entity_and_exact_evidence(self):
        db = self.db()
        snapshot = actual_migration.build_snapshot(
            db, base_currency_code="CAD", migration_run_id="run-first"
        )
        restaged = actual_migration.build_snapshot(
            db, base_currency_code="CAD", migration_run_id="run-second"
        )
        db.close()
        self.assertEqual(len(snapshot["accounts"]), 2)
        self.assertEqual(len(snapshot["transactions"]), 3)
        self.assertEqual(len(snapshot["transfer_pairs"]), 1)
        self.assertEqual(len(snapshot["budget_assignments"]), 1)
        tag_budget = next(row for row in snapshot["sidecar_links"] if row["kind"] == "tag_budget")
        self.assertEqual(tag_budget["metadata"], {"tag": "coffee", "limit_minor": 2500})
        self.assertTrue(all(row["category"] for row in snapshot["budget_assignments"]))
        self.assertEqual(
            {row["kind"] for row in snapshot["schedules"]}, {"recurring", "subscription"}
        )
        self.assertEqual(len(snapshot["subscriptions"]), 1)
        self.assertEqual(len(snapshot["subscription_payments"]), 1)
        subscription = next(row for row in snapshot["schedules"] if row["kind"] == "subscription")
        self.assertEqual(subscription["metadata"]["category"], "software")
        self.assertEqual(snapshot["version"], 3)
        self.assertTrue(
            all(
                row["import_identity"].startswith("alles:migration:run-first:")
                for row in snapshot["transactions"]
            )
        )
        self.assertTrue(
            set(row["import_identity"] for row in snapshot["transactions"]).isdisjoint(
                row["import_identity"] for row in restaged["transactions"]
            )
        )
        imported = next(row for row in snapshot["transactions"] if row["payee"] == "grocer")
        self.assertEqual(
            imported["evidence"]["migration_source_import_identity"],
            "bank:cibc:statement-row-7",
        )
        self.assertTrue(
            all(
                row["evidence"]["migration_source_import_identity"] == ""
                for row in snapshot["transactions"]
                if row["payee"] != "grocer"
            )
        )
        self.assertRegex(snapshot["budget_effective_month"], r"^\d{4}-\d{2}$")
        self.assertTrue(
            all(row["evidence"]["base_currency_code"] == "CAD" for row in snapshot["transactions"])
        )
        self.assertEqual(
            {row["evidence"]["account_kind"] for row in snapshot["accounts"]},
            {"checking", "savings"},
        )
        self.assertTrue(all("color" in row["evidence"] for row in snapshot["accounts"]))

    def test_snapshot_rejects_legacy_transaction_splits_before_staging(self):
        db = self.db()
        transaction_id = db.query(Transaction.id).filter(Transaction.transfer_id == "").scalar()
        db.add(TxnSplit(txn_id=transaction_id, category="food", amount=2.0))
        db.commit()
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "legacy splits"):
            actual_migration.build_snapshot(db, base_currency_code="CAD")
        db.close()

    def test_snapshot_rejects_unbalanced_transfer_base_amounts(self):
        db = self.db()
        leg = db.query(Transaction).filter(Transaction.transfer_id != "").first()
        proof = db.query(MoneyFxEvidence).filter_by(transaction_id=leg.id).one()
        leg.original_amount_text = "9"
        leg.base_amount_text = "9"
        proof.original_amount_text = "9"
        proof.base_amount_text = "9"
        db.commit()

        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError,
            "equal and opposite base amounts",
        ):
            actual_migration.build_snapshot(db, base_currency_code="CAD")
        db.close()

    def test_snapshot_rejects_incomplete_account_and_payment_conversion_evidence(self):
        db = self.db()
        account = db.get(Account, self.left["id"])
        account.opening_fx_rate_text = ""
        db.commit()
        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError,
            f"account {account.id} has incomplete conversion evidence",
        ):
            actual_migration.build_snapshot(db, base_currency_code="CAD")

        account.opening_fx_rate_text = "1"
        payment = db.query(SubPayment).one()
        payment.fx_source = ""
        db.commit()
        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError,
            f"subscription payment {payment.id} has incomplete conversion evidence",
        ):
            actual_migration.build_snapshot(db, base_currency_code="CAD")

        payment.fx_source = "owner_reviewed"
        payment.original_amount_text = "100.00"
        payment.original_currency_code = "CNY"
        payment.base_amount_text = "20.00"
        payment.base_currency_code = "CAD"
        payment.fx_rate_text = "0.3"
        payment.fx_rate_date = "2026-07-19"
        db.commit()
        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError,
            f"subscription payment {payment.id} has contradictory conversion evidence",
        ):
            actual_migration.build_snapshot(db, base_currency_code="CAD")
        db.close()

    def test_snapshot_rejects_dangling_subscription_payment_relationships(self):
        db = self.db()
        payment = db.query(SubPayment).one()
        original_subscription_id = payment.sub_id
        payment.sub_id = "missing-subscription"
        db.commit()
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "missing subscription"):
            actual_migration.build_snapshot(db, base_currency_code="CAD")

        payment.sub_id = original_subscription_id
        payment.txn_id = "missing-transaction"
        db.commit()
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "missing transaction"):
            actual_migration.build_snapshot(db, base_currency_code="CAD")
        db.close()

    def test_snapshot_preserves_persistent_cap_when_current_assignment_already_exists(self):
        db = self.db()
        db.add(Budget(category="food", tag="", limit_amt=40))
        db.commit()
        snapshot = actual_migration.build_snapshot(
            db,
            base_currency_code="CAD",
            today=date(2026, 7, 18),
        )
        cap = next(
            row
            for row in snapshot["sidecar_links"]
            if row["kind"] == "budget_limit" and row["metadata"]["category"] == "food"
        )
        self.assertEqual(
            cap["metadata"],
            {
                "category": "food",
                "limit_minor": 4000,
                "managed_month": "",
                "source": "legacy_persistent_cap",
            },
        )
        assignments = [
            row
            for row in snapshot["budget_assignments"]
            if row["month"] == "2026-07" and row["category"] == "food"
        ]
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]["amount_minor"], 5000)
        db.close()
        self.assertTrue(all("low_balance" in row["evidence"] for row in snapshot["accounts"]))
        imported = next(row for row in snapshot["transactions"] if not row["transfer_id"])
        self.assertEqual(imported["evidence"]["tags"], "groceries,weekly")
        self.assertEqual(imported["evidence"]["receipt_id"], "receipt-1")
        self.assertEqual(imported["evidence"]["import_batch_id"], "batch-1")
        self.assertEqual(imported["evidence"]["import_source"], "finance_import:cibc_csv")
        self.assertEqual(imported["evidence"]["import_row_number"], 7)
        self.assertEqual(imported["evidence"]["import_receipt_json"], '{"version":1}')
        transfer = next(row for row in snapshot["transactions"] if row["transfer_id"])
        self.assertEqual(transfer["evidence"]["migration_source_category"], transfer["category"])
        self.assertEqual(
            transfer["evidence"]["migration_source_transfer_id"], transfer["transfer_id"]
        )

    def test_stage_cutover_and_rollback_keep_legacy_rows_unchanged(self):
        db = self.db()
        before = [
            (row.id, row.amount, row.payee)
            for row in db.query(Transaction).order_by(Transaction.id)
        ]
        result = None
        migration_request = None

        def bridge(request, timeout):
            nonlocal migration_request, result
            if request["command"] == "migrate":
                migration_request = copy.deepcopy(request)
                result = self._bridge_result(request["snapshot"])
                return result
            return result["actual"]

        staged = actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)
        self.assertEqual(staged["status"], "ready")
        self.assertTrue(staged["report"]["pass"])
        self.assertEqual(migration_request["operation_marker"], migration_request["budget_name"])
        self.assertIs(migration_request["replace_existing_staging"], True)
        self.assertEqual(migration_request["budget_name"], f"Alles staged {staged['id']}")
        cutover = actual_migration.cutover(
            db,
            staged["id"],
            bridge_request=bridge,
            backup_fn=lambda: {"ok": True, "backup_id": "actual-test-backup"},
        )
        self.assertEqual(cutover["mode"], "actual")
        self.assertTrue(cutover["legacy_read_only"])
        during = [
            (row.id, row.amount, row.payee)
            for row in db.query(Transaction).order_by(Transaction.id)
        ]
        self.assertEqual(before, during)
        rolled_back = actual_migration.rollback(db, bridge_request=bridge)
        self.assertEqual(rolled_back["mode"], "alles")
        self.assertFalse(rolled_back["legacy_read_only"])
        after = [
            (row.id, row.amount, row.payee)
            for row in db.query(Transaction).order_by(Transaction.id)
        ]
        self.assertEqual(before, after)
        db.close()

    def test_stage_cleans_and_records_budget_when_python_parity_fails(self):
        db = self.db()
        requests = []

        def bridge(request, timeout):
            requests.append((copy.deepcopy(request), timeout))
            if request["command"] == "migrate":
                result = self._bridge_result(request["snapshot"])
                result["actual"]["accounts"][0]["name"] = "parity mismatch"
                return result
            self.assertEqual(request["command"], "delete_staged_budget")
            return {
                "budget_id": request["budget_id"],
                "deleted": True,
                "verified_absent": True,
            }

        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "parity check failed"):
            actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)

        failed = db.query(ActualMigrationRun).order_by(ActualMigrationRun.created_at.desc()).first()
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.actual_budget_id, "actual-budget")
        self.assertEqual(failed.actual_sync_id, "actual-sync")
        self.assertIn("cleanup verified", failed.error)
        self.assertEqual(
            [request[0]["command"] for request in requests], ["migrate", "delete_staged_budget"]
        )
        cleanup = requests[1][0]
        self.assertEqual(cleanup["budget_id"], "actual-budget")
        self.assertEqual(cleanup["sync_id"], "actual-sync")
        db.close()

    def test_next_stage_retries_a_required_budget_cleanup_before_migrating(self):
        db = self.db()

        def failing_bridge(request, timeout):
            if request["command"] == "migrate":
                result = self._bridge_result(request["snapshot"])
                result["actual"]["accounts"][0]["name"] = "parity mismatch"
                return result
            raise RuntimeError("cleanup unavailable")

        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "must be retried"):
            actual_migration.stage(db, base_currency_code="CAD", bridge_request=failing_bridge)
        pending = db.query(ActualMigrationRun).one()
        self.assertEqual(pending.status, "cleanup_required")
        self.assertEqual(pending.actual_budget_id, "actual-budget")

        commands = []

        def retry_bridge(request, timeout):
            commands.append(request["command"])
            if request["command"] == "delete_staged_budget":
                return {
                    "budget_id": request["budget_id"],
                    "deleted": False,
                    "verified_absent": True,
                }
            return self._bridge_result(request["snapshot"])

        staged = actual_migration.stage(db, base_currency_code="CAD", bridge_request=retry_bridge)
        db.refresh(pending)
        self.assertEqual(commands, ["delete_staged_budget", "migrate"])
        self.assertEqual(pending.status, "failed")
        self.assertIn("cleanup retry verified", pending.error)
        self.assertEqual(staged["status"], "ready")
        db.close()

    def test_restaging_deletes_and_invalidates_the_previous_verified_candidate(self):
        db = self.db()
        commands = []

        def bridge(request, timeout):
            commands.append(request["command"])
            if request["command"] == "delete_staged_budget":
                return {
                    "budget_id": request["budget_id"],
                    "deleted": True,
                    "verified_absent": True,
                }
            return self._bridge_result(request["snapshot"])

        first = actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)
        second = actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)

        first_run = db.get(ActualMigrationRun, first["id"])
        state = db.get(FinanceLedgerState, "primary")
        self.assertEqual(commands, ["migrate", "delete_staged_budget", "migrate"])
        self.assertEqual(first_run.status, "superseded")
        self.assertIn("candidate cleanup verified", first_run.error)
        self.assertEqual(state.active_run_id, second["id"])
        self.assertEqual(db.query(ActualMigrationRun).filter_by(status="ready").count(), 1)
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "freshly verified"):
            actual_migration.cutover(db, first["id"], bridge_request=bridge)
        db.close()

    def test_next_stage_requires_manual_reconciliation_for_identified_staging_run(self):
        db = self.db()
        interrupted = ActualMigrationRun(
            id="interrupted-stage",
            status="staging",
            base_currency_code="CAD",
            snapshot_sha256="interrupted-snapshot",
            snapshot_path="/tmp/interrupted-actual-snapshot.json",
            actual_budget_id="interrupted-budget",
            actual_sync_id="interrupted-sync",
        )
        db.add(interrupted)
        db.commit()
        commands = []

        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError,
            "manual reconciliation is required",
        ):
            actual_migration.stage(
                db,
                base_currency_code="CAD",
                bridge_request=lambda request, timeout: commands.append(request["command"]),
            )
        db.refresh(interrupted)
        self.assertEqual(commands, [])
        self.assertEqual(interrupted.status, "staging")
        db.close()

    def test_next_stage_blocks_an_unidentified_run_interrupted_while_staging(self):
        db = self.db()
        db.add(
            ActualMigrationRun(
                id="unidentified-stage",
                status="staging",
                base_currency_code="CAD",
                snapshot_sha256="unidentified-snapshot",
                snapshot_path="/tmp/unidentified-actual-snapshot.json",
            )
        )
        db.commit()
        requests = []

        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError,
            "manual reconciliation is required",
        ):
            actual_migration.stage(
                db,
                base_currency_code="CAD",
                bridge_request=lambda request, timeout: requests.append((request, timeout)),
            )

        self.assertEqual(requests, [])
        self.assertEqual(db.get(ActualMigrationRun, "unidentified-stage").status, "staging")
        db.close()

    def test_indeterminate_migrate_failure_stays_staging_and_blocks_the_next_run(self):
        db = self.db()

        def timed_out(_request, timeout):
            self.assertEqual(timeout, 300)
            raise TimeoutError("bridge timed out")

        with self.assertRaisesRegex(TimeoutError, "bridge timed out"):
            actual_migration.stage(
                db,
                base_currency_code="CAD",
                bridge_request=timed_out,
            )

        interrupted = db.query(ActualMigrationRun).one()
        self.assertEqual(interrupted.status, "staging")
        self.assertFalse(interrupted.actual_budget_id)
        self.assertIn("manual reconciliation is required", interrupted.error)
        requests = []
        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError,
            "manual reconciliation is required",
        ):
            actual_migration.stage(
                db,
                base_currency_code="CAD",
                bridge_request=lambda request, timeout: requests.append((request, timeout)),
            )
        self.assertEqual(requests, [])
        db.close()

    def test_preexecution_bridge_failure_is_retryable(self):
        db = self.db()

        class PreexecutionFailure(RuntimeError):
            staging_possible = False

        with self.assertRaisesRegex(PreexecutionFailure, "runtime unavailable"):
            actual_migration.stage(
                db,
                base_currency_code="CAD",
                bridge_request=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    PreexecutionFailure("runtime unavailable")
                ),
            )

        failed = db.query(ActualMigrationRun).one()
        self.assertEqual(failed.status, "failed")
        self.assertIn("before Actual staging could begin", failed.error)
        staged = actual_migration.stage(
            db,
            base_currency_code="CAD",
            bridge_request=lambda request, timeout: self._bridge_result(request["snapshot"]),
        )
        self.assertEqual(staged["status"], "ready")
        db.close()

    def test_bridge_verified_cleanup_after_migration_failure_is_retryable(self):
        db = self.db()

        def cleaned(_request, timeout):
            self.assertEqual(timeout, 300)
            raise actual_bridge.ActualBridgeError(
                "Actual bridge operation failed with private details withheld",
                code="actual_stage_cleanup_verified",
            )

        with self.assertRaises(actual_bridge.ActualBridgeError):
            actual_migration.stage(
                db,
                base_currency_code="CAD",
                bridge_request=cleaned,
            )

        failed = db.query(ActualMigrationRun).one()
        self.assertEqual(failed.status, "failed")
        self.assertFalse(failed.actual_budget_id)
        self.assertIn("cleanup verified by the bridge", failed.error)
        staged = actual_migration.stage(
            db,
            base_currency_code="CAD",
            bridge_request=lambda request, timeout: self._bridge_result(request["snapshot"]),
        )
        self.assertEqual(staged["status"], "ready")
        db.close()

    def test_structured_migrate_cleanup_failure_records_identity_and_blocks_restaging(self):
        db = self.db()
        commands = []

        def bridge(request, timeout):
            commands.append(request["command"])
            if request["command"] == "migrate":
                raise managed_actual.ManagedActualError(
                    "Actual bridge operation failed with private details withheld",
                    details={
                        "staged_budget": {
                            "budget_id": "identified-budget",
                            "sync_id": "identified-sync",
                        }
                    },
                )
            raise RuntimeError("cleanup unavailable")

        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "must be retried"):
            actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)

        failed = db.query(ActualMigrationRun).one()
        self.assertEqual(failed.status, "cleanup_required")
        self.assertEqual(failed.actual_budget_id, "identified-budget")
        self.assertEqual(failed.actual_sync_id, "identified-sync")
        self.assertEqual(commands, ["migrate", "delete_staged_budget"])
        self.assertNotIn("identified-budget", failed.error)

        commands.clear()
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "requires cleanup"):
            actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)
        self.assertEqual(commands, ["delete_staged_budget"])
        self.assertEqual(db.query(ActualMigrationRun).count(), 1)
        db.close()

    def test_existing_staged_budget_is_bound_without_automatic_deletion(self):
        db = self.db()
        commands = []

        def bridge(request, timeout):
            commands.append(request["command"])
            cause = actual_bridge.ActualBridgeError(
                "existing Actual staging budget requires reconciliation",
                code="actual_stage_reconciliation_required",
            )
            raise managed_actual.ManagedActualError(
                str(cause),
                details={
                    "staged_budget": {
                        "budget_id": "existing-budget",
                        "sync_id": "existing-sync",
                    }
                },
            ) from cause

        with self.assertRaisesRegex(
            managed_actual.ManagedActualError,
            "requires reconciliation",
        ):
            actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)

        run = db.query(ActualMigrationRun).one()
        self.assertEqual(commands, ["migrate"])
        self.assertEqual(run.status, "staging")
        self.assertEqual(run.actual_budget_id, "existing-budget")
        self.assertEqual(run.actual_sync_id, "existing-sync")
        self.assertIn("manual reconciliation", run.error)
        db.close()

    def test_reconcile_refuses_changed_individual_transaction_fields(self):
        db = self.db()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        result = self._bridge_result(snapshot)
        result["actual"]["transactions"][0]["date"] = "2026-07-31"
        report = actual_migration.reconcile(
            snapshot,
            {"actual": result["actual"], "links": [*result["links"], *snapshot["sidecar_links"]]},
        )
        self.assertFalse(report["pass"])
        check = next(row for row in report["checks"] if row["name"] == "transaction field parity")
        self.assertFalse(check["pass"])
        db.close()

    def test_reconcile_refuses_changed_account_name(self):
        db = self.db()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        result = self._bridge_result(snapshot)
        result["actual"]["accounts"][0]["name"] = "wrong account"
        report = actual_migration.reconcile(
            snapshot,
            {"actual": result["actual"], "links": [*result["links"], *snapshot["sidecar_links"]]},
        )
        check = next(
            row
            for row in report["checks"]
            if row["name"] == "account name, kind, and archive state"
        )
        self.assertFalse(check["pass"])
        db.close()

    def test_reconcile_checks_every_account_currency_evidence_field(self):
        db = self.db()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        result = self._bridge_result(snapshot)
        payload = {
            "actual": result["actual"],
            "links": [*result["links"], *snapshot["sidecar_links"]],
        }
        for field in snapshot["accounts"][0]["evidence"]:
            with self.subTest(field=field):
                changed = copy.deepcopy(payload)
                link = next(
                    row
                    for row in changed["links"]
                    if row["kind"] == "account"
                    and row["source_id"] == snapshot["accounts"][0]["id"]
                )
                link["metadata"][field] = "changed"
                report = actual_migration.reconcile(snapshot, changed)
                check = next(
                    row
                    for row in report["checks"]
                    if row["name"] == "account currency and display evidence"
                )
                self.assertFalse(check["pass"])
        db.close()

    def test_reconcile_requires_bijective_canonical_entities(self):
        db = self.db()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")

        extra = self._bridge_result(snapshot)
        unexpected = copy.deepcopy(extra["actual"]["transactions"][0])
        unexpected.update({"id": "unexpected-row", "imported_id": "unexpected-import"})
        extra["actual"]["transactions"].append(unexpected)
        extra_report = actual_migration.reconcile(
            snapshot,
            {"actual": extra["actual"], "links": [*extra["links"], *snapshot["sidecar_links"]]},
        )
        extra_check = next(
            row for row in extra_report["checks"] if row["name"] == "transaction identity bijection"
        )
        self.assertFalse(extra_check["pass"])

        duplicate = self._bridge_result(snapshot)
        account_links = [row for row in duplicate["links"] if row["kind"] == "account"]
        account_links[1]["actual_id"] = account_links[0]["actual_id"]
        duplicate_report = actual_migration.reconcile(
            snapshot,
            {
                "actual": duplicate["actual"],
                "links": [*duplicate["links"], *snapshot["sidecar_links"]],
            },
        )
        duplicate_check = next(
            row for row in duplicate_report["checks"] if row["name"] == "account identity bijection"
        )
        self.assertFalse(duplicate_check["pass"])
        db.close()

    def test_reconcile_refuses_wrong_transfer_payee_semantics(self):
        db = self.db()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        result = self._bridge_result(snapshot)
        transfer_row = next(row for row in result["actual"]["transactions"] if row["transfer_id"])
        transfer_row["payee"] = next(
            row["id"] for row in result["actual"]["payees"] if not row.get("transfer_acct")
        )
        report = actual_migration.reconcile(
            snapshot,
            {"actual": result["actual"], "links": [*result["links"], *snapshot["sidecar_links"]]},
        )
        check = next(row for row in report["checks"] if row["name"] == "transaction field parity")
        self.assertFalse(check["pass"])
        db.close()

    def test_reconcile_requires_each_transfer_link_to_name_its_exact_pair(self):
        db = self.db()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        result = self._bridge_result(snapshot)
        transfer_link = next(row for row in result["links"] if row["kind"] == "transfer")
        left, right = transfer_link["actual_id"].split(":", 1)
        transfer_link["actual_id"] = f"{right}:{left}"
        report = actual_migration.reconcile(
            snapshot,
            {"actual": result["actual"], "links": [*result["links"], *snapshot["sidecar_links"]]},
        )
        check = next(
            row for row in report["checks"] if row["name"] == "transfer link identity bijection"
        )
        self.assertFalse(check["pass"])
        db.close()

    def test_reconcile_checks_complete_schedule_semantics(self):
        db = self.db()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        mutations = {
            "name": lambda row: row.__setitem__("name", "wrong"),
            "account": lambda row: row.__setitem__("account", "wrong"),
            "payee": lambda row: row.__setitem__("payee", "wrong"),
            "cadence": lambda row: row["date"].__setitem__("interval", 9),
            "active state": lambda row: row.__setitem__("completed", not row["completed"]),
            "posting": lambda row: row.__setitem__(
                "posts_transaction", not row["posts_transaction"]
            ),
            "amount operator": lambda row: row.__setitem__("amountOp", "isapprox"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                result = self._bridge_result(snapshot)
                mutate(result["actual"]["schedules"][0])
                report = actual_migration.reconcile(
                    snapshot,
                    {
                        "actual": result["actual"],
                        "links": [*result["links"], *snapshot["sidecar_links"]],
                    },
                )
                check = next(row for row in report["checks"] if row["name"] == "schedules")
                self.assertFalse(check["pass"])
        db.close()

    def test_reconcile_requires_the_budget_cap_link_to_target_the_named_category(self):
        db = self.db()
        db.add(Budget(category="food", tag="", limit_amt=40))
        db.commit()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        result = self._bridge_result(snapshot)
        bound_sidecars = actual_migration._bind_sidecar_links(snapshot, result)
        self.assertEqual(
            {(row["kind"], row["source_id"]) for row in bound_sidecars},
            {(row["kind"], row["source_id"]) for row in snapshot["sidecar_links"]},
        )
        cap_link = next(row for row in bound_sidecars if row["kind"] == "budget_limit")
        linked_category = next(
            row for row in result["actual"]["categories"] if row["id"] == cap_link["actual_id"]
        )
        original_name = linked_category["name"]
        linked_category["name"] = "renamed category"
        result["actual"]["categories"].append({"id": "replacement-category", "name": original_name})
        report = actual_migration.reconcile(
            snapshot,
            {"actual": result["actual"], "links": [*result["links"], *bound_sidecars]},
        )
        check = next(
            row for row in report["checks"] if row["name"] == "persistent budget cap bindings"
        )
        self.assertFalse(check["pass"])
        db.close()

    def test_reconcile_requires_budget_assignment_source_and_target_bijection(self):
        db = self.db()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        duplicate = copy.deepcopy(snapshot["budget_assignments"][0])
        duplicate["id"] = "duplicate-assignment-source"
        snapshot["budget_assignments"].append(duplicate)
        result = self._bridge_result(snapshot)

        report = actual_migration.reconcile(snapshot, result)

        check = next(
            row for row in report["checks"] if row["name"] == "budget assignment identity bijection"
        )
        self.assertFalse(check["pass"])
        self.assertFalse(report["pass"])
        db.close()

    def test_cutover_and_rollback_reuse_the_staged_budget_month(self):
        db = self.db()
        result = None

        def bridge(request, timeout):
            nonlocal result
            if request["command"] == "migrate":
                result = self._bridge_result(request["snapshot"])
                return result
            return result["actual"]

        staged = actual_migration.stage(
            db,
            base_currency_code="CAD",
            bridge_request=bridge,
            today=date(2025, 12, 31),
        )
        cutover = actual_migration.cutover(
            db,
            staged["id"],
            bridge_request=bridge,
            backup_fn=lambda: {"ok": True, "backup_id": "month-boundary"},
        )
        self.assertEqual(cutover["mode"], "actual")
        self.assertEqual(actual_migration.rollback(db, bridge_request=bridge)["mode"], "alles")
        db.close()

    def test_rollback_refuses_any_canonical_actual_change_after_cutover(self):
        db = self.db()
        result = None

        def bridge(request, timeout):
            nonlocal result
            if request["command"] == "migrate":
                result = self._bridge_result(request["snapshot"])
                return result
            return result["actual"]

        staged = actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)
        actual_migration.cutover(
            db,
            staged["id"],
            bridge_request=bridge,
            backup_fn=lambda: {"ok": True, "backup_id": "rollback-checkpoint"},
        )
        result["actual"]["transactions"][0]["notes"] = "changed in Actual"
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "changed after cutover"):
            actual_migration.rollback(db, bridge_request=bridge)
        self.assertEqual(db.get(FinanceLedgerState, "primary").mode, "actual")
        db.close()

    def test_rollback_checkpoint_ignores_only_the_computed_schedule_occurrence(self):
        actual = {
            "accounts": [{"id": "account-1", "name": "chequing"}],
            "transactions": [],
            "schedules": [
                {
                    "id": "schedule-1",
                    "name": "rent",
                    "amount": -2000,
                    "date": {"start": "2026-08-01", "frequency": "monthly", "interval": 1},
                    "next_date": "2026-08-01",
                    "rule": "z-last",
                },
                {
                    "id": "schedule-1",
                    "name": "rent",
                    "amount": -2000,
                    "date": {"start": "2026-08-01", "frequency": "monthly", "interval": 1},
                    "next_date": "2026-09-01",
                    "rule": "a-first",
                },
            ],
        }
        checkpoint = actual_migration.actual_checkpoint_sha256(actual)
        advanced = copy.deepcopy(actual)
        advanced["schedules"][0]["next_date"] = "2026-10-01"
        advanced["schedules"][1]["next_date"] = "2026-07-01"
        self.assertEqual(actual_migration.actual_checkpoint_sha256(advanced), checkpoint)
        advanced["schedules"][0]["amount"] = -2500
        self.assertNotEqual(actual_migration.actual_checkpoint_sha256(advanced), checkpoint)

    def test_rollback_refuses_link_only_canonical_edits(self):
        db = self.db()
        result = None

        def bridge(request, timeout):
            nonlocal result
            if request["command"] == "migrate":
                result = self._bridge_result(request["snapshot"])
                return result
            return result["actual"]

        staged = actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)
        actual_migration.cutover(
            db,
            staged["id"],
            bridge_request=bridge,
            backup_fn=lambda: {"ok": True, "backup_id": "link-checkpoint"},
        )
        link = db.query(ActualEntityLink).filter_by(entity_kind="account").first()
        metadata = json.loads(link.metadata_json)
        metadata["color"] = "owner-edited-color"
        link.metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        db.commit()
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "link evidence changed"):
            actual_migration.rollback(db, bridge_request=bridge)
        self.assertEqual(db.get(FinanceLedgerState, "primary").mode, "actual")
        db.close()

    def test_rollback_serializes_against_canonical_writes(self):
        db = self.db()
        result = None

        def bridge(request, timeout):
            nonlocal result
            if request["command"] == "migrate":
                result = self._bridge_result(request["snapshot"])
                return result
            return result["actual"]

        staged = actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)
        actual_migration.cutover(
            db,
            staged["id"],
            bridge_request=bridge,
            backup_fn=lambda: {"ok": True, "backup_id": "serialized"},
        )
        db.close()

        rollback_inspecting = threading.Event()
        release_rollback = threading.Event()
        write_bridge_entered = threading.Event()
        outcomes = {}

        def blocking_bridge(request, timeout):
            rollback_inspecting.set()
            if not release_rollback.wait(5):
                raise RuntimeError("test did not release rollback")
            return result["actual"]

        def run_rollback():
            session = self.db()
            try:
                outcomes["rollback"] = actual_migration.rollback(
                    session, bridge_request=blocking_bridge
                )
            except Exception as exc:  # pragma: no cover - assertion reports the exact failure
                outcomes["rollback_error"] = exc
            finally:
                session.close()

        def run_write():
            session = self.db()

            def write_bridge(payload, timeout):
                write_bridge_entered.set()
                return {}

            try:
                actual_finance.create_transaction(
                    session,
                    {
                        "account_id": self.left["id"],
                        "date": "2026-07-19",
                        "amount": "1.00",
                    },
                    bridge_request=write_bridge,
                )
            except Exception as exc:
                outcomes["write_error"] = exc
            finally:
                session.close()

        rollback_thread = threading.Thread(target=run_rollback)
        write_thread = threading.Thread(target=run_write)
        rollback_thread.start()
        self.assertTrue(rollback_inspecting.wait(2))
        write_thread.start()
        self.assertFalse(write_bridge_entered.wait(0.1))
        release_rollback.set()
        rollback_thread.join(5)
        write_thread.join(5)
        self.assertFalse(rollback_thread.is_alive())
        self.assertFalse(write_thread.is_alive())
        self.assertEqual(outcomes["rollback"]["mode"], "alles")
        self.assertIsInstance(outcomes.get("write_error"), actual_finance.ActualFinanceError)
        self.assertFalse(write_bridge_entered.is_set())

    def test_fresh_restore_validation_checks_shape_references_and_transfers(self):
        valid = {
            "accounts": [{"id": "a1"}, {"id": "a2"}],
            "transactions": [
                {"id": "t1", "account": "a1", "transfer_id": "t2"},
                {"id": "t2", "account": "a2", "transfer_id": "t1"},
            ],
            "payees": [],
            "categories": [],
            "category_groups": [],
            "schedules": [],
            "budget_months": [],
        }
        self.assertTrue(actual_migration.validate_fresh_readback(valid)["ok"])
        broken = {**valid, "transactions": [{"id": "t1", "account": "missing"}]}
        self.assertFalse(actual_migration.validate_fresh_readback(broken)["ok"])

    def test_restore_validation_requires_every_active_canonical_link(self):
        db = self.db()
        snapshot = {
            "version": 2,
            "base_currency_code": "CAD",
            "accounts": [
                {
                    "id": "source-account",
                    "name": "chequing",
                    "kind": "checking",
                    "archived": False,
                    "opening_minor": 250,
                    "evidence": {},
                }
            ],
            "transactions": [
                {
                    "id": "source-transaction",
                    "account_id": "source-account",
                    "date": "2026-07-01",
                    "amount_minor": -100,
                    "category": "",
                    "payee": "",
                    "notes": "paired",
                    "cleared": True,
                    "transfer_id": "source-transfer",
                    "import_identity": "restore-transaction",
                    "evidence": {},
                }
            ],
            "schedules": [
                {
                    "kind": "recurring",
                    "id": "source-recurring",
                    "name": "rent",
                    "account_id": "source-account",
                    "payee": "landlord",
                    "amount_minor": -2000,
                    "next_date": "2026-08-01",
                    "cycle": "monthly",
                    "cycle_days": 30,
                    "active": True,
                    "posts_transaction": True,
                },
                {
                    "kind": "subscription",
                    "id": "source-subscription",
                    "name": "mail",
                    "account_id": "source-account",
                    "payee": "mail",
                    "amount_minor": -800,
                    "next_date": "2026-08-05",
                    "cycle": "monthly",
                    "cycle_days": 30,
                    "active": True,
                    "posts_transaction": True,
                    "metadata": {"category": "software"},
                },
            ],
            "budget_assignments": [
                {
                    "id": "source-budget",
                    "category": "food",
                    "month": "2026-07",
                    "amount_minor": 5000,
                    "metadata": {},
                }
            ],
        }
        snapshot_path = actual_migration._write_snapshot("restore-run", snapshot)
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary", base_currency_code="CAD")
            db.add(state)
        state.mode = "actual"
        state.active_run_id = "restore-run"
        db.add(
            ActualMigrationRun(
                id="restore-run",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256=actual_migration.snapshot_sha256(snapshot),
                snapshot_path=str(snapshot_path),
            )
        )
        for kind, source_id, actual_id in (
            ("account", "source-account", "a1"),
            ("transaction", "source-transaction", "t1"),
            ("recurring", "source-recurring", "s1"),
            ("subscription", "source-subscription", "s2"),
            ("budget_assignment", "source-budget", "2026-07:c1"),
            ("transfer", "source-transfer", "t1:t2"),
        ):
            db.add(
                ActualEntityLink(
                    run_id="restore-run",
                    entity_kind=kind,
                    source_id=source_id,
                    actual_id=actual_id,
                    metadata_json=('{"category":"software"}' if kind == "subscription" else "{}"),
                )
            )
        db.commit()
        valid = {
            "accounts": [
                {"id": "a1", "name": "chequing", "offbudget": False, "closed": False},
                {"id": "a2", "name": "savings", "offbudget": False, "closed": False},
            ],
            "transactions": [
                {
                    "id": "starting-a1",
                    "account": "a1",
                    "date": "2026-07-01",
                    "amount": 250,
                    "starting_balance_flag": True,
                },
                {
                    "id": "t1",
                    "account": "a1",
                    "date": "2026-07-01",
                    "amount": -100,
                    "notes": "paired",
                    "cleared": True,
                    "transfer_id": "t2",
                },
                {
                    "id": "t2",
                    "account": "a2",
                    "date": "2026-07-01",
                    "amount": 100,
                    "notes": "paired",
                    "cleared": True,
                    "transfer_id": "t1",
                },
            ],
            "payees": [
                {"id": "p1", "name": "landlord"},
                {"id": "p2", "name": "mail"},
            ],
            "categories": [{"id": "c1", "name": "food"}],
            "category_groups": [],
            "schedules": [
                {
                    "id": "s1",
                    "name": "rent",
                    "account": "a1",
                    "payee": "p1",
                    "amount": -2000,
                    "date": {"start": "20260801", "frequency": "monthly", "interval": 1},
                    "completed": False,
                    "posts_transaction": True,
                    "amountOp": "is",
                },
                {
                    "id": "s2",
                    "name": "mail",
                    "account": "a1",
                    "payee": "p2",
                    "amount": -800,
                    "date": {"start": "20260805", "frequency": "monthly", "interval": 1},
                    "completed": False,
                    "posts_transaction": True,
                    "amountOp": "is",
                },
            ],
            "budget_months": [
                {
                    "month": "2026-07",
                    "categoryGroups": [{"categories": [{"id": "c1", "budgeted": 5000}]}],
                }
            ],
        }
        valid_result = actual_migration.validate_active_links(db, valid)
        self.assertTrue(valid_result["ok"], valid_result)
        altered_opening = copy.deepcopy(valid)
        altered_opening["transactions"][0]["amount"] = 249
        opening_result = actual_migration.validate_active_links(db, altered_opening)
        self.assertFalse(opening_result["ok"])
        self.assertTrue(
            any(
                row.get("kind") == "account" and row.get("content_mismatch")
                for row in opening_result["invalid_links"]
            )
        )
        older = {**valid, "schedules": [{"id": "s2"}]}
        result = actual_migration.validate_active_links(db, older)
        self.assertFalse(result["ok"])
        self.assertIn("older than", result["error"])
        for section, mutate in (
            ("accounts", lambda value: value.__setitem__("name", "restored older name")),
            ("transactions", lambda value: value.__setitem__("amount", -99)),
            ("schedules", lambda value: value.__setitem__("amount", -1999)),
            (
                "budget_months",
                lambda value: value["categoryGroups"][0]["categories"][0].__setitem__(
                    "budgeted", 4999
                ),
            ),
        ):
            changed = copy.deepcopy(valid)
            mutate(changed[section][0])
            mismatch = actual_migration.validate_active_links(db, changed)
            self.assertFalse(mismatch["ok"], section)
            self.assertTrue(
                any(row.get("content_mismatch") for row in mismatch["invalid_links"]),
                section,
            )
        subscription_link = (
            db.query(ActualEntityLink)
            .filter_by(entity_kind="subscription", source_id="source-subscription")
            .one()
        )
        subscription_link.metadata_json = "{}"
        db.flush()
        metadata_mismatch = actual_migration.validate_active_links(db, valid)
        self.assertFalse(metadata_mismatch["ok"])
        self.assertTrue(
            any(
                row.get("kind") == "subscription" and row.get("content_mismatch")
                for row in metadata_mismatch["invalid_links"]
            )
        )
        db.close()

    def test_restore_validation_rejects_a_transaction_that_was_tombstoned(self):
        db = self.db()
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary", base_currency_code="CAD")
            db.add(state)
        state.mode = "actual"
        state.active_run_id = "delete-run"
        db.add(
            ActualMigrationRun(
                id="delete-run",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256="snapshot",
                snapshot_path="/tmp/unused-delete-snapshot",
            )
        )
        db.add(
            ActualEntityLink(
                run_id="delete-run",
                entity_kind="transaction",
                source_id="deleted-source",
                actual_id="",
                metadata_json=('{"_deleted":{"actual_id":"deleted-actual","version":1}}'),
            )
        )
        db.commit()
        absent = {
            "accounts": [{"id": "a1"}],
            "transactions": [],
            "payees": [],
            "categories": [],
            "category_groups": [],
            "schedules": [],
            "budget_months": [],
        }
        self.assertTrue(actual_migration.validate_active_links(db, absent)["ok"])
        restored = {
            **absent,
            "transactions": [{"id": "deleted-actual", "account": "a1"}],
        }
        result = actual_migration.validate_active_links(db, restored)
        self.assertFalse(result["ok"])
        self.assertTrue(result["invalid_links"][0]["deleted_entity_restored"])
        db.close()

    def test_restore_validation_rejects_an_account_that_was_tombstoned(self):
        db = self.db()
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary", base_currency_code="CAD")
            db.add(state)
        state.mode = "actual"
        state.active_run_id = "delete-account-run"
        db.add(
            ActualMigrationRun(
                id="delete-account-run",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256="snapshot",
                snapshot_path="/tmp/unused-delete-account-snapshot",
            )
        )
        db.add(
            ActualEntityLink(
                run_id="delete-account-run",
                entity_kind="account",
                source_id="deleted-account-source",
                actual_id="",
                metadata_json='{"_deleted":{"actual_id":"deleted-account","version":1}}',
            )
        )
        db.commit()
        restored = {
            "accounts": [{"id": "deleted-account"}],
            "transactions": [],
            "payees": [],
            "categories": [],
            "category_groups": [],
            "schedules": [],
            "budget_months": [],
        }
        result = actual_migration.validate_active_links(db, restored)
        self.assertFalse(result["ok"])
        self.assertTrue(result["invalid_links"][0]["deleted_entity_restored"])
        db.close()

    def test_restore_validation_rejects_pending_account_creation_and_update_intents(self):
        db = self.db()
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary", base_currency_code="CAD")
            db.add(state)
        state.mode = "actual"
        state.active_run_id = "pending-account-run"
        db.add_all(
            [
                ActualEntityLink(
                    run_id="pending-account-run",
                    entity_kind="account",
                    source_id="pending-create",
                    actual_id="",
                    metadata_json='{"_intent":{"fingerprint":"create","version":1}}',
                ),
                ActualEntityLink(
                    run_id="pending-account-run",
                    entity_kind="account",
                    source_id="pending-update",
                    actual_id="actual-account",
                    metadata_json=(
                        '{"_update_intent":{"fingerprint":"update","version":1},'
                        '"canonical_account":{"closed":false,"name":"before",'
                        '"offbudget":false}}'
                    ),
                ),
            ]
        )
        db.commit()

        result = actual_migration.validate_active_links(
            db,
            {
                "accounts": [
                    {
                        "id": "actual-account",
                        "name": "before",
                        "offbudget": False,
                        "closed": False,
                    }
                ],
                "transactions": [],
                "payees": [],
                "categories": [],
                "category_groups": [],
                "schedules": [],
                "budget_months": [],
            },
        )

        self.assertFalse(result["ok"])
        invalid = {row["source_id"]: row for row in result["invalid_links"]}
        self.assertTrue(invalid["pending-create"]["pending_creation"])
        self.assertTrue(invalid["pending-update"]["pending_update"])
        db.close()

    def test_restore_validation_rejects_pending_transaction_and_transfer_intents(self):
        db = self.db()
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary", base_currency_code="CAD")
            db.add(state)
        state.mode = "actual"
        state.active_run_id = "pending-write-run"
        db.add_all(
            [
                ActualEntityLink(
                    run_id="pending-write-run",
                    entity_kind="transaction",
                    source_id="pending-transaction",
                    actual_id="",
                    metadata_json='{"_intent":{"fingerprint":"transaction","version":1}}',
                ),
                ActualEntityLink(
                    run_id="pending-write-run",
                    entity_kind="transfer",
                    source_id="pending-transfer",
                    actual_id="",
                    metadata_json='{"_intent":{"fingerprint":"transfer","version":1}}',
                ),
            ]
        )
        db.commit()

        result = actual_migration.validate_active_links(
            db,
            {
                "accounts": [{"id": "actual-account"}],
                "transactions": [],
                "payees": [],
                "categories": [],
                "category_groups": [],
                "schedules": [],
                "budget_months": [],
            },
        )

        self.assertFalse(result["ok"])
        invalid = {row["source_id"]: row for row in result["invalid_links"]}
        self.assertTrue(invalid["pending-transaction"]["pending_creation"])
        self.assertTrue(invalid["pending-transfer"]["pending_creation"])
        db.close()

    def test_restore_validation_rejects_a_resurrected_cleared_budget(self):
        db = self.db()
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary", base_currency_code="CAD")
            db.add(state)
        state.mode = "actual"
        state.active_run_id = "deleted-budget-run"
        db.add(
            ActualMigrationRun(
                id="deleted-budget-run",
                status="canonical",
                base_currency_code="CAD",
                snapshot_sha256="snapshot",
                snapshot_path="/tmp/unused-deleted-budget-snapshot",
            )
        )
        db.add(
            ActualEntityLink(
                run_id="deleted-budget-run",
                entity_kind="budget_limit",
                source_id="deleted-budget",
                actual_id="",
                metadata_json=json.dumps(
                    {
                        "category": "food",
                        "limit_minor": 5000,
                        "managed_month": "2026-07",
                        "_deleted": {"actual_id": "c1", "version": 1},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
        db.add(
            ActualEntityLink(
                run_id="deleted-budget-run",
                entity_kind="budget_assignment",
                source_id="deleted-assignment",
                actual_id="",
                metadata_json=json.dumps(
                    {
                        "source_kind": "assignment",
                        "_deleted": {"actual_id": "2026-08:c2", "version": 1},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
        db.commit()
        restored = {
            "accounts": [],
            "transactions": [],
            "payees": [],
            "categories": [
                {"id": "c1", "name": "food"},
                {"id": "c2", "name": "travel"},
            ],
            "category_groups": [],
            "schedules": [],
            "budget_months": [
                {
                    "month": "2026-07",
                    "categoryGroups": [{"categories": [{"id": "c1", "budgeted": 5000}]}],
                },
                {
                    "month": "2026-08",
                    "categoryGroups": [{"categories": [{"id": "c2", "budgeted": 2500}]}],
                },
            ],
        }
        result = actual_migration.validate_active_links(db, restored)
        self.assertFalse(result["ok"])
        self.assertEqual(
            {row["kind"] for row in result["invalid_links"]},
            {"budget_limit", "budget_assignment"},
        )
        self.assertTrue(all(row["deleted_entity_restored"] for row in result["invalid_links"]))
        restored["budget_months"][0]["categoryGroups"][0]["categories"][0]["budgeted"] = 0
        restored["budget_months"][1]["categoryGroups"][0]["categories"][0]["budgeted"] = 0
        self.assertTrue(actual_migration.validate_active_links(db, restored)["ok"])
        db.close()

    def test_restore_validation_rejects_a_same_name_budget_category_replacement(self):
        db = self.db()
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary", base_currency_code="CAD")
            db.add(state)
        state.mode = "actual"
        state.active_run_id = "budget-replacement-run"
        link = ActualEntityLink(
            run_id="budget-replacement-run",
            entity_kind="budget_limit",
            source_id="persistent-food-cap",
            actual_id="original-food-id",
            metadata_json=json.dumps(
                {
                    "category": "food",
                    "limit_minor": 5000,
                    "managed_month": "2026-07",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        db.add(link)
        db.commit()
        restored = {
            "accounts": [],
            "transactions": [],
            "payees": [],
            "categories": [{"id": "replacement-food-id", "name": "food"}],
            "category_groups": [],
            "schedules": [],
            "budget_months": [
                {
                    "month": "2026-07",
                    "categoryGroups": [
                        {"categories": [{"id": "replacement-food-id", "budgeted": 5000}]}
                    ],
                }
            ],
        }

        result = actual_migration.validate_active_links(db, restored)

        self.assertFalse(result["ok"])
        self.assertEqual(result["invalid_links"][0]["source_id"], "persistent-food-cap")
        self.assertEqual(link.actual_id, "original-food-id")
        db.close()

    def test_cutover_refuses_a_legacy_change_after_staging(self):
        db = self.db()
        result = None

        def bridge(request, timeout):
            nonlocal result
            if request["command"] == "migrate":
                result = self._bridge_result(request["snapshot"])
                return result
            return result["actual"]

        staged = actual_migration.stage(db, base_currency_code="CAD", bridge_request=bridge)
        row = db.query(Transaction).first()
        row.amount += 1
        row.base_amount_text = str(row.amount)
        row.original_amount_text = str(row.amount)
        proof = db.query(MoneyFxEvidence).filter_by(transaction_id=row.id).one()
        proof.base_amount_text = str(row.amount)
        proof.original_amount_text = str(row.amount)
        db.commit()
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "changed after staging"):
            actual_migration.cutover(db, staged["id"], bridge_request=bridge, backup_fn=lambda: {})
        self.assertEqual(db.get(FinanceLedgerState, "primary").mode, "alles")
        db.close()

    def test_unsupported_precision_and_mixed_base_currency_fail_closed(self):
        db = self.db()
        row = db.query(Transaction).first()
        row.base_amount_text = "0.001"
        proof = db.query(MoneyFxEvidence).filter_by(transaction_id=row.id).one()
        proof.base_amount_text = "0.001"
        db.commit()
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "precision"):
            actual_migration.build_snapshot(db, base_currency_code="CAD")
        row.base_amount_text = "1.00"
        row.base_currency_code = "CNY"
        proof.base_amount_text = "1.00"
        proof.base_currency_code = "CNY"
        db.commit()
        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError, "no base amount evidence in CAD"
        ):
            actual_migration.build_snapshot(db, base_currency_code="CAD")
        db.close()

    def test_snapshot_rejects_unsupported_and_inexact_schedule_recurrences(self):
        db = self.db()
        recurring = db.query(RecurringTxn).first()
        recurring.cycle = "fortnightly"
        db.commit()
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "cannot be represented"):
            actual_migration.build_snapshot(db, base_currency_code="CAD")

        recurring.cycle = "custom"
        recurring.cycle_days = 0
        db.commit()
        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError, "interval cannot be represented"
        ):
            actual_migration.build_snapshot(db, base_currency_code="CAD")

        recurring.cycle_days = actual_finance.MAX_CUSTOM_RECURRENCE_DAYS + 1
        db.commit()
        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError, "interval cannot be represented"
        ):
            actual_migration.build_snapshot(db, base_currency_code="CAD")

        recurring.cycle = "monthly"
        recurring.anchor_day = 29
        db.commit()
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "short months"):
            actual_migration.build_snapshot(db, base_currency_code="CAD")

        recurring.anchor_day = 31
        recurring.next_date = "2026-07-31"
        db.commit()
        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        schedule = next(row for row in snapshot["schedules"] if row["kind"] == "recurring")
        self.assertEqual(schedule["anchor_day"], 31)
        self.assertEqual(
            actual_migration._schedule_date(schedule)["patterns"],
            [{"type": "day", "value": -1}],
        )
        db.close()

    def test_snapshot_export_rejects_a_symlinked_managed_directory(self):
        with tempfile.TemporaryDirectory(prefix="alles-actual-snapshot-test-") as temp:
            base = Path(temp)
            managed_root = base / "managed"
            outside = base / "outside"
            managed_root.mkdir()
            outside.mkdir()
            (managed_root / "migration-exports").symlink_to(outside, target_is_directory=True)
            with (
                mock.patch.object(managed_actual, "root_dir", return_value=managed_root),
                self.assertRaisesRegex(actual_migration.ActualMigrationError, "unsafe symlink"),
            ):
                actual_migration._write_snapshot("unsafe-run", {"accounts": []})
            self.assertEqual(list(outside.iterdir()), [])

    def test_snapshot_preserves_subcent_original_currency_conversion_evidence(self):
        db = self.db()
        row = db.query(Transaction).filter_by(transfer_id="").one()
        proof = db.query(MoneyFxEvidence).filter_by(transaction_id=row.id).one()
        for target in (row, proof):
            target.original_amount_text = "1.234"
            target.original_currency_code = "KWD"
            target.base_amount_text = "2.47"
            target.base_currency_code = "CAD"
        proof.rate_text = "2"
        proof.rate_date = "2026-07-01"
        proof.source = "owner_reviewed"
        db.commit()

        snapshot = actual_migration.build_snapshot(db, base_currency_code="CAD")
        migrated = next(item for item in snapshot["transactions"] if item["id"] == row.id)
        self.assertEqual(migrated["amount_minor"], 247)
        self.assertEqual(migrated["evidence"]["original_amount_text"], "1.234")
        self.assertEqual(migrated["evidence"]["original_currency_code"], "KWD")
        db.close()

    def test_recurring_schedule_in_a_non_base_account_fails_closed(self):
        db = self.db()
        account = db.get(Account, self.left["id"])
        account.currency = "USD"
        account.currency_code = "USD"
        account.base_currency_code = "CAD"
        account.base_opening_text = "125"
        account.opening_fx_rate_text = "1.25"
        account.opening_fx_rate_date = "2026-07-01"
        account.opening_fx_source = "owner_reviewed"
        db.commit()

        with self.assertRaisesRegex(
            actual_migration.ActualMigrationError,
            "review and convert it before staging",
        ):
            actual_migration.build_snapshot(db, base_currency_code="CAD")
        db.close()

    def test_snapshot_minor_units_match_the_canonical_cent_safe_range(self):
        self.assertEqual(
            actual_migration._minor("70368744177663.99", "amount"),
            7_036_874_417_766_399,
        )
        with self.assertRaisesRegex(actual_migration.ActualMigrationError, "exact numeric range"):
            actual_migration._minor("70368744177664.01", "amount")


if __name__ == "__main__":
    import unittest

    unittest.main()
