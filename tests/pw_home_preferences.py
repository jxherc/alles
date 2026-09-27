"""Old browser Home choices import once without replacing newer server customization."""

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

        invalid = browser.new_context(service_workers="block", reduced_motion="reduce")
        invalid.add_init_script("localStorage.setItem('alles-home-order', '{\"bad\":true}')")
        invalid_page = invalid.new_page()
        invalid_imports: list[str] = []
        invalid_page.on(
            "request",
            lambda request: (
                invalid_imports.append(request.url)
                if request.url.endswith("/api/today/preferences/import-legacy")
                else None
            ),
        )
        invalid_page.goto(base, wait_until="networkidle")
        if invalid_page.locator("#setup-wizard").is_visible():
            invalid_page.locator("#setup-skip").click()
            invalid_page.locator("#setup-wizard").wait_for(state="hidden")
        expect(invalid_page.locator("#today-view")).to_be_visible()
        expect(invalid_page.locator("#today-status")).to_contain_text("customization")
        assert not invalid_imports, invalid_imports
        settings_file = data / "settings.json"
        if settings_file.exists():
            assert "today_layout" not in json.loads(settings_file.read_text("utf-8"))
        assert invalid_page.evaluate("localStorage.getItem('alles-home-order')") == '{"bad":true}'
        invalid.close()

        order = ["watch", "journal", "photos", "plan", "files"]
        hidden = [
            "files",
            "inbox",
            "library",
            "health",
            "finance",
            "vault",
            "activity",
            "system",
            "days",
        ]
        desktop = browser.new_context(
            viewport={"width": 1440, "height": 900},
            reduced_motion="reduce",
            service_workers="block",
        )
        desktop.add_init_script(
            f"localStorage.setItem('alles-home-order', {json.dumps(json.dumps(order))});"
            f"localStorage.setItem('alles-home-hidden', {json.dumps(json.dumps(hidden))});"
        )
        page = desktop.new_page()
        page.set_default_timeout(15_000)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        page.goto(base, wait_until="networkidle")
        expect(page.locator("#today-view")).to_be_visible()
        expected = ["system", "wiki", "files", "plan"]
        pins = page.locator("#today-sections .today-shortcut")
        expect(pins).to_have_count(len(expected))
        assert pins.evaluate_all("items => items.map(item => item.dataset.view)") == expected
        saved = desktop.request.get(f"{base}/api/today/preferences")
        assert saved.ok and saved.json()["shortcuts"] == expected, saved.text()
        assert page.evaluate("localStorage.getItem('alles-home-order')") == json.dumps(order)
        assert page.evaluate("localStorage.getItem('alles-home-hidden')") == json.dumps(hidden)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert not errors, errors
        page.screenshot(path=str(output / "home-preferences-desktop.png"), full_page=True)
        desktop.close()

        phone = browser.new_context(
            viewport={"width": 390, "height": 900},
            is_mobile=True,
            has_touch=True,
            reduced_motion="reduce",
            service_workers="block",
        )
        phone.add_init_script("localStorage.setItem('alles-home-hidden', '[\"plan\",\"wiki\"]')")
        page = phone.new_page()
        page.set_default_timeout(15_000)
        page.goto(base, wait_until="networkidle")
        expect(page.locator("#today-view")).to_be_visible()
        pins = page.locator("#today-sections .today-shortcut")
        expect(pins).to_have_count(len(expected))
        assert pins.evaluate_all("items => items.map(item => item.dataset.view)") == expected
        current = phone.request.put(
            f"{base}/api/today/preferences", data={"shortcuts": ["vault"], "density": "compact"}
        )
        assert current.ok, current.text()
        page.reload(wait_until="networkidle")
        expect(page.locator("#today-sections .today-shortcut")).to_have_count(1)
        assert page.locator("#today-sections .today-shortcut").get_attribute("data-view") == "vault"
        assert phone.request.get(f"{base}/api/today/preferences").json()["shortcuts"] == ["vault"]
        pin = page.locator("#today-sections .today-shortcut")
        box = pin.bounding_box()
        assert box and box["height"] >= 44, box
        pin.focus()
        expect(pin).to_be_focused()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.screenshot(path=str(output / "home-preferences-phone.png"), full_page=True)
        phone.close()
        browser.close()


if __name__ == "__main__":
    run()
