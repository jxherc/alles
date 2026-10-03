"""Account cancellation, acknowledgement and input retention in owned data."""

import json
import os
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
    "cancel-must-remove",
    "retain-retry",
    "retain-cleanup",
    "retain-newer",
    "unsent-close",
    "cancel-unsent-close",
    "deleted-elsewhere",
    "retain-matching-retry",
    "retain-matching-cleanup",
    "retain-matching-newer",
    "retain-store-write",
    "retain-store-readback",
    "oauth-close",
    "oauth-compose",
    "oauth-reload",
    "provider-change",
    "provider-cleanup",
]
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    assert api.post("/api/setup/dismiss").ok
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            kind = case.replace("retain-matching-", "retain-")
            matching = case.startswith("retain-matching-")
            for row in api.get("/api/mail/accounts").json():
                assert api.delete("/api/mail/accounts/" + row["id"]).ok
            account = seed_mail(api, base)
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(5000)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            writes = []
            held = []
            result = {
                "scenario_id": "inbox.accounts." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)

            def confirm():
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()

            def intercept(route):
                method = route.request.method
                if method == "GET":
                    return route.continue_()
                writes.append(
                    {
                        "method": method,
                        "body": route.request.post_data_json if method != "DELETE" else None,
                        "url": route.request.url,
                    }
                )
                if case == "cancel-must-remove":
                    if method == "POST":
                        response = route.fetch()
                        assert response.ok
                        return route.fulfill(status=503, json={"detail": "owned lost create reply"})
                    if (
                        method == "DELETE"
                        and len([r for r in writes if r["method"] == "DELETE"]) == 1
                    ):
                        return route.fulfill(
                            status=503, json={"detail": "owned delayed cancellation"}
                        )
                elif (
                    len(writes) == 1
                    and case != "deleted-elsewhere"
                    and not case.startswith("provider-")
                ):
                    return route.fulfill(status=503, json={"detail": "owned rejected edit"})
                if len(writes) == 2 and kind == "retain-retry":
                    return route.fulfill(status=503, json={"detail": "owned unconfirmed retention"})
                response = route.fetch()
                if len(writes) == 2 and kind == "retain-newer":
                    held.append((route, response))
                    return
                route.fulfill(response=response)

            try:
                page.route(base + "/api/mail/accounts", intercept)
                page.route(base + "/api/mail/accounts/*", intercept)
                page.route(
                    base + "/api/mail/test/*", lambda route: route.fulfill(json={"ok": True})
                )
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.get_by_role("button", name="mail settings", exact=True).click()
                page.get_by_role("button", name="accounts", exact=True).click()
                if case.startswith("oauth-"):
                    page.locator("#mail-add-acct").click()
                    page.locator("#ma-cid").fill("owned-client")
                    page.locator("#ma-csec").fill("dummy")
                    page.locator("#ma-rbase").fill("https://example.invalid")
                    if case == "oauth-reload":
                        dialogs = []

                        def keep_google_inputs(dialog):
                            dialogs.append(dialog.type)
                            dialog.dismiss()

                        page.on("dialog", keep_google_inputs)
                        try:
                            page.reload(wait_until="domcontentloaded", timeout=2000)
                        except Exception as error:
                            assert dialogs == ["beforeunload"] and (
                                "ERR_ABORTED" in str(error) or "Timeout" in str(error)
                            ), str(error)
                        assert dialogs == ["beforeunload"]
                    else:
                        if case == "oauth-close":
                            page.locator("#ma-close").click()
                        else:
                            page.get_by_role("button", name="compose", exact=True).click()
                        expect(page.get_by_role("alertdialog")).to_be_visible()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="cancel", exact=True
                        ).click()
                    expect(page.locator("#ma-cid")).to_have_value("owned-client")
                    expect(page.locator("#ma-csec")).to_have_value("dummy")
                    expect(page.locator("#ma-rbase")).to_have_value("https://example.invalid")
                    assert not errors, errors
                    result["status"] = "passed"
                    continue
                if case in {"cancel-must-remove", "cancel-unsent-close"}:
                    page.locator("#mail-add-acct").click()
                    for key, value in [
                        ("email", "pending@example.invalid"),
                        ("imaph", "127.0.0.1"),
                        ("imapp", "1"),
                        ("smtph", "127.0.0.1"),
                        ("smtpp", "1"),
                        ("pass", "dummy"),
                    ]:
                        page.locator("#ma-" + key).fill(value)
                else:
                    page.locator(".mail-acct-edit").click()
                    page.locator("#ma-name").fill("rejected local name")
                    page.locator("#ma-pass").fill("dummy")
                if case == "unsent-close":
                    page.evaluate(
                        """()=>{ window.accountSet = Storage.prototype.setItem; Storage.prototype.setItem=function(k,v){if(k.startsWith('alles-mail-account-pending:'))throw Error('owned failure');return window.accountSet.call(this,k,v);}; }"""
                    )
                if case == "provider-cleanup":
                    page.evaluate(
                        """()=>{window.savedRemove=Storage.prototype.removeItem;Storage.prototype.removeItem=function(k){if(k.startsWith('alles-mail-account-pending:'))throw Error('owned cleanup failure');return window.savedRemove.call(this,k);};}"""
                    )
                if case == "deleted-elsewhere":
                    assert api.delete("/api/mail/accounts/" + account["id"]).ok
                page.locator("#ma-save").click()
                status = page.locator("#ma-status")
                recovery = page.locator("#ma-recovery-status")
                if case.startswith("provider-"):
                    if case == "provider-cleanup":
                        expect(recovery).to_contain_text("recovery data could not be cleared")
                        page.evaluate("()=>{Storage.prototype.removeItem=window.savedRemove;}")
                        page.get_by_role(
                            "button", name="retry account recovery cleanup", exact=True
                        ).click()
                        expect(recovery).to_have_text("account recovery cleared")
                    else:
                        expect(status).to_have_text("account saved; incoming mail connected")
                    page.locator('[data-provider="gmail"]').click()
                    expect(page.locator("#ma-imaph")).to_have_value("imap.gmail.com")
                    expect(status).to_have_text("account changes are unsaved")
                    expect(recovery).to_be_empty()
                    saved = next(
                        row
                        for row in api.get("/api/mail/accounts").json()
                        if row["id"] == account["id"]
                    )
                    assert saved["imap_host"] == account["imap_host"] and saved["use_ssl"] is False
                elif case == "unsent-close":
                    expect(recovery).to_contain_text("could not retain")
                    assert not writes
                    page.locator("#ma-close").click()
                    expect(page.get_by_role("alertdialog")).to_be_visible()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="cancel", exact=True
                    ).click()
                    expect(page.locator("#ma-pass")).to_have_value("dummy")
                    page.evaluate("()=>{Storage.prototype.setItem=window.accountSet;}")
                    page.get_by_role(
                        "button", name="retry reading account recovery", exact=True
                    ).click()
                    page.locator("#ma-close").click()
                    expect(page.get_by_role("alertdialog")).to_be_visible()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="cancel", exact=True
                    ).click()
                    expect(page.locator("#ma-name")).to_have_value("rejected local name")
                else:
                    expect(recovery).to_contain_text("save unconfirmed")
                    if case == "deleted-elsewhere":
                        page.get_by_role(
                            "button", name="review current settings", exact=True
                        ).click()
                        confirm()
                        page.get_by_role(
                            "button", name="remove pending account", exact=True
                        ).click()
                        confirm()
                        expect(recovery).to_have_text("account removed")
                        assert api.get("/api/mail/accounts").json() == []
                    elif case == "cancel-unsent-close":
                        page.get_by_role(
                            "button", name="remove pending account", exact=True
                        ).click()
                        confirm()
                        expect(recovery).to_have_text("account removed")
                        page.evaluate(
                            """()=>{Storage.prototype.setItem=new Proxy(Storage.prototype.setItem,{apply(target,self,args){if(args[0].startsWith('alles-mail-account-pending:'))throw Error('owned failure');return Reflect.apply(target,self,args);}});}"""
                        )
                        page.locator("#ma-save").click()
                        expect(recovery).to_contain_text("could not retain")
                        assert len(writes) == 2
                        page.locator("#ma-close").click()
                        expect(page.get_by_role("alertdialog")).to_be_visible()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="cancel", exact=True
                        ).click()
                        expect(page.locator("#ma-pass")).to_have_value("dummy")
                    elif case == "cancel-must-remove":
                        aid = writes[0]["body"]["request_id"]
                        page.get_by_role(
                            "button", name="remove pending account", exact=True
                        ).click()
                        confirm()
                        expect(recovery).to_contain_text("removal unconfirmed")
                        page.locator("#ma-close").click()
                        expect(page.locator("#mail-add-acct")).to_be_visible()
                        retain = page.get_by_role(
                            "button", name="review current settings", exact=True
                        )
                        expect(retain).to_have_count(0)
                        page.get_by_role("button", name="retry removal", exact=True).click()
                        expect(recovery).to_have_text("account removed")
                        assert not any(r["id"] == aid for r in api.get("/api/mail/accounts").json())
                    elif case.startswith("retain-store-"):
                        page.evaluate(
                            """kind=>{const set=Storage.prototype.setItem,get=Storage.prototype.getItem;window.failAccountRead=false;Storage.prototype.setItem=function(k,v){if(k.startsWith('alles-mail-account-pending:')){if(kind==='retain-store-write')throw Error('owned write failure');set.call(this,k,v);window.failAccountRead=true;return;}return set.call(this,k,v);};Storage.prototype.getItem=function(k){if(window.failAccountRead&&k.startsWith('alles-mail-account-pending:'))throw Error('owned readback failure');return get.call(this,k);};}""",
                            case,
                        )
                        page.get_by_role(
                            "button", name="review current settings", exact=True
                        ).click()
                        confirm()
                        expect(recovery).to_contain_text("could not retain")
                        assert len(writes) == 1
                        page.locator("#ma-close").click()
                        expect(page.get_by_role("alertdialog")).to_be_visible()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="cancel", exact=True
                        ).click()
                        expect(page.locator("#ma-name")).to_have_value("rejected local name")
                        expect(page.locator("#ma-pass")).to_have_value("dummy")
                    else:
                        if kind == "retain-cleanup":
                            page.evaluate(
                                """()=>{ window.accountRemove=Storage.prototype.removeItem; Storage.prototype.removeItem=function(k){if(k.startsWith('alles-mail-account-pending:'))throw Error('owned cleanup failure');return window.accountRemove.call(this,k);}; }"""
                            )
                        page.get_by_role(
                            "button", name="review current settings", exact=True
                        ).click()
                        confirm()
                        if kind == "retain-newer":
                            for _ in range(150):
                                if held:
                                    break
                                page.wait_for_timeout(20)
                            assert held
                            page.locator("#ma-name").fill(
                                account["name"] if matching else "new input during recovery"
                            )
                            page.locator("#ma-pass").fill("" if matching else "example")
                            route, response = held.pop()
                            route.fulfill(response=response)
                        elif kind == "retain-retry":
                            expect(recovery).to_contain_text("owned unconfirmed retention")
                            if matching:
                                page.locator("#ma-name").fill(account["name"])
                                page.locator("#ma-pass").fill("")
                            page.get_by_role(
                                "button", name="retry saved changes", exact=True
                            ).click()
                        else:
                            expect(recovery).to_contain_text("recovery data could not be cleared")
                        if matching:
                            if kind == "retain-cleanup":
                                page.evaluate(
                                    "()=>{Storage.prototype.removeItem=window.accountRemove;}"
                                )
                                page.get_by_role(
                                    "button", name="retry account recovery cleanup", exact=True
                                ).click()
                                page.locator("#ma-name").fill(account["name"])
                                page.locator("#ma-pass").fill("")
                            expect(page.locator("#ma-save")).to_have_attribute(
                                "aria-disabled", "false"
                            )
                            page.locator("#ma-close").click()
                            expect(page.locator("#mail-add-acct")).to_be_visible()
                            expect(page.get_by_role("alertdialog")).to_have_count(0)
                        else:
                            expect(status).to_contain_text("newer changes are unsaved")
                            expect(page.locator("#ma-name")).to_have_value(
                                "new input during recovery"
                                if kind == "retain-newer"
                                else "rejected local name"
                            )
                            expect(page.locator("#ma-pass")).to_have_value(
                                "example" if kind == "retain-newer" else "dummy"
                            )
                            assert (
                                next(
                                    r
                                    for r in api.get("/api/mail/accounts").json()
                                    if r["id"] == account["id"]
                                )["name"]
                                == account["name"]
                            )
                assert not errors, errors
                result["status"] = "passed"
            except Exception as e:
                result.update(error=str(e), traceback=traceback.format_exc(), page_errors=errors)
            finally:
                for route, response in held:
                    route.fulfill(response=response)
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
