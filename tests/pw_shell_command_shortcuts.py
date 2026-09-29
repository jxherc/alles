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
            expected_draft_failure = [False]
            page.on("pageerror", lambda error: errors.append(str(error)))

            def console(message):
                if message.type != "error":
                    return
                if expected_draft_failure[0] and "503" in message.text:
                    return
                errors.append(message.text)

            page.on("console", console)

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
                data={"path": name, "content": f"# command shortcut {width}\n"},
            )
            assert seed.ok, seed.text()
            session = context.request.post(
                base + "/api/sessions", data={"name": f"palette chat {width}"}
            )
            assert session.ok, session.text()
            session_id = session.json()["id"]

            page.goto(f"http://localhost:{port}/", wait_until="networkidle")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            page.locator("#today-settings").press("Meta+k")
            page.locator("#search-input").fill(name.removesuffix(".md"))
            note = page.locator(f'#search-results [data-type="note"][data-path="{name}"]')
            expect(note).to_be_visible()
            note.click()
            expect(page).to_have_url(f"http://docs.localhost:{port}/#{name.removesuffix('.md')}")
            expect(page.locator("#wiki-preview")).to_contain_text(f"command shortcut {width}")

            page.goto(f"http://localhost:{port}/", wait_until="networkidle")
            page.locator("#today-settings").press("Meta+k")
            page.locator("#search-input").fill(f"palette chat {width}")
            chat = page.locator(f'#search-results [data-type="chat"][data-id="{session_id}"]')
            expect(chat).to_be_visible()
            chat.click()
            expect(page).to_have_url(f"http://aide.localhost:{port}/#{session_id}")
            expect(page.locator("#chat")).to_be_visible()
            page.wait_for_function("id => window._currentSession?.id === id", arg=session_id)

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

            def fail_draft(route):
                if route.request.method == "PUT":
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic draft outage"}',
                    )
                else:
                    route.continue_()

            page.route("**/api/vault-md/safety/draft", fail_draft)
            expected_draft_failure[0] = True
            changed = f"# unsaved palette draft {width}\n"
            source.fill(changed)
            page.locator("#app-drawer-btn").press("Meta+k")
            expect(page.locator("#search-modal")).to_be_visible()
            page.locator("#search-input").fill(f"palette chat {width}")
            chat = page.locator(f'#search-results [data-type="chat"][data-id="{session_id}"]')
            expect(chat).to_be_visible()
            chat.click()
            expect(page.locator("#search-modal")).to_be_visible()
            expect(page.locator("#search-results .search-open-error")).to_be_visible()
            page.wait_for_timeout(800)
            expect(page.locator("#search-results .search-open-error")).to_be_visible()
            expect(page.locator("#search-input")).to_be_focused()
            expect(source).to_have_value(changed)
            assert page.url.startswith(f"http://docs.localhost:{port}/")
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.screenshot(path=str(output / f"command-draft-guard-{width}.png"))

            page.locator("#search-input").fill("home")
            home = page.locator('#search-results [data-type="nav"][data-view="today"]')
            expect(home).to_be_visible()
            home.click()
            expect(page.locator("#search-modal")).to_be_visible()
            expect(page.locator("#search-results .search-open-error")).to_be_visible()
            expect(source).to_have_value(changed)
            assert page.url.startswith(f"http://docs.localhost:{port}/")

            page.unroute("**/api/vault-md/safety/draft", fail_draft)
            expected_draft_failure[0] = False
            page.locator("#search-input").fill(f"palette chat {width}")
            chat = page.locator(f'#search-results [data-type="chat"][data-id="{session_id}"]')
            expect(chat).to_be_visible()
            chat.press("Enter")
            expect(page).to_have_url(f"http://aide.localhost:{port}/#{session_id}")
            draft = context.request.get(base + "/api/vault-md/safety/draft", params={"path": name})
            assert draft.ok and draft.json()["draft"]["content"] == changed

            page.goto(base, wait_until="networkidle")
            page.locator("#today-settings").press("Meta+k")
            page.locator("#search-input").fill(name.removesuffix(".md"))
            note = page.locator(f'#search-results [data-type="note"][data-path="{name}"]')
            expect(note).to_be_visible()
            note.press("Enter")
            expect(page.locator("#wiki-preview")).to_contain_text(f"command shortcut {width}")
            expect(page.locator("#search-modal")).to_be_hidden()
            expect(page.locator("#wiki-preview")).to_be_focused()
            assert page.url.startswith(base + "/")

            page.goto(base, wait_until="networkidle")
            page.locator("#today-settings").press("Meta+k")
            page.locator("#search-input").fill(f"palette chat {width}")
            chat = page.locator(f'#search-results [data-type="chat"][data-id="{session_id}"]')
            expect(chat).to_be_visible()
            chat.click()
            expect(page.locator("#chat")).to_be_visible()
            page.wait_for_function("id => window._currentSession?.id === id", arg=session_id)
            expect(page.locator("#composer-ta")).to_be_focused()
            assert page.url.startswith(base + "/")
            assert not errors, errors
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
