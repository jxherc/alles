"""Legacy Home capture must never report an existing document as a new save."""

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
        for width in (1440, 720, 390):
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
            expected_failure = [False]
            expected_errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def console(message):
                if message.type != "error":
                    return
                if expected_failure[0] and "503" in message.text:
                    expected_errors.append(message.text)
                else:
                    errors.append(message.text)

            page.on("console", console)
            page.goto(base, wait_until="networkidle")
            page.locator("#home-view").wait_for(state="visible")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            for selector in (
                "#hc-input",
                "#hc-save",
                '.hc-mode[data-mode="note"]',
                '.hc-mode[data-mode="task"]',
            ):
                box = page.locator(selector).bounding_box()
                assert box and box["width"] >= 44 and box["height"] >= 44, (selector, box)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )

            title = f"capture collision {width}"
            original = context.request.post(
                f"{base}/api/vault-md/file",
                data={"path": title, "content": "owner original\n"},
            )
            assert original.ok, original.text()

            names_requests = []

            def stale_names(route):
                names_requests.append(route.request.url)
                route.fulfill(status=200, content_type="application/json", body='{"names":[]}')

            page.route("**/api/vault-md/names", stale_names)
            capture = page.locator("#hc-input")
            capture.fill(title)
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/vault-md/file")
                    and response.request.method == "POST"
                )
            ) as saved:
                page.locator("#hc-save").click()
            result = saved.value.json()
            assert result.get("created") is True, result
            assert result["path"] == f"{title} 2.md", result
            expect(capture).to_have_value("")
            expect(page.locator("#toast-container .toast.success").last).to_have_text("note saved")
            assert not names_requests, names_requests

            for path, expected in (
                (f"{title}.md", "owner original\n"),
                (f"{title} 2.md", f"{title}\n"),
            ):
                response = context.request.get(f"{base}/api/vault-md/file", params={"path": path})
                assert response.ok, response.text()
                assert response.json()["content"] == expected

            capture.fill(f"failed capture {width}")
            page.route(
                "**/api/vault-md/file",
                lambda route: (
                    route.fulfill(status=503, body="unavailable")
                    if route.request.method == "POST"
                    else route.continue_()
                ),
            )
            expected_failure[0] = True
            page.locator("#hc-save").click()
            expect(page.locator("#toast-container .toast.error").last).to_contain_text(
                "could not confirm note; check Docs before retrying"
            )
            expect(capture).to_have_value(f"failed capture {width}")
            active = page.evaluate("document.activeElement?.id")
            assert active == "hc-input", active
            expected_failure[0] = False
            assert len(expected_errors) == 1, expected_errors
            page.unroute("**/api/vault-md/file")

            page.locator('.hc-mode[data-mode="task"]').click()
            capture.fill(f"captured task {width}")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/tasks") and response.request.method == "POST"
                )
            ) as task_response:
                capture.press("Enter")
            assert task_response.value.ok, task_response.value.text()
            expect(capture).to_have_value("")
            expect(page.locator("#toast-container .toast.success").last).to_have_text("task added")

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
            capture.fill(f"queued task {width}")
            capture.press("Enter")
            expect(capture).to_have_value("")
            expect(page.locator("#toast-container .toast").last).to_have_text(
                "task queued; it will sync when online"
            )
            page.unroute("**/api/tasks")
            page.screenshot(path=str(output / f"home-capture-{width}.png"), full_page=True)
            assert not errors, errors
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
