"""Signature entry and recovery use owned local settings and never send mail."""

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
    "uncertain",
    "uncertain-edit",
    "late-edited-retry",
    "restore-revision",
    "offline",
    "invalid-result",
    "read-reject",
    "read-invalid",
    "read-late",
    "refresh-late-save",
    "busy",
    "empty-name",
    "cancel",
]
if len(sys.argv) > 1:
    cases = [case for case in cases if case in sys.argv[1:]]
assert cases
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    seed_mail(api, base)
    assert api.post("/api/setup/dismiss").ok
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            for row in api.get("/api/mail/signatures").json()["signatures"]:
                assert api.delete("/api/mail/signatures/" + row["id"]).ok
            for row in api.get("/api/mail/drafts").json():
                assert api.delete("/api/mail/drafts/" + row["id"]).ok
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
            reads = []
            held = []
            blocked = {"read": False}
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            r = {
                "scenario_id": "inbox.signature." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(r)
            text = "Thanks,\nEric <fixture> & team"

            def intercept(route):
                if route.request.method == "GET":
                    reads.append(route.request.url)
                    if blocked["read"]:
                        return route.fulfill(
                            status=503, json={"detail": "owned signature check unavailable"}
                        )
                    if len(reads) == 1 and case in {"read-reject", "refresh-late-save"}:
                        return route.fulfill(
                            status=503, json={"detail": "owned signature list unavailable"}
                        )
                    if len(reads) == 1 and case == "read-invalid":
                        return route.fulfill(json={"signatures": [{"id": 9}]})
                    if (len(reads) == 1 and case == "read-late") or (
                        len(reads) == 2 and case == "refresh-late-save"
                    ):
                        held.append((route, route.fetch()))
                        return
                    return route.continue_()
                writes.append(route.request.post_data_json)
                if case == "restore-revision":
                    if len(writes) == 2:
                        held.append((route, None))
                        return
                    if len(writes) == 3:
                        return route.fulfill(
                            status=503, json={"detail": "owned restored save rejected"}
                        )
                if len(writes) == 1 and case == "reject":
                    return route.fulfill(
                        status=503, json={"detail": "owned signature save rejected"}
                    )
                if len(writes) == 1 and case == "invalid-result":
                    return route.fulfill(json={"id": "wrong", "name": "work", "body": text})
                if len(writes) == 1 and case == "late-edited-retry":
                    held.append((route, None))
                    return
                response = route.fetch()
                assert response.ok
                if len(writes) == 1 and case in {
                    "lost",
                    "uncertain",
                    "uncertain-edit",
                    "restore-revision",
                }:
                    blocked["read"] = case in {"uncertain", "uncertain-edit", "restore-revision"}
                    return route.fulfill(status=503, json={"detail": "owned lost signature reply"})
                if len(writes) == 1 and case == "busy":
                    held.append((route, response))
                    return
                route.fulfill(response=response)

            def wait_held():
                for _ in range(150):
                    if held:
                        return
                    page.wait_for_timeout(20)
                raise AssertionError("expected held request")

            def release():
                route, response = held.pop(0)
                if response is None:
                    response = route.fetch()
                    assert response.status == 409
                route.fulfill(response=response)
                page.evaluate(
                    "()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))"
                )

            def create_signature():
                page.locator("#mc-sig-add").click()
                dialog = page.get_by_role("dialog", name="signature", exact=True)
                expect(dialog.get_by_role("textbox", name="name", exact=True)).to_be_focused()
                dialog.get_by_role("textbox", name="name", exact=True).fill(
                    "" if case == "empty-name" else "work"
                )
                dialog.get_by_role("textbox", name="signature text", exact=True).fill(text)
                for control in dialog.locator("input, textarea, button").all():
                    box = control.bounding_box()
                    assert box and box["height"] >= 44, box
                dialog.get_by_role("button", name="save", exact=True).focus()
                page.keyboard.press("Tab")
                expect(dialog.get_by_role("textbox", name="name", exact=True)).to_be_focused()
                page.keyboard.press("Shift+Tab")
                expect(dialog.get_by_role("button", name="save", exact=True)).to_be_focused()
                page.screenshot(path=str(out / f"{width}-{case}-form.png"), full_page=True)
                return dialog

            try:
                if case != "offline":
                    page.route(base + "/api/mail/signatures", intercept)
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.locator("#mail-compose-btn").click()
                expect(page.locator("#mc-html")).to_be_visible()
                if case == "read-late":
                    wait_held()
                    page.locator("#mc-close").click()
                    page.locator("#mail-compose-btn").click()
                    expect(page.locator("#mc-sig-status")).to_have_text("")
                    page.locator("#mc-subj").fill("new composer")
                    release()
                    expect(page.locator("#mc-subj")).to_have_value("new composer")
                    expect(page.locator(".mc-sig-chip")).to_have_count(0)
                else:
                    if case in {"read-reject", "read-invalid", "refresh-late-save"}:
                        expect(page.locator("#mc-sig-status")).to_contain_text(
                            "could not load signatures"
                        )
                        expect(page.locator("#mc-sig-retry")).to_be_visible()
                        page.locator("#mc-sig-retry").focus()
                        page.keyboard.press("Enter")
                        if case == "refresh-late-save":
                            wait_held()
                        else:
                            expect(page.locator("#mc-sig-status")).to_have_text("")
                            expect(page.locator("#mc-sig-retry")).to_be_hidden()
                    else:
                        expect(page.locator("#mc-sig-status")).to_have_text("")
                    dialog = create_signature()
                    if case == "cancel":
                        page.keyboard.press("Escape")
                        expect(dialog).to_have_count(0)
                        expect(page.locator("#mc-sig-add")).to_be_focused()
                        assert api.get("/api/mail/signatures").json()["signatures"] == []
                        assert writes == []
                    else:
                        if case == "offline":
                            page.wait_for_function("()=>navigator.serviceWorker.controller")
                            context.set_offline(True)
                        dialog.get_by_role("button", name="save", exact=True).focus()
                        page.keyboard.press("Enter")
                        if case == "empty-name":
                            expect(dialog.get_by_role("alert")).to_have_text(
                                "enter a signature name"
                            )
                            assert writes == []
                            dialog.get_by_role("textbox", name="name", exact=True).fill("work")
                            dialog.get_by_role("button", name="save", exact=True).click()
                        if case in {
                            "reject",
                            "uncertain",
                            "uncertain-edit",
                            "late-edited-retry",
                            "restore-revision",
                            "offline",
                            "invalid-result",
                        }:
                            expect(dialog.get_by_role("alert")).to_contain_text(
                                "save unconfirmed", timeout=20000
                            )
                            expect(
                                dialog.get_by_role("textbox", name="name", exact=True)
                            ).to_have_value("work")
                            expect(
                                dialog.get_by_role("textbox", name="signature text", exact=True)
                            ).to_have_value(text)
                            page.screenshot(
                                path=str(out / f"{width}-{case}-unconfirmed.png"), full_page=True
                            )
                            assert len(api.get("/api/mail/signatures").json()["signatures"]) == (
                                1
                                if case in {"uncertain", "uncertain-edit", "restore-revision"}
                                else 0
                            )
                            if case == "offline":
                                queue = page.evaluate(
                                    "()=>new Promise((resolve,reject)=>{const c=new MessageChannel();const t=setTimeout(()=>reject(new Error('worker timeout')),5000);c.port1.onmessage=e=>{clearTimeout(t);resolve(e.data)};navigator.serviceWorker.controller.postMessage({type:'alles-outbox-list'},[c.port2])})"
                                )
                                assert queue["ok"] and queue["items"] == []
                                context.set_offline(False)
                            blocked["read"] = False
                            if case == "restore-revision":
                                body_input = dialog.get_by_role(
                                    "textbox", name="signature text", exact=True
                                )
                                body_input.fill("intermediate text")
                                dialog.get_by_role("button", name="save", exact=True).click()
                                expect(dialog.get_by_role("alert")).to_contain_text(
                                    "save unconfirmed", timeout=20000
                                )
                                body_input.fill(text)
                                dialog.get_by_role("button", name="save", exact=True).click()
                                expect(dialog.get_by_role("alert")).to_contain_text(
                                    "save unconfirmed"
                                )
                                expect(body_input).to_have_value(text)
                                assert (
                                    api.get("/api/mail/signatures").json()["signatures"][0][
                                        "revision"
                                    ]
                                    == 1
                                )
                            if case in {"uncertain-edit", "late-edited-retry"}:
                                text += " updated"
                                dialog.get_by_role(
                                    "textbox", name="signature text", exact=True
                                ).fill(text)
                            dialog.get_by_role("button", name="save", exact=True).click()
                        if case == "busy":
                            wait_held()
                            expect(dialog).to_have_attribute("aria-busy", "true")
                            expect(
                                dialog.get_by_role("button", name="saving…", exact=True)
                            ).to_be_disabled()
                            expect(
                                dialog.get_by_role("button", name="cancel", exact=True)
                            ).to_be_disabled()
                            expect(
                                dialog.get_by_role("textbox", name="signature text", exact=True)
                            ).to_be_disabled()
                            page.keyboard.press("Escape")
                            page.keyboard.press("Tab")
                            expect(dialog).to_be_visible()
                            assert page.evaluate(
                                '()=>document.activeElement.closest("[role=dialog]")!==null'
                            )
                            page.locator(".dialog-overlay").click(position={"x": 3, "y": 3})
                            page.keyboard.press("Tab")
                            assert page.evaluate(
                                '()=>document.activeElement.closest("[role=dialog]")!==null'
                            )
                            page.mouse.move(3, 3)
                            page.mouse.down()
                            page.keyboard.press("Tab")
                            assert page.evaluate(
                                '()=>document.activeElement.closest("[role=dialog]")!==null'
                            )
                            page.mouse.up()
                            assert len(writes) == 1
                            release()
                        expect(dialog).to_have_count(0)
                        expect(page.locator("#mc-sig-list")).to_contain_text("work")
                        expect(page.locator("#mc-sig-status")).to_have_text("")
                        if case == "refresh-late-save":
                            release()
                            expect(page.locator("#mc-sig-list")).to_contain_text("work")
                        if case in {"late-edited-retry", "restore-revision"}:
                            before = api.get("/api/mail/signatures").json()["signatures"]
                            assert len(before) == 1 and before[0]["body"] == text, before
                            release()
                        rows = api.get("/api/mail/signatures").json()["signatures"]
                        assert (
                            len(rows) == 1 and rows[0]["name"] == "work" and rows[0]["body"] == text
                        ), rows
                        if writes:
                            assert {w["id"] for w in writes} == {rows[0]["id"]}
                        if case == "lost":
                            assert len(writes) == 1
                        if case in {"uncertain", "uncertain-edit", "late-edited-retry"}:
                            assert len(writes) == 2
                        if case in {"uncertain-edit", "late-edited-retry"}:
                            assert [w["revision"] for w in writes] == [1, 2]
                        elif case == "restore-revision":
                            assert [w["revision"] for w in writes] == [1, 2, 3, 3]
                            assert rows[0]["revision"] == 3
                        elif writes:
                            assert {w["revision"] for w in writes} == {1}
                        page.locator(".mc-sig-chip").focus()
                        page.keyboard.press("Enter")
                        expect(page.locator("#mc-html")).to_contain_text("Eric <fixture> & team")
                        assert "\nEric <fixture> & team" in page.locator("#mc-html").inner_text()
                        assert page.locator("#mc-html fixture").count() == 0
                        page.locator("#mc-subj").fill("signature draft")
                        page.locator("#mc-save").click()
                        expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                        drafts = api.get("/api/mail/drafts").json()
                        assert (
                            len(drafts) == 1
                            and "Eric &lt;fixture&gt; &amp; team" in drafts[0]["body"]
                        )
                        page.reload(wait_until="networkidle")
                        page.get_by_role("tab", name="mail", exact=True).click()
                        page.locator("#mail-compose-btn").click()
                        expect(page.locator("#mc-sig-list")).to_contain_text("work")
                        page.locator(".mc-sig-chip").click()
                        expect(page.locator("#mc-html")).to_contain_text("Eric <fixture> & team")
                assert not errors, errors
                assert not [
                    line
                    for line in console
                    if not any(
                        x in line for x in ["503", "ERR_INTERNET_DISCONNECTED", "Failed to fetch"]
                    )
                ], console
                assert page.evaluate("()=>document.documentElement.scrollWidth<=innerWidth+1")
                r.update(
                    status="passed",
                    writes=writes,
                    read_count=len(reads),
                    page_errors=errors,
                    console_errors=console,
                )
            except Exception as e:
                r.update(
                    error=str(e),
                    traceback=traceback.format_exc(),
                    writes=writes,
                    read_count=len(reads),
                    page_errors=errors,
                    console_errors=console,
                )
            finally:
                while held:
                    if held[0][1] is None:
                        route, _ = held.pop(0)
                        route.abort()
                    else:
                        release()
                context.set_offline(False)
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
