"""Rule workflow/recovery in an owned mailbox; no outgoing reply rules or deliveries."""

import json
import os
import sys
import traceback
from pathlib import Path
from uuid import uuid4

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
cases = [
    "success",
    "reject",
    "lost",
    "reload",
    "reload-lost",
    "cancel-late",
    "delete-reject",
    "delete-lost",
    "delete-reload",
    "newer-input",
    "write-stale",
    "run-late",
    "run-partial",
    "run-invalid",
    "storage-write",
    "storage-read",
    "storage-cleanup",
    "read-invalid",
    "keyboard",
]
cases += ["reread-pending", "reread-saved", "reread-newer", "reread-empty", "status-node"]
cases += ["notice-write", "notice-readback"]
if len(sys.argv) > 1:
    cases = [case for case in cases if case in sys.argv[1:]]
assert cases
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    account = seed_mail(api, base)
    second = seed_mail(api, base)
    assert api.post("/api/setup/dismiss").ok
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            for row in api.get("/api/mail/rules").json()["rules"]:
                assert api.delete("/api/mail/rules/" + row["id"]).ok
            if case.startswith("delete-"):
                assert api.post(
                    "/api/mail/rules", data={"match_value": "receipts", "action": "markread"}
                ).ok
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(6000)
            errors, console, writes, held = [], [], [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            result = {
                "scenario_id": "inbox.rules." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)

            def open_rules():
                page.get_by_role("button", name="mail settings", exact=True).click()
                page.get_by_role("button", name="rules & vacation responder", exact=True).click()

            def intercept(route):
                method = route.request.method
                if method == "GET":
                    if case == "read-invalid":
                        return route.fulfill(json={"rules": [], "recovery_scopes": []})
                    return route.continue_()
                writes.append(
                    {
                        "method": method,
                        "body": route.request.post_data_json if method == "POST" else None,
                    }
                )
                first = len(writes) == 1
                if first and case in {
                    "reject",
                    "reload",
                    "cancel-late",
                    "delete-reject",
                    "delete-reload",
                }:
                    return route.fulfill(status=503, json={"detail": "owned rejected rule"})
                response = route.fetch()
                assert response.ok, response.text()
                if first and case in {"lost", "reload-lost", "delete-lost"}:
                    return route.fulfill(status=503, json={"detail": "owned lost response"})
                if first and case in {"newer-input", "write-stale"}:
                    held.append((route, response))
                    return
                route.fulfill(response=response)

            def run_intercept(route):
                if case == "run-late":
                    held.append((route, route.fetch()))
                elif case == "run-invalid":
                    route.fulfill(json={"applied": "unknown"})
                elif route.request.url.endswith(second["id"]):
                    route.fulfill(status=503, json={"detail": "owned account unavailable"})
                else:
                    route.continue_()

            try:
                page.route(base + "/api/mail/rules", intercept)
                page.route(base + "/api/mail/rules/*", intercept)
                if case.startswith("run-"):
                    page.route(base + "/api/mail/rules/run/*", run_intercept)
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                open_rules()
                if case == "read-invalid":
                    expect(page.locator("#mail-main").get_by_role("alert")).to_be_visible()
                    page.unroute(base + "/api/mail/rules", intercept)
                    page.locator("#mail-main").get_by_role(
                        "button", name="retry", exact=True
                    ).click()
                    expect(page.locator("#mr-add")).to_be_visible()
                else:
                    expect(page.locator("#mr-value")).to_be_visible()
                    page.locator("#mv-subject").fill("keep unsaved subject")
                    page.locator("#mv-body").fill("keep unsaved vacation text")
                    if case.startswith("run-"):
                        page.locator("#mr-run").click()
                        if case == "run-late":
                            for _ in range(100):
                                if held:
                                    break
                                page.wait_for_timeout(20)
                            assert held
                            page.locator("#mail-compose-btn").click()
                            page.locator("#mc-subj").fill("keep new composer")
                            page.unroute(base + "/api/mail/rules/run/*", run_intercept)
                            route, response = held.pop()
                            route.fulfill(response=response)
                            page.wait_for_timeout(200)
                            expect(page.locator("#mc-subj")).to_have_value("keep new composer")
                        else:
                            expect(page.locator("#mr-run-status")).to_contain_text(
                                "could not confirm"
                            )
                            expect(page.locator("#mr-run-status")).to_contain_text(
                                "1 account(s)" if case == "run-partial" else "0 account(s)"
                            )
                    elif case.startswith("delete-"):
                        page.locator(".mail-rule-del").click()
                        expect(page.locator("#mr-status")).to_contain_text("unconfirmed")
                        expect(page.locator("#mail-rules-list")).to_contain_text("receipts")
                        if case == "delete-reload":
                            page.reload(wait_until="networkidle")
                            page.get_by_role("tab", name="mail", exact=True).click()
                            open_rules()
                        page.locator("#mr-retry").click()
                        expect(page.locator("#mail-rules-list")).to_contain_text("no rules yet")
                        assert api.get("/api/mail/rules").json()["rules"] == []
                    elif case.startswith("notice-"):
                        page.locator("#mr-value").fill("first saved rule")
                        page.locator("#mr-add").click()
                        expect(page.locator("#mr-status")).to_contain_text("rule saved")
                        page.locator("#mr-value").fill("second unsaved rule")
                        page.evaluate(
                            """kind=>{const method=kind==='notice-write'?'setItem':'getItem';const original=Storage.prototype[method];window.restoreRuleStorage=()=>{Storage.prototype[method]=original};Storage.prototype[method]=function(key,...args){if(key.startsWith('alles-mail-rule:'))throw new Error('owned storage failure');return original.call(this,key,...args)}}""",
                            case,
                        )
                        page.locator("#mr-add").click()
                        expect(page.locator("#mr-status")).to_contain_text("no request was sent")
                        assert len(writes) == 1
                        page.evaluate("restoreRuleStorage()")
                        page.locator("#mr-read-retry").click()
                        expect(page.locator("#mr-status")).not_to_contain_text("rule saved")
                        expect(page.locator("#mr-value")).to_have_value("second unsaved rule")
                        if case == "notice-readback":
                            expect(page.locator("#mr-status")).to_contain_text("unconfirmed")
                            page.locator("#mr-retry").click()
                        else:
                            page.locator("#mr-add").click()
                        expect(page.locator("#mr-status")).to_contain_text("rule saved")
                        assert len(api.get("/api/mail/rules").json()["rules"]) == 2
                    elif case.startswith("reread-") or case == "status-node":
                        if case == "status-node":
                            page.evaluate(
                                "()=>window.ruleStatusNode=document.getElementById('mr-status')"
                            )
                            page.locator("#mr-value").fill("receipts")
                            page.locator("#mr-add").click()
                            expect(page.locator("#mr-status")).to_contain_text("rule saved")
                            assert page.evaluate(
                                "()=>window.ruleStatusNode===document.getElementById('mr-status')"
                            ), "live region was replaced"
                        else:
                            scope = api.get("/api/mail/rules").json()["recovery_scopes"][0]
                            pending = {
                                "kind": "create",
                                "request_id": str(uuid4()),
                                "recovery_scope": scope,
                                "match_field": "subject",
                                "match_value": "retained pending text",
                                "action": "label",
                                "action_arg": "retained label",
                                "enabled": True,
                            }
                            if case == "reread-saved":
                                assert api.post("/api/mail/rules", data=pending).ok
                            page.evaluate(
                                """({scope,pending,empty})=>{if(!empty)sessionStorage.setItem('alles-mail-rule:'+scope,JSON.stringify(pending));const original=Storage.prototype.getItem;window.restoreRuleRead=()=>{Storage.prototype.getItem=original};Storage.prototype.getItem=function(key){if(key.startsWith('alles-mail-rule:'))throw new Error('owned read failure');return original.call(this,key)}}""",
                                {
                                    "scope": scope,
                                    "pending": pending,
                                    "empty": case == "reread-empty",
                                },
                            )
                            open_rules()
                            expect(page.locator("#mr-status")).to_contain_text("could not read")
                            if case == "reread-newer":
                                page.locator("#mr-value").fill("newer local text")
                            page.evaluate("restoreRuleRead()")
                            page.locator("#mr-read-retry").focus()
                            page.keyboard.press("Enter")
                            if case == "reread-pending":
                                expect(page.locator("#mr-value")).to_have_value(
                                    pending["match_value"]
                                )
                                expect(page.locator("#mr-field")).to_have_attribute(
                                    "data-value", "subject"
                                )
                                expect(page.locator("#mr-action")).to_have_attribute(
                                    "data-value", "label"
                                )
                                expect(page.locator("#mr-arg")).to_have_value(pending["action_arg"])
                            elif case == "reread-newer":
                                expect(page.locator("#mr-value")).to_have_value("newer local text")
                                expect(page.locator("#mr-retry")).to_be_visible()
                            elif case == "reread-saved":
                                expect(page.locator("#mr-status")).to_contain_text("rule saved")
                                expect(page.locator("#mr-add")).to_have_attribute(
                                    "aria-disabled", "false"
                                )
                                assert writes == [], "reconciliation must not resubmit"
                            else:
                                assert page.evaluate(
                                    "()=>document.activeElement!==document.body && document.activeElement.getClientRects().length>0"
                                ), "focus left on body or hidden status"
                    elif case == "storage-read":
                        scope = api.get("/api/mail/rules").json()["recovery_scopes"][0]
                        page.evaluate(
                            '(scope)=>sessionStorage.setItem("alles-mail-rule:"+scope,"broken")',
                            scope,
                        )
                        open_rules()
                        expect(page.locator("#mr-status")).to_contain_text("could not read")
                        expect(page.locator("#mr-add")).to_have_attribute("aria-disabled", "true")
                        page.locator("#mr-clear").click()
                        page.locator(".dialog-overlay").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                        expect(page.locator("#mr-add")).to_have_attribute("aria-disabled", "false")
                    else:
                        if case == "keyboard":
                            page.locator("#mr-field").focus()
                            page.keyboard.press("ArrowDown")
                            page.keyboard.press("End")
                            page.keyboard.press("Enter")
                            expect(page.locator("#mr-field")).to_have_attribute(
                                "data-value", "subject"
                            )
                            page.locator("#mr-value").fill("Project notes")
                        else:
                            page.locator("#mr-value").fill("receipts")
                        if case in {"storage-write", "storage-cleanup"}:
                            page.evaluate(
                                """kind=>{const method=kind==='storage-write'?'setItem':'removeItem';window.restoreRuleStorage=()=>{Storage.prototype[method]=original};const original=Storage.prototype[method];Storage.prototype[method]=function(key,...args){if(key.startsWith('alles-mail-rule:'))throw new Error('owned storage failure');return original.call(this,key,...args)}}""",
                                case,
                            )
                        page.locator("#mr-add").focus()
                        page.keyboard.press("Enter")
                        if case == "storage-write":
                            expect(page.locator("#mr-status")).to_contain_text(
                                "no request was sent"
                            )
                            assert writes == []
                            page.evaluate("restoreRuleStorage()")
                            page.locator("#mr-read-retry").click()
                            page.locator("#mr-add").click()
                        elif case == "storage-cleanup":
                            expect(page.locator("#mr-status")).to_contain_text("retry cleanup")
                            expect(page.locator("#mr-add")).to_have_attribute(
                                "aria-disabled", "true"
                            )
                            page.evaluate("restoreRuleStorage()")
                            page.locator("#mr-cleanup").click()
                        elif case in {"newer-input", "write-stale"}:
                            for _ in range(100):
                                if held:
                                    break
                                page.wait_for_timeout(20)
                            assert held
                            if case == "newer-input":
                                page.locator("#mr-value").fill("newer unsaved rule")
                            else:
                                page.locator("#mail-compose-btn").click()
                                page.locator("#mc-subj").fill("keep new composer")
                            route, response = held.pop()
                            route.fulfill(response=response)
                            if case == "write-stale":
                                expect(page.locator("#mc-subj")).to_have_value("keep new composer")
                            else:
                                expect(page.locator("#mr-status")).to_contain_text(
                                    "newer changes are unsaved"
                                )
                                expect(page.locator("#mr-value")).to_have_value(
                                    "newer unsaved rule"
                                )
                        elif case in {"reject", "lost", "reload", "reload-lost", "cancel-late"}:
                            expect(page.locator("#mr-status")).to_contain_text("unconfirmed")
                            expect(page.locator("#mr-value")).to_have_value("receipts")
                            original = writes[0]["body"]
                            if case.startswith("reload"):
                                page.reload(wait_until="networkidle")
                                page.get_by_role("tab", name="mail", exact=True).click()
                                open_rules()
                            if case == "reload-lost":
                                expect(page.locator("#mr-status")).to_contain_text("rule saved")
                                assert len(writes) == 1
                            elif case == "cancel-late":
                                page.locator("#mr-cancel").click()
                                expect(page.locator("#mr-status")).to_contain_text("rule removed")
                                assert api.post("/api/mail/rules", data=original).status == 410
                            else:
                                page.locator("#mr-retry").click()
                                expect(page.locator("#mr-status")).to_contain_text("rule saved")
                                assert writes[1]["body"] == original
                        if case not in {"write-stale", "cancel-late"}:
                            expect(page.locator("#mail-rules-list")).to_contain_text(
                                "Project notes" if case == "keyboard" else "receipts"
                            )
                            assert len(api.get("/api/mail/rules").json()["rules"]) == 1
                        if case in {"success", "keyboard"}:
                            from core.database import CachedMessage, SessionLocal

                            with SessionLocal() as db:
                                db.query(CachedMessage).update({"seen": False})
                                db.commit()
                            page.locator("#mr-run").click()
                            expect(page.locator("#mr-run-status")).to_contain_text(
                                "2 rule action(s) confirmed across 2 account(s)"
                            )
                            with SessionLocal() as db:
                                seen = [
                                    (row.uid, row.seen) for row in db.query(CachedMessage).all()
                                ]
                                target = "702" if case == "keyboard" else "701"
                                assert all(value is (uid == target) for uid, value in seen), seen
                            page.locator(".mail-rule-del").click()
                            expect(page.locator("#mail-rules-list")).to_contain_text("no rules yet")
                            open_rules()
                            expect(page.locator("#mail-rules-list")).to_contain_text("no rules yet")
                    if case not in {
                        "run-late",
                        "write-stale",
                        "reload",
                        "reload-lost",
                        "delete-reload",
                        "storage-read",
                        "reread-pending",
                        "reread-saved",
                        "reread-newer",
                        "reread-empty",
                        "success",
                        "keyboard",
                    }:
                        expect(page.locator("#mv-subject")).to_have_value("keep unsaved subject")
                        expect(page.locator("#mv-body")).to_have_value("keep unsaved vacation text")
                assert not errors, errors
                assert not [
                    e for e in console if "Failed to load resource" not in e and "net::ERR" not in e
                ], console
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                result.update(status="passed", page_errors=errors, console=console, writes=writes)
            except Exception as error:
                result.update(
                    error=str(error),
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
raise SystemExit(any(row["status"] != "passed" for row in results))
