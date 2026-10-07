"""Reviewed Inbox acceptance, retry after reload, and linked Plan/source recovery.

Mail reads and model output are controlled fixtures. Acceptance, task/calendar
reads and edits use the real server and disposable database.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_mail_calendar_capture import ModelReply


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    results = []
    model = ThreadingHTTPServer(("127.0.0.1", 0), ModelReply)
    thread = threading.Thread(target=model.serve_forever, daemon=True)
    thread.start()
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from core.database import MailAccount, ModelEndpoint, SessionLocal

        with SessionLocal() as db:
            account = MailAccount(name="capture fixture", email="me@example.invalid")
            db.add(account)
            db.add(
                ModelEndpoint(
                    name="local capture",
                    base_url=f"http://127.0.0.1:{model.server_port}/v1",
                    cached_models='["fixture-model"]',
                    enabled=True,
                )
            )
            db.commit()
            aid = account.id
        mail = {
            "uid": "701",
            "account_id": aid,
            "message_id": "<planning@fixture.invalid>",
            "from": "Teammate <teammate@example.invalid>",
            "to": "me@example.invalid",
            "subject": "Planning from mail",
            "text": "Meet today at 11. Bring the plan.\nKeep this exact source.",
            "html": "",
            "date": date.today().isoformat(),
            "date_ts": time.time(),
            "seen": True,
        }
        original_mail = dict(mail)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            api = pw.request.new_context(base_url=base)
            assert api.post("/api/setup/dismiss").ok
            for width in [1440, 390]:
                for kind in ["task", "event"]:
                    mail.update(original_mail)
                    context = browser.new_context(
                        viewport={"width": width, "height": 900},
                        timezone_id="UTC",
                        reduced_motion="reduce",
                        service_workers="block",
                    )
                    page = context.new_page()
                    page.set_default_timeout(8000)
                    errors, console = [], []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda msg: console.append(msg.text) if msg.type == "error" else None,
                    )
                    page.route(
                        "**/api/mail/inbox/**",
                        lambda route: route.fulfill(json={"messages": [mail]}),
                    )
                    page.route("**/api/mail/message/**", lambda route: route.fulfill(json=mail))
                    page.route(
                        "**/api/mail/attachments/**",
                        lambda route: route.fulfill(json={"attachments": []}),
                    )
                    page.route(
                        "**/api/mail/seen/**", lambda route: route.fulfill(json={"ok": True})
                    )
                    endpoint = "/api/tasks" if kind == "task" else "/api/calendar"
                    button = "#mail-to-task" if kind == "task" else "#mail-to-cal"
                    profile = f"{kind}-{width}"

                    def record(name, **extra):
                        results.append(
                            {
                                "scenario_id": "inbox.capture." + name,
                                "profile": profile,
                                "status": "passed",
                                **extra,
                            }
                        )
                        (out / "scenarios.json").write_text(json.dumps(results, indent=2))

                    def open_mail():
                        page.goto(base + "/?view=mail", wait_until="networkidle")
                        page.get_by_role("button", name="Planning from mail", exact=True).click()
                        expect(page.locator(button)).to_be_visible()

                    try:
                        open_mail()
                        before = len(api.get(endpoint).json())
                        page.locator(button).focus()
                        page.locator(button).press("Enter")
                        expect(page.locator(".capture-review")).to_be_visible()
                        expect(page.locator("#capture-open")).to_be_hidden()
                        assert len(api.get(endpoint).json()) == before
                        original_title = page.locator("#capture-title").input_value()
                        page.locator("#capture-title").fill("")
                        page.locator("#capture-accept").click()
                        expect(page.locator(".capture-status")).to_have_text("add a title")
                        expect(page.locator("#capture-title")).to_be_focused()
                        assert len(api.get(endpoint).json()) == before
                        page.locator("#capture-title").fill(original_title)
                        record("invalid-title-keeps-correction-focus")
                        if kind == "event":
                            initial_start = page.locator("#capture-start").evaluate(
                                "el => el.value"
                            )
                            page.locator("#capture-start").evaluate("el => { el.value = ''; }")
                            page.locator("#capture-accept").click()
                            expect(page.locator(".capture-status")).to_contain_text("valid start")
                            assert page.locator("#capture-start").evaluate(
                                "el => el === document.activeElement || el.contains(document.activeElement)"
                            )
                            assert len(api.get(endpoint).json()) == before
                            page.locator("#capture-start").evaluate(
                                "(el, value) => { el.value = value; }", initial_start
                            )
                            record("invalid-date-keeps-correction-focus")
                            aware_times = {
                                "start": "2032-06-20T13:00:00Z",
                                "end": "2032-06-20T15:00:00Z",
                            }
                            original_times = page.evaluate(
                                "[document.getElementById('capture-start').value, document.getElementById('capture-end').value]"
                            )
                            page.locator("#capture-all-day").click()
                            page.locator("#capture-all-day").click()
                            assert (
                                page.evaluate(
                                    "[document.getElementById('capture-start').value, document.getElementById('capture-end').value]"
                                )
                                == original_times
                            )
                            record("all-day-round-trip-keeps-duration")
                        page.locator("#capture-title").fill("cancelled proposal")
                        page.locator("#capture-cancel").click()
                        expect(page.locator(".capture-review")).to_have_count(0)
                        assert len(api.get(endpoint).json()) == before
                        expect(page.locator(button)).to_be_focused()
                        record("review-and-cancel")

                        page.locator(button).click()
                        expect(page.locator(".capture-review")).to_be_visible()
                        title = "accepted " + profile
                        page.locator("#capture-title").fill(title)
                        page.locator("#capture-notes").fill("my reviewed notes")
                        if kind == "task":
                            page.locator("#capture-project").fill("school")
                            page.locator("#capture-due").evaluate(
                                "el => { el.value = '2032-06-21'; }"
                            )
                        page.screenshot(path=str(out / f"{profile}-review.png"), full_page=True)
                        sent = []

                        def lose_response(route):
                            if route.request.method != "POST":
                                route.continue_()
                                return
                            response = route.fetch()
                            assert response.ok, response.text()
                            sent.append(
                                {"body": route.request.post_data_json, "saved": response.json()}
                            )
                            route.fulfill(
                                status=503, json={"detail": "synthetic lost acceptance response"}
                            )

                        page.route(base + endpoint, lose_response)
                        page.locator("#capture-accept").click()
                        expect(page.locator(".capture-status")).to_contain_text(
                            "will not add a duplicate"
                        )
                        expect(page.locator(".capture-fields")).to_have_attribute("inert", "")
                        assert len(sent) == 1
                        saved = sent[0]["saved"]
                        assert saved["title"] == title
                        assert len(api.get(endpoint).json()) == before + 1
                        page.unroute(base + endpoint, lose_response)
                        for rejected_status in [401, 403, 400, 422]:

                            def reject_retry(route):
                                if route.request.method == "POST":
                                    route.fulfill(
                                        status=rejected_status,
                                        json={"detail": "synthetic retry rejection"},
                                    )
                                else:
                                    route.continue_()

                            page.route(base + endpoint, reject_retry)
                            page.locator("#capture-accept").click()
                            expect(page.locator(".capture-status")).to_contain_text(
                                "synthetic retry rejection"
                            )
                            expect(page.locator("#capture-accept")).to_have_text(
                                "retry confirmation"
                            )
                            expect(page.locator(".capture-fields")).to_have_attribute("inert", "")
                            page.unroute(base + endpoint, reject_retry)
                        record("rejected-retries-preserve-uncertain-identity")
                        page.reload(wait_until="networkidle")
                        page.get_by_role(
                            "button", name="review pending capture", exact=True
                        ).click()
                        expect(page.locator("#capture-accept")).to_have_text("retry confirmation")
                        with page.expect_response(base + endpoint) as retry:
                            page.locator("#capture-accept").click()
                        assert retry.value.ok, retry.value.text()
                        assert retry.value.request.post_data_json == sent[0]["body"]
                        assert retry.value.json()["id"] == saved["id"]
                        assert len(api.get(endpoint).json()) == before + 1
                        expect(page.locator(".capture-status")).to_contain_text("saved in plan")
                        record("lost-response-reload-and-retry", target_id=saved["id"])

                        page.locator("#capture-open").click()
                        title_selector = "#te-title" if kind == "task" else "#cal-title"
                        source_button = "#te-source" if kind == "task" else "#cal-source"
                        expect(page.locator(title_selector)).to_have_value(title)
                        expect(page.locator(source_button)).to_be_visible()
                        assert "record=" + saved["id"] in page.url
                        page.screenshot(path=str(out / f"{profile}-plan.png"), full_page=True)
                        record("open-exact-plan-record")
                        page.locator(title_selector).fill(title + " edited")
                        if kind == "task":
                            page.locator("#te-due").fill("2032-06-22")
                            page.locator("#te-notes").fill("edited notes")
                            save_button = "#te-save"
                        else:
                            page.locator("#cal-start").evaluate(
                                "el => { el.value = '2032-06-22T13:00'; }"
                            )
                            page.locator("#cal-end").evaluate(
                                "el => { el.value = '2032-06-22T14:00'; }"
                            )
                            save_button = "#cal-save"
                        with page.expect_response(
                            lambda response: (
                                response.url.split("?")[0] == base + endpoint + "/" + saved["id"]
                                and response.request.method == "PATCH"
                            )
                        ) as edited:
                            page.locator(save_button).click()
                        assert edited.value.ok, edited.value.text()
                        current = edited.value.json()
                        assert current["source"] == saved["source"]
                        assert current["title"] == title + " edited"
                        assert (
                            current["due_date"] if kind == "task" else current["start_dt"]
                        ).startswith("2032-06-22")
                        page.reload(wait_until="networkidle")
                        expect(page.locator(title_selector)).to_have_value(title + " edited")
                        record("edit-reschedule-and-reload")
                        source_state = {"status": 200}

                        def source_reply(route):
                            if source_state["status"] == 200:
                                route.fulfill(json={"source": saved["source"], "message": mail})
                            else:
                                route.fulfill(
                                    status=source_state["status"],
                                    json={
                                        "detail": {
                                            "message": "source message changed",
                                            "source": saved["source"],
                                        }
                                    },
                                )

                        page.route("**/api/mail/source/**", source_reply)
                        page.locator(source_button).click()
                        expect(page.locator(".mail-reader-subject")).to_have_text(mail["subject"])
                        expect(page.locator(".mail-body-text")).to_have_text(mail["text"])
                        assert "record_view=mail" in page.url
                        page.reload(wait_until="networkidle")
                        expect(page.locator(".mail-body-text")).to_have_text(mail["text"])
                        record(
                            "original-source-link-and-reload",
                            boundary="controlled source read; server identity validation covered by API tests",
                        )
                        source_state["status"] = 409
                        page.reload(wait_until="networkidle")
                        expect(page.locator(".mail-source-error")).to_contain_text(
                            "source message changed"
                        )
                        expect(page.locator(".mail-source-error pre")).to_have_text(mail["text"])
                        expect(page.locator(".mail-reader")).to_have_count(0)
                        page.screenshot(
                            path=str(out / f"{profile}-source-error.png"), full_page=True
                        )
                        source_state["status"] = 200
                        page.get_by_role(
                            "button", name="retry original message", exact=True
                        ).click()
                        expect(page.locator(".mail-body-text")).to_have_text(mail["text"])
                        record("changed-source-retained-excerpt-and-retry")
                        if kind == "task":
                            page.goto(base + "/?view=tasks", wait_until="networkidle")
                            with page.expect_response(
                                lambda response: (
                                    response.url == base + endpoint + "/" + saved["id"]
                                    and response.request.method == "PATCH"
                                )
                            ) as completed:
                                page.locator(f'.task-check[data-id="{saved["id"]}"]').click()
                            assert completed.value.ok, completed.value.text()
                            assert completed.value.json()["done"]
                            page.goto(
                                base + "/?view=tasks&record_view=tasks&record=" + saved["id"],
                                wait_until="networkidle",
                            )
                            expect(page.locator("#te-title")).to_have_value(title + " edited")
                            expect(page.locator("#te-source")).to_be_visible()
                            page.locator("#te-cancel").click()
                            record("complete-and-open-history")

                        open_mail()
                        page.locator(button).click()
                        expect(page.locator(".capture-review")).to_be_visible()
                        page.evaluate(
                            """() => { window._captureStorageSet = Storage.prototype.setItem; Storage.prototype.setItem = function(key, value) { if (key.startsWith('alles.capture.pending.')) throw new Error('storage unavailable'); return window._captureStorageSet.call(this, key, value); }; }"""
                        )
                        count = len(api.get(endpoint).json())
                        page.locator("#capture-accept").click()
                        expect(page.locator(".capture-status")).to_contain_text(
                            "storage unavailable"
                        )
                        assert len(api.get(endpoint).json()) == count
                        expect(page.locator(".capture-fields")).not_to_have_attribute("inert", "")
                        page.evaluate(
                            "() => { Storage.prototype.setItem = window._captureStorageSet; }"
                        )
                        record("storage-failure-keeps-editable-review-without-writing")
                        sent.clear()
                        page.route(base + endpoint, lose_response)
                        page.locator("#capture-accept").click()
                        expect(page.locator(".capture-status")).to_contain_text(
                            "will not add a duplicate"
                        )
                        page.unroute(base + endpoint, lose_response)
                        removed = sent[0]["saved"]["id"]
                        assert api.delete(endpoint + "/" + removed).ok
                        page.locator("#capture-accept").click()
                        expect(page.locator(".capture-status")).to_contain_text("deleted")
                        assert len(api.get(endpoint).json()) == count
                        page.locator("#capture-cancel").click()
                        page.locator("[data-dialog-cancel]").click()
                        expect(page.locator(".capture-review")).to_be_visible()
                        page.locator("#capture-cancel").click()
                        page.locator("[data-dialog-confirm]").click()
                        expect(page.locator(".capture-review")).to_have_count(0)
                        record("deleted-uncertain-target-never-recreated-and-explicit-discard")
                        if kind == "event":

                            def aware_proposal(route):
                                route.fulfill(
                                    json={
                                        "found": True,
                                        "preview": True,
                                        "kind": "event",
                                        "source": saved["source"],
                                        "candidate": {
                                            "title": "aware event",
                                            "start_dt": aware_times["start"],
                                            "end_dt": aware_times["end"],
                                            "all_day": False,
                                            "description": "",
                                            "location": "",
                                        },
                                    }
                                )

                            page.route("**/api/mail/extract-event", aware_proposal)
                            open_mail()
                            page.evaluate(
                                "async () => { const i18n = await import('/static/js/i18n.js'); i18n.configureLocalization({ language: 'en', region: 'CA', timezone: 'America/Toronto' }); }"
                            )
                            page.locator(button).click()
                            expect(page.locator(".capture-review")).to_be_visible()
                            assert (
                                page.locator("#capture-start").evaluate("el => el.value")
                                == "2032-06-20T09:00"
                            )
                            page.locator("#capture-start").evaluate(
                                "el => { el.value = '2032-06-20T10:00'; }"
                            )
                            with page.expect_response(base + endpoint) as aware_saved:
                                page.locator("#capture-accept").click()
                            assert aware_saved.value.ok, aware_saved.value.text()
                            assert (
                                aware_saved.value.json()["start_dt"] == "2032-06-20T14:00:00.000Z"
                            )
                            assert aware_saved.value.json()["end_dt"] == "2032-06-20T15:00:00Z"
                            expect(page.locator(".capture-status")).to_contain_text("saved in plan")
                            page.locator("#capture-cancel").click()
                            page.screenshot(path=str(out / f"{profile}-aware.png"), full_page=True)
                            record("edit-aware-time-in-configured-zone-preserves-other-instant")
                            aware_times.update(
                                start="2026-11-01T05:30:00Z", end="2026-11-01T06:30:00Z"
                            )
                            for variant in ["unchanged", "all-day-round-trip"]:
                                page.locator(button).click()
                                expect(page.locator(".capture-review")).to_be_visible()
                                assert (
                                    page.locator("#capture-start").evaluate("el => el.value")
                                    == "2026-11-01T01:30"
                                )
                                assert (
                                    page.locator("#capture-end").evaluate("el => el.value")
                                    == "2026-11-01T01:30"
                                )
                                if variant == "all-day-round-trip":
                                    page.locator("#capture-all-day").click()
                                    page.locator("#capture-all-day").click()
                                with page.expect_response(base + endpoint) as folded:
                                    page.locator("#capture-accept").click()
                                assert folded.value.ok, folded.value.text()
                                assert folded.value.json()["start_dt"] == aware_times["start"]
                                assert folded.value.json()["end_dt"] == aware_times["end"]
                                expect(page.locator(".capture-status")).to_contain_text(
                                    "saved in plan"
                                )
                                page.screenshot(
                                    path=str(out / f"{profile}-fold-{variant}.png"), full_page=True
                                )
                                page.locator("#capture-cancel").click()
                                record("dst-fold-" + variant)
                            page.unroute("**/api/mail/extract-event", aware_proposal)
                        for cleanup in ("before", "after"):
                            open_mail()
                            page.locator(button).click()
                            expect(page.locator("#capture-accept")).to_be_visible()
                            before = len(api.get(endpoint).json())
                            page.evaluate(
                                """when => {
                                window.__captureRemove = Storage.prototype.removeItem;
                                Storage.prototype.removeItem = function(key) {
                                    if (!key.startsWith('alles.capture.pending.v1:')) return window.__captureRemove.call(this, key);
                                    if (when === 'after') window.__captureRemove.call(this, key);
                                    throw new Error('synthetic cleanup failure');
                                };
                            }""",
                                cleanup,
                            )
                            with page.expect_response(
                                lambda r: r.url == base + endpoint and r.request.method == "POST"
                            ) as confirmed:
                                page.locator("#capture-accept").click()
                            assert confirmed.value.ok, confirmed.value.text()
                            saved = confirmed.value.json()
                            expect(page.locator(".capture-status")).to_contain_text(
                                "saved in plan:"
                            )
                            expect(page.locator("#capture-open")).to_be_focused()
                            page.keyboard.press("Enter")
                            expect(page.locator(source_button)).to_be_visible()
                            assert saved["id"] in page.url
                            assert len(api.get(endpoint).json()) == before + 1
                            page.evaluate(
                                "() => { Storage.prototype.removeItem = window.__captureRemove; }"
                            )
                            if cleanup == "before":
                                open_mail()
                                page.locator(button).click()
                                expect(page.locator(".capture-status")).to_contain_text(
                                    "save has not been confirmed"
                                )
                                with page.expect_response(
                                    lambda r: (
                                        r.url == base + endpoint and r.request.method == "POST"
                                    )
                                ) as repeated:
                                    page.locator("#capture-accept").click()
                                assert repeated.value.json()["id"] == saved["id"]
                                expect(page.locator(".capture-status")).to_contain_text(
                                    "saved in plan:"
                                )
                                page.locator("#capture-cancel").click()
                            assert len(api.get(endpoint).json()) == before + 1
                            record("confirmed-cleanup-" + cleanup)
                        mail.update(
                            text="",
                            html="<head><meta charset=utf-8><title>private-title</title><body><p>Meet <b>today</b> at 11 &amp; bring the plan.</p><script>window.captureSourceExecuted = true;</script>",
                        )
                        open_mail()
                        expect(page.locator(".mail-body-frame")).to_have_attribute("sandbox", "")
                        assert (
                            page.frame_locator(".mail-body-frame")
                            .locator("body")
                            .evaluate("() => window.captureSourceExecuted === undefined")
                        )
                        page.locator(button).click()
                        expect(page.locator(".capture-review")).to_be_visible()
                        page.locator(".capture-source summary").click()
                        excerpt = "Meet today at 11 & bring the plan."
                        expect(page.locator(".capture-source pre")).to_have_text(excerpt)
                        with page.expect_response(base + endpoint) as html_saved:
                            page.locator("#capture-accept").click()
                        assert html_saved.value.ok, html_saved.value.text()
                        saved = html_saved.value.json()
                        assert saved["source"]["excerpt"] == excerpt
                        page.locator("#capture-open").click()
                        expect(page.locator(source_button)).to_be_visible()
                        source_state["status"] = 409
                        page.locator(source_button).click()
                        expect(page.locator(".mail-source-error pre")).to_have_text(excerpt)
                        page.reload(wait_until="networkidle")
                        expect(page.locator(".mail-source-error pre")).to_have_text(excerpt)
                        page.screenshot(
                            path=str(out / f"{profile}-html-source.png"), full_page=True
                        )
                        record("html-only-excerpt-survives-acceptance-and-unavailable-source")
                        # Playwright's service_workers='block' init script reads this forbidden
                        # property inside opaque sandboxed frames; the app runs no script there.
                        tool_error = "Failed to read the 'serviceWorker' property from 'Navigator': Service worker is disabled because the context is sandboxed and lacks the 'allow-same-origin' flag."
                        unexpected_errors = [error for error in errors if error != tool_error]
                        assert not unexpected_errors, unexpected_errors
                        assert all(
                            any(
                                status in entry
                                for status in ("503", "409", "410", "401", "403", "400", "422")
                            )
                            or entry
                            == "Blocked script execution in 'about:srcdoc' because the document's frame is sandboxed and the 'allow-scripts' permission is not set."
                            for entry in console
                        ), console
                        record(
                            "console",
                            expected_console=console,
                            page_errors=unexpected_errors,
                            expected_tool_errors=errors,
                        )
                    except Exception as error:
                        results.append(
                            {
                                "scenario_id": "inbox.capture.failure",
                                "profile": profile,
                                "status": "failed",
                                "error": str(error),
                                "page_errors": errors,
                                "console": console,
                            }
                        )
                        page.screenshot(path=str(out / f"{profile}-failure.png"), full_page=True)
                    finally:
                        (out / "scenarios.json").write_text(json.dumps(results, indent=2))
                        for row in api.get(endpoint).json():
                            api.delete(endpoint + "/" + row["id"])
                        context.close()
            api.dispose()
            browser.close()
    finally:
        model.shutdown()
        model.server_close()
        thread.join(timeout=5)
    assert all(row["status"] == "passed" for row in results), [
        row for row in results if row["status"] != "passed"
    ]


if __name__ == "__main__":
    run()
