"""Manage signatures against an owned local server; never deliver a message."""

import json
import os
import sys
import traceback
import uuid
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
cases = [
    "workflow",
    "edit-reject",
    "edit-lost",
    "edit-uncertain",
    "edit-uncertain-change",
    "edit-conflict",
    "edit-race",
    "edit-deleted",
    "edit-read-reject",
    "edit-offline",
    "edit-cancel",
    "remove-reject",
    "remove-lost",
    "remove-uncertain",
    "remove-overlap",
    "remove-reload",
    "remove-reload-focus",
    "remove-conflict",
    "remove-cancel",
    "remove-late",
    "remove-busy",
    "remove-read-late",
    "remove-offline",
    "long-name",
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
            sid = str(uuid.uuid4())
            name = "work" if case != "long-name" else "signature" * 35
            initial = {"id": sid, "name": name, "body": "Original\nEric <fixture>", "revision": 1}
            if case != "workflow":
                assert api.post("/api/mail/signatures", data=initial).ok
            other = {
                "id": str(uuid.uuid4()),
                "name": "personal",
                "body": "Other signature",
                "revision": 1,
            }
            if case == "remove-overlap":
                assert api.post("/api/mail/signatures", data=other).ok
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="allow" if case.endswith("offline") else "block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            errors, console, writes, deletes, held = [], [], [], [], []
            state = {"block_read": False, "reject_edit_read": False, "hold_read": False}
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            result = {
                "scenario_id": "inbox.signature-management." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)

            def signatures():
                response = api.get("/api/mail/signatures")
                assert response.ok
                return response.json()["signatures"]

            def intercept(route):
                method = route.request.method
                if method == "GET":
                    if state["block_read"] or state["reject_edit_read"]:
                        state["reject_edit_read"] = False
                        return route.fulfill(status=503, json={"detail": "owned list unavailable"})
                    if state["hold_read"]:
                        held.append((route, route.fetch()))
                        return
                    return route.continue_()
                if method == "POST":
                    writes.append(route.request.post_data_json)
                    if len(writes) == 1 and case == "edit-reject":
                        return route.fulfill(status=503, json={"detail": "owned save rejected"})
                    if len(writes) == 1 and case == "edit-race":
                        assert api.post(
                            "/api/mail/signatures",
                            data={**initial, "body": "newer editor", "revision": 2},
                        ).ok
                    response = route.fetch()
                    if len(writes) == 1 and case in {
                        "edit-lost",
                        "edit-uncertain",
                        "edit-uncertain-change",
                    }:
                        assert response.ok
                        state["block_read"] = case != "edit-lost"
                        return route.fulfill(status=503, json={"detail": "owned lost save reply"})
                    return route.fulfill(response=response)
                assert method == "DELETE", method
                deletes.append(route.request.url)
                if len(deletes) == 1 and case in {"remove-reject", "remove-read-late"}:
                    return route.fulfill(status=503, json={"detail": "owned removal rejected"})
                if len(deletes) == 1 and case == "remove-conflict":
                    assert api.post(
                        "/api/mail/signatures",
                        data={**initial, "body": "newer editor", "revision": 2},
                    ).ok
                if len(deletes) == 2 and case == "remove-read-late":
                    held.append((route, None))
                    return
                response = route.fetch()
                if len(deletes) == 1 and case in {
                    "remove-lost",
                    "remove-uncertain",
                    "remove-overlap",
                    "remove-reload",
                    "remove-reload-focus",
                }:
                    assert response.ok
                    state["block_read"] = case in {
                        "remove-uncertain",
                        "remove-overlap",
                        "remove-reload",
                        "remove-reload-focus",
                    }
                    return route.fulfill(status=503, json={"detail": "owned lost removal reply"})
                if len(deletes) == 1 and case in {"remove-late", "remove-busy"}:
                    held.append((route, response))
                    return
                return route.fulfill(response=response)

            def release():
                route, response = held.pop(0)
                route.fulfill(response=response or route.fetch())

            def wait_held():
                for _ in range(150):
                    if held:
                        return
                    page.wait_for_timeout(20)
                raise AssertionError("missing held request")

            def manager():
                page.locator("#mc-sig-manage").focus()
                page.keyboard.press("Enter")
                expect(page.locator("#mc-sig-manage")).to_have_attribute("aria-expanded", "true")
                expect(page.get_by_role("region", name="saved signatures")).to_be_visible()

            def save(dialog):
                dialog.get_by_role("button", name="save", exact=True).click()

            try:
                if not case.endswith("offline"):
                    page.route(base + "/api/mail/signatures**", intercept)
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.locator("#mail-compose-btn").click()
                expect(page.locator("#mc-sig-status")).to_have_text("")
                page.locator("#mc-subj").fill("management draft")
                page.locator("#mc-html").fill("message stays unchanged")
                if case == "workflow":
                    page.locator("#mc-sig-add").click()
                    dialog = page.get_by_role("dialog", name="signature", exact=True)
                    dialog.get_by_role("textbox", name="name", exact=True).fill(name)
                    dialog.get_by_role("textbox", name="signature text", exact=True).fill(
                        initial["body"]
                    )
                    save(dialog)
                    expect(dialog).to_have_count(0)
                    expect(page.locator("#mc-sig-status")).to_have_text("")
                    sid = signatures()[0]["id"]
                manager()
                for control in page.locator("#mc-sig-manager button, #mc-sig-manage").all():
                    box = control.bounding_box()
                    assert box and box["height"] >= 44 and box["width"] >= 44, box
                if case == "long-name":
                    chip = page.locator(".mc-sig-chip")
                    box = chip.bounding_box()
                    compose = page.locator("#mc-html").bounding_box()
                    assert (
                        box["x"] >= compose["x"] - 1
                        and box["x"] + box["width"] <= compose["x"] + compose["width"] + 1
                    ), (box, compose)
                    chip.focus()
                    page.keyboard.press("Enter")
                    expect(page.locator("#mc-html")).to_contain_text("Eric <fixture>")
                page.screenshot(path=str(out / f"{width}-{case}-manager.png"), full_page=True)
                if case.startswith("edit") or case == "workflow":
                    page.get_by_role("button", name="edit " + name, exact=True).focus()
                    page.keyboard.press("Enter")
                    dialog = page.get_by_role("dialog", name="edit signature", exact=True)
                    expect(dialog.get_by_role("textbox", name="name", exact=True)).to_be_focused()
                    expect(
                        dialog.get_by_role("textbox", name="signature text", exact=True)
                    ).to_have_value(initial["body"])
                    new_body = "Thanks,\nEric <updated> & team"
                    dialog.get_by_role("textbox", name="name", exact=True).fill("updated work")
                    dialog.get_by_role("textbox", name="signature text", exact=True).fill(new_body)
                    if case == "edit-cancel":
                        page.keyboard.press("Escape")
                        expect(dialog).to_have_count(0)
                        expect(
                            page.get_by_role("button", name="edit work", exact=True)
                        ).to_be_focused()
                        assert signatures() == [initial]
                    else:
                        if case == "edit-conflict":
                            assert api.post(
                                "/api/mail/signatures",
                                data={**initial, "body": "newer editor", "revision": 2},
                            ).ok
                        if case == "edit-deleted":
                            assert api.delete("/api/mail/signatures/" + sid).ok
                        state["reject_edit_read"] = case == "edit-read-reject"
                        if case == "edit-offline":
                            page.wait_for_function("()=>navigator.serviceWorker.controller")
                            context.set_offline(True)
                        save(dialog)
                        if case in {
                            "edit-reject",
                            "edit-uncertain",
                            "edit-uncertain-change",
                            "edit-read-reject",
                            "edit-offline",
                            "edit-conflict",
                            "edit-race",
                            "edit-deleted",
                        }:
                            expect(dialog.get_by_role("alert")).to_contain_text(
                                "could not check the saved signature"
                                if case in {"edit-offline", "edit-read-reject"}
                                else "this signature"
                                if case in {"edit-conflict", "edit-deleted"}
                                else "save unconfirmed"
                            )
                            expect(
                                dialog.get_by_role("textbox", name="signature text", exact=True)
                            ).to_have_value(new_body)
                            if case in {"edit-conflict", "edit-race", "edit-deleted"}:
                                save(dialog)
                                expect(dialog.get_by_role("alert")).to_contain_text(
                                    "this signature"
                                )
                                assert len(writes) == (1 if case == "edit-race" else 0)
                                assert signatures() == (
                                    []
                                    if case == "edit-deleted"
                                    else [{**initial, "body": "newer editor", "revision": 2}]
                                )
                                page.keyboard.press("Escape")
                            else:
                                state["block_read"] = False
                                context.set_offline(False)
                                if case == "edit-uncertain-change":
                                    new_body += " changed after uncertainty"
                                    dialog.get_by_role(
                                        "textbox", name="signature text", exact=True
                                    ).fill(new_body)
                                save(dialog)
                        expect(dialog).to_have_count(0)
                        expect(page.locator("#mc-sig-status")).to_have_text("")
                        if case not in {"edit-conflict", "edit-race", "edit-deleted"}:
                            rows = signatures()
                            assert (
                                len(rows) == 1
                                and rows[0]["body"] == new_body
                                and rows[0]["name"] == "updated work"
                            ), rows
                            assert rows[0]["revision"] == (
                                3 if case == "edit-uncertain-change" else 2
                            ), rows
                    expect(page.locator("#mc-html")).to_have_text("message stays unchanged")
                if case.startswith("remove") or case == "workflow":
                    if case == "workflow":
                        page.locator(".mc-sig-chip").focus()
                        page.keyboard.press("Enter")
                        expect(page.locator("#mc-html")).to_contain_text(
                            new_body, use_inner_text=True
                        )
                        assert page.locator("#mc-html updated").count() == 0
                        page.locator("#mc-save").click()
                        expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                        draft = api.get("/api/mail/drafts").json()[0]
                        assert "Eric &lt;updated&gt; &amp; team" in draft["body"]
                    before = page.locator("#mc-html").inner_html()
                    page.get_by_role(
                        "button",
                        name="remove " + ("updated work" if case == "workflow" else name),
                        exact=True,
                    ).focus()
                    page.keyboard.press("Enter")
                    confirm = page.get_by_role("alertdialog")
                    expect(confirm).to_contain_text("text already inserted")
                    if case == "remove-cancel":
                        page.keyboard.press("Escape")
                        expect(confirm).to_have_count(0)
                        expect(
                            page.get_by_role("button", name="remove work", exact=True)
                        ).to_be_focused()
                        assert deletes == [] and signatures() == [initial]
                    else:
                        if case == "remove-offline":
                            page.wait_for_function("()=>navigator.serviceWorker.controller")
                            context.set_offline(True)
                        confirm.get_by_role("button", name="confirm", exact=True).click()
                        if case in {"remove-late", "remove-busy"}:
                            wait_held()
                            if case == "remove-late":
                                page.locator("#mc-close").click()
                                page.get_by_role("alertdialog").get_by_role(
                                    "button", name="confirm", exact=True
                                ).click()
                                page.locator("#mail-compose-btn").click()
                                page.locator("#mc-subj").fill("new composer")
                            else:
                                page.locator("[data-sig-remove]").click(force=True)
                                assert len(deletes) == 1
                                expect(page.locator("[data-sig-remove]")).to_have_attribute(
                                    "aria-disabled", "true"
                                )
                            release()
                        if case in {
                            "remove-reject",
                            "remove-uncertain",
                            "remove-overlap",
                            "remove-reload",
                            "remove-reload-focus",
                            "remove-conflict",
                            "remove-read-late",
                            "remove-offline",
                        }:
                            expect(page.locator("#mc-sig-status")).to_contain_text(
                                "removal unconfirmed"
                            )
                            if case == "remove-overlap":
                                page.get_by_role(
                                    "button", name="remove personal", exact=True
                                ).click(force=True)
                                expect(page.get_by_role("alertdialog")).to_have_count(0)
                                assert len(deletes) == 1
                                expect(
                                    page.get_by_role(
                                        "button", name="retry signature removal", exact=True
                                    )
                                ).to_be_visible()
                            state["block_read"] = False
                            if case == "remove-offline":
                                queue = page.evaluate(
                                    "()=>new Promise((resolve,reject)=>{const c=new MessageChannel();const t=setTimeout(()=>reject(new Error('worker timeout')),5000);c.port1.onmessage=e=>{clearTimeout(t);resolve(e.data)};navigator.serviceWorker.controller.postMessage({type:'alles-outbox-list'},[c.port2])})"
                                )
                                assert queue["ok"] and queue["items"] == []
                                assert signatures() == [initial]
                            context.set_offline(False)
                            if case in {"remove-reload", "remove-reload-focus"}:
                                state["hold_read"] = True
                                page.locator("#mc-sig-retry").focus()
                                page.keyboard.press("Enter")
                                wait_held()
                                if case == "remove-reload-focus":
                                    page.locator("#mc-subj").fill("typed during read")
                                release()
                                expect(page.locator("#mc-sig-status")).to_have_text("")
                                expect(page.locator("#mc-sig-retry")).to_be_hidden()
                                expect(
                                    page.locator(
                                        "#mc-subj"
                                        if case == "remove-reload-focus"
                                        else "#mc-sig-manage"
                                    )
                                ).to_be_focused()
                                expect(page.locator("[data-sig-remove]")).to_have_count(0)
                                assert signatures() == [] and len(deletes) == 1
                            else:
                                page.get_by_role(
                                    "button", name="retry signature removal", exact=True
                                ).click()
                            if case == "remove-overlap":
                                expect(page.locator("#mc-sig-status")).to_have_text(
                                    "signature removed"
                                )
                                assert signatures() == [other]
                                expect(
                                    page.get_by_role("button", name="remove work", exact=True)
                                ).to_have_count(0)
                                page.get_by_role(
                                    "button", name="remove personal", exact=True
                                ).click()
                                page.get_by_role("alertdialog").get_by_role(
                                    "button", name="confirm", exact=True
                                ).click()
                            if case == "remove-read-late":
                                wait_held()
                                state["hold_read"] = True
                                page.locator("#mc-sig-retry").click()
                                for _ in range(150):
                                    if len(held) == 2:
                                        break
                                    page.wait_for_timeout(20)
                                assert len(held) == 2
                                release()
                                expect(page.locator("#mc-sig-status")).to_have_text(
                                    "signature removed"
                                )
                                release()
                                page.evaluate(
                                    "()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))"
                                )
                            if case == "remove-conflict":
                                expect(page.locator("#mc-sig-status")).to_contain_text(
                                    "removal unconfirmed"
                                )
                                assert signatures() == [
                                    {**initial, "body": "newer editor", "revision": 2}
                                ]
                                page.locator("#mc-sig-retry").click()
                                expect(page.locator("#mc-sig-status")).to_have_text("")
                                expect(
                                    page.get_by_role(
                                        "button", name="retry signature removal", exact=True
                                    )
                                ).to_have_count(0)
                                assert len(deletes) == 2 and all(
                                    "expected_revision=1" in url for url in deletes
                                )
                        if case == "remove-late":
                            expect(page.locator("#mc-subj")).to_have_value("new composer")
                            expect(page.locator("#mc-sig-status")).to_have_text("")
                        elif case not in {
                            "remove-conflict",
                            "remove-reload",
                            "remove-reload-focus",
                        }:
                            expect(page.locator("#mc-sig-status")).to_have_text("signature removed")
                            expect(page.locator("[data-sig-remove]")).to_have_count(0)
                            expect(page.locator("#mc-sig-manage")).to_be_focused()
                            assert signatures() == []
                        if case != "remove-late":
                            assert page.locator("#mc-html").inner_html() == before
                    if case == "workflow":
                        assert api.get("/api/mail/drafts").json() == [draft]
                        page.reload(wait_until="networkidle")
                        page.get_by_role("tab", name="mail", exact=True).click()
                        page.locator("#mail-compose-btn").click()
                        manager()
                        expect(page.locator("#mc-sig-manager")).to_contain_text(
                            "no saved signatures"
                        )
                        assert api.get("/api/mail/drafts").json() == [draft]
                assert not errors, errors
                assert not [
                    line
                    for line in console
                    if not any(
                        code in line
                        for code in ["503", "409", "ERR_INTERNET_DISCONNECTED", "Failed to fetch"]
                    )
                ], console
                assert page.evaluate("()=>document.documentElement.scrollWidth <= innerWidth + 1")
                result.update(
                    status="passed",
                    writes=writes,
                    deletes=deletes,
                    page_errors=errors,
                    console_errors=console,
                )
            except Exception as error:
                result.update(
                    error=str(error),
                    traceback=traceback.format_exc(),
                    writes=writes,
                    deletes=deletes,
                    page_errors=errors,
                    console_errors=console,
                )
            finally:
                context.set_offline(False)
                while held:
                    release()
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(row["status"] != "passed" for row in results))
