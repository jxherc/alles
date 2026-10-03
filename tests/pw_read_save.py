"""Owned URL-save recovery. Loopback fixture URLs take the guarded link-only path."""

import json
import os
import re
import traceback
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 820, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if urlparse(route.request.url).netloc == urlparse(base).netloc
                    else route.abort()
                ),
            )
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            page = context.new_page()
            page.set_default_timeout(7000)
            errors, console, writes = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            endpoint = base + "/api/read"
            page.on(
                "request",
                lambda request: (
                    writes.append(request.post_data_json)
                    if request.method == "POST" and request.url == endpoint
                    else None
                ),
            )
            context.tracing.start(screenshots=True, snapshots=True)

            def record(name):
                rows.append(
                    {
                        "scenario_id": "library.url-save." + name,
                        "profile": str(width),
                        "status": "passed",
                    }
                )
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

            def saved(url):
                return [item for item in api.get(endpoint).json()["items"] if item["url"] == url]

            replies = []

            def lose(route):
                if route.request.method != "POST":
                    route.continue_()
                    return
                response = route.fetch()
                assert response.ok, response.text()
                replies.append(response.json())
                route.fulfill(status=503, json={"detail": "synthetic lost URL response"})

            try:
                page.goto(base + "/?view=read", wait_until="networkidle")
                field, save = page.locator("#read-url"), page.locator("#read-save")
                expect(save).to_be_enabled()
                url = base + f"/synthetic-owned-source?width={width}"
                field.fill(url)
                page.route(endpoint, lose)
                field.press("Enter")
                expect(page.locator("#read-save-error")).to_contain_text("synthetic lost")
                expect(field).to_have_value(url)
                expect(field).to_be_disabled()
                assert len(saved(url)) == 1 and len(writes) == 1
                intent = writes[-1]
                assert intent["request_id"] and intent["recovery_scope"]
                page.unroute(endpoint, lose)
                record("lost-response-keeps-one-record-and-original-intent")
                page.reload(wait_until="networkidle")
                expect(page.locator("#read-save-check")).to_be_visible()
                expect(field).to_have_value(url)
                assert len(writes) == 1
                page.locator("#read-save-check").focus()
                page.keyboard.press("Enter")
                expect(page.locator("#read-save-open")).to_be_focused()
                assert len(writes) == 1 and len(saved(url)) == 1
                expect(field).to_have_value("")
                record("reload-check-confirms-without-another-create")
                page.locator("#read-save-open").click()
                expect(page.locator(".read-article h1")).to_have_text(replies[-1]["title"])
                assert not api.get(endpoint + "/" + replies[-1]["id"]).json()["read"]
                page.locator("#read-back").click()
                expect(field).to_be_visible()
                record("saved-result-opens-exact-unread-item")

                second = base + f"/synthetic-deleted-source?width={width}"
                field.fill(second)
                page.route(endpoint, lose)
                save.click()
                expect(page.locator("#read-save-error")).to_contain_text("synthetic lost")
                deleted = replies[-1]
                original = writes[-1]
                assert api.delete(endpoint + "/" + deleted["id"]).ok
                page.unroute(endpoint, lose)
                page.reload(wait_until="networkidle")
                save.click()
                expect(page.locator("#read-save-error")).to_contain_text("was deleted")
                assert writes[-1] == original and saved(second) == []
                record("deleted-save-retry-does-not-recreate-article")
                page.locator("#read-save-discard").click()
                dialog = page.get_by_role("alertdialog")
                dialog.get_by_role("button", name="cancel", exact=True).click()
                expect(field).to_be_disabled()
                page.locator("#read-save-discard").click()
                dialog.get_by_role("button", name="confirm", exact=True).click()
                expect(field).to_be_focused()
                expect(field).to_have_value("")
                record("discard-cancel-and-confirm-keep-data-unchanged")

                third = base + f"/synthetic-storage-source?width={width}"
                field.fill(third)
                before = len(writes)
                page.evaluate(
                    """() => { window.originalSetItem = Storage.prototype.setItem; Storage.prototype.setItem = function(key, value) { if (key.startsWith('alles.read.pending.v1:')) throw new Error('synthetic blocked browser storage'); return window.originalSetItem.call(this,key,value); }; }"""
                )
                save.click()
                expect(page.locator("#read-save-error")).to_contain_text(
                    "synthetic blocked browser storage"
                )
                expect(field).to_have_value(third)
                assert len(writes) == before and saved(third) == []
                page.evaluate("() => { Storage.prototype.setItem = window.originalSetItem; }")
                record("unavailable-browser-storage-fails-before-create")

                page.route(
                    endpoint,
                    lambda route: (
                        route.fulfill(status=503, json={"detail": "synthetic before-write outage"})
                        if route.request.method == "POST"
                        else route.continue_()
                    ),
                )
                save.click()
                expect(page.locator("#read-save-error")).to_contain_text("synthetic before-write")
                pending = writes[-1]
                page.unroute(endpoint)
                page.locator("#read-save-check").click()
                expect(page.locator("#read-save-error")).to_contain_text("not found")
                expect(field).to_have_value(third)
                save.click()
                expect(page.locator("#read-save-open")).to_be_focused()
                assert writes[-1] == pending and len(saved(third)) == 1
                record("missing-receipt-keeps-intent-and-retry-saves-once")

                fourth = base + f"/synthetic-late-source?width={width}"
                field.fill(fourth)
                held = []
                page.route(
                    endpoint,
                    lambda route: (
                        held.append(route) if route.request.method == "POST" else route.continue_()
                    ),
                )
                save.click()
                expect(save).to_be_disabled()
                page.wait_for_function("document.getElementById('read-save').disabled")
                assert len(held) == 1
                page.get_by_role("tab", name="books", exact=True).click()
                focused = page.evaluate("document.activeElement.textContent")
                response = held[0].fetch()
                assert response.ok
                held[0].fulfill(response=response)
                page.wait_for_timeout(150)
                assert page.evaluate("document.activeElement.textContent") == focused
                page.get_by_role("tab", name="saved", exact=True).click()
                expect(page.locator("#read-save-open")).to_be_visible()
                assert len(saved(fourth)) == 1
                record("late-save-keeps-new-view-and-focus")
                page.unroute(endpoint)
                retired_url = base + f"/synthetic-retired-scope?width={width}"
                field.fill(retired_url)
                page.route(endpoint, lose)
                save.click()
                expect(page.locator("#read-save-error")).to_contain_text("synthetic lost")
                pending_scope = writes[-1]["recovery_scope"]
                accepted_scopes = ["f" * 64, pending_scope]
                page.unroute(endpoint, lose)
                before_rotation = len(writes)

                def scoped_list(route):
                    response = route.fetch()
                    assert response.ok
                    payload = response.json()
                    payload["recovery_scopes"] = list(accepted_scopes)
                    route.fulfill(response=response, json=payload)

                listed = re.compile(re.escape(endpoint) + r"(?:\?.*)?$")
                page.route(listed, scoped_list)
                page.get_by_role("radio", name="unread", exact=True).click()
                expect(page.locator("#read-body .legacy-load-note")).to_have_count(0)
                expect(field).to_be_disabled()
                accepted_scopes[:] = ["f" * 64]
                page.get_by_role("radio", name="all", exact=True).click()
                expect(field).to_be_enabled()
                expect(field).to_have_value("")
                assert len(writes) == before_rotation
                assert page.evaluate(
                    "scope => sessionStorage.getItem('alles.read.pending.v1:' + scope) !== null",
                    pending_scope,
                )
                page.unroute(listed, scoped_list)
                page.get_by_role("radio", name="unread", exact=True).click()
                expect(field).to_have_value(retired_url)
                expect(field).to_be_disabled()
                page.locator("#read-save-check").click()
                expect(page.locator("#read-save-open")).to_be_visible()
                assert len(writes) == before_rotation and len(saved(retired_url)) == 1
                record("retired-pending-scope-never-becomes-a-new-draft")
                page.screenshot(path=str(out / f"{width}-saved-result.png"))
                assert not errors, errors
                assert all(
                    any(code in message for code in ("503", "404", "410")) for message in console
                ), console
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                record("saved-result-bounds-keyboard-and-console")
            except Exception as error:
                rows.append(
                    {
                        "scenario_id": "library.url-save.current",
                        "profile": str(width),
                        "status": "failed",
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                    }
                )
                page.screenshot(path=str(out / f"{width}-failed.png"))
            finally:
                context.tracing.stop(path=str(out / f"{width}-trace.zip"))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
        browser.close()
    assert all(row["status"] == "passed" for row in rows), "see scenarios.json"


if __name__ == "__main__":
    run()
