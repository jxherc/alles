"""Server recovery with real owned policy, logs, export and process restart.

Metrics and service/provider lifecycle responses are explicitly simulated. No
host supervisor or remote backup mutation is forwarded. Run directly with the
project Python; artifacts are written under ALLES_BROWSER_ARTIFACTS.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from pw_settings_helpers import choose_settings_section

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from run_browser_gates import (  # noqa: E402
    free_port,
    isolated_environment,
    owned_data,
    stop_process,
    wait_for_server,
)

PASS = "server-audit-synthetic-owner-only-2026"
STATS = {
    "live": True,
    "host": {
        "os": "synthetic audit OS",
        "platform": "darwin",
        "hostname": "owned-fixture",
        "python": "3.12",
        "user": "synthetic",
        "arch": "arm64",
        "backend": "cpu",
    },
    "cpu": {
        "name": "synthetic CPU",
        "cores": 4,
        "percent": 21,
        "per_core": [10, 20, 30, 24],
        "freq_mhz": 2400,
    },
    "memory": {"total_gb": 16, "used_gb": 4, "available_gb": 12, "percent": 25},
    "disks": [],
    "gpu": {"has": False},
    "uptime_sec": 1200,
    "load": [0.1, 0.2, 0.3],
    "swap": None,
    "net": {},
    "disk_io": {},
    "procs": [],
    "proc_count": 0,
    "temp_c": None,
}


def serve():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    runid = os.environ["ALLES_TEST_RUN_ID"]
    assert (
        Path(tempfile.gettempdir()).resolve() in data.parents
        and (data / ".alles-test-owner").read_text() == runid
    )
    import logging

    import uvicorn
    from fastapi import Depends, Request

    from app import app
    from core import auth
    from services import sysmon

    sysmon.snapshot = lambda: STATS

    @app.post("/api/test-fixture/expire-owner", dependencies=[Depends(auth.require_auth)])
    def expire(request: Request):
        token = request.cookies.get("aide_session", "")
        assert auth.verify_session(token)
        auth._recent_auth[token] = 0
        return {"expired": True}

    @app.post("/api/test-fixture/long-log", dependencies=[Depends(auth.require_auth)])
    def long_log():
        logging.getLogger("audit.synthetic").warning(
            "审计 fixture-only " + ("long-owned-message-" * 30)
        )
        return {"logged": True}

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["PORT"]), proxy_headers=False)


def _run_cleanup(actions):
    """Release every owned resource without replacing the workflow failure."""
    original = sys.exception()
    first_error = None
    for label, action in actions:
        try:
            action()
        except BaseException as error:
            if original is not None:
                original.add_note(f"Cleanup failed ({label}): {error!r}")
            elif first_error is None:
                first_error = error
            else:
                first_error.add_note(f"Cleanup also failed ({label}): {error!r}")
    if first_error is not None:
        raise first_error


def run():
    from playwright.sync_api import expect, sync_playwright

    from services.appearance import from_legacy

    out = Path(os.environ.get("ALLES_BROWSER_ARTIFACTS", "/tmp/alles-server-recovery"))
    out.mkdir(parents=True, exist_ok=True)
    records = []
    cleanup = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for profile in ["desktop", "phone"]:
                dest = out / profile
                dest.mkdir(exist_ok=True)
                with owned_data() as (data, runid):
                    port = free_port()
                    env = isolated_environment(data, runid, port, dest)
                    env.update(
                        AUTH_ENABLED="true",
                        AUTH_PASSWORD=PASS,
                        SECRET_KEY="server-audit-synthetic-fixture-key-only",
                    )
                    process = None
                    context = None
                    log = None
                    state = {
                        "stats_failure": False,
                        "stats_failures": 0,
                        "service_simulated": False,
                        "service_fail": False,
                        "service_hold": False,
                        "service_running": False,
                        "service_mutations": 0,
                        "backup_simulated": False,
                        "backup_fail": True,
                        "backup_runs": 0,
                        "blocked_mutations": [],
                    }
                    held_service = []
                    events = {
                        "console": [],
                        "pageerrors": [],
                        "responses": [],
                        "failed_requests": [],
                        "requests": [],
                    }
                    fixture = {
                        "profile": profile,
                        "data_root": str(data),
                        "port": port,
                        "run_id": runid,
                    }
                    cleanup.append(fixture)

                    def start():
                        nonlocal process, log
                        log = (data / "alles-server.log").open("a")
                        process = subprocess.Popen(
                            [sys.executable, str(Path(__file__).resolve()), "--server"],
                            cwd=ROOT,
                            env=env,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            start_new_session=False,
                        )
                        try:
                            wait_for_server(process, port, runid, 60)
                        except BaseException:
                            stop_process(process, process_group=False)
                            log.close()
                            raise

                    try:
                        start()
                        fixture["server_pids"] = [process.pid]
                        context = browser.new_context(
                            base_url=f"http://127.0.0.1:{port}",
                            viewport={
                                "width": 390 if profile == "phone" else 1440,
                                "height": 844 if profile == "phone" else 900,
                            },
                            is_mobile=profile == "phone",
                            has_touch=profile == "phone",
                            locale="en-CA",
                            timezone_id="America/Toronto",
                            reduced_motion="reduce",
                            service_workers="block",
                            accept_downloads=True,
                        )
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        api = context.request
                        assert api.post("/api/auth/login", data={"password": PASS}).ok
                        assert api.post("/api/setup/dismiss").ok
                        assert api.put("/api/appearance", data=from_legacy("dark", None)).ok
                        page = context.new_page()
                        page.set_default_timeout(12000)
                        page.on(
                            "console",
                            lambda m: events["console"].append({"type": m.type, "text": m.text}),
                        )
                        page.on("pageerror", lambda e: events["pageerrors"].append(str(e)))
                        page.on(
                            "response",
                            lambda r: (
                                events["responses"].append(
                                    {
                                        "method": r.request.method,
                                        "path": urlparse(r.url).path,
                                        "status": r.status,
                                    }
                                )
                                if r.status >= 400
                                else None
                            ),
                        )
                        page.on(
                            "requestfailed",
                            lambda r: events["failed_requests"].append(
                                {
                                    "method": r.method,
                                    "path": urlparse(r.url).path,
                                    "reason": r.failure,
                                }
                            ),
                        )
                        page.on(
                            "request",
                            lambda r: events["requests"].append(
                                {"method": r.method, "path": urlparse(r.url).path}
                            ),
                        )

                        def handler(route):
                            req = route.request
                            path = urlparse(req.url).path
                            method = req.method

                            def answer(body, status=200):
                                route.fulfill(
                                    status=status,
                                    content_type="application/json",
                                    body=json.dumps(body),
                                )

                            if path == "/api/system/stats" and state["stats_failure"]:
                                state["stats_failures"] += 1
                                answer({"detail": "simulated stats outage"}, 503)
                                return
                            if path == "/api/system/searxng" and method == "GET":
                                answer(
                                    {
                                        "installed": False,
                                        "owned": False,
                                        "available": False,
                                        "support_verified": False,
                                        "actions": [],
                                    }
                                )
                                return
                            if path == "/api/finance/actual" and method == "GET":
                                answer(
                                    {
                                        "service": {
                                            "available": False,
                                            "installed": False,
                                            "owned": False,
                                        },
                                        "ledger": {"mode": "alles"},
                                    }
                                )
                                return
                            if path == "/api/system/companions" and method == "GET":
                                answer({"companions": []})
                                return
                            if (
                                path == "/api/system/services"
                                and method == "GET"
                                and state["service_simulated"]
                            ):
                                answer(
                                    {
                                        "services": [
                                            {
                                                "service_id": "audit-synthetic",
                                                "name": "synthetic owned service",
                                                "manager": "compose",
                                                "owned": True,
                                                "available": True,
                                                "running": state["service_running"],
                                                "actions": ["start", "stop", "restart"],
                                            }
                                        ]
                                    }
                                )
                                return
                            if path.startswith("/api/system/services/audit-synthetic/"):
                                state["service_mutations"] += 1
                                if state["service_fail"]:
                                    answer({"detail": "simulated service rejection"}, 503)
                                    return
                                if state["service_hold"]:
                                    held_service.append(route)
                                    return
                                state["service_running"] = path.rsplit("/", 1)[-1] != "stop"
                                answer({"ok": True})
                                return
                            if (
                                path == "/api/backup/webdav"
                                and method == "GET"
                                and state["backup_simulated"]
                            ):
                                answer(
                                    {
                                        "configured": True,
                                        "last_backup_at": "2026-09-25T12:00:00Z"
                                        if state["backup_runs"]
                                        else "",
                                        "last_verified_at": "",
                                    }
                                )
                                return
                            if path == "/api/backup/webdav/run" and state["backup_simulated"]:
                                if state["backup_fail"]:
                                    answer({"detail": "simulated WebDAV outage"}, 503)
                                else:
                                    state["backup_runs"] += 1
                                    answer({"filename": "synthetic-only.alles-backup"})
                                return
                            if method not in ["GET", "HEAD"] and (
                                path.startswith("/api/system/services/")
                                or path.startswith("/api/system/companions/")
                                or path.startswith("/api/system/host-services/")
                                or path.startswith("/api/system/searxng/")
                                or path.startswith("/api/finance/actual/service/")
                                or path in ["/api/backup/webdav/run", "/api/backup/s3/run"]
                            ):
                                state["blocked_mutations"].append({"method": method, "path": path})
                                answer(
                                    {"detail": "audit safety guard blocked a host/provider action"},
                                    409,
                                )
                                return
                            route.continue_()

                        page.route("**/api/**", handler)
                        root = page.locator("#server-workbench-view")

                        def save_record(name, status="passed", **details):
                            records.append(
                                {
                                    "scenario_id": name,
                                    "profile": profile,
                                    "status": status,
                                    **details,
                                }
                            )
                            (out / "scenarios.json").write_text(json.dumps(records, indent=2))

                        def shot(name):
                            page.screenshot(path=str(dest / (name + ".png")), full_page=True)

                        def reveal(target):
                            for _ in range(30):
                                rect = target.bounding_box()
                                assert rect, "missing screenshot target"
                                if (
                                    rect["y"] >= 105
                                    and rect["y"] + min(rect["height"], 100)
                                    <= page.viewport_size["height"] - 20
                                ):
                                    break
                                page.mouse.move(
                                    page.viewport_size["width"] - 35,
                                    page.viewport_size["height"] / 2,
                                )
                                page.mouse.wheel(0, -550 if rect["y"] < 105 else 550)
                                page.wait_for_timeout(60)
                            expect(target).to_be_in_viewport()

                        def tab(section):
                            root.locator(f'[data-group-section="{section}"]').click()
                            expect(root).to_have_attribute("data-section", section)
                            if section not in ["overview", "activity", "watch"]:
                                expect(root.locator("[data-group-overview]")).not_to_contain_text(
                                    "loading current data…"
                                )

                        def card(title):
                            return root.locator(".server-workbench-card").filter(
                                has=page.get_by_role("heading", name=title, exact=True)
                            )

                        def keyboard_to(target, limit=150):
                            for _ in range(limit):
                                if target.evaluate("e=>e===document.activeElement"):
                                    break
                                page.keyboard.press("Tab")
                            expect(target).to_be_focused()
                            expect(target).to_be_in_viewport()

                        page.goto("/?view=server")
                        expect(root).to_be_visible()
                        expect(page.locator("#box-cpu")).to_be_visible()
                        shot("01-overview-synthetic-metrics")
                        state["stats_failure"] = True
                        expect(page.locator("#system-body")).to_contain_text(
                            "couldn’t read system stats: server returned 503"
                        )
                        expect(page.locator("#system-host")).to_have_text("unavailable")
                        expect(page.locator("#box-cpu")).to_have_count(0)
                        assert (
                            page.locator("#system-host").evaluate(
                                "e=>getComputedStyle(e,'::after').display"
                            )
                            == "none"
                        )
                        shot("02-monitor-after-simulated-failure")
                        save_record(
                            "server.monitor-stale-feedback",
                            source="synthetic metric provider followed by explicit HTTP503",
                            visible_status="unavailable",
                            stale_metrics_removed=True,
                        )
                        tab("logs")
                        tab("overview")
                        expect(page.locator("#system-body")).to_contain_text(
                            "couldn’t read system stats"
                        )
                        expect(page.locator("#system-body")).not_to_contain_text(
                            "reading the machine"
                        )
                        expect(page.locator("#system-host")).to_have_text("unavailable")
                        shot("02b-monitor-reentry-after-outage")
                        save_record(
                            "server.monitor-loading-after-success",
                            source="synthetic metrics and explicit HTTP503",
                            failure_visible_after_reentry=True,
                        )
                        state["stats_failure"] = False
                        expect(page.locator("#box-cpu")).to_be_visible()
                        expect(page.locator("#system-host")).to_contain_text("live")
                        expect(page.locator("#system-body")).not_to_contain_text("couldn’t read")
                        shot("02c-monitor-recovered")
                        tab("logs")
                        expect(card("runtime logs")).to_be_visible()
                        live_logs = api.get("/api/system/logs?limit=80").json()["entries"]
                        assert any(e.get("ts") for e in live_logs)
                        log_rows = (
                            card("runtime logs")
                            .locator(".server-workbench-log")
                            .evaluate_all(
                                'es=>es.map(e=>({time:e.querySelector("time").textContent,message:e.querySelector("span").textContent}))'
                            )
                        )
                        assert log_rows and all(row["time"] for row in log_rows), log_rows
                        assert all(
                            row["time"] in {entry.get("ts") for entry in live_logs}
                            for row in log_rows
                        )
                        shot("03-runtime-log-times")
                        save_record(
                            "server.runtime-log-timestamps",
                            api_timestamps=[e.get("ts") for e in live_logs[:3]],
                            rendered=log_rows[:8],
                        )

                        def logs_fault(route):
                            route.fulfill(
                                status=503,
                                content_type="application/json",
                                body=json.dumps({"detail": "simulated runtime log outage"}),
                            )

                        page.route("**/api/system/logs?limit=80", logs_fault)
                        tab("updates")
                        tab("logs")
                        expect(card("runtime logs")).to_contain_text("simulated runtime log outage")
                        expect(
                            card("owner audit trail").locator(".server-workbench-log").first
                        ).to_be_visible()
                        shot("03b-partial-logs-error")
                        page.unroute("**/api/system/logs?limit=80", logs_fault)
                        tab("logs")
                        expect(
                            card("runtime logs").locator(".server-workbench-log").first
                        ).to_be_visible()
                        save_record(
                            "server.partial-logs-recovery",
                            source="real owner audit entries plus simulated runtime-log HTTP503; tab retry recovers",
                        )
                        tab("policy")
                        editor = card("server access policy").locator("textarea")
                        expect(editor).to_be_visible()
                        original = editor.input_value()
                        editor.fill('{"invalid":true}')
                        card("server access policy").get_by_role(
                            "button", name="validate and show diff"
                        ).click()
                        expect(card("server access policy")).to_contain_text("policy accepts only")
                        assert editor.input_value() == '{"invalid":true}'
                        editor.fill(original)
                        assert api.post("/api/test-fixture/expire-owner").ok
                        card("server access policy").get_by_role(
                            "button", name="save policy", exact=True
                        ).click()
                        dialog = page.locator(".dialog-overlay")
                        expect(dialog).to_be_visible()
                        shot("04-policy-owner-confirmation")
                        page.keyboard.press("Escape")
                        expect(dialog).to_be_hidden()
                        expect(card("server access policy")).to_contain_text(
                            "owner confirmation cancelled"
                        )
                        assert editor.input_value() == original
                        card("server access policy").get_by_role(
                            "button", name="save policy", exact=True
                        ).click()
                        expect(dialog).to_be_visible()
                        dialog.locator("input").fill(PASS)
                        page.keyboard.press("Enter")
                        expect(dialog).to_be_hidden()
                        expect(card("server access policy")).to_contain_text("saved and verified")
                        policy = api.get("/api/system/policy").json()
                        assert policy["valid"] and policy["policy"] == {
                            "control_mode": "owned_only",
                            "host_services": [],
                        }
                        assert (data / "server-policy.json").stat().st_mode & 0o777 == 0o600
                        shot("05-policy-saved")
                        policy_message = (
                            card("server access policy").locator(".server-workbench-status").first
                        )
                        assert "is-error" not in (policy_message.get_attribute("class") or "")
                        save_record(
                            "server.policy-success-style",
                            message=policy_message.inner_text(),
                            classes=policy_message.get_attribute("class"),
                        )
                        save_record(
                            "server.policy-recovery",
                            source="real owned backend with expired recent-owner confirmation",
                            policy=policy["policy"],
                            file_mode="0600",
                            retained_failed_draft=True,
                            cancelled_and_retried=True,
                        )
                        expect(card("server access policy")).not_to_contain_text("policy_missing")
                        expect(card("server access policy")).not_to_contain_text(
                            "server policy file is missing"
                        )
                        expect(
                            card("server access policy")
                            .locator(".server-workbench-fact")
                            .filter(has_text="effective state")
                        ).to_contain_text("owned_only")
                        save_record(
                            "server.policy-stale-permission-feedback",
                            source="real accepted policy and0600 file",
                            visible=card("server access policy").inner_text(),
                            actual_policy=policy["policy"],
                            actual_valid=policy["valid"],
                        )
                        policy_confirmation = (
                            card("server access policy")
                            .locator("label")
                            .filter(has_text="type “allow host services”")
                        )
                        expect(policy_confirmation).to_be_hidden()
                        assert policy_confirmation.evaluate(
                            "e=>e.hidden && getComputedStyle(e).display==='none'"
                        )
                        keyboard_to(
                            card("server access policy").get_by_role(
                                "button", name="save policy", exact=True
                            )
                        )
                        page.keyboard.press("Tab")
                        assert not policy_confirmation.locator("input").evaluate(
                            "e=>e===document.activeElement"
                        )
                        # Validate an allowlisted draft without saving it or invoking any host service.
                        editor.fill(
                            json.dumps({"control_mode": "allowlisted_host", "host_services": []})
                        )
                        card("server access policy").get_by_role(
                            "button", name="validate and show diff"
                        ).click()
                        expect(policy_confirmation).to_be_visible()
                        keyboard_to(policy_confirmation.locator("input"))
                        assert policy_confirmation.locator("input").bounding_box()["height"] >= 44
                        shot("05b-conditional-host-confirmation-keyboard")
                        editor.fill(original)
                        card("server access policy").get_by_role(
                            "button", name="validate and show diff"
                        ).click()
                        expect(policy_confirmation).to_be_hidden()
                        assert api.get("/api/system/policy").json()["policy"] == {
                            "control_mode": "owned_only",
                            "host_services": [],
                        }
                        save_record(
                            "server.policy-hidden-confirmation",
                            source="real owned-only saved policy; unsaved allowlisted draft only",
                            hidden_in_owned_mode=True,
                            reachable_for_allowlisted_draft=True,
                            no_host_permission_save=True,
                        )
                        tab("updates")
                        tab("policy")
                        expect(card("server access policy")).not_to_contain_text("policy_missing")
                        expect(policy_confirmation).to_be_hidden()
                        shot("05c-policy-reentry")
                        # Simulated service lifecycle is intercepted before any real supervisor route.
                        state["service_simulated"] = True
                        tab("services")
                        service = card("service control")
                        expect(service).to_contain_text("compose · stopped")
                        service.get_by_role("button", name="restart", exact=True).click()
                        expect(dialog).to_be_visible()
                        page.keyboard.press("Escape")
                        expect(dialog).to_be_hidden()
                        assert state["service_mutations"] == 0
                        state["service_fail"] = True
                        keyboard_to(service.get_by_role("button", name="start", exact=True))
                        page.keyboard.press("Enter")
                        expect(service).to_contain_text("simulated service rejection")
                        expect(
                            service.get_by_role("button", name="start", exact=True)
                        ).to_be_enabled()
                        assert not state["service_running"] and state["service_mutations"] == 1
                        shot("06a-service-failure")
                        state["service_fail"] = False
                        keyboard_to(service.get_by_role("button", name="start", exact=True))
                        page.keyboard.press("Enter")
                        expect(service).to_contain_text("compose · running")
                        expect(service).not_to_contain_text("in progress")
                        expect(service).not_to_contain_text("simulated service rejection")
                        expect(
                            service.get_by_role("button", name="start", exact=True)
                        ).to_be_focused()
                        assert state["service_running"] and state["service_mutations"] == 2
                        assert root.locator(".server-workbench-content").count() == 1
                        shot("06-service-after-simulated-start")
                        save_record(
                            "server.service-action-refresh",
                            source="simulated owned-service rejection then success; no supervisor called",
                            visible=service.inner_text(),
                            simulated_backend_running=True,
                            keyboard_focus_retained=True,
                        )
                        # A late action refresh must not replace the newly selected tab.
                        state["service_hold"] = True
                        service.get_by_role("button", name="restart", exact=True).click()
                        expect(dialog).to_be_visible()
                        keyboard_to(dialog.get_by_role("button", name="confirm", exact=True))
                        page.keyboard.press("Enter")
                        expect(dialog).to_be_hidden()
                        for _ in range(50):
                            if held_service:
                                break
                            page.wait_for_timeout(20)
                        assert len(held_service) == 1 and state["service_mutations"] == 3
                        expect(
                            service.get_by_role("button", name="restart", exact=True)
                        ).to_be_disabled()
                        tab("updates")
                        held_service.pop().fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps({"ok": True}),
                        )
                        state["service_hold"] = False
                        page.wait_for_timeout(250)
                        expect(root).to_have_attribute("data-section", "updates")
                        expect(card("release and update status")).to_be_visible()
                        expect(service).to_have_count(0)
                        tab("services")
                        expect(service).to_contain_text("compose · running")
                        page.reload()
                        expect(service).to_contain_text("compose · running")
                        assert root.locator(".server-workbench-content").count() == 1
                        shot("07-service-after-reload")
                        save_record(
                            "server.service-late-refresh",
                            source="simulated delayed restart response; no supervisor called",
                            updates_not_replaced=True,
                            visible_state_after_reload="running",
                            mutations=3,
                        )
                        tab("backups")
                        expect(
                            card("webdav").get_by_role("button", name="run encrypted backup")
                        ).to_be_disabled()
                        expect(
                            card("s3-compatible storage").get_by_role(
                                "button", name="run encrypted backup"
                            )
                        ).to_be_disabled()
                        save_record(
                            "server.unconfigured-backup-disabled",
                            source="real empty owned configuration",
                        )
                        state["backup_simulated"] = True
                        tab("updates")
                        tab("backups")
                        webdav = card("webdav")
                        webdav.get_by_role("button", name="run encrypted backup").click()
                        expect(webdav).to_contain_text("simulated WebDAV outage")
                        shot("08-backup-simulated-failure")
                        expect(card("backups and storage")).not_to_contain_text("running")
                        expect(webdav).not_to_contain_text("creating encrypted backup")
                        expect(
                            webdav.get_by_role("button", name="run encrypted backup")
                        ).to_be_enabled()
                        save_record(
                            "server.backup-failure-status",
                            source="simulated WebDAV503; no provider called",
                            intro=card("backups and storage").inner_text(),
                            local_error=webdav.inner_text(),
                        )
                        state["backup_fail"] = False
                        keyboard_to(webdav.get_by_role("button", name="run encrypted backup"))
                        page.keyboard.press("Enter")
                        expect(webdav).to_contain_text("2026-09-25T12:00:00Z")
                        expect(webdav).to_contain_text(
                            "backup complete · synthetic-only.alles-backup"
                        )
                        expect(webdav).not_to_contain_text("simulated WebDAV outage")
                        expect(
                            webdav.get_by_role("button", name="run encrypted backup")
                        ).to_be_focused()
                        assert state["backup_runs"] == 1
                        assert root.locator(".server-workbench-content").count() == 1
                        shot("09-backup-simulated-success")
                        save_record(
                            "server.backup-action-refresh",
                            source="simulated WebDAV success",
                            visible=webdav.inner_text(),
                            simulated_backups=1,
                            keyboard_focus_retained=True,
                        )
                        tab("updates")
                        tab("backups")
                        expect(card("webdav")).to_contain_text("2026-09-25T12:00:00Z")
                        state["backup_simulated"] = False
                        # Real local export through the product settings entry; no provider is used.
                        page.goto("/?view=today")
                        page.locator("#today-settings").click()
                        expect(page.locator("#settings-modal")).to_be_visible()
                        choose_settings_section(page, "backup")
                        with page.expect_download() as download_event:
                            page.locator("#backup-export-btn").click()
                            expect(page.locator(".dialog-overlay")).to_be_visible()
                            page.locator(".dialog-overlay input").fill(PASS)
                            page.keyboard.press("Enter")
                        download = download_event.value
                        exported = dest / "owned-encrypted-export.alles-backup"
                        download.save_as(exported)
                        assert (
                            exported.stat().st_size > 100
                            and download.suggested_filename.endswith(".alles-backup")
                        )
                        assert exported.read_bytes().startswith(b"ALLES-BACKUP-V1\0")
                        save_record(
                            "server.local-export",
                            source="real owned encrypted download, no host/provider backup",
                            filename=download.suggested_filename,
                            size=exported.stat().st_size,
                        )
                        # Real owned restart; no host supervisor operation is involved.
                        page.goto("about:blank")
                        before = api.get("/api/system/policy").json()["canonical"]
                        stop_process(process, process_group=False)
                        log.close()
                        start()
                        fixture["server_pids"].append(process.pid)
                        assert api.post("/api/auth/login", data={"password": PASS}).ok
                        assert api.get("/api/system/policy").json()["canonical"] == before
                        page.goto("/?view=server-policy")
                        expect(card("server access policy")).to_contain_text("owned_only")
                        shot("10-after-owned-restart")
                        save_record(
                            "server.owned-restart-persistence",
                            same_policy=True,
                            source="real owned process restart and fresh authenticated session",
                        )
                        assert api.post("/api/test-fixture/long-log").ok
                        assert api.put("/api/appearance", data=from_legacy("light", None)).ok
                        page.goto("/?view=server-logs")
                        expect(card("runtime logs")).to_contain_text("long-owned-message")
                        reveal(
                            card("runtime logs")
                            .locator(".server-workbench-log")
                            .filter(has_text="long-owned-message")
                        )
                        shot("11-light-long-runtime-log")
                        geometry = root.evaluate(
                            "e=>({scroll:e.scrollWidth,client:e.clientWidth,viewport:document.documentElement.clientWidth,document:document.documentElement.scrollWidth})"
                        )
                        buttons = root.locator("button:visible").evaluate_all(
                            'es=>es.map(e=>({text:e.textContent,role:e.getAttribute("role"),rect:{width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}}))'
                        )
                        assert (
                            geometry["document"] <= geometry["viewport"]
                            and geometry["scroll"] <= geometry["client"] + 1
                        ), geometry
                        save_record(
                            "server.light-long-content-geometry",
                            geometry=geometry,
                            buttons=buttons,
                        )
                        tab("policy")
                        keyboard_to(root.locator('[data-group-section="policy"]'))
                        page.keyboard.press("Home")
                        expect(root).to_have_attribute("data-section", "overview")
                        page.keyboard.press("ArrowRight")
                        expect(root).to_have_attribute("data-section", "services")
                        save_record(
                            "server.keyboard-tabs",
                            keys=["Home", "ArrowRight"],
                            source="actual bounded Tab entry",
                        )
                        tab("logs")
                        expect(card("runtime logs")).to_be_visible()
                        tab("updates")
                        expect(card("release and update status")).to_be_visible()
                        page.go_back()
                        expect(root).to_have_attribute("data-section", "logs")
                        expect(card("runtime logs")).to_be_visible()
                        page.go_forward()
                        expect(root).to_have_attribute("data-section", "updates")
                        expect(card("release and update status")).to_be_visible()
                        save_record("server.browser-history", back="logs", forward="updates")
                        assert not state["blocked_mutations"], state["blocked_mutations"]
                        assert not events["pageerrors"], events["pageerrors"]
                        actual_responses = Counter(
                            (e["method"], e["path"], e["status"]) for e in events["responses"]
                        )
                        expected_responses = Counter(
                            {
                                ("GET", "/api/system/stats", 503): state["stats_failures"],
                                ("GET", "/api/system/logs", 503): 1,
                                ("POST", "/api/system/policy/diff", 409): 1,
                                ("PUT", "/api/system/policy", 403): 2,
                                ("POST", "/api/backup/webdav/run", 503): 1,
                                ("POST", "/api/system/services/audit-synthetic/start", 503): 1,
                            }
                        )
                        assert actual_responses == expected_responses, (
                            actual_responses,
                            expected_responses,
                        )
                        assert Counter(
                            (e["method"], e["path"], e["reason"]) for e in events["failed_requests"]
                        ) == Counter({("GET", "/api/backup", "net::ERR_ABORTED"): 1}), events[
                            "failed_requests"
                        ]
                        expected_console = Counter(
                            {
                                (
                                    "warning",
                                    "Service Worker registration blocked by Playwright",
                                ): 10,
                                (
                                    "error",
                                    "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
                                ): state["stats_failures"] + 3,
                                (
                                    "error",
                                    "Failed to load resource: the server responded with a status of 409 (Conflict)",
                                ): 1,
                                (
                                    "error",
                                    "Failed to load resource: the server responded with a status of 403 (Forbidden)",
                                ): 2,
                            }
                        )
                        assert (
                            Counter((e["type"], e["text"]) for e in events["console"])
                            == expected_console
                        ), events["console"]
                    except BaseException:
                        if context:
                            try:
                                page.screenshot(
                                    path=str(dest / "harness-failure.png"), full_page=True
                                )
                            except Exception:
                                pass
                        raise
                    finally:
                        actions = []
                        if context:
                            actions.extend(
                                [
                                    (
                                        "events",
                                        lambda: (dest / "events.json").write_text(
                                            json.dumps(events, indent=2)
                                        ),
                                    ),
                                    (
                                        "trace",
                                        lambda: context.tracing.stop(path=str(dest / "trace.zip")),
                                    ),
                                    ("context", context.close),
                                ]
                            )
                        if process:
                            actions.append(
                                ("server", lambda: stop_process(process, process_group=False))
                            )
                        if log:
                            actions.append(("log", log.close))
                        if (data / "alles-server.log").exists():
                            actions.append(
                                (
                                    "log artifact",
                                    lambda: shutil.copyfile(
                                        data / "alles-server.log", dest / "server.log"
                                    ),
                                )
                            )
                        actions.extend(
                            [
                                (
                                    "server status",
                                    lambda: fixture.update(
                                        server_stopped=process is None or process.poll() is not None
                                    ),
                                ),
                                (
                                    "fixture state",
                                    lambda: (dest / "fixture-state.json").write_text(
                                        json.dumps(state, indent=2)
                                    ),
                                ),
                            ]
                        )
                        _run_cleanup(actions)
                fixture["data_removed"] = not data.exists()
                with socket.socket() as sock:
                    sock.settimeout(0.2)
                    fixture["port_closed"] = sock.connect_ex(("127.0.0.1", port)) != 0
                (out / "owned-fixtures.json").write_text(json.dumps(cleanup, indent=2))
        finally:

            def record_cleanup():
                for item in cleanup:
                    item["data_removed"] = not Path(item["data_root"]).exists()
                    with socket.socket() as sock:
                        sock.settimeout(0.2)
                        item["port_closed"] = sock.connect_ex(("127.0.0.1", item["port"])) != 0
                (out / "owned-fixtures.json").write_text(json.dumps(cleanup, indent=2))

            _run_cleanup(
                [
                    ("browser", browser.close),
                    ("cleanup evidence", record_cleanup),
                    (
                        "scenarios",
                        lambda: (out / "scenarios.json").write_text(json.dumps(records, indent=2)),
                    ),
                ]
            )
    print(json.dumps({"status": "passed", "scenarios": len(records), "cleanup": cleanup}))


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    serve() if sys.argv[1:] == ["--server"] else run()
