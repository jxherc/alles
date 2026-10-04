"""Run maintained browser gates against separate, owned local Alles instances.

Usage: python scripts/run_browser_gates.py --suite smoke --output /tmp/alles-browser
The full suite adds inspected regression gates; it is not a product-wide certification.
Artifacts stay outside product history and contain synthetic test data only.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
from browser_gate_safety import require_server_ownership  # noqa: E402
from stabilization_report import (  # noqa: E402
    BROWSER_SUITES,
    acceptance_fingerprint,
    source_fingerprint,
)

# Explicitly maintained, inspected entries; the reporter shares this exact contract.
SUITES = BROWSER_SUITES
COMMANDS = {
    "style-ownership": ("tests/pw_style_ownership.py",),
    "smoke-desktop": ("tests/pw_stability_smoke.py", "desktop"),
    "smoke-phone": ("tests/pw_stability_smoke.py", "phone"),
    "cleanup-regressions": ("tests/pw_cleanup_regressions.py",),
    "minimal-workflows": ("tests/pw_minimal_workflows.py",),
    "docs-import": ("tests/pw_docs_import.py",),
    "docs-navigation": ("tests/pw_docs_navigation.py",),
    "source-keyboard": ("tests/pw_source_keyboard.py",),
    "markdown-attributes": ("tests/pw_markdown_attributes.py",),
    "docs-editor-loading": ("tests/pw_docs_editor_loading.py",),
    "docs-workbench-navigation": ("tests/pw_docs_workbench_navigation.py",),
    "files-workflows": ("tests/pw_phase7_files_real.py",),
    "files-upload-recovery": ("tests/pw_files_upload_recovery.py",),
    "files-transfer-clearance": ("tests/pw_files_transfer_clearance.py",),
    "gallery-workflows": ("tests/pw_gallery_workflows.py",),
    "aide-creations": ("tests/pw_aide_creations.py",),
    "gallery-hidden": ("tests/pw_gallery_hidden.py",),
    "plan-workflows": ("tests/pw_plan_workflows.py",),
    "plan-recovery": ("tests/pw_plan_recovery.py",),
    "plan-continuity": ("tests/pw_plan_continuity.py",),
    "plan-recurring-continuity": ("tests/pw_plan_recurring_continuity.py",),
    "calendar-workflows": ("tests/pw_calendar_workflows.py",),
    "mail-calendar-capture": ("tests/pw_mail_calendar_capture.py",),
    "reviewed-capture": ("tests/pw_reviewed_capture.py",),
    "home-reviewed-capture": ("tests/pw_home_reviewed_capture.py",),
    "home-note-recovery": ("tests/pw_home_note_recovery.py",),
    "note-destination-recovery": ("tests/pw_note_destination_recovery.py",),
    "home-aide-runs": ("tests/pw_home_aide_runs.py",),
    "calendar-metadata-picker": ("tests/pw_calendar_metadata_picker.py",),
    "pwa-offline": ("tests/pw_offline_11b.py",),
    "pwa-storage": ("tests/pw_offline_storage.py",),
    "pwa-rejection": ("tests/pw_offline_rejection.py",),
    "andromeda-saved": ("tests/pw_andromeda_saved.py",),
    "andromeda-handoff": ("tests/pw_andromeda_handoff.py",),
    "andromeda-continuation": ("tests/pw_andromeda_continuation.py",),
    "aide-task-capture": ("tests/pw_aide_task_capture.py",),
    "aide-send-preflight": ("tests/pw_aide_send_preflight.py",),
    "compare-preflight": ("tests/pw_compare_preflight.py",),
    "task-completion-recovery": ("tests/pw_task_completion_recovery.py",),
    "aide-drawer": ("tests/pw_aide_drawer.py",),
    "managed-service-workflow": ("tests/pw_managed_service.py",),
    "journal-recovery": ("tests/pw_journal_recovery.py",),
    "journal-search-export": ("tests/pw_journal_search_export.py",),
    "journal-reflect": ("tests/pw_journal_reflect.py",),
    "andromeda-cancellation": ("tests/pw_andromeda_cancellation.py",),
    "health-workflows": ("tests/pw_health_workflows.py",),
    "health-create-recovery": ("tests/pw_health_create_recovery.py",),
    "health-import-recovery": ("tests/pw_health_import_recovery.py",),
    "subscriptions-recovery": ("tests/pw_subscriptions_recovery.py",),
    "subscription-history": ("tests/pw_subscription_history.py",),
    "health-calendar-day": ("tests/pw_health_calendar_day.py",),
    "habit-recovery": ("tests/pw_habit_recovery.py",),
    "habit-create-recovery": ("tests/pw_habit_create_recovery.py",),
    "finance-imports": ("tests/pw_finance_imports.py",),
    "finance-workflows": ("tests/pw_finance_workflows.py",),
    "finance-networth-history": ("tests/pw_finance_networth_history.py",),
    "finance-recurring-create": ("tests/pw_finance_recurring_create.py",),
    "finance-recurring-edit": ("tests/pw_finance_recurring_edit.py",),
    "finance-recurring-repair": ("tests/pw_finance_recurring_repair.py",),
    "library-workflows": ("tests/pw_library_workflows.py",),
    "book-create": ("tests/pw_book_create.py",),
    "read-text": ("tests/pw_read_text.py",),
    "book-scope-recovery": ("tests/pw_book_scope_recovery.py",),
    "book-write-outcomes": ("tests/pw_book_write_outcomes.py",),
    "book-write-recovery": ("tests/pw_book_write_recovery.py",),
    "book-write-lifecycle": ("tests/pw_book_write_lifecycle.py",),
    "feed-outcomes": ("tests/pw_feed_outcomes.py",),
    "feed-workflows": ("tests/pw_feed_workflows.py",),
    "read-completion": ("tests/pw_read_completion.py",),
    "read-position": ("tests/pw_read_position.py",),
    "read-position-exit": ("tests/pw_read_position_exit.py",),
    "read-recovery": ("tests/pw_read_recovery.py",),
    "read-navigation": ("tests/pw_read_navigation.py",),
    "read-ownership": ("tests/pw_read_ownership.py",),
    "read-notes": ("tests/pw_read_notes.py",),
    "read-save": ("tests/pw_read_save.py",),
    "read-scope-recovery": ("tests/pw_read_scope_recovery.py",),
    "inbox-workflows": ("tests/pw_inbox_workflows.py",),
    "inbox-read-recovery": ("tests/pw_inbox_read_recovery.py",),
    "mail-review-regressions": ("tests/pw_mail_review_regressions.py",),
    "inbox-saved-searches": ("tests/pw_inbox_saved_searches.py",),
    "mail-editor-recovery": ("tests/pw_mail_editor_recovery.py",),
    "mail-draft-recovery": ("tests/pw_mail_draft_recovery.py",),
    "mail-outbox-recovery": ("tests/pw_mail_outbox_recovery.py",),
    "mail-triage-recovery": ("tests/pw_mail_triage_recovery.py",),
    "mail-triage-races": ("tests/pw_mail_triage_races.py",),
    "mail-triage-read-timing": ("tests/pw_mail_triage_read_timing.py",),
    "mail-hidden-recovery": ("tests/pw_mail_hidden_recovery.py",),
    "mail-vacation-recovery": ("tests/pw_mail_vacation_recovery.py",),
    "mail-rule-recovery": ("tests/pw_mail_rule_recovery.py",),
    "mail-account-recovery": ("tests/pw_mail_account_recovery.py",),
    "mail-account-recovery-edges": ("tests/pw_mail_account_recovery_edges.py",),
    "mail-oauth-recovery": ("tests/pw_mail_oauth_recovery.py",),
    "mail-signature-recovery": ("tests/pw_mail_signature_recovery.py",),
    "mail-signature-management": ("tests/pw_mail_signature_management.py",),
    "vault-backup": ("tests/pw_vault_backup.py",),
    "vault-setup-desktop": ("tests/pw_vault_setup.py", "desktop"),
    "vault-setup-phone": ("tests/pw_vault_setup.py", "phone"),
    "vault-actions-recovery": ("tests/pw_vault_actions_recovery.py",),
    "vault-create-recovery": ("tests/pw_vault_create_recovery.py",),
    "setup-auth": ("tests/pw_setup_auth.py",),
    "settings-recovery": ("tests/pw_settings_recovery.py",),
    "settings-panes": ("tests/pw_settings_panes.py",),
    "settings-language-badges": ("tests/pw_settings_language_badges.py",),
    "settings-selected": ("tests/pw_settings_selected.py",),
    "settings-context": ("tests/pw_settings_context.py",),
    "server-recovery": ("tests/pw_server_recovery.py",),
    "reminder-recovery": ("tests/pw_reminder_recovery.py",),
    "home-reminders": ("tests/pw_today_reminders.py",),
    "home-capture": ("tests/pw_home_capture.py",),
    "home-day-draft": ("tests/pw_home_day_draft.py",),
    "home-record-links": ("tests/pw_home_record_links.py",),
    "home-record-recovery": ("tests/pw_home_record_recovery.py",),
    "home-preferences": ("tests/pw_home_preferences.py",),
    "today-capture-confirm": ("tests/pw_today_capture_confirm.py",),
    "home-route-parity": ("tests/pw_home_route_parity.py",),
    "home-route-parity-off": ("tests/pw_home_route_parity.py",),
    "home-suggestions": ("tests/pw_home_suggestions.py",),
    "shell-command-shortcuts": ("tests/pw_shell_command_shortcuts.py",),
    "shell-app-name": ("tests/pw_shell_app_name.py",),
    "aide-continuity": ("tests/pw_aide_continuity.py",),
    "aide-composer": ("tests/pw_aide_composer.py",),
    "aide-image-retry": ("tests/pw_aide_image_retry.py",),
    "aide-questions": ("tests/pw_aide_question_recovery.py",),
    "aide-document-safety": ("tests/pw_aide_document_safety.py",),
    "aide-multi-source": ("tests/pw_aide_multi_source.py",),
    "aide-session-list": ("tests/pw_aide_session_list.py",),
    "aide-source-outcomes": ("tests/pw_aide_source_outcomes.py",),
    **{
        f"surfaces-{device}-{theme}": ("tests/pw_stability_surfaces.py", device, theme)
        for device in ("desktop", "phone")
        for theme in ("dark", "light")
    },
}


def isolated_environment(data: Path, run_id: str, port: int, artifacts: Path) -> dict[str, str]:
    # Do not inherit ALLES_DB, provider secrets, proxies, custom Python hooks, or the owner's .env.
    allowed = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "VIRTUAL_ENV",
        "PLAYWRIGHT_BROWSERS_PATH",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update(
        {
            "ALLES_DATA": str(data),
            "ALLES_DB": str(data / "aide.db"),
            "ALLES_TEST_DATA": "1",
            "ALLES_TEST_RUN_ID": run_id,
            "AUTH_ENABLED": "false",
            "ALLES_HOST": "127.0.0.1",
            "ALLES_ACCESS_PROFILE": "device",
            "BASE_DOMAIN": "localhost",
            "PORT": str(port),
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONUNBUFFERED": "1",
            "HF_HOME": str(data / "model-cache" / "huggingface"),
            "FASTEMBED_CACHE_PATH": str(data / "model-cache" / "fastembed"),
            "HF_HUB_OFFLINE": "1",
            "TZ": "UTC",
            "ALLES_BROWSER_ARTIFACTS": str(artifacts),
            "ALLES_CLEANUP_SHOTS": str(artifacts),
        }
    )
    return env


@contextmanager
def owned_data():
    with tempfile.TemporaryDirectory(prefix="alles-browser-owned-") as raw:
        data = Path(raw).resolve()
        run_id = uuid.uuid4().hex
        (data / ".alles-test-owner").write_text(run_id, encoding="utf-8")
        yield data, run_id


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop_process(process: subprocess.Popen, *, process_group: bool = True) -> None:
    """Only terminate the child/group created by this runner, never a port's occupant."""
    if process.poll() is not None:
        return
    if os.name == "posix" and process_group:
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "posix" and process_group:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=10)


