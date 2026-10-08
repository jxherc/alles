"""Manual account recovery with owned data; connection checks are explicitly stubbed."""

import json
import os
import sys
import traceback
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
cases = [
    "success",
    "create-reject",
    "create-lost",
    "create-reload",
    "create-reload-lost",
    "cancel-late",
    "double-create",
    "edit-tls",
    "local-email",
    "default-port",
    "invalid-port",
    "edit-reject",
    "newer-input",
    "late-save",
    "test-reject",
    "test-late",
    "delete-reject",
    "delete-lost",
    "delete-reload",
    "list-reject",
    "list-invalid",
    "storage-write",
    "storage-read",
    "storage-cleanup",
    "cancel-navigation",
    "keyboard",
    "edit-conflict",
    "edit-reload",
    "delete-conflict",
    "keep-before-late-edit",
]
if len(sys.argv) > 1:
    cases = [case for case in cases if case in sys.argv[1:]]
assert cases
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    assert api.post("/api/setup/dismiss").ok
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            for row in api.get("/api/mail/accounts").json():
                assert api.delete("/api/mail/accounts/" + row["id"]).ok
            account = seed_mail(api, base)
            if case == "local-email":
                response = api.patch(
                    "/api/mail/accounts/" + account["id"], data={"email": "fixture@localhost"}
                )
                assert response.ok
                account = response.json()
            if case in {"default-port", "invalid-port"}:
                response = api.patch(
                    "/api/mail/accounts/" + account["id"],
                    data={"imap_port": 0 if case == "default-port" else -1},
                )
                assert response.ok
                account = response.json()
            assert account["use_ssl"] is False
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            errors, console, writes, held = [], [], [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            page.on("dialog", lambda dialog: dialog.accept())
            result = {
                "scenario_id": "inbox.accounts." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)
            email = f"{case}-{width}@example.invalid"
            secret = "  dummy  "

            def open_accounts():
                page.get_by_role("button", name="mail settings", exact=True).click()
                page.get_by_role("button", name="accounts", exact=True).click()
                expect(page.locator("#mail-add-acct")).to_be_visible()

            def confirm():
                page.locator(".dialog-overlay").get_by_role(
                    "button", name="confirm", exact=True
                ).click()

            def fill():
                page.locator("#ma-email").fill(email)
                page.locator("#ma-imaph").fill("127.0.0.1")
                page.locator("#ma-imapp").fill("1")
                page.locator("#ma-smtph").fill("127.0.0.1")
                page.locator("#ma-smtpp").fill("1")
                page.locator("#ma-pass").fill(secret)

            def rows():
                return api.get("/api/mail/accounts").json()

            def intercept(route):
                method = route.request.method
                if method == "GET":
                    return route.continue_()
                body = route.request.post_data_json if method != "DELETE" else None
                writes.append({"method": method, "body": body, "url": route.request.url})
                first = len(writes) == 1
                if first and case in {
                    "create-reject",
                    "create-reload",
                    "cancel-late",
                    "edit-reject",
                    "edit-reload",
                    "delete-reject",
                    "delete-reload",
                    "keep-before-late-edit",
                }:
                    return route.fulfill(status=503, json={"detail": "owned rejected request"})
                response = route.fetch()
                if first and case in {"create-lost", "create-reload-lost", "delete-lost"}:
                    return route.fulfill(status=503, json={"detail": "owned lost response"})
                if first and case in {"double-create", "newer-input", "late-save"}:
                    held.append((route, response))
                    return
                route.fulfill(response=response)

            def test_response(route):
                if case == "test-reject":
                    route.fulfill(status=503, json={"detail": "owned connection unavailable"})
                elif case == "test-late":
                    held.append((route, None))
                else:
                    route.fulfill(json={"ok": True})

            try:
                page.route(
                    base + "/api/mail/oauth/status",
                    lambda route: route.fulfill(
                        json={
                            "configured": True,
                            "redirect_uri": base + "/api/mail/oauth/google/callback",
                        }
                    ),
                )
                page.route(base + "/api/mail/test/*", test_response)
                page.route(base + "/api/mail/accounts", intercept)
                page.route(base + "/api/mail/accounts/*", intercept)
                if case in {"default-port", "invalid-port"}:
                    page.route(
                        base + "/api/mail/inbox/*",
                        lambda route: route.fulfill(json={"messages": []}),
                    )
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                if case.startswith("list-"):

                    def bad_list(route):
                        route.fulfill(
                            status=503 if case == "list-reject" else 200,
                            json={"detail": "owned unavailable"}
                            if case == "list-reject"
                            else {"accounts": [], "recovery_scopes": []},
                        )

                    page.route(base + "/api/mail/accounts?context=true", bad_list)
                    page.get_by_role("button", name="mail settings", exact=True).click()
                    page.get_by_role("button", name="accounts", exact=True).click()
                    expect(page.locator("#mail-main").get_by_role("alert")).to_be_visible()
                    page.unroute(base + "/api/mail/accounts?context=true", bad_list)
                    page.locator("#mail-main").get_by_role(
                        "button", name="retry", exact=True
                    ).click()
                    expect(page.locator(".mail-acct-row")).to_have_count(1)
                else:
                    if case == "storage-read":
                        page.evaluate(
                            """() => { window.accountGet = Storage.prototype.getItem; Storage.prototype.getItem = function(k) { if (k.startsWith('alles-mail-account-pending:')) throw Error('owned read failure'); return window.accountGet.call(this,k); }; }"""
                        )
                    open_accounts()
                    recovery = page.locator("#ma-recovery-status")
                    if case == "storage-read":
                        expect(recovery).to_contain_text("could not read account recovery")
                        expect(page.locator("#mail-add-acct")).to_have_attribute(
                            "aria-disabled", "true"
                        )
                        page.evaluate("() => { Storage.prototype.getItem = window.accountGet; }")
                        page.get_by_role(
                            "button", name="retry reading account recovery", exact=True
                        ).click()
                        expect(page.locator("#mail-add-acct")).to_have_attribute(
                            "aria-disabled", "false"
                        )
                    elif case.startswith("delete-"):
                        if case == "delete-conflict":
                            assert api.patch(
                                "/api/mail/accounts/" + account["id"],
                                data={"name": "newer saved name"},
                            ).ok
                        page.locator(".mail-acct-del").click()
                        confirm()
                        expect(recovery).to_contain_text("removal unconfirmed")
                        if case == "delete-reload":
                            page.reload(wait_until="networkidle")
                            page.get_by_role("tab", name="mail", exact=True).click()
                            open_accounts()
                        if case == "delete-conflict":
                            page.get_by_role(
                                "button", name="review current settings", exact=True
                            ).click()
                            confirm()
                            expect(page.locator("#ma-name")).to_have_value("newer saved name")
                            assert len(rows()) == 1
                        else:
                            page.get_by_role("button", name="retry removal", exact=True).click()
                            expect(recovery).to_have_text("account removed")
                            assert rows() == []
                    else:
                        editing = case in {
                            "edit-tls",
                            "local-email",
                            "default-port",
                            "invalid-port",
                            "edit-reject",
                            "edit-conflict",
                            "edit-reload",
                            "keep-before-late-edit",
                        }
                        if editing:
                            page.locator(".mail-acct-edit").click()
                            page.locator("#ma-name").fill("updated label")
                            if case in {"default-port", "invalid-port"}:
                                expect(page.locator("#ma-imapp")).to_have_value(
                                    "143" if case == "default-port" else "-1"
                                )
                                if case == "invalid-port":
                                    page.locator("#ma-imapp").fill("1")
                        else:
                            page.locator("#mail-add-acct").click()
                            fill()
                        status = page.locator("#ma-status")
                        if case == "edit-conflict":
                            assert api.patch(
                                "/api/mail/accounts/" + account["id"],
                                data={"name": "newer saved name"},
                            ).ok
                        if case == "storage-write":
                            page.evaluate(
                                """() => { window.accountSet = Storage.prototype.setItem; Storage.prototype.setItem = function(k,v) { if (k.startsWith('alles-mail-account-pending:')) throw Error('owned write failure'); return window.accountSet.call(this,k,v); }; }"""
                            )
                        if case == "storage-cleanup":
                            page.evaluate(
                                """() => { window.accountRemove = Storage.prototype.removeItem; Storage.prototype.removeItem = function(k) { if (k.startsWith('alles-mail-account-pending:')) throw Error('owned cleanup failure'); return window.accountRemove.call(this,k); }; }"""
                            )
                        if case == "cancel-navigation":
                            page.locator("#ma-close").click()
                            page.locator(".dialog-overlay").get_by_role(
                                "button", name="cancel", exact=True
                            ).click()
                            expect(page.locator("#ma-pass")).to_have_value(secret)
                        if case == "keyboard":
                            page.locator("#ma-tls").focus()
                            page.keyboard.press("Space")
                            expect(page.locator("#ma-tls")).to_have_attribute(
                                "aria-pressed", "false"
                            )
                            page.locator("#ma-imapp").fill("70000")
                            page.locator("#ma-save").click()
                            expect(page.locator("#ma-imapp")).to_be_focused()
                            expect(status).to_contain_text("from 1 to 65535")
                            assert not writes
                            page.locator("#ma-imapp").fill("1")
                        page.locator("#ma-save").click()
                        if case in {"double-create", "newer-input", "late-save", "test-late"}:
                            for _ in range(200):
                                if held:
                                    break
                                page.wait_for_timeout(20)
                            assert held
                            if case == "double-create":
                                expect(page.locator("#ma-save")).to_have_attribute(
                                    "aria-disabled", "true"
                                )
                                box = page.locator("#ma-save").bounding_box()
                                page.mouse.click(
                                    box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                                )
                                assert len(writes) == 1
                                assert len([r for r in rows() if r["email"] == email]) == 1
                            elif case == "newer-input":
                                page.locator("#ma-name").fill("newer unsaved label")
                                page.locator("#ma-pass").fill("example")
                            else:
                                page.locator("#mail-compose-btn").click()
                                page.locator("#mc-subj").fill("keep new composer")
                            route, response = held.pop()
                            route.fulfill(response=response) if response else route.fulfill(
                                json={"ok": True}
                            )
                            if case in {"late-save", "test-late"}:
                                page.wait_for_timeout(100)
                                expect(page.locator("#mc-subj")).to_have_value("keep new composer")
                            elif case == "newer-input":
                                expect(status).to_contain_text("newer changes are unsaved")
                                expect(page.locator("#ma-pass")).to_have_value("example")
                                expect(page.locator("#ma-name")).to_have_value(
                                    "newer unsaved label"
                                )
                                page.locator("#ma-save").click()
                                expect(status).to_have_text(
                                    "account saved; incoming mail connected"
                                )
                                saved = [r for r in rows() if r["email"] == email]
                                assert len(saved) == 1 and saved[0]["name"] == "newer unsaved label"
                        elif case == "storage-write":
                            expect(recovery).to_contain_text("could not retain account recovery")
                            assert not writes
                            expect(page.locator("#ma-pass")).to_have_value(secret)
                            page.evaluate(
                                "() => { Storage.prototype.setItem = window.accountSet; }"
                            )
                            page.get_by_role(
                                "button", name="retry reading account recovery", exact=True
                            ).click()
                            page.locator("#ma-save").click()
                            expect(status).to_have_text("account saved; incoming mail connected")
                        elif case == "storage-cleanup":
                            expect(recovery).to_contain_text("recovery data could not be cleared")
                            assert len(writes) == 1
                            page.evaluate(
                                "() => { Storage.prototype.removeItem = window.accountRemove; }"
                            )
                            page.get_by_role(
                                "button", name="retry account recovery cleanup", exact=True
                            ).click()
                            expect(recovery).to_have_text("account recovery cleared")
                            assert len(writes) == 1
                        elif case in {
                            "create-reject",
                            "create-lost",
                            "create-reload",
                            "create-reload-lost",
                            "cancel-late",
                            "edit-reject",
                            "edit-reload",
                            "edit-conflict",
                            "keep-before-late-edit",
                        }:
                            expect(recovery).to_contain_text("save unconfirmed")
                            expect(page.locator("#ma-pass")).to_have_value(
                                "" if editing else secret
                            )
                            storage = page.evaluate(
                                "() => Object.fromEntries(Object.entries(sessionStorage))"
                            )
                            recovery_storage = {
                                k: v
                                for k, v in storage.items()
                                if k.startswith("alles-mail-account-pending:")
                            }
                            assert len(recovery_storage) == 1
                            metadata = json.loads(next(iter(recovery_storage.values())))
                            assert set(metadata) <= {
                                "kind",
                                "id",
                                "label",
                                "recovery_scope",
                                "expected_revision",
                            }
                            if "reload" in case:
                                page.reload(wait_until="networkidle")
                                page.get_by_role("tab", name="mail", exact=True).click()
                                open_accounts()
                            if case in {"create-reload", "cancel-late"}:
                                old = writes[0]["body"]
                                page.get_by_role(
                                    "button", name="remove pending account", exact=True
                                ).click()
                                confirm()
                                expect(recovery).to_have_text("account removed")
                                assert api.post("/api/mail/accounts", data=old).status == 410
                                assert not [r for r in rows() if r["email"] == email]
                            elif case == "create-reload-lost":
                                page.get_by_role(
                                    "button", name="review saved account", exact=True
                                ).click()
                                expect(page.locator("#ma-email")).to_have_value(email)
                                expect(page.locator("#ma-pass")).to_have_value("")
                                assert len([r for r in rows() if r["email"] == email]) == 1
                            elif case in {"edit-conflict", "edit-reload", "keep-before-late-edit"}:
                                old = writes[0]["body"]
                                page.get_by_role(
                                    "button", name="review current settings", exact=True
                                ).click()
                                confirm()
                                expect(page.locator("#ma-save")).to_have_attribute(
                                    "aria-disabled", "false"
                                )
                                expect(page.locator("#ma-name")).to_have_value(
                                    "newer saved name"
                                    if case == "edit-conflict"
                                    else account["name"]
                                )
                                assert (
                                    api.patch(
                                        "/api/mail/accounts/" + account["id"], data=old
                                    ).status
                                    == 409
                                )
                            else:
                                page.get_by_role(
                                    "button", name="retry saved changes", exact=True
                                ).click()
                                expect(recovery).to_have_text("")
                                expect(status).to_have_text("account saved")
                                assert writes[0]["body"] == writes[1]["body"]
                                assert (
                                    len(
                                        [
                                            r
                                            for r in rows()
                                            if r["email"]
                                            == (account["email"] if editing else email)
                                        ]
                                    )
                                    == 1
                                )
                        elif case == "test-reject":
                            expect(status).to_contain_text(
                                "account saved, but connection unconfirmed"
                            )
                            assert len([r for r in rows() if r["email"] == email]) == 1
                            page.unroute(base + "/api/mail/test/*", test_response)
                            page.route(
                                base + "/api/mail/test/*",
                                lambda route: route.fulfill(json={"ok": True}),
                            )
                            page.locator("#ma-test").click()
                            expect(status).to_have_text("account saved; incoming mail connected")
                            assert len(writes) == 1
                        else:
                            expect(status).to_have_text("account saved; incoming mail connected")
                            if case in {"edit-tls", "local-email", "default-port", "invalid-port"}:
                                saved = next(r for r in rows() if r["id"] == account["id"])
                                assert (
                                    saved["use_ssl"] is False and saved["name"] == "updated label"
                                )
                                if case in {"default-port", "invalid-port"}:
                                    assert saved["imap_port"] == (
                                        143 if case == "default-port" else 1
                                    )
                            elif case == "keyboard":
                                assert (
                                    next(r for r in rows() if r["email"] == email)["use_ssl"]
                                    is False
                                )
                assert not errors, errors
                assert not [
                    line
                    for line in console
                    if line
                    not in {
                        "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
                        "Failed to load resource: the server responded with a status of 409 (Conflict)",
                    }
                ], console
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                result.update(
                    status="passed", page_errors=errors, console=console, writes=len(writes)
                )
            except Exception as error:
                result.update(
                    error=str(error),
                    traceback=traceback.format_exc(),
                    page_errors=errors,
                    console=console,
                    writes=len(writes),
                )
            finally:
                for route, response in held:
                    route.fulfill(response=response) if response else route.fulfill(
                        json={"ok": True}
                    )
                if page.locator("#ma-status").count():
                    page.locator("#ma-status").scroll_into_view_if_needed()
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
