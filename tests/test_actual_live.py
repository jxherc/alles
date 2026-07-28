"""Opt-in official Actual 26.7.0 install, bridge, backup, and restore gate."""

import contextlib
import os
import signal
import socket
import subprocess
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text

from core.migrations import m0037_finance_currency_import_foundation
from services import actual_migration, managed_actual


def _managed_server_script() -> str:
    return str(
        (
            managed_actual.app_dir()
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        ).resolve()
    )


def _process_start_token(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _verified_process_identity(pid: int, expected_script: str) -> tuple[object, str]:
    command = managed_actual._process_command(pid)
    started = _process_start_token(pid)
    if not managed_actual._command_owns_script(command, expected_script) or not started:
        raise AssertionError("managed Actual cleanup fallback ownership was not verified")
    return command, started


def _force_stop_verified_process(pid: int, expected_script: str) -> None:
    if not managed_actual._process_alive(pid):
        return
    identity = _verified_process_identity(pid, expected_script)
    if _verified_process_identity(pid, expected_script) != identity:
        raise AssertionError("managed Actual cleanup fallback process identity changed")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    for _attempt in range(50):
        if not managed_actual._process_alive(pid):
            return
        time.sleep(0.1)
    if _verified_process_identity(pid, expected_script) != identity:
        raise AssertionError("managed Actual cleanup fallback process identity changed")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    for _attempt in range(50):
        if not managed_actual._process_alive(pid):
            return
        time.sleep(0.1)
    raise AssertionError("managed Actual cleanup fallback process survived force-stop")


def _stop_managed_actual_or_fail() -> None:
    """Stop the owned live-gate process, force it down if needed, and report failure."""
    marker_path = managed_actual.root_dir() / "server.pid.json"
    marker = managed_actual._read_json(marker_path)
    try:
        pid = int(marker.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    expected_script = _managed_server_script()
    try:
        managed_actual.stop()
        return
    except Exception as stop_error:
        listener_pids = managed_actual._listener_pids()
        managed_pids = managed_actual._managed_server_pids()
        verified_targets = set(managed_pids or ())
        if pid > 0 and managed_actual._process_alive(pid):
            command = managed_actual._process_command(pid)
            if managed_actual._command_owns_script(command, expected_script):
                verified_targets.add(pid)
        try:
            for target in sorted(verified_targets):
                _force_stop_verified_process(target, expected_script)
        except AssertionError as fallback_error:
            raise fallback_error from stop_error

        remaining_listeners = managed_actual._listener_pids()
        remaining_managed = managed_actual._managed_server_pids()
        if (
            any(
                value is None
                for value in (listener_pids, managed_pids, remaining_listeners, remaining_managed)
            )
            or bool(remaining_listeners)
            or bool(remaining_managed)
        ):
            raise AssertionError(
                "managed Actual cleanup failed and fallback could not prove process absence"
            ) from stop_error
        marker_path.unlink(missing_ok=True)
        raise AssertionError(
            "managed Actual cleanup required a verified force-stop fallback"
        ) from stop_error


class ActualLiveCleanupTests(unittest.TestCase):
    def test_stop_failure_force_stops_verified_owned_process_and_still_fails_loudly(self):
        with tempfile.TemporaryDirectory(prefix="alles-actual-cleanup-unit-") as root_value:
            root = Path(root_value)
            marker = root / "server.pid.json"
            app = root / "app"
            expected = str(
                (
                    app
                    / "node_modules"
                    / "@actual-app"
                    / "sync-server"
                    / "build"
                    / "bin"
                    / "actual-server.js"
                ).resolve()
            )
            managed_actual._atomic_json(marker, {"pid": 43210, "server_script": expected})
            alive = {"value": True}

            def kill(_pid, _signal):
                alive["value"] = False

            with (
                mock.patch.object(managed_actual, "root_dir", return_value=root),
                mock.patch.object(managed_actual, "app_dir", return_value=app),
                mock.patch.object(
                    managed_actual,
                    "stop",
                    side_effect=managed_actual.ManagedActualError("normal stop failed"),
                ),
                mock.patch.object(
                    managed_actual, "_process_alive", side_effect=lambda _pid: alive["value"]
                ),
                mock.patch.object(
                    managed_actual,
                    "_process_command",
                    return_value=("node", expected),
                ),
                mock.patch(__name__ + "._process_start_token", return_value="stable-start"),
                mock.patch.object(managed_actual, "_listener_pids", side_effect=[{43210}, set()]),
                mock.patch.object(
                    managed_actual, "_managed_server_pids", side_effect=[{43210}, set()]
                ),
                mock.patch.object(os, "kill", side_effect=kill) as force_kill,
                self.assertRaisesRegex(AssertionError, "verified force-stop fallback"),
            ):
                _stop_managed_actual_or_fail()

            force_kill.assert_called_once_with(43210, signal.SIGTERM)
            self.assertFalse(marker.exists())

    def test_stop_failure_finds_and_force_stops_markerless_managed_listener(self):
        with tempfile.TemporaryDirectory(prefix="alles-actual-cleanup-unit-") as root_value:
            root = Path(root_value)
            app = root / "app"
            expected = str(
                (
                    app
                    / "node_modules"
                    / "@actual-app"
                    / "sync-server"
                    / "build"
                    / "bin"
                    / "actual-server.js"
                ).resolve()
            )
            alive = {"value": True}

            def kill(_pid, _signal):
                alive["value"] = False

            with (
                mock.patch.object(managed_actual, "root_dir", return_value=root),
                mock.patch.object(managed_actual, "app_dir", return_value=app),
                mock.patch.object(
                    managed_actual,
                    "stop",
                    side_effect=managed_actual.ManagedActualError("normal stop failed"),
                ),
                mock.patch.object(
                    managed_actual, "_process_alive", side_effect=lambda _pid: alive["value"]
                ),
                mock.patch.object(
                    managed_actual,
                    "_process_command",
                    return_value=("node", expected),
                ),
                mock.patch(__name__ + "._process_start_token", return_value="stable-start"),
                mock.patch.object(managed_actual, "_listener_pids", side_effect=[{54321}, set()]),
                mock.patch.object(
                    managed_actual, "_managed_server_pids", side_effect=[{54321}, set()]
                ),
                mock.patch.object(os, "kill", side_effect=kill) as force_kill,
                self.assertRaisesRegex(AssertionError, "verified force-stop fallback"),
            ):
                _stop_managed_actual_or_fail()

            force_kill.assert_called_once_with(54321, signal.SIGTERM)

    def test_force_stop_refuses_a_reused_pid_before_sigkill(self):
        expected = str(Path("/tmp/actual-server.js").resolve())
        with (
            mock.patch.object(managed_actual, "_process_alive", return_value=True),
            mock.patch.object(
                managed_actual,
                "_process_command",
                side_effect=[("node", expected), ("node", expected), ("node", expected)],
            ),
            mock.patch(
                __name__ + "._process_start_token",
                side_effect=["original-start", "original-start", "replacement-start"],
            ),
            mock.patch.object(time, "sleep"),
            mock.patch.object(os, "kill") as force_kill,
            self.assertRaisesRegex(AssertionError, "process identity changed"),
        ):
            _force_stop_verified_process(76543, expected)

        force_kill.assert_called_once_with(76543, signal.SIGTERM)

    def test_stop_failure_does_not_kill_an_unverified_listener(self):
        with tempfile.TemporaryDirectory(prefix="alles-actual-cleanup-unit-") as root_value:
            root = Path(root_value)
            app = root / "app"
            with (
                mock.patch.object(managed_actual, "root_dir", return_value=root),
                mock.patch.object(managed_actual, "app_dir", return_value=app),
                mock.patch.object(
                    managed_actual,
                    "stop",
                    side_effect=managed_actual.ManagedActualError("normal stop failed"),
                ),
                mock.patch.object(managed_actual, "_listener_pids", side_effect=[{65432}, {65432}]),
                mock.patch.object(
                    managed_actual, "_managed_server_pids", side_effect=[set(), set()]
                ),
                mock.patch.object(os, "kill") as force_kill,
                self.assertRaisesRegex(AssertionError, "could not prove process absence"),
            ):
                _stop_managed_actual_or_fail()

            force_kill.assert_not_called()


def _snapshot():
    def evidence(amount):
        return {
            "original_amount_text": amount,
            "original_currency_code": "CAD",
            "base_amount_text": amount,
            "base_currency_code": "CAD",
            "rate_text": "1",
            "rate_date": "",
            "source": "live_test",
        }

    transactions = [
        {
            "id": "t1",
            "account_id": "a1",
            "date": "2026-07-18",
            "amount_minor": -1234,
            "category": "food",
            "payee": "market",
            "notes": "live migration",
            "cleared": True,
            "transfer_id": "",
            "import_identity": "live:t1",
            "evidence": {**evidence("-12.34"), "source_hash": "live:t1"},
        },
        {
            "id": "t2",
            "account_id": "a1",
            "date": "2026-07-18",
            "amount_minor": -2000,
            "category": "transfer",
            "payee": "cash",
            "notes": "transfer",
            "cleared": False,
            "transfer_id": "x1",
            "import_identity": "live:t2",
            "evidence": {**evidence("-20"), "source_hash": "live:t2"},
        },
        {
            "id": "t3",
            "account_id": "a2",
            "date": "2026-07-18",
            "amount_minor": 2000,
            "category": "transfer",
            "payee": "CIBC chequing",
            "notes": "transfer",
            "cleared": False,
            "transfer_id": "x1",
            "import_identity": "live:t3",
            "evidence": {**evidence("20"), "source_hash": "live:t3"},
        },
    ]
    return {
        "version": 1,
        "base_currency_code": "CAD",
        "accounts": [
            {
                "id": "a1",
                "name": "CIBC chequing",
                "kind": "checking",
                "archived": False,
                "opening_minor": 100000,
                "evidence": {
                    **evidence("1000"),
                    "account_kind": "checking",
                    "color": "clay",
                    "low_balance": 50.0,
                },
            },
            {
                "id": "a2",
                "name": "cash",
                "kind": "cash",
                "archived": False,
                "opening_minor": 5000,
                "evidence": {
                    **evidence("50"),
                    "account_kind": "cash",
                    "color": "mint",
                    "low_balance": 0.0,
                },
            },
        ],
        "transactions": transactions,
        "transfer_pairs": [{"id": "x1", "left": transactions[1], "right": transactions[2]}],
        "category_names": ["food", "transfer", "housing"],
        "payee_names": ["market", "cash", "CIBC chequing", "landlord"],
        "budget_assignments": [
            {
                "id": "b1",
                "category": "food",
                "month": "2026-07",
                "amount_minor": 30000,
                "metadata": {"source_kind": "assignment"},
            }
        ],
        "schedules": [
            {
                "kind": "recurring",
                "id": "r1",
                "name": "rent",
                "account_id": "a1",
                "payee": "landlord",
                "amount_minor": -80000,
                "next_date": "2026-08-01",
                "cycle": "monthly",
                "cycle_days": 30,
                "active": True,
                "posts_transaction": True,
                "metadata": {"category": "housing"},
            }
        ],
        "subscriptions": [],
        "subscription_payments": [],
        "sidecar_links": [],
    }


def _upgraded_snapshot(path: Path) -> dict:
    """Build a cutover fixture from rows that really passed through the additive 8B migration."""
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE money_accounts (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, "
                    "kind VARCHAR, currency VARCHAR, opening FLOAT, color VARCHAR, archived BOOLEAN, "
                    "low_balance FLOAT, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE money_transactions (id VARCHAR PRIMARY KEY, account_id VARCHAR, "
                    "date VARCHAR NOT NULL, amount FLOAT, category VARCHAR, payee VARCHAR, notes TEXT, "
                    "transfer_id VARCHAR, tags TEXT, receipt_id VARCHAR, cleared BOOLEAN, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE subscriptions (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, price FLOAT, "
                    "currency VARCHAR, cycle VARCHAR, cycle_days INTEGER, next_due VARCHAR NOT NULL, "
                    "category VARCHAR, url VARCHAR, notes TEXT, active BOOLEAN, remind_days INTEGER, "
                    "last_notified_due VARCHAR, account_id VARCHAR, last_posted_due VARCHAR, trial_end VARCHAR, "
                    "cancel_url VARCHAR, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE sub_payments (id VARCHAR PRIMARY KEY, sub_id VARCHAR, date VARCHAR, "
                    "amount FLOAT, txn_id VARCHAR, created_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO money_accounts VALUES "
                    "('legacy-a','legacy chequing','savings','CAD',42.75,'ochre',0,10.5,NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO money_transactions VALUES "
                    "('legacy-t','legacy-a','2026-06-30',-2.25,'food','market','upgraded row','','tagged','receipt-1',1,NULL)"
                )
            )
            m0037_finance_currency_import_foundation.up(conn)
            account = (
                conn.execute(
                    text(
                        "SELECT id,name,kind,archived,color,low_balance,base_opening_text,"
                        "original_opening_text,currency_code,base_currency_code,opening_fx_rate_text,"
                        "opening_fx_rate_date,opening_fx_source FROM money_accounts"
                    )
                )
                .mappings()
                .one()
            )
            transaction = (
                conn.execute(
                    text(
                        "SELECT t.id,t.account_id,t.date,t.category,t.payee,t.notes,t.cleared,t.transfer_id,"
                        "t.import_identity,e.original_amount_text,e.original_currency_code,e.base_amount_text,"
                        "e.base_currency_code,e.rate_text,e.rate_date,e.source,e.source_hash "
                        "FROM money_transactions t JOIN money_fx_evidence e ON e.transaction_id=t.id"
                    )
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    account_evidence = {
        "original_amount_text": account["original_opening_text"],
        "original_currency_code": account["currency_code"],
        "base_amount_text": account["base_opening_text"],
        "base_currency_code": account["base_currency_code"],
        "rate_text": account["opening_fx_rate_text"],
        "rate_date": account["opening_fx_rate_date"],
        "source": account["opening_fx_source"],
        "account_kind": account["kind"],
        "color": account["color"],
        "low_balance": account["low_balance"],
    }
    transaction_evidence = {
        key: transaction[key]
        for key in (
            "original_amount_text",
            "original_currency_code",
            "base_amount_text",
            "base_currency_code",
            "rate_text",
            "rate_date",
            "source",
            "source_hash",
        )
    }
    transaction_row = {
        "id": transaction["id"],
        "account_id": transaction["account_id"],
        "date": transaction["date"],
        "amount_minor": int(Decimal(transaction["base_amount_text"]) * 100),
        "category": transaction["category"],
        "payee": transaction["payee"],
        "notes": transaction["notes"],
        "cleared": bool(transaction["cleared"]),
        "transfer_id": transaction["transfer_id"] or "",
        "import_identity": transaction["import_identity"]
        or f"alles:transaction:{transaction['id']}",
        "evidence": transaction_evidence,
    }
    return {
        "version": 1,
        "base_currency_code": "CAD",
        "accounts": [
            {
                "id": account["id"],
                "name": account["name"],
                "kind": account["kind"],
                "archived": bool(account["archived"]),
                "opening_minor": int(Decimal(account["base_opening_text"]) * 100),
                "evidence": account_evidence,
            }
        ],
        "transactions": [transaction_row],
        "transfer_pairs": [],
        "category_names": [transaction["category"]],
        "payee_names": [transaction["payee"]],
        "budget_assignments": [],
        "schedules": [],
        "subscriptions": [],
        "subscription_payments": [],
        "sidecar_links": [],
    }


@unittest.skipUnless(
    os.environ.get("ALLES_RUN_ACTUAL_LIVE") == "1",
    "set ALLES_RUN_ACTUAL_LIVE=1 for the pinned official runtime gate",
)
class ActualLiveGateTests(unittest.TestCase):
    def test_install_migrate_write_backup_restore_and_fresh_readback(self):
        old_data = os.environ.get("ALLES_DATA")
        old_port = os.environ.get("ALLES_ACTUAL_PORT")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        try:
            with contextlib.ExitStack() as stack:
                root = stack.enter_context(tempfile.TemporaryDirectory(prefix="alles-actual-live-"))
                # Registered after TemporaryDirectory, so LIFO cleanup stops the
                # owned process while its PID metadata still exists.
                stack.callback(_stop_managed_actual_or_fail)
                os.environ["ALLES_DATA"] = root
                os.environ["ALLES_ACTUAL_PORT"] = str(port)
                installed = managed_actual.install()
                self.assertTrue(installed["healthy"])
                self.assertEqual(installed["version"], "26.7.0")
                cleanup_budget = managed_actual.bridge_request(
                    {
                        "command": "create_budget",
                        "budget_name": "Alles incomplete staging cleanup gate",
                    },
                    timeout=180,
                )
                cleanup_request = {
                    "command": "delete_staged_budget",
                    "budget_id": cleanup_budget["budget_id"],
                    "sync_id": cleanup_budget["sync_id"],
                }
                removed = managed_actual.bridge_request(cleanup_request, timeout=180)
                self.assertTrue(removed["deleted"])
                self.assertTrue(removed["verified_absent"])
                absent = managed_actual.bridge_request(cleanup_request, timeout=180)
                self.assertFalse(absent["deleted"])
                self.assertTrue(absent["verified_absent"])
                migrated = managed_actual.bridge_request(
                    {
                        "command": "migrate",
                        "budget_name": "Alles Stage 8 live gate",
                        "snapshot": _snapshot(),
                    },
                    timeout=300,
                )
                parity = actual_migration.reconcile(_snapshot(), migrated)
                self.assertTrue(parity["pass"], parity)
                upgraded = _upgraded_snapshot(Path(root) / "upgraded-ledger.sqlite3")
                upgraded_result = managed_actual.bridge_request(
                    {
                        "command": "migrate",
                        "budget_name": "Alles Stage 8 upgraded-ledger gate",
                        "snapshot": upgraded,
                    },
                    timeout=300,
                )
                upgraded_parity = actual_migration.reconcile(upgraded, upgraded_result)
                self.assertTrue(upgraded_parity["pass"], upgraded_parity)
                actual = managed_actual.bridge_request(
                    {
                        "command": "inspect",
                        "budget_id": migrated["budget_id"],
                        "sync_id": migrated["sync_id"],
                    },
                    timeout=180,
                )
                self.assertEqual(len(actual["accounts"]), 2)
                self.assertEqual(
                    sum(bool(row.get("starting_balance_flag")) for row in actual["transactions"]),
                    2,
                )
                imported = {row.get("imported_id"): row for row in actual["transactions"]}
                self.assertTrue({"live:t1", "live:t2", "live:t3"}.issubset(imported))
                self.assertEqual(imported["live:t2"]["transfer_id"], imported["live:t3"]["id"])
                self.assertEqual(imported["live:t3"]["transfer_id"], imported["live:t2"]["id"])
                account_ids = {
                    row["source_id"]: row["actual_id"]
                    for row in migrated["links"]
                    if row["kind"] == "account"
                }
                request = {
                    "command": "write",
                    "budget_id": migrated["budget_id"],
                    "sync_id": migrated["sync_id"],
                    "action": "create_transaction",
                    "transaction": {
                        "account": account_ids["a1"],
                        "date": "2026-07-19",
                        "amount": -250,
                        "payee_name": "coffee",
                        "category_name": "food",
                        "notes": "post-cutover live",
                        "imported_id": "live:post-cutover",
                        "cleared": False,
                    },
                }
                first = managed_actual.bridge_request(request, timeout=180)
                second = managed_actual.bridge_request(request, timeout=180)
                self.assertEqual(first["id"], second["id"])
                before_backup = managed_actual.bridge_request(
                    {
                        "command": "inspect",
                        "budget_id": migrated["budget_id"],
                        "sync_id": migrated["sync_id"],
                    },
                    timeout=180,
                )
                self.assertEqual(
                    sum(
                        row.get("imported_id") == "live:post-cutover"
                        for row in before_backup["transactions"]
                    ),
                    1,
                )
                transfer = managed_actual.bridge_request(
                    {
                        "command": "write",
                        "budget_id": migrated["budget_id"],
                        "sync_id": migrated["sync_id"],
                        "action": "create_transfer",
                        "transfer": {
                            "from_account": account_ids["a1"],
                            "to_account": account_ids["a2"],
                            "amount_minor": 300,
                            "date": "2026-07-19",
                            "notes": "post-cutover transfer",
                            "imported_id": "live:transfer",
                        },
                    },
                    timeout=180,
                )
                self.assertTrue(transfer["from_id"])
                self.assertTrue(transfer["to_id"])
                backup = managed_actual.backup()
                self.assertGreater(managed_actual.verify_backup(backup["backup_id"])["files"], 0)
                managed_actual.bridge_request(
                    {
                        "command": "write",
                        "budget_id": migrated["budget_id"],
                        "sync_id": migrated["sync_id"],
                        "action": "delete_transaction",
                        "actual_id": first["id"],
                    },
                    timeout=180,
                )
                managed_actual.bridge_request(
                    {
                        "command": "write",
                        "budget_id": migrated["budget_id"],
                        "sync_id": migrated["sync_id"],
                        "action": "delete_transfer",
                        "actual_ids": [transfer["from_id"], transfer["to_id"]],
                    },
                    timeout=180,
                )
                after_delete = managed_actual.bridge_request(
                    {
                        "command": "inspect",
                        "budget_id": migrated["budget_id"],
                        "sync_id": migrated["sync_id"],
                    },
                    timeout=180,
                )
                remaining_ids = {row["id"] for row in after_delete["transactions"]}
                self.assertFalse({transfer["from_id"], transfer["to_id"]} & remaining_ids)

                def verify_restored():
                    with tempfile.TemporaryDirectory(prefix="alles-actual-fresh-client-") as fresh:
                        readback = managed_actual.bridge_request(
                            {
                                "command": "readback",
                                "sync_id": migrated["sync_id"],
                                "fresh_data_dir": fresh,
                            },
                            timeout=180,
                        )
                    restored_by_id = {row["id"]: row for row in readback["transactions"]}
                    restored_transfer = (
                        restored_by_id.get(transfer["from_id"]),
                        restored_by_id.get(transfer["to_id"]),
                    )
                    return {
                        "ok": sum(
                            row.get("imported_id") == "live:post-cutover"
                            for row in readback["transactions"]
                        )
                        == 1
                        and all(restored_transfer)
                        and restored_transfer[0].get("transfer_id") == transfer["to_id"]
                        and restored_transfer[1].get("transfer_id") == transfer["from_id"],
                        "transactions": len(readback["transactions"]),
                    }

                restored = managed_actual.restore(backup["backup_id"], verify_fn=verify_restored)
                self.assertTrue(restored["readback"]["ok"])
        finally:
            if old_data is None:
                os.environ.pop("ALLES_DATA", None)
            else:
                os.environ["ALLES_DATA"] = old_data
            if old_port is None:
                os.environ.pop("ALLES_ACTUAL_PORT", None)
            else:
                os.environ["ALLES_ACTUAL_PORT"] = old_port


if __name__ == "__main__":
    unittest.main()
