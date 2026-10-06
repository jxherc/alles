"""Ordinary Vault async type, focus and confirmation regressions.

Run against an owned disposable server with PORT, ALLES_DATA, ALLES_TEST_DATA,
ALLES_TEST_RUN_ID and ALLES_BROWSER_ARTIFACTS set by its launcher.
The served Vault source must match this working tree; no product JS is replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(profile, expected_source=None, case_group="all"):
    source = ROOT / "static/js/vault.js"
    expected_source = expected_source or sha(source)
    assert sha(source) == expected_source, "working Vault bytes do not match the expected source"
    base = f"http://127.0.0.1:{int(os.environ['PORT'])}"
    origin = urlsplit(base)
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert (data / ".alles-test-owner").read_text() == os.environ["ALLES_TEST_RUN_ID"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    results = []
    cases = [
        ("type", method, mode) for method in ("POST", "PATCH") for mode in ("pointer", "keyboard")
    ]
    cases += [
        ("focus", method, target)
        for method in ("POST", "PATCH", "lookup")
        for target in ("cancel", "close", "initiator")
    ]
    cases += [("newer-form", method, "password") for method in ("POST", "PATCH", "lookup")]
    cases += [("confirmation", "lookup", action) for action in ("escape", "cancel")]
    if case_group == "original":
        cases = [case for case in cases if case[0] != "confirmation"]
    elif case_group == "confirmation":
        cases = [case for case in cases if case[0] == "confirmation"]

    with sync_playwright() as pw:
        api = pw.request.new_context(base_url=base)

        readback_count = 0

        def request(method, path, **kwargs):
            nonlocal readback_count
            assert path.startswith("/api/") or path == "/static/js/vault.js"
            assert not path.startswith("//") and "://" not in path
            response = api.fetch(path, method=method, max_redirects=0, timeout=10000, **kwargs)
            if method == "GET" and path.startswith("/api/vault"):
                readback_count += 1
                payload = response.body()
                capture = output / f"api-readback-{readback_count:04d}.json"
                capture.write_bytes(payload)
                receipt = {
                    "sequence": readback_count,
                    "path": path,
                    "method": method,
                    "status": response.status,
                    "file": capture.name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                with (output / "api-readbacks.jsonl").open("a") as stream:
                    stream.write(json.dumps(receipt) + "\n")
            return response

        assert request("POST", "/api/setup/dismiss").ok
        master = str(uuid.uuid4())
        opened = request("POST", "/api/vault/unlock", data={"password": master})
        assert opened.ok
        headers = {"X-Vault-Token": opened.json()["token"]}
        served = request("GET", "/static/js/vault.js")
        assert served.ok and hashlib.sha256(served.body()).hexdigest() == expected_source
        browser = pw.chromium.launch()
        try:
            for kind, method, action in cases:
                name = "async fixture " + uuid.uuid4().hex
                secret = str(uuid.uuid4()).center(46)
                corrected = str(uuid.uuid4()).center(50)
                notes = (
                    "synthetic line one\r\nline two \r\n"
                    if method == "PATCH"
                    else "synthetic line one\nline two \n"
                )
                row = {
                    "scenario_id": f"vault.async.{kind}.{method}.{action}",
                    "profile": profile,
                    "feature_id": "passwords.vault-and-browser",
                    "source_sha256": expected_source,
                    "status": "failed",
                    "observations": {},
                }
                results.append(row)
                context = browser.new_context(
                    viewport={
                        "width": 390 if profile == "phone" else 1440,
                        "height": 844 if profile == "phone" else 900,
                    },
                    is_mobile=profile == "phone",
                    has_touch=profile == "phone",
                    reduced_motion="reduce",
                    service_workers="block",
                )
                denied, sockets, page_errors, console, http_errors, writes, failed_requests = (
                    [],
                    [],
                    [],
                    [],
                    [],
                    [],
                    [],
                )
                expected_http = Counter()

                def exact_origin(route):
                    target = urlsplit(route.request.url)
                    if (target.scheme, target.netloc) == (origin.scheme, origin.netloc):
                        route.continue_()
                    else:
                        denied.append({"scheme": target.scheme, "origin": target.netloc})
                        route.abort()

                def deny_socket(ws):
                    sockets.append(ws.url)
                    ws.close()

                held_routes = {}

                def dispatch(route):
                    hold = held_routes.get((route.request.url, route.request.method))
                    if hold is None:
                        exact_origin(route)
                    else:
                        hold.pending.append(route)

                context.route("**/*", dispatch)
                context.route_web_socket("**/*", deny_socket)
                page = context.new_page()
                page.set_default_timeout(6000)
                page.on("pageerror", lambda e: page_errors.append(str(e)))
                page.on(
                    "requestfailed",
                    lambda req: failed_requests.append({"url": req.url, "failure": req.failure}),
                )
                page.on(
                    "console",
                    lambda msg: (
                        console.append({"text": msg.text, "url": msg.location.get("url", "")})
                        if msg.type == "error"
                        else None
                    ),
                )
                page.on(
                    "response",
                    lambda response: (
                        http_errors.append((response.request.method, response.url, response.status))
                        if response.status >= 400
                        else None
                    ),
                )

                def observe(req):
                    if (req.method == "POST" and req.url == base + "/api/vault") or (
                        req.method == "PATCH"
                        and entry_id is not None
                        and req.url == base + f"/api/vault/{entry_id}"
                    ):
                        writes.append(
                            {"method": req.method, "url": req.url, "body": req.post_data_json}
                        )

                page.on("request", observe)
                holds = []

                class Hold:
                    def __init__(self, url, verb):
                        self.url, self.verb, self.pending, self.used = url, verb, [], False
                        held_routes[(url, verb)] = self
                        holds.append(self)

                    def wait(self):
                        deadline = time.monotonic() + 8
                        while not self.pending and time.monotonic() < deadline:
                            page.wait_for_timeout(20)
                        assert len(self.pending) == 1, "did not hold exactly one ordinary request"

                    def release(self, failure=False):
                        self.wait()
                        route = self.pending[0]
                        # Send the real owned API request, with redirects forbidden.
                        response = route.fetch(max_redirects=0, timeout=10000)
                        assert response.ok, f"owned API returned {response.status}"
                        row["observations"].setdefault("real_api_statuses", []).append(
                            {"method": self.verb, "status": response.status}
                        )
                        if failure:
                            expected_http[(self.verb, self.url, 503)] += 1
                            route.fulfill(
                                status=503,
                                content_type="application/json",
                                body='{"detail":"synthetic unavailable"}',
                            )
                        else:
                            route.fulfill(response=response)
                        self.used = True
                        held_routes.pop((self.url, self.verb), None)

                    def dispose(self):
                        if not self.used:
                            for route in self.pending:
                                try:
                                    route.abort()
                                except Exception:
                                    pass
                        held_routes.pop((self.url, self.verb), None)

                def rows():
                    response = request("GET", "/api/vault", headers=headers)
                    assert response.ok
                    return [entry for entry in response.json() if entry["name"] == name]

                def saved():
                    entries = rows()
                    assert len(entries) == 1, f"expected one fixture entry, found {len(entries)}"
                    response = request(
                        "GET", f"/api/vault/{entries[0]['id']}/reveal", headers=headers
                    )
                    assert response.ok
                    return response.json()

                def key(locator):
                    expect(locator).to_be_enabled()
                    locator.focus()
                    page.keyboard.press("Enter")

                def fill_new(new_name=name, value=secret):
                    page.locator("#vault-new-btn").click()
                    expect(page.locator("#vf-name")).to_be_focused()
                    page.locator("#vf-name").fill(new_name)
                    page.locator("#vf-f-username").fill(" fixture ")
                    page.locator("#vf-f-password").fill(value)
                    page.locator("#vf-f-notes").fill(notes)

                def close_form(uncertain):
                    key(page.locator("#vf-cancel"))
                    if uncertain:
                        expect(page.locator(".dialog-overlay")).to_contain_text(
                            "may already be saved"
                        )
                        page.locator(".dialog-overlay [data-dialog-confirm]").click()
                    expect(page.locator("#vf-name")).to_have_count(0)

                def attempt_type(mode):
                    combo = page.locator("#vf-type")
                    disabled = combo.get_attribute("aria-disabled") == "true"
                    if mode == "pointer":
                        box = combo.bounding_box()
                        assert box
                        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        if combo.get_attribute("aria-expanded") == "true":
                            page.get_by_role("option", name="API key", exact=True).click()
                    else:
                        # Actual Tab/arrow/Enter navigation; never force focus on a disabled div.
                        page.locator("#vf-x").focus()
                        for _ in range(12):
                            page.keyboard.press("Tab")
                            active = page.evaluate("document.activeElement?.id")
                            if active == "vf-type":
                                page.keyboard.press("ArrowDown")
                                page.keyboard.press("Enter")
                                break
                            if active == "vf-x":
                                break
                    value = combo.get_attribute("data-value")
                    marker = "newer synthetic value " + uuid.uuid4().hex
                    field = page.locator("#vf-f-apikey")
                    entered = bool(value == "apikey" and field.count() and field.is_enabled())
                    if entered:
                        field.fill(marker)
                    return disabled, value, entered, marker

                try:
                    entry_id = None
                    if method == "PATCH":
                        created = request(
                            "POST",
                            "/api/vault",
                            headers=headers,
                            data={
                                "name": name,
                                "type": "login",
                                "username": " fixture ",
                                "fields": {"password": secret, "notes": notes},
                            },
                        )
                        assert created.ok
                        entry_id = created.json()["id"]
                    page.goto(base + "/?view=vault", wait_until="networkidle")
                    page.locator("#vault-pw-input").fill(master)
                    page.locator("#vault-unlock-btn").click()
                    expect(page.locator("#vault-new-btn")).to_be_visible()
                    if method == "PATCH":
                        page.locator(f'[data-vault-open="{entry_id}"]').click()
                        expect(page.locator("#vf-f-password")).to_have_value(secret)
                        page.locator("#vf-f-username").fill(" updated fixture ")
                        endpoint = base + f"/api/vault/{entry_id}"
                    else:
                        fill_new()
                        endpoint = base + "/api/vault"

                    if method == "lookup":
                        lost = Hold(endpoint, "POST")
                        key(page.locator("#vf-save"))
                        lost.release(failure=True)
                        expect(page.locator("#vf-error")).to_contain_text("save failed (503)")
                        page.locator("#vf-f-password").fill(corrected)
                        expected_http[("POST", endpoint, 409)] += 1
                        key(page.locator("#vf-save"))
                        expect(page.locator("#vf-error")).to_contain_text(
                            "already saved with different values"
                        )
                        assert writes[0]["body"]["request_id"] == writes[1]["body"]["request_id"]
                        endpoint = base + "/api/vault/requests/" + writes[0]["body"]["request_id"]
                        held = Hold(endpoint, "GET")
                        initiator = "vf-open-saved"
                    else:
                        held = Hold(endpoint, method)
                        initiator = "vf-save"
                    key(page.locator("#" + initiator))
                    held.wait()
                    expect(page.locator("#" + initiator)).to_be_disabled()

                    if kind == "confirmation":
                        row["observations"]["focus_before_release"] = page.evaluate(
                            "document.activeElement?.id || document.activeElement?.tagName"
                        )
                        held.release()
                        dialog = page.locator(".dialog-overlay")
                        expect(dialog).to_contain_text(
                            "discard this draft and open the saved entry?"
                        )
                        expect(dialog.locator("[data-dialog-cancel]")).to_be_focused()
                        row["observations"]["confirmation_cancel_initially_focused"] = True
                        page.screenshot(path=str(output / f"{row['scenario_id']}-confirmation.png"))
                        if action == "escape":
                            page.keyboard.press("Escape")
                        else:
                            dialog.locator("[data-dialog-cancel]").click()
                        expect(dialog).to_have_count(0)
                        expect(page.locator("#vf-open-saved")).to_be_enabled()
                        row["observations"].update(
                            dismissal=action,
                            focus_after_dismissal=page.evaluate(
                                "document.activeElement?.id || document.activeElement?.tagName"
                            ),
                        )
                        expect(page.locator("#vf-name")).to_have_value(name)
                        expect(page.locator("#vf-f-username")).to_have_value(" fixture ")
                        expect(page.locator("#vf-f-password")).to_have_value(corrected)
                        expect(page.locator("#vf-f-notes")).to_have_value(notes)
                        expect(page.locator("#vf-type")).to_have_attribute("data-value", "login")
                        expect(page.locator("#vf-save")).to_be_enabled()
                        expect(page.locator("#vf-open-saved")).to_be_focused()
                        assert len(writes) == 2, (
                            "dismissing the owned confirmation issued an extra entry write"
                        )
                        persisted = saved()
                        assert persisted["fields"]["password"] == secret
                        assert persisted["fields"]["notes"] == notes
                        row["observations"].update(
                            draft_fields_retained=True,
                            open_saved_enabled_and_focused=True,
                            original_saved_fields_retained=True,
                            entry_write_count=len(writes),
                        )
                    elif kind == "type":
                        disabled, changed_type, entered, marker = attempt_type(action)
                        row["observations"].update(
                            type_disabled_while_pending=disabled,
                            selected_type_while_pending=changed_type,
                            newer_field_edit_entered=entered,
                        )
                        page.screenshot(path=str(output / f"{row['scenario_id']}-pending.png"))
                        held.release()
                        expect(page.locator("#vf-name")).to_have_count(0)
                        persisted = saved()
                        loss = (
                            entered
                            and persisted["type"] == "login"
                            and persisted["fields"].get("apikey") != marker
                        )
                        row["observations"].update(
                            saved_original_type=persisted["type"] == "login",
                            newer_edit_lost_after_success=loss,
                            modal_closed_after_success=True,
                        )
                        row["observations"].update(
                            exact_password_bytes_preserved=persisted["fields"]["password"]
                            == secret,
                            exact_note_bytes_preserved=persisted["fields"]["notes"] == notes,
                        )
                        assert persisted["fields"]["password"] == secret
                        assert persisted["fields"]["notes"] == notes
                        # Delay these assertions until the real save outcome is recorded.
                        assert disabled and changed_type == "login" and not entered and not loss, (
                            "pending type control accepted newer edits; see bounded observations"
                        )
                    elif kind == "focus":
                        target = {"cancel": "vf-cancel", "close": "vf-x", "initiator": initiator}[
                            action
                        ]
                        if action != "initiator":
                            page.locator("#" + target).focus()
                            expect(page.locator("#" + target)).to_be_focused()
                        row["observations"]["focus_before_release"] = page.evaluate(
                            "document.activeElement?.id || document.activeElement?.tagName"
                        )
                        held.release(failure=True)
                        expect(page.locator("#vf-error")).to_contain_text("your input is kept")
                        expect(page.locator("#" + initiator)).to_be_enabled()
                        active = page.evaluate("document.activeElement?.id")
                        row["observations"].update(
                            expected_focus=target,
                            focus_after_failure=active,
                            newer_focus_taken=action != "initiator" and active != target,
                        )
                        expect(page.locator("#vf-f-password")).to_have_value(
                            corrected if method == "lookup" else secret
                        )
                        expect(page.locator("#vf-type")).to_be_enabled()
                        assert active == target, "late recovery took the selected focus target"
                        if action != "initiator":
                            # Enter must activate the chosen cancellation control, not a retry.
                            page.keyboard.press("Enter")
                            if method in {"POST", "lookup"}:
                                expect(page.locator(".dialog-overlay")).to_contain_text(
                                    "may already be saved"
                                )
                                page.locator(".dialog-overlay [data-dialog-confirm]").click()
                            expect(page.locator("#vf-name")).to_have_count(0)
                        elif method == "lookup":
                            key(page.locator("#vf-open-saved"))
                            expect(page.locator(".dialog-overlay")).to_contain_text(
                                "discard this draft"
                            )
                            page.locator(".dialog-overlay [data-dialog-confirm]").click()
                            expect(page.locator("#vf-f-password")).to_have_value(secret)
                            close_form(False)
                        else:
                            key(page.locator("#vf-save"))
                            expect(page.locator("#vf-name")).to_have_count(0)
                            if method == "POST":
                                assert writes[0]["body"] == writes[1]["body"], (
                                    "retry changed the ordinary request identity/payload"
                                )
                        persisted = saved()
                        row["observations"].update(
                            exact_password_bytes_preserved=persisted["fields"]["password"]
                            == secret,
                            exact_note_bytes_preserved=persisted["fields"]["notes"] == notes,
                        )
                        assert persisted["fields"]["password"] == secret
                        assert persisted["fields"]["notes"] == notes
                    else:
                        close_form(method != "PATCH")
                        newer_name = name + " newer draft"
                        fill_new(newer_name, corrected)
                        page.locator("#vf-f-password").focus()
                        held.release(failure=True)
                        page.wait_for_load_state("networkidle")
                        expect(page.locator("#vf-name")).to_have_value(newer_name)
                        expect(page.locator("#vf-f-password")).to_have_value(corrected)
                        expect(page.locator("#vf-f-password")).to_be_focused()
                        row["observations"]["newer_form_and_focus_retained"] = True
                        close_form(False)
                        assert saved()["fields"]["password"] == secret
                    row["status"] = "passed"
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    for hold in holds:
                        hold.dispose()
                    try:
                        page.wait_for_load_state("networkidle")
                    except Exception as exc:
                        row["status"] = "failed"
                        row["settling_error"] = type(exc).__name__
                    actual_http = Counter(http_errors)
                    allowed_console = Counter(
                        (url, status) for method_, url, status in expected_http.elements()
                    )
                    seen_console = Counter()
                    unexpected_console = []
                    for message in console:
                        match = re.search(
                            r"Failed to load resource: the server responded with a status of (\d+)",
                            message["text"],
                        )
                        key_ = (message["url"], int(match.group(1))) if match else None
                        if key_ is None:
                            unexpected_console.append(message)
                        else:
                            seen_console[key_] += 1
                            if seen_console[key_] > allowed_console[key_]:
                                unexpected_console.append(message)
                    row["events"] = {
                        "page_errors": page_errors,
                        "http_errors": http_errors,
                        "expected_http": [[*key_, count] for key_, count in expected_http.items()],
                        "console_errors": console,
                        "unexpected_console": unexpected_console,
                        "denied_origins": denied,
                        "closed_websockets": sockets,
                        "failed_requests": failed_requests,
                    }
                    if (
                        page_errors
                        or denied
                        or failed_requests
                        or unexpected_console
                        or actual_http != expected_http
                    ):
                        row["status"] = "failed"
                        row["event_mismatch"] = True
                    try:
                        page.screenshot(path=str(output / f"{row['scenario_id']}-result.png"))
                    except Exception as exc:
                        row["screenshot_error"] = type(exc).__name__
                    context.close()
                    for entry in rows():
                        response = request("DELETE", f"/api/vault/{entry['id']}", headers=headers)
                        assert response.ok
                    (output / "scenarios.json").write_text(json.dumps(results, indent=2) + "\n")
            assert sha(source) == expected_source, "Vault changed during the adapter"
        finally:
            browser.close()
            api.dispose()
    print(
        json.dumps(
            {
                "profile": profile,
                "case_group": case_group,
                "scenarios": len(results),
                "failed": sum(row["status"] != "passed" for row in results),
            }
        )
    )
    return int(any(row["status"] != "passed" for row in results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("desktop", "phone"), required=True)
    parser.add_argument("--source-sha256", help="optional expected working-tree Vault SHA-256")
    parser.add_argument("--case-group", choices=("all", "original", "confirmation"), default="all")
    args = parser.parse_args()
    raise SystemExit(run(args.profile, args.source_sha256, args.case_group))
