"""Home notes keep one save identity through lost replies, reload and conflicts."""

import json
import os
import time
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        api = pw.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        for host, width in (
            ("127.0.0.1", 1440),
            ("127.0.0.1", 390),
            ("localhost", 1440),
            ("localhost", 390),
        ):
            base = f"http://{host}:{os.environ['PORT']}"
            profile = str(width) if host == "127.0.0.1" else f"localhost-{width}"
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(8000)
            errors, console, writes = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console", lambda item: console.append(item.text) if item.type == "error" else None
            )
            page.on(
                "request",
                lambda request: (
                    writes.append(request.post_data_json)
                    if request.url == base + "/api/vault-md/file" and request.method == "POST"
                    else None
                ),
            )

            def record(name):
                rows.append(
                    {"scenario_id": "home.note." + name, "profile": profile, "status": "passed"}
                )
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

            def home():
                page.goto(base + "/?view=today", wait_until="networkidle")
                if page.locator("#today-capture-mode").get_attribute("aria-pressed") == "true":
                    page.locator("#today-capture-mode").click()

            entry = page.locator("#today-capture-input")
            submit = page.locator('#today-capture [type="submit"]')
            recovery = page.locator("#today-note-recovery")
            saved_responses = []

            def lose(route):
                if route.request.method != "POST":
                    route.continue_()
                    return
                response = route.fetch()
                assert response.ok, response.text()
                saved_responses.append(response.json())
                route.fulfill(status=503, json={"detail": "synthetic lost note reply"})

            def unknown(route):
                if route.request.method == "POST":
                    route.fulfill(status=200, json={})
                else:
                    route.continue_()

            try:
                for variant in ("repeated", "pending", "empty", "moved"):
                    home()
                    scope = api.get("/api/vault-md/create-scope").json()["scopes"][0]
                    if variant in ("pending", "moved"):
                        page.evaluate(
                            """scope => sessionStorage.setItem('alles.note.pending.v1:' + scope, JSON.stringify({
                            text: 'owned pending focus', body: {path: 'owned pending focus', content: 'owned pending focus\\n', unique: true, request_id: crypto.randomUUID()}
                        }))""",
                            scope,
                        )

                    def fail_scope(route):
                        route.fulfill(
                            status=503, json={"detail": "synthetic recovery read failure"}
                        )

                    page.route(base + "/api/vault-md/create-scope", fail_scope)
                    page.reload(wait_until="networkidle")
                    scope_retry = recovery.get_by_role("button", name="retry note recovery")
                    expect(scope_retry).to_be_visible()
                    scope_retry.focus()
                    if variant != "repeated":
                        page.unroute(base + "/api/vault-md/create-scope", fail_scope)
                    held = []

                    def hold_scope(route):
                        held.append((route, route.fetch()))

                    if variant == "moved":
                        page.route(base + "/api/vault-md/create-scope", hold_scope)
                        with page.expect_request(base + "/api/vault-md/create-scope"):
                            page.keyboard.press("Enter")
                        entry.focus()
                        deadline = time.monotonic() + 5
                        while not held and time.monotonic() < deadline:
                            page.wait_for_timeout(20)
                        assert len(held) == 1, "recovery reply was not held"
                        route, response = held[0]
                        route.fulfill(response=response)
                        page.unroute(base + "/api/vault-md/create-scope", hold_scope)
                        expect(recovery.locator(".note-retry")).to_be_visible()
                        expect(entry).to_be_focused()
                    else:
                        with page.expect_response(base + "/api/vault-md/create-scope"):
                            page.keyboard.press("Enter")
                        target = (
                            scope_retry
                            if variant == "repeated"
                            else recovery.locator(".note-retry")
                            if variant == "pending"
                            else entry
                        )
                        expect(target).to_be_focused()
                    page.unroute(base + "/api/vault-md/create-scope", fail_scope)
                    page.evaluate(
                        "scope => sessionStorage.removeItem('alles.note.pending.v1:' + scope)",
                        scope,
                    )
                    record("scope-retry-focus-" + variant)

                for text in ("a" + "😀" * 30, "😀" * 61):
                    home()
                    entry.fill(text)
                    with page.expect_response(
                        lambda r: (
                            r.url == base + "/api/vault-md/file" and r.request.method == "POST"
                        )
                    ) as unicode_reply:
                        submit.click()
                    assert unicode_reply.value.ok, unicode_reply.value.text()
                    path = unicode_reply.value.json()["path"]
                    assert writes[-1]["path"] == text[:60], writes[-1]["path"]
                    assert (
                        api.get("/api/vault-md/file", params={"path": path}).json()["content"]
                        == text + "\n"
                    )
                    expect(entry).to_have_value("")
                    recovery.locator(".note-saved-open").click()
                    expect(page.locator("#wiki-preview")).to_contain_text(text)
                record("unicode-title-preserves-complete-characters")

                home()
                text = f"confirmed scope failure {profile}"
                entry.fill(text)
                scope_calls = []

                def fail_followup_scope(route):
                    scope_calls.append(1)
                    if len(scope_calls) == 1:
                        route.continue_()
                    else:
                        route.fulfill(
                            status=503, json={"detail": "synthetic recovery read failure"}
                        )

                page.route(base + "/api/vault-md/create-scope", fail_followup_scope)
                submit.click()
                retry_scope = recovery.get_by_role("button", name="retry note recovery")
                expect(retry_scope).to_be_visible()
                expect(recovery.locator(".note-saved-open")).to_be_visible()
                expect(entry).to_have_value("")
                page.unroute(base + "/api/vault-md/create-scope", fail_followup_scope)
                retry_scope.focus()
                page.keyboard.press("Enter")
                expect(retry_scope).to_have_count(0)
                expect(recovery.locator(".note-saved-open")).to_be_focused()
                page.keyboard.press("Enter")
                expect(page.locator("#wiki-preview")).to_contain_text(text)
                record("confirmed-link-survives-scope-error")

                home()
                text = f"confirmed storage read failure {profile}"
                entry.fill(text)

                def fail_storage_after_save(route):
                    if route.request.method != "POST":
                        route.continue_()
                        return
                    response = route.fetch()
                    assert response.ok
                    page.evaluate("""() => {
                        window.__noteGetItem = Storage.prototype.getItem;
                        Storage.prototype.getItem = function(key) {
                            if (key.startsWith('alles.note.pending.v1:')) throw new Error('synthetic storage read failure');
                            return window.__noteGetItem.call(this, key);
                        };
                    }""")
                    route.fulfill(response=response)

                page.route(base + "/api/vault-md/file", fail_storage_after_save)
                submit.click()
                expect(recovery.locator(".note-recovery-error")).to_contain_text(
                    "synthetic storage read failure"
                )
                expect(recovery.locator(".note-saved-open")).to_be_visible()
                expect(entry).to_have_value("")
                page.unroute(base + "/api/vault-md/file", fail_storage_after_save)
                page.evaluate("() => { Storage.prototype.getItem = window.__noteGetItem; }")
                recovery.get_by_role("button", name="retry note recovery").click()
                expect(recovery.locator(".note-recovery-error")).to_have_count(0)
                recovery.locator(".note-saved-open").click()
                expect(page.locator("#wiki-preview")).to_contain_text(text)
                record("confirmed-link-survives-storage-read-error")

                home()
                text = f"capture note {width} # original"
                entry.fill(text)
                page.route(base + "/api/vault-md/file", lose)
                submit.click()
                expect(page.locator("#today-status")).to_contain_text("could not confirm note")
                expect(recovery.locator(".note-retry")).to_be_visible()
                expect(entry).to_have_value(text)
                page.unroute(base + "/api/vault-md/file", lose)
                first = saved_responses[-1]
                with page.expect_response(
                    lambda r: r.url == base + "/api/vault-md/file" and r.request.method == "POST"
                ) as reply:
                    submit.click()
                assert reply.value.json()["path"] == first["path"]
                expect(entry).to_have_value("")
                assert writes[-1] == writes[-2]
                record("lost-response-retry-same-note")
                recovery.locator(".note-saved-open").focus()
                page.keyboard.press("Enter")
                expect(page.locator("#wiki-preview")).to_contain_text(text)
                page.locator("#wiki-edit-btn").click()
                page.locator("#wiki-source-btn").click()
                source = page.locator("#wiki-source")
                expect(source).to_have_value(text + "\n")
                source.fill(text + "\nedited in docs\n")
                page.locator("#wiki-save-btn").click()
                expect(page.locator("#wiki-save-state")).to_have_text("saved")
                page.reload(wait_until="networkidle")
                expect(page.locator("#wiki-preview")).to_contain_text("edited in docs")
                assert (
                    api.get("/api/vault-md/file", params={"path": first["path"]}).json()["content"]
                    == text + "\nedited in docs\n"
                )
                record("open-exact-note-edit-and-reload")

                home()
                original = f"reload pending note {width}"
                entry.fill(original)
                page.route(base + "/api/vault-md/file", lose)
                submit.click()
                expect(recovery.locator(".note-retry")).to_be_visible()
                page.unroute(base + "/api/vault-md/file", lose)
                pending = dict(writes[-1])
                page.reload(wait_until="networkidle")
                expect(recovery.locator(".note-retry")).to_be_visible()
                newer = f"new task after reload {width}"
                entry.fill(newer)
                recovery.locator("summary").click()
                expect(recovery.locator("pre")).to_have_text(original)
                recovery.locator(".note-retry").focus()
                page.keyboard.press("Enter")
                expect(recovery.locator(".note-saved-open")).to_be_focused()
                expect(entry).to_have_value(newer)
                assert writes[-1] == pending
                assert page.locator("#today-capture-mode").get_attribute("aria-pressed") == "true"
                record("reload-retry-keeps-new-task-input-and-focus")

                home()
                entry.fill(f"unknown note reply {width}")
                page.route(base + "/api/vault-md/file", unknown)
                submit.click()
                expect(recovery.locator(".note-retry")).to_be_visible()
                pending = dict(writes[-1])
                page.unroute(base + "/api/vault-md/file", unknown)
                entry.fill(f"different new note {width}")
                count = len(writes)
                submit.click()
                expect(page.locator("#today-status")).to_contain_text("finish the pending note")
                assert len(writes) == count
                recovery.locator(".note-retry").click()
                expect(recovery.locator(".note-saved-open")).to_be_visible()
                expect(entry).to_have_value(f"different new note {width}")
                assert writes[-1] == pending
                record("unknown-result-keeps-identity-and-new-note-input")

                home()
                entry.fill(f"storage failure note {width}")
                page.evaluate("""() => {
                    window.__noteSetItem = Storage.prototype.setItem;
                    Storage.prototype.setItem = function(key, value) {
                        if (key.startsWith('alles.note.pending.v1:')) throw new Error('synthetic storage failure');
                        return window.__noteSetItem.call(this, key, value);
                    };
                }""")
                count = len(writes)
                submit.click()
                expect(page.locator("#today-status")).to_contain_text("storage failure")
                assert len(writes) == count
                expect(entry).to_have_value(f"storage failure note {width}")
                page.evaluate("() => { Storage.prototype.setItem = window.__noteSetItem; }")
                submit.click()
                expect(entry).to_have_value("")
                record("storage-failure-stops-write-and-retries")

                home()
                original = f"changed pending note {width}"
                entry.fill(original)
                page.route(base + "/api/vault-md/file", lose)
                submit.click()
                expect(recovery.locator(".note-retry")).to_be_visible()
                page.unroute(base + "/api/vault-md/file", lose)
                path = saved_responses[-1]["path"]
                doc = api.get("/api/vault-md/file", params={"path": path}).json()
                changed = api.post(
                    "/api/vault-md/safety/save",
                    data={
                        "path": path,
                        "content": "changed externally",
                        "expected_hash": doc["hash"],
                    },
                )
                assert changed.ok, changed.text()
                recovery.locator(".note-retry").click()
                expect(recovery.locator("p")).to_contain_text("saved note has changed")
                expect(recovery.locator(".note-open")).to_be_visible()
                assert (
                    api.get("/api/vault-md/file", params={"path": path}).json()["content"]
                    == "changed externally"
                )
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(out / f"{profile}-changed-note.png"), full_page=True)
                recovery.locator(".note-open").click()
                expect(page.locator("#wiki-preview")).to_contain_text("changed externally")
                record("changed-note-is-preserved-and-opened")
                home()
                assert api.delete("/api/vault-md/file", params={"path": path}).ok
                recovery.locator(".note-retry").click()
                expect(recovery.locator("p")).to_contain_text("moved or deleted")
                expect(recovery.locator(".note-open")).to_be_hidden()
                assert (
                    api.get("/api/vault-md/file", params={"path": path}).json().get("exists")
                    is False
                )
                recovery.locator(".note-discard").click()
                expect(page.get_by_role("alertdialog")).to_contain_text("may already be saved")
                page.locator("[data-dialog-cancel]").click()
                expect(recovery.locator(".note-retry")).to_be_visible()
                recovery.locator(".note-discard").click()
                page.locator("[data-dialog-confirm]").click()
                expect(recovery.locator(".note-resume")).to_have_count(0)
                expect(entry).to_be_focused()
                record("deleted-note-is-not-recreated-explicit-discard")

                entry.fill(f"confirmed note cleanup {width}")
                page.evaluate("""() => {
                    window.__noteRemoveItem = Storage.prototype.removeItem;
                    Storage.prototype.removeItem = function(key) {
                        const result = window.__noteRemoveItem.call(this, key);
                        if (key.startsWith('alles.note.pending.v1:')) throw new Error('synthetic cleanup failure');
                        return result;
                    };
                }""")
                with page.expect_response(
                    lambda r: r.url == base + "/api/vault-md/file" and r.request.method == "POST"
                ) as confirmed:
                    submit.click()
                assert confirmed.value.ok
                expect(entry).to_have_value("")
                expect(recovery.locator(".note-saved-open")).to_be_visible()
                page.evaluate("() => { Storage.prototype.removeItem = window.__noteRemoveItem; }")
                record("confirmed-save-survives-recovery-cleanup-failure")

                entry.fill(f"persistent cleanup note {profile}")
                page.evaluate("""() => {
                    Storage.prototype.removeItem = function(key) {
                        if (key.startsWith('alles.note.pending.v1:')) throw new Error('synthetic persistent cleanup failure');
                        return window.__noteRemoveItem.call(this, key);
                    };
                }""")
                submit.click()
                expect(entry).to_have_value("")
                expect(recovery.locator(".note-clear-saved")).to_be_visible()
                expect(recovery.locator(".note-saved-open")).to_be_visible()
                recovery.locator(".note-clear-saved").click()
                expect(recovery.locator("p")).to_contain_text(
                    "note saved; its browser recovery copy could not be cleared"
                )
                expect(recovery.locator(".note-saved-open")).to_be_visible()
                page.evaluate("() => { Storage.prototype.removeItem = window.__noteRemoveItem; }")
                recovery.locator(".note-clear-saved").click()
                expect(recovery.locator(".note-clear-saved")).to_have_count(0)
                expect(recovery.locator("p")).to_have_text("note saved")
                expect(recovery.locator(".note-saved-open")).to_be_focused()
                assert not page.evaluate(
                    "Object.keys(sessionStorage).some(key => key.startsWith('alles.note.pending.v1:'))"
                )
                record("persistent-cleanup-failure-keeps-verified-note-link")
                assert not errors, errors
                unexpected = [
                    line
                    for line in console
                    if not any(code in line for code in ("503", "409", "410"))
                ]
                assert not unexpected, unexpected
                record("console")
            except Exception as error:
                rows.append(
                    {
                        "scenario_id": "home.note.failure",
                        "profile": profile,
                        "status": "failed",
                        "error": str(error),
                        "page_errors": errors,
                        "console": console,
                    }
                )
            finally:
                page.screenshot(path=str(out / f"{profile}-final.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        api.dispose()
        browser.close()
    raise SystemExit(any(row["status"] != "passed" for row in rows))


if __name__ == "__main__":
    run()
