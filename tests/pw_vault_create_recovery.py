"""Ordinary encrypted Vault saves recover uncertain responses without duplicate entries."""

import json
import os
import time
import uuid
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    scenarios = []
    with sync_playwright() as pw:
        api = pw.request.new_context(base_url=base)
        api.post("/api/setup/dismiss")
        master = str(uuid.uuid4())
        opened = api.post("/api/vault/unlock", data={"password": master})
        assert opened.ok
        headers = {"X-Vault-Token": opened.json()["token"]}
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in [
                "retry",
                "conflict",
                "cancel",
                "rejected",
                "rejected-after-lost",
                "deleted",
                "late-save-lock",
                "lookup-lock",
                "expired",
                "reveal-lock",
                "expired-reveal",
                "dismissed-save",
                "dismissed-save-stale-list",
                "reveal-order",
            ]:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    reduced_motion="reduce",
                    service_workers="block",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                page = context.new_page()
                errors, console, posts, held = [], [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )

                def observe(request):
                    if request.url == base + "/api/vault" and request.method == "POST":
                        posts.append(
                            {
                                "id": request.post_data_json.get("request_id"),
                                "unlock": request.headers.get("x-vault-token"),
                            }
                        )

                page.on("request", observe)
                name = f"recovery {case} {width}"
                secret = str(uuid.uuid4()).center(42)
                corrected = str(uuid.uuid4()).center(46)
                result = {
                    "scenario_id": "vault.create." + case,
                    "feature_id": "passwords.vault-and-browser",
                    "profile": "desktop" if width == 1440 else "phone",
                    "status": "failed",
                }
                scenarios.append(result)
                other_entry = None

                def rows():
                    response = api.get("/api/vault", headers=headers)
                    assert response.ok
                    return [row for row in response.json() if row["name"] == name]

                def unlock():
                    page.locator("#vault-pw-input").fill(master)
                    page.locator("#vault-unlock-btn").click()
                    expect(page.locator("#vault-new-btn")).to_be_visible()

                def new_form(value=secret):
                    page.locator("#vault-new-btn").click()
                    expect(page.locator("#vf-name")).to_be_focused()
                    expect(page.locator("#vf-open-saved")).to_be_hidden()
                    page.locator("#vf-name").fill(name)
                    page.locator("#vf-f-username").fill(" fixture ")
                    page.locator("#vf-f-password").fill(value)

                def reject(route):
                    if route.request.method != "POST":
                        if case == "dismissed-save-stale-list" and len(held) == 1:
                            response = route.fetch()
                            assert response.ok
                            held.append((route, response))
                        else:
                            route.continue_()
                        return
                    if case in {"dismissed-save", "dismissed-save-stale-list"}:
                        held.append((route, None))
                        return
                    if case != "rejected":
                        response = route.fetch()
                        assert response.ok
                    if case == "late-save-lock":
                        held.append((route, response))
                    else:
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"detail":"synthetic unavailable"}',
                        )

                def revoke_browser_unlock():
                    tok = posts[0]["unlock"]
                    response = api.post("/api/vault/lock", headers={"X-Vault-Token": tok})
                    assert response.ok

                def wait_for_held_response(count=1):
                    deadline = time.monotonic() + 10
                    while len(held) < count and time.monotonic() < deadline:
                        page.wait_for_timeout(20)
                    assert len(held) == count, "fixture did not hold the expected response"

                try:
                    page.goto(base + "/?view=vault", wait_until="networkidle")
                    unlock()
                    new_form()
                    page.route(base + "/api/vault", reject)
                    page.locator("#vf-save").click()
                    if case in {"dismissed-save", "dismissed-save-stale-list"}:
                        expect(page.locator("#vf-save")).to_be_disabled()
                        wait_for_held_response()
                        assert not rows()
                        page.locator("#vf-cancel").click()
                        page.locator(".dialog-overlay [data-dialog-confirm]").click()
                        expect(page.locator("#vf-name")).to_have_count(0)
                        expect(page.locator("#vault-entry-list")).to_contain_text("no entries")
                        if case == "dismissed-save-stale-list":
                            wait_for_held_response(2)
                        response = held[0][0].fetch()
                        assert response.ok
                        held[0][0].fulfill(response=response)
                        expect(page.locator("#vault-entry-list")).to_contain_text(name)
                        if case == "dismissed-save-stale-list":
                            held[1][0].fulfill(response=held[1][1])
                        page.unroute(base + "/api/vault", reject)
                        page.wait_for_load_state("networkidle")
                        assert len(rows()) == 1
                        expect(page.locator("#vault-entry-list")).to_contain_text(name)
                    elif case == "late-save-lock":
                        expect(page.locator("#vf-save")).to_be_disabled()
                        wait_for_held_response()
                        page.evaluate(
                            "document.querySelector('#vf-save').dispatchEvent(new MouseEvent('click', {bubbles:true}))"
                        )
                        page.evaluate("document.querySelector('#vault-lock-btn').click()")
                        expect(page.locator("#vf-name")).to_have_count(0)
                        expect(page.locator("#vault-pw-input")).to_be_visible()
                        assert len(posts) == 1 and len(held) == 1
                        unlock()
                        new_form(corrected)
                        held[0][0].fulfill(response=held[0][1])
                        page.unroute(base + "/api/vault", reject)
                        page.wait_for_load_state("networkidle")
                        expect(page.locator("#vf-name")).to_have_value(name)
                        expect(page.locator("#vf-f-password")).to_have_value(corrected)
                        page.locator("#vf-cancel").click()
                    else:
                        expect(page.locator("#vf-error")).to_contain_text("save failed (503)")
                        expect(page.locator("#vf-f-password")).to_have_value(secret)
                        expect(page.locator("#vf-save")).to_be_focused()
                        assert posts[0]["id"]
                        assert len(rows()) == (0 if case == "rejected" else 1)
                        page.unroute(base + "/api/vault", reject)
                        if case in {"conflict", "deleted", "lookup-lock"}:
                            page.locator("#vf-f-password").fill(corrected)
                            page.locator("#vf-save").click()
                            expect(page.locator("#vf-error")).to_contain_text(
                                "already saved with different values"
                            )
                            assert posts[0]["id"] == posts[1]["id"]
                            recovery = page.locator("#vf-open-saved")
                            box = recovery.bounding_box()
                            assert box and box["width"] >= 44 and box["height"] >= 44
                            if case == "deleted":
                                assert api.delete(
                                    f"/api/vault/{rows()[0]['id']}", headers=headers
                                ).ok
                                recovery.click()
                                expect(page.locator("#vf-error")).to_contain_text("deleted")
                                expect(recovery).to_be_hidden()
                                expect(page.locator("#vf-f-password")).to_have_value(corrected)
                            elif case == "lookup-lock":

                                def hold_lookup(route):
                                    response = route.fetch()
                                    assert response.ok
                                    held.append((route, response))

                                page.route(base + "/api/vault/requests/**", hold_lookup)
                                recovery.click()
                                expect(recovery).to_be_disabled()
                                wait_for_held_response()
                                page.evaluate("document.querySelector('#vault-lock-btn').click()")
                                expect(page.locator("#vf-name")).to_have_count(0)
                                assert len(held) == 1
                                held[0][0].fulfill(response=held[0][1])
                                page.wait_for_load_state("networkidle")
                                expect(page.locator("#vf-name")).to_have_count(0)
                                expect(page.locator(".dialog-overlay")).to_have_count(0)
                            else:
                                recovery.focus()
                                page.keyboard.press("Enter")
                                page.locator(".dialog-overlay [data-dialog-cancel]").click()
                                expect(page.locator("#vf-f-password")).to_have_value(corrected)
                                recovery.click()
                                page.locator(".dialog-overlay [data-dialog-confirm]").click()
                                expect(page.locator("#vf-f-password")).to_have_value(secret)
                                page.locator("#vf-f-password").fill(corrected)
                                page.locator("#vf-save").click()
                                expect(page.locator("#vf-name")).to_have_count(0)
                        elif case in {"cancel", "rejected-after-lost"}:
                            if case == "rejected-after-lost":

                                def reject_again(route):
                                    if route.request.method == "POST":
                                        route.fulfill(
                                            status=400,
                                            content_type="application/json",
                                            body='{"detail":"synthetic rejected retry"}',
                                        )
                                    else:
                                        route.continue_()

                                page.route(base + "/api/vault", reject_again)
                                page.locator("#vf-save").click()
                                expect(page.locator("#vf-error")).to_contain_text(
                                    "synthetic rejected retry"
                                )
                                page.unroute(base + "/api/vault", reject_again)
                            page.locator("#vf-cancel").click()
                            expect(page.locator(".dialog-card")).to_contain_text(
                                "may already be saved"
                            )
                            page.locator(".dialog-overlay [data-dialog-cancel]").click()
                            expect(page.locator("#vf-f-password")).to_have_value(secret)
                            page.locator("#vf-cancel").click()
                            page.locator(".dialog-overlay [data-dialog-confirm]").click()
                            expect(page.locator("#vf-name")).to_have_count(0)
                            expect(page.locator("#vault-entry-list")).to_contain_text(name)
                        elif case == "expired":
                            revoke_browser_unlock()
                            page.locator("#vf-save").click()
                            expect(page.locator("#vf-name")).to_have_count(0)
                            expect(page.locator("#vault-pw-input")).to_be_visible()
                            unlock()
                            expect(page.locator("#vault-entry-list")).to_contain_text(name)
                        else:
                            if case == "rejected":
                                page.locator("#vf-f-password").fill(corrected)
                            page.locator("#vf-save").click()
                            expect(page.locator("#vf-name")).to_have_count(0)
                            assert posts[0]["id"] == posts[1]["id"]
                    if case in {"reveal-lock", "expired-reveal"}:
                        entry_id = rows()[0]["id"]
                        if case == "reveal-lock":

                            def hold_reveal(route):
                                response = route.fetch()
                                assert response.ok
                                held.append((route, response))

                            page.route(base + f"/api/vault/{entry_id}/reveal", hold_reveal)
                        else:
                            revoke_browser_unlock()
                        page.locator(f'[data-vault-open="{entry_id}"]').click()
                        if case == "reveal-lock":
                            wait_for_held_response()
                            page.evaluate("document.querySelector('#vault-lock-btn').click()")
                            expect(page.locator("#vault-pw-input")).to_be_visible()
                            held[0][0].fulfill(response=held[0][1])
                            page.wait_for_load_state("networkidle")
                        expect(page.locator("#vault-pw-input")).to_be_visible()
                        expect(page.locator("#vf-name")).to_have_count(0)
                    if case == "reveal-order":
                        first_id = rows()[0]["id"]
                        second_name = name + " second"
                        response = api.post(
                            "/api/vault",
                            headers=headers,
                            data={"name": second_name, "fields": {"password": corrected}},
                        )
                        assert response.ok
                        other_entry = response.json()["id"]
                        page.reload(wait_until="networkidle")
                        unlock()

                        def hold_selection(route):
                            response = route.fetch()
                            assert response.ok
                            held.append((route, response))

                        page.route(base + "/api/vault/*/reveal", hold_selection)
                        page.locator(f'[data-vault-open="{first_id}"]').click()
                        page.locator(f'[data-vault-open="{other_entry}"]').click()
                        wait_for_held_response(2)
                        first = next(pair for pair in held if first_id in pair[0].request.url)
                        second = next(pair for pair in held if other_entry in pair[0].request.url)
                        first[0].fulfill(response=first[1])
                        page.evaluate(
                            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
                        )
                        second[0].fulfill(response=second[1])
                        page.wait_for_load_state("networkidle")
                        expect(page.locator("#vf-name")).to_have_value(second_name)
                        expect(page.locator("#vf-f-password")).to_have_value(corrected)
                    page.screenshot(path=str(output / f"{case}-{width}-result.png"), full_page=True)
                    expected = 0 if case == "deleted" else 1
                    assert len(rows()) == expected
                    if expected:
                        reveal = api.get(f"/api/vault/{rows()[0]['id']}/reveal", headers=headers)
                        assert reveal.ok
                        assert reveal.json()["fields"]["password"] == (
                            corrected if case in {"conflict", "rejected"} else secret
                        )
                    page.reload(wait_until="networkidle")
                    unlock()
                    assert len(rows()) == expected
                    if case == "retry":
                        new_form()
                        page.locator("#vf-save").click()
                        expect(page.locator("#vf-name")).to_have_count(0)
                        assert len(rows()) == 2
                        assert posts[-1]["id"] != posts[0]["id"]
                    assert not errors, errors
                    assert all(
                        any(str(status) in message for status in [400, 403, 409, 410, 503])
                        for message in console
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    result["status"] = "passed"
                except Exception as error:
                    result["error"] = str(error)
                    page.screenshot(path=str(output / f"{case}-{width}-failed.png"), full_page=True)
                finally:
                    (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2))
                    page.unroute_all(behavior="ignoreErrors")
                    context.close()
                    for row in rows():
                        api.delete(f"/api/vault/{row['id']}", headers=headers)
                    if other_entry:
                        api.delete(f"/api/vault/{other_entry}", headers=headers)
                    (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2))
        browser.close()
        api.dispose()
    print(json.dumps(scenarios, indent=2))
    raise SystemExit(any(row["status"] != "passed" for row in scenarios))


if __name__ == "__main__":
    run()
