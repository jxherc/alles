"""Owned offline replay recovery against real authentication, IndexedDB and SQLite.

401 comes from restarting the owned server, invalidating its in-memory session.
409/422/503 responses are explicit service-worker transport fault simulations.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from run_browser_gates import (  # noqa: E402
    free_port,
    isolated_environment,
    owned_data,
    stop_process,
    wait_for_server,
)

FEATURE = "extension-mobile.pwa-and-extension"
MODES = (
    "session-restart-inline",
    "session-restart-reload",
    "simulated-409",
    "simulated-422",
    "simulated-503",
)


def run():
    output = (
        Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
        if os.environ.get("ALLES_BROWSER_ARTIFACTS")
        else Path(tempfile.mkdtemp(prefix="alles-offline-rejection-"))
    )
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with owned_data() as (data, run_id):
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        password = "synthetic-replay-" + uuid.uuid4().hex
        env = isolated_environment(data, run_id, port, output)
        env.update(
            AUTH_ENABLED="true",
            AUTH_PASSWORD=password,
            SECRET_KEY=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        server = None
        with (output / "auth-server.log").open("w") as log:

            def start():
                process = subprocess.Popen(
                    [sys.executable, "app.py"],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=False,
                )
                try:
                    wait_for_server(process, port, run_id, 90)
                except BaseException:
                    stop_process(process, process_group=False)
                    raise
                return process

            server = start()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    inspector = p.request.new_context(base_url=base)
                    assert inspector.post("/api/auth/login", data={"password": password}).ok
                    # This gate starts with a returning owner. First-run setup has its own gate.
                    dismissed = inspector.post("/api/setup/dismiss")
                    assert dismissed.ok, dismissed.text()
                    assert dismissed.json()["setup"]["dismissed"] is True
                    setup = inspector.get("/api/setup/status")
                    assert setup.ok and setup.json()["setup"]["dismissed"] is True
                    for profile in ("desktop", "phone"):
                        for mode in MODES:
                            dest = output / f"{profile}-{mode}"
                            dest.mkdir(exist_ok=True)
                            auth = mode.startswith("session-restart")
                            code = 401 if auth else int(mode.split("-")[1])
                            ordered = code == 409
                            record = {
                                "scenario_id": "pwa.queue-auth-recovery"
                                if auth
                                else "pwa.queue-rejection-recovery",
                                "feature_id": FEATURE,
                                "profile": profile,
                                "mode": mode,
                                "status": "failed",
                                "detail": "workflow did not finish",
                                "browser": browser.version,
                                "run_id": run_id,
                                "fixture": "returning user; setup dismissed through the authenticated API",
                                "integration_mode": "real owned server restart"
                                if auth
                                else f"simulated replay HTTP {code}; real UI, queue and persistence",
                            }
                            records.append(record)
                            context = browser.new_context(
                                viewport={
                                    "width": 390 if profile == "phone" else 1440,
                                    "height": 844 if profile == "phone" else 900,
                                },
                                is_mobile=profile == "phone",
                                has_touch=profile == "phone",
                                locale="en-US",
                                timezone_id="UTC",
                                reduced_motion="reduce",
                                color_scheme="light" if profile == "phone" else "dark",
                            )
                            context.tracing.start(screenshots=True, snapshots=True, sources=True)
                            page = context.new_page()
                            page.set_default_timeout(15000)
                            state = {"offline": False, "expired": False}
                            events = {
                                "console": [],
                                "page_errors": [],
                                "failed_requests": [],
                                "http_errors": [],
                            }
                            page.on(
                                "console",
                                lambda m: events["console"].append(
                                    {"type": m.type, "text": m.text, **state}
                                ),
                            )
                            page.on("pageerror", lambda e: events["page_errors"].append(str(e)))
                            page.on(
                                "requestfailed",
                                lambda r: events["failed_requests"].append(
                                    {
                                        "url": r.url,
                                        "method": r.method,
                                        "failure": r.failure,
                                        **state,
                                    }
                                ),
                            )
                            page.on(
                                "response",
                                lambda r: (
                                    events["http_errors"].append(
                                        {
                                            "url": r.url,
                                            "method": r.request.method,
                                            "status": r.status,
                                            **state,
                                        }
                                    )
                                    if r.status >= 400
                                    else None
                                ),
                            )
                            note = f"saved offline {profile} {mode} 中文 long note retained after rejection"

                            later_note = (
                                f"later offline {profile} change after a rejected predecessor"
                            )

                            def saved(which=note):
                                response = inspector.get("/api/health")
                                assert response.ok, response.text()
                                return [
                                    item
                                    for item in response.json()["entries"]
                                    if item["note"] == which
                                ]

                            def login_ui():
                                expect(page.locator("#login-screen")).to_be_visible()
                                page.locator("#login-pw").fill(password)
                                page.locator("#login-submit").click()
                                expect(page.locator("#login-screen")).to_be_hidden()

                            def queue():
                                return worker.evaluate("async()=>await _all()")

                            def until(predicate):
                                deadline = time.monotonic() + 15
                                while time.monotonic() < deadline:
                                    if predicate():
                                        return
                                    page.wait_for_timeout(100)
                                raise AssertionError("expected state did not arrive")

                            def review():
                                page.locator("#sync-indicator").get_by_role(
                                    "button", name="review", exact=True
                                ).click()
                                dialog = page.get_by_role(
                                    "dialog", name="offline changes", exact=True
                                )
                                expect(dialog).to_be_visible()
                                expect(dialog).to_contain_text(note)
                                expect(dialog).to_contain_text("73.875")
                                expect(
                                    dialog.get_by_role("button", name="close", exact=True)
                                ).to_be_focused()
                                first_control = (
                                    dialog.get_by_label("Alles password", exact=True)
                                    if auth
                                    else dialog.get_by_role(
                                        "button", name="save a copy", exact=True
                                    ).first
                                )
                                dialog.get_by_role("button", name="close", exact=True).press("Tab")
                                expect(first_control).to_be_focused()
                                first_control.press("Shift+Tab")
                                expect(
                                    dialog.get_by_role("button", name="close", exact=True)
                                ).to_be_focused()
                                dimensions = dialog.evaluate("""el => ({
                                  rect: { x: el.getBoundingClientRect().x, right: el.getBoundingClientRect().right },
                                  viewport: innerWidth, overflow: el.scrollWidth - el.clientWidth,
                                  targets: [...el.querySelectorAll('button, input')].map(b => ({text:b.textContent, width:b.getBoundingClientRect().width,height:b.getBoundingClientRect().height}))
                                })""")
                                assert (
                                    dimensions["rect"]["x"] >= 0
                                    and dimensions["rect"]["right"] <= dimensions["viewport"]
                                )
                                assert dimensions["overflow"] <= 1, dimensions
                                assert all(
                                    x["height"] >= 44 and x["width"] >= 44
                                    for x in dimensions["targets"]
                                ), dimensions
                                record["review_dimensions"] = dimensions
                                return dialog

                            try:
                                page.goto(base, wait_until="networkidle")
                                login_ui()
                                expect(page.locator("#setup-wizard")).to_be_hidden()
                                page.wait_for_function("navigator.serviceWorker.controller")
                                page.goto(base + "/?view=today", wait_until="networkidle")
                                expect(page.locator("#setup-wizard")).to_be_hidden()
                                page.locator("#today-settings").click()
                                page.locator('.s-nav-item[data-pane="themes"]').click()
                                theme = "light" if profile == "phone" else "dark"
                                with page.expect_response(
                                    lambda r: (
                                        r.url.endswith("/api/appearance")
                                        and r.request.method == "PUT"
                                    )
                                ) as appearance:
                                    page.locator(f'[data-theme-mode="{theme}"]').click()
                                assert appearance.value.ok
                                page.locator("#settings-modal-close").click()
                                page.goto(base + "/?view=health-log", wait_until="networkidle")
                                if theme == "light":
                                    expect(page.locator("html")).to_have_attribute(
                                        "data-theme", "light"
                                    )
                                else:
                                    expect(page.locator("html")).not_to_have_attribute(
                                        "data-theme", "light"
                                    )
                                worker = context.service_workers[0]
                                assert queue() == []
                                page.locator("#health-add-toggle").click()
                                page.locator("#health-value").fill("73.875")
                                page.locator("#health-note").fill(note)
                                state["offline"] = True
                                context.set_offline(True)
                                with page.expect_response(
                                    lambda r: (
                                        r.url.endswith("/api/health") and r.request.method == "POST"
                                    )
                                ) as initial:
                                    page.locator("#health-create").press("Enter")
                                assert initial.value.json() == {"queued": True, "offline": True}
                                assert initial.value.from_service_worker
                                expect(page.locator("#health-entry-form")).to_have_count(0)
                                expect(page.locator("#sync-indicator")).to_contain_text("1 pending")
                                original = queue()
                                assert len(original) == 1 and not saved()
                                if ordered:
                                    page.locator("#health-add-toggle").click()
                                    page.locator("#health-value").fill("74.625")
                                    page.locator("#health-note").fill(later_note)
                                    with page.expect_response(
                                        lambda r: (
                                            r.url.endswith("/api/health")
                                            and r.request.method == "POST"
                                        )
                                    ) as later_response:
                                        page.locator("#health-create").press("Enter")
                                    assert later_response.value.json() == {
                                        "queued": True,
                                        "offline": True,
                                    }
                                    expect(page.locator("#sync-indicator")).to_contain_text(
                                        "2 pending"
                                    )
                                    original = queue()
                                    assert len(original) == 2 and not saved(later_note)
                                record["queued_input"] = original
                                page.screenshot(path=str(dest / "01-queued.png"), full_page=True)
                                if auth:
                                    stop_process(server, process_group=False)
                                    server = start()
                                    assert inspector.post(
                                        "/api/auth/login", data={"password": password}
                                    ).ok
                                    state["expired"] = True
                                worker.evaluate(
                                    """status => {
                                  self.__replayAudit = [];
                                  self.__originalFetch = self.fetch;
                                  self.fetch = async function(input, options) {
                                    const url = typeof input === 'string' ? input : input.url;
                                    const method = options?.method || input.method || 'GET';
                                    if (new URL(url, self.location.origin).pathname === '/api/health' && method === 'POST') {
                                      const response = status ? new Response(JSON.stringify({detail: 'explicitly simulated rejected replay'}), {status,headers:{'content-type':'application/json'}}) : await self.__originalFetch.call(this,input,options);
                                      self.__replayAudit.push({status:response.status,simulated:!!status,body:options?.body || null});
                                      return response;
                                    }
                                    return self.__originalFetch.call(this,input,options);
                                  };
                                }""",
                                    0 if auth else code,
                                )
                                context.set_offline(False)
                                state["offline"] = False
                                until(lambda: bool(queue()[0].get("response_status")))
                                rejected = queue()
                                assert (
                                    len(rejected) == len(original)
                                    and rejected[0]["body"] == original[0]["body"]
                                )
                                assert rejected[0]["response_status"] == code
                                assert not saved()
                                expect(page.locator("#sync-indicator")).to_contain_text(
                                    "sign in needed"
                                    if auth
                                    else "pending"
                                    if code == 503
                                    else "needs attention"
                                )
                                record["rejected_input"] = rejected
                                record["replay_after_rejection"] = worker.evaluate(
                                    "()=>self.__replayAudit"
                                )
                                page.screenshot(
                                    path=str(dest / "02-retained-error.png"), full_page=True
                                )
                                if auth:
                                    dialog = review()
                                    dialog.get_by_label("Alles password", exact=True).fill(
                                        "wrong-synthetic-password"
                                    )
                                    dialog.get_by_role(
                                        "button", name="sign in & retry", exact=True
                                    ).click()
                                    expect(dialog.get_by_role("status")).to_contain_text(
                                        "wrong password"
                                    )
                                    assert queue()[0]["body"] == original[0]["body"] and not saved()
                                    page.screenshot(
                                        path=str(dest / "03-wrong-password.png"), full_page=True
                                    )
                                    dialog.press("Escape")
                                    expect(dialog).to_have_count(0)
                                    expect(page.locator("#sync-indicator button")).to_be_focused()
                                    if mode.endswith("reload"):
                                        page.reload(wait_until="networkidle")
                                        assert queue()[0]["body"] == original[0]["body"]
                                        login_ui()
                                        state["expired"] = False
                                    else:
                                        dialog = review()
                                        dialog.get_by_label("Alles password", exact=True).fill(
                                            password
                                        )
                                        dialog.get_by_label("Alles password", exact=True).press(
                                            "Enter"
                                        )
                                        until(lambda: not queue() and len(saved()) == 1)
                                        expect(dialog.get_by_role("status")).to_contain_text(
                                            "all changes have been sent"
                                        )
                                        dialog.get_by_role(
                                            "button", name="close", exact=True
                                        ).click()
                                        state["expired"] = False
                                        expect(page.locator("#app-drawer-btn")).to_be_focused()
                                else:
                                    page.reload(wait_until="networkidle")
                                    assert queue()[0]["body"] == original[0]["body"] and not saved()
                                    if code != 503:
                                        assert len(worker.evaluate("()=>self.__replayAudit")) == 1
                                    dialog = review()
                                    if ordered:
                                        later_row = dialog.locator(
                                            f'[data-outbox-id="{original[1]["id"]}"]'
                                        )
                                        expect(later_row).to_contain_text(
                                            "resolve the earlier offline change before retrying this one."
                                        )
                                        expect(
                                            later_row.get_by_role(
                                                "button", name="retry saved change", exact=True
                                            )
                                        ).to_be_disabled()
                                        # Retrying the first row while it still conflicts must keep the later action disabled.
                                        dialog.get_by_role(
                                            "button", name="retry saved change", exact=True
                                        ).first.click()
                                        until(
                                            lambda: (
                                                len(worker.evaluate("()=>self.__replayAudit")) == 2
                                            )
                                        )
                                        expect(
                                            later_row.get_by_role(
                                                "button", name="retry saved change", exact=True
                                            )
                                        ).to_be_disabled()
                                        assert (
                                            len(queue()) == 2
                                            and not saved()
                                            and not saved(later_note)
                                        )
                                        assert all(
                                            json.loads(x["body"])["note"] == note
                                            for x in worker.evaluate("()=>self.__replayAudit")
                                        )
                                        record["later_retry_blocked"] = True
                                    with page.expect_download() as download:
                                        dialog.get_by_role(
                                            "button", name="save a copy", exact=True
                                        ).first.click()
                                    path = download.value.path()
                                    exported = json.loads(Path(path).read_text())
                                    assert exported["body"] == original[0]["body"]
                                    record["downloaded_copy"] = exported
                                    page.screenshot(
                                        path=str(dest / "03-review.png"), full_page=True
                                    )
                                    if code in (409, 422):
                                        dialog.get_by_role(
                                            "button", name="discard", exact=True
                                        ).click()
                                        confirmation = page.get_by_role("alertdialog")
                                        expect(confirmation).to_be_visible()
                                        confirmation.press("Escape")
                                        expect(confirmation).to_have_count(0)
                                        expect(dialog).to_be_visible()
                                        expect(
                                            dialog.get_by_role("button", name="discard", exact=True)
                                        ).to_be_focused()
                                        assert queue()[0]["body"] == original[0]["body"]
                                    worker.evaluate("()=>{self.fetch=self.__originalFetch}")
                                    if code == 422:
                                        dialog.get_by_role(
                                            "button", name="discard", exact=True
                                        ).click()
                                        page.get_by_role("alertdialog").get_by_role(
                                            "button", name="confirm", exact=True
                                        ).click()
                                        until(lambda: not queue())
                                        assert not saved()
                                        expect(dialog.get_by_role("status")).to_contain_text(
                                            "all changes have been sent or discarded"
                                        )
                                        dialog.get_by_role(
                                            "button", name="close", exact=True
                                        ).click()
                                        expect(page.locator("#app-drawer-btn")).to_be_focused()
                                        page.locator("#health-add-toggle").click()
                                        page.locator("#health-value").fill("73.9")
                                        page.locator("#health-note").fill(note)
                                        page.locator("#health-create").press("Enter")
                                    else:
                                        dialog.get_by_role(
                                            "button", name="retry saved change", exact=True
                                        ).first.click()
                                        if ordered:
                                            until(lambda: len(queue()) == 1 and len(saved()) == 1)
                                            assert not saved(later_note)
                                            expect(
                                                later_row.get_by_role(
                                                    "button", name="retry saved change", exact=True
                                                )
                                            ).to_be_enabled()
                                            later_row.get_by_role(
                                                "button", name="retry saved change", exact=True
                                            ).click()
                                            until(
                                                lambda: not queue() and len(saved(later_note)) == 1
                                            )
                                            later = saved(later_note)[0]
                                            assert (
                                                later["value"] == 74.625
                                                and saved()[0]["id"] < later["id"]
                                            )
                                            record["persisted_order"] = [saved()[0], later]
                                        until(lambda: not queue() and len(saved()) == 1)
                                        expect(dialog.get_by_role("status")).to_contain_text(
                                            "all changes have been sent"
                                        )
                                        dialog.get_by_role(
                                            "button", name="close", exact=True
                                        ).click()
                                        expect(page.locator("#app-drawer-btn")).to_be_focused()
                                until(lambda: not queue() and len(saved()) == 1)
                                entries = saved()
                                assert entries[0]["value"] == (73.9 if code == 422 else 73.875)
                                expect(page.locator("#sync-indicator")).to_be_hidden()
                                page.goto(base + "/?view=health-log", wait_until="networkidle")
                                expect(
                                    page.locator(".health-row").filter(has_text=note)
                                ).to_be_visible()
                                assert len(saved()) == 1 and queue() == []
                                if ordered:
                                    expect(
                                        page.locator(".health-row").filter(has_text=later_note)
                                    ).to_be_visible()
                                    assert len(saved(later_note)) == 1
                                page.screenshot(path=str(dest / "04-persisted.png"), full_page=True)
                                record["saved_entry"] = entries[0]
                                assert not events["page_errors"], events
                                assert all(
                                    x["offline"]
                                    and x["method"] == "GET"
                                    and urlparse(x["url"]).path
                                    in {"/api/health", "/api/health/overview", "/api/reminders/due"}
                                    and x["failure"] == "net::ERR_INTERNET_DISCONNECTED"
                                    for x in events["failed_requests"]
                                ), events
                                assert all(
                                    x["status"] == 401
                                    and (
                                        (
                                            x["method"] == "POST"
                                            and urlparse(x["url"]).path == "/api/auth/login"
                                        )
                                        or (
                                            x["expired"]
                                            and x["method"] == "GET"
                                            and urlparse(x["url"]).path == "/api/reminders/due"
                                        )
                                    )
                                    for x in events["http_errors"]
                                ), events
                                errors = [x for x in events["console"] if x["type"] == "error"]
                                assert len(errors) == len(events["failed_requests"]) + len(
                                    events["http_errors"]
                                ), events
                                record.update(
                                    status="passed",
                                    detail="two queued changes persisted once each in order; later retry stayed unavailable until predecessor resolved"
                                    if ordered
                                    else "rejected payload survived reload/recovery; visible feedback and exactly one saved entry verified",
                                )
                            except BaseException as error:
                                record["failure"] = repr(error)
                                page.screenshot(path=str(dest / "failure.png"), full_page=True)
                                raise
                            finally:
                                (dest / "observations.json").write_text(
                                    json.dumps(record, indent=2)
                                )
                                (dest / "events.json").write_text(json.dumps(events, indent=2))
                                (output / "scenarios.json").write_text(
                                    json.dumps(records, indent=2)
                                )
                                context.tracing.stop(path=str(dest / "trace.zip"))
                                context.close()
                    inspector.dispose()
                    browser.close()
            finally:
                if server is not None:
                    stop_process(server, process_group=False)
    assert not data.exists()
    (output / "owned-fixture.json").write_text(
        json.dumps(
            {
                "data_root": str(data),
                "data_removed": True,
                "server_stopped": server.poll() is not None,
                "run_id": run_id,
            },
            indent=2,
        )
    )
    print(json.dumps({"status": "passed", "scenarios": records}))


if __name__ == "__main__":

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    run()
