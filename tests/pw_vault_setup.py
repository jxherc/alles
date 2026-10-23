"""First-run Vault and existing-entry authentication recovery on fresh owned data."""

import json
import os
import sys
import uuid
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    profile = sys.argv[1]
    width = 390 if profile == "phone" else 1440
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    scenarios = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": width, "height": 900},
            reduced_motion="reduce",
            service_workers="block",
            is_mobile=width == 390,
            has_touch=width == 390,
        )
        page = context.new_page()
        page.set_default_timeout(10000)
        api = context.request
        assert api.post(base + "/api/setup/dismiss").ok
        password, replacement = str(uuid.uuid4()), str(uuid.uuid4())
        secret, corrected = str(uuid.uuid4()).center(42), str(uuid.uuid4()).center(44)
        errors, console, unlocks, posts = [], [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: console.append(message.text) if message.type == "error" else None,
        )
        page.on(
            "request",
            lambda request: (
                posts.append(request.url)
                if request.url.endswith("/api/vault/unlock") and request.method == "POST"
                else None
            ),
        )

        def observe(response):
            if response.url.endswith("/api/vault/unlock") and response.ok:
                unlocks.append(response.json()["token"])

        page.on("response", observe)

        def begin(name):
            record = {
                "scenario_id": "vault.setup." + name,
                "feature_id": "passwords.vault-and-browser",
                "profile": profile,
                "status": "failed",
            }
            scenarios.append(record)
            checkpoint()
            return record

        def checkpoint():
            (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2))

        def passed(record):
            record["status"] = "passed"
            checkpoint()

        def unlock(value):
            page.locator("#vault-pw-input").fill(value)
            expect(page.locator("#vault-unlock-btn")).to_be_enabled()
            page.locator("#vault-unlock-btn").focus()
            page.keyboard.press("Enter")

        def reveal():
            page.get_by_role("button", name="open daily credential", exact=True).click()
            expect(page.locator("#vf-f-password")).to_be_visible()

        record = begin("first-run-confirmation")
        try:
            page.goto(base + "/?view=vault", wait_until="networkidle")
            expect(page.locator("#vault-unlock-btn")).to_have_text("create vault")
            expect(page.locator("#vault-lock-help")).to_contain_text(
                "separate from your alles sign-in"
            )
            expect(page.locator("#vault-pw-confirm")).to_be_visible()
            page.locator("#vault-pw-confirm").fill("short")
            unlock("short")
            expect(page.locator("#vault-unlock-error")).to_contain_text("12")
            page.locator("#vault-pw-confirm").fill(replacement)
            unlock(password)
            expect(page.locator("#vault-unlock-error")).to_contain_text("match")
            assert not posts
            page.screenshot(path=str(output / "setup-confirmation.png"), full_page=True)
            passed(record)

            record = begin("lost-setup-response")

            def lose_setup(route):
                response = route.fetch()
                assert response.ok
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"synthetic setup response unavailable"}',
                )

            page.route(base + "/api/vault/unlock", lose_setup, times=1)
            page.locator("#vault-pw-confirm").fill(password)
            unlock(password)
            expect(page.locator("#vault-unlock-error")).to_contain_text(
                "synthetic setup response unavailable"
            )
            expect(page.locator("#vault-unlock-btn")).to_have_text("unlock")
            expect(page.locator("#vault-pw-confirm")).to_be_hidden()
            unlock(password)
            expect(page.locator("#vault-new-btn")).to_be_visible()
            expect(page.locator("#vault-entry-list")).to_contain_text("no entries")
            passed(record)

            record = begin("store-read-edit-lock")
            page.locator("#vault-new-btn").click()
            page.locator("#vf-name").fill("daily credential")
            page.locator("#vf-f-password").fill(secret)
            page.locator("#vf-save").click()
            expect(page.locator("#vf-name")).to_have_count(0)
            reveal()
            expect(page.locator("#vf-f-password")).to_have_value(secret)
            page.locator("#vf-f-password").fill(corrected)
            page.locator("#vf-save").click()
            expect(page.locator("#vf-name")).to_have_count(0)
            page.locator("#vault-lock-btn").click()
            expect(page.locator("#vault-pw-input")).to_have_value("")
            expect(page.locator("#vault-lock-help")).to_contain_text("cannot reset")
            unlock(replacement)
            expect(page.locator("#vault-unlock-error")).to_contain_text("wrong")
            unlock(password)
            expect(page.locator("#vault-new-btn")).to_be_visible()
            reveal()
            expect(page.locator("#vf-f-password")).to_have_value(corrected)
            passed(record)

            record = begin("expired-existing-edit")
            page.locator("#vf-f-password").fill(secret)
            tok = unlocks[-1]
            assert api.post(base + "/api/vault/lock", headers={"X-Vault-Token": tok}).ok
            page.locator("#vf-save").click()
            expect(page.locator("#vf-name")).to_have_count(0)
            expect(page.locator("#vault-pw-input")).to_be_visible()
            unlock(password)
            expect(page.locator("#vault-new-btn")).to_be_visible()
            reveal()
            expect(page.locator("#vf-f-password")).to_have_value(corrected)
            page.locator("#vf-f-password").fill(secret)
            page.locator("#vf-save").click()
            expect(page.locator("#vf-name")).to_have_count(0)
            page.reload(wait_until="networkidle")
            unlock(password)
            expect(page.locator("#vault-new-btn")).to_be_visible()
            reveal()
            expect(page.locator("#vf-f-password")).to_have_value(secret)
            page.locator("#vf-cancel").click()
            passed(record)

            record = begin("password-change-recovery")
            page.locator("#vault-manage-btn").click()
            page.locator('[data-chpw="default"]').click()
            page.locator("#np-1").fill(replacement)
            page.locator("#np-2").fill(replacement)
            page.locator("#np-ok").click()
            expect(page.locator("#np-1")).to_have_count(0)
            page.locator("#mv-close").click()
            page.locator("#vault-lock-btn").click()
            unlock(password)
            expect(page.locator("#vault-unlock-error")).to_contain_text("wrong")
            unlock(replacement)
            expect(page.locator("#vault-new-btn")).to_be_visible()
            reveal()
            expect(page.locator("#vf-f-password")).to_have_value(secret)
            page.locator("#vf-cancel").click()
            passed(record)

            record = begin("setup-status-retry")
            page.route(
                base + "/api/vault/setup",
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"synthetic status unavailable"}',
                ),
                times=1,
            )
            page.locator("#vault-lock-btn").click()
            expect(page.locator("#vault-unlock-error")).to_contain_text("could not check")
            expect(page.locator("#vault-unlock-btn")).to_be_disabled()
            page.locator("#vault-setup-retry").click()
            expect(page.locator("#vault-unlock-btn")).to_be_enabled()
            unlock(replacement)
            expect(page.locator("#vault-new-btn")).to_be_visible()
            reveal()
            expect(page.locator("#vf-f-password")).to_have_value(secret)
            page.screenshot(path=str(output / "recovered.png"), full_page=True)
            assert not errors, errors
            assert all(
                any(str(status) in message for status in [401, 403, 503]) for message in console
            ), console
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            passed(record)
        except Exception as error:
            record["error"] = str(error)
            checkpoint()
            page.screenshot(path=str(output / "failed.png"), full_page=True)
        finally:
            page.unroute_all(behavior="ignoreErrors")
            context.close()
            browser.close()
    raise SystemExit(any(row["status"] != "passed" for row in scenarios))


if __name__ == "__main__":
    run()
