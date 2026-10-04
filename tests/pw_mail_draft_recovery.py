"""Draft write recovery on owned records; never sends mail."""

import json
import os
import re
import sys
import time
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail

base = f"http://127.0.0.1:{os.environ['PORT']}"
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
cases = [
    "create-keyboard-reload",
    "failed-create-reload",
    "lost-reply-reload",
    "late-save-new-input",
    "stale-update-copy",
    "stale-delete",
    "deleted-pending-create",
    "changed-store",
    "storage-failure",
    "cleanup-failure",
    "offline-save",
    "empty-draft-signature",
    "confirmed-late-ack",
    "confirmed-new-save-old-ack",
    "recovery-without-account",
    "metadata-recovery-focus",
    "unreadable-recovery",
    "reply-fields-reload",
    "confirmed-new-save-old-error",
    "legacy-outbox-quarantine",
    "changed-store-pending-ack",
    "pre-save-read-cannot-confirm",
    "partial-storage-keeps-editor",
    "changed-pending-ack",
    "deleted-pending-ack",
    "failed-create-stalled-read",
    "failed-update-stalled-read",
    "successful-save-stalled-read",
]
if len(sys.argv) > 1:
    cases = [x for x in cases if x in sys.argv[1:]]
assert cases
records = []
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    account = seed_mail(api, base)
    assert api.post("/api/setup/dismiss").ok
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            for row in api.get("/api/mail/drafts").json():
                assert api.delete("/api/mail/drafts/" + row["id"]).ok
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="allow"
                if case in {"offline-save", "legacy-outbox-quarantine"}
                else "block",
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            errors = []
            console = []
            writes = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on(
                "console", lambda item: console.append(item.text) if item.type == "error" else None
            )
            page.on(
                "request",
                lambda r: (
                    writes.append(r.post_data_json)
                    if r.url == base + "/api/mail/drafts" and r.method == "POST"
                    else None
                ),
            )
            result = {
                "scenario_id": "inbox.draft-save." + case,
                "profile": str(width),
                "status": "failed",
            }
            records.append(result)
            body = page.locator("#mc-html")
            status = page.locator("#mail-draft-status")
            bar = page.locator("#mail-draft-recovery")
            endpoint = base + "/api/mail/drafts"
            metadata = endpoint + "?context=true"

            def rows():
                return api.get(endpoint).json()

            def compose(text="owned frozen draft 中文"):
                page.get_by_role("button", name="compose", exact=True).click()
                expect(body).to_be_visible()
                body.fill(text)
                page.locator("#mc-subj").fill("owned draft")

            def loaded():
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.wait_for_load_state("networkidle")

            def reload():
                page.once("dialog", lambda d: d.accept())
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.wait_for_load_state("networkidle")

            def wait_held(held):
                end = time.monotonic() + 5
                while not held and time.monotonic() < end:
                    page.wait_for_timeout(20)
                assert len(held) == 1

            def saved():
                expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                if page.locator("#mc-save").count():
                    expect(page.locator("#mc-save")).to_have_attribute("aria-disabled", "false")

            def open_row(row):
                page.get_by_role("button", name="drafts", exact=True).click()
                page.locator(f'.mail-draft-row[data-id="{row["id"]}"] .mail-open').click()
                expect(body).to_be_visible()

            def fail(route):
                route.fulfill(status=503, json={"detail": "owned draft outage"})

            def worker_message(message):
                return page.evaluate(
                    """message => new Promise((resolve, reject) => {
                    const channel = new MessageChannel();
                    const timeout = setTimeout(() => reject(new Error('outbox check timed out')), 5000);
                    channel.port1.onmessage = event => { clearTimeout(timeout); resolve(event.data); };
                    navigator.serviceWorker.controller.postMessage(message, [channel.port2]);
                })""",
                    message,
                )

            try:
                if case == "metadata-recovery-focus":
                    page.route(metadata, fail)
                loaded()
                if case in {
                    "failed-create-stalled-read",
                    "failed-update-stalled-read",
                    "successful-save-stalled-read",
                }:
                    if case == "failed-update-stalled-read":
                        original = api.post(
                            endpoint,
                            data={
                                "account_id": account["id"],
                                "subject": "owned failed update",
                                "body": "original",
                            },
                        ).json()
                        open_row(original)
                        body.fill("pending update")
                    else:
                        page.get_by_role("button", name="drafts", exact=True).click()
                        page.wait_for_load_state("networkidle")
                        compose("pending create")
                    held = []
                    seen = {"value": False}
                    page.evaluate("""() => {
                        const real=window.fetch;let count=0;window.__oldRecoveryReturned=false;
                        window.fetch=async(...args)=>{
                            const first=String(args[0])==='/api/mail/drafts?context=true' && ++count===1;
                            const response=await real(...args);
                            if(first){const json=response.json.bind(response);response.json=async()=>{
                                const value=await json();setTimeout(()=>window.__oldRecoveryReturned=true,0);return value;
                            }}return response;
                        };
                    }""")

                    def stalled_read(route):
                        if seen["value"]:
                            route.continue_()
                            return
                        seen["value"] = True
                        response = route.fetch()
                        held.append((route, response))

                    page.route(metadata, stalled_read)
                    if case != "successful-save-stalled-read":
                        page.route(endpoint, fail)
                    page.locator("#mc-save").click()
                    wait_held(held)
                    if case != "successful-save-stalled-read":
                        page.locator("#mail-refresh-btn").click()
                    expect(page.locator("#mail-draft-retry")).to_have_attribute(
                        "aria-disabled", "false"
                    )
                    page.unroute(endpoint, fail)
                    page.locator("#mail-draft-retry").click()
                    saved()
                    assert len(rows()) == 1 and rows()[0]["body"] == (
                        "pending update"
                        if case == "failed-update-stalled-read"
                        else "pending create"
                    )
                    if case == "failed-update-stalled-read":
                        assert rows()[0]["id"] == original["id"]
                    route, response = held.pop()
                    route.fulfill(response=response)
                    page.wait_for_function("window.__oldRecoveryReturned")
                    expect(bar).to_be_hidden()
                    page.locator("#mc-close").click()
                    expect(page.get_by_role("alertdialog")).to_have_count(0)
                elif case == "pre-save-read-cannot-confirm":
                    original = api.post(
                        endpoint,
                        data={
                            "account_id": account["id"],
                            "subject": "owned stale read",
                            "body": "version A",
                        },
                    ).json()
                    open_row(original)
                    held_reads = []
                    held_posts = []
                    seen = {"read": False}
                    page.evaluate("""() => {
                        const real=window.fetch;let count=0;window.__oldReadReturned=false;
                        window.fetch=async(...args)=>{
                            const first=String(args[0])==='/api/mail/drafts?context=true' && ++count===1;
                            const response=await real(...args);
                            if(first){const json=response.json.bind(response);response.json=async()=>{
                                const value=await json();setTimeout(()=>window.__oldReadReturned=true,0);return value;
                            }}return response;
                        };
                    }""")

                    def hold_read(route):
                        if seen["read"]:
                            route.continue_()
                            return
                        seen["read"] = True
                        response = route.fetch()
                        held_reads.append((route, response))

                    def hold_post(route):
                        response = route.fetch()
                        assert response.status == 409
                        held_posts.append((route, response))

                    page.route(metadata, hold_read)
                    page.locator("#mail-refresh-btn").click()
                    wait_held(held_reads)
                    changed = api.post(endpoint, data={**original, "body": "version B"}).json()
                    page.route(endpoint, hold_post)
                    page.locator("#mc-save").click()
                    wait_held(held_posts)
                    route, response = held_reads.pop()
                    route.fulfill(response=response)
                    page.wait_for_function("window.__oldReadReturned")
                    assert (
                        page.evaluate(
                            "() => Object.keys(sessionStorage).filter(k=>k.startsWith('alles-mail-draft:')).length"
                        )
                        == 1
                    ), "older read falsely cleared pending save"
                    assert rows() == [changed]
                    route, response = held_posts.pop()
                    route.fulfill(response=response)
                    expect(page.locator("#mail-draft-copy")).to_have_attribute(
                        "aria-disabled", "false"
                    )
                elif case == "partial-storage-keeps-editor":
                    compose()
                    page.evaluate("""() => {
                        const real=Storage.prototype.getItem;let fail=true;
                        Storage.prototype.getItem=function(k){if(fail && k.startsWith('alles-mail-draft:')){fail=false;throw Error('owned verification failure')}return real.call(this,k)};
                    }""")
                    page.locator("#mc-save").click()
                    expect(status).to_contain_text("no save was sent")
                    assert writes == []
                    page.locator("#mail-draft-load-retry").click()
                    page.locator("#mail-draft-retry").click()
                    saved()
                    first = rows()[0]
                    body.fill("next edit after partial storage failure")
                    page.locator("#mc-save").click()
                    saved()
                    assert len(rows()) == 1 and rows()[0]["id"] == first["id"], rows()
                    assert rows()[0]["body"] == "next edit after partial storage failure"
                elif case in {"changed-pending-ack", "deleted-pending-ack"}:
                    original = api.post(
                        endpoint,
                        data={
                            "account_id": account["id"],
                            "subject": "owned pending",
                            "body": "original",
                        },
                    ).json()
                    open_row(original)
                    body.fill("pending content")
                    held = []
                    seen = {"post": False}
                    page.evaluate("""() => {
                        const real=window.fetch;let count=0;window.__oldPostReturned=false;
                        window.fetch=async(...args)=>{
                            const first=String(args[0])==='/api/mail/drafts' && args[1]?.method==='POST' && ++count===1;
                            const response=await real(...args);
                            if(first){const json=response.json.bind(response);response.json=async()=>{
                                const value=await json();setTimeout(()=>window.__oldPostReturned=true,0);return value;
                            }}return response;
                        };
                    }""")

                    def hold_first_post(route):
                        if seen["post"]:
                            route.continue_()
                            return
                        seen["post"] = True
                        response = route.fetch()
                        assert response.ok
                        held.append((route, response))

                    page.route(endpoint, hold_first_post)
                    page.locator("#mc-save").click()
                    wait_held(held)
                    if case == "changed-pending-ack":
                        newer = api.post(
                            endpoint, data={**rows()[0], "body": "other saved version"}
                        ).json()
                    else:
                        assert api.delete(endpoint + "/" + original["id"]).ok
                    page.locator("#mail-refresh-btn").click()
                    expect(page.locator("#mail-draft-copy")).to_have_attribute(
                        "aria-disabled", "false"
                    )
                    expect(status).not_to_have_text("saving draft…")
                    page.locator("#mail-draft-copy").click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="confirm", exact=True
                    ).click()
                    saved()
                    route, response = held.pop()
                    route.fulfill(response=response)
                    page.wait_for_function("window.__oldPostReturned")
                    values = rows()
                    copies = [r for r in values if r["id"] != original["id"]]
                    assert len(copies) == 1 and copies[0]["body"] == "pending content"
                    if case == "changed-pending-ack":
                        assert api.get(endpoint + "/" + original["id"]).json() == newer
                    else:
                        assert len(values) == 1
                    page.locator("#mc-close").click()
                    expect(page.get_by_role("alertdialog")).to_have_count(0)
                elif case == "metadata-recovery-focus":
                    expect(status).to_contain_text("could not load draft recovery")
                    compose()
                    expect(page.locator("#mc-save")).to_have_attribute("aria-disabled", "true")
                    assert writes == []
                    retry = page.locator("#mail-draft-load-retry")
                    retry.focus()
                    page.keyboard.press("Enter")
                    expect(retry).to_be_focused()
                    expect(status).to_contain_text("could not load draft recovery")
                    page.unroute(metadata, fail)
                    page.keyboard.press("Enter")
                    expect(bar).to_be_hidden()
                    expect(page.locator("#mc-save")).to_be_focused()
                    page.keyboard.press("Enter")
                    saved()
                    assert len(rows()) == 1
                elif case == "unreadable-recovery":
                    scope = api.get(metadata).json()["recovery_scopes"][0]
                    page.evaluate(
                        "scope => sessionStorage.setItem('alles-mail-draft:'+scope, '{broken')",
                        scope,
                    )
                    reload()
                    expect(status).to_contain_text("could not read draft recovery data")
                    page.locator("#mail-draft-clear").click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="cancel", exact=True
                    ).click()
                    expect(status).to_contain_text("could not read draft recovery data")
                    page.locator("#mail-draft-clear").click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="confirm", exact=True
                    ).click()
                    expect(bar).to_be_hidden()
                    assert writes == [] and rows() == []
                    compose()
                    page.locator("#mc-save").click()
                    saved()
                elif case == "reply-fields-reload":
                    original = api.post(
                        endpoint,
                        data={
                            "account_id": account["id"],
                            "to": "recipient@example.invalid",
                            "cc": "copy@example.invalid",
                            "bcc": "private@example.invalid",
                            "subject": "re: owned reply 中文",
                            "body": "<p>original</p>",
                            "in_reply_to": "<owned-message@example.invalid>",
                            "references": "<parent@example.invalid> <owned-message@example.invalid>",
                        },
                    ).json()
                    open_row(original)
                    body.fill("exact reply 中文")
                    page.locator('#mc-richbar [data-cmd="bold"]').click()
                    body.press("End")
                    body.press("X")
                    page.route(endpoint, fail)
                    page.locator("#mc-save").click()
                    expect(page.get_by_text("save unconfirmed", exact=True).last).to_be_visible()
                    pending = writes[0]
                    assert "<b>" in pending["body"] or "<strong>" in pending["body"], pending
                    reload()
                    page.locator("#mail-draft-pending").click()
                    expect(body).to_contain_text("exact reply 中文")
                    page.unroute(endpoint, fail)
                    page.locator("#mc-save").click()
                    saved()
                    assert writes[-1] == pending
                    stored = rows()
                    assert len(stored) == 1
                    for field in [
                        "account_id",
                        "to",
                        "cc",
                        "bcc",
                        "subject",
                        "body",
                        "in_reply_to",
                        "references",
                    ]:
                        assert stored[0][field] == pending[field], field
                elif case == "legacy-outbox-quarantine":
                    page.wait_for_function(
                        "() => navigator.serviceWorker?.controller", timeout=15000
                    )
                    original = api.post(
                        endpoint, data={"subject": "keep saved draft", "body": "owned exact body"}
                    ).json()
                    page.evaluate(
                        """rows => new Promise((resolve, reject) => {
                        const request = indexedDB.open('alles-sync', 1);
                        request.onupgradeneeded = () => request.result.createObjectStore('outbox', {keyPath:'id', autoIncrement:true});
                        request.onerror = () => reject(request.error);
                        request.onsuccess = () => {
                            const db=request.result, tx=db.transaction('outbox','readwrite');
                            for(const row of rows) tx.objectStore('outbox').add(row);
                            tx.oncomplete=()=>{db.close();resolve()};tx.onerror=()=>reject(tx.error);
                        };
                    })""",
                        [
                            {
                                "url": endpoint,
                                "method": "POST",
                                "headers": {"content-type": "application/json"},
                                "body": json.dumps({"subject": "old queued create"}),
                                "ts": 1,
                            },
                            {
                                "url": endpoint + "/" + original["id"],
                                "method": "DELETE",
                                "headers": {},
                                "body": "",
                                "ts": 2,
                            },
                        ],
                    )
                    assert worker_message({"type": "alles-flush"})["ok"]
                    queue = worker_message({"type": "alles-outbox-list"})
                    assert queue["ok"] and len(queue["items"]) == 2, queue
                    assert all(
                        item["blocked_reason"] == "replay_policy_changed" for item in queue["items"]
                    )
                    assert rows() == [original] and writes == []
                    for item in queue["items"]:
                        assert worker_message({"type": "alles-retry-outbox", "id": item["id"]})[
                            "ok"
                        ]
                    assert rows() == [original] and writes == []
                elif case == "recovery-without-account":
                    compose()
                    page.route(endpoint, fail)
                    page.locator("#mc-save").click()
                    expect(page.get_by_text("save unconfirmed", exact=True).last).to_be_visible()
                    pending = writes[0]
                    for acct in api.get("/api/mail/accounts").json():
                        assert api.delete("/api/mail/accounts/" + acct["id"]).ok
                    reload()
                    expect(page.locator("#mail-draft-pending")).to_be_visible()
                    page.locator("#mail-draft-pending").click()
                    expect(body).to_have_text("owned frozen draft 中文")
                    replacement = seed_mail(api, base)
                    reload()
                    page.locator("#mail-draft-pending").click()
                    expect(body).to_have_text("owned frozen draft 中文")
                    picker = page.get_by_role("combobox", name="sending account", exact=True)
                    picker.click()
                    page.get_by_role("option", name="Inbox fixture", exact=True).click()
                    page.unroute(endpoint, fail)
                    page.locator("#mc-save").click()
                    saved()
                    assert rows()[0]["account_id"] == pending["account_id"]
                    page.locator("#mc-save").click()
                    saved()
                    assert len(rows()) == 1 and rows()[0]["account_id"] == replacement["id"]
                elif case in {
                    "create-keyboard-reload",
                    "late-save-new-input",
                    "cleanup-failure",
                    "storage-failure",
                    "offline-save",
                }:
                    compose()
                    if case == "create-keyboard-reload":
                        page.locator('.mc-chipfield[data-role="to"] .mc-chip-input').fill(
                            "recipient@example.invalid"
                        )
                        page.locator('.mc-chipfield[data-role="to"] .mc-chip-input').press("Enter")
                        page.locator("#mc-save").focus()
                        page.keyboard.press("Enter")
                        saved()
                        first = rows()
                        assert len(first) == 1
                        assert (
                            first[0]["body"] == "owned frozen draft 中文"
                            and first[0]["to"] == "recipient@example.invalid"
                        )
                        assert (
                            writes[0]["request_id"] == first[0]["id"]
                            and writes[0]["recovery_scope"]
                        )
                        reload()
                        open_row(first[0])
                        expect(body).to_have_text("owned frozen draft 中文")
                        body.fill("explicit later edit")
                        page.locator("#mc-save").click()
                        saved()
                        assert len(rows()) == 1 and rows()[0]["body"] == "explicit later edit"
                        assert writes[-1]["expected_revision"]
                    elif case == "late-save-new-input":
                        held = []

                        def hold(route):
                            response = route.fetch()
                            assert response.ok
                            held.append((route, response))

                        page.route(endpoint, hold)
                        page.locator("#mc-save").click()
                        wait_held(held)
                        body.fill("later editor input")
                        route, response = held.pop()
                        route.fulfill(response=response)
                        saved()
                        expect(body).to_have_text("later editor input")
                        assert rows()[0]["body"] == "owned frozen draft 中文"
                        page.locator("#mc-close").click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="cancel", exact=True
                        ).click()
                        page.unroute(endpoint, hold)
                        page.locator("#mc-save").click()
                        saved()
                        assert len(rows()) == 1 and rows()[0]["body"] == "later editor input"
                    elif case == "storage-failure":
                        page.evaluate(
                            "() => {window.__draftSet=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k.startsWith('alles-mail-draft:'))throw Error('owned storage failure');return window.__draftSet.call(this,k,v)}}"
                        )
                        page.locator("#mc-save").click()
                        expect(status).to_contain_text("no save was sent")
                        assert writes == [] and rows() == []
                        page.evaluate("() => {Storage.prototype.setItem=window.__draftSet}")
                        page.locator("#mail-draft-load-retry").click()
                        expect(bar).to_be_hidden()
                        page.locator("#mc-save").click()
                        saved()
                        assert len(rows()) == 1
                    elif case == "cleanup-failure":
                        page.evaluate(
                            "() => {window.__draftRemove=Storage.prototype.removeItem;Storage.prototype.removeItem=function(k){if(k.startsWith('alles-mail-draft:'))throw Error('owned cleanup failure');return window.__draftRemove.call(this,k)}}"
                        )
                        page.locator("#mc-save").click()
                        expect(status).to_contain_text("recovery data could not be cleared")
                        assert len(writes) == 1 and len(rows()) == 1
                        expect(page.locator("#mc-save")).to_have_attribute("aria-disabled", "true")
                        page.locator("#mc-save").focus()
                        page.keyboard.press("Enter")
                        assert len(writes) == 1
                        page.evaluate("() => {Storage.prototype.removeItem=window.__draftRemove}")
                        page.locator("#mail-draft-cleanup").click()
                        expect(page.locator("#mail-draft-cleanup")).to_have_count(0)
                        reload()
                        assert len(rows()) == 1 and len(writes) == 1
                    else:
                        page.wait_for_function(
                            "() => navigator.serviceWorker?.controller", timeout=15000
                        )
                        context.set_offline(True)
                        page.locator("#mc-save").click()
                        expect(
                            page.get_by_text("save unconfirmed", exact=True).last
                        ).to_be_visible()
                        queued = worker_message({"type": "alles-outbox-list"})
                        assert queued["ok"] and queued["items"] == [], queued
                        context.set_offline(False)
                        page.locator("#mail-draft-load-retry").click()
                        expect(page.locator("#mail-draft-retry")).to_have_attribute(
                            "aria-disabled", "false"
                        )
                        assert rows() == []
                        page.locator("#mail-draft-retry").click()
                        saved()
                        assert len(rows()) == 1
                elif case in {
                    "failed-create-reload",
                    "lost-reply-reload",
                    "deleted-pending-create",
                    "changed-store",
                }:
                    compose()
                    block = {"value": False}

                    def context_read(route):
                        if block["value"]:
                            fail(route)
                        else:
                            route.continue_()

                    def lose(route):
                        if case != "failed-create-reload":
                            response = route.fetch()
                            assert response.ok
                        block["value"] = case != "failed-create-reload"
                        fail(route)

                    page.route(metadata, context_read)
                    page.route(endpoint, lose)
                    page.locator("#mc-save").click()
                    expect(page.get_by_text("save unconfirmed", exact=True).last).to_be_visible()
                    if block["value"]:
                        expect(status).to_contain_text("could not load draft recovery")
                    else:
                        expect(page.locator("#mail-draft-retry")).to_have_attribute(
                            "aria-disabled", "false"
                        )
                    pending = writes[0]
                    assert pending["request_id"] and pending["recovery_scope"]
                    if case == "changed-store":
                        page.unroute(metadata, context_read)
                        page.route(
                            metadata,
                            lambda route: route.fulfill(
                                json={"drafts": [], "recovery_scopes": ["f" * 64]}
                            ),
                        )
                        page.locator("#mail-draft-load-retry").click()
                        expect(page.locator("#mc-status")).to_contain_text("different mail store")
                        expect(page.locator("#mc-save")).to_have_attribute("aria-disabled", "true")
                        page.locator("#mc-save").focus()
                        page.keyboard.press("Enter")
                        assert len(writes) == 1
                        page.unroute(metadata)
                        page.unroute(endpoint, lose)
                        page.get_by_role("button", name="drafts", exact=True).click()
                        saved()
                        assert len(rows()) == 1
                    elif case == "deleted-pending-create":
                        assert api.delete(endpoint + "/" + pending["request_id"]).ok
                        block["value"] = False
                        page.unroute(endpoint, lose)
                        page.locator("#mail-draft-load-retry").click()
                        page.locator("#mail-draft-retry").click()
                        expect(page.locator("#mail-draft-copy")).to_be_visible()
                        assert rows() == []
                        page.locator("#mail-draft-copy").click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                        saved()
                        assert len(rows()) == 1 and rows()[0]["id"] != pending["request_id"]
                    else:
                        block["value"] = False
                        page.unroute(endpoint, lose)
                        reload()
                        if case == "failed-create-reload":
                            expect(page.locator("#mail-draft-pending")).to_be_visible()
                            page.locator("#mail-draft-pending").click()
                            expect(body).to_have_text("owned frozen draft 中文")
                            page.locator("#mc-save").click()
                            saved()
                            assert writes[-1] == pending
                        else:
                            expect(page.locator("#mail-draft-pending")).to_have_count(0)
                        assert (
                            len(rows()) == 1
                            and rows()[0]["id"] == pending["request_id"]
                            and rows()[0]["body"] == "owned frozen draft 中文"
                        )
                elif case in {"stale-update-copy", "stale-delete", "empty-draft-signature"}:
                    initial = api.post(
                        endpoint,
                        data={
                            "account_id": account["id"],
                            "subject": "owned existing",
                            "body": ""
                            if case == "empty-draft-signature"
                            else "original saved body",
                        },
                    ).json()
                    if case == "empty-draft-signature":

                        def signatures(route):
                            response = route.fetch()
                            data = response.json()
                            data["mail_signature"] = "Owned default signature"
                            route.fulfill(response=response, json=data)

                        page.route(base + "/api/settings", signatures)
                        open_row(initial)
                        expect(body).to_have_text("")
                        page.locator("#mc-close").click()
                        expect(page.get_by_role("alertdialog")).to_have_count(0)
                    else:
                        open_row(initial)
                        later = api.post(
                            endpoint, data={**initial, "body": "newer saved version"}
                        ).json()
                        if case == "stale-delete":
                            page.get_by_role("button", name=re.compile(r"^delete draft: ")).click()
                            expect(
                                page.get_by_text(
                                    "this draft has changed; refresh before deleting it", exact=True
                                ).last
                            ).to_be_visible()
                            assert rows() == [later]
                            expect(body).to_have_text("original saved body")
                        else:
                            body.fill("my pending version")
                            page.locator("#mc-save").click()
                            expect(page.locator("#mail-draft-copy")).to_be_visible()
                            assert rows() == [later]
                            expect(body).to_have_text("my pending version")
                            page.locator("#mail-draft-current").click()
                            page.get_by_role("alertdialog").get_by_role(
                                "button", name="confirm", exact=True
                            ).click()
                            expect(body).to_have_text("newer saved version")
                            page.locator("#mail-draft-copy").click()
                            page.get_by_role("alertdialog").get_by_role(
                                "button", name="confirm", exact=True
                            ).click()
                            expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                            values = rows()
                            assert len(values) == 2
                            assert api.get(endpoint + "/" + initial["id"]).json() == later
                            assert any(r["body"] == "my pending version" for r in values)
                            expect(body).to_have_text("newer saved version")
                else:
                    compose()
                    held = []
                    seen = {"value": False}
                    page.evaluate("""() => {
                        const real = window.fetch;
                        let count=0;
                        window.__firstDraftReturned=false;
                        window.fetch=async(...args)=>{
                            const first=String(args[0])==='/api/mail/drafts' && args[1]?.method==='POST' && ++count===1;
                            const response=await real(...args);
                            if(first){const json=response.json.bind(response);response.json=async()=>{
                                const value=await json();setTimeout(()=>window.__firstDraftReturned=true,0);return value;
                            }}
                            return response;
                        };
                    }""")

                    def hold_ack(route):
                        if seen["value"]:
                            route.continue_()
                            return
                        seen["value"] = True
                        response = route.fetch()
                        assert response.ok
                        held.append((route, response))

                    page.route(endpoint, hold_ack)
                    page.locator("#mc-save").click()
                    wait_held(held)
                    first = rows()[0]
                    if case == "changed-store-pending-ack":
                        page.route(
                            metadata,
                            lambda route: route.fulfill(
                                json={"drafts": [], "recovery_scopes": ["f" * 64]}
                            ),
                        )
                        page.get_by_role("button", name="drafts", exact=True).click()
                        expect(page.locator("#mc-status")).to_contain_text("different mail store")
                        page.get_by_role("button", name="compose", exact=True).click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                        expect(body).to_have_text("")
                        expect(page.locator("#mc-save")).to_have_attribute("aria-disabled", "false")
                        route, response = held.pop()
                        route.fulfill(response=response)
                        page.wait_for_function("window.__firstDraftReturned")
                        expect(body).to_have_text("")
                        expect(page.locator("#mc-save")).to_have_attribute("aria-disabled", "false")
                        assert len(writes) == 1 and rows() == [first]
                        assert (
                            page.evaluate(
                                "() => Object.keys(sessionStorage).filter(key=>key.startsWith('alles-mail-draft:')).length"
                            )
                            == 1
                        )
                    else:
                        page.get_by_role("button", name="drafts", exact=True).click()
                        expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                        if case in {"confirmed-new-save-old-ack", "confirmed-new-save-old-error"}:
                            expect(page.locator("#mc-save")).to_have_attribute(
                                "aria-disabled", "false"
                            )
                            body.fill("second save before old acknowledgement")
                            page.locator("#mc-save").click()
                            saved()
                            assert rows()[0]["body"] == "second save before old acknowledgement"
                            route, response = held.pop()
                            if case == "confirmed-new-save-old-error":
                                route.fulfill(
                                    status=410, json={"detail": "owned delayed deleted reply"}
                                )
                            else:
                                route.fulfill(response=response)
                            page.wait_for_function("window.__firstDraftReturned")
                            expect(body).to_have_text("second save before old acknowledgement")
                            page.locator("#mc-close").click()
                            expect(page.get_by_role("alertdialog")).to_have_count(0)
                            assert (
                                len(rows()) == 1
                                and rows()[0]["body"] == "second save before old acknowledgement"
                            )
                        else:
                            assert api.delete(endpoint + "/" + first["id"]).ok
                            page.locator("#mail-refresh-btn").click()
                            expect(page.locator(".mail-draft-row")).to_have_count(0)
                            route, response = held.pop()
                            route.fulfill(response=response)
                            page.wait_for_function("window.__firstDraftReturned")
                            expect(page.locator("#mc-save")).to_have_text("save as new draft")
                            expect(body).to_have_text("owned frozen draft 中文")
                            page.locator("#mc-close").click()
                            expect(page.get_by_role("alertdialog")).to_be_visible()
                            page.get_by_role("alertdialog").get_by_role(
                                "button", name="cancel", exact=True
                            ).click()
                            assert rows() == []
                assert not errors, errors
                unexpected = [
                    line
                    for line in console
                    if not any(
                        marker in line
                        for marker in [
                            "503 (Service Unavailable)",
                            "409 (Conflict)",
                            "410 (Gone)",
                        ]
                    )
                    and not (
                        case == "offline-save"
                        and ("ERR_INTERNET_DISCONNECTED" in line or "Failed to fetch" in line)
                    )
                ]
                assert not unexpected, unexpected
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1")
                for button in bar.locator("button:visible").all():
                    box = button.bounding_box()
                    assert box["width"] >= 43.5 and box["height"] >= 43.5, box
                result["status"] = "passed"
            except Exception as error:
                result.update(error=str(error), page_errors=errors, console=console)
            finally:
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(records, indent=2))
                if case == "recovery-without-account":
                    for acct in api.get("/api/mail/accounts").json():
                        assert api.delete("/api/mail/accounts/" + acct["id"]).ok
                    account = seed_mail(api, base)
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in records))
