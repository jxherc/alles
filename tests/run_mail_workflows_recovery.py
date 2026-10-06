"""Run one Mail workflow against a fresh owned fixture and actual working-tree assets."""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "scripts")]


def group_absent(process):
    if process is None:
        return True
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return True
    return False


def main():
    from pw_mail_workflows_recovery import (
        BASIC_CASES,
        CASES,
        LOADING_CASES,
        digest,
        source_proof,
        write_json,
    )
    from run_browser_gates import (
        free_port,
        isolated_environment,
        owned_data,
        stop_process,
        wait_for_server,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guard", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--expected-acceptance", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=BASIC_CASES + CASES + LOADING_CASES, required=True)
    parser.add_argument(
        "--pane", choices=["composer", "account", "rules", "vacation"], default="composer"
    )
    parser.add_argument("--width", type=int, choices=[1440, 390], default=1440)
    args = parser.parse_args()
    if args.width == 390 and args.case not in ["accounts-round-trip", "recipients-save"]:
        parser.error("only accounts-round-trip and recipients-save have a prepared phone profile")
    if not all(
        re.fullmatch("[a-f0-9]{64}", value)
        for value in [args.expected_source, args.expected_acceptance]
    ):
        parser.error("provide the complete reviewed source and acceptance hashes")
    guard = args.guard.expanduser().resolve()
    out = args.output.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False)
    receipt_path = out / "receipt.json"
    receipt = {
        "status": "running",
        "case": args.case,
        "pane": args.pane,
        "width": args.width,
        "expected_source": args.expected_source,
        "expected_acceptance": args.expected_acceptance,
        "guard_path": str(guard),
        "working_directory": str(ROOT),
        "browser_started": False,
        "startup_seconds": 90,
        "case_seconds": 240,
        "asset_mode": "actual working-tree HTTP responses; no source fulfillment",
    }
    server = browser = data = port = owner_root = None

    def record():
        write_json(receipt_path, receipt)

    def proof():
        return source_proof(args.expected_source, args.expected_acceptance, guard)

    record()
    try:
        receipt["pre_server_proof"] = proof()
        record()
        assert receipt["pre_server_proof"]["matches_reviewed_freeze"], (
            "source, acceptance or guard drift; no automatic refresh"
        )
        with owned_data() as (owner_root, run_id):
            # The owned-test header requires data beneath the process temporary directory.
            temporary_root = owner_root / "tmp"
            temporary_root.mkdir()
            data = temporary_root / "data"
            data.mkdir()
            (data / ".alles-test-owner").write_text(run_id, encoding="utf-8")
            assert temporary_root in data.parents
            port = free_port()
            env = isolated_environment(data, run_id, port, out)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            if sys.platform == "darwin":
                env.setdefault(
                    "PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / "Library/Caches/ms-playwright")
                )
            for name in ["home", "config", "cache"]:
                (data / name).mkdir()
            env.update(
                HOME=str(data / "home"),
                XDG_CONFIG_HOME=str(data / "config"),
                XDG_CACHE_HOME=str(data / "cache"),
            )
            env.update(
                TMPDIR=str(temporary_root), TEMP=str(temporary_root), TMP=str(temporary_root)
            )
            origin = f"http://127.0.0.1:{port}"
            database = Path(env["ALLES_DB"]).resolve()
            assert database.is_relative_to(data.resolve())
            assert (data / ".alles-test-owner").read_text().strip() == run_id
            driver = ROOT / "tests/pw_mail_workflows_recovery.py"
            server_command = [
                sys.executable,
                "-B",
                str(driver),
                "--serve-fixture",
                "--case",
                args.case,
                "--guard",
                str(guard),
            ]
            receipt.update(
                run_id=run_id,
                port=port,
                origin=origin,
                owned_root=str(data.resolve()),
                owned_outer_root=str(owner_root),
                owned_temporary_root=str(temporary_root),
                data_descends_from_owned_temporary_root=True,
                database=str(database),
                server_command=server_command,
            )
            record()
            try:
                with (
                    (out / "server.log").open("w") as server_output,
                    (out / "browser.log").open("w") as browser_output,
                ):
                    server = subprocess.Popen(
                        server_command,
                        cwd=ROOT,
                        env=env,
                        stdout=server_output,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    receipt.update(server_pid=server.pid, server_pgid=os.getpgid(server.pid))
                    record()
                    wait_for_server(server, port, run_id, 90)
                    fixture_path = data / "mail-compact-fixture.json"
                    import json

                    fixture = json.loads(fixture_path.read_text())
                    assert fixture["run_id"] == run_id and fixture["pid"] == server.pid
                    assert fixture["guard_sha256"] == receipt["pre_server_proof"]["guard_sha256"]
                    assert fixture["workflow_case"] == args.case
                    (out / fixture_path.name).write_bytes(fixture_path.read_bytes())
                    current = proof()
                    current.update(
                        origin=origin,
                        run_id=run_id,
                        owned_root=str(data.resolve()),
                        database=str(database),
                        owner_marker=(data / ".alles-test-owner").read_text().strip(),
                        server_pid=server.pid,
                        server_pgid=os.getpgid(server.pid),
                        fixture_pid=fixture["pid"],
                        fixture_sha256=digest(fixture_path),
                        fixture_account_id=fixture["account_id"],
                        owned_health_header_verified=True,
                        server_running=server.poll() is None,
                    )
                    receipt["pre_browser_proof"] = current
                    record()
                    assert current["server_running"] and current["matches_reviewed_freeze"], (
                        "source drift or fixture exit; browser not started"
                    )
                    command = [
                        sys.executable,
                        "-B",
                        str(driver),
                        "--base",
                        origin,
                        "--run-id",
                        run_id,
                        "--launch-receipt",
                        str(receipt_path),
                        "--guard",
                        str(guard),
                        "--case",
                        args.case,
                        "--pane",
                        args.pane,
                        "--width",
                        str(args.width),
                    ]
                    receipt["browser_command"] = command
                    record()
                    browser = subprocess.Popen(
                        command,
                        cwd=ROOT,
                        env=env,
                        stdout=browser_output,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    receipt.update(
                        browser_started=True,
                        browser_driver_pid=browser.pid,
                        browser_driver_pgid=os.getpgid(browser.pid),
                    )
                    record()
                    receipt["exit_code"] = browser.wait(timeout=240)
                    receipt["status"] = "passed" if receipt["exit_code"] == 0 else "failed"
            finally:
                if browser:
                    stop_process(browser)
                if server:
                    stop_process(server)
                receipt.update(
                    server_stopped=server is None or server.poll() is not None,
                    browser_stopped=browser is None or browser.poll() is not None,
                    server_group_absent=group_absent(server),
                    browser_group_absent=group_absent(browser),
                )
    except BaseException as error:
        receipt.update(status="failed", error=repr(error), stack=traceback.format_exc())
    finally:
        receipt["temporary_data_removed"] = data is None or not data.exists()
        receipt["owned_outer_root_removed"] = owner_root is None or not owner_root.exists()
        if port is not None:
            try:
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", port))
                receipt["port_rebound"] = True
            except OSError as error:
                receipt.update(port_rebound=False, port_rebind_error=repr(error))
        try:
            receipt["post_run_proof"] = proof()
            receipt["source_unchanged"] = receipt["post_run_proof"]["matches_reviewed_freeze"]
        except Exception as error:
            receipt.update(source_unchanged=False, source_check_error=repr(error))
        required = ["source_unchanged", "temporary_data_removed", "owned_outer_root_removed"]
        if data is not None:
            required += [
                "server_stopped",
                "browser_stopped",
                "server_group_absent",
                "browser_group_absent",
                "port_rebound",
            ]
        receipt["terminal_checks_passed"] = all(receipt.get(key) is True for key in required)
        if not receipt["terminal_checks_passed"]:
            receipt["status"] = "failed"
        record()
    print(out)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
