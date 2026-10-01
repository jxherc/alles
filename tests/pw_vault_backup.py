"""Owned Vault layout and local encrypted-backup recovery workflows.

Desktop and phone Chromium use real authentication, encryption, staging and records.
Only confirmation age and explicit broken transport/response cases are controlled.
No host service administration, remote provider or offline CLI apply runs here.
"""

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from pw_settings_helpers import choose_settings_section

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_browser_gates import (  # noqa: E402
    free_port,
    isolated_environment,
    stop_process,
    wait_for_server,
)

SCENARIOS = {
    "vault.local-item-recovery": "passwords.vault-and-browser",
    "server.local-backup-file-actions": "server.management",
    "server.local-backup-retry": "server.management",
    "server.local-backup-owner-confirmation": "server.management",
}


def serve_fixture():
    """Expose controlled confirmation expiry only on an owned loopback test server."""
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert Path(tempfile.gettempdir()).resolve() in data.parents
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    sys.path.insert(0, str(ROOT))
    import uvicorn
    from fastapi import Depends, HTTPException, Request

    from app import app
    from core import auth

    @app.post("/api/test-fixture/expire-owner", dependencies=[Depends(auth.require_auth)])
    def expire(request: Request):
        token = request.cookies.get("aide_session", "")
        if not auth.verify_session(token):
            raise HTTPException(401, "fixture needs an authenticated owner")
        auth._recent_auth[token] = auth.time.time() - auth.RECENT_AUTH_SECONDS - 1
        return {"expired": True}

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["PORT"]), proxy_headers=False)


