"""Real isolated owner setup, sign-in and recent-owner recovery.

Run directly or through run_browser_gates.py. Each profile owns its own server and
fresh data because creating an owner lock changes the whole single-user instance.
Only explicit transport failures, confirmation age, and the companion installer
are controlled fixtures; password verification and route authorization stay real.
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from pw_settings_helpers import choose_settings_section

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from run_browser_gates import (  # noqa: E402
    free_port,
    isolated_environment,
    owned_data,
    stop_process,
    wait_for_server,
)


def serve_fixture():
    """Test-only server entrypoint. Never installs anything in the host's Obsidian."""
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
    from services import obsidian_setup

    installs = []

    def status(_vault):
        return {
            "obsidian_detected": False,
            "companion_installed": bool(installs),
            "companion_integrity": "verified" if installs else "not-installed",
            "plugin_path": "",
        }

    def install(vault):
        assert data in Path(vault).resolve().parents
        installs.append(str(vault))
        return status(vault)

    obsidian_setup.install_companion = install
    obsidian_setup.status = status
    obsidian_setup.detect_obsidian = lambda: None

    @app.post("/api/test-fixture/expire-owner", dependencies=[Depends(auth.require_auth)])
    def expire(request: Request):
        token = request.cookies.get("aide_session", "")
        if not auth.verify_session(token):
            raise HTTPException(401, "fixture needs an authenticated owner")
        auth._recent_auth[token] = 0
        return {"expired": True}

    @app.get("/api/test-fixture/installs", dependencies=[Depends(auth.require_auth)])
    def installed():
        return {"count": len(installs)}

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["PORT"]), proxy_headers=False)


