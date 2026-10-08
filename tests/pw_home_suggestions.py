"""Current Home keeps opted-in suggestions usable without hiding uncertain outcomes."""

from __future__ import annotations

import json
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
        for width, theme in ((1440, "dark"), (1440, "light"), (390, "dark"), (390, "light")):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                is_mobile=width == 390,
                has_touch=width == 390,
                color_scheme=theme,
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(15_000)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            cards: list[dict] = []
            fail_get = False
            outcomes = {
                "act": [{}, {"queued": True, "offline": True}, {"ok": True}],
                "dismiss": [None, {"queued": True, "offline": True}, {"ok": True}],
            }
            model_calls: list[str] = []

            def intercept(route):
                nonlocal fail_get
                request = route.request
                suffix = request.url.split("/api/proactive", 1)[1]
                if request.method == "GET" and suffix == "":
                    if fail_get:
                        route.fulfill(status=503, body="unavailable")
                    else:
                        route.fulfill(
                            status=200, content_type="application/json", body=json.dumps(cards)
                        )
                    return
                if request.method == "POST" and suffix.endswith(("/act", "/dismiss")):
                    action = suffix.rsplit("/", 1)[1]
                    result = outcomes[action].pop(0)
                    if result is None:
                        route.fulfill(status=503, body="unavailable")
                    else:
                        if result.get("ok") is True:
                            item_id = suffix.strip("/").split("/", 1)[0]
                            cards[:] = [card for card in cards if card["id"] != item_id]
                        route.fulfill(
                            status=200, content_type="application/json", body=json.dumps(result)
                        )
                    return
                route.continue_()

            page.route("**/api/proactive**", intercept)
            page.on(
                "request",
                lambda request: (
                    model_calls.append(request.url)
                    if request.method == "POST"
                    and ("/api/chat" in request.url or request.url.endswith("/api/proactive/run"))
                    else None
                ),
            )
            page.goto(base, wait_until="networkidle")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            expect(page.locator("#today-view")).to_be_visible()
            expect(page.locator(".today-suggestions")).to_have_count(0)
            page.evaluate(
                """async mode => {
                  const { PRESETS } = await import('/static/js/theme.js');
                  localStorage.setItem('alles-appearance', JSON.stringify({
                    preset: mode, colors: PRESETS[mode].colors,
                  }));
                }""",
                theme,
            )

            cards[:] = [
                {
                    "id": "suggest-act",
                    "title": '<img src=x onerror="alert(1)"> review the plan',
                    "body": "aide noticed a dated task",
                    "link": "tasks",
                },
                {
                    "id": "suggest-dismiss",
                    "title": "a thought, not a link",
                    "body": "very long context " + "details " * 50 + "<script>alert(1)</script>",
                    "link": "",
                },
            ]
            page.reload(wait_until="networkidle")
            section = page.locator(".today-suggestions")
            expect(section).to_be_visible()
            applied_theme = page.evaluate("document.documentElement.dataset.theme || 'dark'")
            assert applied_theme == theme, (width, theme, applied_theme)
            expect(section.locator(".today-suggestion")).to_have_count(2)
            assert section.locator("img, script").count() == 0
            assert section.locator("[data-suggestion-act]").count() == 1
            for button in section.locator("button").all():
                box = button.bounding_box()
                assert box and box["height"] >= 44, box
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.screenshot(
                path=str(output / f"home-suggestions-{width}-{theme}.png"), full_page=True
            )

            act = section.locator('[data-suggestion-act="suggest-act"]')
            for _ in range(2):
                with page.expect_response(
                    lambda response: response.url.endswith("/suggest-act/act")
                ):
                    act.click()
                expect(section.locator(".today-suggestion")).to_have_count(2)
                expect(section.locator(".today-suggestion-status").first).to_contain_text(
                    "could not confirm"
                )
            act.focus()
            with page.expect_response(lambda response: response.url.endswith("/suggest-act/act")):
                act.press("Enter")
            expect(page.locator("#plan-view")).to_be_visible()
            page.goto(base, wait_until="networkidle")
            expect(section.locator(".today-suggestion")).to_have_count(1)
            assert section.locator("[data-suggestion-act]").count() == 0

            dismiss = section.locator('[data-suggestion-dismiss="suggest-dismiss"]')
            for _ in range(2):
                with page.expect_response(
                    lambda response: response.url.endswith("/suggest-dismiss/dismiss")
                ):
                    dismiss.click()
                expect(section.locator(".today-suggestion")).to_have_count(1)
                expect(section.locator(".today-suggestion-status")).to_contain_text(
                    "could not confirm"
                )
            dismiss.focus()
            with page.expect_response(
                lambda response: response.url.endswith("/suggest-dismiss/dismiss")
            ):
                dismiss.press("Enter")
            expect(section).to_have_count(0)
            expect(page.locator("#today-settings")).to_be_focused()
            page.reload(wait_until="networkidle")
            expect(section).to_have_count(0)

            fail_get = True
            page.reload(wait_until="networkidle")
            expect(page.locator("#today-status")).to_contain_text("suggestions")
            expect(section).to_have_count(0)
            assert not model_calls, model_calls
            assert not errors, errors
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
