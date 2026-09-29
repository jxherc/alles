"""Docs tabs and browser history keep unsaved documents visible on draft failure."""

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
            page.on("pageerror", lambda error: errors.append(str(error)))
            name = f"workbench-navigation-{width}.md"
            original = "# original\n"
            changed = "# keep this unsaved draft\n"
            seed = context.request.post(
                base + "/api/vault-md/file",
                data={"path": name, "content": original},
            )
            assert seed.ok, seed.text()
            assert context.request.post(base + "/api/setup/dismiss").ok
            page.goto(f"{base}/?view=wiki&doc={name}", wait_until="networkidle")
            expect(page.locator("#setup-wizard")).to_be_hidden()
            expect(page.locator("#wiki-preview")).to_contain_text("original")
            assert page.evaluate("Number.isSafeInteger(history.state?.__allesRoutePosition)")
            page.locator("#wiki-edit-btn").click()
            page.locator("#wiki-source-btn").click()
            source = page.locator("#wiki-source")
            expect(source).to_be_visible()

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
            source.fill(changed)
            journal_tab = page.locator('#docs-workbench-view [data-group-section="journal"]')
            journal_tab.focus()
            journal_tab.press("Enter")
            expect(page.locator("#wiki-save-state")).to_have_text("synthetic draft outage")
            expect(page.locator("#wiki-save-state")).to_be_visible()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            ), width
            expect(
                page.locator('#docs-workbench-view [data-group-section="notes"]')
            ).to_have_attribute("aria-selected", "true")
            expect(page.locator("#docs-journal-section")).to_be_hidden()
            expect(source).to_have_value(changed)
            file_response = context.request.get(base + "/api/vault-md/file", params={"path": name})
            assert file_response.ok, file_response.text()
            assert file_response.json()["content"] == original
            page.screenshot(path=str(output / f"docs-workbench-guard-{width}.png"))

            page.unroute("**/api/vault-md/safety/draft", fail_draft)
            journal_tab.press("Enter")
            expect(page.locator("#docs-journal-section")).to_be_visible()
            assert page.evaluate("Number.isSafeInteger(history.state?.__allesRoutePosition)")
            draft = context.request.get(base + "/api/vault-md/safety/draft", params={"path": name})
            assert draft.ok, draft.text()
            assert draft.json()["draft"]["content"] == changed

            documents_tab = page.locator('#docs-workbench-view [data-group-section="notes"]')
            documents_tab.click()
            expect(source).to_be_visible()
            documents_url = page.url
            back_edit = "# back must keep this draft\n"
            source.fill(back_edit)
            page.route("**/api/vault-md/safety/draft", fail_draft)
            page.go_back()
            expect(page).to_have_url(documents_url)
            expect(documents_tab).to_have_attribute("aria-selected", "true")
            expect(page.locator("#docs-journal-section")).to_be_hidden()
            expect(source).to_have_value(back_edit)
            expect(page.locator("#wiki-save-state")).to_have_text("synthetic draft outage")

            page.unroute("**/api/vault-md/safety/draft", fail_draft)
            page.go_back()
            expect(page.locator("#docs-journal-section")).to_be_visible()
            page.go_back()
            expect(source).to_be_visible()
            forward_documents_url = page.url
            forward_edit = "# forward must keep this draft\n"
            source.fill(forward_edit)
            page.route("**/api/vault-md/safety/draft", fail_draft)
            page.go_forward()
            expect(page).to_have_url(forward_documents_url)
            expect(documents_tab).to_have_attribute("aria-selected", "true")
            expect(page.locator("#docs-journal-section")).to_be_hidden()
            expect(source).to_have_value(forward_edit)
            expect(page.locator("#wiki-save-state")).to_have_text("synthetic draft outage")
            page.unroute("**/api/vault-md/safety/draft", fail_draft)
            page.go_forward()
            expect(page.locator("#docs-journal-section")).to_be_visible()
            draft = context.request.get(base + "/api/vault-md/safety/draft", params={"path": name})
            assert draft.ok, draft.text()
            assert draft.json()["draft"]["content"] == forward_edit

            documents_tab.click()
            expect(source).to_be_visible()
            page.evaluate("window._navigateHome()")
            expect(page.locator("#today-view")).to_be_visible()
            page.go_back()
            expect(source).to_be_visible()
            home_forward_url = page.url
            home_edit = "# home forward must keep this draft\n"
            source.fill(home_edit)
            page.route("**/api/vault-md/safety/draft", fail_draft)
            page.go_forward()
            expect(page).to_have_url(home_forward_url)
            expect(source).to_have_value(home_edit)
            expect(page.locator("#today-view")).to_be_hidden()
            expect(page.locator("#wiki-save-state")).to_have_text("synthetic draft outage")
            page.unroute("**/api/vault-md/safety/draft", fail_draft)
            page.go_forward()
            expect(page.locator("#today-view")).to_be_visible()
            draft = context.request.get(base + "/api/vault-md/safety/draft", params={"path": name})
            assert draft.ok, draft.text()
            assert draft.json()["draft"]["content"] == home_edit
            if width == 1440:
                page.evaluate("window._navigateTo('docs')")
                expect(source).to_be_visible()
                page.evaluate("history.pushState(null, '', '?view=journal')")
                page.go_back()
                expect(source).to_be_visible()
                legacy_forward_url = page.url
                legacy_edit = "# an older forward entry must keep this draft\n"
                source.fill(legacy_edit)
                page.route("**/api/vault-md/safety/draft", fail_draft)
                page.go_forward()
                expect(page).to_have_url(legacy_forward_url)
                expect(source).to_have_value(legacy_edit)
                expect(page.locator("#docs-journal-section")).to_be_hidden()
                expect(page.locator("#wiki-save-state")).to_have_text("synthetic draft outage")
                page.unroute("**/api/vault-md/safety/draft", fail_draft)

                no_index = page.evaluate(
                    """() => {
                      Object.defineProperty(window, 'navigation', {
                        value: undefined, configurable: true,
                      });
                      return window.navigation === undefined;
                    }"""
                )
                assert no_index
                page.evaluate("history.pushState(null, '', '?view=journal')")
                page.go_back()
                expect(source).to_be_visible()
                fallback_url = page.url
                fallback_edit = "# no browser index must keep this draft\n"
                source.fill(fallback_edit)
                page.route("**/api/vault-md/safety/draft", fail_draft)
                page.go_forward()
                expect(page).to_have_url(fallback_url)
                expect(source).to_have_value(fallback_edit)
                expect(page.locator("#docs-journal-section")).to_be_hidden()
                page.unroute("**/api/vault-md/safety/draft", fail_draft)
                journal_tab.click()
                expect(page.locator("#docs-journal-section")).to_be_visible()
                draft = context.request.get(
                    base + "/api/vault-md/safety/draft", params={"path": name}
                )
                assert draft.ok, draft.text()
                assert draft.json()["draft"]["content"] == fallback_edit
            assert not errors, errors
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
