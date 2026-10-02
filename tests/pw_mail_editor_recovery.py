"""mail editor workflows on owned local records; never sends mail."""

import base64
import json
import os
import sys
import time
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import retain_fixture_send_delay, seed_mail


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        api = pw.request.new_context(base_url=base)
        account = seed_mail(api, base)
        assert api.post("/api/setup/dismiss").ok
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in [
                "delete-old-read-new-compose",
                "send-late-editor",
                "send-late-edit",
                "schedule-late-editor",
                "schedule-late-edit",
                "delete-reopen",
                "delete-pending-read",
                "message-race",
                "draft-read-race",
                "failed-delete-keeps-edits",
                "folder-keeps-edits",
                "signature-read-race",
                "section-keeps-edits",
                "close-save-reopen",
                "message-cancel-replace",
                "section-history-cancel",
                "delete-late-edit",
                "image-late-new-editor",
                "link-keyboard",
                "signature-repeat",
                "reload-protect",
                "rich-preview",
                "rich-clean-close",
                "account-choice-dirty",
                "current-tab-keeps-editor",
            ]:
                if len(sys.argv) > 1 and case not in sys.argv[1:]:
                    continue
                for draft in api.get("/api/mail/drafts").json():
                    assert api.delete("/api/mail/drafts/" + draft["id"]).ok
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                )
                page = context.new_page()
                page.set_default_timeout(7000)
                errors = []
                console = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on(
                    "console",
                    lambda item: console.append(item.text) if item.type == "error" else None,
                )
                result = {
                    "scenario_id": "inbox.editor." + case,
                    "profile": str(width),
                    "status": "failed",
                }
                records.append(result)
                try:
                    page.goto(base + "/?view=inbox", wait_until="networkidle")
                    page.get_by_role("tab", name="mail", exact=True).click()
                    page.wait_for_load_state("networkidle")
                    body = page.get_by_role("textbox", name="message", exact=True)

                    def compose():
                        page.get_by_role("button", name="compose", exact=True).click()
                        expect(body).to_be_visible()
                        body.fill("owned unsaved reply")

                    def held_one(held):
                        end = time.monotonic() + 5
                        while not held and time.monotonic() < end:
                            page.wait_for_timeout(20)
                        assert len(held) == 1

                    if case == "delete-old-read-new-compose":
                        draft = api.post(
                            "/api/mail/drafts",
                            data={
                                "account_id": account["id"],
                                "subject": "old reading",
                                "body": "old body",
                            },
                        ).json()
                        page.get_by_role("button", name="drafts", exact=True).click()
                        reads = []
                        settings = []

                        def hold_draft(route):
                            response = route.fetch()
                            if route.request.method == "GET":
                                reads.append((route, response))
                            else:
                                route.fulfill(response=response)

                        def hold_settings(route):
                            response = route.fetch()
                            settings.append((route, response))

                        page.evaluate(
                            "() => {const real=window.fetch;window.__newSettingsReturned=false;window.__oldDraftReturned=false;window.fetch=async(...args)=>{const response=await real(...args);const settings=String(args[0])==='/api/settings';const draft=!args[1]?.method && String(args[0]).includes('/api/mail/drafts/');if(settings || draft){const json=response.json.bind(response);response.json=async()=>{const data=await json();setTimeout(()=>{if(settings)window.__newSettingsReturned=true;else window.__oldDraftReturned=true},0);return data}}return response}}"
                        )
                        page.route(base + "/api/mail/drafts/" + draft["id"] + "?*", hold_draft)
                        page.get_by_role("button", name="old reading", exact=True).click()
                        held_one(reads)
                        page.route(base + "/api/settings", hold_settings)
                        page.get_by_role("button", name="compose", exact=True).click()
                        held_one(settings)
                        page.get_by_role("button", name="delete draft", exact=True).click()
                        expect(page.locator(".mail-draft-row")).to_have_count(0)
                        route, response = settings.pop()
                        route.fulfill(response=response)
                        page.wait_for_function("window.__newSettingsReturned === true")
                        try:
                            expect(body).to_be_visible()
                            body.fill("new independent composer")
                        finally:
                            route, response = reads.pop()
                            route.fulfill(response=response)
                        page.wait_for_function("window.__oldDraftReturned === true")
                        expect(body).to_have_text("new independent composer")
                    elif case in {
                        "send-late-editor",
                        "send-late-edit",
                        "schedule-late-editor",
                        "schedule-late-edit",
                    }:
                        scheduling = case.startswith("schedule-")
                        compose()
                        page.locator('.mc-chipfield[data-role="to"] .mc-chip-input').fill(
                            "recipient@example.invalid"
                        )
                        page.locator('.mc-chipfield[data-role="to"] .mc-chip-input').press("Enter")
                        held = []
                        page.evaluate(
                            "() => {const real=window.fetch;window.__sendReturned=false;window.fetch=async(...args)=>{const response=await real(...args);if((String(args[0]).includes('/send-undoable/') || String(args[0]).includes('/schedule/'))){const json=response.json.bind(response);response.json=async()=>{const data=await json();setTimeout(()=>window.__sendReturned=true,0);return data}}return response}}"
                        )

                        def hold_send(route):
                            payload = route.request.post_data_json
                            submitted_delay = payload.get("delay")
                            if not scheduling:
                                payload["delay"] = 3600
                            response = route.fetch(post_data=json.dumps(payload))
                            assert response.ok
                            if not scheduling:
                                retain_fixture_send_delay(
                                    base, response.json()["id"], submitted_delay
                                )
                            held.append((route, response))

                        page.route(
                            base
                            + ("/api/mail/schedule/" if scheduling else "/api/mail/send-undoable/")
                            + account["id"],
                            hold_send,
                        )
                        if scheduling:
                            page.locator("#mc-schedule").click()
                            page.locator("#mc-sched-date").click()
                            page.get_by_role("button", name="next month", exact=True).click()
                            page.locator('.dp-day[data-d="15"]').click()
                        page.locator("#mc-schedule" if scheduling else "#mc-send").click()
                        held_one(held)
                        if case.endswith("-editor"):
                            page.get_by_role("button", name="compose", exact=True).click()
                            page.get_by_role("alertdialog").get_by_role(
                                "button", name="confirm", exact=True
                            ).click()
                            expect(body).to_have_text("")
                        body.fill("newer unsent editor")
                        route, response = held.pop()
                        queued = response.json()
                        try:
                            route.fulfill(response=response)
                            page.wait_for_function("window.__sendReturned === true")
                            expect(body).to_have_text("newer unsent editor")
                            if scheduling:
                                expect(
                                    page.get_by_text("scheduled", exact=True).last
                                ).to_be_visible()
                            else:
                                expect(page.locator("#mail-undo-btn")).to_be_visible()
                                page.locator("#mail-undo-btn").click()
                                expect(page.locator("#mail-undo-bar")).not_to_be_visible()
                                assert queued["id"] not in [
                                    r["id"]
                                    for r in api.get("/api/mail/scheduled").json()["scheduled"]
                                ]
                        finally:
                            assert api.post("/api/mail/scheduled/" + queued["id"] + "/cancel").ok
                    elif case in {"delete-reopen", "delete-pending-read"}:
                        draft = api.post(
                            "/api/mail/drafts",
                            data={
                                "account_id": account["id"],
                                "subject": "owned deletion",
                                "body": "stored body",
                            },
                        ).json()
                        page.get_by_role("button", name="drafts", exact=True).click()
                        held = []
                        reads = []
                        page.evaluate(
                            "() => {const real=window.fetch;window.__draftReadReturned=false;window.fetch=async(...args)=>{const response=await real(...args);if(!args[1]?.method && String(args[0]).includes('/api/mail/drafts/')){const json=response.json.bind(response);response.json=async()=>{const data=await json();setTimeout(()=>window.__draftReadReturned=true,0);return data}}return response}}"
                        )

                        def hold_draft(route):
                            if route.request.method == "DELETE":
                                held.append(route)
                            elif case == "delete-pending-read":
                                response = route.fetch()
                                reads.append((route, response))
                            else:
                                route.continue_()

                        page.route(base + "/api/mail/drafts/" + draft["id"] + "?*", hold_draft)
                        if case == "delete-pending-read":
                            page.get_by_role("button", name="owned deletion", exact=True).click()
                            held_one(reads)
                        page.get_by_role("button", name="delete draft", exact=True).click()
                        held_one(held)
                        if case == "delete-reopen":
                            page.locator(".mail-draft-row .mail-from").click()
                            page.wait_for_function(
                                '() => window.__draftReadReturned || document.querySelector(".mail-open")?.disabled'
                            )
                        route = held.pop()
                        response = route.fetch()
                        assert response.ok
                        route.fulfill(response=response)
                        expect(page.locator(".mail-draft-row")).to_have_count(0)
                        if reads:
                            route, response = reads.pop()
                            route.fulfill(response=response)
                            page.wait_for_function("window.__draftReadReturned === true")
                        expect(body).to_have_count(0)
                        assert api.get("/api/mail/drafts/" + draft["id"]).status == 404
                    elif case == "current-tab-keeps-editor":
                        compose()
                        page.get_by_role("tab", name="mail", exact=True).click()
                        expect(page.get_by_role("alertdialog")).to_have_count(0)
                        expect(body).to_have_text("owned unsaved reply")
                    elif case == "account-choice-dirty":
                        other = api.post(
                            "/api/mail/accounts",
                            data={
                                "name": "Other fixture",
                                "email": "other@example.invalid",
                                "imap_host": "127.0.0.1",
                                "imap_port": account["imap_port"],
                                "smtp_host": "127.0.0.1",
                                "smtp_port": account["smtp_port"],
                                "username": "other fixture",
                                "password": "placeholder",
                                "use_ssl": False,
                            },
                        )
                        assert other.ok
                        other = other.json()
                        try:
                            draft = api.post(
                                "/api/mail/drafts",
                                data={
                                    "account_id": account["id"],
                                    "subject": "account choice",
                                    "body": "saved text",
                                },
                            )
                            assert draft.ok
                            page.reload(wait_until="networkidle")
                            page.get_by_role("tab", name="mail", exact=True).click()
                            page.get_by_role("button", name="drafts", exact=True).click()
                            page.get_by_role("button", name="account choice", exact=True).click()
                            expect(body).to_have_text("saved text")
                            page.locator("#mc-account").click()
                            page.get_by_role("option", name="Other fixture", exact=True).click()
                            page.locator("#mc-close").click()
                            dialog = page.get_by_role("alertdialog")
                            expect(dialog).to_be_visible()
                            dialog.get_by_role("button", name="cancel", exact=True).click()
                            expect(page.locator("#mc-account")).to_have_attribute(
                                "data-value", other["id"]
                            )
                            expect(body).to_have_text("saved text")
                            assert (
                                api.get("/api/mail/drafts/" + draft.json()["id"]).json()[
                                    "account_id"
                                ]
                                == account["id"]
                            )
                        finally:
                            assert api.delete("/api/mail/accounts/" + other["id"]).ok
                    elif case in {"rich-preview", "rich-clean-close"}:
                        markup = (
                            '<p><a href="https://example.invalid/source">project context</a></p>'
                        )
                        response = api.post(
                            "/api/mail/drafts",
                            data={
                                "account_id": account["id"],
                                "subject": "owned rich draft",
                                "body": markup,
                            },
                        )
                        assert response.ok
                        page.get_by_role("button", name="drafts", exact=True).click()
                        if case == "rich-preview":
                            expect(page.locator(".mail-draft-row .mail-snippet")).to_have_text(
                                "project context"
                            )
                        else:
                            page.get_by_role("button", name="owned rich draft", exact=True).click()
                            expect(body.locator("a")).to_have_text("project context")
                            body.locator("a").hover()
                            page.locator("#mc-close").click()
                            expect(body).to_have_count(0)
                            expect(page.get_by_role("alertdialog")).to_have_count(0)
                            assert (
                                api.get("/api/mail/drafts/" + response.json()["id"]).json()["body"]
                                == markup
                            )
                    elif case == "reload-protect":
                        compose()
                        dialogs = []

                        def keep_edits(dialog):
                            dialogs.append(dialog.type)
                            dialog.dismiss()

                        page.on("dialog", keep_edits)
                        try:
                            page.reload(wait_until="domcontentloaded", timeout=2000)
                        except Exception as error:
                            assert dialogs == ["beforeunload"] and (
                                "ERR_ABORTED" in str(error) or "Timeout" in str(error)
                            ), str(error)
                        assert dialogs == ["beforeunload"], (
                            "reload erased unsaved text without a leave decision"
                        )
                        expect(body).to_have_text("owned unsaved reply")
                    elif case == "close-save-reopen":
                        compose()
                        page.get_by_placeholder("subject", exact=True).fill("owned roundtrip")
                        page.locator("#mc-close").click()
                        dialog = page.get_by_role("alertdialog")
                        expect(dialog).to_be_visible()
                        dialog.get_by_role("button", name="cancel", exact=True).click()
                        expect(body).to_have_text("owned unsaved reply")
                        page.locator("#mc-save").click()
                        expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                        page.locator("#mc-close").click()
                        expect(body).to_have_count(0)
                        expect(page.get_by_role("alertdialog")).to_have_count(0)
                        page.get_by_role("button", name="drafts", exact=True).click()
                        page.get_by_role("button", name="owned roundtrip", exact=True).click()
                        expect(body).to_have_text("owned unsaved reply")
                    elif case == "message-cancel-replace":
                        compose()
                        page.route(
                            base + "/api/mail/message/" + account["id"] + "?*",
                            lambda route: route.fulfill(
                                json={
                                    "uid": "702",
                                    "from": "Fixture <fixture@example.invalid>",
                                    "subject": "owned message",
                                    "text": "owned message body",
                                    "html": "",
                                    "to": "me@example.invalid",
                                }
                            ),
                        )
                        target = page.locator('.mail-row[data-uid="702"] .mail-open')
                        target.click()
                        dialog = page.get_by_role("alertdialog")
                        expect(dialog).to_be_visible()
                        dialog.get_by_role("button", name="cancel", exact=True).click()
                        expect(body).to_have_text("owned unsaved reply")
                        target.click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                        expect(page.locator(".mail-reader-subject")).to_have_text("owned message")
                        expect(body).to_have_count(0)
                    elif case == "section-history-cancel":
                        compose()
                        before = page.url
                        page.get_by_role("tab", name="contacts", exact=True).click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                        expect(
                            page.get_by_role("tab", name="contacts", exact=True)
                        ).to_have_attribute("aria-selected", "true")
                        expect(body).to_have_count(0)
                        page.go_back()
                        expect(page.get_by_role("tab", name="mail", exact=True)).to_have_attribute(
                            "aria-selected", "true"
                        )
                        expect(body).to_have_count(0)
                        compose()
                        page.go_forward()
                        dialog = page.get_by_role("alertdialog")
                        expect(dialog).to_be_visible()
                        dialog.get_by_role("button", name="cancel", exact=True).click()
                        expect(page).to_have_url(before)
                        expect(body).to_have_text("owned unsaved reply")
                        expect(body).to_be_visible()
                    elif case == "delete-late-edit":
                        draft = api.post(
                            "/api/mail/drafts",
                            data={
                                "account_id": account["id"],
                                "subject": "owned draft",
                                "body": "old body",
                            },
                        ).json()
                        page.get_by_role("button", name="drafts", exact=True).click()
                        page.get_by_role("button", name="owned draft", exact=True).click()
                        expect(body).to_have_text("old body")
                        held = []

                        def hold_delete(route):
                            response = route.fetch()
                            assert response.ok
                            held.append((route, response))

                        page.route(base + "/api/mail/drafts/" + draft["id"] + "?*", hold_delete)
                        page.get_by_role("button", name="delete draft", exact=True).click()
                        held_one(held)
                        body.fill("later unsaved edit")
                        route, response = held.pop()
                        route.fulfill(response=response)
                        expect(page.locator(".mail-draft-row")).to_have_count(0)
                        expect(body).to_have_text("later unsaved edit")
                        page.locator("#mc-save").click()
                        expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                        rows = api.get("/api/mail/drafts").json()
                        assert (
                            len(rows) == 1
                            and rows[0]["id"] != draft["id"]
                            and rows[0]["body"] == "later unsaved edit"
                        ), rows
                    elif case == "image-late-new-editor":
                        compose()
                        held = []
                        page.evaluate(
                            "() => { const real=window.fetch; window.__uploadReturned=false; window.fetch=async(...args)=>{const response=await real(...args); if(String(args[0])==='/api/uploads'){const json=response.json.bind(response);response.json=async()=>{const data=await json();setTimeout(()=>{window.__uploadReturned=true},0);return data}}return response}; }"
                        )

                        def hold_upload(route):
                            response = route.fetch()
                            assert response.ok
                            held.append((route, response))

                        page.route(base + "/api/uploads", hold_upload)
                        pixel = base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aB3sAAAAASUVORK5CYII="
                        )
                        page.locator("#mc-image-input").set_input_files(
                            {"name": "owned.png", "mimeType": "image/png", "buffer": pixel}
                        )
                        held_one(held)
                        page.get_by_role("button", name="compose", exact=True).click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                        expect(body).to_have_text("")
                        body.fill("newer editor text")
                        body.focus()
                        route, response = held.pop()
                        route.fulfill(response=response)
                        page.wait_for_function("window.__uploadReturned === true")
                        expect(body).to_have_text("newer editor text")
                        expect(body.locator("img")).to_have_count(0)
                        expect(body).to_be_focused()
                    elif case == "link-keyboard":
                        compose()
                        body.fill("owned link")
                        body.focus()
                        body.press("ControlOrMeta+A")
                        page.locator('[data-cmd="createLink"]').focus()
                        page.keyboard.press("Enter")
                        dialog = page.get_by_role("dialog", name="link URL:", exact=True)
                        expect(dialog).to_be_visible()
                        dialog.get_by_role("textbox").fill("https://example.invalid/owned")
                        dialog.get_by_role("button", name="ok", exact=True).click()
                        expect(body.locator("a")).to_have_text("owned link")
                        expect(body.locator("a")).to_have_attribute(
                            "href", "https://example.invalid/owned"
                        )
                        page.get_by_placeholder("subject", exact=True).fill("owned link draft")
                        page.locator("#mc-save").click()
                        expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                        page.locator("#mc-close").click()
                        page.get_by_role("button", name="drafts", exact=True).click()
                        page.get_by_role("button", name="owned link draft", exact=True).click()
                        expect(body.locator("a")).to_have_attribute(
                            "href", "https://example.invalid/owned"
                        )
                    elif case == "signature-repeat":
                        compose()
                        page.locator("#mc-sig-add").click()
                        dialog = page.get_by_role("dialog", name="signature name:", exact=True)
                        dialog.get_by_role("textbox").fill("owned signature")
                        dialog.get_by_role("button", name="ok", exact=True).click()
                        dialog = page.get_by_role("dialog", name="signature text:", exact=True)
                        dialog.get_by_role("textbox").fill("owned signature text")
                        dialog.get_by_role("button", name="ok", exact=True).click()
                        expect(page.locator("#mc-sig-list")).to_contain_text("owned signature")
                        body.fill("bold once")
                        body.focus()
                        body.press("ControlOrMeta+A")
                        page.locator('[data-cmd="bold"]').focus()
                        page.keyboard.press("Enter")
                        expect(body.locator("b,strong")).to_have_text("bold once")
                    elif case == "signature-read-race":
                        held = []

                        def hold_settings(route):
                            response = route.fetch()
                            assert response.ok
                            held.append((route, response))

                        page.route(base + "/api/settings", hold_settings)
                        page.evaluate(
                            "() => { const real = window.fetch; window.__signatureReturned = false; window.fetch = async (...args) => { const response = await real(...args); if (String(args[0]) === '/api/settings') { const json = response.json.bind(response); response.json = async () => { const data = await json(); setTimeout(() => { window.__signatureReturned = true; }, 0); return data; }; } return response; }; }"
                        )
                        page.get_by_role("button", name="compose", exact=True).click()
                        held_one(held)
                        page.route(
                            base + "/api/mail/message/" + account["id"] + "?*",
                            lambda route: route.fulfill(
                                json={
                                    "uid": "702",
                                    "from": "Fixture <fixture@example.invalid>",
                                    "subject": "owned message",
                                    "text": "owned message body",
                                    "html": "",
                                    "to": "me@example.invalid",
                                }
                            ),
                        )
                        page.locator('.mail-row[data-uid="702"] .mail-open').click()
                        expect(page.locator(".mail-reader-subject")).to_have_text("owned message")
                        route, response = held.pop()
                        route.fulfill(response=response)
                        page.wait_for_function("window.__signatureReturned === true")
                        expect(page.locator(".mail-reader-subject")).to_have_text("owned message")
                        expect(body).to_have_count(0)
                    elif case == "section-keeps-edits":
                        compose()
                        page.get_by_role("tab", name="contacts", exact=True).click()
                        dialog = page.get_by_role("alertdialog")
                        expect(dialog).to_be_visible()
                        dialog.get_by_role("button", name="cancel", exact=True).click()
                        expect(body).to_have_text("owned unsaved reply")
                        expect(body).to_be_visible()
                    elif case == "message-race":
                        held = []
                        page.route(
                            base + "/api/mail/message/" + account["id"] + "?*",
                            lambda route: held.append(route),
                        )
                        page.locator('.mail-row[data-uid="702"] .mail-open').click()
                        held_one(held)
                        compose()
                        held.pop().fulfill(
                            json={
                                "uid": "702",
                                "from": "Fixture <fixture@example.invalid>",
                                "subject": "owned message",
                                "text": "owned message body",
                                "html": "",
                                "to": "me@example.invalid",
                            }
                        )
                        page.wait_for_load_state("networkidle")
                        expect(body).to_have_text("owned unsaved reply")
                    elif case == "draft-read-race":
                        draft = api.post(
                            "/api/mail/drafts",
                            data={
                                "account_id": account["id"],
                                "subject": "older draft",
                                "body": "old body",
                            },
                        ).json()
                        page.get_by_role("button", name="drafts", exact=True).click()
                        held = []

                        def hold(route):
                            response = route.fetch()
                            held.append((route, response))

                        page.route(base + "/api/mail/drafts/" + draft["id"] + "?*", hold)
                        page.get_by_role("button", name="older draft", exact=True).click()
                        held_one(held)
                        compose()
                        route, response = held.pop()
                        route.fulfill(response=response)
                        page.wait_for_load_state("networkidle")
                        expect(body).to_have_text("owned unsaved reply")
                    elif case == "failed-delete-keeps-edits":
                        draft = api.post(
                            "/api/mail/drafts",
                            data={
                                "account_id": account["id"],
                                "subject": "owned draft",
                                "body": "old body",
                            },
                        ).json()
                        page.get_by_role("button", name="drafts", exact=True).click()
                        page.get_by_role("button", name="owned draft", exact=True).click()
                        body.fill("owned unsaved reply")
                        page.route(
                            base + "/api/mail/drafts/" + draft["id"] + "?*",
                            lambda route: route.fulfill(
                                status=503, json={"detail": "owned deletion failure"}
                            ),
                        )
                        page.evaluate(
                            "() => { const real = window.fetch; window.__draftDeleteReturned = false; window.fetch = async (...args) => { const response = await real(...args); if (args[1]?.method === 'DELETE' && String(args[0]).includes('/api/mail/drafts/')) setTimeout(() => { window.__draftDeleteReturned = true; }, 0); return response; }; }"
                        )
                        page.get_by_role("button", name="delete draft", exact=True).click()
                        dialog = page.get_by_role("alertdialog")
                        if dialog.is_visible():
                            dialog.get_by_role("button", name="confirm", exact=True).click()
                        page.wait_for_function("window.__draftDeleteReturned === true")
                        page.wait_for_load_state("networkidle")
                        expect(body).to_have_text("owned unsaved reply")
                        assert api.get("/api/mail/drafts/" + draft["id"]).ok
                    else:
                        compose()
                        page.get_by_role("button", name="primary", exact=True).click()
                        dialog = page.get_by_role("alertdialog")
                        if dialog.is_visible():
                            dialog.get_by_role("button", name="cancel", exact=True).click()
                        expect(body).to_have_text("owned unsaved reply")
                    assert not errors, errors
                    assert all("503" in value for value in console), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                        "horizontal overflow"
                    )
                    for button in page.locator("#mail-main .btn:visible").all():
                        box = button.bounding_box()
                        assert box["width"] >= 43.5 and box["height"] >= 43.5, {
                            "text": button.inner_text(),
                            "box": box,
                        }
                    result["status"] = "passed"
                except Exception as error:
                    result.update(error=str(error), page_errors=errors, console=console)
                finally:
                    page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(records, indent=2))
        browser.close()
        api.dispose()
    raise SystemExit(any(r["status"] != "passed" for r in records))


if __name__ == "__main__":
    run()
