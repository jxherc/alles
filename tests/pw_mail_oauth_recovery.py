"""Google setup recovery with disposable keys; never starts provider authorization."""

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
    "save-reject",
    "save-lost",
    "newer-input",
    "double-save",
    "status-reject",
    "status-invalid",
    "blank-redirect",
    "reload-reject",
    "reload-lost",
    "keep-late",
    "partial-id",
    "partial-secret",
    "legacy-redirect",
    "legacy-text",
    "keep-conflict",
    "retained-secret-race",
    "keep-newer",
    "storage-write",
    "storage-read",
    "storage-cleanup",
    "cancel-navigation",
    "late-close",
    "keep-secret",
    "keyboard",
    "normalization",
    "reopen-retry",
    "reopen-before-edit",
    "reopen-during-edit",
    "keep-retry",
    "keep-before-edit",
    "keep-during-edit",
]
if len(sys.argv) > 1:
    cases = [c for c in cases if c in sys.argv[1:]]
assert cases
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    assert api.post("/api/setup/dismiss").ok
    seed_mail(api, base)
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            configured = case in [
                "blank-redirect",
                "keep-secret",
                "legacy-redirect",
                "legacy-text",
                "retained-secret-race",
                "normalization",
            ]
            assert api.patch(
                "/api/settings",
                data={
                    "mail_oauth_client_id": "saved-client"
                    if configured or case == "partial-id"
                    else "",
                    "mail_oauth_client_secret": "dummy"
                    if configured or case == "partial-secret"
                    else "",
                    "mail_oauth_redirect_base": "https://mail.example.invalid"
                    if configured
                    else "",
                },
            ).ok
            if case in ["legacy-redirect", "legacy-text"]:
                assert api.patch(
                    "/api/settings",
                    data={
                        "mail_oauth_client_id": " saved-client "
                        if case == "legacy-text"
                        else "saved-client",
                        "mail_oauth_redirect_base": "https://example.invalid/base/"
                        if case == "legacy-text"
                        else "http:/example.invalid",
                    },
                ).ok
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(6500)
            held = []
            writes = []
            errors = []
            console = []
            status_reads = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            page.on("dialog", lambda d: d.accept())
            result = {
                "scenario_id": "inbox.oauth." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)

            def status():
                return api.get("/api/mail/oauth/status").json()

            def read(route):
                status_reads.append(True)
                if len(status_reads) == 1 and case in ["status-reject", "status-invalid"]:
                    return route.fulfill(
                        status=503 if case == "status-reject" else 200,
                        json={"detail": "owned status unavailable"}
                        if case == "status-reject"
                        else {"configured": False},
                    )
                route.continue_()

            def save(route):
                writes.append(route.request.post_data_json)
                if len(writes) == 1 and case in [
                    "keep-retry",
                    "keep-before-edit",
                    "keep-during-edit",
                    "reopen-retry",
                    "reopen-before-edit",
                    "reopen-during-edit",
                    "save-reject",
                    "reload-reject",
                    "keep-late",
                    "partial-id",
                    "partial-secret",
                    "legacy-redirect",
                    "legacy-text",
                    "keep-conflict",
                    "retained-secret-race",
                    "keep-newer",
                ]:
                    return route.fulfill(status=503, json={"detail": "owned save unavailable"})
                if len(writes) == 2 and case == "keep-conflict":
                    assert api.patch(
                        "/api/settings",
                        data={
                            "mail_oauth_client_id": "other-client",
                            "mail_oauth_client_secret": "example",
                        },
                    ).ok
                if len(writes) == 2 and case == "retained-secret-race":
                    assert api.post("/api/mail/oauth/config", data=writes[0]).ok
                if len(writes) == 2 and case in [
                    "keep-retry",
                    "keep-before-edit",
                    "keep-during-edit",
                ]:
                    return route.fulfill(status=503, json={"detail": "owned keep unavailable"})
                response = route.fetch()
                if len(writes) == 1 and case in ["save-lost", "reload-lost"]:
                    return route.fulfill(status=503, json={"detail": "owned lost reply"})
                if (len(writes) == 1 and case in ["newer-input", "double-save", "late-close"]) or (
                    len(writes) == 2 and case in ["keep-newer", "reopen-during-edit"]
                ):
                    held.append((route, response))
                    return
                if len(writes) == 3 and case == "keep-during-edit":
                    held.append((route, response))
                    return
                route.fulfill(response=response)

            def open_form():
                page.get_by_role("button", name="mail settings", exact=True).click()
                page.get_by_role("button", name="accounts", exact=True).click()
                page.locator("#mail-add-acct").click()

            def inputs():
                if configured:
                    disclosure = page.locator("#ma-oauth summary")
                    disclosure.scroll_into_view_if_needed()
                    box = disclosure.bounding_box()
                    assert box and box["height"] >= 44 and box["width"] >= 44, box
                    disclosure.focus()
                    page.keyboard.press("Enter")
                expect(page.locator("#ma-cid")).to_be_visible()
                page.locator("#ma-cid").fill("owned-client")
                page.locator("#ma-csec").fill("  dummy  ")

            def confirm():
                page.locator(".dialog-overlay").get_by_role(
                    "button", name="confirm", exact=True
                ).click()

            def wait_held():
                for _ in range(100):
                    if held:
                        return
                    page.wait_for_timeout(20)
                raise AssertionError("request was not held")

            def storage(mode):
                page.evaluate(
                    """mode=>{window.oauthStorageFault=mode; if(window.oauthStorageHook)return; window.oauthStorageHook=true;for(const name of ['getItem','setItem','removeItem']){const original=Storage.prototype[name];Storage.prototype[name]=function(key,...args){if(String(key).startsWith('alles-mail-oauth-pending:')&&((window.oauthStorageFault==='read'&&name==='getItem')||(window.oauthStorageFault==='write'&&name==='setItem')||(window.oauthStorageFault==='cleanup'&&name==='removeItem')))throw Error('owned storage failure');return original.call(this,key,...args)}}}""",
                    mode,
                )

            try:
                page.route(base + "/api/mail/oauth/status", read)
                page.route(base + "/api/mail/oauth/config", save)
                page.route(
                    base + "/api/mail/oauth/google/start",
                    lambda route: route.fulfill(
                        status=500, json={"detail": "provider navigation forbidden in fixture"}
                    ),
                )
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                if case == "storage-read":
                    storage("read")
                open_form()
                if case in ["status-reject", "status-invalid"]:
                    expect(page.locator("#ma-oauth")).to_contain_text("could not load Google setup")
                    expect(page.locator("#ma-cid")).to_have_count(0)
                    page.get_by_role("button", name="retry Google setup", exact=True).click()
                    expect(page.locator("#ma-cid")).to_be_visible()
                elif case == "storage-read":
                    expect(page.locator("#ma-oauth-status")).to_contain_text("could not read")
                    expect(page.locator("#ma-oauth-save")).to_have_attribute(
                        "aria-disabled", "true"
                    )
                    storage("")
                    page.get_by_role(
                        "button", name="retry reading Google recovery", exact=True
                    ).click()
                    expect(page.locator("#ma-oauth-save")).to_have_attribute(
                        "aria-disabled", "false"
                    )
                elif case in ["keep-retry", "keep-before-edit", "keep-during-edit"]:
                    inputs()
                    page.locator("#ma-rbase").fill("https://mail.example.invalid/")
                    page.locator("#ma-oauth-save").click()
                    expect(page.locator("#ma-oauth-status")).to_contain_text("unconfirmed")
                    page.get_by_role("button", name="review saved Google setup", exact=True).click()
                    confirm()
                    expect(page.locator("#ma-oauth-status")).to_contain_text("unconfirmed")
                    if case == "keep-before-edit":
                        page.locator("#ma-cid").fill("newer-client")
                        page.locator("#ma-csec").fill("example")
                    page.get_by_role("button", name="retry Google save", exact=True).click()
                    if case == "keep-during-edit":
                        wait_held()
                        page.locator("#ma-cid").fill("newer-client")
                        page.locator("#ma-csec").fill("example")
                        route, response = held.pop()
                        route.fulfill(response=response)
                    expect(page.locator("#ma-oauth-status")).to_contain_text("Google setup saved")
                    expect(page.locator("#ma-rbase")).to_have_value("")
                    assert writes[1] == writes[2]
                    assert not status()["configured"]
                    if case == "keep-retry":
                        expect(page.locator("#ma-cid")).to_have_value("")
                        expect(page.locator("#ma-csec")).to_have_value("")
                        page.locator("#ma-close").click()
                        expect(page.locator("#mail-add-acct")).to_be_visible()
                        expect(page.get_by_role("alertdialog")).to_have_count(0)
                    else:
                        expect(page.locator("#ma-cid")).to_have_value("newer-client")
                        expect(page.locator("#ma-csec")).to_have_value("example")
                        expect(page.locator("#ma-oauth-status")).to_contain_text(
                            "newer changes are unsaved"
                        )
                elif case.startswith("reopen-"):
                    inputs()
                    page.locator("#ma-rbase").fill("https://mail.example.invalid/")
                    page.locator("#ma-oauth-save").click()
                    expect(page.locator("#ma-oauth-status")).to_contain_text("unconfirmed")
                    page.locator("#ma-close").click()
                    confirm()
                    expect(page.locator("#mail-add-acct")).to_be_visible()
                    page.locator("#mail-add-acct").click()
                    expect(page.locator("#ma-cid")).to_have_value("")
                    if case == "reopen-before-edit":
                        page.locator("#ma-cid").fill("newer-client")
                        page.locator("#ma-csec").fill("example")
                    page.get_by_role("button", name="retry Google save", exact=True).click()
                    if case == "reopen-during-edit":
                        wait_held()
                        page.locator("#ma-cid").fill("newer-client")
                        page.locator("#ma-csec").fill("example")
                        route, response = held.pop()
                        route.fulfill(response=response)
                    expect(page.locator("#ma-oauth-status")).to_contain_text("Google setup saved")
                    expect(page.locator("#ma-rbase")).to_have_value("https://mail.example.invalid")
                    assert writes[0] == writes[1]
                    if case == "reopen-retry":
                        expect(page.locator("#ma-cid")).to_have_value("owned-client")
                        expect(page.locator("#ma-csec")).to_have_value("")
                        page.locator("#ma-close").click()
                        expect(page.locator("#mail-add-acct")).to_be_visible()
                        expect(page.get_by_role("alertdialog")).to_have_count(0)
                    else:
                        expect(page.locator("#ma-cid")).to_have_value("newer-client")
                        expect(page.locator("#ma-csec")).to_have_value("example")
                        expect(page.locator("#ma-oauth-status")).to_contain_text(
                            "newer changes are unsaved"
                        )
                elif case == "keep-secret":
                    page.locator("#ma-oauth summary").click()
                    expect(page.locator("#ma-cid")).to_have_value("saved-client")
                    expect(page.locator("#ma-csec")).to_have_value("")
                    page.locator("#ma-rbase").fill("")
                    page.locator("#ma-oauth-save").click()
                    expect(page.locator("#ma-oauth-status")).to_contain_text("Google setup saved")
                    assert writes[-1]["client_secret"] is None
                    assert status()["client_secret_configured"]
                    assert status()["redirect_base"] == ""
                else:
                    inputs()
                    if case == "retained-secret-race":
                        page.locator("#ma-cid").fill("saved-client")
                    elif case == "normalization":
                        page.locator("#ma-cid").fill("  saved-client  ")
                        page.locator("#ma-csec").fill("")
                        page.locator("#ma-rbase").fill("https://mail.example.invalid/base/")
                    if case == "keyboard":
                        assert page.get_by_label("Google client id", exact=True).count() == 1
                        assert page.get_by_label("Google client secret", exact=True).count() == 1
                        for target in ["ma-cid", "ma-csec", "ma-rbase", "ma-oauth-save"]:
                            rect = page.locator("#" + target).bounding_box()
                            assert rect and rect["height"] >= 44, (target, rect)
                    if case == "blank-redirect":
                        page.locator("#ma-rbase").fill("")
                    if case == "cancel-navigation":
                        page.locator("#ma-close").click()
                        page.locator(".dialog-overlay").get_by_role(
                            "button", name="cancel", exact=True
                        ).click()
                        expect(page.locator("#ma-cid")).to_have_value("owned-client")
                        expect(page.locator("#ma-csec")).to_have_value("  dummy  ")
                        assert not writes
                    else:
                        if case in ["storage-write", "storage-cleanup"]:
                            storage("write" if case == "storage-write" else "cleanup")
                        if case == "keyboard":
                            page.locator("#ma-oauth-save").focus()
                            page.keyboard.press("Enter")
                        else:
                            page.locator("#ma-oauth-save").click()
                        if case == "storage-write":
                            expect(page.locator("#ma-oauth-status")).to_contain_text(
                                "no request was sent"
                            )
                            assert not writes
                            storage("")
                            page.get_by_role(
                                "button", name="retry reading Google recovery", exact=True
                            ).click()
                            expect(page.locator("#ma-oauth-save")).to_have_attribute(
                                "aria-disabled", "false"
                            )
                            page.locator("#ma-oauth-save").click()
                        if case in ["newer-input", "double-save", "late-close"]:
                            wait_held()
                            if case == "newer-input":
                                page.locator("#ma-cid").fill("newer-client")
                                page.locator("#ma-csec").fill("example")
                            elif case == "double-save":
                                page.locator("#ma-oauth-save").click(force=True)
                                assert len(writes) == 1
                            else:
                                page.locator("#ma-close").click()
                                confirm()
                                expect(page.locator("#mail-add-acct")).to_be_visible()
                            route, response = held.pop()
                            route.fulfill(response=response)
                        if case in [
                            "save-reject",
                            "save-lost",
                            "reload-reject",
                            "reload-lost",
                            "keep-late",
                            "partial-id",
                            "partial-secret",
                            "legacy-redirect",
                            "legacy-text",
                            "keep-conflict",
                            "retained-secret-race",
                            "keep-newer",
                        ]:
                            expect(page.locator("#ma-oauth-status")).to_contain_text("unconfirmed")
                            expect(page.locator("#ma-csec")).to_have_value("  dummy  ")
                            records = page.evaluate(
                                "()=>Object.keys(sessionStorage).filter(k=>k.startsWith('alles-mail-oauth-pending:')).map(k=>JSON.parse(sessionStorage.getItem(k)))"
                            )
                            assert len(records) == 1 and set(records[0]) == {
                                "expected_revision",
                                "recovery_scope",
                            }, records
                            if case in ["save-reject", "save-lost"]:
                                page.get_by_role(
                                    "button", name="retry Google save", exact=True
                                ).click()
                                expect(page.locator("#ma-oauth-status")).to_contain_text(
                                    "Google setup saved"
                                )
                                assert writes[0] == writes[1]
                            else:
                                if case.startswith("reload"):
                                    page.reload(wait_until="networkidle")
                                    page.get_by_role("tab", name="mail", exact=True).click()
                                    open_form()
                                    expect(page.locator("#ma-oauth-status")).to_contain_text(
                                        "unconfirmed"
                                    )
                                    expect(
                                        page.get_by_role(
                                            "button", name="retry Google save", exact=True
                                        )
                                    ).to_have_count(0)
                                page.get_by_role(
                                    "button", name="review saved Google setup", exact=True
                                ).click()
                                confirm()
                                if case == "keep-newer":
                                    wait_held()
                                    page.locator("#ma-cid").fill("newer-client")
                                    page.locator("#ma-csec").fill("example")
                                    route, response = held.pop()
                                    route.fulfill(response=response)
                                    expect(page.locator("#ma-cid")).to_have_value("newer-client")
                                    expect(page.locator("#ma-csec")).to_have_value("example")
                                if case in ["keep-conflict", "retained-secret-race"]:
                                    expect(page.locator("#ma-oauth-status")).to_contain_text(
                                        "unconfirmed"
                                    )
                                    assert status()["client_id"] == (
                                        "other-client"
                                        if case == "keep-conflict"
                                        else "saved-client"
                                    )
                                    expect(
                                        page.get_by_role(
                                            "button", name="review saved Google setup", exact=True
                                        )
                                    ).to_be_visible()
                                    if case == "retained-secret-race":
                                        expect(page.locator("#ma-oauth-save")).to_have_attribute(
                                            "aria-disabled", "true"
                                        )
                                        page.get_by_role(
                                            "button", name="review saved Google setup", exact=True
                                        ).click()
                                        confirm()
                                        expect(page.locator("#ma-oauth-status")).to_have_text(
                                            "Google setup saved"
                                        )
                                        expect(page.locator("#ma-oauth-save")).to_have_attribute(
                                            "aria-disabled", "false"
                                        )
                                else:
                                    expect(page.locator("#ma-oauth-status")).to_contain_text(
                                        "Google setup saved"
                                    )
                                    assert status()["configured"] == (
                                        case in ["reload-lost", "legacy-redirect", "legacy-text"]
                                    )
                                    if case in ["partial-id", "partial-secret"]:
                                        assert status()["client_id"] == (
                                            "saved-client" if case == "partial-id" else ""
                                        )
                                        assert status()["client_secret_configured"] == (
                                            case == "partial-secret"
                                        )
                                        expect(page.locator("#ma-oauth-save")).to_have_attribute(
                                            "aria-disabled", "false"
                                        )
                                        page.locator("#ma-cid").fill("recovered-client")
                                        page.locator("#ma-csec").fill("example")
                                        page.locator("#ma-oauth-save").click()
                                        expect(page.locator("#ma-oauth-status")).to_have_text(
                                            "Google setup saved"
                                        )
                                        assert (
                                            status()["client_id"] == "recovered-client"
                                            and status()["configured"]
                                        )
                                    if case in ["legacy-redirect", "legacy-text"]:
                                        assert status()["client_id"] == (
                                            " saved-client "
                                            if case == "legacy-text"
                                            else "saved-client"
                                        )
                                        assert status()["redirect_base"] == (
                                            "https://example.invalid/base/"
                                            if case == "legacy-text"
                                            else "http:/example.invalid"
                                        )
                                        expect(page.locator("#ma-oauth-save")).to_have_attribute(
                                            "aria-disabled", "false"
                                        )
                                        page.locator("#ma-cid").fill("corrected-client")
                                        page.locator("#ma-rbase").fill("")
                                        page.locator("#ma-oauth-save").click()
                                        expect(page.locator("#ma-oauth-status")).to_have_text(
                                            "Google setup saved"
                                        )
                                        assert (
                                            status()["client_id"] == "corrected-client"
                                            and status()["redirect_base"] == ""
                                        )
                                    if case == "keep-late":
                                        assert (
                                            api.post(
                                                "/api/mail/oauth/config", data=writes[0]
                                            ).status
                                            == 409
                                        )
                                        assert not status()["configured"]
                        elif case == "late-close":
                            expect(page.locator("#mail-add-acct")).to_be_visible()
                            page.locator("#mail-add-acct").click()
                            expect(page.locator("#ma-oauth-saved")).to_contain_text(
                                "Google client keys are saved"
                            )
                            assert status()["client_id"] == "owned-client"
                        else:
                            expect(page.locator("#ma-oauth-status")).to_contain_text(
                                "Google setup saved"
                            )
                            if case == "storage-cleanup":
                                expect(page.locator("#ma-oauth-status")).to_contain_text(
                                    "could not be cleared"
                                )
                                expect(page.locator("#ma-oauth-save")).to_have_attribute(
                                    "aria-disabled", "true"
                                )
                                storage("")
                                page.get_by_role(
                                    "button", name="retry Google recovery cleanup", exact=True
                                ).click()
                                expect(page.locator("#ma-oauth-save")).to_have_attribute(
                                    "aria-disabled", "false"
                                )
                                assert len(writes) == 1
                            elif case == "normalization":
                                expect(page.locator("#ma-oauth-status")).to_have_text(
                                    "Google setup saved"
                                )
                                expect(page.locator("#ma-cid")).to_have_value("saved-client")
                                expect(page.locator("#ma-rbase")).to_have_value(
                                    "https://mail.example.invalid/base"
                                )
                                page.locator("#ma-close").click()
                                expect(page.locator("#mail-add-acct")).to_be_visible()
                                expect(page.get_by_role("alertdialog")).to_have_count(0)
                            elif case == "newer-input":
                                expect(page.locator("#ma-cid")).to_have_value("newer-client")
                                expect(page.locator("#ma-csec")).to_have_value("example")
                                expect(page.locator("#ma-oauth-status")).to_contain_text(
                                    "newer changes are unsaved"
                                )
                                page.locator("#ma-oauth-save").click()
                                expect(page.locator("#ma-csec")).to_have_value("")
                                assert status()["client_id"] == "newer-client"
                            else:
                                expect(page.locator("#ma-csec")).to_have_value("")
                                assert status()["client_id"] == "owned-client"
                            if case == "blank-redirect":
                                assert status()["redirect_base"] == ""
                        if writes and case not in ["keep-secret", "normalization"]:
                            assert writes[0]["client_secret"] == "  dummy  "
                assert not errors, errors
                assert page.evaluate("()=>document.documentElement.scrollWidth<=innerWidth"), (
                    "horizontal overflow"
                )
                result.update(
                    status="passed", page_errors=errors, console=console, writes=len(writes)
                )
            except Exception as e:
                result.update(
                    error=str(e),
                    traceback=traceback.format_exc(),
                    page_errors=errors,
                    console=console,
                )
            finally:
                for route, response in held:
                    route.fulfill(response=response)
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
