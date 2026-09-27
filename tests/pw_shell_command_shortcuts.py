"""The universal command opens by keyboard without stealing text entry."""

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
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )

            page.goto(base, wait_until="networkidle")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            expect(page.locator("#today-view")).to_be_visible()
            settings = page.locator("#today-settings")
            settings.focus()
            settings.press("Meta+k")
            expect(page.locator("#search-modal")).to_be_visible()
            expect(page.locator("#search-input")).to_be_focused()
            page.screenshot(path=str(output / f"command-{width}.png"))
            page.keyboard.press("Escape")
            expect(page.locator("#search-modal")).to_be_hidden()
            expect(settings).to_be_focused()

            capture = page.locator("#today-capture-input")
            capture.fill("draft")
            capture.press("/")
            expect(capture).to_have_value("draft/")
            expect(page.locator("#search-modal")).to_be_hidden()

            settings.focus()
            settings.press("/")
            expect(page.locator("#search-modal")).to_be_visible()
            page.keyboard.press("Escape")
            expect(settings).to_be_focused()

            page.evaluate(
                "localStorage.setItem('aide-shortcuts', JSON.stringify({search: 'Alt+P'}))"
            )
            settings.press("Alt+p")
            expect(page.locator("#search-modal")).to_be_visible()
            page.keyboard.press("Escape")

            page.locator("#app-drawer-btn").click()
            page.locator('.app-drawer-item[data-view="chat"]').click()
            composer = page.locator("#composer-ta")
            expect(composer).to_be_visible()
            composer.fill("")
            composer.press("/")
            expect(composer).to_have_value("/")
            expect(page.locator("#search-modal")).to_be_hidden()

            name = f"command-shortcut-{width}.md"
            seed = context.request.post(
                base + "/api/vault-md/file",
                data={"path": name, "content": "# command shortcut\n"},
            )
            assert seed.ok, seed.text()
            page.goto(f"http://docs.localhost:{port}/?doc={name}", wait_until="networkidle")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            expect(page.locator("#wiki-preview")).to_contain_text("command shortcut")
            page.locator("#wiki-edit-btn").click()
            page.locator("#wiki-source-btn").click()
            source = page.locator("#wiki-source")
            expect(source).to_be_visible()
            source.focus()
            source.press("Meta+k")
            expect(page.locator("#search-modal")).to_be_hidden()
            assert not errors, errors
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
