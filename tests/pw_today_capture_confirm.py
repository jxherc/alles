"""Current Home must distinguish a confirmed save, an offline queue, and an unknown outcome."""

from __future__ import annotations

import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run() -> None:
    port = os.environ["PORT"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    base = f"http://127.0.0.1:{port}"
    require_server_ownership(base, run_id)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                is_mobile=width == 390,
                has_touch=width == 390,
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(15_000)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base, wait_until="networkidle")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            expect(page.locator("#today-view")).to_be_visible()
            capture = page.locator("#today-capture-input")
            form = page.locator("#today-capture")
            submit = page.locator('#today-capture [type="submit"]')
            mode = page.locator("#today-capture-mode")
            for control in (capture, submit, mode):
                box = control.bounding_box()
                assert box and box["height"] >= 44, (control, box)

            page.route(
                "**/api/tasks",
                lambda route: (
                    route.fulfill(status=200, content_type="application/json", body="{}")
                    if route.request.method == "POST"
                    else route.continue_()
                ),
            )
            capture.fill("task with unknown result")
            submit.click()
            expect(page.locator(".capture-review")).to_be_visible()
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/tasks") and response.request.method == "POST"
                )
            ) as unknown:
                page.locator("#capture-accept").click()
            expect(form).not_to_have_attribute("aria-busy", "true")
            expect(capture).to_have_value("task with unknown result")
            expect(page.locator(".capture-status")).to_contain_text("same acceptance")
            expect(page.locator("#capture-accept")).to_be_focused()
            page.unroute("**/api/tasks")

            page.route(
                "**/api/tasks",
                lambda route: (
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body='{"queued":true,"offline":true}',
                    )
                    if route.request.method == "POST"
                    else route.continue_()
                ),
            )
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/tasks") and response.request.method == "POST"
                )
            ) as queued:
                page.locator("#capture-accept").click()
            expect(form).not_to_have_attribute("aria-busy", "true")
            expect(capture).to_have_value("task with unknown result")
            expect(page.locator(".capture-status")).to_contain_text("same acceptance")
            assert queued.value.request.post_data_json == unknown.value.request.post_data_json
            page.unroute("**/api/tasks")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/tasks") and response.request.method == "POST"
                )
            ) as confirmed:
                page.locator("#capture-accept").click()
            assert confirmed.value.ok, confirmed.value.text()
            assert confirmed.value.request.post_data_json == unknown.value.request.post_data_json
            expect(page.locator(".capture-status")).to_contain_text("saved in plan")
            expect(capture).to_have_value("")
            page.locator("#capture-cancel").click()

            mode.click()
            expect(mode).to_have_attribute("aria-pressed", "false")
            page.route(
                "**/api/vault-md/file",
                lambda route: (
                    route.fulfill(
                        status=200, content_type="application/json", body='{"created":false}'
                    )
                    if route.request.method == "POST"
                    else route.continue_()
                ),
            )
            capture.fill("note with unknown result")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/vault-md/file")
                    and response.request.method == "POST"
                )
            ):
                submit.click()
            expect(form).not_to_have_attribute("aria-busy", "true")
            expect(capture).to_have_value("note with unknown result")
            expect(page.locator("#today-status")).to_contain_text(
                "could not confirm note; check Docs before retrying"
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.screenshot(
                path=str(output / f"today-capture-uncertain-{width}.png"), full_page=True
            )
            page.unroute("**/api/vault-md/file")

            page.route(
                "**/api/vault-md/file",
                lambda route: (
                    route.fulfill(status=503, body="unavailable")
                    if route.request.method == "POST"
                    else route.continue_()
                ),
            )
            capture.fill("note with lost response")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/vault-md/file")
                    and response.request.method == "POST"
                )
            ):
                submit.click()
            expect(form).not_to_have_attribute("aria-busy", "true")
            expect(capture).to_have_value("note with lost response")
            expect(page.locator("#today-status")).to_contain_text(
                "could not confirm note; check Docs before retrying"
            )
            page.unroute("**/api/vault-md/file")

            real = f"confirmed note {width}"
            capture.fill(real)
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/vault-md/file")
                    and response.request.method == "POST"
                )
            ) as response:
                submit.click()
            expect(form).not_to_have_attribute("aria-busy", "true")
            assert response.value.json().get("created") is True
            expect(capture).to_have_value("")
            expect(page.locator("#toast-container .toast.success").last).to_have_text("note saved")
            saved = context.request.get(f"{base}/api/vault-md/file", params={"path": f"{real}.md"})
            assert saved.ok and saved.json()["content"] == f"{real}\n"
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            assert not errors, errors
            page.screenshot(path=str(output / f"today-capture-confirm-{width}.png"), full_page=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
