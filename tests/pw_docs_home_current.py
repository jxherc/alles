"""Single-host regression: Docs Home opens the current Today surface."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8968")
BASE = f"http://127.0.0.1:{PORT}"
OUTPUT = Path(tempfile.gettempdir()) / "alles-docs-home-current.png"


def run() -> None:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(f"page: {error}"))
        page.on(
            "console",
            lambda message: (
                errors.append(f"console: {message.text}") if message.type == "error" else None
            ),
        )

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_function("typeof window._navigateTo === 'function'")
        if page.locator("#setup-wizard").is_visible():
            page.locator("#setup-skip").click()
            page.locator("#setup-wizard").wait_for(state="hidden")
        page.locator('.today-shortcut[data-view="wiki"]').click()
        page.locator("#wiki-view").wait_for(state="visible")
        assert not page.locator("#today-view").is_visible()
        assert not page.locator("#home-view").is_visible()

        page.locator('[data-docs-route="home"]').click()
        page.locator("#today-view").wait_for(state="visible")
        assert not page.locator("#home-view").is_visible()
        assert not page.locator("#wiki-view").is_visible()
        OUTPUT.unlink(missing_ok=True)
        page.screenshot(path=str(OUTPUT), full_page=True)

        context.close()
        browser.close()

    if errors:
        raise AssertionError("browser errors:\n" + "\n".join(errors))
    print(f"Docs Home current-route gate passed; capture: {OUTPUT}")


if __name__ == "__main__":
    run()