def check_profile(browser, profile, output, records):
    from playwright.sync_api import expect

    directory = output / profile
    directory.mkdir(parents=True, exist_ok=True)
    events = {"console": [], "page_errors": [], "failed_requests": [], "http_errors": []}
    expected_http = Counter()
    current = None

    def begin(scenario):
        nonlocal current
        current = {
            "scenario_id": scenario,
            "feature_id": "setup-security.owner-setup",
            "profile": profile,
            "status": "failed",
            "detail": "workflow did not finish",
        }
        records.append(current)

    def passed():
        current.update(status="passed", detail="real local persistence and browser assertions")

    cleanup = {}
    data = None
    try:
        with owned_data() as (data, run_id):
            port = free_port()
            base = f"http://127.0.0.1:{port}"
            env = isolated_environment(data, run_id, port, directory)
            # An explicit false override would prevent the owner lock created by the UI.
            env.pop("AUTH_ENABLED", None)
            env["SECRET_KEY"] = "synthetic-setup-browser-fixture-only"
            process = None
            context = None
            try:
                with (directory / "server.log").open("w") as server_log:
                    process = subprocess.Popen(
                        [sys.executable, str(Path(__file__).resolve()), "--server"],
                        cwd=ROOT,
                        env=env,
                        stdout=server_log,
                        stderr=subprocess.STDOUT,
                        # Stay in the gate's group so runner timeouts also stop descendants.
                        start_new_session=False,
                    )
                    wait_for_server(process, port, run_id, 60)
                    context = browser.new_context(
                        viewport={"width": 390 if profile == "phone" else 1440, "height": 900},
                        is_mobile=profile == "phone",
                        has_touch=profile == "phone",
                        locale="en-CA",
                        timezone_id="America/Toronto",
                        reduced_motion="reduce",
                        service_workers="block",
                    )
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)
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
                            {"path": urlparse(request.url).path, "failure": request.failure}
                        ),
                    )
                    page.on(
                        "response",
                        lambda response: (
                            events["http_errors"].append(
                                {"path": urlparse(response.url).path, "status": response.status}
                            )
                            if response.status >= 400
                            else None
                        ),
                    )

                    def state():
                        response = context.request.get(base + "/api/setup/status")
                        assert response.ok
                        return response.json()["setup"]

                    def expire():
                        assert context.request.post(base + "/api/test-fixture/expire-owner").ok

                    def installs():
                        return context.request.get(base + "/api/test-fixture/installs").json()[
                            "count"
                        ]

                    def shot(name):
                        layout = page.evaluate("""() => ({
                            width: innerWidth, viewport: visualViewport.width,
                            document: document.documentElement.scrollWidth,
                            body: document.body.scrollWidth,
                            overflow: [...document.querySelectorAll('body *')].map(element => {
                                const box = element.getBoundingClientRect();
                                const style = getComputedStyle(element);
                                return {id: element.id, tag: element.tagName, class: element.className,
                                    right: box.right, width: box.width, display: style.display,
                                    visibility: style.visibility};
                            }).filter(row => row.width && row.right > innerWidth + 1).slice(0, 30)
                        })""")
                        (directory / f"{name}-layout.json").write_text(json.dumps(layout, indent=2))
                        page.screenshot(path=str(directory / f"{name}.png"))

                    begin("setup-security.owner-setup.3")
                    page.goto(base, wait_until="networkidle")
                    expect(page.locator("#sw-name")).to_be_visible()
                    page.locator("#sw-name").fill("Synthetic owner 研究")
                    page.locator("#sw-timezone").fill("America/Toronto")
                    page.route(
                        "**/api/setup/step",
                        lambda route: route.fulfill(
                            status=503,
                            content_type="application/json",
                            body=json.dumps({"message": "synthetic save failure; retry"}),
                        ),
                        times=1,
                    )
                    expected_http[("/api/setup/step", 503)] += 1
                    page.locator("#sw-save").click()
                    expect(page.locator("#sw-status")).to_contain_text("synthetic save failure")
                    expect(page.locator("#sw-name")).to_have_value("Synthetic owner 研究")
                    assert state()["completed_steps"] == []
                    page.locator("#sw-save").click()
                    expect(page.locator("#setup-dots")).to_contain_text("2 / 5")
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#setup-dots")).to_contain_text("2 / 5")
                    assert state()["username"] == "Synthetic owner 研究"
                    page.locator("#setup-skip").click()
                    expect(page.locator("#setup-wizard")).to_be_hidden()
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#setup-wizard")).to_be_hidden()
                    page.locator("#today-settings").click()
                    if profile == "phone":
                        choose_settings_section(page, "themes")
                        with page.expect_response(
                            lambda response: (
                                response.url.endswith("/api/appearance")
                                and response.request.method == "PUT"
                            )
                        ) as appearance:
                            page.locator('[data-theme-mode="light"]').click()
                        assert appearance.value.ok
                        expect(page.locator("html")).to_have_attribute("data-theme", "light")
                    choose_settings_section(page, "backup")
                    page.locator("#setup-resume-btn").click()
                    expect(page.locator("#setup-dots")).to_contain_text("2 / 5")
                    passed()

                    begin("setup.companion-reauth")
                    page.locator('#sw-access [data-value="device"]').click()
                    page.keyboard.press("ArrowRight")
                    expect(page.locator('#sw-access [data-value="lan"]')).to_have_attribute(
                        "aria-checked", "true"
                    )
                    password = "synthetic-owner-browser-passphrase"
                    page.locator("#sw-owner-password").fill("short")
                    page.locator("#sw-save").click()
                    expect(page.locator("#sw-status")).to_contain_text("12 characters")
                    page.locator("#sw-owner-password").fill(password)
                    page.locator("#sw-save").click()
                    expect(page.locator("#setup-dots")).to_contain_text("3 / 5")
                    page.locator("#sw-vault").fill(str(data / "visible" / "Vault"))
                    page.locator("#sw-files").fill(str(data / "visible" / "Files"))
                    page.locator("#sw-save").click()
                    expect(page.locator("#sw-install-obsidian")).to_be_visible()
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#setup-dots")).to_contain_text("3 / 5")
                    expire()
                    button = page.locator("#sw-install-obsidian")
                    dialog = page.locator(".dialog-overlay")
                    expected_http[("/api/setup/obsidian", 403)] += 3
                    button.click()
                    expect(dialog).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(dialog).to_have_count(0)
                    expect(page.locator("#setup-wizard")).to_be_visible()
                    expect(button).to_be_focused()
                    expect(page.locator("#sw-status")).to_contain_text("confirmation cancelled")
                    assert installs() == 0
                    button.click()
                    expect(dialog).to_be_visible()
                    expected_http[("/api/auth/reauth", 401)] += 1
                    dialog.locator(".dialog-input").fill("wrong-synthetic-password")
                    dialog.locator(".dialog-input").press("Enter")
                    expect(page.locator("#sw-status")).to_contain_text("invalid password")
                    assert installs() == 0
                    button.click()
                    expect(dialog).to_be_visible()
                    expect(dialog.locator(".dialog-input")).to_be_focused()
                    dialog.locator(".dialog-input").fill(password)
                    dialog.locator(".dialog-input").press("Enter")
                    expect(page.locator("#sw-obsidian")).to_contain_text("installed and verified")
                    expect(page.locator("#sw-status")).to_be_empty()
                    expect(page.locator("#sw-save")).to_be_focused()
                    assert installs() == 1
                    assert not (data / "visible" / "Vault" / ".obsidian").exists()
                    shot("companion-confirmed-simulated-install")
                    current["integration_mode"] = (
                        "real auth; simulated companion install after authorization"
                    )
                    passed()

                    begin("setup-security.owner-setup.1")
                    page.locator("#sw-save").click()
                    expect(page.locator("#setup-dots")).to_contain_text("4 / 5")
                    page.locator("#sw-save").click()
                    expect(page.locator("#setup-dots")).to_contain_text("5 / 5")
                    page.locator("#sw-save").click()
                    expect(page.locator("#setup-dots")).to_have_text("setup complete")
                    page.locator("#sw-start").click()
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#setup-wizard")).to_be_hidden()
                    assert state()["completed"]
                    context.clear_cookies()
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#login-pw")).to_be_visible()
                    assert context.request.get(base + "/api/setup/status").status == 401
                    expected_http[("/api/auth/login", 401)] += 1
                    page.get_by_role("textbox", name="password", exact=True).fill("wrong-password")
                    page.locator("#login-submit").click()
                    error = page.locator("#login-error")
                    expect(error).to_contain_text("wrong password")
                    expect(error).to_be_visible()
                    assert error.evaluate("""element => {
                        const box = element.getBoundingClientRect();
                        const top = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
                        return (top === element || element.contains(top))
                            && getComputedStyle(element).color !== getComputedStyle(element).backgroundColor;
                    }""")
                    # The error belongs to the foreground sign-in surface, not a covered toast.
                    assert page.locator("#login-screen #login-error").count() == 1
                    for target in (page.locator("#login-pw"), page.locator("#login-submit")):
                        box = target.bounding_box()
                        assert box["width"] >= 44 and box["height"] >= 44, box
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.wait_for_timeout(250)
                    shot("login-invalid-password")
                    if profile == "phone":
                        # A short viewport is a layout check, not a native on-screen keyboard test.
                        page.set_viewport_size({"width": 390, "height": 420})
                        for target in (
                            page.locator("#login-pw"),
                            page.locator("#login-submit"),
                            error,
                        ):
                            box = target.bounding_box()
                            assert box["y"] >= 0 and box["y"] + box["height"] <= 420, box
                        shot("login-short-viewport")
                        page.set_viewport_size({"width": 390, "height": 900})
                    page.locator("#login-pw").fill(password)
                    page.locator("#login-pw").press("Enter")
                    expect(page.locator("#today-view")).to_be_visible()
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#today-view")).to_be_visible()
                    assert state()["completed"]
                    passed()

                    begin("setup.login-recovery")
                    context.clear_cookies()
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#login-pw")).to_be_visible()
                    page.locator("#login-pw").fill(password)
                    for status, message in [
                        (503, "temporarily unavailable"),
                        (429, "too many attempts"),
                    ]:
                        page.route(
                            "**/api/auth/login",
                            lambda route: route.fulfill(
                                status=status, content_type="application/json", body="{}"
                            ),
                            times=1,
                        )
                        expected_http[("/api/auth/login", status)] += 1
                        page.locator("#login-submit").click()
                        expect(error).to_contain_text(message)
                        expect(page.locator("#login-pw")).to_have_value(password)
                        expect(page.locator("#login-submit")).to_be_enabled()
                    page.route(
                        "**/api/auth/login", lambda route: route.abort("connectionfailed"), times=1
                    )
                    page.locator("#login-submit").click()
                    expect(error).to_contain_text("could not reach Alles")
                    expect(page.locator("#login-pw")).to_have_value(password)
                    expect(page.locator("#login-submit")).to_be_enabled()
                    shot("login-network-failure")
                    page.locator("#login-pw").press("Enter")
                    expect(page.locator("#today-view")).to_be_visible()
                    assert context.request.get(base + "/api/auth/me").json()["authenticated"]
                    passed()

                    begin("setup-security.owner-setup.2")
                    expire()
                    page.locator("#today-settings").click()
                    choose_settings_section(page, "developer")
                    page.locator("#token-name").fill("Synthetic acceptance token")
                    generate = page.locator("#token-add-btn")
                    expected_http[("/api/tokens", 403)] += 3
                    generate.click()
                    expect(dialog).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(dialog).to_have_count(0)
                    expect(page.locator("#settings-modal")).to_be_visible()
                    expect(generate).to_be_focused()
                    expect(page.locator("#token-name")).to_have_value("Synthetic acceptance token")
                    assert context.request.get(base + "/api/tokens").json() == []
                    shot("owner-cancel-keeps-settings")
                    generate.click()
                    expect(dialog).to_be_visible()
                    expected_http[("/api/auth/reauth", 401)] += 1
                    dialog.locator(".dialog-input").fill("wrong-synthetic-password")
                    with page.expect_response(
                        lambda r: r.url.endswith("/api/auth/reauth")
                    ) as denied:
                        dialog.locator(".dialog-input").press("Enter")
                    assert denied.value.status == 401
                    assert context.request.get(base + "/api/tokens").json() == []
                    expect(page.locator("#token-name")).to_have_value("Synthetic acceptance token")
                    generate.click()
                    expect(dialog).to_be_visible()
                    dialog.locator(".dialog-input").fill(password)
                    dialog.locator(".dialog-input").press("Enter")
                    expect(page.locator("#token-list")).to_contain_text(
                        "Synthetic acceptance token"
                    )
                    assert len(context.request.get(base + "/api/tokens").json()) == 1
                    page.reload(wait_until="networkidle")
                    page.locator("#today-settings").click()
                    choose_settings_section(page, "developer")
                    expect(page.locator("#token-list")).to_contain_text(
                        "Synthetic acceptance token"
                    )
                    passed()

                    assert not events["page_errors"], events
                    assert events["failed_requests"] == [
                        {"path": "/api/auth/login", "failure": "net::ERR_CONNECTION_FAILED"}
                    ], events
                    assert (
                        Counter((r["path"], r["status"]) for r in events["http_errors"])
                        == expected_http
                    ), events
                    errors = [r["text"] for r in events["console"] if r["type"] == "error"]
                    allowed = re.compile(
                        r"^Failed to load resource: (?:the server responded with a status of (?:401|403|429|503) "
                        r"\([^)]+\)|net::ERR_CONNECTION_FAILED)$"
                    )
                    assert len(errors) == sum(expected_http.values()) + 1, events
                    assert all(allowed.fullmatch(message) for message in errors), events
            except Exception:
                if context and context.pages:
                    context.pages[0].screenshot(path=str(directory / "failure.png"), full_page=True)
                raise
            finally:
                if context:
                    context.tracing.stop(path=str(directory / "trace.zip"))
                    context.close()
                if process:
                    stop_process(process, process_group=False)
                (directory / "events.json").write_text(json.dumps(events, indent=2))
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                cleanup = {"server_stopped": process is None or process.poll() is not None}
    finally:
        cleanup["temporary_data_removed"] = data is not None and not data.exists()
        (directory / "cleanup.json").write_text(json.dumps(cleanup, indent=2))


def run():
    from playwright.sync_api import sync_playwright

    output = Path(
        os.environ.get("ALLES_BROWSER_ARTIFACTS") or tempfile.mkdtemp(prefix="alles-setup-auth-")
    )
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for profile in ("desktop", "phone"):
                check_profile(browser, profile, output, records)
        finally:
            browser.close()
    print(json.dumps({"status": "passed", "scenarios": records, "artifacts": str(output)}))


if __name__ == "__main__":
    if sys.argv[1:] == ["--server"]:
        serve_fixture()
    else:

        def interrupted(_signal, _frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, interrupted)
        run()
