"""Saved mail search workflows on real owned records; no provider writes."""

import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    cases = [
        "save-keyboard-reload",
        "save-rejected",
        "lost-reply-reload",
        "cleanup-failure",
        "storage-failure",
        "delete-rejected",
        "delete-lost-reply",
        "read-order",
        "deleted-pending",
        "unicode",
        "delete-focus-moved",
        "delayed-save-new-query",
        "offline-save",
        "delete-confirmation-store-change",
        "confirmed-save-late-failure",
        "confirmed-save-late-success",
        "delete-later-confirmation",
        "unicode-whitespace",
        "delete-other-failure",
        "unconfirmed-save-late-success",
        "unicode-recovery-reload",
        "delete-success-new-store-read",
        "confirmed-retry-deleted",
        "confirmed-retry-store-change",
        "confirmed-delete-late-failure",
        "dismiss-refreshed-pending",
        "dismiss-changed-pending",
        "dismiss-changed-store",
        "confirmed-delete-store-change",
        "failed-removal-store-roundtrip",
        "pending-removal-other-store-failure",
        "pending-removal-other-store-success",
    ]
    if len(sys.argv) > 1:
        cases = [case for case in cases if case in sys.argv[1:]]
    assert cases
    records = []
    with sync_playwright() as pw:
        api = pw.request.new_context(base_url=base)
        seed_mail(api, base)
        assert api.post("/api/setup/dismiss").ok
        browser = pw.chromium.launch()
        endpoint = base + "/api/mail/saved-searches"

        def searches():
            response = api.get(endpoint)
            assert response.ok
            return response.json()["searches"]

        for width in [1440, 390]:
            for case in cases:
                for row in searches():
                    assert api.delete(endpoint + "/" + row["id"]).ok
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="allow" if case == "offline-save" else "block",
                    reduced_motion="reduce",
                )
                if case == "unconfirmed-save-late-success":
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                page.set_default_timeout(7000)
                errors, console, writes = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda item: console.append(item.text) if item.type == "error" else None,
                )
                page.on(
                    "request",
                    lambda request: (
                        writes.append(request.post_data_json)
                        if request.url == endpoint and request.method == "POST"
                        else None
                    ),
                )
                result = dict(
                    scenario_id="inbox.saved-search." + case, profile=str(width), status="failed"
                )
                records.append(result)
                bar = page.locator("#mail-saved")
                status = page.locator("#mail-saved-status")
                field = page.locator("#mail-search")
                save = page.locator("#mail-saved-save")
                chips = bar.locator(".mail-saved-chip")

                def search(query):
                    field.fill(query)
                    field.press("Enter")
                    expect(field).to_have_value(query)

                def reopen():
                    page.reload(wait_until="networkidle")
                    page.get_by_role("tab", name="mail", exact=True).click()
                    page.wait_for_load_state("networkidle")

                def pending():
                    return page.evaluate(
                        "() => Object.keys(sessionStorage).filter(key => key.startsWith('alles-mail-search:')).map(key => JSON.parse(sessionStorage.getItem(key)))"
                    )

                def wait_held(held):
                    deadline = time.monotonic() + 5
                    while not held and time.monotonic() < deadline:
                        page.wait_for_timeout(20)
                    assert len(held) == 1, "expected one held response"

                def reject(route):
                    route.fulfill(status=503, json={"detail": "owned synthetic failure"})

                try:
                    page.goto(base + "/?view=inbox", wait_until="networkidle")
                    page.get_by_role("tab", name="mail", exact=True).click()
                    page.wait_for_load_state("networkidle")
                    search("Project")
                    expect(save).to_have_attribute("aria-disabled", "false")
                    if case in {
                        "dismiss-refreshed-pending",
                        "dismiss-changed-pending",
                        "dismiss-changed-store",
                    }:
                        held = []
                        state = {"hold": False}

                        def failed_pending(route):
                            if route.request.method == "POST" or not state["hold"]:
                                reject(route)
                            else:
                                held.append(route)

                        page.route(endpoint, failed_pending)
                        save.click()
                        expect(status).to_contain_text("could not load saved searches")
                        original = pending()[0]
                        page.evaluate(
                            "() => { const real = window.fetch; window.__savedReadReturned = false; window.fetch = async (...args) => { const response = await real(...args); if (String(args[0]) === '/api/mail/saved-searches' && (!args[1]?.method || args[1].method === 'GET')) { const json = response.json.bind(response); response.json = async () => { const data = await json(); setTimeout(() => { window.__savedReadReturned = true; }, 0); return data; }; } return response; }; }"
                        )
                        state["hold"] = True
                        page.locator("#mail-saved-load-retry").click()
                        wait_held(held)
                        page.locator("#mail-saved-discard").click()
                        dialog = page.get_by_role("alertdialog")
                        expect(dialog).to_be_visible()
                        listing = api.get(endpoint).json()
                        if case == "dismiss-changed-pending":
                            changed = {**original, "name": "new name", "query": "new query"}
                            page.evaluate(
                                "value => sessionStorage.setItem('alles-mail-search:' + value.recovery_scope, JSON.stringify(value))",
                                changed,
                            )
                        elif case == "dismiss-changed-store":
                            changed = {
                                **original,
                                "request_id": str(uuid4()),
                                "recovery_scope": "e" * 64,
                                "name": "other pending",
                            }
                            page.evaluate(
                                "value => sessionStorage.setItem('alles-mail-search:' + value.recovery_scope, JSON.stringify(value))",
                                changed,
                            )
                            listing = {"searches": [], "recovery_scopes": ["e" * 64]}
                        held.pop().fulfill(json=listing)
                        page.wait_for_function("window.__savedReadReturned === true")
                        dialog.get_by_role("button", name="confirm", exact=True).click()
                        expect(dialog).not_to_be_visible()
                        if case == "dismiss-refreshed-pending":
                            expect(page.locator("#mail-saved-discard")).to_have_count(0)
                            assert pending() == []
                            expect(save).to_have_attribute("aria-disabled", "false")
                        else:
                            expect(page.locator("#mail-saved-discard")).to_be_visible()
                            assert changed in pending()
                        assert searches() == [] and len(writes) == 1
                    elif case in {
                        "confirmed-delete-store-change",
                        "failed-removal-store-roundtrip",
                        "pending-removal-other-store-failure",
                        "pending-removal-other-store-success",
                    }:
                        save.click()
                        expect(chips).to_have_text(["Project"])
                        identity = searches()[0]["id"]
                        original = api.get(endpoint).json()
                        other = {
                            "searches": [
                                {"id": identity, "name": "other store", "query": "other query"}
                            ],
                            "recovery_scopes": ["d" * 64],
                        }
                        current = {"store": original}
                        page.route(endpoint, lambda route: route.fulfill(json=current["store"]))
                        delete_url = endpoint + "/" + identity + "?*"
                        held = []

                        def hold_removal(route):
                            held.append(route)

                        def remove(name):
                            bar.get_by_role(
                                "button", name="remove saved search " + name, exact=True
                            ).click()

                        def show(store, query):
                            current["store"] = store
                            search(query)
                            expect(chips).to_have_text([row["name"] for row in store["searches"]])

                        if case == "confirmed-delete-store-change":
                            page.route(delete_url, hold_removal)
                            remove("Project")
                            wait_held(held)
                            assert api.delete(endpoint + "/" + identity).ok
                            show(api.get(endpoint).json(), "Receipt")
                            current["store"] = other
                            held.pop().fulfill(
                                status=403,
                                json={"detail": "this removal belongs to a different mail store"},
                            )
                            expect(chips).to_have_text(["other store"])
                            expect(bar).not_to_contain_text("could not confirm removal")
                            expect(bar).not_to_contain_text("saved search removed")
                        elif case == "failed-removal-store-roundtrip":
                            page.route(delete_url, reject)
                            remove("Project")
                            expect(status).to_contain_text("could not confirm removal of “Project”")
                            show(other, "Other")
                            expect(bar).not_to_contain_text("could not confirm removal")
                            remove("other store")
                            expect(status).to_contain_text(
                                "could not confirm removal of “other store”"
                            )
                            show(original, "Return")
                            expect(status).to_contain_text("could not confirm removal of “Project”")
                            expect(status).not_to_contain_text(
                                "could not confirm removal of “other store”"
                            )
                            page.unroute(delete_url, reject)
                            current["store"] = {**original, "searches": []}
                            remove("Project")
                            expect(chips).to_have_count(0)
                            expect(status).to_have_text("saved search removed")
                            show(other, "Other again")
                            expect(status).to_contain_text(
                                "could not confirm removal of “other store”"
                            )
                            expect(status).not_to_contain_text(
                                "could not confirm removal of “Project”"
                            )
                            show({**other, "searches": []}, "Other removed")
                            expect(status).to_have_text("saved search removed")
                            assert searches() == []
                        else:
                            page.route(delete_url, hold_removal)
                            remove("Project")
                            wait_held(held)
                            show(other, "Other")
                            if case.endswith("failure"):
                                reject(held.pop())
                            else:
                                assert api.delete(endpoint + "/" + identity).ok
                                held.pop().fulfill(json={"ok": True})
                            expect(bar).not_to_contain_text("saving changes…")
                            expect(bar).not_to_contain_text("could not confirm removal")
                            expect(bar).not_to_contain_text("saved search removed")
                            show(api.get(endpoint).json(), "Return")
                            if case.endswith("failure"):
                                expect(status).to_contain_text(
                                    "could not confirm removal of “Project”"
                                )
                                page.unroute(delete_url, hold_removal)
                                current["store"] = {**original, "searches": []}
                                remove("Project")
                                expect(chips).to_have_count(0)
                                expect(status).to_have_text("saved search removed")
                            else:
                                expect(bar).not_to_contain_text("could not confirm removal")
                                expect(chips).to_have_count(0)
                            assert searches() == []
                    elif case == "delete-success-new-store-read":
                        save.click()
                        expect(chips).to_have_text(["Project"])
                        identity = searches()[0]["id"]
                        deleted, reads = [], []

                        def hold_delete(route):
                            response = route.fetch()
                            assert response.ok
                            deleted.append((route, response))

                        page.route(endpoint + "/" + identity + "?*", hold_delete)
                        bar.get_by_role(
                            "button", name="remove saved search Project", exact=True
                        ).click()
                        wait_held(deleted)
                        other = {
                            "searches": [
                                {"id": str(uuid4()), "name": "other store", "query": "other query"}
                            ],
                            "recovery_scopes": ["b" * 64],
                        }
                        state = {"first": True}

                        def read_other_store(route):
                            if state["first"]:
                                state["first"] = False
                                reads.append(route)
                            else:
                                route.fulfill(json=other)

                        page.route(endpoint, read_other_store)
                        search("Receipt")
                        wait_held(reads)
                        route, response = deleted.pop()
                        route.fulfill(response=response)
                        reads.pop().fulfill(json=other)
                        expect(chips).to_have_text(["other store"])
                        expect(bar).not_to_contain_text("saving changes…")
                        assert searches() == []
                    elif case in {"confirmed-retry-deleted", "confirmed-retry-store-change"}:

                        def reject_first_save(route):
                            if route.request.method == "POST":
                                reject(route)
                            else:
                                route.continue_()

                        page.route(endpoint, reject_first_save)
                        save.click()
                        expect(page.locator("#mail-saved-retry")).to_have_attribute(
                            "aria-disabled", "false"
                        )
                        original = pending()[0]
                        assert api.post(endpoint, data=original).ok
                        page.unroute(endpoint, reject_first_save)
                        held = []

                        def hold_retry(route):
                            if route.request.method == "POST":
                                held.append(route)
                            else:
                                route.continue_()

                        page.route(endpoint, hold_retry)
                        page.locator("#mail-saved-retry").click()
                        wait_held(held)
                        search("Receipt")
                        expect(chips).to_have_text(["Project"])
                        page.wait_for_function(
                            "() => !Object.keys(sessionStorage).some(key => key.startsWith('alles-mail-search:'))"
                        )
                        if case == "confirmed-retry-store-change":
                            other = {
                                "searches": [
                                    {
                                        "id": str(uuid4()),
                                        "name": "other store",
                                        "query": "other query",
                                    }
                                ],
                                "recovery_scopes": ["c" * 64],
                            }
                            page.route(endpoint, lambda route: route.fulfill(json=other))
                            held.pop().fulfill(
                                status=403,
                                json={
                                    "detail": "this pending save belongs to a different mail store"
                                },
                            )
                            expect(chips).to_have_text(["other store"])
                            assert searches()[0]["id"] == original["request_id"]
                        else:
                            assert api.delete(endpoint + "/" + original["request_id"]).ok
                            held.pop().continue_()
                            expect(status).not_to_have_text("saving changes…")
                            expect(chips).to_have_count(0)
                            expect(status).to_contain_text("deleted")
                            assert searches() == [] and not pending()
                    elif case == "confirmed-delete-late-failure":
                        save.click()
                        expect(chips).to_have_text(["Project"])
                        identity = searches()[0]["id"]
                        held = []

                        def hold_removed(route):
                            response = route.fetch()
                            assert response.ok
                            held.append(route)

                        page.route(endpoint + "/" + identity + "?*", hold_removed)
                        bar.get_by_role(
                            "button", name="remove saved search Project", exact=True
                        ).click()
                        wait_held(held)
                        search("Receipt")
                        expect(chips).to_have_count(0)
                        page.route(endpoint, reject)
                        reject(held.pop())
                        expect(status).to_have_text("saved search removed")
                        expect(page.locator("#mail-saved-load-retry")).to_have_count(0)
                        assert searches() == []
                    elif case == "unconfirmed-save-late-success":
                        held = []
                        intercepted = False

                        def hold_unobserved_save(route):
                            nonlocal intercepted
                            if route.request.method == "POST" and not intercepted:
                                intercepted = True
                                response = route.fetch()
                                assert response.ok
                                held.append((route, response))
                            else:
                                route.continue_()

                        page.route(endpoint, hold_unobserved_save)
                        save.click()
                        wait_held(held)
                        original = pending()[0]
                        assert api.delete(endpoint + "/" + original["request_id"]).ok
                        page.evaluate(
                            "() => { const real = window.fetch; window.__searchReadReturned = false; window.fetch = async (...args) => { const response = await real(...args); if (String(args[0]) === '/api/mail/saved-searches' && (!args[1]?.method || args[1].method === 'GET')) { const json = response.json.bind(response); response.json = async () => { const data = await json(); setTimeout(() => { window.__searchReadReturned = true; }, 0); return data; }; } return response; }; }"
                        )
                        search("Receipt")
                        page.wait_for_function("window.__searchReadReturned === true")
                        expect(chips).to_have_count(0)
                        route, response = held.pop()
                        route.fulfill(response=response)
                        expect(status).not_to_have_text("saving changes…")
                        expect(chips).to_have_count(0)
                        assert searches() == [] and pending()[0] == original
                        page.locator("#mail-saved-retry").click()
                        expect(status).to_contain_text("deleted")
                        assert searches() == [] and pending()[0] == original
                    elif case == "unicode-recovery-reload":
                        query = "\u0085\ufeff" + " " * 39 + "Project"
                        search(query)
                        state = {"committed": False}

                        def lose_unicode_reply(route):
                            if route.request.method == "POST":
                                response = route.fetch()
                                assert response.ok
                                state["committed"] = True
                                reject(route)
                            elif state["committed"]:
                                reject(route)
                            else:
                                route.continue_()

                        page.route(endpoint, lose_unicode_reply)
                        save.click()
                        expect(status).to_contain_text("could not load saved searches")
                        original = pending()[0]
                        assert original["name"] == "\ufeff"
                        assert searches()[0]["id"] == original["request_id"]
                        reopen()
                        expect(status).to_contain_text("could not load saved searches")
                        page.locator("#mail-saved-load-retry").focus()
                        page.unroute(endpoint, lose_unicode_reply)
                        page.keyboard.press("Enter")
                        expect(status).to_have_text("search saved")
                        assert not pending() and len(writes) == 1
                        assert searches()[0]["id"] == original["request_id"]
                        expect(chips).to_have_text(["Project"])
                        expect(bar.get_by_role("button", name="Project", exact=True)).to_have_count(
                            1
                        )
                    elif case == "confirmed-save-late-success":
                        held = []

                        def hold_committed_save(route):
                            if route.request.method == "POST":
                                response = route.fetch()
                                assert response.ok
                                held.append((route, response))
                            else:
                                route.continue_()

                        page.route(endpoint, hold_committed_save)
                        save.click()
                        wait_held(held)
                        search("Receipt")
                        expect(chips).to_have_text(["Project"])
                        page.wait_for_function(
                            "() => !Object.keys(sessionStorage).some(key => key.startsWith('alles-mail-search:'))"
                        )
                        identity = searches()[0]["id"]
                        assert api.delete(endpoint + "/" + identity).ok
                        search("Project notes")
                        expect(chips).to_have_count(0)
                        route, response = held.pop()
                        route.fulfill(response=response)
                        expect(save).to_have_attribute("aria-disabled", "false")
                        expect(chips).to_have_count(0)
                        assert searches() == [] and not pending()
                    elif case == "delete-later-confirmation":
                        save.click()
                        expect(chips).to_have_text(["Project"])
                        identity = searches()[0]["id"]

                        def lose_delete(route):
                            response = route.fetch()
                            assert response.ok
                            reject(route)

                        page.route(endpoint + "/" + identity + "?*", lose_delete)
                        page.route(endpoint, reject)
                        bar.get_by_role(
                            "button", name="remove saved search Project", exact=True
                        ).click()
                        expect(status).to_contain_text("could not load saved searches")
                        expect(
                            bar.get_by_role(
                                "button", name="remove saved search Project", exact=True
                            )
                        ).to_have_attribute("aria-disabled", "false")
                        assert searches() == []
                        page.locator("#mail-saved-load-retry").focus()
                        page.unroute(endpoint, reject)
                        page.keyboard.press("Enter")
                        expect(chips).to_have_count(0)
                        expect(status).to_have_text("saved search removed")
                        expect(page.locator("#mail-saved-load-retry")).to_have_count(0)
                    elif case == "unicode-whitespace":
                        query = "a" * 39 + "\u0085b"
                        search(query)
                        save.click()
                        expect(status).to_have_text("search saved")
                        row = searches()[0]
                        assert row["name"] == "a" * 39 and row["query"] == query
                        assert not pending() and len(writes) == 1
                        query = "\u0085\u001c Project \u0085"
                        search(query)
                        save.click()
                        expect(status).to_have_text("search saved")
                        assert searches()[-1]["name"] == "Project"
                        assert searches()[-1]["query"] == "Project"
                        assert not pending() and len(writes) == 2
                        expect(save).to_have_count(0)
                    elif case == "delete-other-failure":
                        save.click()
                        expect(chips).to_have_text(["Project"])
                        search("Receipt")
                        expect(save).to_have_attribute("aria-disabled", "false")
                        save.click()
                        expect(chips).to_have_text(["Project", "Receipt"])
                        first, second = searches()
                        first_url = endpoint + "/" + first["id"] + "?*"
                        second_url = endpoint + "/" + second["id"] + "?*"
                        page.route(first_url, reject)
                        page.route(second_url, reject)
                        for name in ["Project", "Receipt"]:
                            button = bar.get_by_role(
                                "button", name="remove saved search " + name, exact=True
                            )
                            button.click()
                            expect(button).to_have_attribute("aria-disabled", "false")
                            expect(status).to_contain_text(
                                "could not confirm removal of “" + name + "”"
                            )
                        page.unroute(second_url, reject)
                        bar.get_by_role(
                            "button", name="remove saved search Receipt", exact=True
                        ).click()
                        expect(chips).to_have_text(["Project"])
                        expect(status).to_contain_text("could not confirm removal of “Project”")
                        expect(status).not_to_contain_text("could not confirm removal of “Receipt”")
                        page.unroute(first_url, reject)
                        bar.get_by_role(
                            "button", name="remove saved search Project", exact=True
                        ).click()
                        expect(chips).to_have_count(0)
                        expect(status).to_have_text("saved search removed")
                        assert searches() == []
                    elif case == "delete-confirmation-store-change":
                        save.click()
                        expect(chips).to_have_text(["Project"])
                        identity = searches()[0]["id"]
                        scope = "a" * 64
                        new_pending = {
                            "request_id": str(uuid4()),
                            "name": "new store pending",
                            "query": "new query",
                            "recovery_scope": scope,
                        }
                        page.evaluate(
                            "pending => sessionStorage.setItem('alles-mail-search:' + pending.recovery_scope, JSON.stringify(pending))",
                            new_pending,
                        )
                        page.route(endpoint + "/" + identity + "?*", reject)
                        page.route(
                            endpoint,
                            lambda route: route.fulfill(
                                json={
                                    "searches": [
                                        {
                                            "id": str(uuid4()),
                                            "name": "new store",
                                            "query": "new query",
                                        }
                                    ],
                                    "recovery_scopes": [scope],
                                }
                            ),
                        )
                        bar.get_by_role(
                            "button", name="remove saved search Project", exact=True
                        ).click()
                        expect(chips).to_have_text(["new store"])
                        expect(status).to_contain_text("new store pending")
                        expect(status).not_to_contain_text("saved search removed")
                        assert searches()[0]["id"] == identity
                    elif case == "confirmed-save-late-failure":
                        held = []

                        def hold_late_save(route):
                            if route.request.method == "POST":
                                response = route.fetch()
                                assert response.ok
                                held.append(route)
                            else:
                                route.continue_()

                        page.route(endpoint, hold_late_save)
                        save.click()
                        wait_held(held)
                        search("Receipt")
                        expect(chips).to_have_text(["Project"])
                        page.wait_for_function(
                            "() => !Object.keys(sessionStorage).some(key => key.startsWith('alles-mail-search:'))"
                        )
                        reject(held.pop())
                        expect(status).to_have_text("search saved")
                        expect(field).to_have_value("Receipt")
                        assert len(searches()) == 1 and not pending()
                    elif case == "offline-save":
                        page.wait_for_function(
                            "() => navigator.serviceWorker && navigator.serviceWorker.controller",
                            timeout=15000,
                        )
                        context.set_offline(True)
                        save.click()
                        expect(status).to_contain_text("could not load saved searches")
                        original = pending()[0]
                        assert searches() == []
                        queued = page.evaluate("""() => new Promise((resolve, reject) => {
                            const channel = new MessageChannel();
                            const timeout = setTimeout(() => reject(new Error('outbox check timed out')), 5000);
                            channel.port1.onmessage = event => { clearTimeout(timeout); resolve(event.data); };
                            navigator.serviceWorker.controller.postMessage({type: 'alles-outbox-list'}, [channel.port2]);
                        })""")
                        assert queued["ok"] and queued["items"] == [], queued
                        context.set_offline(False)
                        page.locator("#mail-saved-load-retry").focus()
                        page.keyboard.press("Enter")
                        expect(page.locator("#mail-saved-retry")).to_have_attribute(
                            "aria-disabled", "false"
                        )
                        page.locator("#mail-saved-retry").click()
                        expect(chips).to_have_text(["Project"])
                        assert searches()[0]["id"] == original["request_id"]
                    elif case == "save-keyboard-reload":
                        save.focus()
                        page.keyboard.press("Enter")
                        expect(chips).to_have_text(["Project"])
                        expect(status).to_have_text("search saved")
                        identity = searches()[0]["id"]
                        assert not pending()
                        reopen()
                        expect(chips).to_have_text(["Project"])
                        chips.focus()
                        page.keyboard.press("Enter")
                        expect(field).to_have_value("Project")
                        expect(page.locator('.mail-row[data-uid="702"] .mail-open')).to_be_visible()
                        assert searches()[0]["id"] == identity
                    elif case == "save-rejected":

                        def fail_post(route):
                            if route.request.method == "POST":
                                reject(route)
                            else:
                                route.continue_()

                        page.route(endpoint, fail_post)
                        save.click()
                        retry = page.locator("#mail-saved-retry")
                        expect(retry).to_have_attribute("aria-disabled", "false")
                        expect(status).to_contain_text("could not confirm saving")
                        page.screenshot(path=str(out / f"{width}-save-error.png"), full_page=True)
                        assert searches() == []
                        original = pending()[0]
                        retry.focus()
                        page.keyboard.press("Enter")
                        expect(retry).to_have_attribute("aria-disabled", "false")
                        expect(retry).to_be_focused()
                        search("Receipt")
                        expect(field).to_have_value("Receipt")
                        page.unroute(endpoint, fail_post)
                        retry.click()
                        expect(chips).to_have_text(["Project"])
                        expect(status).to_have_text("search saved")
                        expect(field).to_have_value("Receipt")
                        assert all(write == original for write in writes)
                        assert len(searches()) == 1 and not pending()
                    elif case in {"lost-reply-reload", "deleted-pending"}:
                        state = {"committed": False}

                        def lose_reply(route):
                            if route.request.method == "POST":
                                response = route.fetch()
                                assert response.ok
                                state["committed"] = True
                                reject(route)
                            elif state["committed"]:
                                reject(route)
                            else:
                                route.continue_()

                        page.route(endpoint, lose_reply)
                        save.click()
                        expect(status).to_contain_text("could not load saved searches")
                        assert len(searches()) == 1
                        original = pending()[0]
                        if case == "deleted-pending":
                            assert api.delete(endpoint + "/" + original["request_id"]).ok
                        reopen()
                        expect(status).to_contain_text("could not load saved searches")
                        page.locator("#mail-saved-load-retry").focus()
                        page.unroute(endpoint, lose_reply)
                        page.keyboard.press("Enter")
                        if case == "lost-reply-reload":
                            expect(chips).to_have_text(["Project"])
                            expect(status).to_have_text("search saved")
                            assert (
                                len(writes) == 1 and searches()[0]["id"] == original["request_id"]
                            )
                            assert not pending()
                        else:
                            page.locator("#mail-saved-retry").click()
                            expect(status).to_contain_text("deleted")
                            assert searches() == [] and pending()[0] == original
                            page.locator("#mail-saved-discard").click()
                            page.get_by_role("alertdialog").get_by_role(
                                "button", name="confirm", exact=True
                            ).click()
                            expect(page.locator("#mail-saved-discard")).to_have_count(0)
                            assert not pending()
                            search("Project")
                            save.click()
                            expect(chips).to_have_text(["Project"])
                            assert searches()[0]["id"] != original["request_id"]
                    elif case in {"cleanup-failure", "storage-failure"}:
                        operation = "removeItem" if case == "cleanup-failure" else "setItem"
                        page.evaluate(
                            "operation => { window.restoreSearchStorage = Storage.prototype[operation]; Storage.prototype[operation] = function(key, ...args) { if (key.startsWith('alles-mail-search:')) throw new DOMException('owned storage failure'); return window.restoreSearchStorage.call(this, key, ...args); }; }",
                            operation,
                        )
                        save.click()
                        if case == "cleanup-failure":
                            expect(status).to_contain_text(
                                "search saved. its recovery data could not be cleared"
                            )
                            expect(chips).to_have_text(["Project"])
                            page.screenshot(
                                path=str(out / f"{width}-cleanup-warning.png"), full_page=True
                            )
                            assert len(searches()) == 1 and len(pending()) == 1
                        else:
                            expect(status).to_contain_text("no save was sent")
                            assert searches() == [] and writes == []
                        page.evaluate(
                            "operation => { Storage.prototype[operation] = window.restoreSearchStorage; }",
                            operation,
                        )
                        if case == "cleanup-failure":
                            page.locator("#mail-saved-cleanup").click()
                            expect(status).to_have_text("search saved")
                            assert len(writes) == 1 and not pending()
                        else:
                            page.locator("#mail-saved-load-retry").click()
                            expect(save).to_have_attribute("aria-disabled", "false")
                            save.click()
                            expect(chips).to_have_text(["Project"])
                    elif case in {"delete-rejected", "delete-lost-reply", "delete-focus-moved"}:
                        save.click()
                        expect(chips).to_have_text(["Project"])
                        original = writes[0]
                        identity = searches()[0]["id"]
                        url = endpoint + "/" + identity + "?*"
                        button = bar.get_by_role(
                            "button", name="remove saved search Project", exact=True
                        )
                        held = []

                        def remove_reply(route):
                            if case == "delete-rejected":
                                reject(route)
                            else:
                                response = route.fetch()
                                assert response.ok
                                if case == "delete-focus-moved":
                                    held.append((route, response))
                                else:
                                    reject(route)

                        page.route(url, remove_reply)
                        button.focus()
                        page.keyboard.press("Enter")
                        if case == "delete-rejected":
                            expect(status).to_contain_text("could not confirm removal")
                            expect(button).to_be_focused()
                            expect(chips).to_have_count(1)
                            assert len(searches()) == 1
                            page.unroute(url, remove_reply)
                            button.click()
                        elif case == "delete-focus-moved":
                            wait_held(held)
                            field.focus()
                            route, response = held.pop()
                            route.fulfill(response=response)
                        expect(status).to_have_text("saved search removed")
                        expect(chips).to_have_count(0)
                        if case == "delete-focus-moved":
                            expect(field).to_be_focused()
                        assert searches() == []
                        assert api.post(endpoint, data=original).status == 410
                        reopen()
                        expect(chips).to_have_count(0)
                    elif case == "read-order":
                        save.click()
                        expect(chips).to_have_text(["Project"])
                        held, calls = [], []

                        def hold_first_read(route):
                            calls.append(route.request.method)
                            if len(calls) == 1:
                                response = route.fetch()
                                held.append((route, response))
                            else:
                                route.continue_()

                        page.route(endpoint, hold_first_read)
                        search("Receipt")
                        wait_held(held)
                        assert api.post(
                            endpoint,
                            data={"name": "newest", "query": "Receipt", "request_id": str(uuid4())},
                        ).ok
                        search("Project")
                        expect(chips).to_have_text(["Project", "newest"])
                        route, response = held.pop()
                        route.fulfill(response=response)
                        page.wait_for_load_state("networkidle")
                        expect(chips).to_have_text(["Project", "newest"])
                    elif case == "unicode":
                        query = "🧪" * 35 + " Project notes"
                        search(query)
                        save.click()
                        expect(status).to_have_text("search saved")
                        row = searches()[0]
                        assert row["query"] == query and row["name"] == query[:40].strip()
                        expect(chips).to_have_text([row["name"]])
                    elif case == "delayed-save-new-query":
                        held = []

                        def hold_save(route):
                            if route.request.method == "POST":
                                response = route.fetch()
                                held.append((route, response))
                            else:
                                route.continue_()

                        page.route(endpoint, hold_save)
                        save.click()
                        wait_held(held)
                        search("Receipt")
                        field.focus()
                        route, response = held.pop()
                        route.fulfill(response=response)
                        page.unroute(endpoint, hold_save)
                        expect(status).to_have_text("search saved")
                        expect(field).to_be_focused()
                        expect(field).to_have_value("Receipt")
                        assert [row["query"] for row in searches()] == ["Project"]
                        expect(save).to_have_attribute("aria-disabled", "false")
                        save.click()
                        expect(chips).to_have_text(["Project", "Receipt"])
                        assert len({row["id"] for row in searches()}) == 2
                    assert not errors, errors
                    assert all(
                        "503" in value
                        or "403" in value
                        or "410" in value
                        or (
                            case == "offline-save"
                            and ("ERR_INTERNET_DISCONNECTED" in value or "Failed to fetch" in value)
                        )
                        for value in console
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                        "horizontal overflow"
                    )
                    for button in bar.locator("button:visible").all():
                        box = button.bounding_box()
                        assert box["width"] >= 43.5 and box["height"] >= 43.5, box
                    result["status"] = "passed"
                except Exception as error:
                    result.update(
                        error=str(error), page_errors=errors, console=console, writes=writes
                    )
                finally:
                    page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                    if case == "unconfirmed-save-late-success":
                        context.tracing.stop(path=str(out / f"{width}-{case}-trace.zip"))
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(records, indent=2))
        browser.close()
        api.dispose()
    raise SystemExit(any(record["status"] != "passed" for record in records))


if __name__ == "__main__":
    run()
