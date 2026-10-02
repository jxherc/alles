"""Future-only schedules on owned data; controlled transport failures, no SMTP."""

import json
import os
import sys
import time
import traceback
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import retain_fixture_send_delay, seed_mail

base = f"http://127.0.0.1:{os.environ['PORT']}"
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
cases = [
    "lost-reply",
    "failed-reload-retry",
    "cancel-before-create",
    "cancel-lost-reply",
    "cancel-failed-reload",
    "late-queue-new-text",
    "offline",
    "cleanup-failure",
    "stale-draft-cleanup",
    "storage-failure",
    "send-lost-reply-undo",
    "send-failed-reload-retry",
    "send-undo-failure",
    "cancel-claimed-delivery",
    "schedule-timezone",
    "legacy-outbox-quarantine",
    "send-offline",
    "metadata-retry",
    "cancel-before-create-new-text",
    "cancel-queued-new-text",
    "cancel-plain-message",
    "cancel-plain-message-new-editor",
    "cancel-reopened-decline",
    "cleanup-retired-delete",
    "cleanup-canceled-delete",
    "send-store-change-undo",
    "cleanup-canceled-lost-reply",
    "cleanup-keep-lost-reply",
    "send-cancel-claimed-draft",
    "send-cancel-sent-draft",
    "send-cancel-uncertain-draft",
    "newer-saved-draft-cleanup",
    "send-cancel-claimed-cleanup",
    "send-cancel-sent-cleanup",
    "send-cancel-uncertain-cleanup",
    "cleanup-reopen-accepted",
    "cleanup-reopen-late-dialog",
]
if len(sys.argv) > 1:
    cases = [case for case in cases if case in sys.argv[1:]]
