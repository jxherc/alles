"""The old Home flag and links now use the same safe capture and Aide shell."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
            page.goto(f"{base}/?app=home&keep=flag-off", wait_until="networkidle")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            expect(page.locator("#today-view")).to_be_visible()
            assert not page.locator("#home-view").is_visible()
            assert parse_qs(urlparse(page.url).query).get("keep") == ["flag-off"]
            build = context.request.get(f"{base}/api/system/build")
            assert build.ok and build.json()["feature_flags"]["afterlife_today"] is True
            capture = page.locator("#today-capture-input")
            mode = page.locator("#today-capture-mode")
            submit = page.locator('#today-capture [type="submit"]')
            for control in (capture, mode, submit):
                box = control.bounding_box()
                assert box and box["width"] >= 44 and box["height"] >= 44, box
            mode.click()
            expect(mode).to_have_attribute("aria-pressed", "false")

            title = f"capture collision {width}"
            original = context.request.post(
                f"{base}/api/vault-md/file",
                data={"path": title, "content": "owner original\n"},
            )
            assert original.ok, original.text()
            names_requests: list[str] = []
            page.on(
                "request",
                lambda request: (
                    names_requests.append(request.url)
                    if request.url.endswith("/api/vault-md/names")
                    else None
                ),
            )
            capture.fill(title)
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/vault-md/file")
                    and response.request.method == "POST"
                )
            ) as saved:
                submit.click()
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
                assert response.ok and response.json()["content"] == expected

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
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/vault-md/file")
                    and response.request.method == "POST"
                )
            ):
                submit.click()
            expect(page.locator("#today-capture")).not_to_have_attribute("aria-busy", "true")
            expect(page.locator("#today-status")).to_contain_text(
                "could not confirm note; check Docs before retrying"
            )
            expect(capture).to_have_value(f"failed capture {width}")
            expect(capture).to_be_focused()
            expected_failure[0] = False
            assert len(expected_errors) == 1, expected_errors
            page.unroute("**/api/vault-md/file")

            mode.click()
            expect(mode).to_have_attribute("aria-pressed", "true")
            capture.fill(f"captured task {width}")
            submit.click()
            expect(page.locator(".capture-review")).to_be_visible()
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/tasks") and response.request.method == "POST"
                )
            ) as task_response:
                page.locator("#capture-accept").click()
            assert task_response.value.ok and task_response.value.json().get("id")
            expect(capture).to_have_value("")
            expect(page.locator(".capture-status")).to_contain_text("saved in plan")
            page.locator("#capture-cancel").click()

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
            submit.click()
            expect(page.locator(".capture-review")).to_be_visible()
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/tasks") and response.request.method == "POST"
                )
            ) as queued:
                page.locator("#capture-accept").click()
            expect(page.locator("#today-capture")).not_to_have_attribute("aria-busy", "true")
            expect(capture).to_have_value(f"queued task {width}")
            expect(page.locator(".capture-status")).to_contain_text("same acceptance")
            page.unroute("**/api/tasks")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/tasks") and response.request.method == "POST"
                )
            ) as confirmed:
                page.locator("#capture-accept").click()
            assert confirmed.value.ok, confirmed.value.text()
            assert confirmed.value.request.post_data_json == queued.value.request.post_data_json
            expect(page.locator(".capture-status")).to_contain_text("saved in plan")
            expect(capture).to_have_value("")
            saved_tasks = context.request.get(f"{base}/api/tasks").json()
            assert (
                len([task for task in saved_tasks if task["title"] == f"queued task {width}"]) == 1
            )
            page.locator("#capture-cancel").click()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.screenshot(path=str(output / f"home-capture-{width}.png"), full_page=True)

            persona = context.request.post(
                f"{base}/api/personas", data={"name": f"private helper {width}"}
            )
            assert persona.ok, persona.text()
            session = context.request.post(
                f"{base}/api/sessions", data={"name": f"returning chat {width}"}
            )
            assert session.ok, session.text()
            page.evaluate("window._refreshPersonaBtn()")
            expect(page.locator("#persona-btn")).to_be_hidden()
            page.locator("#app-drawer-btn").click()
            page.locator('.app-drawer-item[data-view="chat"]').click()
            expect(page.locator("#chat")).to_be_visible()
            expect(page.locator("#persona-btn")).to_be_visible()
            page.evaluate("window._reloadAideSessions()")
            if page.locator("body").evaluate("body => body.classList.contains('sidebar-hidden')"):
                page.locator("#sidebar-toggle-btn").click()
            page.locator(f'.session-item[data-id="{session.json()["id"]}"] .session-open').click()
            expect(page.locator("#session-actions-btn")).to_be_visible()
            page.goto(f"{base}/?view=home", wait_until="networkidle")
            expect(page.locator("#today-view")).to_be_visible()
            expect(page.locator("#persona-btn")).to_be_hidden()
            expect(page.locator("#session-actions-btn")).to_be_hidden()
            assert not errors, errors
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
