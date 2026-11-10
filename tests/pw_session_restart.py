"""An open page across restarts, an ended session, and a start that never finishes.

Run directly or through run_browser_gates.py. The gate owns its server because it restarts
it: sign in, restart (the page keeps working), lose the session (sign in shows over the same
page and it carries on), then a start whose module never loads and one whose first request
never answers (a "not started" screen with retry instead of a blank page).
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_browser_gates import (  # noqa: E402
    free_port,
    isolated_environment,
    owned_data,
    stop_process,
    wait_for_server,
)

PASSWORD = "synthetic-session-gate-only"
STATE = """() => ({
  login: getComputedStyle(document.getElementById('login-screen')).display,
  down: getComputedStyle(document.getElementById('notrunning-screen')).display,
  preboot: document.body.classList.contains('preboot'),
})"""


def check(browser, output: Path, records: list) -> None:
    def scenario(name: str) -> dict:
        record = {
            "scenario_id": name,
            "feature_id": "setup-security.owner-setup",
            "profile": "ipad",
            "status": "failed",
            "detail": "workflow did not finish",
        }
        records.append(record)
        return record

    with owned_data() as (data, run_id):
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = isolated_environment(data, run_id, port, output)
        env.update(AUTH_ENABLED="true", AUTH_PASSWORD=PASSWORD)
        server = None

        def start():
            nonlocal server
            log = (output / "server.log").open("a")
            server = subprocess.Popen(
                [sys.executable, "app.py"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=False,
            )
            wait_for_server(server, port, run_id, 90)

        def restart():
            stop_process(server, process_group=False)
            start()

        def settings_status(page) -> int:
            return page.evaluate("fetch('/api/settings').then(reply => reply.status)")

        try:
            start()
            context = browser.new_context(
                viewport={"width": 1210, "height": 834}, service_workers="block"
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            current = scenario("a session survives a restart")
            page.goto(base + "/")
            page.wait_for_selector("#login-pw", state="visible")
            page.fill("#login-pw", PASSWORD)
            page.click("#login-submit")
            page.wait_for_function(
                "() => !document.body.classList.contains('login-mode')"
                " && !document.body.classList.contains('preboot')"
            )
            # let the start finish first: a restart under a page that is still loading its
            # modules is another case than the one checked here
            page.wait_for_load_state("networkidle")
            saved = (data / "sessions.json").read_text("utf-8")
            cookie = next(c for c in context.cookies() if c["name"] == "aide_session")
            assert cookie["value"] not in saved, "the raw session token is on disk"
            restart()
            assert settings_status(page) == 200
            assert page.evaluate(STATE) == {"login": "none", "down": "none", "preboot": False}
            current.update(status="passed", detail="same page, no reload, after a real restart")

            current = scenario("an ended session shows sign in over the running page")
            page.evaluate("document.body.dataset.gateMarker = 'same-page'")
            (data / "sessions.json").unlink()
            restart()
            assert settings_status(page) == 401
            # coming back to the page asks whether the session is still there (browsers that
            # report a response's status to the page notice the 401 itself, without this)
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_selector("#login-pw", state="visible")
            page.fill("#login-pw", "not-the-password")
            page.click("#login-submit")
            page.wait_for_function(
                "() => document.getElementById('login-error').textContent.trim() !== ''"
            )
            assert page.evaluate(STATE)["login"] == "flex"
            page.fill("#login-pw", PASSWORD)
            page.click("#login-submit")
            page.wait_for_function("() => !document.body.classList.contains('login-mode')")
            assert settings_status(page) == 200
            # the page was not started again: its own state is still there
            assert page.evaluate("document.body.dataset.gateMarker") == "same-page"
            assert page.evaluate("document.getElementById('login-pw').value") == ""
            assert not errors, errors
            current.update(status="passed", detail="signed in again without a reload")
            context.close()

            current = scenario("a module that never loads ends in a retry screen")
            context = browser.new_context(
                viewport={"width": 1210, "height": 834}, service_workers="block"
            )
            page = context.new_page()
            page.route("**/static/js/chat.js*", lambda route: route.abort())
            began = time.monotonic()
            page.goto(base + "/")
            page.wait_for_selector("#notrunning-screen", state="visible", timeout=20_000)
            assert 10 < time.monotonic() - began < 20
            assert page.locator("#notrunning-retry").is_visible()
            assert page.evaluate(STATE)["preboot"] is False
            current.update(status="passed", detail="bootwatch.js showed retry")
            context.close()

            current = scenario("a first request that never answers ends in a retry screen")
            context = browser.new_context(
                viewport={"width": 390, "height": 844}, service_workers="block"
            )
            page = context.new_page()
            held = []  # never answered: the request hangs until the page gives up on it
            page.route("**/api/auth/me", lambda route: held.append(route))
            began = time.monotonic()
            page.goto(base + "/")
            page.wait_for_selector("#notrunning-screen", state="visible", timeout=20_000)
            assert time.monotonic() - began < 15
            current.update(status="passed", detail="the sign in check gives up after 8 seconds")
            context.close()

            current = scenario("a sign in screen left open is not replaced")
            context = browser.new_context(
                viewport={"width": 390, "height": 844}, service_workers="block"
            )
            page = context.new_page()
            page.goto(base + "/")
            page.wait_for_selector("#login-pw", state="visible")
            page.wait_for_timeout(13_500)
            assert page.evaluate(STATE) == {"login": "flex", "down": "none", "preboot": False}
            current.update(status="passed", detail="the limit only acts on a page still hidden")
            context.close()
        finally:
            if server:
                stop_process(server, process_group=False)
            (output / "scenarios.json").write_text(json.dumps(records, indent=2))


def run():
    from playwright.sync_api import sync_playwright

    output = Path(
        os.environ.get("ALLES_BROWSER_ARTIFACTS")
        or tempfile.mkdtemp(prefix="alles-session-restart-")
    )
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        # webkit: the owner's ipad is where a lost session was seen
        browser = playwright.webkit.launch()
        try:
            check(browser, output, records)
        finally:
            browser.close()
    print(json.dumps({"status": "passed", "scenarios": records, "artifacts": str(output)}))


if __name__ == "__main__":

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    run()
