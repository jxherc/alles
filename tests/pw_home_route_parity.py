"""Old Home links, browser history, and retired app hosts reach their current owners."""

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
            page.goto(f"{base}/?app=home&keep=a%2Bb", wait_until="networkidle")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            expect(page.locator("#today-view")).to_be_visible()
            parsed = urlparse(page.url)
            assert parse_qs(parsed.query).get("keep") == ["a+b"], page.url
            query = parse_qs(parsed.query)
            assert "app" not in query and query.get("view", ["today"])[0] in ("home", "today"), (
                page.url
            )

            plan = page.locator('#today-sections .today-shortcut[data-view="plan"]')
            plan.focus()
            plan.press("Enter")
            expect(page.locator("#plan-view")).to_be_visible()
            page.go_back(wait_until="networkidle")
            expect(page.locator("#today-view")).to_be_visible()
            page.go_forward(wait_until="networkidle")
            expect(page.locator("#plan-view")).to_be_visible()
            page.goto(f"{base}/?view=today&keep=still-here", wait_until="networkidle")
            expect(page.locator("#today-view")).to_be_visible()
            assert parse_qs(urlparse(page.url).query).get("keep") == ["still-here"]
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            assert not errors, errors
            page.screenshot(path=str(output / f"home-route-{width}.png"), full_page=True)
            context.close()

        context = browser.new_context(reduced_motion="reduce", service_workers="block")
        page = context.new_page()
        page.set_default_timeout(15_000)
        page.goto(f"http://home.localhost:{port}/?keep=home-link#anchor", wait_until="networkidle")
        expect(page.locator("#today-view")).to_be_visible()
        parsed = urlparse(page.url)
        assert parsed.hostname == "localhost", page.url
        assert parse_qs(parsed.query).get("keep") == ["home-link"], page.url
        assert parsed.fragment == "anchor", page.url

        for old_host, current_host, root, section in (
            ("days", "plan", "#plan-view", "days"),
            ("journal", "docs", "#docs-workbench-view", "journal"),
            ("gallery", "files", "#files-workbench-view", "gallery"),
            ("activity", "server", "#server-workbench-view", "activity"),
            ("watch", "server", "#server-workbench-view", "watch"),
        ):
            page.goto(f"http://{old_host}.localhost:{port}/", wait_until="networkidle")
            expect(page.locator(root)).to_be_visible()
            assert urlparse(page.url).hostname == f"{current_host}.localhost", page.url
            expect(page.locator(f'{root} [data-group-section="{section}"]')).to_have_attribute(
                "aria-selected", "true"
            )
        context.close()
        browser.close()


if __name__ == "__main__":
    run()
