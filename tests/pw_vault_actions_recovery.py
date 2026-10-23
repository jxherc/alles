"""Vault actions with isolated files, synthetic secrets and a stub clipboard."""

import json
import os
import re
import traceback
import uuid
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    results = []
    with sync_playwright() as pw:
        api = pw.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        master = str(uuid.uuid4())
        opened = api.post("/api/vault/unlock", data={"password": master})
        assert opened.ok
        headers = {"X-Vault-Token": opened.json()["token"]}
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in [
                "daily",
                "quoted-upload",
                "share-replacement",
                "copy-error",
                "copy-lock",
                "copy-denied",
                "form-delete",
                "delete-lost",
                "attachments-error",
                "upload-lost",
                "upload-rejected",
                "upload-close",
                "upload-lock",
                "download-error",
                "download-lock",
                "remove-error",
                "share-error",
                "share-lock",
                "share-denied",
                "share-revoke",
            ]:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                context.add_init_script(
                    "window._copies=[];Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>{if(window._denyCopy)throw new Error('synthetic clipboard denied');window._copies.push(value);}}});"
                )
                page = context.new_page()
                page.set_default_timeout(6000)
                errors, console, downloads = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                page.on("download", lambda download: downloads.append(download))
                name = f"action {case} {width}"
                secret = str(uuid.uuid4()).center(42)
                content = uuid.uuid4().bytes + b"\x00\xff\r\n"
                response = api.post(
                    "/api/vault",
                    headers=headers,
                    data={
                        "name": name,
                        "type": "login",
                        "fields": {"username": "fixture", "password": secret},
                    },
                )
                assert response.ok
                eid = response.json()["id"]
                endpoint = base + "/api/vault/" + eid
                result = {
                    "scenario_id": "vault.actions." + case,
                    "feature_id": "passwords.vault-and-browser",
                    "profile": "desktop" if width == 1440 else "phone",
                    "status": "failed",
                }
                results.append(result)

                def fail(route):
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic unavailable"}',
                    )

                def lost(route):
                    response = route.fetch()
                    assert response.ok, response.text()
                    fail(route)

                def key(locator):
                    expect(locator).to_be_enabled()
                    locator.focus()
                    page.keyboard.press("Enter")

                def attachments():
                    return api.get(endpoint + "/attachments", headers=headers).json()

                def upload():
                    page.locator("#vf-attach-input").set_input_files(
                        {
                            "name": "fixture.bin",
                            "mimeType": "application/octet-stream",
                            "buffer": content,
                        }
                    )

                def wait_held(held):
                    for _ in range(100):
                        if held:
                            return
                        page.wait_for_timeout(10)
                    assert held, "request not held"

                def close_form():
                    key(page.locator("#vf-x"))
                    if case.startswith("upload-") and case != "upload-rejected":
                        key(page.locator("[data-dialog-confirm]"))
                    expect(page.locator("#vf-name")).to_have_count(0)

                try:
                    if case in [
                        "attachments-error",
                        "download-error",
                        "download-lock",
                        "remove-error",
                    ]:
                        response = api.post(
                            endpoint + "/attachments",
                            headers=headers,
                            multipart={
                                "file": {
                                    "name": "fixture.bin",
                                    "mimeType": "application/octet-stream",
                                    "buffer": content,
                                }
                            },
                        )
                        assert response.ok
                    page.goto(base + "/?view=vault", wait_until="networkidle")
                    page.locator("#vault-pw-input").fill(master)
                    key(page.locator("#vault-unlock-btn"))
                    row = page.locator(f'.vault-entry[data-id="{eid}"]')
                    expect(row).to_be_visible()
                    if case in ["copy-error", "copy-lock"]:
                        held = []
                        page.route(
                            endpoint + "/reveal",
                            fail
                            if case == "copy-error"
                            else lambda route: held.append((route, route.fetch())),
                        )
                        page.evaluate(
                            "(()=>{const copy=window._vaultCopy;window._vaultCopy=id=>window._copyDone=copy(id);})()"
                        )
                        key(row.locator("[data-vault-copy]"))
                        if case == "copy-lock":
                            wait_held(held)
                            key(page.locator("#vault-lock-btn"))
                            expect(page.locator("#vault-pw-input")).to_be_visible()
                            for route, response in held:
                                route.fulfill(response=response)
                        page.evaluate("window._copyDone")
                        assert page.evaluate("window._copies.length") == 0
                        if case == "copy-error":
                            expect(page.locator(".toast.error")).to_be_visible()
                    else:
                        if case == "attachments-error":
                            page.route(endpoint + "/attachments", fail)
                        key(row.locator("[data-vault-open]"))
                        expect(page.locator("#vf-name")).to_have_value(name)
                        if case == "quoted-upload":
                            page.locator("#vf-attach-input").set_input_files(
                                {"name": 'a"b.txt', "mimeType": "text/plain", "buffer": content}
                            )
                            expect(page.locator(".vf-attach-row")).to_have_count(1)
                            expect(page.locator("#vf-upload-status")).to_be_hidden()
                            expect(page.locator("#vf-error")).to_be_hidden()
                            assert len(attachments()) == 1
                            with page.expect_download() as pending:
                                key(page.locator("[data-dl]"))
                            assert Path(pending.value.path()).read_bytes() == content
                        elif case == "share-replacement":
                            key(page.locator("#vf-share"))
                            expect(page.locator("#vf-share-url")).to_have_value(
                                re.compile(r"^http://127[.]0[.]0[.]1:[0-9]+/sv/[^#]+#.+")
                            )
                            previous = page.locator("#vf-share-url").input_value()
                            page.route(endpoint + "/share", lost)
                            key(page.locator("#vf-share"))
                            expect(page.locator("#vf-error")).to_contain_text("could not create")
                            expect(page.locator("#vf-share-result")).to_be_hidden()
                            expect(page.locator("#vf-share-url")).to_have_value("")
                            page.unroute(endpoint + "/share")
                            key(page.locator("#vf-share"))
                            expect(page.locator("#vf-share-url")).to_have_value(
                                re.compile(r"^http://127[.]0[.]0[.]1:[0-9]+/sv/[^#]+#.+")
                            )
                            assert page.locator("#vf-share-url").input_value() != previous
                        elif case == "copy-denied":
                            page.evaluate("window._denyCopy=true")
                            key(page.locator('[data-copy="vf-f-password"]'))
                            expect(page.locator("#vf-error")).to_contain_text(
                                "clipboard unavailable"
                            )
                            expect(page.locator("#vf-f-password")).to_have_value(secret)
                            page.evaluate("window._denyCopy=false")
                            key(page.locator('[data-copy="vf-f-password"]'))
                            page.wait_for_function("window._copies.length===1")
                            assert page.evaluate("window._copies[0]") == secret
                        elif case in ["form-delete", "delete-lost"]:
                            page.locator("#vf-name").fill("retained correction")
                            page.route(endpoint, lost if case == "delete-lost" else fail)
                            key(page.locator("#vf-del"))
                            key(page.locator("[data-dialog-confirm]"))
                            expect(page.locator("#vf-error")).to_contain_text(
                                "could not confirm deletion"
                            )
                            expect(page.locator("#vf-name")).to_have_value("retained correction")
                            page.unroute(endpoint)
                            key(page.locator("#vf-del"))
                            key(page.locator("[data-dialog-confirm]"))
                            expect(page.locator("#vf-name")).to_have_count(0)
                            expect(row).to_have_count(0)
                        elif case == "attachments-error":
                            expect(page.locator("#vf-attach [role=alert]")).to_contain_text(
                                "could not load"
                            )
                            expect(page.locator(".vf-attach-empty")).to_have_count(0)
                            page.unroute(endpoint + "/attachments")
                            key(page.locator("[data-attach-retry]"))
                            expect(page.locator(".vf-attach-row")).to_have_count(1)
                        elif case.startswith("upload-"):
                            url = endpoint + "/attachments"
                            held = []
                            if case in ["upload-lost", "upload-close"]:
                                page.route(
                                    url,
                                    lambda route: (
                                        lost(route)
                                        if route.request.method == "POST"
                                        else route.continue_()
                                    ),
                                )
                            elif case == "upload-rejected":
                                page.route(
                                    url,
                                    lambda route: (
                                        fail(route)
                                        if route.request.method == "POST"
                                        else route.continue_()
                                    ),
                                )
                            else:
                                page.route(
                                    url,
                                    lambda route: (
                                        held.append((route, route.fetch()))
                                        if route.request.method == "POST"
                                        else route.continue_()
                                    ),
                                )
                            upload()
                            if case == "upload-lock":
                                wait_held(held)
                                close_form()
                                key(page.locator("#vault-lock-btn"))
                                expect(page.locator("#vault-pw-input")).to_be_visible()
                                for route, response in held:
                                    route.fulfill(response=response)
                                page.wait_for_load_state("networkidle")
                                expect(page.locator("#vf-name")).to_have_count(0)
                                assert len(attachments()) == 1
                            else:
                                expect(page.locator("#vf-error")).to_contain_text(
                                    "could not confirm the upload"
                                )
                                expect(page.locator("#vf-upload-status")).to_contain_text(
                                    "file is kept"
                                )
                                if case == "upload-close":
                                    key(page.locator("#vf-x"))
                                    key(page.locator("[data-dialog-cancel]"))
                                    expect(page.locator("#vf-name")).to_be_visible()
                                    close_form()
                                    page.unroute(url)
                                    key(row.locator("[data-vault-open]"))
                                    expect(page.locator(".vf-attach-row")).to_have_count(1)
                                else:
                                    page.unroute(url)
                                    key(page.locator("#vf-attach-btn"))
                                    expect(page.locator(".vf-attach-row")).to_have_count(1)
                                    expect(page.locator("#vf-upload-status")).to_be_hidden()
                                assert len(attachments()) == 1
                        elif case in ["download-error", "download-lock", "remove-error"]:
                            expect(page.locator(".vf-attach-row")).to_have_count(1)
                            aid = attachments()[0]["id"]
                            url = base + "/api/vault/attachments/" + aid
                            held = []
                            if case == "download-lock":
                                page.route(url, lambda route: held.append((route, route.fetch())))
                            else:
                                page.route(url, fail)
                            key(
                                page.locator("[data-rm]" if case == "remove-error" else "[data-dl]")
                            )
                            if case == "remove-error":
                                key(page.locator("[data-dialog-confirm]"))
                            if case == "download-lock":
                                wait_held(held)
                                close_form()
                                key(page.locator("#vault-lock-btn"))
                                expect(page.locator("#vault-pw-input")).to_be_visible()
                                for route, response in held:
                                    route.fulfill(response=response)
                                page.wait_for_load_state("networkidle")
                                assert downloads == []
                            else:
                                expect(page.locator("#vf-error")).to_be_visible()
                                assert downloads == []
                                assert len(attachments()) == 1
                                page.unroute(url)
                                if case == "remove-error":
                                    key(page.locator("[data-rm]"))
                                    key(page.locator("[data-dialog-confirm]"))
                                    expect(page.locator(".vf-attach-empty")).to_be_visible()
                                    assert attachments() == []
                                else:
                                    with page.expect_download() as pending:
                                        key(page.locator("[data-dl]"))
                                    assert Path(pending.value.path()).read_bytes() == content
                        elif case.startswith("share-"):
                            url = endpoint + "/share"
                            held = []
                            if case == "share-error":
                                page.route(url, fail)
                            if case == "share-lock":
                                page.route(url, lambda route: held.append((route, route.fetch())))
                            if case == "share-denied":
                                page.evaluate("window._denyCopy=true")
                            key(page.locator("#vf-share"))
                            if case == "share-error":
                                expect(page.locator("#vf-error")).to_contain_text(
                                    "could not create"
                                )
                                assert page.evaluate("window._copies.length") == 0
                                expect(page.locator("#vf-share-result")).to_be_hidden()
                                page.unroute(url)
                                key(page.locator("#vf-share"))
                                expect(page.locator("#vf-share-result")).to_be_visible()
                            elif case == "share-lock":
                                wait_held(held)
                                close_form()
                                key(page.locator("#vault-lock-btn"))
                                expect(page.locator("#vault-pw-input")).to_be_visible()
                                for route, response in held:
                                    route.fulfill(response=response)
                                page.wait_for_load_state("networkidle")
                                assert page.evaluate("window._copies.length") == 0
                            else:
                                expect(page.locator("#vf-share-result")).to_be_visible()
                                expect(page.locator("#vf-share-url")).to_have_value(
                                    re.compile(r"^http://127[.]0[.]0[.]1:[0-9]+/sv/[^#]+#.+")
                                )
                                link = page.locator("#vf-share-url").input_value()
                                assert link.startswith(base + "/sv/") and "#" in link
                                if case == "share-denied":
                                    expect(page.locator("#vf-error")).to_contain_text(
                                        "clipboard unavailable"
                                    )
                                    page.evaluate("window._denyCopy=false")
                                    key(page.locator("#vf-share-copy"))
                                    page.wait_for_function("window._copies.length===1")
                                    assert page.evaluate("window._copies[0]") == link
                                shared = context.new_page()
                                shared.goto(link)
                                expect(shared.locator(".v").last).to_have_text(secret.strip())
                                shared.close()
                                page.route(url, fail)
                                key(page.locator("#vf-share-revoke"))
                                expect(page.locator("#vf-error")).to_contain_text(
                                    "could not confirm revocation"
                                )
                                assert api.get(link.split("#")[0] + "/data").ok
                                page.unroute(url)
                                key(page.locator("#vf-share-revoke"))
                                expect(page.locator("#vf-share-result")).to_be_hidden()
                                assert api.get(link.split("#")[0] + "/data").status == 404
                        else:
                            key(page.locator('[data-copy="vf-f-password"]'))
                            page.wait_for_function("window._copies.length===1")
                            assert page.evaluate("window._copies[0]") == secret
                            upload()
                            expect(page.locator(".vf-attach-row")).to_have_count(1)
                            with page.expect_download() as pending:
                                key(page.locator("[data-dl]"))
                            assert Path(pending.value.path()).read_bytes() == content
                            key(page.locator("#vf-x"))
                            key(page.locator("#vault-lock-btn"))
                            page.locator("#vault-pw-input").fill(master)
                            key(page.locator("#vault-unlock-btn"))
                            key(row.locator("[data-vault-open]"))
                            expect(page.locator(".vf-attach-row")).to_have_count(1)
                            expect(page.locator("#vf-f-password")).to_have_value(secret)
                    assert not errors, errors
                    assert all(
                        any(str(code) in message for code in [403, 404, 503]) for message in console
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), (
                        "horizontal overflow"
                    )
                    result["status"] = "passed"
                except Exception as error:
                    result["error"] = str(error)
                    result["traceback"] = traceback.format_exc()
                finally:
                    page.screenshot(path=str(output / f"{case}-{width}.png"), full_page=True)
                    api.delete(endpoint, headers=headers)
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(results, indent=2))
        browser.close()
        api.dispose()
    print(json.dumps(results, indent=2))
    raise SystemExit(any(result["status"] != "passed" for result in results))


if __name__ == "__main__":
    run()