def run_profile(browser, profile, output, records):
    from playwright.sync_api import expect

    directory = output / profile
    directory.mkdir(parents=True, exist_ok=True)
    current = None
    events = {"console": [], "page_errors": [], "failed_requests": [], "http_errors": []}
    expected_http = Counter()
    expected_failures = Counter()
    cleanup = {}
    process = None
    context = None
    data = None

    def begin(scenario):
        nonlocal current
        current = {
            "scenario_id": scenario,
            "feature_id": SCENARIOS[scenario],
            "profile": profile,
            "browser": browser.version,
            "status": "failed",
            "detail": "workflow did not finish",
        }
        records.append(current)

    def passed(detail):
        current.update(status="passed", detail=detail)
        print(
            json.dumps(
                {"profile": profile, "scenario": current["scenario_id"], "status": "passed"}
            ),
            flush=True,
        )
        (output / "scenarios.json").write_text(json.dumps(records, indent=2))

    try:
        # Recovery staging is a sibling of ALLES_DATA, so own their common parent.
        with tempfile.TemporaryDirectory(prefix="alles-browser-backup-") as owned:
            data = Path(owned).resolve() / "data"
            data.mkdir()
            run_id = uuid.uuid4().hex
            (data / ".alles-test-owner").write_text(run_id)
            port = free_port()
            base = f"http://127.0.0.1:{port}"
            password = "synthetic-owner-" + uuid.uuid4().hex
            vault_password = "synthetic-master-" + uuid.uuid4().hex
            secret = "fixture-only-secret-" + uuid.uuid4().hex
            env = isolated_environment(data, run_id, port, directory)
            env.update(
                AUTH_ENABLED="true",
                AUTH_PASSWORD=password,
                SECRET_KEY=uuid.uuid4().hex + uuid.uuid4().hex,
            )
            cleanup.update(data_root=str(data), owned_root=owned, run_id=run_id, port=port)
            try:
                with (directory / "server.log").open("w") as server_log:
                    process = subprocess.Popen(
                        [sys.executable, str(Path(__file__).resolve()), "--server"],
                        cwd=ROOT,
                        env=env,
                        stdout=server_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=False,
                    )
                    wait_for_server(process, port, run_id, 90)
                    context = browser.new_context(
                        base_url=base,
                        viewport={
                            "width": 390 if profile == "phone" else 1440,
                            "height": 844 if profile == "phone" else 900,
                        },
                        is_mobile=profile == "phone",
                        has_touch=profile == "phone",
                        reduced_motion="reduce",
                        locale="en-US",
                        timezone_id="UTC",
                        service_workers="block",
                        accept_downloads=True,
                    )
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    api = context.request
                    assert api.post("/api/auth/login", data={"password": password}).ok
                    assert api.post("/api/setup/dismiss").json()["setup"]["dismissed"]
                    # Use the persisted appearance contract, not a transient storage override.
                    sys.path.insert(0, str(ROOT))
                    from services.appearance import from_legacy

                    assert api.put(
                        "/api/appearance",
                        data=from_legacy("light" if profile == "phone" else "dark", None),
                    ).ok
                    note_response = api.post(
                        "/api/notes",
                        data={
                            "title": "backup synthetic 中文",
                            "content": "saved original content",
                        },
                    )
                    assert note_response.ok, note_response.text()
                    token = api.post("/api/vault/unlock", data={"password": vault_password}).json()[
                        "token"
                    ]
                    assert api.post(
                        "/api/vault",
                        data={"name": "original credential", "fields": {"password": secret}},
                        headers={"X-Vault-Token": token},
                    ).ok
                    assert api.post("/api/vault/lock", headers={"X-Vault-Token": token}).ok
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
                    page.on(
                        "console",
                        lambda message: events["console"].append(
                            {"type": message.type, "text": message.text}
                        ),
                    )
                    page.on(
                        "requestfailed",
                        lambda request: events["failed_requests"].append(
                            {
                                "path": urlparse(request.url).path,
                                "method": request.method,
                                "failure": request.failure,
                            }
                        ),
                    )
                    page.on(
                        "response",
                        lambda response: (
                            events["http_errors"].append(
                                {
                                    "path": urlparse(response.url).path,
                                    "method": response.request.method,
                                    "status": response.status,
                                }
                            )
                            if response.status >= 400
                            else None
                        ),
                    )

                    def shot(name):
                        page.screenshot(path=str(directory / f"{name}.png"), full_page=True)

                    def fits(locator, *, target=False):
                        measurement = locator.evaluate("""el => {
                            const r = el.getBoundingClientRect();
                            const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                            return {x:r.x,right:r.right,y:r.y,bottom:r.bottom,w:r.width,h:r.height,
                              viewport:innerWidth,height:innerHeight,hit:hit === el || el.contains(hit)};
                        }""")
                        assert (
                            measurement["x"] >= 0
                            and measurement["right"] <= measurement["viewport"]
                        ), measurement
                        assert (
                            measurement["y"] >= 0 and measurement["bottom"] <= measurement["height"]
                        ), measurement
                        assert measurement["hit"], measurement
                        if target:
                            assert measurement["w"] >= 44 and measurement["h"] >= 44, measurement
                        return measurement

                    def vault_fits():
                        measurements = {}
                        for selector in (
                            "#vault-new-btn",
                            "#vault-lock-btn",
                            "#vault-watchtower-btn",
                            ".vault-entry-main",
                            "[data-vault-copy]",
                            "[data-vault-delete]",
                        ):
                            controls = page.locator(selector)
                            measurements[selector] = [
                                fits(controls.nth(i), target=True) for i in range(controls.count())
                            ]
                        assert (
                            page.locator("#vault-legacy-panel").evaluate("el => el.scrollLeft") == 0
                        )
                        assert (
                            page.locator("#vault-view").evaluate(
                                "el => el.scrollWidth - el.clientWidth"
                            )
                            <= 1
                        )
                        return measurements

                    def unlock():
                        page.locator("#vault-pw-input").fill(vault_password)
                        with page.expect_response(
                            lambda r: r.url.endswith("/api/vault/unlock")
                        ) as response:
                            page.locator("#vault-pw-input").press("Enter")
                        assert response.value.ok
                        expect(page.locator("#vault-entry-list")).to_contain_text(
                            "original credential"
                        )
                        return response.value.json()["token"]

                    begin("vault.local-item-recovery")
                    page.goto(base + "/?view=vault")
                    expect(page.locator("#setup-wizard")).to_be_hidden()
                    browser_token = unlock()
                    current["before"] = vault_fits()
                    shot("01-vault-before-new")
                    traversal = []
                    for _ in range(35):
                        page.keyboard.press("Tab")
                        active = page.evaluate("document.activeElement.id")
                        traversal.append(active)
                        if active == "vault-new-btn":
                            break
                    assert traversal[-1] == "vault-new-btn", traversal
                    page.keyboard.press("Enter")
                    expect(page.locator("#vf-name")).to_be_focused()
                    name = ("saved browser credential 中文 " + "long name " * 5).strip()
                    page.locator("#vf-name").fill(name)
                    page.locator("#vf-f-username").fill("synthetic-owner")
                    page.locator("#vf-f-password").fill(secret)
                    page.locator("#vf-save").click()
                    expect(page.locator("#vf-name")).to_have_count(0)
                    expect(page.locator("#vault-entry-list")).to_contain_text(name)
                    expect(page.locator("#vault-new-btn")).to_be_focused()
                    current["after_save"] = vault_fits()
                    current["keyboard_path"] = traversal
                    shot("02-vault-after-keyboard-save")
                    entries = api.get("/api/vault", headers={"X-Vault-Token": browser_token}).json()
                    entry = next(item for item in entries if item["name"] == name)
                    page.locator(f'[data-vault-open="{entry["id"]}"]').click()
                    expect(page.locator("#vf-f-password")).to_have_value(secret)
                    page.keyboard.press("Escape")
                    page.locator("#vault-lock-btn").click()
                    expect(page.locator("#vault-pw-input")).to_be_visible()
                    assert (
                        api.get("/api/vault", headers={"X-Vault-Token": browser_token}).status
                        == 403
                    )
                    page.reload()
                    browser_token = unlock()
                    expect(page.locator("#vault-entry-list")).to_contain_text(name)
                    current["after_reload"] = vault_fits()
                    assert (
                        api.get(
                            f"/api/vault/{entry['id']}/reveal",
                            headers={"X-Vault-Token": browser_token},
                        ).json()["value"]
                        == secret
                    )
                    shot("03-vault-persisted")
                    passed(
                        "keyboard new/save retained visible actions and list; secret persisted, revealed and relocked"
                    )

                    def open_backup():
                        page.goto(base + "/?view=today")
                        expect(page.locator("#setup-wizard")).to_be_hidden()
                        page.locator("#today-settings").click()
                        choose_settings_section(page, "backup")
                        expect(page.locator("#backup-export-btn")).to_be_visible()

                    status = page.locator("#backup-restore-status")
                    choose = page.locator("#backup-restore-btn")
                    choose_key = page.locator("#backup-recovery-key-btn")
                    prompt = page.locator(".dialog-overlay")
                    backup = Path(owned) / "fixture.alles-backup"
                    key = Path(owned) / "fixture.key"

                    def select(locator, file, *, keyboard=False):
                        with page.expect_file_chooser() as chooser:
                            if keyboard:
                                page.keyboard.press("Enter")
                            else:
                                locator.click()
                        chooser.value.set_files(file)

                    def stage_selected():
                        with page.expect_response(
                            lambda r: r.url.endswith("/api/backup/restore") and r.status == 202
                        ) as response:
                            select(choose, backup)
                        assert response.value.ok, response.value.text()
                        expect(status).to_contain_text("verified and staged")
                        expect(choose).to_be_enabled()
                        assert (
                            page.locator("#backup-restore-input").evaluate("el=>el.files.length")
                            == 0
                        )
                        return response.value.json()["restore_id"]

                    def cancel_stage(restore_id):
                        assert api.get(f"/api/backup/restores/{restore_id}").ok
                        assert api.delete(f"/api/backup/restores/{restore_id}").ok
                        assert api.get(f"/api/backup/restores/{restore_id}").status == 404

                    begin("server.local-backup-file-actions")
                    open_backup()
                    for control, destination, route in (
                        ("#backup-export-btn", backup, "/api/backup"),
                        ("#backup-key-export-btn", key, "/api/backup/recovery-key"),
                    ):
                        page.locator(control).click()
                        expect(prompt).to_be_visible()
                        prompt.locator("input").fill(password)
                        expected_failures[(route, "net::ERR_ABORTED")] += 1
                        with page.expect_download() as download:
                            prompt.locator("input").press("Enter")
                        download.value.save_as(destination)
                    assert backup.read_bytes().startswith(b"ALLES-BACKUP-V1\0")
                    current["encrypted_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
                    page.locator("#backup-key-export-btn").focus()
                    page.keyboard.press("Tab")
                    expect(choose).to_be_focused()
                    page.keyboard.press("Tab")
                    expect(choose_key).to_be_focused()
                    current["key_target"] = fits(choose_key, target=True)
                    select(choose_key, key, keyboard=True)
                    expect(page.locator("#backup-recovery-key-name")).to_have_text(key.name)
                    page.keyboard.press("Shift+Tab")
                    expect(choose).to_be_focused()
                    current["backup_target"] = fits(choose, target=True)
                    before_notes = api.get("/api/notes").json()
                    with page.expect_response(
                        lambda r: r.url.endswith("/api/backup/restore")
                    ) as response:
                        select(choose, backup, keyboard=True)
                    assert response.value.status == 202, response.value.text()
                    restore_id = response.value.json()["restore_id"]
                    expect(status).to_contain_text(restore_id)
                    assert api.get("/api/notes").json() == before_notes
                    choose.scroll_into_view_if_needed()
                    shot("04-backup-keyboard-staged")
                    open_backup()
                    assert api.get(f"/api/backup/restores/{restore_id}").ok
                    assert api.get("/api/notes").json() == before_notes
                    cancel_stage(restore_id)
                    current["restore_id"] = restore_id
                    passed(
                        "keyboard activated both file choosers; real encrypted stage persisted after reload and canceled without live changes"
                    )

                    begin("server.local-backup-retry")
                    failures = (
                        ("transport", "connection lost while checking the backup"),
                        ("malformed-json", "could not read the backup response"),
                        ("missing-stage", "could not verify the backup response"),
                    )
                    current["integration_mode"] = (
                        "explicit reset and response corruption; each retry reaches real backup staging"
                    )
                    for fault, message in failures:
                        if fault == "transport":
                            expected_failures[
                                ("/api/backup/restore", "net::ERR_CONNECTION_RESET")
                            ] += 1
                            page.route(
                                "**/api/backup/restore",
                                lambda route: route.abort("connectionreset"),
                                times=1,
                            )
                        else:
                            body = "{" if fault == "malformed-json" else "{}"
                            page.route(
                                "**/api/backup/restore",
                                lambda route, _request, body=body: route.fulfill(
                                    status=202, content_type="application/json", body=body
                                ),
                                times=1,
                            )
                        select(choose, backup)
                        expect(status).to_contain_text(message)
                        expect(status).to_contain_text("choose a backup file to try again")
                        expect(choose).to_be_enabled()
                        expect(choose_key).to_be_enabled()
                        assert (
                            page.locator("#backup-restore-input").evaluate("el=>el.files.length")
                            == 0
                        )
                        choose.scroll_into_view_if_needed()
                        shot(f"05-backup-{fault}-retry")
                        cancel_stage(stage_selected())
                    invalid = Path(owned) / "invalid.alles-backup"
                    invalid.write_bytes(b"invalid synthetic backup")
                    expected_http[("/api/backup/restore", 400)] += 1
                    select(choose, invalid)
                    expect(status).to_contain_text("backup ZIP is invalid or incomplete")
                    expect(choose).to_be_enabled()
                    cancel_stage(stage_selected())
                    assert api.get("/api/notes").json() == before_notes
                    passed(
                        "reset, malformed JSON, invalid success payload and real invalid backup show errors; same-file retry stages successfully"
                    )

                    begin("server.local-backup-owner-confirmation")
                    current["integration_mode"] = (
                        "real auth/backup endpoints; recent confirmation timestamp deliberately expired"
                    )
                    expired = api.post("/api/test-fixture/expire-owner")
                    assert expired.ok, expired.text()
                    expected_http[("/api/backup/restore", 403)] += 1
                    select(choose, backup)
                    expect(prompt).to_be_visible()
                    expect(choose).to_be_disabled()
                    expect(choose_key).to_be_disabled()
                    page.keyboard.press("Escape")
                    expect(status).to_contain_text("backup check canceled")
                    expect(choose).to_be_enabled()
                    expect(choose).to_be_focused()
                    assert (
                        page.locator("#backup-restore-input").evaluate("el=>el.files.length") == 0
                    )
                    shot("06-backup-confirmation-canceled")
                    expected_http[("/api/backup/restore", 403)] += 1
                    expected_http[("/api/auth/reauth", 401)] += 1
                    select(choose, backup)
                    prompt.locator("input").fill("wrong-owner-password")
                    prompt.locator("input").press("Enter")
                    expect(status).to_contain_text("backup check canceled")
                    expect(choose).to_be_enabled()
                    select(choose_key, key)
                    expected_http[("/api/backup/restore", 403)] += 1
                    select(choose, backup)
                    expect(prompt).to_be_visible()
                    prompt.locator("input").fill(password)
                    with page.expect_response(
                        lambda r: r.url.endswith("/api/backup/restore") and r.status == 202
                    ) as response:
                        prompt.locator("input").press("Enter")
                    assert response.value.status == 202, response.value.text()
                    restore_id = response.value.json()["restore_id"]
                    expect(status).to_contain_text(restore_id)
                    expect(choose).to_be_enabled()
                    expect(choose_key).to_be_enabled()
                    assert (
                        page.locator("#backup-restore-input").evaluate("el=>el.files.length") == 0
                    )
                    assert (
                        page.locator("#backup-recovery-key-input").evaluate("el=>el.files.length")
                        == 0
                    )
                    shot("07-backup-owner-recovered")
                    open_backup()
                    cancel_stage(restore_id)
                    assert api.get("/api/notes").json() == before_notes
                    assert not events["page_errors"], events
                    assert (
                        Counter((x["path"], x["status"]) for x in events["http_errors"])
                        == expected_http
                    ), events
                    assert (
                        Counter((x["path"], x["failure"]) for x in events["failed_requests"])
                        == expected_failures
                    ), events
                    console_errors = [x for x in events["console"] if x["type"] == "error"]
                    assert len(console_errors) == sum(expected_http.values()) + 1, events
                    passed(
                        "real expired confirmation supports cancel, wrong password and successful multipart retry; stage and original notes persist"
                    )
            finally:
                try:
                    if context:
                        if current and current["status"] != "passed":
                            try:
                                page.screenshot(path=str(directory / "failure.png"), full_page=True)
                            except Exception:
                                pass
                        (directory / "events.json").write_text(json.dumps(events, indent=2))
                        context.tracing.stop(path=str(directory / "trace.zip"))
                        context.close()
                finally:
                    if process:
                        stop_process(process, process_group=False)
                        cleanup["server_stopped"] = process.poll() is not None
    except BaseException as error:
        if current:
            current["failure"] = repr(error)
        raise
    finally:
        if data:
            cleanup["data_removed"] = not data.exists()
            cleanup["owned_root_removed"] = not data.parent.exists()
            with socket.socket() as probe:
                probe.settimeout(0.2)
                cleanup["port_closed"] = probe.connect_ex(("127.0.0.1", cleanup["port"])) != 0
        (directory / "owned-fixture.json").write_text(json.dumps(cleanup, indent=2))
        (output / "scenarios.json").write_text(json.dumps(records, indent=2))
    assert all(
        cleanup.get(field)
        for field in ("data_removed", "owned_root_removed", "port_closed", "server_stopped")
    ), cleanup


def run():
    from playwright.sync_api import sync_playwright

    output = (
        Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
        if os.environ.get("ALLES_BROWSER_ARTIFACTS")
        else Path(tempfile.mkdtemp(prefix="alles-vault-backup-"))
    )
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for profile in ("desktop", "phone"):
                run_profile(browser, profile, output, records)
        finally:
            browser.close()
    print(json.dumps({"status": "passed", "scenarios": records}))


if __name__ == "__main__":

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    if "--server" in sys.argv:
        serve_fixture()
    else:
        run()