def wait_for_server(process: subprocess.Popen, port: int, run_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = "server did not respond"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"server exited during startup ({process.returncode}); see server.log"
            )
        try:
            require_server_ownership(f"http://127.0.0.1:{port}/", run_id)
            return
        except RuntimeError as exc:
            last_error = str(exc)
            # A responding unrelated server is never an acceptable startup target.
            if "does not match" in last_error or "redirect" in last_error:
                raise
        time.sleep(0.2)
    raise RuntimeError(f"server startup timed out: {last_error}")


def git_text(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def build_fingerprint() -> str:
    return source_fingerprint(ROOT)


def run_gate(name: str, output: Path, startup_timeout: float, gate_timeout: float) -> dict:
    directory = output / name
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    before = build_fingerprint()
    contract_before = acceptance_fingerprint(root=ROOT)
    result = {
        "gate": name,
        "status": "failed",
        "artifacts": str(directory),
        "build_fingerprint": before,
        "acceptance_fingerprint": contract_before,
        "integration_mode": "local services; model downloads disabled; no provider credentials",
    }
    if name in {"feed-workflows", "read-text"}:
        result["integration_mode"] = (
            "real local app and database; synthetic HTTP responses; no external requests"
        )
    with owned_data() as (data, run_id):
        port = free_port()
        env = isolated_environment(data, run_id, port, directory)
        if name in {"home-capture", "home-route-parity-off"}:
            env["ALLES_AFTERLIFE_FEATURES"] = "afterlife_shell"
        result.update({"run_id": run_id, "port": port, "data_root": str(data)})
        server = gate = None
        try:
            with (
                (directory / "server.log").open("w") as server_log,
                (directory / "gate.log").open("w") as gate_log,
            ):
                server = subprocess.Popen(
                    [
                        sys.executable,
                        {
                            "feed-workflows": "tests/feed_browser_server.py",
                            "read-text": "tests/read_text_browser_server.py",
                            "managed-service-workflow": "tests/managed_service_browser_server.py",
                        }.get(name, "app.py"),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=server_log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                wait_for_server(server, port, run_id, startup_timeout)
                gate = subprocess.Popen(
                    [sys.executable, *COMMANDS[name]],
                    cwd=ROOT,
                    env=env,
                    stdout=gate_log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                code = gate.wait(timeout=gate_timeout)
                result["exit_code"] = code
                result["status"] = "passed" if code == 0 else "failed"
                if code:
                    result["error"] = "browser gate failed; see gate.log and browser artifacts"
        except KeyboardInterrupt:
            result.update(status="interrupted", error="browser gate interrupted")
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if gate is not None:
                stop_process(gate)
            if server is not None:
                stop_process(server)
            result["duration_seconds"] = round(time.monotonic() - started, 2)
            result["server_stopped"] = server is None or server.poll() is not None
    result["temporary_data_removed"] = not data.exists()
    result["build_fingerprint_after"] = build_fingerprint()
    result["acceptance_fingerprint_after"] = acceptance_fingerprint(root=ROOT)
    if (
        result["build_fingerprint_after"] != before
        or result["acceptance_fingerprint_after"] != contract_before
    ):
        result.update(
            status="invalidated", error="source or acceptance contract changed during the gate"
        )
    scenarios = directory / "scenarios.json"
    if scenarios.is_file():
        result["scenarios"] = json.loads(scenarios.read_text("utf-8"))
    controls = directory / "controls.json"
    if controls.is_file():
        result["controls"] = json.loads(controls.read_text("utf-8"))
    surfaces = directory / "surfaces.json"
    if surfaces.is_file():
        result["surfaces"] = json.loads(surfaces.read_text("utf-8"))
    write_report(directory / "result.json", result)
    return result


def write_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def scenario_evidence(result: dict) -> list[dict]:
    rows = []
    for scenario in result.get("scenarios", []):
        if not scenario.get("scenario_id"):
            continue
        row = {**scenario, "gate": result["gate"], "artifacts": result["artifacts"]}
        if "profiles" not in row:
            if row.get("profile"):
                row["profiles"] = [row["profile"]]
            elif result["gate"] in {"smoke-desktop", "smoke-phone"}:
                row["profiles"] = [result["gate"].removeprefix("smoke-")]
        rows.append(row)
    return rows


def control_evidence(result: dict) -> list[dict]:
    rows = []
    for control in result.get("controls", []):
        if not control.get("control_id"):
            continue
        row = {**control, "gate": result["gate"], "artifacts": result["artifacts"]}
        if "profiles" not in row:
            if row.get("profile"):
                row["profiles"] = [row["profile"]]
            elif result["gate"] in {"smoke-desktop", "smoke-phone"}:
                row["profiles"] = [result["gate"].removeprefix("smoke-")]
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES, default="smoke")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--startup-timeout", type=float, default=90)
    parser.add_argument("--gate-timeout", type=float, default=180)
    args = parser.parse_args()
    if args.startup_timeout <= 0 or args.gate_timeout <= 0:
        parser.error("timeouts must be positive")
    output = args.output or Path(tempfile.mkdtemp(prefix="alles-browser-results-"))
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Existing evidence is never overwritten, including results from another suite.
    if (output / "results.json").exists() or any(
        (output / name).exists() for name in SUITES[args.suite]
    ):
        parser.error("output already contains gate evidence; choose a fresh directory")
    report = {
        "schema_version": 2,
        "run_id": uuid.uuid4().hex,
        "suite": args.suite,
        "status": "running",
        "expected_gates": list(SUITES[args.suite]),
        "started_at": datetime.now(UTC).isoformat(),
        "revision": git_text("rev-parse", "HEAD"),
        "working_tree": git_text("status", "--short"),
        "build_fingerprint": build_fingerprint(),
        "acceptance_fingerprint": acceptance_fingerprint(root=ROOT),
        "environment": {"python": sys.version, "platform": platform.platform()},
        "limitations": [
            "Maintained local workflows, inspected cleanup paths and resting surfaces; not all interactions.",
            "Chromium emulation does not certify Safari, physical phones or installed PWA.",
            "No live providers, personal data or external accounts are used.",
            "Cleanup gate has screenshots and process logs; smoke also records browser traces.",
        ],
        "results": [],
        "scenarios": [],
        "controls": [],
    }
    report_path = output / "results.json"
    write_report(report_path, report)
    try:
        for name in SUITES[args.suite]:
            print(f"running {name}", flush=True)
            result = run_gate(name, output, args.startup_timeout, args.gate_timeout)
            report["results"].append(result)
            report["scenarios"].extend(scenario_evidence(result))
            report["controls"].extend(control_evidence(result))
            write_report(report_path, report)
            print(f"{name}: {result['status']} ({result['duration_seconds']}s)", flush=True)
            if result["status"] == "interrupted":
                report["status"] = "interrupted"
                break
        else:
            report["status"] = (
                "passed" if all(r["status"] == "passed" for r in report["results"]) else "failed"
            )
    except KeyboardInterrupt:
        report.update(status="interrupted", error="browser suite interrupted")
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        if (
            build_fingerprint() != report["build_fingerprint"]
            or acceptance_fingerprint(root=ROOT) != report["acceptance_fingerprint"]
            or any(
                r["status"] == "invalidated"
                or r.get("build_fingerprint") != report["build_fingerprint"]
                or r.get("build_fingerprint_after") != report["build_fingerprint"]
                or r.get("acceptance_fingerprint") != report["acceptance_fingerprint"]
                or r.get("acceptance_fingerprint_after") != report["acceptance_fingerprint"]
                for r in report["results"]
            )
        ):
            report["status"] = "invalidated"
        report["completed_at"] = datetime.now(UTC).isoformat()
        write_report(report_path, report)
    print(f"evidence: {report_path}")
    if report["status"] == "interrupted":
        return 130
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