assert cases
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    account = seed_mail(api, base)
    assert api.post("/api/setup/dismiss").ok
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            for row in api.get("/api/mail/scheduled").json()["scheduled"]:
                assert api.post("/api/mail/scheduled/" + row["id"] + "/cancel").ok
            for row in api.get("/api/mail/drafts").json():
                assert api.delete("/api/mail/drafts/" + row["id"]).ok
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="allow"
                if case in {"offline", "send-offline", "legacy-outbox-quarantine"}
                else "block",
                reduced_motion="reduce",
                timezone_id="America/Toronto",
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            errors = []
            console = []
            writes = []
            held = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda entry: console.append(entry.text) if entry.type == "error" else None,
            )
            sending = case.startswith("send-")
            endpoint = (
                base
                + ("/api/mail/send-undoable/" if sending else "/api/mail/schedule/")
                + account["id"]
            )
            page.on(
                "request",
                lambda r: (
                    writes.append(r.post_data_json)
                    if r.url == endpoint and r.method == "POST"
                    else None
                ),
            )
            result = {
                "scenario_id": "inbox.outbox." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)
            body = page.locator("#mc-html")
            status = page.locator("#mail-outbox-status")

            def load():
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.wait_for_load_state("networkidle")

            def reload():
                page.once("dialog", lambda dialog: dialog.accept())
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.wait_for_load_state("networkidle")

            def compose():
                page.get_by_role("button", name="compose", exact=True).click()
                expect(body).to_be_visible()
                to = page.locator('.mc-chipfield[data-role="to"] .mc-chip-input')
                to.fill("recipient@example.invalid")
                to.press("Enter")
                page.locator("#mc-subj").fill("owned scheduled message")
                body.fill("exact future message 中文")

            def pick():
                page.locator("#mc-schedule").click()
                page.locator("#mc-sched-date").click()
                page.get_by_role("button", name="next month", exact=True).click()
                page.locator('.dp-day[data-d="15"]').click()

            def rows():
                return api.get("/api/mail/scheduled").json()["scheduled"]

            def hold(route):
                response = route.fetch()
                assert response.ok
                held.append((route, response))

            def held_one():
                limit = time.monotonic() + 7
                while not held and time.monotonic() < limit:
                    page.wait_for_timeout(30)
                assert held, "request was not held"

            def fail(route):
                route.fulfill(status=503, json={"detail": "owned unavailable response"})

            def lost(route):
                response = route.fetch()
                assert response.ok
                route.fulfill(status=503, json={"detail": "owned lost response"})

            def future_send(route):
                payload = route.request.post_data_json
                existing = api.get(
                    "/api/mail/scheduled", params={"request_id": payload["request_id"]}
                ).json()["scheduled"]
                if existing:
                    return route.fetch()
                response = route.fetch(post_data=json.dumps(payload | {"delay": 3600}))
                assert response.ok
                retain_fixture_send_delay(base, response.json()["id"], payload["delay"])
                return response

            def worker_message(message):
                return page.evaluate(
                    """message=>new Promise((resolve,reject)=>{
                    const c=new MessageChannel();const t=setTimeout(()=>reject(new Error('worker timeout')),5000);
                    c.port1.onmessage=e=>{clearTimeout(t);resolve(e.data)};
                    navigator.serviceWorker.controller.postMessage(message,[c.port2]);
                })""",
                    message,
                )

            try:
                if case == "metadata-retry":
                    page.route(base + "/api/mail/scheduled?context=true", fail)
                load()
                if case in {"offline", "send-offline", "legacy-outbox-quarantine"}:
                    page.wait_for_function("()=>navigator.serviceWorker.controller", timeout=15000)
                if case == "metadata-retry":
                    expect(status).to_contain_text("could not check the outbox")
                    page.unroute(base + "/api/mail/scheduled?context=true", fail)
                    page.locator("#mail-outbox-check").focus()
                    page.keyboard.press("Enter")
                    expect(page.locator("#mail-outbox-recovery")).not_to_be_visible()
                    expect(page.locator("#mail-compose-btn")).to_be_focused()
                compose()
                draft = None
                if case in {
                    "cleanup-failure",
                    "stale-draft-cleanup",
                    "cleanup-retired-delete",
                    "cleanup-canceled-delete",
                    "cleanup-canceled-lost-reply",
                    "cleanup-keep-lost-reply",
                    "send-cancel-claimed-draft",
                    "send-cancel-sent-draft",
                    "send-cancel-uncertain-draft",
                    "newer-saved-draft-cleanup",
                    "send-cancel-claimed-cleanup",
                    "send-cancel-sent-cleanup",
                    "send-cancel-uncertain-cleanup",
                    "cleanup-reopen-accepted",
                    "cleanup-reopen-late-dialog",
                }:
                    page.locator("#mc-save").click()
                    expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                    page.wait_for_load_state("networkidle")
                    draft = api.get("/api/mail/drafts").json()[0]
                if not sending:
                    pick()
                if case in {"cleanup-reopen-accepted", "cleanup-reopen-late-dialog"}:
                    page.route(base + "/api/mail/drafts/" + draft["id"] + "?*", hold)
                    late_dialog = case == "cleanup-reopen-late-dialog"
                    if late_dialog:
                        page.route(endpoint, hold)
                    page.locator("#mc-schedule").click()
                    held_one()
                    assert len(writes) == 1 and len(rows()) == 1
                    if late_dialog:
                        body.fill("newer text before opening recovery")
                    else:
                        assert api.get("/api/mail/drafts").json() == []
                    page.locator("#mail-outbox-open").focus()
                    page.keyboard.press("Enter")
                    page.evaluate("()=>new Promise(resolve=>setTimeout(resolve,0))")
                    if late_dialog:
                        expect(page.get_by_role("alertdialog")).to_be_visible()
                        route, response = held.pop()
                        route.fulfill(response=response)
                        held_one()
                        expect(body).to_have_text("newer text before opening recovery")
                    route, response = held.pop()
                    route.fulfill(response=response)
                    expect(page.locator("#mail-outbox-check")).to_have_count(0)
                    if late_dialog:
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                    page.wait_for_load_state("networkidle")
                    assert page.locator("#mc-html").count() == 0, (
                        "cleanup reopened the accepted original as another sendable message"
                    )
                    assert len(writes) == 1 and len(rows()) == 1
                elif case == "cancel-reopened-decline":
                    page.route(endpoint, hold)
                    page.locator("#mc-schedule").click()
                    held_one()
                    identity = writes[0]["request_id"]
                    url = base + "/api/mail/scheduled/" + identity + "/cancel?*"
                    page.route(url, fail)
                    page.locator("#mail-outbox-cancel").click()
                    expect(status).to_contain_text("cancellation unconfirmed")
                    page.locator("#mail-outbox-open").click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="confirm", exact=True
                    ).click()
                    expect(body).to_have_text("exact future message 中文")
                    body.fill("new text after reopening pending message")
                    page.unroute(url, fail)
                    page.locator("#mail-outbox-cancel").click()
                    expect(status).to_contain_text("delivery canceled")
                    page.locator("#mail-outbox-open").click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="cancel", exact=True
                    ).click()
                    expect(page.get_by_role("alertdialog")).not_to_be_visible()
                    page.evaluate("()=>new Promise(resolve=>setTimeout(resolve,0))")
                    assert page.locator("#mail-outbox-open").count() == 1, (
                        "declining replacement discarded canceled original"
                    )
                    assert page.evaluate(
                        "()=>Object.keys(sessionStorage).some(k=>k.startsWith('alles-mail-outbox:'))"
                    )
                    expect(body).to_have_text("new text after reopening pending message")
                    route, response = held.pop()
                    route.fulfill(response=response)
                    page.locator("#mail-outbox-open").click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="confirm", exact=True
                    ).click()
                    expect(body).to_have_text("exact future message 中文")
                    page.locator("#mc-save").click()
                    expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                    assert (
                        api.get("/api/mail/drafts").json()[0]["body"] == "exact future message 中文"
                    )
                elif case in {
                    "send-cancel-claimed-draft",
                    "send-cancel-sent-draft",
                    "send-cancel-uncertain-draft",
                    "send-cancel-claimed-cleanup",
                    "send-cancel-sent-cleanup",
                    "send-cancel-uncertain-cleanup",
                }:

                    def held_send(route):
                        response = future_send(route)
                        held.append((route, response))

                    page.route(endpoint, held_send)
                    page.locator("#mc-send").click()
                    held_one()
                    identity = writes[0]["request_id"]
                    claimed_state = (
                        "sending"
                        if case.startswith("send-cancel-claimed-")
                        else ("sent" if case.startswith("send-cancel-sent-") else "uncertain")
                    )
                    cleanup_failure = case.endswith("-cleanup")
                    cleanup_url = base + "/api/mail/drafts/" + draft["id"] + "?*"
                    if cleanup_failure:
                        page.route(cleanup_url, fail)
                    sys.path.insert(0, str(Path.cwd()))
                    from core.database import ScheduledMail, SessionLocal

                    with SessionLocal() as db:
                        db.get(ScheduledMail, identity).status = claimed_state
                        db.commit()
                    try:
                        page.locator("#mail-outbox-cancel").click()
                        expect(status).to_contain_text(
                            "could not remove the saved draft"
                            if cleanup_failure
                            else "could not cancel"
                        )
                        assert page.locator("#mc-html").count() == 0, (
                            "accepted original remains sendable after cancellation lost"
                        )
                        if cleanup_failure:
                            assert page.locator("#mail-outbox-finish").count() == 1, (
                                "failed cancellation hides draft cleanup retry"
                            )
                            assert page.locator("#mail-outbox-keep-draft").count() == 1, (
                                "failed cancellation hides keeping the saved draft"
                            )
                        else:
                            assert api.get("/api/mail/drafts").json() == [], (
                                "accepted delivery skipped saved draft cleanup"
                            )
                        route, response = held.pop()
                        route.fulfill(response=response)
                        page.wait_for_load_state("networkidle")
                        assert page.locator("#mc-html").count() == 0
                        if cleanup_failure:
                            with page.expect_response(
                                lambda reply: (
                                    reply.request.method == "DELETE"
                                    and "/api/mail/drafts/" in reply.url
                                )
                            ) as cleanup_reply:
                                page.locator("#mail-outbox-finish").focus()
                                page.keyboard.press("Enter")
                            assert cleanup_reply.value.status == 503
                            expect(status).to_contain_text("could not remove the saved draft")
                            page.wait_for_load_state("networkidle")
                            assert api.get("/api/mail/drafts").json() == [draft]
                            if claimed_state == "sent":
                                page.unroute(cleanup_url, fail)
                                page.locator("#mail-outbox-finish").click()
                                expect(page.locator("#mail-outbox-check")).to_have_count(0)
                                assert api.get("/api/mail/drafts").json() == []
                            else:
                                page.locator("#mail-outbox-keep-draft").focus()
                                page.keyboard.press("Enter")
                                expect(page.locator("#mail-outbox-check")).to_have_count(0)
                                assert api.get("/api/mail/drafts").json() == [draft]
                            assert not page.evaluate(
                                "()=>Object.keys(sessionStorage).some(k=>k.startsWith('alles-mail-outbox:'))"
                            )
                            compose()
                            expect(page.locator("#mc-send")).to_have_attribute(
                                "aria-disabled", "false"
                            )
                            expect(page.locator("#mc-schedule")).to_have_attribute(
                                "aria-disabled", "false"
                            )
                        assert len(writes) == 1
                        current = api.get(
                            "/api/mail/scheduled", params={"request_id": identity}
                        ).json()["scheduled"][0]
                        assert (
                            current["status"] == claimed_state
                            and current["body"] == "exact future message 中文"
                        )
                    finally:
                        with SessionLocal() as db:
                            db.get(ScheduledMail, identity).status = "canceled"
                            db.commit()
                elif case == "send-store-change-undo":
                    page.route(endpoint, lambda route: route.fulfill(response=future_send(route)))
                    page.locator("#mc-send").click()
                    expect(page.locator("#mail-undo-btn")).to_be_visible()
                    stale_undo = page.locator("#mail-undo-btn").element_handle()
                    original = rows()[0]
                    cancel_requests = []

                    def unexpected_cancel(route):
                        cancel_requests.append(route.request.url)
                        route.fulfill(json={"ok": True, "status": "canceled"})

                    page.route(base + "/api/mail/scheduled/*/cancel?*", unexpected_cancel)
                    page.route(
                        base + "/api/mail/scheduled?context=true",
                        lambda route: route.fulfill(
                            json={"scheduled": [], "recovery_scopes": ["f" * 64]}
                        ),
                    )
                    page.locator("#mail-refresh-btn").click()
                    expect(page.locator(".mail-sched-chip")).to_have_count(0)
                    page.wait_for_load_state("networkidle")
                    stale_undo.evaluate("button=>button.click()")
                    page.wait_for_load_state("networkidle")
                    assert cancel_requests == [], (
                        "old undo sent a cancellation in the new mail store"
                    )
                    assert page.locator("#mail-undo-btn").count() == 0
                    assert rows() == [original]
                elif case in {
                    "cleanup-retired-delete",
                    "cleanup-canceled-delete",
                    "cleanup-canceled-lost-reply",
                    "cleanup-keep-lost-reply",
                }:
                    cleanup_responses = []
                    page.on(
                        "response",
                        lambda response: (
                            cleanup_responses.append(response.status)
                            if response.request.method == "DELETE"
                            and "/api/mail/drafts/" in response.url
                            else None
                        ),
                    )
                    page.route(endpoint, hold)
                    url = base + "/api/mail/drafts/" + draft["id"] + "?*"
                    page.route(url, hold)
                    page.locator("#mc-schedule").click()
                    held_one()
                    body.fill("newer draft text survives cleanup")
                    route, response = held.pop()
                    route.fulfill(response=response)
                    held_one()
                    assert api.get("/api/mail/drafts").json() == []
                    page.unroute(url, hold)
                    if case == "cleanup-keep-lost-reply":
                        route, response = held.pop()
                        route.fulfill(status=503, json={"detail": "owned lost cleanup reply"})
                        expect(status).to_contain_text("could not remove the saved draft")
                        page.locator("#mail-outbox-keep-draft").click()
                        expect(page.locator("#mail-outbox-check")).to_have_count(0)
                    elif case in {"cleanup-canceled-delete", "cleanup-canceled-lost-reply"}:
                        page.locator("#mail-outbox-cancel").click()
                        expect(status).to_contain_text("delivery canceled")
                        page.locator("#mail-outbox-finish").click()
                        expect(page.locator("#mail-outbox-check")).to_have_count(0)
                        assert cleanup_responses == []
                    else:
                        page.locator("#mail-outbox-check").click()
                        expect(page.locator("#mail-outbox-check")).to_have_count(0)
                        assert cleanup_responses == [200], "repeated tombstone cleanup must succeed"
                    if held:
                        route, response = held.pop()
                        if case == "cleanup-canceled-lost-reply":
                            route.fulfill(status=503, json={"detail": "owned lost cleanup reply"})
                        else:
                            route.fulfill(response=response)
                    page.wait_for_load_state("networkidle")
                    expect(body).to_have_text("newer draft text survives cleanup")
                    with page.expect_response(
                        lambda response: (
                            response.url == base + "/api/mail/drafts"
                            and response.request.method == "POST"
                        )
                    ) as saved_reply:
                        page.locator("#mc-save").click()
                    assert saved_reply.value.status == 200, (
                        "newer text still targets the deleted draft"
                    )
                    page.wait_for_load_state("networkidle")
                    expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                    saved = api.get("/api/mail/drafts").json()
                    assert len(saved) == 1 and saved[0]["id"] != draft["id"]
                    assert saved[0]["body"] == "newer draft text survives cleanup"
                elif case in {"cancel-before-create-new-text", "cancel-queued-new-text"}:
                    if case == "cancel-before-create-new-text":
                        page.route(endpoint, lambda route: held.append((route, None)))
                    else:
                        page.route(endpoint, hold)
                    page.locator("#mc-schedule").click()
                    held_one()
                    body.fill("newer editor text must stay")
                    page.locator("#mail-outbox-cancel").click()
                    expect(status).to_contain_text("delivery canceled")
                    expect(body).to_have_text("newer editor text must stay")
                    assert page.locator("#mail-outbox-open").count() == 1, (
                        "cancellation discarded retained original while editor had newer text"
                    )
                    assert page.evaluate(
                        "()=>Object.keys(sessionStorage).some(k=>k.startsWith('alles-mail-outbox:'))"
                    )
                    route, response = held.pop()
                    if response is None:
                        response = route.fetch()
                        assert response.status == 410
                    route.fulfill(response=response)
                    page.wait_for_load_state("networkidle")
                    expect(body).to_have_text("newer editor text must stay")
                    page.locator("#mail-outbox-open").click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="cancel", exact=True
                    ).click()
                    expect(body).to_have_text("newer editor text must stay")
                    page.locator("#mail-outbox-open").click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="confirm", exact=True
                    ).click()
                    expect(body).to_have_text("exact future message 中文")
                    page.locator("#mc-save").click()
                    expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                    assert (
                        api.get("/api/mail/drafts").json()[0]["body"] == "exact future message 中文"
                    )
                elif case in {"cancel-plain-message", "cancel-plain-message-new-editor"}:
                    text = "plain <literal> & 中文\nsecond line"
                    if case == "cancel-plain-message":
                        page.locator("#mc-close").click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                    row = api.post(
                        endpoint,
                        data={
                            "to": "recipient@example.invalid",
                            "subject": "plain message",
                            "body": text,
                            "html": "",
                            "send_at": "2099-01-01T12:00:00",
                        },
                    ).json()
                    page.locator("#mail-refresh-btn").click()
                    page.locator('[data-cancel="' + row["id"] + '"]').click()
                    expect(status).to_contain_text("delivery canceled")
                    if case.endswith("new-editor"):
                        expect(body).to_have_text("exact future message 中文")
                        page.locator("#mail-outbox-open").click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                    expect(body).to_be_visible()
                    assert body.inner_text() == text, (
                        "canceled plain-text body was lost or interpreted as markup"
                    )
                    assert body.locator("literal").count() == 0
                    page.locator("#mc-save").click()
                    expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                    saved = api.get("/api/mail/drafts").json()[0]
                    assert "&lt;literal&gt;" in saved["body"] and "&amp;" in saved["body"]
                elif case == "legacy-outbox-quarantine":
                    original = api.post(
                        endpoint,
                        data={
                            "to": "recipient@example.invalid",
                            "subject": "keep scheduled",
                            "body": "original",
                            "send_at": "2099-01-01T12:00:00",
                        },
                    ).json()
                    entries = [
                        (
                            endpoint,
                            {
                                "to": "recipient@example.invalid",
                                "subject": "old scheduled",
                                "body": "exact",
                                "send_at": "2099-01-02T12:00:00",
                            },
                        ),
                        (
                            base + "/api/mail/send-undoable/unavailable-fixture-account",
                            {"to": "recipient@example.invalid", "delay": 3600},
                        ),
                        (
                            base + "/api/mail/send/unavailable-fixture-account",
                            {"to": "recipient@example.invalid"},
                        ),
                        (base + "/api/mail/scheduled/" + original["id"] + "/cancel", {}),
                    ]
                    page.evaluate(
                        """entries=>new Promise((resolve,reject)=>{
                        const request=indexedDB.open('alles-sync',1);
                        request.onupgradeneeded=()=>request.result.createObjectStore('outbox',{keyPath:'id',autoIncrement:true});
                        request.onerror=()=>reject(request.error);
                        request.onsuccess=()=>{const db=request.result,tx=db.transaction('outbox','readwrite');
                            for(const [url,body] of entries)tx.objectStore('outbox').add({url,method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),ts:1});
                            tx.oncomplete=()=>{db.close();resolve()};tx.onerror=()=>reject(tx.error);
                        };
                    })""",
                        entries,
                    )
                    assert worker_message({"type": "alles-flush"})["ok"]
                    queue = worker_message({"type": "alles-outbox-list"})
                    assert queue["ok"] and len(queue["items"]) == 4
                    assert all(
                        item["blocked_reason"] == "replay_policy_changed" for item in queue["items"]
                    )
                    for item in queue["items"]:
                        assert worker_message({"type": "alles-retry-outbox", "id": item["id"]})[
                            "ok"
                        ]
                    assert rows() == [original] and writes == []
                elif case == "metadata-retry":
                    page.locator("#mc-schedule").click()
                    expect(status).to_contain_text("scheduled for")
                    assert len(rows()) == 1
                elif case in {
                    "send-lost-reply-undo",
                    "send-failed-reload-retry",
                    "send-undo-failure",
                }:

                    def send(route):
                        response = future_send(route)
                        if case == "send-lost-reply-undo":
                            route.fulfill(status=503, json={"detail": "owned lost send response"})
                        else:
                            route.fulfill(response=response)

                    page.route(endpoint, fail if case == "send-failed-reload-retry" else send)
                    page.locator("#mc-send").click()
                    if case == "send-failed-reload-retry":
                        expect(status).to_contain_text("unconfirmed")
                        original = writes[0]
                        reload()
                        page.unroute(endpoint, fail)
                        page.route(endpoint, send)
                        page.locator("#mail-outbox-retry").click()
                    expect(page.locator("#mail-undo-btn")).to_be_visible()
                    assert len(rows()) == 1
                    row = rows()[0]
                    assert row["request_delay"] == 8 and row["id"] == writes[0]["request_id"]
                    if case == "send-failed-reload-retry":
                        assert writes == [original, original]
                    cancel_url = base + "/api/mail/scheduled/" + row["id"] + "/cancel?*"
                    if case == "send-undo-failure":
                        page.route(cancel_url, fail)
                    page.locator("#mail-undo-btn").focus()
                    page.keyboard.press("Enter")
                    if case == "send-undo-failure":
                        expect(status).to_contain_text("cancellation unconfirmed")
                        assert rows()[0]["status"] == "scheduled"
                        reload()
                        page.unroute(cancel_url, fail)
                        page.locator("#mail-outbox-cancel").click()
                    expect(status).to_contain_text("delivery canceled")
                    expect(body).to_have_text("exact future message 中文")
                    assert rows() == []
                elif case == "cancel-claimed-delivery":
                    page.locator("#mc-schedule").click()
                    expect(status).to_contain_text("scheduled for")
                    row = rows()[0]
                    from core.database import ScheduledMail, SessionLocal

                    with SessionLocal() as db:
                        db.get(ScheduledMail, row["id"]).status = "sending"
                        db.commit()
                    try:
                        page.locator('[data-cancel="' + row["id"] + '"]').click()
                        expect(status).to_contain_text("could not cancel: delivery has started")
                        assert rows()[0]["status"] == "sending"
                        expect(page.locator("[data-cancel]")).to_have_count(0)
                    finally:
                        with SessionLocal() as db:
                            db.get(ScheduledMail, row["id"]).status = "canceled"
                            db.commit()
                elif case == "schedule-timezone":
                    from datetime import datetime, timezone
                    from zoneinfo import ZoneInfo

                    selected = page.locator("#mc-sched-date").evaluate("el=>el.value") + "T09:00"
                    page.locator("#mc-schedule").click()
                    expect(status).to_contain_text("scheduled for")
                    expected = (
                        datetime.fromisoformat(selected)
                        .replace(tzinfo=ZoneInfo("America/Toronto"))
                        .astimezone(timezone.utc)
                    )
                    actual = datetime.fromisoformat(rows()[0]["send_at"]).replace(
                        tzinfo=timezone.utc
                    )
                    assert expected == actual
                    expect(page.locator(".mail-sched-chip")).to_contain_text("09:00")
                elif case == "lost-reply":
                    page.route(endpoint, lost)
                    page.locator("#mc-schedule").click()
                    expect(status).to_contain_text("scheduled for")
                    expect(body).not_to_be_visible()
                    assert len(rows()) == 1
                    assert len(writes) == 1
                    reload()
                    assert len(rows()) == 1
                    expect(page.locator(".mail-sched-chip")).to_contain_text(
                        "owned scheduled message"
                    )
                elif case == "failed-reload-retry":
                    page.route(endpoint, fail)
                    page.locator("#mc-schedule").click()
                    expect(status).to_contain_text("unconfirmed")
                    assert rows() == []
                    original = writes[0]
                    body.fill("later unsaved typing")
                    reload()
                    page.unroute(endpoint, fail)
                    expect(status).to_contain_text("unconfirmed")
                    page.locator("#mail-outbox-open").click()
                    expect(body).to_have_text("exact future message 中文")
                    page.locator("#mail-outbox-retry").focus()
                    page.keyboard.press("Enter")
                    expect(status).to_contain_text("scheduled for")
                    assert len(rows()) == 1
                    assert writes == [original, original]
                elif case == "cancel-before-create":
                    page.route(endpoint, lambda route: held.append((route, None)))
                    page.locator("#mc-schedule").click()
                    held_one()
                    identity = writes[0]["request_id"]
                    page.locator("#mail-outbox-cancel").click()
                    expect(status).to_contain_text("delivery canceled")
                    expect(body).to_have_text("exact future message 中文")
                    route, _ = held.pop()
                    response = route.fetch()
                    assert response.status == 410
                    route.fulfill(response=response)
                    page.wait_for_load_state("networkidle")
                    current = api.get(
                        "/api/mail/scheduled", params={"request_id": identity}
                    ).json()["scheduled"][0]
                    assert (
                        current["status"] == "canceled"
                        and current["request_kind"] == "canceled-before-queue"
                    )
                    assert rows() == []
                    expect(body).to_have_text("exact future message 中文")
                elif case in {"cancel-lost-reply", "cancel-failed-reload"}:
                    page.locator("#mc-schedule").click()
                    expect(status).to_contain_text("scheduled for")
                    row = rows()[0]
                    url = base + "/api/mail/scheduled/" + row["id"] + "/cancel?*"
                    handler = lost if case == "cancel-lost-reply" else fail
                    page.route(url, handler)
                    page.locator('[data-cancel="' + row["id"] + '"]').click()
                    if case == "cancel-failed-reload":
                        expect(status).to_contain_text("cancellation unconfirmed")
                        assert rows()[0]["status"] == "scheduled"
                        reload()
                        page.unroute(url, handler)
                        page.locator("#mail-outbox-cancel").click()
                    expect(status).to_contain_text("delivery canceled")
                    expect(body).to_have_text("exact future message 中文")
                    assert rows() == []
                elif case == "late-queue-new-text":
                    page.route(endpoint, hold)
                    page.locator("#mc-schedule").click()
                    held_one()
                    body.fill("newer text stays dirty")
                    page.locator("#mail-refresh-btn").click()
                    expect(status).to_contain_text("scheduled for")
                    expect(body).to_have_text("newer text stays dirty")
                    route, response = held.pop()
                    route.fulfill(response=response)
                    page.wait_for_load_state("networkidle")
                    expect(body).to_have_text("newer text stays dirty")
                    assert len(rows()) == 1
                elif case in {"offline", "send-offline"}:
                    context.set_offline(True)
                    page.locator("#mc-send" if sending else "#mc-schedule").click()
                    expect(status).to_contain_text("could not check")
                    queued = page.evaluate(
                        """()=>new Promise((resolve,reject)=>{const c=new MessageChannel();const t=setTimeout(()=>reject(new Error('worker timeout')),5000);c.port1.onmessage=e=>{clearTimeout(t);resolve(e.data)};navigator.serviceWorker.controller.postMessage({type:'alles-outbox-list'},[c.port2]);})"""
                    )
                    assert queued["ok"] and queued["items"] == []
                    assert rows() == []
                elif case == "cleanup-failure":
                    url = base + "/api/mail/drafts/" + draft["id"] + "?*"
                    page.route(url, fail)
                    page.locator("#mc-schedule").click()
                    expect(status).to_contain_text("could not remove the saved draft")
                    assert len(rows()) == 1
                    assert len(api.get("/api/mail/drafts").json()) == 1
                    page.unroute(url, fail)
                    page.locator("#mail-outbox-finish").click()
                    expect(page.locator("#mail-outbox-finish")).to_have_count(0)
                    assert api.get("/api/mail/drafts").json() == []
                    assert len(writes) == 1
                elif case == "newer-saved-draft-cleanup":
                    page.route(endpoint, hold)
                    page.locator("#mc-schedule").click()
                    held_one()
                    body.fill("newer saved draft text")
                    with page.expect_response(
                        lambda response: (
                            response.url == base + "/api/mail/drafts"
                            and response.request.method == "POST"
                        )
                    ) as saved_reply:
                        page.locator("#mc-save").click()
                    assert saved_reply.value.status == 200
                    page.wait_for_function(
                        "()=>document.querySelector('#mc-save')?.getAttribute('aria-disabled')==='false'"
                    )
                    current = api.get("/api/mail/drafts").json()[0]
                    assert current["id"] == draft["id"] and current["revision"] != draft["revision"]
                    route, response = held.pop()
                    route.fulfill(response=response)
                    expect(status).to_contain_text("changed and was kept")
                    expect(body).to_have_text("newer saved draft text")
                    body.fill("later edit to the newer saved version")
                    with page.expect_response(
                        lambda response: (
                            response.url == base + "/api/mail/drafts"
                            and response.request.method == "POST"
                        )
                    ) as saved_reply:
                        page.locator("#mc-save").click()
                    assert saved_reply.value.status == 200
                    saved = api.get("/api/mail/drafts").json()
                    assert len(saved) == 1 and saved[0]["id"] == draft["id"]
                    assert saved[0]["body"] == "later edit to the newer saved version"
                elif case == "stale-draft-cleanup":
                    page.route(endpoint, hold)
                    page.locator("#mc-schedule").click()
                    held_one()
                    changed = api.post(
                        "/api/mail/drafts",
                        data=draft | {"subject": "newer saved draft", "body": "newer saved text"},
                    )
                    assert changed.ok
                    route, response = held.pop()
                    route.fulfill(response=response)
                    expect(status).to_contain_text("changed and was kept")
                    current = api.get("/api/mail/drafts").json()[0]
                    assert current["body"] == "newer saved text" and current["id"] == draft["id"]
                    assert len(rows()) == 1
                elif case == "storage-failure":
                    page.evaluate(
                        """()=>{const set=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k.startsWith('alles-mail-outbox:'))throw new Error('owned quota');return set.call(this,k,v)}}"""
                    )
                    page.locator("#mc-schedule").click()
                    expect(status).to_contain_text("could not retain")
                    assert writes == [] and rows() == []
                    expect(body).to_have_text("exact future message 中文")
                assert not errors, errors
                unexpected = [
                    line
                    for line in console
                    if not any(
                        text in line
                        for text in [
                            "503",
                            "409",
                            "404",
                            "410",
                            "ERR_INTERNET_DISCONNECTED",
                            "Failed to fetch",
                            "Service Worker registration blocked",
                        ]
                    )
                ]
                assert not unexpected, unexpected
                assert page.evaluate("()=>document.documentElement.scrollWidth <= innerWidth+1")
                for button in page.locator(
                    "#mail-outbox-recovery button, .mail-sched-cancel"
                ).all():
                    if button.is_visible():
                        assert button.bounding_box()["height"] >= 44
                result.update(
                    status="passed",
                    write_count=len(writes),
                    page_errors=errors,
                    console_errors=console,
                )
            except Exception as error:
                result.update(
                    error=str(error),
                    traceback=traceback.format_exc(),
                    page_errors=errors,
                    console_errors=console,
                )
            finally:
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                for row in rows():
                    assert api.post("/api/mail/scheduled/" + row["id"] + "/cancel").ok
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
