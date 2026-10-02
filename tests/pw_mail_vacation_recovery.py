"""Vacation settings recovery using disposable state; replies always disabled."""

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
    "reject",
    "lost",
    "offline",
    "invalid-result",
    "read-reject",
    "read-malformed",
    "newer-input",
    "write-stale",
    "read-rules",
    "read-stale",
    "pending-reopen",
    "edit-after-subject",
    "edit-after-body",
    "edit-after-enabled",
]
if len(sys.argv) > 1:
    cases = [c for c in cases if c in sys.argv[1:]]
assert cases and len(cases) == len(set(cases))
initial = {"enabled": False, "subject": "Initial", "body": "initial text"}
body = {"enabled": False, "subject": "Away", "body": "back Monday\nsecond line"}
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    seed_mail(api, base)
    assert api.post("/api/setup/dismiss").ok
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            assert api.post("/api/mail/vacation", data=initial).ok
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="allow" if case == "offline" else "block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            errors = []
            console = []
            writes = []
            held = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            result = {
                "scenario_id": "inbox.vacation." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)

            def intercept(route):
                if route.request.method == "GET":
                    if case == "read-reject":
                        return route.fulfill(
                            status=503, json={"detail": "owned vacation unavailable"}
                        )
                    if case == "read-malformed":
                        return route.fulfill(json={"enabled": "unknown"})
                    if case == "read-stale":
                        held.append((route, route.fetch()))
                        return
                    return route.continue_()
                writes.append(route.request.post_data_json)
                assert writes[-1]["enabled"] is False
                if len(writes) == 1 and case == "invalid-result":
                    return route.fulfill(
                        json={"enabled": False, "subject": "wrong", "body": "wrong"}
                    )
                if len(writes) == 1 and case == "reject":
                    return route.fulfill(status=503, json={"detail": "owned rejected vacation"})
                if len(writes) == 1 and case == "pending-reopen":
                    held.append((route, None))
                    return
                response = route.fetch()
                assert response.ok
                if len(writes) == 1 and case == "lost":
                    return route.fulfill(status=503, json={"detail": "owned lost vacation reply"})
                if len(writes) == 1 and case in {"newer-input", "write-stale"}:
                    held.append((route, response))
                    return
                route.fulfill(response=response)

            try:
                if case != "offline":
                    page.route(base + "/api/mail/vacation", intercept)
                if case == "read-rules":
                    page.route(
                        base + "/api/mail/rules",
                        lambda route: route.fulfill(
                            status=503, json={"detail": "owned rules unavailable"}
                        ),
                    )
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                page.get_by_role("button", name="mail settings", exact=True).click()
                page.get_by_role("button", name="rules & vacation responder", exact=True).click()
                if case == "read-stale":
                    for _ in range(100):
                        if held:
                            break
                        page.wait_for_timeout(20)
                    assert held
                    page.locator("#mail-compose-btn").click()
                    expect(page.locator("#mc-html")).to_be_visible()
                    page.locator("#mc-subj").fill("keep new composer")
                    route, response = held.pop()
                    route.fulfill(response=response)
                    page.evaluate(
                        "()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))"
                    )
                    expect(page.locator("#mc-subj")).to_have_value("keep new composer")
                    expect(page.locator("#mv-save")).to_have_count(0)
                elif case.startswith("read-"):
                    expect(page.locator("#mail-main").get_by_role("alert")).to_be_visible()
                    expect(page.locator("#mv-save")).to_have_count(0)
                    page.unroute(base + "/api/mail/vacation", intercept)
                    page.unroute(base + "/api/mail/rules")
                    page.locator("#mail-main").get_by_role(
                        "button", name="retry", exact=True
                    ).click()
                    expect(page.locator("#mv-subject")).to_have_value("Initial")
                    expect(page.locator("#mv-body")).to_have_value("initial text")
                else:
                    expect(page.locator("#mv-body")).to_have_value("initial text")
                    page.locator("#mv-enabled").focus()
                    page.keyboard.press("Enter")
                    expect(page.locator("#mv-enabled")).to_have_attribute("aria-pressed", "true")
                    page.keyboard.press("Enter")
                    expect(page.locator("#mv-enabled")).to_have_attribute("aria-pressed", "false")
                    page.locator("#mv-subject").fill(body["subject"])
                    page.locator("#mv-body").fill(body["body"])
                    if case == "offline":
                        page.wait_for_function("()=>navigator.serviceWorker.controller")
                        context.set_offline(True)
                    page.locator("#mv-save").focus()
                    page.keyboard.press("Enter")
                    if case in {"reject", "lost", "offline", "invalid-result"}:
                        expect(page.locator("#mv-status")).to_contain_text("unconfirmed")
                        page.locator("#mv-status").scroll_into_view_if_needed()
                        page.screenshot(
                            path=str(out / f"{width}-{case}-unconfirmed.png"), full_page=True
                        )
                        expect(page.locator("#mv-subject")).to_have_value(body["subject"])
                        expect(page.locator("#mv-body")).to_have_value(body["body"])
                        assert api.get("/api/mail/vacation").json() == (
                            body if case == "lost" else initial
                        )
                        if case == "offline":
                            queue = page.evaluate(
                                "()=>new Promise((resolve,reject)=>{const c=new MessageChannel();const t=setTimeout(()=>reject(new Error('worker timeout')),5000);c.port1.onmessage=e=>{clearTimeout(t);resolve(e.data)};navigator.serviceWorker.controller.postMessage({type:'alles-outbox-list'},[c.port2])})"
                            )
                            assert queue["ok"] and queue["items"] == []
                            context.set_offline(False)
                        page.locator("#mv-save").click()
                    if case == "pending-reopen":
                        expect(page.locator("#mv-save")).to_be_disabled()
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(20)
                        assert held
                        page.get_by_role("button", name="mail settings", exact=True).click()
                        page.get_by_role(
                            "button", name="rules & vacation responder", exact=True
                        ).click()
                        expect(page.locator("#mail-main").get_by_role("status")).to_have_text(
                            "loading rules…"
                        )
                        expect(page.locator("#mv-save")).to_have_count(0)
                        route, _ = held.pop()
                        response = route.fetch()
                        assert response.ok
                        route.fulfill(response=response)
                        expect(page.locator("#mv-body")).to_have_value(body["body"])
                        page.locator("#mv-body").fill("newer unsaved text")
                        page.locator("#mv-save").click()
                    if case in {"newer-input", "write-stale"}:
                        expect(page.locator("#mv-save")).to_be_disabled()
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(20)
                        assert held and len(writes) == 1
                        if case == "newer-input":
                            page.locator("#mv-body").fill("newer unsaved text")
                        else:
                            page.locator("#mail-compose-btn").click()
                            expect(page.locator("#mc-html")).to_be_visible()
                            page.locator("#mc-subj").fill("keep new composer")
                        route, response = held.pop()
                        route.fulfill(response=response)
                        page.evaluate(
                            "()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))"
                        )
                    if case == "write-stale":
                        expect(page.locator("#mc-subj")).to_have_value("keep new composer")
                        expect(page.locator("#mv-status")).to_have_count(0)
                    else:
                        expect(page.locator("#mv-status")).to_contain_text("saved")
                        expect(page.locator("#mv-save")).to_be_enabled()
                        if case == "newer-input":
                            expect(page.locator("#mv-status")).to_have_text(
                                "earlier vacation reply saved; newer changes are unsaved"
                            )
                            expect(page.locator("#mv-body")).to_have_value("newer unsaved text")
                            page.locator("#mv-save").click()
                            expect(page.locator("#mv-status")).to_contain_text("saved")
                            expect(page.locator("#mv-save")).to_be_enabled()
                        if case.startswith("edit-after-"):
                            field = case.removeprefix("edit-after-")
                            if field == "enabled":
                                page.locator("#mv-enabled").click()
                            else:
                                page.locator("#mv-" + field).fill("new unsaved value")
                            assert api.get("/api/mail/vacation").json() == body
                            expect(page.locator("#mv-status")).to_have_text(
                                "vacation changes are unsaved"
                            )
                            if field == "enabled":
                                page.locator("#mv-enabled").click()
                            else:
                                page.locator("#mv-" + field).fill(body[field])
                            expect(page.locator("#mv-status")).to_have_text("vacation reply saved")
                        expected = body | (
                            {"body": "newer unsaved text"}
                            if case in {"newer-input", "pending-reopen"}
                            else {}
                        )
                        assert api.get("/api/mail/vacation").json() == expected
                        page.reload(wait_until="networkidle")
                        page.get_by_role("tab", name="mail", exact=True).click()
                        page.get_by_role("button", name="mail settings", exact=True).click()
                        page.get_by_role(
                            "button", name="rules & vacation responder", exact=True
                        ).click()
                        expect(page.locator("#mv-body")).to_have_value(expected["body"])
                assert not [
                    line
                    for line in console
                    if not any(
                        x in line for x in ["503", "ERR_INTERNET_DISCONNECTED", "Failed to fetch"]
                    )
                ], console
                assert not errors, errors
                assert page.evaluate("()=>document.documentElement.scrollWidth<=innerWidth+1")
                sizes = page.locator("#mv-save,#mv-enabled").evaluate_all(
                    "buttons=>buttons.filter(b=>b.getClientRects().length).map(b=>{const r=b.getBoundingClientRect();return [r.width,r.height]})"
                )
                assert all(w >= 44 and h >= 44 for w, h in sizes), sizes
                result.update(
                    status="passed", writes=writes, page_errors=errors, console_errors=console
                )
            except Exception as e:
                result.update(
                    error=str(e),
                    traceback=traceback.format_exc(),
                    writes=writes,
                    page_errors=errors,
                    console_errors=console,
                )
            finally:
                for route, response in held:
                    route.fulfill(response=response if response is not None else route.fetch())
                context.set_offline(False)
                visible_result = page.locator("#mv-status,#mail-main [role=alert]").first
                if visible_result.count():
                    visible_result.scroll_into_view_if_needed()
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
