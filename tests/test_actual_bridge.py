import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services import actual_bridge


class ActualBridgeTests(unittest.TestCase):
    def test_locked_bridge_files_and_exact_versions_exist(self):
        package = json.loads(actual_bridge.package_json().read_text("utf-8"))
        self.assertEqual(
            package["dependencies"],
            {
                "@actual-app/api": "26.7.0",
                "@actual-app/cli": "26.7.0",
                "@actual-app/sync-server": "26.7.0",
            },
        )
        self.assertTrue(actual_bridge.lockfile().is_file())
        self.assertTrue(actual_bridge.bridge_script().is_file())

    def test_bridge_staging_and_transfer_guards_are_ordered_before_mutation(self):
        source = actual_bridge.bridge_script().read_text("utf-8")
        self.assertIn("importedKey(item.account, item.imported_id)", source)
        self.assertIn("item.account === transaction.account", source)
        self.assertIn("item.account === transfer.from_account", source)
        create_budget = source[
            source.index("async function createBudget") : source.index("async function migrate")
        ]
        self.assertIn("request.operation_marker", create_budget)
        self.assertIn("item.name === marker", create_budget)
        self.assertIn("await api.loadBudget(budget.id)", create_budget)
        self.assertIn("await removeCreatedBudget(client", create_budget)
        self.assertLess(
            create_budget.index("item.name === marker"),
            create_budget.index("client.send('create-budget'"),
        )
        self.assertGreater(
            create_budget.rindex("await removeCreatedBudget(client"),
            create_budget.index("client.send('create-budget'"),
        )
        self.assertIn("if (!creationAttempted) throw error", create_budget)
        self.assertLess(
            create_budget.index("client.send('upload-budget')"),
            create_budget.index("await api.sync()"),
        )
        self.assertIn("did not receive a sync identity", create_budget)
        self.assertIn("request.server_url && !budget.groupId", create_budget)
        self.assertIn("request.replace_existing_staging === true", create_budget)
        self.assertLess(
            create_budget.index("throw new ExistingStagedBudgetError(budget)"),
            create_budget.index("creationAttempted = true"),
        )

        init_client = source[
            source.index("async function initActualClient") : source.index(
                "async function loadBudget"
            )
        ]
        self.assertIn("const client = await api.init", init_client)
        self.assertIn("typeof client.send !== 'function'", init_client)
        self.assertIn("@actual-app/api 26.7.0", init_client)

        close_account = source[
            source.index("if (request.action === 'close_account')") : source.index(
                "if (request.action === 'create_transaction')"
            )
        ]
        self.assertIn("request.transfer_account_id", close_account)
        self.assertIn("request.transfer_category_id", close_account)
        self.assertIn("transferAccountId || undefined", close_account)

        delete_transfer = source[
            source.index("if (request.action === 'delete_transfer')") : source.index(
                "if (request.action === 'set_budget')"
            )
        ]
        validation = delete_transfer.index("left.transfer_id !== right.id")
        deletion = delete_transfer.index("await api.deleteTransaction")
        self.assertLess(validation, deletion)
        self.assertIn("ids.length !== 2 || ids[0] === ids[1]", delete_transfer)

        create_transfer = source[
            source.index("if (request.action === 'create_transfer')") : source.index(
                "if (request.action === 'delete_transfer')"
            )
        ]
        self.assertIn("Actual transfer import requires a stable imported id", create_transfer)
        self.assertIn("matches.length !== 1", create_transfer)
        self.assertIn("const beforeIds = new Set", create_transfer)
        self.assertIn("candidateIds.some(id => beforeIds.has(id))", create_transfer)
        self.assertIn("if (!reconciliationRequired)", create_transfer)
        self.assertEqual(create_transfer.count("await api.deleteTransaction("), 1)
        self.assertIn("reciprocalPairs.length !== 2", create_transfer)
        self.assertIn("Actual transfer reconciliation requires owner review", create_transfer)
        self.assertLess(
            create_transfer.index("if (!importedId)"),
            create_transfer.index("await api.importTransactions"),
        )

        migration = source[
            source.index("async function migrate") : source.index("async function write")
        ]
        self.assertIn("request.replace_existing_staging !== true", migration)
        self.assertIn("request.sync_id = created.sync_id", migration)
        self.assertIn("await removeCreatedBudget(client, created)", migration)
        self.assertIn("throw new StagedBudgetCleanupVerifiedError(error)", migration)
        self.assertIn("safeMinor(row.opening_minor", migration)
        self.assertIn("closed: Boolean(row.archived)", migration)
        self.assertNotIn("await api.closeAccount", migration)
        self.assertIn("safeMinor(row.amount_minor", migration)
        self.assertIn("await api.addTransactions(accountId", migration)
        self.assertNotIn("await api.importTransactions(accountId", migration)
        self.assertIn("learnCategories: false, runTransfers: false", migration)
        self.assertLess(
            migration.index("if (!leftPayee || !rightPayee)"),
            migration.index("await api.updateTransaction(left.id"),
        )
        self.assertLess(
            migration.index("Actual transfer migration linkage could not be verified"),
            migration.index("entityLinks.push({ kind: 'transfer'"),
        )
        self.assertIn("verifiedLeft.payee !== leftPayee", migration)
        self.assertIn("verifiedRight.payee !== rightPayee", migration)

        inspect_budget = source[
            source.index("async function inspectBudget") : source.index(
                "async function managedBudgetIdentity"
            )
        ]
        self.assertIn("new Date('9999-12-31T00:00:00.000Z')", inspect_budget)
        self.assertIn("api.getAccountBalance(account.id, allDatesCutoff)", inspect_budget)

        cleanup = source[
            source.index("async function deleteStagedBudget") : source.index(
                "async function migrate"
            )
        ]
        self.assertIn("item.id === budgetId", cleanup)
        self.assertIn("const idMatches = localBudgets.filter", cleanup)
        self.assertIn("const syncMatches = syncId", cleanup)
        self.assertIn("await api.downloadBudget(syncId", cleanup)
        self.assertIn("if (!budgetId && !syncId)", cleanup)
        self.assertIn("budgetId && idMatches.length !== 1", cleanup)
        self.assertIn("syncId && syncMatches.length !== 1", cleanup)
        self.assertIn("idMatches[0] !== syncMatches[0]", cleanup)
        self.assertIn("remoteBudgetMatches(client, syncId)", cleanup)
        self.assertIn("remoteBudget?.fileId", cleanup)
        self.assertIn("verified_absent: true", cleanup)
        self.assertIn("request.command === 'delete_staged_budget'", source)

        create_account = source[
            source.index("if (request.action === 'create_account')") : source.index(
                "if (request.action === 'update_account')"
            )
        ]
        self.assertIn("request.operation_marker", create_account)
        self.assertIn("markerPattern.test(marker)", create_account)
        self.assertLess(
            create_account.index("await api.getAccounts()"),
            create_account.index("await api.createAccount"),
        )

        managed_categories = source[
            source.index("async function managedCategoryContext") : source.index(
                "async function ensurePayee"
            )
        ]
        self.assertIn("category.group_id === groupId", managed_categories)
        self.assertIn("await managedCategoryGroupName(request)", managed_categories)
        self.assertIn("matches.length > 1", managed_categories)
        managed_identity = source[
            source.index("async function managedBudgetIdentity") : source.index(
                "async function managedCategoryContext"
            )
        ]
        self.assertIn("if (syncId) return syncId", managed_identity)
        self.assertIn("item.id === budgetId", managed_identity)
        self.assertIn("matches[0]?.groupId", managed_identity)

        payee_guards = source[
            source.index("async function ensurePayee") : source.index("async function createBudget")
        ]
        self.assertIn("payeeMap.get(key) === null", payee_guards)
        self.assertIn("Actual payee name is not unique", payee_guards)
        self.assertIn("payeeMap.set(name, null)", payee_guards)
        create_transaction = source[
            source.index("if (request.action === 'create_transaction')") : source.index(
                "if (request.action === 'update_transaction')"
            )
        ]
        update_transaction = source[
            source.index("if (request.action === 'update_transaction')") : source.index(
                "if (request.action === 'delete_transaction')"
            )
        ]
        self.assertIn("canonicalPayeeMap(payees)", create_transaction)
        self.assertIn("canonicalPayeeMap(payees)", update_transaction)
        self.assertIn("if (!fields.payee_name) fields.imported_payee = null", update_transaction)
        self.assertIn("reimportDeleted: request.reimport_deleted === true", create_transaction)
        self.assertIn("Actual transaction import requires a stable imported id", create_transaction)
        self.assertIn("matches.length !== 1", create_transaction)
        self.assertIn(
            "Actual imported transaction was not uniquely discoverable", create_transaction
        )
        delete_transaction = source[
            source.index("if (request.action === 'delete_transaction')") : source.index(
                "if (request.action === 'create_transfer')"
            )
        ]
        self.assertIn("matches.length !== 1", delete_transaction)
        self.assertIn("matches[0].transfer_id", delete_transaction)
        self.assertIn("must be deleted with delete_transfer", delete_transaction)

        load_budget = source[
            source.index("async function loadBudget") : source.index("function dateRule")
        ]
        self.assertIn("if (preferSync)", load_budget)
        self.assertIn("sync_id is required for fresh-client readback", load_budget)
        date_rule = source[
            source.index("function dateRule") : source.index("async function allTransactions")
        ]
        self.assertIn("endMode: 'never'", date_rule)
        readback = source[
            source.index("if (request.command === 'readback')") : source.index(
                "throw new Error(`unsupported Actual bridge command"
            )
        ]
        self.assertIn("preferSync: true", readback)

    def test_bridge_only_surfaces_allowlisted_errors_after_private_value_redaction(self):
        source = actual_bridge.bridge_script().read_text("utf-8")
        redactor = source[
            source.index("function cleanError") : source.index("function packageVersion")
        ]
        helpers = source[
            source.index("const SAFE_BRIDGE_ERRORS") : source.index("function packageVersion")
        ]
        self.assertIn("SAFE_BRIDGE_ERRORS.has(message)", redactor)
        self.assertIn("requestPrivateValues(request)", helpers)
        self.assertIn("[redacted url]", helpers)
        self.assertIn("[redacted path]", helpers)
        self.assertIn("private details withheld", redactor)
        self.assertNotIn("return message.slice", redactor)
        self.assertIn("cleanError(error, request)", source)
        self.assertIn("error instanceof StagedBudgetCleanupError", source)
        self.assertIn("error instanceof ExistingStagedBudgetError", source)
        self.assertIn("failure.staged_budget = error.stagedBudget", source)

    def test_call_parses_only_prefixed_structured_result(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout='Actual startup noise\nALLES_ACTUAL_RESULT={"ok":true,"data":{"value":3}}\n',
                stderr="",
            )

        self.assertEqual(actual_bridge.call({"command": "versions"}, runner=runner), {"value": 3})

    def test_secret_text_is_redacted_from_errors(self):
        secret = "owner-super-secret"

        def runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=1,
                stdout=(
                    'ALLES_ACTUAL_RESULT={"ok":false,"error":{"code":"failed",'
                    f'"message":"password={secret} token={secret}"}}\n'
                ),
                stderr=f"password={secret}",
            )

        with self.assertRaises(actual_bridge.ActualBridgeError) as raised:
            actual_bridge.call({"command": "inspect", "password": secret}, runner=runner)
        self.assertNotIn(secret, str(raised.exception))

    def test_cleanup_required_error_preserves_only_the_internal_staged_identity(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=1,
                stdout=(
                    'ALLES_ACTUAL_RESULT={"ok":false,"error":{'
                    '"code":"actual_stage_cleanup_required",'
                    '"message":"Actual bridge operation failed with private details withheld",'
                    '"staged_budget":{"budget_id":"budget-private","sync_id":"sync-private"}}}\n'
                ),
                stderr="private cleanup details",
            )

        with self.assertRaises(actual_bridge.ActualBridgeError) as raised:
            actual_bridge.call({"command": "migrate"}, runner=runner)
        self.assertEqual(
            raised.exception.details,
            {
                "staged_budget": {
                    "budget_id": "budget-private",
                    "sync_id": "sync-private",
                }
            },
        )
        self.assertNotIn("budget-private", str(raised.exception))

    def test_cleanup_verified_error_preserves_the_retryable_failure_code(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=1,
                stdout=(
                    'ALLES_ACTUAL_RESULT={"ok":false,"error":{'
                    '"code":"actual_stage_cleanup_verified",'
                    '"message":"Actual bridge operation failed with private details withheld"}}\n'
                ),
                stderr="private migration details",
            )

        with self.assertRaises(actual_bridge.ActualBridgeError) as raised:
            actual_bridge.call({"command": "migrate"}, runner=runner)
        self.assertEqual(raised.exception.code, "actual_stage_cleanup_verified")
        self.assertEqual(raised.exception.details, {})

    def test_cleanup_required_error_rejects_a_missing_budget_identity(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=1,
                stdout=(
                    'ALLES_ACTUAL_RESULT={"ok":false,"error":{'
                    '"code":"actual_stage_cleanup_required","message":"failed",'
                    '"staged_budget":{"budget_id":"","sync_id":"sync"}}}\n'
                ),
                stderr="",
            )

        with self.assertRaisesRegex(
            actual_bridge.ActualBridgeError, "invalid staged-budget identity"
        ):
            actual_bridge.call({"command": "migrate"}, runner=runner)

    def test_reconciliation_required_error_preserves_only_the_staged_identity(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=1,
                stdout=(
                    'ALLES_ACTUAL_RESULT={"ok":false,"error":{'
                    '"code":"actual_stage_reconciliation_required",'
                    '"message":"existing Actual staging budget requires reconciliation",'
                    '"staged_budget":{"budget_id":"budget-private","sync_id":"sync-private"}}}\n'
                ),
                stderr="private reconciliation details",
            )

        with self.assertRaises(actual_bridge.ActualBridgeError) as raised:
            actual_bridge.call({"command": "migrate"}, runner=runner)
        self.assertEqual(raised.exception.code, "actual_stage_reconciliation_required")
        self.assertEqual(
            raised.exception.details["staged_budget"],
            {"budget_id": "budget-private", "sync_id": "sync-private"},
        )
        self.assertNotIn("budget-private", str(raised.exception))

    def test_timeout_is_structured_and_does_not_echo_payload(self):
        def runner(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], stderr="private")

        with self.assertRaisesRegex(actual_bridge.ActualBridgeError, "timed out"):
            actual_bridge.call({"command": "inspect", "password": "hidden"}, runner=runner)

    def test_real_bridge_output_is_stopped_at_the_fixed_byte_limit(self):
        with tempfile.TemporaryDirectory(prefix="alles-actual-output-") as directory:
            script = Path(directory) / "bridge.py"
            script.write_text("import sys\nsys.stdout.write('x' * 65536)\n", "utf-8")
            with mock.patch.object(actual_bridge, "MAX_OUTPUT_BYTES", 1024):
                with self.assertRaises(actual_bridge.ActualBridgeError) as raised:
                    actual_bridge.call(
                        {"command": "versions"},
                        script=script,
                        node=sys.executable,
                    )
        self.assertEqual(raised.exception.code, "actual_bridge_too_large")

    def test_unstructured_bridge_failure_does_not_surface_arbitrary_stderr(self):
        private = "http://owner:password@127.0.0.1/private/data/file.sqlite"

        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr=private)

        with self.assertRaises(actual_bridge.ActualBridgeError) as raised:
            actual_bridge.call({"command": "inspect"}, runner=runner)
        self.assertEqual(str(raised.exception), "Actual bridge returned no structured result")
        self.assertNotIn(private, str(raised.exception))

    def test_calls_are_serialized(self):
        active = 0
        maximum = 0
        state_lock = threading.Lock()

        def runner(*args, **kwargs):
            nonlocal active, maximum
            with state_lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
            return SimpleNamespace(
                returncode=0, stdout='ALLES_ACTUAL_RESULT={"ok":true,"data":{}}\n', stderr=""
            )

        threads = [
            threading.Thread(
                target=actual_bridge.call,
                args=({"command": "versions"},),
                kwargs={"runner": runner},
            )
            for _ in range(3)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(maximum, 1)


if __name__ == "__main__":
    unittest.main()
